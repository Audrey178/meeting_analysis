"""Ba document kết quả của API v3 (``POST /v3/meetings/tasks|decisions|content``).

Mọi document cùng một khung (theo ``outputs/giaoviec.json``)::

    schema_version, document_type, meeting_id, artifact_revision,
    source, generation, data, extensions

``data`` khác nhau theo document:
    tasks      ``data.tasks``: việc giao mới + việc cũ (backlog) cập nhật tiến độ.
    decisions  ``data.header`` (thông tin biên bản) + ``data.items`` (theo ``outputs/ketluan.json``).
    content    ``data.topics``: các chủ đề, mỗi chủ đề có tiêu đề, tóm tắt, khoảng item và ý thảo luận.

Trích dẫn ở mức item transcript thô: ``segment_ids`` là ``id`` gốc của item trong request (giữ
kiểu: số khi xuất từ STT), kèm ``turn_ids`` (lượt nói chứa các item đó).

Hai bước:
    ``build_document_entry``  lúc tính: ``MeetingReport`` của lần ``analyze`` -> ``data`` + ``audit`` +
                              độ phủ của document (dict JSON, ``pipeline_v3`` lưu vào cache).
    ``build_document``        lúc trả response: mục cache -> document đủ khung (đã qua model).
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from src.agentic_v3 import ActionItemV3, MeetingReport, ProgressUpdate, TaskProgress, VerificationRecord
from src.agentic_v3.actors.agenda import AgendaTask, TaskAgenda, TaskParty
from src.agentic_v3.actors.attendees import AttendeeRoster
from src.agentic_v3.core.schemas import ActionItemCandidate, DiscussionPoint
from src.utils.contracts import SpeakerTurn, TopicLabel, TopicSegment

SCHEMA_VERSION = "1.0"
CITATION_NAMESPACE = "transcript_item_id"
TASK_IDENTITY_STRATEGY = "confirm_turn_assignee_v1"

ItemId = int | str


# ----- Model chung -----


class SourceIn(BaseModel):
    """Nguồn của cuộc họp (gửi kèm request, không ảnh hưởng kết quả nên không vào khoá cache)."""

    transcript_version_id: str | None = None
    transcript_uri: str | None = None
    document_uris: list[str] = []


class CoverageOut(BaseModel):
    """Độ phủ của document: số item transcript thuộc các chủ đề tính xong / tổng số item."""

    is_complete: bool
    processed_segment_count: int
    total_segment_count: int


class GenerationWarningOut(BaseModel):
    """Một cảnh báo khi tính: ``code`` = "topic_failed" (agent lỗi ở một chủ đề sau mọi lần thử)."""

    code: str
    topic_id: str
    agent: str
    message: str


class GenerationOut(BaseModel):
    """Trạng thái lần tính: ``status`` = "complete" | "partial" (có chủ đề lỗi, xem ``warnings``)."""

    status: Literal["complete", "partial"]
    generated_at: str
    coverage: CoverageOut
    warnings: list[GenerationWarningOut] = []
    confidence: float | None = None


class SegmentRefOut(BaseModel):
    """Một item được trích: mã gốc, lượt nói chứa nó, nguyên văn và ``speaker_id`` của người nói."""

    segment_id: ItemId
    turn_id: str
    text: str
    speaker_id: str | None = None


class VerifierStepOut(BaseModel):
    """Một bước tra cứu (ReAct) của Verifier."""

    thought: str
    action: str
    argument: str
    observation: str


class ConsensusRoundOut(BaseModel):
    """Một vòng Verifier gửi feedback -> agent trích xuất trả lời.
    ``stance``: "accept" | "amend" | "defend", rỗng khi Verifier đã giữ (keep)."""

    candidate_text: str
    verdict: str
    feedback: str
    deciding_turn_id: str | None = None
    stance: str = ""
    response: str = ""


class VerificationRecordOut(BaseModel):
    """Bản ghi kiểm chứng một mục bị Evidence-Check nghi ngờ (``kind``: "action" | "decision").
    ``decided_by``: "consensus" (đồng thuận), "verifier" (hết vòng, theo Verifier) hoặc "fallback"."""

    item_key: str
    segment_id: str
    kind: str
    candidate_text: str
    reasons: list[str]
    steps: list[VerifierStepOut]
    verdict: str
    reasoning: str
    final_text: str = ""
    deciding_turn_id: str | None = None
    decided_by: str = "consensus"
    rounds: list[ConsensusRoundOut] = []


class SkippedAgentOut(BaseModel):
    """Agent trích xuất mà Planner bỏ qua ở một chủ đề (không lượt nào có thể là giao/chốt việc)."""

    segment_id: str
    agent: str


class FailedTopicOut(BaseModel):
    """Lời gọi agent vẫn lỗi sau mọi lần thử: kết quả của agent đó ở chủ đề này bị thiếu."""

    segment_id: str
    agent: str
    error: str


class AuditOut(BaseModel):
    """Thông tin để đối chiếu: bản ghi Verifier, agent bị bỏ qua, chủ đề lỗi."""

    verification_records: list[VerificationRecordOut] = []
    skipped_agents: list[SkippedAgentOut] = []
    failed_topics: list[FailedTopicOut] = []


class DocumentExtensionsOut(BaseModel):
    """Thông tin kỹ thuật của document.

    ``input_fingerprint`` là analysis_key (khoá của transcript), ``document_key`` là tên mục cache
    của document: ``GET /v3/meetings/analyses/{input_fingerprint}/{document_key}`` lấy lại document.
    ``artifact_version_id`` tăng sau mỗi lần ghi cache của bản phân tích (bỏ response cũ hơn).
    ``audit``: bản ghi Verifier, agent bị Planner bỏ qua, chủ đề lỗi (để đối chiếu).
    """

    analysis_schema_version: str | None = None
    input_fingerprint: str
    document_key: str
    prompt_version: str | None = None
    model: str | None = None
    transcript_review_state: str | None = None
    citation_namespace: str = CITATION_NAMESPACE
    task_identity_strategy: str | None = None
    artifact_version_id: int
    audit: AuditOut = AuditOut()


class _DocumentOut(BaseModel):
    """Khung chung của ba document."""

    schema_version: str = SCHEMA_VERSION
    meeting_id: str
    artifact_revision: int
    source: SourceIn
    generation: GenerationOut
    extensions: DocumentExtensionsOut


# ----- Giao việc -----


class AssignmentResolutionOut(BaseModel):
    """Cách định danh một bên nhận việc (``src/agentic_v3/actors/resolution.py``).

    ``role``: "lead" | "support" | "joint"; ``flag``: "ambiguous" | "missing" | None.
    """

    mention: str | None = None
    role: str = "lead"
    flag: str | None = None
    reason: str = ""
    candidates: list[dict[str, Any]] = []


class _TargetExtensionsOut(BaseModel):
    resolution: AssignmentResolutionOut | None = None


class UnitTargetOut(BaseModel):
    target_type: Literal["unit"] = "unit"
    unit_id: str | None = None
    unit_name: str | None = None
    extensions: _TargetExtensionsOut = _TargetExtensionsOut()


class PersonTargetOut(BaseModel):
    target_type: Literal["person"] = "person"
    person_id: str | None = None
    person_name: str | None = None
    extensions: _TargetExtensionsOut = _TargetExtensionsOut()


class UnknownTargetOut(BaseModel):
    """Bên nhận việc chưa định danh được là người hay đơn vị (``name`` là cách gọi trong bản ghi)."""

    target_type: Literal["unknown"] = "unknown"
    name: str | None = None
    extensions: _TargetExtensionsOut = _TargetExtensionsOut()


AssignmentTarget = UnitTargetOut | PersonTargetOut | UnknownTargetOut


class TaskAssignmentOut(BaseModel):
    """Bên chính, các bên còn lại (phối hợp/cùng thực hiện) và ``speaker_id`` của người giao."""

    primary: AssignmentTarget | None = None
    collaborators: list[AssignmentTarget] = []
    assigned_by_speaker_id: str | None = None


class TaskContentOut(BaseModel):
    title: str
    description: str


class DueOut(BaseModel):
    """Hạn: ``raw`` nguyên văn, ``date`` ISO (quy theo ngày họp), ``kind`` (exact/before/end_of_period/relative/unknown)."""

    raw: str | None = None
    date: str | None = None
    kind: str = "unknown"


class DetectionConfidenceOut(BaseModel):
    overall: float | None = None
    content: float | None = None
    assignment: float | None = None
    due: float | None = None


class TaskDetectionOut(BaseModel):
    """Cách phát hiện việc.

    ``mode``: "explicit" (giao/nhận rõ), "inferred" (đề xuất/báo cáo, đã qua kiểm chứng) hoặc
    "backlog" (việc cũ trong danh sách cần báo cáo). ``clarity``: "clear" | "unclear".
    ``review_hints``: mã gợi ý cần người xem lại (vd. "assignee_ambiguous", "due_unresolved").
    """

    mode: Literal["explicit", "inferred", "backlog"]
    clarity: Literal["clear", "unclear"]
    review_hints: list[str] = []
    confidence: DetectionConfidenceOut = DetectionConfidenceOut()


class ReferenceExtensionsOut(BaseModel):
    """``evidence_ids``: các turn_id; ``source_segment_refs``: từng item trích kèm nguyên văn."""

    source_event_id: str | None = None
    evidence_ids: list[str] = []
    source_segment_refs: list[SegmentRefOut] = []


class TaskReferencesOut(BaseModel):
    segment_ids: list[ItemId] = []
    confidence: float | None = None
    extensions: ReferenceExtensionsOut = ReferenceExtensionsOut()


class ProgressStepOut(BaseModel):
    """Một cập nhật tiến độ của việc cũ trong một chủ đề (``ProgressUpdateOut`` ở mức item).

    ``deciding``: cập nhật quyết định trạng thái của việc (lượt chỉ đạo/kết luận thắng lượt báo
    cáo, cùng loại thì lượt muộn hơn thắng). ``p_directive``: xác suất lượt nêu trạng thái là chỉ
    đạo/kết luận, None nếu không đo.
    """

    topic_id: str
    status: str
    status_turn_id: str | None = None
    summary: str = ""
    blockers: list[str] = []
    directive: str = ""
    due: DueOut | None = None
    deadline_removed: bool = False
    proposed_status: str | None = None
    status_flag: str | None = None
    verification: str = "rule"
    reason: str = ""
    p_directive: float | None = None
    deciding: bool = False
    segment_ids: list[ItemId] = []
    turn_ids: list[str] = []


class TaskProgressOut(BaseModel):
    """Tiến độ của việc cũ sau phiên họp (``TaskProgressOut`` cũ, bỏ phần trùng với task)."""

    previous_status: str | None = None
    status: str
    previous_due: str | None = None
    status_conflict: bool = False
    uncertain: bool = False
    overdue: bool = False
    summary: str = ""
    blockers: list[str] = []
    directive: str = ""
    deadline_removed: bool = False
    updates: list[ProgressStepOut] = []


class TaskExtractedOut(BaseModel):
    content: TaskContentOut
    assignment: TaskAssignmentOut
    due: DueOut | None = None
    priority: str | None = None
    detection: TaskDetectionOut
    references: TaskReferencesOut
    progress: TaskProgressOut | None = None


class TaskWorkflowOut(BaseModel):
    """Trạng thái duyệt/thực hiện (mặc định như ``outputs/giaoviec.json``).

    ``source_presence``: "present" (cuộc họp có nói tới việc) | "absent" (việc cũ không được nhắc).
    ``dependency_task_ids``: việc cũ mà việc giao này tiếp nối (``relation`` = "follow_up").
    """

    review_status: str = "pending"
    execution_status: str = "proposed"
    required_confirmations: list[str] = []
    confirmed_fields: list[str] = []
    overrides: dict[str, Any] = {}
    attachments: list[Any] = []
    dependency_task_ids: list[str] = []
    updated_at: str | None = None
    updated_by: str | None = None
    revision: int = 1
    source_presence: Literal["present", "absent"] = "present"


class TaskExtensionsOut(ReferenceExtensionsOut):
    """Thông tin từ pipeline: chủ đề, trạng thái agent khai, cách kiểm chứng, lượt chốt.

    ``relation``: "new" | "follow_up" (việc mới tiếp nối việc cũ) | "backlog" (việc cũ, có thể đã
    gộp lời giao lại/dời hạn, xem ``merged_relations``); None khi request không có danh sách việc.
    """

    topic_id: str | None = None
    status: str | None = None
    verification: str | None = None
    confirm_turn_id: str | None = None
    relation: str | None = None
    merged_relations: list[str] = []
    assigned_by_speaker: str | None = None


class TaskOut(BaseModel):
    task_id: str
    source_uri: str | None = None
    extracted: TaskExtractedOut
    workflow: TaskWorkflowOut
    extensions: TaskExtensionsOut


class TasksDataOut(BaseModel):
    tasks: list[TaskOut]


class TasksDocument(_DocumentOut):
    """``POST /v3/meetings/tasks``: việc giao mới và tiến độ việc cũ (theo ``outputs/giaoviec.json``)."""

    document_type: Literal["meeting_tasks"] = "meeting_tasks"
    data: TasksDataOut


# ----- Kết luận -----


class DecisionsHeaderOut(BaseModel):
    """Thông tin biên bản (khoá như ``metadata`` của ``outputs/ketluan.json``).

    ``ngay_hop`` (dd/mm/yyyy) từ ``meeting_date``, ``chu_tri`` từ ``chair``, ``thanh_phan`` và các
    số đếm từ ``attendees`` (danh sách người có mặt). Trường không suy ra được để rỗng.
    """

    ngay_hop: str = ""
    chu_tri: str = ""
    thanh_phan: str = ""
    so_nguoi_tham_gia: int | None = None
    so_nguoi_co_mat: int | None = None
    so_to_trinh: str = ""
    ten_de_an_day_du: str = ""
    don_vi_trinh: str = ""
    don_vi_chu_tri: str = ""
    nguoi_ky_thong_bao: str = ""
    chuc_danh_nguoi_ky: str = ""
    loai_tai_lieu: str = ""
    don_vi_thuc_hien: str = ""


class DecisionExtensionsOut(BaseModel):
    decision_id: str
    topic_id: str
    status: str
    verification: str
    confirm_turn_id: str | None = None
    source_segment_refs: list[SegmentRefOut] = []


class DecisionItemOut(BaseModel):
    """Một kết luận. ``original_segment_ids`` giữ trích dẫn gốc khi người duyệt sửa ``segment_ids``."""

    so_thu_tu: int
    noi_dung: str
    segment_ids: list[ItemId]
    original_segment_ids: list[ItemId]
    turn_ids: list[str]
    extensions: DecisionExtensionsOut


class DecisionsDataOut(BaseModel):
    header: DecisionsHeaderOut
    items: list[DecisionItemOut]


class DecisionsDocument(_DocumentOut):
    """``POST /v3/meetings/decisions``: kết luận cuộc họp (theo ``outputs/ketluan.json``)."""

    document_type: Literal["meeting_decisions"] = "meeting_decisions"
    data: DecisionsDataOut


# ----- Diễn biến -----


class SpanOut(BaseModel):
    """Khoảng của chủ đề: item đầu và cuối (``[first, last]``), lượt nói đầu và cuối."""

    segment_ids: list[ItemId]
    turn_ids: list[str]


class DiscussionPointDocOut(BaseModel):
    """``speaker_ids[i]`` là mã người nói của ``speakers[i]`` (None nếu transcript không có mã)."""

    point_id: str
    text: str
    speakers: list[str]
    speaker_ids: list[str | None] = []
    segment_ids: list[ItemId]
    turn_ids: list[str]
    source_segment_refs: list[SegmentRefOut] = []


class TopicContentOut(BaseModel):
    title: str
    summary: str


class TopicExtractedOut(BaseModel):
    content: TopicContentOut
    span: SpanOut
    discussion_points: list[DiscussionPointDocOut]


class TopicWorkflowOut(BaseModel):
    review_status: str = "pending"
    confirmed_fields: list[str] = []
    overrides: dict[str, Any] = {}
    updated_at: str | None = None
    updated_by: str | None = None
    revision: int = 1


class TopicExtensionsOut(BaseModel):
    segmentation_method: str | None = None
    boundary_score: float | None = None


class TopicOut(BaseModel):
    topic_id: str
    order: int
    extracted: TopicExtractedOut
    workflow: TopicWorkflowOut = TopicWorkflowOut()
    extensions: TopicExtensionsOut


class TranscriptTurnOut(BaseModel):
    """Một lượt nói (các item liền nhau cùng người nói) để hiển thị transcript và tra ``turn_ids``."""

    turn_id: str
    speaker: str | None
    speaker_id: str | None = None
    segment_ids: list[ItemId]
    text: str


class ContentDataOut(BaseModel):
    topics: list[TopicOut]
    turns: list[TranscriptTurnOut]


class ContentDocument(_DocumentOut):
    """``POST /v3/meetings/content``: diễn biến cuộc họp theo chủ đề."""

    document_type: Literal["meeting_content"] = "meeting_content"
    data: ContentDataOut


MeetingDocument = TasksDocument | DecisionsDocument | ContentDocument


# ----- Đầu vào của bước dựng -----


@dataclasses.dataclass(frozen=True)
class MeetingContext:
    """Những gì cần để dựng document ngoài ``MeetingReport``.

    Các trường:
        meeting_id: mã cuộc họp (của nền).
        turns, segments, labels: lượt nói (có ``source_items``), chủ đề, nhãn của nền.
        items: mã gốc + ``speaker_id`` của từng item transcript (mục ``base``).
        meeting_date: ngày họp ISO, None nếu không có.
        chair: người chủ trì do request gửi, None nếu không có.
        roster: danh sách tham dự, None nếu không có.
        agenda: danh sách việc cần báo cáo, None nếu không có (hoặc document không dùng).
    """

    meeting_id: str
    turns: tuple[SpeakerTurn, ...]
    segments: tuple[TopicSegment, ...]
    labels: tuple[TopicLabel, ...]
    items: Sequence[Mapping]
    meeting_date: str | None = None
    chair: str | None = None
    roster: AttendeeRoster | None = None
    agenda: TaskAgenda | None = None


# ----- Tra trích dẫn -----


class _Citations:
    """Tra cứu item của một cuộc họp: mã gốc, lượt nói chứa item, nguyên văn, ``speaker_id``.

    Đầu vào khi tạo: turns - lượt nói có ``source_items``; items - mã gốc + ``speaker_id`` của item.
    """

    def __init__(self, turns: Sequence[SpeakerTurn], items: Sequence[Mapping]) -> None:
        self._original: dict[str, ItemId] = {}
        self._speaker_id: dict[str, str | None] = {}
        for item in items:
            item_id = str(item["id"]).strip()
            self._original[item_id] = item["id"]
            self._speaker_id[item_id] = item.get("speaker_id")
        self._turn_of_item: dict[str, str] = {}
        self._text: dict[str, str] = {}
        self._order: dict[str, int] = {}
        self.items_of_turn: dict[str, tuple[str, ...]] = {}
        self._speaker_id_of_name: dict[str, str] = {}
        for turn in turns:
            self.items_of_turn[turn.turn_id] = tuple(item_id for item_id, _ in turn.source_items)
            speaker_id = self.speaker_id_of_turn(turn.turn_id)
            if turn.speaker and speaker_id:
                self._speaker_id_of_name.setdefault(turn.speaker, speaker_id)
            for item_id, text in turn.source_items:
                self._turn_of_item[item_id] = turn.turn_id
                self._text[item_id] = text
                self._order.setdefault(item_id, len(self._order))

    def ordered(self, item_ids: Iterable[str]) -> list[str]:
        """Mã item không trùng, theo thứ tự transcript."""

        return sorted(set(item_ids), key=lambda item_id: self._order.get(item_id, len(self._order)))

    def cited(self, segment_ids: Sequence[str], turn_ids: Sequence[str]) -> list[str]:
        """Item được trích; mục không có ``segment_ids`` thì lấy mọi item của các lượt bằng chứng."""

        if segment_ids:
            return self.ordered(segment_ids)
        return self.ordered(item_id for turn_id in turn_ids for item_id in self.items_of_turn.get(turn_id, ()))

    def original(self, item_ids: Iterable[str]) -> list[ItemId]:
        return [self._original.get(item_id, item_id) for item_id in item_ids]

    def turns(self, item_ids: Iterable[str]) -> list[str]:
        """Lượt nói chứa các item, không trùng, theo thứ tự."""

        return list(dict.fromkeys(self._turn_of_item[item_id] for item_id in item_ids if item_id in self._turn_of_item))

    def refs(self, item_ids: Iterable[str]) -> list[dict]:
        return [
            {
                "segment_id": self._original.get(item_id, item_id),
                "turn_id": self._turn_of_item[item_id],
                "text": self._text[item_id],
                "speaker_id": self._speaker_id.get(item_id),
            }
            for item_id in item_ids
            if item_id in self._turn_of_item
        ]

    def speaker_id_of_turn(self, turn_id: str | None) -> str | None:
        """``speaker_id`` (của transcript gốc) của item đầu tiên trong lượt, None nếu không có."""

        items = self.items_of_turn.get(turn_id or "", ())
        return self._speaker_id.get(items[0]) if items else None

    def speaker_id_of_name(self, speaker: str) -> str | None:
        """``speaker_id`` của người nói có nhãn ``speaker`` trong các lượt, None nếu không có."""

        return self._speaker_id_of_name.get(speaker)

    def item_count(self, turn_ids: Iterable[str]) -> int:
        return sum(len(self.items_of_turn.get(turn_id, ())) or 1 for turn_id in turn_ids)


def _citation(citations: _Citations, segment_ids: Sequence[str], turn_ids: Sequence[str]) -> dict:
    """``segment_ids`` (mã gốc), ``turn_ids`` và ``source_segment_refs`` của một mục."""

    items = citations.cited(segment_ids, turn_ids)
    return {
        "segment_ids": citations.original(items),
        "turn_ids": citations.turns(items) or list(turn_ids),
        "source_segment_refs": citations.refs(items),
    }


def _stable_id(prefix: str, parts: Iterable[str | None], used: set[str]) -> str:
    """``prefix`` + 16 hex đầu của sha256(``parts``); trùng thì thêm hậu tố ``_2``, ``_3``..."""

    digest = hashlib.sha256("\n".join(part or "" for part in parts).encode("utf-8")).hexdigest()[:16]
    candidate, suffix = f"{prefix}{digest}", 2
    while candidate in used:
        candidate, suffix = f"{prefix}{digest}_{suffix}", suffix + 1
    used.add(candidate)
    return candidate


def _due(raw: str | None, date_iso: str | None, kind: str | None) -> dict | None:
    return {"raw": raw, "date": date_iso, "kind": kind or "unknown"} if raw or date_iso else None


# ----- Giao việc -----

_EXPLICIT_STATUSES = frozenset({"assigned", "self_committed"})
_REVIEW_HINT_OF_VERIFICATION = {
    "consensus": "verifier_consensus",
    "verifier": "verifier_no_consensus",
    "debate": "verifier_consensus",
    "fallback": "verifier_failed",
}
# Trạng thái thực hiện của việc cũ theo trạng thái sau phiên họp ("mentioned"/"not_reported" giữ trạng thái trước).
_EXECUTION_STATUS = {
    "done": "done",
    "in_progress": "in_progress",
    "blocked": "blocked",
    "returned": "in_progress",
    "deferred": "deferred",
}


def _target(name: str | None, actor_type: str | None, ref_id: str | None, resolution: dict | None) -> dict:
    """Một bên nhận việc theo ``AssignmentTarget``: đơn vị, người, hoặc chưa rõ."""

    extensions = {"resolution": resolution}
    if actor_type == "organization":
        return {"target_type": "unit", "unit_id": ref_id, "unit_name": name, "extensions": extensions}
    if actor_type == "person":
        return {"target_type": "person", "person_id": ref_id, "person_name": name, "extensions": extensions}
    return {"target_type": "unknown", "name": name, "extensions": extensions}


def _candidates(candidates: Iterable) -> list[dict]:
    return [dataclasses.asdict(candidate) for candidate in candidates]


def _assignment_targets(item: ActionItemCandidate) -> tuple[dict | None, list[dict]]:
    """(bên chính, các bên còn lại) của một việc giao; bên chính là assignee đầu tiên (chủ trì trước).

    Việc chưa qua định danh actor (không phải ``ActionItemV3``, hoặc không có ``assignees``) lấy
    ``actor`` làm bên chính.
    """

    assignees = item.assignees if isinstance(item, ActionItemV3) else ()
    if not assignees:
        if not item.actor:
            return None, []
        resolution = {
            "mention": item.actor,
            "role": "lead",
            "flag": getattr(item, "actor_flag", None),
            "reason": getattr(item, "actor_reason", ""),
            "candidates": _candidates(getattr(item, "actor_candidates", ())),
        }
        return _target(item.actor, getattr(item, "actor_type", None), None, resolution), []
    targets = [
        _target(
            assignee.name or assignee.mention,
            assignee.actor_type if assignee.name else "unknown",
            assignee.ref_id,
            {
                "mention": assignee.mention,
                "role": assignee.role,
                "flag": assignee.flag,
                "reason": assignee.reason,
                "candidates": _candidates(assignee.candidates),
            },
        )
        for assignee in assignees
    ]
    return targets[0], targets[1:]


def _target_name(target: Mapping | None) -> str | None:
    if target is None:
        return None
    return target.get("unit_name") or target.get("person_name") or target.get("name")


def _new_task(item: ActionItemCandidate, citations: _Citations, context: MeetingContext, used_ids: set[str]) -> dict:
    """Một việc giao mới (hoặc tiếp nối việc cũ, ``relation`` = "follow_up") thành ``TaskOut``.

    ``task_id`` = "task_" + sha256(meeting_id, lượt chốt, bên chính)[:16], ổn định qua các lần tính
    khi lượt chốt và bên nhận việc không đổi.
    """

    primary, collaborators = _assignment_targets(item)
    confirm_turn_id = item.confirm_turn_id or next(iter(item.evidence_ids), None)
    task_id = _stable_id("task_", (context.meeting_id, confirm_turn_id, _target_name(primary)), used_ids)
    citation = _citation(citations, item.segment_ids, item.evidence_ids)
    due = _due(item.deadline_raw, item.deadline_date, item.deadline_kind)
    actor_flag = getattr(item, "actor_flag", None)
    relation = getattr(item, "relation", None)
    hints = []
    if actor_flag:
        hints.append(f"assignee_{actor_flag}")
    elif primary is None:
        hints.append("assignee_missing")
    if item.verification in _REVIEW_HINT_OF_VERIFICATION:
        hints.append(_REVIEW_HINT_OF_VERIFICATION[item.verification])
    if due and not due["date"]:
        hints.append("due_unresolved")
    references_extensions = {
        "source_event_id": None,
        "evidence_ids": citation["turn_ids"],
        "source_segment_refs": citation["source_segment_refs"],
    }
    speaker = next((turn.speaker for turn in context.turns if turn.turn_id == item.confirm_turn_id), None)
    return {
        "task_id": task_id,
        "source_uri": None,
        "extracted": {
            "content": {"title": item.text, "description": item.text},
            "assignment": {
                "primary": primary,
                "collaborators": collaborators,
                "assigned_by_speaker_id": citations.speaker_id_of_turn(item.confirm_turn_id),
            },
            "due": due,
            "priority": None,
            "detection": {
                "mode": "explicit" if item.status in _EXPLICIT_STATUSES else "inferred",
                "clarity": "clear" if item.verification == "rule" and primary is not None and not actor_flag else "unclear",
                "review_hints": hints,
            },
            "references": {"segment_ids": citation["segment_ids"], "confidence": None, "extensions": references_extensions},
            "progress": None,
        },
        "workflow": {
            "required_confirmations": ["content", "assignment.primary", *(["due"] if due else [])],
            "dependency_task_ids": [item.task_id] if relation == "follow_up" and item.task_id else [],
            "source_presence": "present",
        },
        "extensions": {
            **references_extensions,
            "topic_id": item.segment_id,
            "status": item.status,
            "verification": item.verification,
            "confirm_turn_id": item.confirm_turn_id,
            "relation": relation,
            "assigned_by_speaker": speaker,
        },
    }


def _party_target(party: TaskParty, roster: AttendeeRoster | None) -> dict:
    """Một bên của việc cũ: mã người/đơn vị trong danh sách tham dự thì ra người/đơn vị, tên tự do thì chưa rõ."""

    if roster is not None and party.ref_id:
        if any(person.person_id == party.ref_id for person in roster.people):
            return _target(party.name, "person", party.ref_id, None)
        if roster.find_organization(party.ref_id) is not None:
            return _target(party.name, "organization", party.ref_id, None)
    return _target(party.name, None, party.ref_id, None)


def _progress_step(update: ProgressUpdate, deciding: ProgressUpdate | None, citations: _Citations) -> dict:
    citation = _citation(citations, update.segment_ids, update.evidence_ids)
    return {
        "topic_id": update.segment_id,
        "status": update.status,
        "status_turn_id": update.status_turn_id,
        "summary": update.summary,
        "blockers": list(update.blockers),
        "directive": update.directive,
        "due": _due(update.deadline_raw, update.deadline_date, update.deadline_kind),
        "deadline_removed": update.deadline_removed,
        "proposed_status": update.proposed_status,
        "status_flag": update.status_flag,
        "verification": update.verification,
        "reason": update.reason,
        "p_directive": update.p_directive,
        "deciding": update == deciding,
        "segment_ids": citation["segment_ids"],
        "turn_ids": citation["turn_ids"],
    }


def _backlog_task(
    progress: TaskProgress,
    merged: Sequence[ActionItemCandidate],
    task: AgendaTask | None,
    citations: _Citations,
    context: MeetingContext,
) -> dict:
    """Một việc cũ trong danh sách cần báo cáo thành ``TaskOut``, gộp lời giao lại/dời hạn của cuộc họp.

    Đầu vào: progress - tiến độ sau phiên họp; merged - việc giao có ``relation`` "reassign" /
        "reschedule" trỏ về việc này, theo thứ tự lượt nói; task - việc trong danh sách.
    """

    reassign = next((item for item in reversed(merged) if item.relation == "reassign"), None)
    reschedule = next((item for item in reversed(merged) if item.relation == "reschedule"), None)
    changed = reassign or reschedule
    deciding = progress.deciding_update

    if reassign is not None:
        primary, collaborators = _assignment_targets(reassign)
    elif task is not None:
        primary = _party_target(task.owner, context.roster)
        collaborators = [_party_target(party, context.roster) for party in task.support]
    else:
        primary, collaborators = _target(progress.owner, None, None, None), []

    if progress.deadline_removed:
        due = None
    else:
        due = (
            (reschedule and _due(reschedule.deadline_raw, reschedule.deadline_date, reschedule.deadline_kind))
            or _due(progress.deadline_raw, progress.deadline_date, progress.deadline_kind)
            or _due(None, progress.previous_due, "exact")
        )

    item_ids = [item_id for update in progress.updates for item_id in citations.cited(update.segment_ids, update.evidence_ids)]
    item_ids += [item_id for item in merged for item_id in citations.cited(item.segment_ids, item.evidence_ids)]
    items = citations.ordered(item_ids)
    references_extensions = {
        "source_event_id": None,
        "evidence_ids": citations.turns(items),
        "source_segment_refs": citations.refs(items),
    }
    present = bool(progress.updates or merged)
    hints = [
        hint
        for hint, flagged in (
            ("status_uncertain", progress.uncertain),
            ("status_conflict", progress.status_conflict),
            ("overdue", progress.overdue),
            ("not_reported", progress.status == "not_reported"),
        )
        if flagged
    ]
    confirmations = [
        *(["progress"] if present else []),
        *(["assignment.primary"] if reassign is not None else []),
        *(["due"] if reschedule is not None or progress.deadline_raw or progress.deadline_removed else []),
    ]
    confirm_turn_id = changed.confirm_turn_id if changed else None
    return {
        "task_id": progress.task_id,
        "source_uri": None,
        "extracted": {
            "content": {"title": progress.title, "description": (deciding.summary if deciding else "") or progress.title},
            "assignment": {
                "primary": primary,
                "collaborators": collaborators,
                "assigned_by_speaker_id": citations.speaker_id_of_turn(confirm_turn_id),
            },
            "due": due,
            "priority": None,
            "detection": {
                "mode": "backlog",
                "clarity": "unclear" if progress.uncertain or progress.status_conflict else "clear",
                "review_hints": hints,
            },
            "references": {"segment_ids": citations.original(items), "confidence": None, "extensions": references_extensions},
            "progress": {
                "previous_status": progress.previous_status,
                "status": progress.status,
                "previous_due": progress.previous_due,
                "status_conflict": progress.status_conflict,
                "uncertain": progress.uncertain,
                "overdue": progress.overdue,
                "summary": deciding.summary if deciding else "",
                "blockers": list(deciding.blockers) if deciding else [],
                "directive": deciding.directive if deciding else "",
                "deadline_removed": progress.deadline_removed,
                "updates": [_progress_step(update, deciding, citations) for update in progress.updates],
            },
        },
        "workflow": {
            "execution_status": _EXECUTION_STATUS.get(progress.status, progress.previous_status or "not_started"),
            "required_confirmations": confirmations,
            "source_presence": "present" if present else "absent",
        },
        "extensions": {
            **references_extensions,
            "topic_id": deciding.segment_id if deciding else None,
            "status": progress.status,
            "verification": deciding.verification if deciding else None,
            "confirm_turn_id": confirm_turn_id or (deciding.status_turn_id if deciding else None),
            "relation": "backlog",
            "merged_relations": [item.relation for item in merged],
            "assigned_by_speaker": next(
                (turn.speaker for turn in context.turns if confirm_turn_id and turn.turn_id == confirm_turn_id), None
            ),
        },
    }


def _tasks_data(report: MeetingReport, context: MeetingContext, citations: _Citations) -> dict:
    """``data.tasks``: việc giao mới theo thứ tự lượt nói, rồi việc cũ theo thứ tự danh sách.

    Việc giao "reassign"/"reschedule" được gộp vào việc cũ tương ứng; "follow_up" là việc riêng có
    ``dependency_task_ids`` trỏ về việc cũ.
    """

    backlog_ids = {progress.task_id for progress in report.task_progress}
    merged: dict[str, list[ActionItemCandidate]] = {}
    used_ids = set(backlog_ids)
    tasks = []
    for item in report.assignments:
        if item.task_id in backlog_ids and getattr(item, "relation", None) in ("reassign", "reschedule"):
            merged.setdefault(item.task_id, []).append(item)
        else:
            tasks.append(_new_task(item, citations, context, used_ids))
    agenda = context.agenda or TaskAgenda()
    tasks += [
        _backlog_task(progress, merged.get(progress.task_id, []), agenda.find(progress.task_id), citations, context)
        for progress in report.task_progress
    ]
    return {"tasks": tasks}


# ----- Kết luận -----


def _format_date(value: str | None) -> str:
    """"YYYY-MM-DD" -> "dd/mm/yyyy" (như ``ngay_hop`` của biên bản); rỗng nếu không có."""

    if not value:
        return ""
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return value


def _decisions_header(context: MeetingContext) -> dict:
    """Thông tin biên bản từ ngày họp, người chủ trì và danh sách tham dự."""

    roster = context.roster or AttendeeRoster()
    members = []
    for person in roster.people:
        organization = roster.find_organization(person.org_id)
        details = ", ".join(part for part in (person.position, organization.name if organization else "") if part)
        members.append(f"{person.full_name} ({details})" if details else person.full_name)
    people = len(roster.people) or None
    return {
        "ngay_hop": _format_date(context.meeting_date),
        "chu_tri": context.chair or "",
        "thanh_phan": "; ".join(members),
        "so_nguoi_tham_gia": people,
        "so_nguoi_co_mat": people,
    }


def _decisions_data(report: MeetingReport, context: MeetingContext, citations: _Citations) -> dict:
    used_ids: set[str] = set()
    items = []
    for index, decision in enumerate(report.decisions, start=1):
        citation = _citation(citations, decision.segment_ids, decision.evidence_ids)
        confirm_turn_id = decision.confirm_turn_id or next(iter(decision.evidence_ids), None)
        items.append(
            {
                "so_thu_tu": index,
                "noi_dung": decision.text,
                "segment_ids": citation["segment_ids"],
                "original_segment_ids": list(citation["segment_ids"]),
                "turn_ids": citation["turn_ids"],
                "extensions": {
                    "decision_id": _stable_id(
                        "decision_", (context.meeting_id, decision.segment_id, confirm_turn_id), used_ids
                    ),
                    "topic_id": decision.segment_id,
                    "status": decision.status,
                    "verification": decision.verification,
                    "confirm_turn_id": decision.confirm_turn_id,
                    "source_segment_refs": citation["source_segment_refs"],
                },
            }
        )
    return {"header": _decisions_header(context), "items": items}


# ----- Diễn biến -----


def _discussion_point(point: DiscussionPoint, point_id: str, citations: _Citations) -> dict:
    citation = _citation(citations, point.segment_ids, point.evidence_ids)
    return {
        "point_id": point_id,
        "text": point.text,
        "speakers": list(point.speakers),
        "speaker_ids": [citations.speaker_id_of_name(speaker) for speaker in point.speakers],
        **citation,
    }


def _content_data(report: MeetingReport, context: MeetingContext, citations: _Citations) -> dict:
    labels = {label.segment_id: label for label in context.labels}
    points: dict[str, list[DiscussionPoint]] = {}
    for point in report.meeting_development:
        points.setdefault(point.segment_id, []).append(point)
    topics = []
    for order, segment in enumerate(context.segments, start=1):
        label = labels.get(segment.segment_id)
        turn_ids = list(segment.atom_ids or ())
        items = [item_id for turn_id in turn_ids for item_id in citations.items_of_turn.get(turn_id, ())]
        topics.append(
            {
                "topic_id": segment.segment_id,
                "order": order,
                "extracted": {
                    "content": {"title": label.title if label else "", "summary": label.summary if label else ""},
                    "span": {
                        "segment_ids": citations.original([items[0], items[-1]]) if items else [],
                        "turn_ids": [turn_ids[0], turn_ids[-1]] if turn_ids else [],
                    },
                    "discussion_points": [
                        _discussion_point(point, f"{segment.segment_id}:{index}", citations)
                        for index, point in enumerate(points.get(segment.segment_id, []), start=1)
                    ],
                },
                "extensions": {
                    "segmentation_method": segment.segmentation_method,
                    "boundary_score": segment.boundary_score,
                },
            }
        )
    turns = [
        {
            "turn_id": turn.turn_id,
            "speaker": turn.speaker,
            "speaker_id": citations.speaker_id_of_turn(turn.turn_id),
            "segment_ids": citations.original(citations.items_of_turn.get(turn.turn_id, ())),
            "text": turn.text_exact,
        }
        for turn in context.turns
    ]
    return {"topics": topics, "turns": turns}


# ----- Audit và độ phủ -----


def _verification_record(record: VerificationRecord) -> dict:
    """Bản ghi Verifier theo ``VerificationRecordOut`` (các vòng không lặp lại chuỗi tra cứu)."""

    return {
        "item_key": record.item_key,
        "segment_id": record.segment_id,
        "kind": record.kind,
        "candidate_text": record.candidate_text,
        "reasons": list(record.reasons),
        "steps": [dataclasses.asdict(step) for step in record.steps],
        "verdict": record.verdict,
        "reasoning": record.reasoning,
        "final_text": record.final_text,
        "deciding_turn_id": record.deciding_turn_id,
        "decided_by": record.decided_by,
        "rounds": [
            {
                "candidate_text": round_.candidate_text,
                "verdict": round_.verdict,
                "feedback": round_.feedback,
                "deciding_turn_id": round_.deciding_turn_id,
                "stance": round_.stance,
                "response": round_.response,
            }
            for round_ in record.rounds
        ],
    }


def _audit(report: MeetingReport) -> dict:
    return {
        "verification_records": [_verification_record(record) for record in report.verification_records],
        "skipped_agents": [{"segment_id": s.segment_id, "agent": s.agent} for s in report.skipped_agents],
        "failed_topics": [{"segment_id": f.segment_id, "agent": f.agent, "error": f.error} for f in report.failures],
    }


def _coverage(report: MeetingReport, context: MeetingContext, citations: _Citations) -> dict:
    """Số item thuộc các chủ đề mà mọi agent của document đều chạy xong / tổng số item."""

    failed_topics = {failure.segment_id for failure in report.failures}
    total = processed = 0
    for segment in context.segments:
        count = citations.item_count(segment.atom_ids or ())
        total += count
        processed += 0 if segment.segment_id in failed_topics else count
    return {"is_complete": not report.failures, "processed_segment_count": processed, "total_segment_count": total}


_DOCUMENT_TYPES = {"tasks": "meeting_tasks", "decisions": "meeting_decisions", "content": "meeting_content"}
_DATA_BUILDERS = {"tasks": _tasks_data, "decisions": _decisions_data, "content": _content_data}
_MODELS: dict[str, type[_DocumentOut]] = {"tasks": TasksDocument, "decisions": DecisionsDocument, "content": ContentDocument}


def build_document_entry(document: str, report: MeetingReport, context: MeetingContext) -> dict:
    """Phần nội dung của document từ kết quả một lần ``analyze`` (lưu vào cache).

    Đầu vào: document - tasks | decisions | content; report - ``MeetingReport`` của lần tính chỉ
        gồm các phần của document này; context - nền và thông tin request.
    Đầu ra: dict JSON gồm ``data``, ``audit``, ``coverage``, ``warnings`` và ``complete`` (không có
        chủ đề lỗi).
    """

    citations = _Citations(context.turns, context.items)
    return {
        "complete": not report.failures,
        "data": _DATA_BUILDERS[document](report, context, citations),
        "audit": _audit(report),
        "coverage": _coverage(report, context, citations),
        "warnings": [
            {"code": "topic_failed", "topic_id": f.segment_id, "agent": f.agent, "message": f.error}
            for f in report.failures
        ],
    }


def build_document(
    document: str,
    *,
    analysis_key: str,
    document_key: str,
    meeting_id: str,
    entry: Mapping,
    source: Mapping | None,
) -> dict:
    """Document đủ khung từ mục cache (``build_document_entry`` + thông tin lần tính).

    Đầu vào:
        document: tasks | decisions | content.
        analysis_key: khoá bản phân tích (``extensions.input_fingerprint``).
        document_key: tên mục cache của document (``extensions.document_key``).
        meeting_id: mã cuộc họp của nền.
        entry: mục document (``data``, ``audit``, ``coverage``, ``warnings``, ``version``,
            ``generation``, ``computed_at``, ``source``).
        source: ``source`` của request hiện tại; None thì dùng bản lưu cùng document.
    Đầu ra: dict theo ``TasksDocument`` | ``DecisionsDocument`` | ``ContentDocument``, đã qua model
        (đủ mọi trường mặc định, giống hệt response của API).
    """

    document_dict = {
        "schema_version": SCHEMA_VERSION,
        "document_type": _DOCUMENT_TYPES[document],
        "meeting_id": meeting_id,
        "artifact_revision": entry["generation"],
        "source": dict(source or entry.get("source") or {}),
        "generation": {
            "status": "complete" if entry["complete"] else "partial",
            "generated_at": entry["computed_at"],
            "coverage": entry["coverage"],
            "warnings": entry["warnings"],
            "confidence": None,
        },
        "data": entry["data"],
        "extensions": {
            "input_fingerprint": analysis_key,
            "document_key": document_key,
            "model": os.environ.get("MODEL_NAME") or None,
            "citation_namespace": CITATION_NAMESPACE,
            "task_identity_strategy": TASK_IDENTITY_STRATEGY if document == "tasks" else None,
            "artifact_version_id": entry["version"],
            "audit": entry["audit"],
        },
    }
    return _MODELS[document].model_validate(document_dict).model_dump(mode="json")


__all__ = [
    "CITATION_NAMESPACE",
    "ContentDocument",
    "DecisionsDocument",
    "MeetingContext",
    "MeetingDocument",
    "SourceIn",
    "TasksDocument",
    "build_document",
    "build_document_entry",
]
