"""Test đơn vị cho ``services/analysis_cache.py``: nơi lưu (file JSON, bộ nhớ), version, khoá theo
nội dung request, fingerprint pipeline, chạy-một-lần, và backend Redis (fakeredis, hoặc Redis thật
khi đặt ``V3_TEST_REDIS_URL``; xem ``conftest.py``)."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from services.analysis_cache import (
    AnalysisCache,
    CacheUnavailableError,
    InMemoryAnalysisStore,
    JsonFileAnalysisStore,
    LocalAnalysisBackend,
    NullAnalysisStore,
    RedisAnalysisBackend,
    SingleFlight,
    build_analysis_backend,
    fingerprint_pipeline,
    make_analysis_key,
)

KEY = "0123456789abcdef0123456789abcdef"


def test_json_store_round_trips_and_leaves_no_temp_files(tmp_path: Path) -> None:
    store = JsonFileAnalysisStore(tmp_path)

    store.save(KEY, "base", {"turns": ["Chị Mai: đồng ý"], "version": 1})
    store.save(KEY, "decisions", {"data": [], "version": 2})

    assert store.load(KEY, "base") == {"turns": ["Chị Mai: đồng ý"], "version": 1}
    assert store.load(KEY, "assignments") is None
    assert set(store.load_all(KEY)) == {"base", "decisions"}
    assert sorted(path.name for path in (tmp_path / KEY).iterdir()) == ["base.json", "decisions.json"]


def test_json_store_treats_corrupt_file_as_missing(tmp_path: Path) -> None:
    store = JsonFileAnalysisStore(tmp_path)
    (tmp_path / KEY).mkdir()
    (tmp_path / KEY / "base.json").write_text("{không phải json", encoding="utf-8")

    assert store.load(KEY, "base") is None
    assert store.load_all(KEY) == {}


@pytest.mark.parametrize("key", ["../../etc", "0123456789ABCDEF0123456789ABCDEF", "abc"])
def test_store_rejects_malformed_keys(tmp_path: Path, key: str) -> None:
    with pytest.raises(ValueError):
        JsonFileAnalysisStore(tmp_path).save(key, "base", {})


def test_json_store_rejects_malformed_entry_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        JsonFileAnalysisStore(tmp_path).save(KEY, "../base", {})


def test_memory_store_evicts_least_recently_used_and_copies_entries() -> None:
    store = InMemoryAnalysisStore(max_analyses=2)
    first, second, third = (f"{index:032x}" for index in range(3))
    store.save(first, "base", {"items": [1]})
    store.save(second, "base", {"items": [2]})
    store.load(first, "base")  # first vừa được dùng, second thành cũ nhất

    store.save(third, "base", {"items": [3]})
    loaded = store.load(first, "base")
    loaded["items"].append(99)

    assert store.load(second, "base") is None
    assert store.load(first, "base") == {"items": [1]}


def test_cache_versions_increase_across_entries_and_survive_restart(tmp_path: Path) -> None:
    cache = AnalysisCache(LocalAnalysisBackend(JsonFileAnalysisStore(tmp_path)))
    base = cache.save(KEY, "base", {"turns": []})
    part = cache.save(KEY, "decisions", {"data": []})

    restarted = AnalysisCache(LocalAnalysisBackend(JsonFileAnalysisStore(tmp_path)))
    later = restarted.save(KEY, "decisions", {"data": [1]})

    assert (base["version"], part["version"], later["version"]) == (1, 2, 3)
    assert restarted.version(KEY, "base") == 1
    assert restarted.load(KEY, "decisions") == later


def test_cache_keeps_serving_when_store_cannot_write() -> None:
    class FullDisk(NullAnalysisStore):
        def save(self, key, name, entry):
            raise OSError("No space left on device")

    cache = AnalysisCache(LocalAnalysisBackend(FullDisk()))

    entry = cache.save(KEY, "base", {"turns": []})

    assert entry["version"] == 1
    assert cache.version(KEY, "base") is None  # không ghi được thì không coi là đã lưu


def test_analysis_key_depends_on_content_not_key_order() -> None:
    payload = {"items": [{"id": "1", "text": "Chốt."}], "chair": None, "meeting_date": None}

    key = make_analysis_key(payload, "fp")

    assert key == make_analysis_key(dict(reversed(list(payload.items()))), "fp")
    assert key != make_analysis_key({**payload, "chair": "Anh Tuấn"}, "fp")
    assert key != make_analysis_key(payload, "fp2")
    assert len(key) == 32


def test_fingerprint_follows_sources_and_env_but_skips_tests(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src" / "tests").mkdir(parents=True)
    prompt = tmp_path / "src" / "prompts.py"
    prompt.write_text("PROMPT = 'v1'\n", encoding="utf-8")
    test_file = tmp_path / "src" / "tests" / "test_x.py"
    test_file.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("MODEL_NAME", "model-a")

    def fingerprint() -> str:
        return fingerprint_pipeline([tmp_path / "src"], ["MODEL_NAME"], root=tmp_path)

    original = fingerprint()
    test_file.write_text("x = 2\n", encoding="utf-8")
    assert fingerprint() == original
    prompt.write_text("PROMPT = 'v2'\n", encoding="utf-8")
    after_prompt = fingerprint()
    monkeypatch.setenv("MODEL_NAME", "model-b")

    assert after_prompt != original
    assert fingerprint() != after_prompt


def test_single_flight_shares_one_computation_and_its_error() -> None:
    flights, calls, release = SingleFlight(), [], threading.Event()

    def slow():
        calls.append(1)
        release.wait(5)
        return "kết quả"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(flights.run, "k", slow)
        time.sleep(0.1)
        second = pool.submit(flights.run, "k", slow)
        time.sleep(0.1)
        release.set()
        assert (first.result(), second.result()) == ("kết quả", "kết quả")
    assert len(calls) == 1

    def broken():
        raise RuntimeError("gateway down")

    with pytest.raises(RuntimeError):
        flights.run("k", broken)
    assert flights.run("k", lambda: "lần sau tính lại") == "lần sau tính lại"


def test_backend_is_chosen_from_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("V3_CACHE", "memory")
    assert isinstance(build_analysis_backend(tmp_path), LocalAnalysisBackend)
    monkeypatch.setenv("V3_CACHE", "disk")
    monkeypatch.setenv("V3_CACHE_DIR", str(tmp_path / "cache"))
    build_analysis_backend(tmp_path).save(KEY, "base", {})
    assert (tmp_path / "cache" / KEY / "base.json").is_file()
    monkeypatch.setenv("V3_CACHE", "off")
    assert build_analysis_backend(tmp_path).load(KEY, "base") is None
    monkeypatch.setenv("V3_CACHE", "redis")
    monkeypatch.setenv("V3_CACHE_REDIS_URL", "redis://127.0.0.1:1/0")  # không có server
    with pytest.raises(CacheUnavailableError, match="docker compose up -d redis"):
        build_analysis_backend(tmp_path)
    monkeypatch.setenv("V3_CACHE", "sqlite")
    with pytest.raises(ValueError):
        build_analysis_backend(tmp_path)


# ----- Backend Redis -----


def test_redis_backend_round_trips_with_versions_and_ttl(redis_connect, redis_prefix) -> None:
    client = redis_connect()
    backend = RedisAnalysisBackend(client, prefix=redis_prefix, ttl_seconds=3600)

    base = backend.save(KEY, "base", {"turns": ["Chị Mai: đồng ý"], "version": 99})
    part = backend.save(KEY, "decisions", {"data": []})

    assert (base["version"], part["version"]) == (1, 2)  # version cũ trong entry bị thay
    assert backend.load(KEY, "base") == {"turns": ["Chị Mai: đồng ý"], "version": 1}
    assert (backend.version(KEY, "decisions"), backend.version(KEY, "assignments")) == (2, None)
    assert backend.load(KEY, "assignments") is None
    assert 0 < client.ttl(f"{redis_prefix}{KEY}") <= 3600


def test_redis_backends_share_versions_across_workers(redis_connect, redis_prefix) -> None:
    worker_a = RedisAnalysisBackend(redis_connect(), prefix=redis_prefix)
    worker_b = RedisAnalysisBackend(redis_connect(), prefix=redis_prefix)

    first = worker_a.save(KEY, "base", {"turns": []})
    second = worker_b.save(KEY, "decisions", {"data": [1]})

    assert second["version"] == first["version"] + 1
    assert worker_a.load(KEY, "decisions") == second
    assert worker_b.version(KEY, "base") == first["version"]


def test_redis_lock_is_reentrant_and_excludes_other_workers(redis_connect, redis_prefix) -> None:
    worker_a = RedisAnalysisBackend(redis_connect(), prefix=redis_prefix)
    worker_b = RedisAnalysisBackend(redis_connect(), prefix=redis_prefix)
    waited = []

    def other_worker() -> None:
        started = time.monotonic()
        with worker_b.lock(KEY):
            waited.append(time.monotonic() - started)

    with worker_a.lock(KEY):
        with worker_a.lock(KEY):  # gọi lồng trong cùng luồng không tự chặn mình
            thread = threading.Thread(target=other_worker)
            thread.start()
            time.sleep(0.3)
        assert not waited  # worker kia vẫn đang chờ
    thread.join(5)

    assert len(waited) == 1 and waited[0] >= 0.25


def test_redis_run_once_lets_waiting_worker_reuse_result(redis_connect, redis_prefix) -> None:
    workers = [RedisAnalysisBackend(redis_connect(), prefix=redis_prefix) for _ in range(2)]
    computed = []

    def ensure(worker: RedisAnalysisBackend) -> dict:
        def compute() -> dict:
            cached = worker.load(KEY, "base")  # người chờ thấy kết quả của người vừa tính
            if cached is not None:
                return cached
            computed.append(1)
            time.sleep(0.3)
            return worker.save(KEY, "base", {"turns": ["x"]})

        return worker.run_once(KEY, "base", compute)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(ensure, workers))

    assert len(computed) == 1
    assert results[0] == results[1]


def test_redis_flight_lock_is_renewed_while_computing(redis_connect, redis_prefix) -> None:
    workers = [RedisAnalysisBackend(redis_connect(), prefix=redis_prefix, flight_lock_seconds=0.6) for _ in range(2)]
    spans = []

    def slow(worker: RedisAnalysisBackend) -> None:
        def compute() -> None:
            started = time.monotonic()
            time.sleep(1.5)  # lâu hơn hẳn thời hạn khoá 0.6s
            spans.append((started, time.monotonic()))

        worker.run_once(KEY, ("assignments", 1), compute)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(slow, workers[0])
        time.sleep(0.1)
        second = pool.submit(slow, workers[1])
        first.result(10)
        second.result(10)

    (start_a, end_a), (start_b, end_b) = sorted(spans)
    assert start_b >= end_a  # khoá được gia hạn nên lần tính thứ hai không chạy chồng


def test_redis_unreachable_is_reported_as_cache_unavailable() -> None:
    with pytest.raises(CacheUnavailableError):
        RedisAnalysisBackend.from_url("redis://127.0.0.1:1/0")
