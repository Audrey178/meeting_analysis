"""Quy trình v3 (``src/agentic_v3``) cho API: cắt chủ đề (``segmentation.py``), rồi mọi chủ đề chạy song song
(gán nhãn -> trích xuất -> Evidence-Check -> Verifier ReAct <-> agent trích xuất tới khi
đồng thuận), trả kết quả trong MỘT request (không có bước duyệt người).

Kết quả được cache (``analysis_cache.py``) theo hai tầng, cùng một ``analysis_key`` = hash phần
transcript của request (``meeting_id``, ``revision_id``, ``items``):

    base        segment_meeting (stage01-03 + cắt chủ đề, ``services/segmentation.py``)
                + MeetingAnalyzerV3.label_segments (nhãn mọi chủ đề)
    document    content | decisions | tasks, mỗi document một lần MeetingAnalyzerV3.analyze trên
                nhãn của base, lưu ở mục ``"<document>@<hash>"`` (hash các trường request còn lại
                mà document phụ thuộc, xem ``document_entry_name``):
                    content    phần development (Diễn biến)
                    decisions  phần decisions (Kết luận)
                    tasks      phần assignments + progress (Giao việc + tiến độ việc cũ)

Nhãn thuộc base vì nằm trong prompt của mọi agent và mọi mục được gắn vào chủ đề theo nó;
tính lại một document không bao giờ đổi base. Mỗi lần tính, ``services/documents.py`` dựng nội
dung document (``data``, ``audit``, độ phủ) thẳng từ ``MeetingReport`` và mục cache lưu đúng nội
dung đó; khi trả response chỉ bọc thêm khung (``build_document``).

``MeetingAnalyzerV3`` và ``AnalysisCache`` sống suốt vòng đời ứng dụng (``app.state``) để mọi
request dùng chung một ``LLMConcurrencyGate`` và một chỗ chạy-một-lần.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sys
from collections.abc import Collection, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

_BE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BE_DIR.parent
for _dir in (_BE_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from experiments.dialstart import DialStartSegmenter

from src.agentic_v3 import AnalysisPart, MeetingAnalyzerV3, V3Config
from src.agentic_v3.actors.agenda import TaskAgenda, parse_task_agenda
from src.agentic_v3.actors.attendees import AttendeeRoster, parse_attendee_roster
from src.utils.contracts import SpeakerTurn, TopicLabel, TopicSegment
from src.utils.ports import EmbeddingAdapter

from services.analysis_cache import AnalysisCache, build_analysis_backend, fingerprint_pipeline
from services.documents import MeetingContext, build_document, build_document_entry
from services.segmentation import load_pipeline_config, segment_meeting


def build_v3_config_from_env() -> V3Config:
    """Cấu hình v3 từ biến môi trường ``V3_*`` (giá trị thiếu dùng mặc định của ``V3Config``).

    Đầu ra: V3Config.
    """

    defaults = V3Config()
    return V3Config(
        extract_attempts=int(os.environ.get("V3_EXTRACT_ATTEMPTS", defaults.extract_attempts)),
        verifier_max_tool_calls=int(os.environ.get("V3_VERIFIER_MAX_TOOL_CALLS", defaults.verifier_max_tool_calls)),
        consensus_max_rounds=int(os.environ.get("V3_CONSENSUS_MAX_ROUNDS", defaults.consensus_max_rounds)),
        max_concurrency=int(os.environ.get("V3_MAX_CONCURRENCY", defaults.max_concurrency)),
    )


def _build_verifier_llm(default_llm):
    """LLM cho Verifier: backend riêng nếu có ``VERIFIER_MODEL_NAME``, không thì ``default_llm``.

    Biến môi trường (chỉ đọc khi có ``VERIFIER_MODEL_NAME``):
        VERIFIER_BASE_URL, VERIFIER_API_KEY: endpoint OpenAI-compatible (vd DeepSeek).
        VERIFIER_RESPONSE_MODE: ``json_object`` (mặc định, DeepSeek không hỗ trợ
            ``json_schema`` strict) hoặc ``json_schema``.
        VERIFIER_LLM_CONCURRENCY: số lời gọi Verifier đồng thời (gate riêng, mặc định 8).
        VERIFIER_THINKING: ``enabled``/``disabled`` gửi kèm ``{"thinking": {"type": ...}}``
            (DeepSeek V4); để trống thì không gửi. ``deepseek-flash`` bật thinking thì
            hay trả ``content`` toàn khoảng trắng ở chế độ ``json_object``.

    Đầu vào: default_llm - LLM dùng chung của các vai trò khác.
    Đầu ra: (adapter, số lời gọi đồng thời hoặc None nếu dùng chung gate).
    Lỗi: ValueError nếu có ``VERIFIER_MODEL_NAME`` mà thiếu ``VERIFIER_BASE_URL``/``VERIFIER_API_KEY``.
    """

    from src.utils.openai_adapters import OpenAIChatJSONAdapter

    model = os.environ.get("VERIFIER_MODEL_NAME", "").strip()
    if not model:
        return default_llm, None
    base_url = os.environ.get("VERIFIER_BASE_URL", "").strip()
    api_key = os.environ.get("VERIFIER_API_KEY", "").strip()
    if not base_url or not api_key:
        raise ValueError("VERIFIER_MODEL_NAME cần đi kèm VERIFIER_BASE_URL và VERIFIER_API_KEY")
    thinking = os.environ.get("VERIFIER_THINKING", "").strip().lower()
    if thinking not in ("", "enabled", "disabled"):
        raise ValueError(f"VERIFIER_THINKING không hợp lệ: {thinking!r} (enabled | disabled)")
    llm = OpenAIChatJSONAdapter(
        model=model,
        base_url=base_url,
        api_key=api_key,
        response_mode=os.environ.get("VERIFIER_RESPONSE_MODE", "json_object"),
        extra_body={"thinking": {"type": thinking}} if thinking else None,
    )
    return llm, int(os.environ.get("VERIFIER_LLM_CONCURRENCY", "8"))


def _build_decisions_client():
    """Client OpenAI cho Decisions API cùng tên model, hoặc None nếu chưa bật.

    Dùng chung cho bộ phân loại lượt chốt (``_build_turn_judge``) và lượt nêu trạng thái
    tiến độ (``_build_progress_judge``).

    Biến môi trường:
        TURN_ACT_MODEL: model Decisions (vd ``gpt-6-luna``); để trống thì không bật, evidence-check
            dùng luật từ khoá như v1.
        TURN_ACT_API_KEY: key OpenAI; để trống thì dùng ``VERIFIER_API_KEY`` rồi ``OPENAI_API_KEY``.
        TURN_ACT_BASE_URL: mặc định ``https://api.openai.com/v1`` (KHÔNG kế thừa ``OPENAI_BASE_URL``,
            vốn trỏ tới gateway chỉ có chat).
        TURN_ACT_TIMEOUT_SECONDS: timeout mỗi lời gọi (mặc định 10; quá hạn thì quay về luật từ khoá).

    Đầu ra: (client, model) hoặc None.
    Lỗi: ValueError nếu có ``TURN_ACT_MODEL`` mà không tìm được API key.
    """

    from openai import OpenAI

    model = os.environ.get("TURN_ACT_MODEL", "").strip()
    if not model:
        return None
    api_key = next(
        (value for name in ("TURN_ACT_API_KEY", "VERIFIER_API_KEY", "OPENAI_API_KEY")
         if (value := os.environ.get(name, "").strip())),
        None,
    )
    if api_key is None:
        raise ValueError("TURN_ACT_MODEL cần TURN_ACT_API_KEY (hoặc VERIFIER_API_KEY/OPENAI_API_KEY)")
    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get("TURN_ACT_BASE_URL", "").strip() or "https://api.openai.com/v1",
        timeout=float(os.environ.get("TURN_ACT_TIMEOUT_SECONDS", "10")),
        max_retries=2,  # đã gặp "Connection reset by peer" lẻ tẻ khi đo; SDK tự thử lại lỗi mạng/429/5xx
    )
    return client, model


def _build_turn_judge(decisions=None):
    """Bộ phân loại lượt chốt theo nghĩa (OpenAI Decisions API), hoặc None nếu chưa bật.

    Đầu vào: decisions - kết quả ``_build_decisions_client`` (None thì không bật; evidence-check
        dùng luật từ khoá như v1).
    Đầu ra: ``DecisionsTurnActJudge`` hoặc None.
    """

    from src.agentic_v3.core.turn_act import DecisionsTurnActJudge

    if decisions is None:
        return None
    client, model = decisions
    return DecisionsTurnActJudge(client, model=model)


def _build_progress_judge(decisions=None):
    """Bộ phân loại lượt nêu trạng thái tiến độ (Decisions), hoặc None nếu chưa bật.

    Chưa bật thì trạng thái agent tiến độ khai được giữ và đánh dấu ``unchecked``.

    Đầu vào: decisions - kết quả ``_build_decisions_client``.
    Đầu ra: ``DecisionsProgressActJudge`` hoặc None.
    """

    from src.agentic_v3.nodes.progress_act import DecisionsProgressActJudge

    if decisions is None:
        return None
    client, model = decisions
    return DecisionsProgressActJudge(client, model=model)


def build_analyzer_v3() -> MeetingAnalyzerV3:
    """Dựng analyzer v3 dùng adapter OpenAI thật (gọi lười, lần đầu có request v3).

    Một instance LLM dùng chung cho gán nhãn + ba agent trích xuất; Verifier có thể trỏ sang backend riêng
    (``_build_verifier_llm``). Số lời gọi đồng thời đọc từ ``V3_LLM_CONCURRENCY`` (mặc định 8).
    Lượt chốt và lượt nêu trạng thái tiến độ được xét theo nghĩa khi có ``TURN_ACT_MODEL``
    (``_build_turn_judge``, ``_build_progress_judge``, chung một client).

    Đầu ra: MeetingAnalyzerV3.
    """

    from src.stages.stage07_topic_labeling import StructuredLLMTopicLabeler
    from src.utils.openai_adapters import OpenAIChatJSONAdapter

    llm = OpenAIChatJSONAdapter()
    verifier_llm, verifier_concurrency = _build_verifier_llm(llm)
    labeler = StructuredLLMTopicLabeler(llm, model_name=getattr(llm, "model_name", "openai"))
    decisions = _build_decisions_client()
    return MeetingAnalyzerV3(
        content_llm=llm,
        action_llm=llm,
        decision_llm=llm,
        verifier_llm=verifier_llm,
        labeler=labeler,
        labeler_config=load_pipeline_config().topic_labeler,
        config=build_v3_config_from_env(),
        llm_concurrency=int(os.environ.get("V3_LLM_CONCURRENCY", "8")),
        verifier_llm_concurrency=verifier_concurrency,
        turn_judge=_build_turn_judge(decisions),
        progress_judge=_build_progress_judge(decisions),
    )


def read_meeting_date(payload: dict) -> str | None:
    """Lấy ngày họp ISO "YYYY-MM-DD" từ payload (``AnalyzeV3Request.model_dump()`` cho ra ``date``).

    Đầu vào: payload - transcript dạng dict.
    Đầu ra: chuỗi ISO, hoặc None nếu payload không có ngày họp.
    """

    value = payload.get("meeting_date")
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def read_attendee_roster(payload: dict) -> AttendeeRoster | None:
    """Đọc danh sách tham dự (``attendees``) gửi kèm request, None nếu không có.

    Đầu vào: payload - ``AnalyzeRequest.model_dump()``.
    Đầu ra: AttendeeRoster hoặc None.
    Lỗi: ValueError nếu danh sách sai dạng (router trả 422).
    """

    attendees = payload.get("attendees")
    return parse_attendee_roster(attendees) if attendees else None


def read_task_agenda(payload: dict, roster: AttendeeRoster | None) -> TaskAgenda | None:
    """Đọc danh sách việc cần báo cáo (``tasks``) gửi kèm request, None nếu không có/rỗng.

    Đầu vào: payload - ``AnalyzeV3Request.model_dump()``; roster - danh sách tham dự để tra
        mã người/đơn vị.
    Đầu ra: TaskAgenda hoặc None.
    Lỗi: ValueError nếu danh sách sai dạng (router trả 422).
    """

    tasks = payload.get("tasks")
    if not tasks or not tasks.get("tasks"):
        return None
    return parse_task_agenda(tasks, roster)


# Mã nguồn/cấu hình quyết định kết quả, đưa vào fingerprint của cache (đường dẫn so với gốc repo).
_FINGERPRINT_SOURCES = (
    "src",
    "be/services",
    "be/schemas.py",
    "configs",
    "experiments/dialstart",
    "experiments/treeseg_turn_level",
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
    "TURN_ACT_BASE_URL",
    "TOPIC_SEGMENTER",
    "DIALSTART_CHECKPOINT",
    "EMBEDDING_BACKEND",
    "EMBEDDING_MODEL",
    "EMBEDDING_TEXT_PREFIX",
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
# Phần kết quả (``MeetingAnalyzerV3.analyze``) của từng document; Tiến độ chỉ có khi request có ``tasks``.
_PARTS_OF_DOCUMENT: dict[DocumentKind, tuple[AnalysisPart, ...]] = {
    "content": ("development",),
    "decisions": ("decisions",),
    "tasks": ("assignments", "progress"),
}
# Trường của request tạo nên transcript: khoá của bản phân tích (nền chung của mọi document).
_TRANSCRIPT_FIELDS = ("meeting_id", "revision_id", "items")
# Trường còn lại của request mà từng document phụ thuộc, đi vào tên mục cache của document.
# Content/Decisions không nhận ``tasks``: chúng chạy không có danh sách việc (danh sách việc
# nằm trong prompt của mọi agent, nên nhận vào thì kết quả đổi theo mà khoá không đổi).
_DOCUMENT_INPUT_FIELDS: dict[DocumentKind, tuple[str, ...]] = {
    "content": ("chair", "meeting_date", "attendees"),
    "decisions": ("chair", "meeting_date", "attendees"),
    "tasks": ("chair", "meeting_date", "attendees", "tasks"),
}
DOCUMENT_KEY_PATTERN = r"^(content|decisions|tasks)@[0-9a-f]{16}$"


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
    """Phần transcript của request (``meeting_id``, ``revision_id``, ``items``): nguồn của khoá bản phân tích."""

    return {field: payload.get(field) for field in _TRANSCRIPT_FIELDS}


def document_entry_name(document: DocumentKind, payload: Mapping) -> str:
    """Tên mục cache của ``document``: ``"<document>@<16 hex>"``, hash từ các trường request nó phụ thuộc.

    Đầu vào: document - content | decisions | tasks; payload - ``AnalyzeV3Request.model_dump()``.
    Đầu ra: str khớp ``DOCUMENT_KEY_PATTERN``.
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
    ``speaker_id`` lấy từ trường ``speaker_id``, thiếu thì từ ``ref_id`` (mã người nói của bản xuất STT).
    """

    return [
        {"id": item.get("id", item.get("item_id")), "speaker_id": item.get("speaker_id") or _first_ref_id(item.get("ref_id"))}
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
    """Dựng lại dataclass phẳng (``SpeakerTurn``/``TopicSegment``/``TopicLabel``) từ dict JSON."""

    return cls(**{name: _as_tuple(value) for name, value in data.items()})


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
        của ứng dụng; embedding_adapter, topic_segmenter - cho bước cắt chủ đề.
    Lỗi: ValueError nếu danh sách tham dự hoặc danh sách việc sai dạng (kiểm trước mọi bước tính).
    """

    def __init__(
        self,
        payload: dict,
        *,
        analyzer: MeetingAnalyzerV3,
        cache: AnalysisCache,
        embedding_adapter: EmbeddingAdapter,
        topic_segmenter: DialStartSegmenter | None,
    ) -> None:
        self.roster = read_attendee_roster(payload)
        self.agenda = read_task_agenda(payload, self.roster)
        self.payload = payload
        self.key = cache.key_for(transcript_payload(payload))
        self.entry_names = {document: document_entry_name(document, payload) for document in DOCUMENT_KINDS}
        self.analyzer = analyzer
        self.cache = cache
        self.embedding_adapter = embedding_adapter
        self.topic_segmenter = topic_segmenter

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
        """Cắt chủ đề và gán nhãn mọi chủ đề rồi lưu làm nền.

        Trước khi tính, dùng luôn nền đã lưu có version > ``newer_than``: nền mà request khác vừa
        tính trong lúc request này chờ (backend Redis cho người chờ chạy hàm này sau người tính).

        Đầu vào: newer_than - 0 khi chỉ cần có nền; version nền lúc request bắt đầu khi ``refresh``.
        """

        entry = self.cache.load(self.key, "base")
        if entry is not None and entry["version"] > newer_than:
            return _MeetingBase.from_entry(entry)
        meeting = segment_meeting(
            self.payload, embedding_adapter=self.embedding_adapter, topic_segmenter=self.topic_segmenter
        )
        labels = self.analyzer.label_segments(meeting.segments)
        entry = self.cache.save(
            self.key,
            "base",
            {
                "meeting_id": meeting.meeting_id,
                "revision_id": meeting.revision_id,
                "computed_at": _now_iso(),
                "items": _transcript_items(self.payload),
                "turns": [dataclasses.asdict(turn) for turn in meeting.turns],
                "segments": [dataclasses.asdict(segment) for segment in meeting.segments],
                "labels": [dataclasses.asdict(label) for label in labels],
            },
        )
        return _MeetingBase(entry, tuple(meeting.turns), tuple(meeting.segments), tuple(labels))

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
            revision_id=base.entry["revision_id"],
            meeting_date=read_meeting_date(self.payload),
            chair=self.payload.get("chair"),
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
                chair=self.payload.get("chair"),
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
    analyzer: MeetingAnalyzerV3,
    embedding_adapter: EmbeddingAdapter,
    cache: AnalysisCache,
    topic_segmenter: DialStartSegmenter | None = None,
    refresh: bool = False,
    refresh_base: bool = False,
) -> dict:
    """Một document (Giao việc, Kết luận hoặc Diễn biến) của cuộc họp, dùng lại cache nếu có.

    Đầu vào:
        payload: ``AnalyzeV3Request.model_dump()``.
        document: content | decisions | tasks.
        analyzer: ``MeetingAnalyzerV3`` dùng chung của ứng dụng.
        embedding_adapter, topic_segmenter: như ``segmentation.segment_meeting``.
        cache: ``AnalysisCache`` dùng chung của ứng dụng.
        refresh: tính lại document này trên nền đã có.
        refresh_base: tính lại cả nền (cắt chủ đề + nhãn); các document khác trên nền cũ sẽ được
            tính lại khi được yêu cầu.
    Đầu ra: dict theo model document tương ứng (``services/documents.py``).
    Lỗi: ``LLMUpstreamError`` nếu bước embedding lỗi; ``ValueError`` nếu transcript, danh sách
        tham dự hoặc danh sách việc không hợp lệ; ``PartReloadFailedError`` nếu tính lại mà có chủ
        đề lỗi (bản cũ được giữ); ``AnalysisConflictError`` nếu nền bị thay liên tục.
    """

    run = _MeetingAnalysisRun(
        payload,
        analyzer=analyzer,
        cache=cache,
        embedding_adapter=embedding_adapter,
        topic_segmenter=topic_segmenter,
    )
    result = run.execute((document,), refresh_base=refresh_base, refresh=(document,) if refresh else ())
    return build_document(
        document,
        analysis_key=result.key,
        document_key=result.entry_names[document],
        meeting_id=result.base_entry["meeting_id"],
        entry=result.entries[document],
        source=payload.get("source"),
    )


def load_cached_document_v3(key: str, document_key: str, cache: AnalysisCache) -> dict | None:
    """Document đã cache, không tính gì.

    Đầu vào: key - analysis_key; document_key - ``"<document>@<hash>"`` (cả hai đã kiểm dạng);
        cache - cache dùng chung.
    Đầu ra: dict document, hoặc None nếu nền hoặc document không còn (hay không cùng nền).
    """

    with cache.lock(key):
        base_entry = cache.load(key, "base")
        entry = cache.load(key, document_key)
    if base_entry is None or entry is None or entry["base_version"] != base_entry["version"]:
        return None
    document = document_key.split("@", 1)[0]
    return build_document(
        document,
        analysis_key=key,
        document_key=document_key,
        meeting_id=base_entry["meeting_id"],
        entry=entry,
        source=None,
    )


__all__ = [
    "DOCUMENT_KEY_PATTERN",
    "DOCUMENT_KINDS",
    "AnalysisConflictError",
    "DocumentKind",
    "PartReloadFailedError",
    "build_analysis_cache_v3",
    "build_analyzer_v3",
    "build_v3_config_from_env",
    "document_entry_name",
    "document_parts",
    "load_cached_document_v3",
    "read_attendee_roster",
    "read_task_agenda",
    "run_meeting_document_v3",
    "transcript_payload",
]
