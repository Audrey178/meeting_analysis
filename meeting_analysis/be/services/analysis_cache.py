"""Cache kết quả phân tích v3 theo nội dung request (dùng ở ``services/pipeline_v3.py``).

Một bản phân tích có khoá ``analysis_key`` = hash(transcript chuẩn hoá + fingerprint pipeline) và
gồm nhiều mục lưu riêng (dict JSON): ``base`` (lượt nói, chủ đề, nhãn) và mỗi document kết quả
(tên ``<document>@<hash đầu vào riêng của document>``).
Module này không biết nội dung các mục; cách tính và ghép chúng nằm ở ``pipeline_v3``.

``AnalysisCache`` dựa vào một backend lo ba việc:
- lưu mục kèm version tăng dần theo bản phân tích (response mang version lớn nhất nó chứa, để
  frontend bỏ response cũ hơn cái đang hiển thị);
- khoá các đoạn đọc-ghi cần nhất quán;
- chạy-một-lần: request trùng chờ lần tính đang chạy thay vì tính thêm lần nữa.

Backend chọn theo ``V3_CACHE`` (``build_analysis_backend``):
    redis (mặc định)  ``RedisAnalysisBackend``: mỗi bản phân tích là một hash Redis có TTL
                      (``V3_CACHE_TTL_SECONDS``); version, khoá và chạy-một-lần cũng nằm trên
                      Redis nên đúng cả khi chạy nhiều worker/instance. Redis chạy bằng
                      ``docker compose up -d redis`` (``docker-compose.yml``), địa chỉ ở
                      ``V3_CACHE_REDIS_URL``.
    disk              file JSON ``<V3_CACHE_DIR>/<key>/<mục>.json``; không tự dọn.
    memory            trong tiến trình, tối đa ``V3_CACHE_MAX_ANALYSES`` bản (LRU).
    off               không lưu; request nào cũng tính lại từ đầu.
Ba chế độ sau dùng ``LocalAnalysisBackend``: khoá, version và chạy-một-lần nằm trong tiến
trình nên chỉ đúng với uvicorn một worker.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping
from concurrent.futures import Future
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any, Protocol, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Khoá đi vào đường dẫn file/tên khoá Redis, nên mọi chỗ nhận khoá từ ngoài đều kiểm theo mẫu này.
ANALYSIS_KEY_PATTERN = r"^[0-9a-f]{32}$"
_ANALYSIS_KEY_RE = re.compile(ANALYSIS_KEY_PATTERN)
# Tên mục: ``base`` hoặc ``<document>@<16 hex>`` (xem ``pipeline_v3.document_entry_name``).
_ENTRY_NAME_RE = re.compile(r"^[a-z_]+(@[0-9a-f]{16})?$")
_LOCK_STRIPES = 64
_SKIPPED_DIRS = frozenset({"tests", "__pycache__"})
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_DEFAULT_TTL_SECONDS = 7 * 24 * 3600


class CacheUnavailableError(Exception):
    """Không dùng được cache: Redis không kết nối được, chưa cài ``redis``, hoặc khoá bị giữ quá lâu."""


def make_analysis_key(payload: Mapping[str, Any], fingerprint: str) -> str:
    """Khoá của một bản phân tích: sha256 của payload chuẩn hoá cùng fingerprint pipeline.

    Không dùng ``meeting_id``/``revision_id`` làm khoá: transcript xuất từ STT không có hai
    trường này và được gán chung ``stt-export``/``export-0``.

    Đầu vào: payload - ``AnalyzeV3Request.model_dump()``; fingerprint - ``fingerprint_pipeline``.
    Đầu ra: 32 ký tự hex.
    """

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{fingerprint}\n{canonical}".encode("utf-8")).hexdigest()[:32]


def fingerprint_pipeline(sources: Iterable[Path], env_names: Iterable[str], *, root: Path) -> str:
    """Hash những gì quyết định kết quả ngoài request: mã nguồn, cấu hình và biến môi trường.

    File ``.py``/``.json`` được hash theo nội dung, nên sửa prompt thì cache cũ tự hết hiệu
    lực kể cả khi chưa commit; checkpoint ``.pt`` chỉ theo kích thước + thời điểm sửa. Bỏ qua
    thư mục ``tests`` và ``__pycache__``. ``env_names`` chỉ nên gồm tên model/endpoint/cấu
    hình, không gồm khoá API.

    Đầu vào: sources - file hoặc thư mục; env_names - tên biến môi trường; root - gốc repo
        (đường dẫn được hash theo dạng tương đối với gốc này).
    Đầu ra: chuỗi hex.
    """

    digest = hashlib.sha256()
    for path in sorted(set(_iter_source_files(sources, root))):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        if path.suffix == ".pt":
            stat = path.stat()
            digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
        else:
            digest.update(path.read_bytes())
    for name in sorted(env_names):
        digest.update(f"{name}={os.environ.get(name, '')}".encode("utf-8"))
    return digest.hexdigest()


def _iter_source_files(sources: Iterable[Path], root: Path) -> Iterator[Path]:
    """Các file ``.py``/``.json``/``.pt`` dưới ``sources`` (bỏ ``tests``, ``__pycache__``)."""

    for source in sources:
        if source.is_file():
            yield source
            continue
        if not source.is_dir():
            continue
        for path in source.rglob("*"):
            if (
                path.suffix in (".py", ".json", ".pt")
                and path.is_file()
                and not _SKIPPED_DIRS.intersection(path.relative_to(root).parts)
            ):
                yield path


def _checked_key(key: str) -> str:
    """Trả lại ``key`` nếu đúng dạng ``ANALYSIS_KEY_PATTERN``.

    Lỗi: ValueError nếu sai dạng (chặn khoá kiểu ``../..`` đi vào đường dẫn file/tên khoá Redis).
    """

    if not _ANALYSIS_KEY_RE.fullmatch(key):
        raise ValueError(f"analysis_key không hợp lệ: {key!r}")
    return key


# ----- Nơi lưu thuần (dùng với LocalAnalysisBackend) -----


class AnalysisStore(Protocol):
    """Nơi lưu các mục (dict JSON) của từng bản phân tích."""

    def load(self, key: str, name: str) -> dict | None:
        """Mục ``name`` của bản ``key``, None nếu chưa có."""

    def load_all(self, key: str) -> dict[str, dict]:
        """Mọi mục đang lưu của bản ``key`` (tên mục -> mục)."""

    def save(self, key: str, name: str, entry: dict) -> None:
        """Ghi (đè) mục ``name`` của bản ``key``."""


class NullAnalysisStore:
    """Không lưu gì (``V3_CACHE=off``): request nào cũng tính lại từ đầu."""

    def load(self, key: str, name: str) -> dict | None:
        return None

    def load_all(self, key: str) -> dict[str, dict]:
        return {}

    def save(self, key: str, name: str, entry: dict) -> None:
        return None


class InMemoryAnalysisStore:
    """Lưu trong tiến trình (``V3_CACHE=memory`` và trong test), tối đa ``max_analyses`` bản (LRU).

    Mục được chép qua JSON khi ghi và khi đọc, giống nơi lưu file: dữ liệu phải serialize được,
    và người gọi sửa dict trả về không làm hỏng bản đã lưu.

    Đầu vào khi tạo: max_analyses - số bản phân tích giữ lại; bản dùng lâu nhất bị bỏ trước.
    """

    def __init__(self, max_analyses: int = 32) -> None:
        if max_analyses < 1:
            raise ValueError("max_analyses phải >= 1")
        self._max_analyses = max_analyses
        self._analyses: OrderedDict[str, dict[str, str]] = OrderedDict()
        self._lock = threading.Lock()

    def load(self, key: str, name: str) -> dict | None:
        with self._lock:
            entries = self._analyses.get(key)
            if entries is None:
                return None
            self._analyses.move_to_end(key)
            raw = entries.get(name)
        return json.loads(raw) if raw is not None else None

    def load_all(self, key: str) -> dict[str, dict]:
        with self._lock:
            entries = dict(self._analyses.get(key, {}))
        return {name: json.loads(raw) for name, raw in entries.items()}

    def save(self, key: str, name: str, entry: dict) -> None:
        raw = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            self._analyses.setdefault(key, {})[name] = raw
            self._analyses.move_to_end(key)
            while len(self._analyses) > self._max_analyses:
                self._analyses.popitem(last=False)


class JsonFileAnalysisStore:
    """Mỗi mục là một file JSON ``<root>/<key>/<name>.json`` (``V3_CACHE=disk``).

    Ghi qua file tạm rồi ``os.replace``, nên không ai đọc phải file đang ghi dở. File hỏng hoặc
    không đọc được thì coi như chưa có (sẽ tính lại). Không tự dọn: xoá ``root`` để giải phóng chỗ.

    Đầu vào khi tạo: root - thư mục gốc của cache.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def load(self, key: str, name: str) -> dict | None:
        return self._read(self._path(key, name))

    def load_all(self, key: str) -> dict[str, dict]:
        folder = self._root / _checked_key(key)
        if not folder.is_dir():
            return {}
        entries = {}
        for path in folder.glob("*.json"):
            entry = self._read(path)
            if entry is not None:
                entries[path.stem] = entry
        return entries

    def save(self, key: str, name: str, entry: dict) -> None:
        path = self._path(key, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(entry, handle, ensure_ascii=False)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def _path(self, key: str, name: str) -> Path:
        if not _ENTRY_NAME_RE.fullmatch(name):
            raise ValueError(f"tên mục cache không hợp lệ: {name!r}")
        return self._root / _checked_key(key) / f"{name}.json"

    @staticmethod
    def _read(path: Path) -> dict | None:
        try:
            with path.open(encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning("Bỏ qua mục cache không đọc được %s: %s", path, exc)
            return None


class SingleFlight:
    """Gộp các lần tính trùng: trong lúc một lần tính ``name`` đang chạy, lời gọi khác cùng
    ``name`` chờ và nhận chung kết quả (hoặc cùng lỗi) thay vì tính thêm lần nữa."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[Hashable, Future] = {}

    def run(self, name: Hashable, compute: Callable[[], T]) -> T:
        """Chạy ``compute`` nếu chưa có lần tính ``name`` nào đang chạy, không thì chờ lần đó.

        Đầu vào: name - định danh lần tính; compute - hàm tính.
        Đầu ra: kết quả của ``compute`` (của lần này hoặc lần đang chạy).
        Lỗi: lỗi mà ``compute`` raise, cho cả người tính lẫn người chờ.
        """

        with self._lock:
            future = self._running.get(name)
            is_leader = future is None
            if is_leader:
                future = Future()
                self._running[name] = future
        if not is_leader:
            return future.result()
        try:
            result = compute()
        except BaseException as exc:
            future.set_exception(exc)
            raise
        else:
            future.set_result(result)
            return result
        finally:
            with self._lock:
                del self._running[name]


# ----- Backend: nơi lưu + version + khoá + chạy-một-lần -----


class AnalysisBackend(Protocol):
    """Lưu mục có version, khoá theo bản phân tích và chạy-một-lần (khoá đã được kiểm dạng)."""

    def load(self, key: str, name: str) -> dict | None:
        """Mục ``name`` của bản ``key`` (có ``version``), None nếu chưa có."""

    def version(self, key: str, name: str) -> int | None:
        """Version của mục ``name`` đang lưu, None nếu chưa có."""

    def save(self, key: str, name: str, entry: dict) -> dict:
        """Ghi ``entry`` với version mới, lớn hơn mọi version đã cấp cho bản ``key``; trả bản đã gắn version."""

    def lock(self, key: str) -> AbstractContextManager[None]:
        """Khoá các đoạn đọc-ghi cần nhất quán của bản ``key`` (gọi lồng trong cùng luồng được)."""

    def run_once(self, key: str, name: Hashable, compute: Callable[[], T]) -> T:
        """Chạy ``compute`` sao cho cùng (``key``, ``name``) không có hai lần tính chạy song song."""


class LocalAnalysisBackend:
    """Backend trong một tiến trình quanh một ``AnalysisStore`` (``V3_CACHE`` = disk | memory | off).

    Khoá là ``RLock`` theo bản phân tích, version đọc từ nơi lưu một lần mỗi khoá rồi giữ trong
    tiến trình, chạy-một-lần bằng ``SingleFlight`` (người chờ nhận chung kết quả hoặc lỗi). Chỉ
    đúng với uvicorn một worker.

    Đầu vào khi tạo: store - nơi lưu.
    """

    def __init__(self, store: AnalysisStore) -> None:
        self._store = store
        self._flights = SingleFlight()
        self._locks = tuple(threading.RLock() for _ in range(_LOCK_STRIPES))
        self._versions: dict[str, dict[str, int]] = {}

    def load(self, key: str, name: str) -> dict | None:
        return self._store.load(key, name)

    def version(self, key: str, name: str) -> int | None:
        with self.lock(key):
            return self._index(key).get(name)

    def save(self, key: str, name: str, entry: dict) -> dict:
        """Lỗi ghi file chỉ được ghi log: response vẫn dùng mục vừa tính, lần sau tính lại."""

        with self.lock(key):
            index = self._index(key)
            stamped = {**entry, "version": max(index.values(), default=0) + 1}
            try:
                self._store.save(key, name, stamped)
            except OSError as exc:
                logger.warning("Không lưu được mục cache %s/%s: %s", key, name, exc)
                return stamped
            index[name] = stamped["version"]
            return stamped

    def lock(self, key: str) -> threading.RLock:
        return self._locks[int(key, 16) % len(self._locks)]

    def run_once(self, key: str, name: Hashable, compute: Callable[[], T]) -> T:
        return self._flights.run((key, name), compute)

    def _index(self, key: str) -> dict[str, int]:
        """Version đang lưu của từng mục; đọc nơi lưu một lần cho mỗi khoá. Gọi khi giữ ``lock(key)``."""

        index = self._versions.get(key)
        if index is None:
            index = {
                name: entry["version"]
                for name, entry in self._store.load_all(key).items()
                if isinstance(entry.get("version"), int)
            }
            self._versions[key] = index
        return index


# Ghi một mục: tăng bộ đếm version của bản phân tích, ghi dữ liệu + version rồi gia hạn TTL, trong
# một script để không ai đọc được dữ liệu mới đi với version cũ (hoặc ngược lại).
_REDIS_SAVE_SCRIPT = """
local version = redis.call('HINCRBY', KEYS[1], '__version__', 1)
redis.call('HSET', KEYS[1], 'data:' .. ARGV[1], ARGV[2], 'version:' .. ARGV[1], version)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return version
"""


@contextmanager
def _redis_errors(message: str = "Redis lỗi") -> Iterator[None]:
    """Đổi lỗi kết nối/timeout của Redis thành ``CacheUnavailableError`` (router trả 503)."""

    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import TimeoutError as RedisTimeoutError

    try:
        yield
    except (RedisConnectionError, RedisTimeoutError) as exc:
        raise CacheUnavailableError(f"{message}: {exc}") from exc


def _release_quietly(lock) -> None:
    """Nhả lock Redis; lock đã hết hạn hoặc Redis lỗi thì chỉ ghi log (kết quả đã tính vẫn dùng được)."""

    from redis.exceptions import LockError, RedisError

    try:
        lock.release()
    except LockError:
        logger.warning("Khoá cache %s đã hết hạn trước khi nhả", lock.name)
    except RedisError as exc:
        logger.warning("Không nhả được khoá cache %s: %s", lock.name, exc)


@contextmanager
def _keep_lock_alive(lock, seconds: float) -> Iterator[None]:
    """Gia hạn ``lock`` (mỗi ``seconds``/3 giây) trong lúc khối lệnh chạy.

    Lần tính có thể dài hơn thời hạn khoá (gọi LLM nhiều phút); nếu worker chết thì không ai
    gia hạn nữa và khoá tự hết hạn sau ``seconds`` giây.
    """

    from redis.exceptions import LockError, RedisError

    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(seconds / 3):
            try:
                lock.extend(seconds, replace_ttl=True)
            except LockError:
                logger.warning("Mất khoá chạy-một-lần %s; worker khác có thể tính trùng", lock.name)
                return
            except RedisError as exc:
                logger.warning("Không gia hạn được khoá %s: %s", lock.name, exc)

    renewer = threading.Thread(target=renew, name="v3-cache-lock-renew", daemon=True)
    renewer.start()
    try:
        yield
    finally:
        stop.set()
        renewer.join()


def _flight_name(name: Hashable) -> str:
    """Tên lần tính trong khoá Redis: ``("assignments", 5)`` -> ``"assignments@5"``."""

    return "@".join(str(part) for part in name) if isinstance(name, tuple) else str(name)


class RedisAnalysisBackend:
    """Backend trên Redis (``V3_CACHE=redis``), đúng cả khi nhiều worker/instance dùng chung.

    Mỗi bản phân tích là một hash ``<prefix><key>`` gồm ``data:<mục>`` (JSON), ``version:<mục>``
    và bộ đếm ``__version__``; cả hash chung một TTL, gia hạn mỗi lần ghi, nên hết hạn cùng nhau.
    Khoá đọc-ghi là lock ``<prefix><key>:lock``. Chạy-một-lần là lock
    ``<prefix><key>:flight:<tên>`` được gia hạn trong lúc tính; người chờ chạy ``compute`` sau
    khi lock được nhả, nên ``compute`` phải tự xem lại cache trước khi tính (``pipeline_v3``
    dùng kết quả vừa xuất hiện trong lúc chờ).

    Đầu vào khi tạo:
        client: ``redis.Redis``.
        ttl_seconds: thời gian giữ một bản phân tích kể từ lần ghi cuối.
        prefix: tiền tố tên khoá Redis.
        lock_seconds: thời hạn (và thời gian chờ tối đa) của khoá đọc-ghi.
        flight_lock_seconds: thời hạn của khoá chạy-một-lần, gia hạn liên tục trong lúc tính.
    """

    def __init__(
        self,
        client,
        *,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        prefix: str = "meeting_analysis:v3:",
        lock_seconds: float = 30,
        flight_lock_seconds: float = 60,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("ttl_seconds phải >= 1")
        self._client = client
        self._ttl_seconds = int(ttl_seconds)
        self._prefix = prefix
        self._lock_seconds = lock_seconds
        self._flight_lock_seconds = flight_lock_seconds
        self._save_script = client.register_script(_REDIS_SAVE_SCRIPT)
        self._held = threading.local()

    @classmethod
    def from_url(cls, url: str, **kwargs) -> RedisAnalysisBackend:
        """Kết nối tới ``url`` (kiểm bằng PING) rồi dựng backend.

        Lỗi: CacheUnavailableError nếu chưa cài ``redis`` hoặc không kết nối được.
        """

        try:
            import redis
        except ImportError as exc:
            raise CacheUnavailableError("V3_CACHE=redis cần gói redis (pip install redis)") from exc
        client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=10, health_check_interval=30)
        with _redis_errors(f"Không kết nối được Redis tại {url} (chạy `docker compose up -d redis`?)"):
            client.ping()
        return cls(client, **kwargs)

    def load(self, key: str, name: str) -> dict | None:
        with _redis_errors():
            data, version = self._client.hmget(self._hash(key), f"data:{name}", f"version:{name}")
        if data is None or version is None:
            return None
        return {**json.loads(data), "version": int(version)}

    def version(self, key: str, name: str) -> int | None:
        with _redis_errors():
            value = self._client.hget(self._hash(key), f"version:{name}")
        return int(value) if value is not None else None

    def save(self, key: str, name: str, entry: dict) -> dict:
        if not _ENTRY_NAME_RE.fullmatch(name):
            raise ValueError(f"tên mục cache không hợp lệ: {name!r}")
        data = json.dumps({field: value for field, value in entry.items() if field != "version"}, ensure_ascii=False)
        with _redis_errors():
            version = self._save_script(keys=[self._hash(key)], args=[name, data, self._ttl_seconds])
        return {**entry, "version": int(version)}

    @contextmanager
    def lock(self, key: str) -> Iterator[None]:
        held = self._held_keys()
        if key in held:  # đã giữ khoá này trong luồng hiện tại (gọi lồng)
            yield
            return
        lock = self._client.lock(
            f"{self._hash(key)}:lock", timeout=self._lock_seconds, blocking_timeout=self._lock_seconds
        )
        with _redis_errors():
            acquired = lock.acquire()
        if not acquired:
            raise CacheUnavailableError(f"Chờ khoá cache của bản phân tích {key} quá {self._lock_seconds}s")
        held.add(key)
        try:
            yield
        finally:
            held.discard(key)
            _release_quietly(lock)

    def run_once(self, key: str, name: Hashable, compute: Callable[[], T]) -> T:
        # thread_local=False: luồng gia hạn cần đọc token của lock do luồng này lấy.
        lock = self._client.lock(
            f"{self._hash(key)}:flight:{_flight_name(name)}",
            timeout=self._flight_lock_seconds,
            sleep=0.2,
            thread_local=False,
        )
        with _redis_errors():
            lock.acquire()  # chờ lần tính cùng tên đang chạy ở bất kỳ worker nào
        try:
            with _keep_lock_alive(lock, self._flight_lock_seconds):
                return compute()
        finally:
            _release_quietly(lock)

    def _hash(self, key: str) -> str:
        return f"{self._prefix}{_checked_key(key)}"

    def _held_keys(self) -> set[str]:
        """Các bản phân tích mà luồng hiện tại đang giữ khoá đọc-ghi."""

        held = getattr(self._held, "keys", None)
        if held is None:
            held = self._held.keys = set()
        return held


def build_analysis_backend(default_dir: Path) -> AnalysisBackend:
    """Backend theo biến môi trường (xem docstring module).

    Đầu vào: default_dir - thư mục cache khi ``V3_CACHE=disk`` mà không có ``V3_CACHE_DIR``.
    Đầu ra: AnalysisBackend.
    Lỗi: ValueError nếu ``V3_CACHE`` không phải redis | disk | memory | off;
        CacheUnavailableError nếu chọn redis mà không kết nối được.
    """

    mode = os.environ.get("V3_CACHE", "redis").strip().lower()
    if mode == "redis":
        return RedisAnalysisBackend.from_url(
            os.environ.get("V3_CACHE_REDIS_URL", "").strip() or _DEFAULT_REDIS_URL,
            ttl_seconds=int(os.environ.get("V3_CACHE_TTL_SECONDS", "").strip() or _DEFAULT_TTL_SECONDS),
        )
    if mode == "off":
        return LocalAnalysisBackend(NullAnalysisStore())
    if mode == "memory":
        return LocalAnalysisBackend(InMemoryAnalysisStore(int(os.environ.get("V3_CACHE_MAX_ANALYSES", "32"))))
    if mode == "disk":
        return LocalAnalysisBackend(
            JsonFileAnalysisStore(Path(os.environ.get("V3_CACHE_DIR", "").strip() or default_dir))
        )
    raise ValueError(f"V3_CACHE không hợp lệ: {mode!r} (redis | disk | memory | off)")


class AnalysisCache:
    """Cache dùng chung của ứng dụng: khoá theo nội dung request + một backend (một instance cho cả app).

    Đầu vào khi tạo:
        backend: ``LocalAnalysisBackend`` hoặc ``RedisAnalysisBackend``.
        fingerprint: ``fingerprint_pipeline``; đổi mã nguồn hoặc model thì khoá đổi theo, nên
            kết quả cũ không bị dùng lại.
    """

    def __init__(self, backend: AnalysisBackend, fingerprint: str = "") -> None:
        self._backend = backend
        self._fingerprint = fingerprint

    def key_for(self, payload: Mapping[str, Any]) -> str:
        """Khoá của bản phân tích ứng với ``payload`` (``make_analysis_key``)."""

        return make_analysis_key(payload, self._fingerprint)

    def lock(self, key: str) -> AbstractContextManager[None]:
        """Khoá của bản ``key``: giữ khi ghi có điều kiện, và khi cần đọc nhiều mục nhất quán."""

        return self._backend.lock(_checked_key(key))

    def load(self, key: str, name: str) -> dict | None:
        """Mục ``name`` của bản ``key`` (có ``version``), None nếu chưa có."""

        return self._backend.load(_checked_key(key), name)

    def version(self, key: str, name: str) -> int | None:
        """Version của mục ``name`` đang lưu, None nếu chưa có."""

        return self._backend.version(_checked_key(key), name)

    def save(self, key: str, name: str, entry: dict) -> dict:
        """Ghi ``entry`` với version mới (lớn hơn mọi mục của bản ``key``).

        Đầu vào: key, name - bản và mục; entry - dict JSON.
        Đầu ra: bản sao ``entry`` có thêm ``version``.
        """

        return self._backend.save(_checked_key(key), name, entry)

    def run_once(self, key: str, name: Hashable, compute: Callable[[], T]) -> T:
        """Chạy lần tính ``name`` của bản ``key`` sao cho không có hai lần cùng tên chạy song song.

        Backend trong tiến trình cho người chờ nhận chung kết quả; backend Redis cho người chờ
        chạy ``compute`` sau khi lần đang chạy xong, nên ``compute`` phải tự xem lại cache trước.
        ``name`` phải phân biệt mọi thứ làm kết quả khác nhau (vd. phần + version nền).
        """

        return self._backend.run_once(_checked_key(key), name, compute)


__all__ = [
    "ANALYSIS_KEY_PATTERN",
    "AnalysisBackend",
    "AnalysisCache",
    "AnalysisStore",
    "CacheUnavailableError",
    "InMemoryAnalysisStore",
    "JsonFileAnalysisStore",
    "LocalAnalysisBackend",
    "NullAnalysisStore",
    "RedisAnalysisBackend",
    "SingleFlight",
    "build_analysis_backend",
    "fingerprint_pipeline",
    "make_analysis_key",
]
