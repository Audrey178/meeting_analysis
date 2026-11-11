"""Chạy pipeline (``src/pipeline/run.py``) cho API, qua cache.

Một bản phân tích gồm "nền" (bước 1-3: lượt nói, chủ đề, nhãn -- ``MeetingAnalyzer.prepare``) và
ba document tính trên nền đó (bước 4-6 -- ``MeetingAnalyzer.analyze``): Diễn biến, Kết luận, Giao
việc. Nền và từng document là các mục cache riêng, nên tính lại một document không đụng nền hay
document khác.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import sys
from collections.abc import Collection, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal

_BE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BE_DIR.parent
for _dir in (_BE_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

if TYPE_CHECKING:
    from src.pipeline.step2_segment.dialstart import DialStartSegmenter

from services.analysis_cache import (
    AnalysisCache,
    build_analysis_backend,
    fingerprint_pipeline,
)
from services.documents import MeetingContext, build_document, build_document_entry
from services.request_inputs import (
    read_attendee_roster,
    read_chair,
    read_meeting_date,
    read_task_agenda,
)
from src.pipeline.run import MeetingAnalyzer
from src.pipeline.shared.meeting_inputs.agenda import TaskAgenda
from src.pipeline.shared.schemas import AnalysisPart
from src.utils.contracts import SpeakerTurn, TopicLabel, TopicSegment

logger = logging.getLogger(__name__)


# Mã nguồn/cấu hình quyết định kết quả, đưa vào fingerprint của cache (đường dẫn so với gốc repo).
_FINGERPRINT_SOURCES = (
    "src",
    "be/services",
    "be/schemas.py",
    "configs",
    "experiments/dialstart",  # checkpoint DialSTART
)
# Biến môi trường quyết định kết quả: tên model, endpoint và cấu hình (không gồm khoá API).
_FINGERPRINT_ENV = (
    "MODEL_NAME",
    "OPENAI_BASE_URL",
    "VERIFIER_MODEL_NAME",
    "VERIFIER_BASE_URL",
    "VERIFIER_RESPONSE_MODE",
    "VERIFIER_THINKING",
    "TURN_ACT_MODEL",
    "OPENROUTER_DECISIONS_URL",
    "DIALSTART_CHECKPOINT",
    "DIALSTART_DEVICE",
    "V3_EXTRACT_ATTEMPTS",
    "V3_VERIFIER_MAX_TOOL_CALLS",
    "V3_CONSENSUS_MAX_ROUNDS",
)
_DEFAULT_CACHE_DIR = _REPO_ROOT / "outputs" / "v3_cache"

# Số lần làm lại khi nền bị request khác thay ngay trong lúc đang tính.
_MAX_BASE_ATTEMPTS = 3

DocumentKind = Literal["content", "decisions", "tasks"]
DOCUMENT_KINDS: tuple[DocumentKind, ...] = ("content", "decisions", "tasks")
_DOCUMENT_TITLES: dict[DocumentKind, str] = {"content": "Diễn biến", "decisions": "Kết luận", "tasks": "Giao việc"}
# Phần kết quả (``MeetingAnalyzer.analyze``) của từng document; Tiến độ chỉ có khi request có ``tasks``.
_PARTS_OF_DOCUMENT: dict[DocumentKind, tuple[AnalysisPart, ...]] = {
    "content": ("content",),
    "decisions": ("decisions",),
    "tasks": ("assignments", "progress"),
}
# Trường của request tạo nên transcript: khoá của bản phân tích (nền chung của mọi document).
_TRANSCRIPT_FIELDS = ("meeting_id", "items")
# Trường còn lại của request mà từng document phụ thuộc, đi vào tên mục cache của document.
# Content/Decisions không nhận ``tasks``: chúng chạy không có danh sách việc (danh sách việc
# nằm trong prompt của mọi agent, nên nhận vào thì kết quả đổi theo mà khoá không đổi).
_DOCUMENT_INPUT_FIELDS: dict[DocumentKind, tuple[str, ...]] = {
    "content": ("chair", "meeting_date", "attendees"),
    "decisions": ("chair", "meeting_date", "attendees"),
    "tasks": ("chair", "meeting_date", "attendees", "tasks"),
}


class PartReloadFailedError(Exception):
    """Chạy lại một document mà có chủ đề lỗi, trong khi bản đang lưu của nó đầy đủ: giữ bản cũ."""


class AnalysisConflictError(Exception):
    """Nền phân tích bị thay liên tục trong lúc tính (có request chạy lại toàn bộ song song)."""


def build_analysis_cache_v3() -> AnalysisCache:
    """Cache kết quả v3 theo ``V3_CACHE`` (xem ``analysis_cache.build_analysis_backend``; mặc định Redis).

    Fingerprint lấy từ mã nguồn, cấu hình và biến môi trường lúc dựng (một lần mỗi tiến trình;
    ``uvicorn --reload`` dựng lại sau mỗi lần sửa code).

    Đầu ra: AnalysisCache.
    """

    fingerprint = fingerprint_pipeline(
        (_REPO_ROOT / source for source in _FINGERPRINT_SOURCES), _FINGERPRINT_ENV, root=_REPO_ROOT
    )
    return AnalysisCache(build_analysis_backend(_DEFAULT_CACHE_DIR), fingerprint)


def transcript_payload(payload: Mapping) -> dict:
    """Phần transcript của request (``meeting_id``, ``items``): nguồn của khoá bản phân tích."""

    return {field: payload.get(field) for field in _TRANSCRIPT_FIELDS}


def document_entry_name(document: DocumentKind, payload: Mapping) -> str:
    """Tên mục cache của ``document``: ``"<document>@<16 hex>"``, hash từ các trường request nó phụ thuộc.

    Đầu vào: document - content | decisions | tasks; payload - ``AnalyzeV3Request.model_dump()``.
    Đầu ra: str ``"<document>@<16 hex>"``.
    """

    inputs = {field: payload.get(field) for field in _DOCUMENT_INPUT_FIELDS[document]}
    canonical = json.dumps(inputs, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return f"{document}@{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


def document_parts(document: DocumentKind, agenda: TaskAgenda | None) -> tuple[AnalysisPart, ...]:
    """Các phần kết quả của ``document``: Tiến độ chỉ có khi request có danh sách việc.

    Đầu vào: document; agenda - kết quả ``read_task_agenda``.
    Đầu ra: tuple phần.
    """

    return tuple(part for part in _PARTS_OF_DOCUMENT[document] if part != "progress" or agenda is not None)


def _transcript_items(payload: Mapping) -> list[dict]:
    """Mã gốc (giữ kiểu: số khi xuất từ STT) và ``speaker_id`` của từng item transcript, theo thứ tự.

    Lượt nói chỉ giữ mã item dạng chuỗi (``SpeakerTurn.source_items``); document trích dẫn bằng mã gốc.
    ``speaker_id`` lấy từ ``ref_id`` (mã người nói của bản xuất STT), thiếu thì từ trường ``speaker_id``;
    cùng thứ tự với ``SpeakerTurn.speaker_id`` của pipeline.
    """

    return [
        {"id": item.get("id", item.get("item_id")), "speaker_id": _first_ref_id(item.get("ref_id")) or item.get("speaker_id")}
        for item in payload.get("items") or ()
        if isinstance(item, Mapping)
    ]


def _first_ref_id(value: object) -> str | None:
    """Mã đầu tiên của ``ref_id`` (chuỗi hoặc mảng chuỗi), None nếu không có."""

    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return next((entry.strip() for entry in value if isinstance(entry, str) and entry.strip()), None)
    return None


def _now_iso() -> str:
    """Thời điểm hiện tại (UTC, ISO 8601) cho ``computed_at``."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_tuple(value):
    """List JSON (kể cả lồng nhau, vd. ``source_items``) đổi lại thành tuple như trong dataclass."""

    return tuple(_as_tuple(element) for element in value) if isinstance(value, list) else value


def _restore_dataclass(cls, data: Mapping):
    """Dựng lại dataclass phẳng (``SpeakerTurn``/``TopicSegment``/``TopicLabel``) từ dict JSON.

    Bỏ qua khoá không còn là trường của ``cls`` (vd. ``evidence_ids`` của lượt nói trong cache cũ).
    """

    fields = {field.name for field in dataclasses.fields(cls)}
    return cls(**{name: _as_tuple(value) for name, value in data.items() if name in fields})


@dataclasses.dataclass(frozen=True)
class _MeetingBase:
    """Nền chung của mọi document: mục ``base`` đã lưu (có ``version``) và đối tượng dựng từ nó.

    Các trường: entry - mục cache; turns, segments, labels - lượt nói, chủ đề, nhãn.
    """

    entry: dict
    turns: tuple[SpeakerTurn, ...]
    segments: tuple[TopicSegment, ...]
    labels: tuple[TopicLabel, ...]

    @property
    def version(self) -> int:
        return self.entry["version"]

    @classmethod
    def from_entry(cls, entry: dict) -> _MeetingBase:
        return cls(
            entry=entry,
            turns=tuple(_restore_dataclass(SpeakerTurn, turn) for turn in entry["turns"]),
            segments=tuple(_restore_dataclass(TopicSegment, segment) for segment in entry["segments"]),
            labels=tuple(_restore_dataclass(TopicLabel, label) for label in entry["labels"]),
        )


@dataclasses.dataclass(frozen=True)
class DocumentResult:
    """Kết quả một lần lấy document: nền và các mục document cùng nền.

    Các trường:
        key: analysis_key (khoá của nền).
        base_entry: mục ``base``.
        entries: document -> mục của nó.
        entry_names: document -> tên mục cache (``"<document>@<hash>"``).
        fresh: các document vừa tính trong request này (không lấy từ cache).
    """

    key: str
    base_entry: dict
    entries: dict[DocumentKind, dict]
    entry_names: dict[DocumentKind, str]
    fresh: frozenset[DocumentKind]


class _MeetingAnalysisRun:
    """Một request phân tích v3: lấy hoặc tính nền, rồi lấy hoặc tính từng document, đều qua cache.

    Ba bất biến:
    1. Mọi document trong một response được tính trên cùng một nền (cùng ranh giới chủ đề và nhãn).
    2. Mỗi mục của một bản phân tích có tối đa một lần tính đang chạy; request trùng chờ chung.
    3. Chỉ ghi cache khi tính xong; chạy lại một document mà lỗi thì bản đầy đủ đang lưu còn nguyên.

    Đầu vào khi tạo: payload - ``AnalyzeV3Request.model_dump()``; analyzer, cache - dùng chung
        của ứng dụng; segmenter - ``DialStartSegmenter`` cho bước cắt chủ đề.
    Lỗi: ValueError nếu danh sách tham dự hoặc danh sách việc sai dạng (kiểm trước mọi bước tính).
    """

    def __init__(
        self,
        payload: dict,
        *,
        analyzer: MeetingAnalyzer,
        cache: AnalysisCache,
        segmenter: DialStartSegmenter,
    ) -> None:
        self.roster = read_attendee_roster(payload)
        self.agenda = read_task_agenda(payload, self.roster)
        self.chair = read_chair(payload)
        self.payload = payload
        self.key = cache.key_for(transcript_payload(payload))
        self.entry_names = {document: document_entry_name(document, payload) for document in DOCUMENT_KINDS}
        self.analyzer = analyzer
        self.cache = cache
        self.segmenter = segmenter

    def execute(
        self,
        documents: Collection[DocumentKind],
        *,
        refresh_base: bool,
        refresh: Collection[DocumentKind],
    ) -> DocumentResult:
        """Các document ``documents`` trên cùng một nền, tính lại những gì được yêu cầu hoặc còn thiếu.

        Đầu vào: documents - document cần lấy; refresh_base - tính lại nền (cắt chủ đề + nhãn), mọi
            document trên nền cũ hết dùng được; refresh - document phải tính lại dù đã có.
        Đầu ra: DocumentResult.
        Lỗi: PartReloadFailedError, AnalysisConflictError; lỗi của bước cắt chủ đề
            (``LLMUpstreamError``, ``ValueError``).
        """

        force = frozenset(refresh)
        for _ in range(_MAX_BASE_ATTEMPTS):
            base = self._ensure_base(refresh=refresh_base)
            entries, fresh = self._ensure_documents(base, documents, force)
            result = self._latest(base, entries, fresh)
            if result is not None:
                return result
            # Request khác vừa tính lại nền: đọc lại theo nền mới; document của nền đó do chính
            # request kia tính (chờ chung qua ``run_once``).
            refresh_base, force = False, frozenset()
        raise AnalysisConflictError("Bản phân tích đang được chạy lại toàn bộ; thử lại sau.")

    def _ensure_base(self, *, refresh: bool) -> _MeetingBase:
        """Nền đã lưu, hoặc tính mới (``refresh`` hoặc chưa có)."""

        seen = self.cache.version(self.key, "base") or 0
        if not refresh:
            entry = self.cache.load(self.key, "base")
            if entry is not None:
                return _MeetingBase.from_entry(entry)
        newer_than = seen if refresh else 0
        return self.cache.run_once(self.key, "base", lambda: self._compute_base(newer_than))

    def _compute_base(self, newer_than: int) -> _MeetingBase:
        """Bước 1-3 (lượt nói, chủ đề, nhãn) rồi lưu làm nền.

        Trước khi tính, dùng luôn nền đã lưu có version > ``newer_than``: nền mà request khác vừa
        tính trong lúc request này chờ (backend Redis cho người chờ chạy hàm này sau người tính).

        Đầu vào: newer_than - 0 khi chỉ cần có nền; version nền lúc request bắt đầu khi ``refresh``.
        """

        entry = self.cache.load(self.key, "base")
        if entry is not None and entry["version"] > newer_than:
            return _MeetingBase.from_entry(entry)
        meeting = self.analyzer.prepare(self.payload, segmenter=self.segmenter)
        entry = self.cache.save(
            self.key,
            "base",
            {
                "meeting_id": meeting.meeting_id,
                "computed_at": _now_iso(),
                "items": _transcript_items(self.payload),
                "turns": [dataclasses.asdict(turn) for turn in meeting.turns],
                "segments": [dataclasses.asdict(segment) for segment in meeting.segments],
                "labels": [dataclasses.asdict(label) for label in meeting.labels],
            },
        )
        return _MeetingBase(entry, meeting.turns, meeting.segments, meeting.labels)

    def _ensure_documents(
        self, base: _MeetingBase, documents: Collection[DocumentKind], force: frozenset[str]
    ) -> tuple[dict[DocumentKind, dict], frozenset[DocumentKind]]:
        """Các document trên ``base``, song song: document trong ``force`` luôn tính lại, còn lại lấy cache.

        Document lỗi thì lỗi được raise sau khi các document kia xong (và đã lưu).

        Đầu ra: (document -> mục theo thứ tự ``documents``, các document vừa tính).
        """

        with ThreadPoolExecutor(max_workers=len(documents), thread_name_prefix="v3-doc") as pool:
            futures = {
                document: pool.submit(self._ensure_document, base, document, document in force)
                for document in documents
            }
            outcomes = {document: future.result() for document, future in futures.items()}
        entries = {document: entry for document, (entry, _) in outcomes.items()}
        fresh = frozenset(document for document, (_, computed) in outcomes.items() if computed)
        return entries, fresh

    def _ensure_document(self, base: _MeetingBase, document: DocumentKind, force: bool) -> tuple[dict, bool]:
        """Mục của ``document``: từ cache nếu dùng lại được và không bị ép tính lại.

        Đầu ra: (mục, True nếu vừa được tính).
        """

        name = self.entry_names[document]
        seen = self.cache.version(self.key, name) or 0
        if not force:
            entry = self._load_document(base, name)
            if entry is not None:
                return entry, False
        newer_than = seen if force else 0
        # Version nền nằm trong tên lần tính: lần tính lại nền không được chờ chung lần tính cùng
        # document trên nền cũ.
        return self.cache.run_once(
            self.key, (name, base.version), lambda: self._compute_document(base, document, newer_than, seen)
        )

    def _load_document(self, base: _MeetingBase, name: str) -> dict | None:
        """Mục đã lưu ``name`` nếu dùng lại được: cùng nền và không có chủ đề lỗi."""

        entry = self.cache.load(self.key, name)
        if entry is None or entry["base_version"] != base.version or entry["status"] != "ok":
            return None
        return entry

    def _compute_document(
        self, base: _MeetingBase, document: DocumentKind, newer_than: int, seen: int
    ) -> tuple[dict, bool]:
        """Tính ``document`` trên nhãn của ``base`` rồi lưu.

        Trước khi tính, dùng luôn mục dùng lại được có version > ``newer_than`` (request khác vừa
        tính trong lúc request này chờ, như ``_compute_base``). Không lưu nếu nền đã bị thay trong
        lúc tính (bất biến 1). Lần tính có chủ đề lỗi không được đè bản đầy đủ đang lưu trên cùng
        nền (bất biến 3): khi đó raise để giữ bản cũ.

        Đầu vào: newer_than - 0 khi chỉ cần có mục; version lúc request bắt đầu khi chạy lại;
            seen - version lúc request bắt đầu (mục mới hơn coi như vừa tính, không lấy từ cache).
        Đầu ra: (mục, True nếu vừa được tính).
        Lỗi: PartReloadFailedError.
        """

        name = self.entry_names[document]
        entry = self._load_document(base, name)
        if entry is not None and entry["version"] > newer_than:
            return entry, entry["version"] > seen
        parts = document_parts(document, self.agenda)
        report = self.analyzer.analyze(
            meeting_id=base.entry["meeting_id"],
            meeting_date=read_meeting_date(self.payload),
            chair=self.chair,
            turns=base.turns,
            segments=base.segments,
            attendee_roster=self.roster,
            task_agenda=self.agenda if document == "tasks" else None,
            parts=parts,
            labels=base.labels,
        )
        content = build_document_entry(
            document,
            report,
            MeetingContext(
                meeting_id=base.entry["meeting_id"],
                turns=base.turns,
                segments=base.segments,
                labels=base.labels,
                items=base.entry["items"],
                meeting_date=read_meeting_date(self.payload),
                roster=self.roster,
                agenda=self.agenda if document == "tasks" else None,
            ),
        )
        failures = report.failures
        with self.cache.lock(self.key):
            previous = self.cache.load(self.key, name) or {}
            entry = {
                "base_version": base.version,
                "generation": previous.get("generation", 0) + 1,
                "computed_at": _now_iso(),
                "status": "ok" if content["complete"] else "incomplete",
                "source": self.payload.get("source"),
                **content,
            }
            if self.cache.version(self.key, "base") not in (None, base.version):
                # Nền đã bị thay trong lúc tính: không lưu, ``execute`` làm lại theo nền mới.
                return {**entry, "version": 0}, True
            if failures and previous.get("base_version") == base.version and previous.get("status") == "ok":
                failed = ", ".join(f"{f.segment_id}: {f.error}" for f in failures)
                raise PartReloadFailedError(
                    f"Chạy lại phần {_DOCUMENT_TITLES[document]} lỗi ở {len(failures)} chủ đề ({failed}); "
                    "giữ nguyên kết quả trước."
                )
            return self.cache.save(self.key, name, entry), True

    def _latest(
        self, base: _MeetingBase, entries: dict[DocumentKind, dict], fresh: frozenset[DocumentKind]
    ) -> DocumentResult | None:
        """Các mục cùng nền, ưu tiên mục mới hơn mà request khác vừa ghi.

        Đầu ra: DocumentResult, hoặc None nếu nền đã bị thay trong lúc tính.
        """

        with self.cache.lock(self.key):
            if self.cache.version(self.key, "base") not in (None, base.version):
                return None
            if any(entry["base_version"] != base.version for entry in entries.values()):
                return None
            latest, latest_fresh = dict(entries), set(fresh)
            for document, entry in entries.items():
                name = self.entry_names[document]
                stored_version = self.cache.version(self.key, name)
                if stored_version is None or stored_version <= entry["version"]:
                    continue
                stored = self.cache.load(self.key, name)
                if stored is not None and stored["base_version"] == base.version:
                    latest[document] = stored
                    latest_fresh.add(document)
            return DocumentResult(
                key=self.key,
                base_entry=base.entry,
                entries=latest,
                entry_names={document: self.entry_names[document] for document in latest},
                fresh=frozenset(latest_fresh),
            )


def run_meeting_document_v3(
    payload: dict,
    document: DocumentKind,
    *,
    analyzer: MeetingAnalyzer,
    cache: AnalysisCache,
    segmenter: DialStartSegmenter,
    refresh: bool = False,
    refresh_base: bool = False,
) -> dict:
    """Một document (Giao việc, Kết luận hoặc Diễn biến) của cuộc họp, dùng lại cache nếu có.

    Đầu vào:
        payload: ``AnalyzeV3Request.model_dump()``.
        document: content | decisions | tasks.
        analyzer: ``MeetingAnalyzer`` dùng chung của ứng dụng.
        cache: ``AnalysisCache`` dùng chung của ứng dụng.
        segmenter: ``DialStartSegmenter`` dùng chung của ứng dụng (bước 2).
        refresh: tính lại document này trên nền đã có.
        refresh_base: tính lại cả nền (cắt chủ đề + nhãn); các document khác trên nền cũ sẽ được
            tính lại khi được yêu cầu.
    Đầu ra: dict theo model document tương ứng (``services/documents.py``).
    Lỗi: ``LLMUpstreamError`` nếu LLM gán nhãn lỗi; ``ValueError`` nếu transcript, danh sách
        tham dự hoặc danh sách việc không hợp lệ; ``PartReloadFailedError`` nếu tính lại mà có chủ
        đề lỗi (bản cũ được giữ); ``AnalysisConflictError`` nếu nền bị thay liên tục.
    """

    run = _MeetingAnalysisRun(
        payload,
        analyzer=analyzer,
        cache=cache,
        segmenter=segmenter,
    )
    result = run.execute((document,), refresh_base=refresh_base, refresh=(document,) if refresh else ())
    return build_document(
        document,
        meeting_id=result.base_entry["meeting_id"],
        entry=result.entries[document],
        source=payload.get("source"),
    )


# Mục cache giữ request ``POST /content`` gần nhất của một cuộc họp, để lấy document theo ``meeting_id``.
_MEETING_REQUEST_ENTRY = "request"


def _meeting_index_key(cache: AnalysisCache, meeting_id: str) -> str:
    """Khoá (32 hex) của chỉ mục theo ``meeting_id``; có fingerprint pipeline nên đổi mã nguồn/model thì hết hiệu lực."""

    return cache.key_for({"meeting_index": meeting_id})


def remember_meeting_request_v3(meeting_id: str, payload: dict, cache: AnalysisCache) -> None:
    """Lưu ``payload`` làm request gần nhất của cuộc họp ``meeting_id`` (request sau đè request trước).

    Đầu vào: meeting_id - ``meeting_id`` của document vừa trả (đã điền mặc định với STT export);
        payload - ``AnalyzeV3Request.model_dump()``; cache - cache dùng chung.
    """

    # Lưu dạng JSON (``meeting_date`` thành chuỗi ISO); khoá document hash bằng ``default=str``
    # nên request khôi phục cho ra đúng các mục cache cũ.
    stored = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    cache.save(_meeting_index_key(cache, meeting_id), _MEETING_REQUEST_ENTRY, {"payload": stored})


def run_meeting_document_by_id_v3(
    meeting_id: str,
    document: DocumentKind,
    *,
    analyzer: MeetingAnalyzer,
    cache: AnalysisCache,
    segmenter: DialStartSegmenter,
) -> dict | None:
    """Document của cuộc họp ``meeting_id`` theo request ``POST /content`` gần nhất của nó.

    Document đã tính sẵn thì lấy từ cache; đang tính nền thì chờ chung lần tính đó; chưa có (tính
    nền lỗi, cache hết hạn) thì tính như ``run_meeting_document_v3`` với request đã lưu.

    Đầu ra: dict document, hoặc None nếu chưa có request nào của cuộc họp (hoặc đã hết hạn).
    Lỗi: như ``run_meeting_document_v3``.
    """

    entry = cache.load(_meeting_index_key(cache, meeting_id), _MEETING_REQUEST_ENTRY)
    if entry is None:
        return None
    return run_meeting_document_v3(
        entry["payload"],
        document,
        analyzer=analyzer,
        cache=cache,
        segmenter=segmenter,
    )


def prefetch_meeting_documents_v3(
    payload: dict,
    documents: Collection[DocumentKind],
    *,
    analyzer: MeetingAnalyzer,
    cache: AnalysisCache,
    segmenter: DialStartSegmenter,
) -> None:
    """Tính sẵn ``documents`` vào cache (chạy nền sau response của một document khác), không trả gì.

    Document đã có trong cache cùng nền thì bỏ qua; request của document đó tới trong lúc đang tính
    thì chờ chung lần tính này (``run_once``). Lỗi chỉ ghi log: request sau của document đó tự tính lại.

    Đầu vào: payload - ``AnalyzeV3Request.model_dump()``; documents - document cần tính sẵn; còn lại
        như ``run_meeting_document_v3``.
    """

    try:
        run = _MeetingAnalysisRun(
            payload,
            analyzer=analyzer,
            cache=cache,
            segmenter=segmenter,
        )
        run.execute(tuple(documents), refresh_base=False, refresh=())
    except Exception:
        logger.exception("Tính sẵn %s lỗi; request sau sẽ tính lại.", ", ".join(documents))


__all__ = [
    "DOCUMENT_KINDS",
    "AnalysisConflictError",
    "DocumentKind",
    "PartReloadFailedError",
    "build_analysis_cache_v3",
    "document_entry_name",
    "document_parts",
    "prefetch_meeting_documents_v3",
    "remember_meeting_request_v3",
    "run_meeting_document_by_id_v3",
    "run_meeting_document_v3",
    "transcript_payload",
]
