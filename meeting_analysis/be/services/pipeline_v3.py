"""Quy trình v3 (``src/agentic_v3``) cho API: cắt chủ đề (``segmentation.py``), rồi mọi chủ đề chạy song song
(gán nhãn -> trích xuất -> Evidence-Check -> Verifier ReAct <-> agent trích xuất tới khi
đồng thuận), trả kết quả trong MỘT request (không có bước duyệt người).

Kết quả được cache theo nội dung request (``analysis_cache.py``) và tách làm hai tầng:

    base   segment_meeting (stage01-03 + cắt chủ đề, ``services/segmentation.py``)
           + MeetingAnalyzerV3.label_segments (nhãn mọi chủ đề)
    phần   development | assignments | decisions | progress, mỗi phần một lần
           MeetingAnalyzerV3.analyze(parts={phần}, labels=nhãn của base)

Nhãn thuộc base vì nằm trong prompt của cả bốn agent và giao diện gắn mọi mục vào chủ đề
theo nó; chạy lại một phần không bao giờ đổi base. ``run_meeting_analysis_v3`` lấy từ cache
phần nào đã có và chỉ tính phần còn thiếu (hoặc phần được yêu cầu chạy lại).

``MeetingAnalyzerV3`` và ``AnalysisCache`` sống suốt vòng đời ứng dụng (``app.state``) để mọi
request dùng chung một ``LLMConcurrencyGate`` và một chỗ chạy-một-lần.
"""

from __future__ import annotations

import dataclasses
import os
import sys
from collections.abc import Collection, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

_BE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BE_DIR.parent
for _dir in (_BE_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from experiments.dialstart import DialStartSegmenter

from src.agentic_v3 import (
    AGENT_OF_PART,
    ANALYSIS_PARTS,
    ActionItemV3,
    AnalysisPart,
    MeetingAnalyzerV3,
    MeetingReport,
    V3Config,
)
from src.agentic_v3.actors.agenda import TaskAgenda, parse_task_agenda
from src.agentic_v3.actors.attendees import AttendeeRoster, parse_attendee_roster
from src.agentic_v3.core.schemas import ActionItemCandidate, DecisionCandidate, SpeakerSection
from src.utils.contracts import SpeakerTurn, TopicLabel, TopicSegment
from src.utils.ports import EmbeddingAdapter

from services.analysis_cache import AnalysisCache, build_analysis_backend, fingerprint_pipeline
from services.segmentation import load_pipeline_config, segment_meeting


def _env_flag(name: str, default: bool) -> bool:
    """Đọc biến môi trường dạng cờ ("1/true/yes/on" là bật)."""

    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_v3_config_from_env() -> V3Config:
    """Cấu hình v3 từ biến môi trường ``V3_*`` (giá trị thiếu dùng mặc định của ``V3Config``).

    Đầu ra: V3Config.
    """

    defaults = V3Config()
    return V3Config(
        skip_agents_without_commit=_env_flag("V3_SKIP_AGENTS_WITHOUT_COMMIT", defaults.skip_agents_without_commit),
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


def _serialize_speaker_section(section: SpeakerSection) -> dict:
    """Chuyển một ``SpeakerSection`` thành dict JSON cho phản hồi API.

    Đầu vào: section - các luận điểm của một người nói trong một chủ đề.
    Đầu ra: dict gồm ``initials``, ``full_name`` và ``points`` (mỗi điểm có text,
        evidence_ids, quotes, citation_count).
    """

    return {
        "initials": section.initials,
        "full_name": section.full_name,
        "points": [
            {
                "text": point.text,
                "evidence_ids": list(point.evidence_ids),
                "quotes": list(point.quotes),
                "citation_count": point.citation_count,
            }
            for point in section.points
        ],
    }


def read_meeting_date(payload: dict) -> str | None:
    """Lấy ngày họp ISO "YYYY-MM-DD" từ payload (``AnalyzeV3Request.model_dump()`` cho ra ``date``).

    Đầu vào: payload - transcript dạng dict.
    Đầu ra: chuỗi ISO, hoặc None nếu payload không có ngày họp.
    """

    value = payload.get("meeting_date")
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _serialize_action_item(item: ActionItemCandidate) -> dict:
    """Chuyển một ``ActionItemCandidate`` (đã kiểm chứng) thành dict JSON cho phản hồi API.

    Đầu vào: item - một việc được giao, đã qua Evidence-Check (+ Debate/Judge
        nếu uncertain).
    Đầu ra: dict gồm ``segment_id``, ``actor``, ``text``, ``deadline_raw``/``deadline_date``/
        ``deadline_kind``, ``evidence_ids``,
        ``quotes``, ``citation_count``. Không gộp theo người: ``actor`` đi kèm TỪNG item
        thay vì nằm ở một object cha.
    """

    return {
        "segment_id": item.segment_id,
        "actor": item.actor,
        "text": item.text,
        "deadline_raw": item.deadline_raw,
        "deadline_date": item.deadline_date,
        "deadline_kind": item.deadline_kind,
        "status": item.status,
        "confirm_turn_id": item.confirm_turn_id,
        "verification": item.verification,
        "evidence_ids": list(item.evidence_ids),
        "quotes": list(item.quotes),
        "citation_count": len(item.evidence_ids),
    }


def _serialize_decision(item: DecisionCandidate) -> dict:
    """Chuyển một ``DecisionCandidate`` (đã kiểm chứng) thành dict JSON cho phản hồi API.

    Đầu vào: item - một quyết định/chốt phương án, đã qua Evidence-Check (+
        Debate/Judge nếu uncertain).
    Đầu ra: dict gồm ``segment_id``, ``text``, ``evidence_ids``, ``quotes``,
        ``citation_count``.
    """

    return {
        "segment_id": item.segment_id,
        "text": item.text,
        "status": item.status,
        "confirm_turn_id": item.confirm_turn_id,
        "verification": item.verification,
        "evidence_ids": list(item.evidence_ids),
        "quotes": list(item.quotes),
        "citation_count": len(item.evidence_ids),
    }


def _group_meeting_development_by_topic(
    segments, labels_by_segment: dict, meeting_development: list[SpeakerSection]
) -> list[dict]:
    """Ghép ``meeting_development`` (danh sách phẳng) với tiêu đề/tóm tắt chủ đề để trả JSON.
    Đầu vào:
        segments: các đoạn chủ đề của cuộc họp, theo đúng thứ tự.
        labels_by_segment: bảng tra segment_id -> TopicLabel (từ stage07).
        meeting_development: các ``SpeakerSection`` của báo cáo (phẳng, mọi chủ đề trộn chung).
    Đầu ra: list[dict], mỗi phần tử một chủ đề, theo đúng thứ tự ``segments``.
    """

    sections_by_segment: dict[str, list[SpeakerSection]] = {}
    for section in meeting_development:
        sections_by_segment.setdefault(section.segment_id, []).append(section)

    return [
        {
            "segment_id": segment.segment_id,
            "title": label.title if label else "",
            "summary": label.summary if label else "",
            "speakers": [
                _serialize_speaker_section(section)
                for section in sections_by_segment.get(segment.segment_id, [])
            ],
        }
        for segment in segments
        for label in [labels_by_segment.get(segment.segment_id)]
    ]


def _serialize_verification_record(record) -> dict:
    """Chuyển ``VerificationRecord`` thành dict JSON."""

    return {
        "item_key": record.item_key,
        "segment_id": record.segment_id,
        "kind": record.kind,
        "candidate_text": record.candidate_text,
        "reasons": list(record.reasons),
        "steps": [
            {"thought": s.thought, "action": s.action, "argument": s.argument, "observation": s.observation}
            for s in record.steps
        ],
        "verdict": record.verdict,
        "reasoning": record.reasoning,
        "final_text": record.final_text,
        "deciding_turn_id": record.deciding_turn_id,
        "decided_by": record.decided_by,
        "rounds": [
            {
                "candidate_text": r.candidate_text,
                "verdict": r.verdict,
                "feedback": r.feedback,
                "deciding_turn_id": r.deciding_turn_id,
                "stance": r.stance,
                "response": r.response,
            }
            for r in record.rounds
        ],
    }


def _serialize_candidate(candidate) -> dict:
    """Một ``ActorCandidate`` thành dict theo ``ActorCandidateOut``."""

    return {
        "name": candidate.name,
        "actor_type": candidate.actor_type,
        "score": candidate.score,
        "reason": candidate.reason,
        "ref_id": candidate.ref_id,
    }


def _serialize_action_item_v3(item) -> dict:
    """Việc giao v3 = dict của ``_serialize_action_item`` cộng phần định danh actor (nếu item là ``ActionItemV3``).

    Đầu vào: item - ActionItemCandidate hoặc ActionItemV3.
    Đầu ra: dict theo ``ActionItemV3Out``.
    """

    serialized = _serialize_action_item(item)
    if isinstance(item, ActionItemV3):
        serialized.update(
            actor_type=item.actor_type,
            actor_flag=item.actor_flag,
            actor_reason=item.actor_reason,
            actor_candidates=[_serialize_candidate(c) for c in item.actor_candidates],
            assignees=[
                {
                    "mention": a.mention,
                    "role": a.role,
                    "name": a.name,
                    "actor_type": a.actor_type,
                    "flag": a.flag,
                    "reason": a.reason,
                    "ref_id": a.ref_id,
                    "candidates": [_serialize_candidate(c) for c in a.candidates],
                }
                for a in item.assignees
            ],
            relation=item.relation,
        )
    serialized["task_id"] = item.task_id
    return serialized


def _serialize_progress_update(update) -> dict:
    """Chuyển ``ProgressUpdate`` thành dict theo ``ProgressUpdateOut``."""

    return {
        "segment_id": update.segment_id,
        "task_id": update.task_id,
        "status": update.status,
        "status_turn_id": update.status_turn_id,
        "evidence_ids": list(update.evidence_ids),
        "quotes": list(update.quotes),
        "summary": update.summary,
        "blockers": list(update.blockers),
        "directive": update.directive,
        "deadline_raw": update.deadline_raw,
        "deadline_date": update.deadline_date,
        "deadline_kind": update.deadline_kind,
        "deadline_removed": update.deadline_removed,
        "proposed_status": update.proposed_status,
        "status_flag": update.status_flag,
        "status_probabilities": dict(update.status_probabilities),
        "p_directive": update.p_directive,
        "verification": update.verification,
        "reason": update.reason,
    }


def _serialize_task_progress(progress) -> dict:
    """Chuyển ``TaskProgress`` thành dict theo ``TaskProgressOut``."""

    return {
        "task_id": progress.task_id,
        "title": progress.title,
        "owner": progress.owner,
        "previous_status": progress.previous_status,
        "status": progress.status,
        "previous_due": progress.previous_due,
        "deadline_raw": progress.deadline_raw,
        "deadline_date": progress.deadline_date,
        "deadline_kind": progress.deadline_kind,
        "deadline_removed": progress.deadline_removed,
        "status_conflict": progress.status_conflict,
        "uncertain": progress.uncertain,
        "overdue": progress.overdue,
        "deciding_update": (
            _serialize_progress_update(progress.deciding_update) if progress.deciding_update else None
        ),
        "updates": [_serialize_progress_update(update) for update in progress.updates],
    }


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
    "V3_SKIP_AGENTS_WITHOUT_COMMIT",
    "V3_EXTRACT_ATTEMPTS",
    "V3_VERIFIER_MAX_TOOL_CALLS",
    "V3_CONSENSUS_MAX_ROUNDS",
)
_DEFAULT_CACHE_DIR = _REPO_ROOT / "outputs" / "v3_cache"

# Kind của bản ghi Verifier thuộc từng phần (Diễn biến và Tiến độ không qua Verifier).
_RECORD_KIND_OF_PART = {"assignments": "action", "decisions": "decision"}
_PART_TITLES = {"development": "Diễn biến", "assignments": "Giao việc", "decisions": "Kết luận", "progress": "Tiến độ"}
# Số lần làm lại khi nền bị request khác thay ngay trong lúc đang tính.
_MAX_BASE_ATTEMPTS = 3


class PartNotApplicableError(Exception):
    """Phần được yêu cầu không có trong bản phân tích (Tiến độ khi request không có ``tasks``)."""


class PartReloadFailedError(Exception):
    """Chạy lại một phần mà có chủ đề lỗi, trong khi bản đang lưu của phần đó đầy đủ: giữ bản cũ."""


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


def applicable_parts(agenda: TaskAgenda | None) -> tuple[AnalysisPart, ...]:
    """Các phần của một bản phân tích: Tiến độ chỉ có khi request có danh sách việc.

    Đầu vào: agenda - kết quả ``read_task_agenda``.
    Đầu ra: tuple phần theo thứ tự ``ANALYSIS_PARTS``.
    """

    return tuple(part for part in ANALYSIS_PARTS if part != "progress" or agenda is not None)


def _now_iso() -> str:
    """Thời điểm hiện tại (UTC, ISO 8601) cho ``computed_at``."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _restore_dataclass(cls, data: Mapping):
    """Dựng lại dataclass phẳng (``SpeakerTurn``/``TopicSegment``/``TopicLabel``) từ dict JSON.

    JSON biến tuple thành list, nên mọi list được đổi lại thành tuple như trong dataclass gốc.
    """

    return cls(**{name: tuple(value) if isinstance(value, list) else value for name, value in data.items()})


@dataclasses.dataclass(frozen=True)
class _MeetingBase:
    """Nền chung của mọi phần: mục ``base`` đã lưu (có ``version``) và đối tượng dựng từ nó.

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


def _build_part_data(part: AnalysisPart, report: MeetingReport, base: _MeetingBase) -> dict:
    """Phần ``part`` của response, từ ``MeetingReport`` của lần tính riêng phần đó.

    Ba danh sách dùng chung giữa các phần (``failed_topics``, ``skipped_agents``,
    ``verification_records``) chỉ giữ mục của phần này, để khi ghép, chạy lại một phần không
    xoá hay nhân đôi mục của phần khác.

    Đầu vào: part - phần; report - kết quả ``analyze(parts={part})``; base - nền đã dùng.
    Đầu ra: dict JSON (các khoá của ``AnalyzeV3Result`` thuộc phần này).
    """

    agent = AGENT_OF_PART[part]
    record_kind = _RECORD_KIND_OF_PART.get(part)
    data: dict = {
        "failed_topics": [
            {"segment_id": f.segment_id, "agent": f.agent, "error": f.error} for f in report.failures if f.agent == agent
        ],
        "skipped_agents": [
            {"segment_id": s.segment_id, "agent": s.agent} for s in report.skipped_agents if s.agent == agent
        ],
        "verification_records": [
            _serialize_verification_record(r) for r in report.verification_records if r.kind == record_kind
        ],
    }
    if part == "development":
        labels_by_segment = {label.segment_id: label for label in base.labels}
        data["topics"] = _group_meeting_development_by_topic(
            base.segments, labels_by_segment, list(report.meeting_development)
        )
    elif part == "assignments":
        data["verified_assignments"] = [_serialize_action_item_v3(item) for item in report.assignments]
    elif part == "decisions":
        data["verified_decisions"] = [_serialize_decision(item) for item in report.decisions]
    else:
        data["task_progress"] = [_serialize_task_progress(progress) for progress in report.task_progress]
    return data


def _build_result(key: str, base_entry: dict, entries: Mapping[str, dict], fresh: Collection[str]) -> dict:
    """Ghép nền và các phần thành dict theo ``AnalyzeV3Result``.

    Đầu vào: key - analysis_key; base_entry - mục ``base``; entries - phần -> mục của phần (theo
        thứ tự ``ANALYSIS_PARTS``); fresh - các phần vừa tính trong request này.
    Đầu ra: dict theo ``AnalyzeV3Result``; ``cache_version`` là version lớn nhất trong các mục.
    """

    order = {segment["segment_id"]: index for index, segment in enumerate(base_entry["segments"])}

    def gather(field: str) -> list[dict]:
        items = [item for entry in entries.values() for item in entry["data"][field]]
        return sorted(items, key=lambda item: order.get(item["segment_id"], len(order)))

    def part_field(part: str, field: str) -> list[dict]:
        return entries[part]["data"][field] if part in entries else []

    return {
        "analysis_key": key,
        "cache_version": max(entry["version"] for entry in (base_entry, *entries.values())),
        "parts": {
            part: {
                "generation": entry["generation"],
                "computed_at": entry["computed_at"],
                "from_cache": part not in fresh,
                "status": entry["status"],
            }
            for part, entry in entries.items()
        },
        "meeting_id": base_entry["meeting_id"],
        "revision_id": base_entry["revision_id"],
        "topics": part_field("development", "topics"),
        "verified_assignments": part_field("assignments", "verified_assignments"),
        "verified_decisions": part_field("decisions", "verified_decisions"),
        "task_progress": part_field("progress", "task_progress"),
        "turns": [
            {"turn_id": turn["turn_id"], "speaker": turn["speaker"], "text": turn["text_exact"]}
            for turn in base_entry["turns"]
        ],
        "failed_topics": gather("failed_topics"),
        "verification_records": gather("verification_records"),
        "skipped_agents": gather("skipped_agents"),
    }


class _MeetingAnalysisRun:
    """Một request phân tích v3: lấy hoặc tính nền, rồi lấy hoặc tính từng phần, đều qua cache.

    Ba bất biến:
    1. Mọi phần trong một response được tính trên cùng một nền (cùng ranh giới chủ đề và nhãn).
    2. Mỗi mục của một bản phân tích có tối đa một lần tính đang chạy; request trùng chờ chung.
    3. Chỉ ghi cache khi tính xong; chạy lại một phần mà lỗi thì bản đầy đủ đang lưu còn nguyên.

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
        self.parts = applicable_parts(self.agenda)
        self.payload = payload
        self.key = cache.key_for(payload)
        self.analyzer = analyzer
        self.cache = cache
        self.embedding_adapter = embedding_adapter
        self.topic_segmenter = topic_segmenter

    def execute(self, *, refresh: bool, reload_part: AnalysisPart | None) -> dict:
        """Trả kết quả đủ mọi phần, tính lại những gì được yêu cầu hoặc còn thiếu.

        Đầu vào: refresh - tính lại tất cả, kể cả nền; reload_part - phần cần tính lại (None nếu
            không có).
        Đầu ra: dict theo ``AnalyzeV3Result``.
        Lỗi: PartNotApplicableError, PartReloadFailedError, AnalysisConflictError; lỗi của bước
            cắt chủ đề (``LLMUpstreamError``, ``ValueError``).
        """

        if reload_part is not None and reload_part not in self.parts:
            raise PartNotApplicableError(
                f"Không có phần {_PART_TITLES[reload_part]}: request không có danh sách việc cần báo cáo."
            )
        force = frozenset(self.parts) if refresh else frozenset(part for part in (reload_part,) if part)
        for _ in range(_MAX_BASE_ATTEMPTS):
            base = self._ensure_base(refresh=refresh)
            entries, fresh = self._ensure_parts(base, force)
            result = self._assemble(base, entries, fresh)
            if result is not None:
                return result
            # Request khác vừa chạy lại toàn bộ nên nền đã đổi: đọc lại theo nền mới; các phần của
            # nền đó do chính request kia tính (chờ chung qua ``run_once``).
            refresh, force = False, frozenset()
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
                "parts": list(self.parts),
                "computed_at": _now_iso(),
                "turns": [dataclasses.asdict(turn) for turn in meeting.turns],
                "segments": [dataclasses.asdict(segment) for segment in meeting.segments],
                "labels": [dataclasses.asdict(label) for label in labels],
            },
        )
        return _MeetingBase(entry, tuple(meeting.turns), tuple(meeting.segments), tuple(labels))

    def _ensure_parts(self, base: _MeetingBase, force: frozenset[str]) -> tuple[dict[str, dict], frozenset[str]]:
        """Mọi phần trên ``base``, song song: phần trong ``force`` luôn tính lại, phần khác lấy cache.

        Phần lỗi thì lỗi được raise sau khi các phần kia xong (và đã lưu).

        Đầu ra: (phần -> mục theo thứ tự ``self.parts``, các phần vừa tính).
        """

        with ThreadPoolExecutor(max_workers=len(self.parts), thread_name_prefix="v3-part") as pool:
            futures = {part: pool.submit(self._ensure_part, base, part, part in force) for part in self.parts}
            outcomes = {part: future.result() for part, future in futures.items()}
        entries = {part: entry for part, (entry, _) in outcomes.items()}
        fresh = frozenset(part for part, (_, computed) in outcomes.items() if computed)
        return entries, fresh

    def _ensure_part(self, base: _MeetingBase, part: AnalysisPart, force: bool) -> tuple[dict, bool]:
        """Mục của ``part``: từ cache nếu dùng lại được và không bị ép tính lại.

        Đầu ra: (mục, True nếu vừa được tính).
        """

        seen = self.cache.version(self.key, part) or 0
        if not force:
            entry = self._load_part(base, part)
            if entry is not None:
                return entry, False
        newer_than = seen if force else 0
        # Version nền nằm trong tên lần tính: lần chạy lại toàn bộ (nền mới) không được chờ chung
        # lần tính cùng phần trên nền cũ.
        return self.cache.run_once(
            self.key, (part, base.version), lambda: self._compute_part(base, part, newer_than, seen)
        )

    def _load_part(self, base: _MeetingBase, part: AnalysisPart) -> dict | None:
        """Mục đã lưu của ``part`` nếu dùng lại được: cùng nền và không có chủ đề lỗi."""

        entry = self.cache.load(self.key, part)
        if entry is None or entry["base_version"] != base.version or entry["status"] != "ok":
            return None
        return entry

    def _compute_part(
        self, base: _MeetingBase, part: AnalysisPart, newer_than: int, seen: int
    ) -> tuple[dict, bool]:
        """Tính ``part`` trên nhãn của ``base`` rồi lưu.

        Trước khi tính, dùng luôn mục dùng lại được có version > ``newer_than`` (request khác vừa
        tính trong lúc request này chờ, như ``_compute_base``). Không lưu nếu nền đã bị thay trong
        lúc tính (bất biến 1). Lần tính có chủ đề lỗi không được đè bản đầy đủ đang lưu trên cùng
        nền (bất biến 3): khi đó raise để giữ bản cũ.

        Đầu vào: newer_than - 0 khi chỉ cần có mục; version lúc request bắt đầu khi chạy lại;
            seen - version lúc request bắt đầu (mục mới hơn coi như vừa tính, không lấy từ cache).
        Đầu ra: (mục, True nếu vừa được tính).
        Lỗi: PartReloadFailedError.
        """

        entry = self._load_part(base, part)
        if entry is not None and entry["version"] > newer_than:
            return entry, entry["version"] > seen
        report = self.analyzer.analyze(
            meeting_id=base.entry["meeting_id"],
            revision_id=base.entry["revision_id"],
            meeting_date=read_meeting_date(self.payload),
            chair=self.payload.get("chair"),
            turns=base.turns,
            segments=base.segments,
            attendee_roster=self.roster,
            task_agenda=self.agenda,
            parts=(part,),
            labels=base.labels,
        )
        data = _build_part_data(part, report, base)
        failures = data["failed_topics"]
        with self.cache.lock(self.key):
            previous = self.cache.load(self.key, part) or {}
            entry = {
                "base_version": base.version,
                "generation": previous.get("generation", 0) + 1,
                "computed_at": _now_iso(),
                "status": "incomplete" if failures else "ok",
                "data": data,
            }
            if self.cache.version(self.key, "base") not in (None, base.version):
                # Nền đã bị thay trong lúc tính: không lưu, ``execute`` làm lại theo nền mới.
                return {**entry, "version": 0}, True
            if failures and previous.get("base_version") == base.version and previous.get("status") == "ok":
                failed = ", ".join(f"{f['segment_id']}: {f['error']}" for f in failures)
                raise PartReloadFailedError(
                    f"Chạy lại phần {_PART_TITLES[part]} lỗi ở {len(failures)} chủ đề ({failed}); "
                    "giữ nguyên kết quả trước."
                )
            return self.cache.save(self.key, part, entry), True

    def _assemble(self, base: _MeetingBase, entries: dict[str, dict], fresh: frozenset[str]) -> dict | None:
        """Ghép response, ưu tiên mục mới hơn mà request khác vừa ghi cho cùng nền.

        Đầu ra: dict theo ``AnalyzeV3Result``, hoặc None nếu nền đã bị thay trong lúc tính.
        """

        with self.cache.lock(self.key):
            if self.cache.version(self.key, "base") not in (None, base.version):
                return None
            if any(entry["base_version"] != base.version for entry in entries.values()):
                return None
            latest, latest_fresh = dict(entries), set(fresh)
            for part, entry in entries.items():
                stored_version = self.cache.version(self.key, part)
                if stored_version is None or stored_version <= entry["version"]:
                    continue
                stored = self.cache.load(self.key, part)
                if stored is not None and stored["base_version"] == base.version:
                    latest[part] = stored
                    latest_fresh.add(part)
            return _build_result(self.key, base.entry, latest, latest_fresh)


def run_meeting_analysis_v3(
    payload: dict,
    *,
    analyzer: MeetingAnalyzerV3,
    embedding_adapter: EmbeddingAdapter,
    cache: AnalysisCache,
    topic_segmenter: DialStartSegmenter | None = None,
    refresh: bool = False,
    reload_part: AnalysisPart | None = None,
) -> dict:
    """Phân tích một cuộc họp bằng v3, dùng lại mọi phần đã cache cho cùng request.

    Đầu vào:
        payload: transcript dạng dict (``AnalyzeV3Request.model_dump()``); ``chair`` (tùy
            chọn) là tên người chủ trì.
        analyzer: ``MeetingAnalyzerV3`` dùng chung của ứng dụng.
        embedding_adapter, topic_segmenter: như ``segmentation.segment_meeting``.
        cache: ``AnalysisCache`` dùng chung của ứng dụng.
        refresh: True thì tính lại tất cả, kể cả cắt chủ đề và nhãn.
        reload_part: phần cần tính lại trên nền đã có (các phần khác lấy cache); None thì không.
    Đầu ra: dict theo ``AnalyzeV3Result`` (đủ mọi phần, kèm ``analysis_key``/``cache_version``/``parts``).
    Lỗi: ``LLMUpstreamError`` nếu bước embedding lỗi; ``ValueError`` nếu transcript, danh sách
        tham dự hoặc danh sách việc không hợp lệ; ``PartNotApplicableError`` nếu chạy lại Tiến độ
        mà request không có danh sách việc; ``PartReloadFailedError`` nếu chạy lại một phần mà
        có chủ đề lỗi (bản cũ được giữ); ``AnalysisConflictError`` nếu nền bị thay liên tục.
    """

    run = _MeetingAnalysisRun(
        payload,
        analyzer=analyzer,
        cache=cache,
        embedding_adapter=embedding_adapter,
        topic_segmenter=topic_segmenter,
    )
    return run.execute(refresh=refresh, reload_part=reload_part)


def load_cached_analysis_v3(key: str, cache: AnalysisCache) -> dict | None:
    """Kết quả đã cache của bản ``key``, không tính gì (dùng khi trang web tải lại).

    Đầu vào: key - analysis_key (đã kiểm dạng); cache - cache dùng chung.
    Đầu ra: dict theo ``AnalyzeV3Result``, hoặc None nếu chưa có đủ mọi phần trên cùng một nền.
    """

    with cache.lock(key):
        base_entry = cache.load(key, "base")
        if base_entry is None:
            return None
        entries = {}
        for part in base_entry["parts"]:
            entry = cache.load(key, part)
            if entry is None or entry["base_version"] != base_entry["version"]:
                return None
            entries[part] = entry
        return _build_result(key, base_entry, entries, fresh=())


__all__ = [
    "AnalysisConflictError",
    "PartNotApplicableError",
    "PartReloadFailedError",
    "applicable_parts",
    "build_analysis_cache_v3",
    "build_analyzer_v3",
    "build_v3_config_from_env",
    "load_cached_analysis_v3",
    "read_attendee_roster",
    "read_task_agenda",
    "run_meeting_analysis_v3",
]
