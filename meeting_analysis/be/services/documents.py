"""Ba document kết quả của API v3 (``POST /v3/meetings/tasks|decisions|content``).

Mọi document cùng một khung (theo ``outputs/giaoviec.json``)::

    schema_version, document_type, meeting_id, artifact_revision,
    source, generation, data

``data`` khác nhau theo document:
    tasks      ``data.tasks``: việc giao mới + việc cũ (backlog) cập nhật tiến độ.
    decisions  ``data.items``: các kết luận.
    content    ``data.topics``: các chủ đề, mỗi chủ đề có tiêu đề, tóm tắt, khoảng item và ý thảo luận.

Trích dẫn ở mức item transcript thô: ``segment_ids`` là ``id`` gốc của item trong request (giữ
kiểu: số khi xuất từ STT), kèm ``turn_ids`` (lượt nói chứa các item đó).

Hai bước:
    ``build_document_entry``  lúc tính: ``MeetingReport`` của lần ``analyze`` -> ``data`` + độ phủ của
                              document (dict JSON, ``pipeline_v3`` lưu vào cache).
    ``build_document``        lúc trả response: mục cache -> document đủ khung (đã qua model).
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel

from src.pipeline.shared.meeting_inputs.agenda import AgendaTask, TaskAgenda, TaskParty
from src.pipeline.shared.meeting_inputs.attendees import AttendeeRoster
from src.pipeline.shared.schemas import (
    ActionItemCandidate,
    ActionItem,
    ActorAssignee,
    DiscussionPoint,
    MeetingReport,
    ProgressUpdate,
    TaskProgress,
)
from src.utils.contracts import SpeakerTurn, TopicLabel, TopicSegment

SCHEMA_VERSION = "1.0"

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


class _DocumentOut(BaseModel):
    """Khung chung của ba document."""

    schema_version: str = SCHEMA_VERSION
    meeting_id: str
    artifact_revision: int
    source: SourceIn
    generation: GenerationOut


# ----- Giao việc -----


class AssignmentResolutionOut(BaseModel):
    """Cách định danh một bên nhận việc (``src/pipeline/shared/actors/resolution.py``).

    ``role``: "lead" | "support" | "joint"; ``flag``: "ambiguous" | "missing" | None.
    """

    mention: str | None = None
    role: str = "lead"
    flag: str | None = None
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


class ReferenceExtensionsOut(BaseModel):
    """``evidence_ids``: các turn_id; ``source_segment_refs``: từng item trích kèm nguyên văn."""

    source_event_id: str | None = None
    evidence_ids: list[str] = []
    source_segment_refs: list[SegmentRefOut] = []


class TaskReferencesOut(BaseModel):
    segment_ids: list[ItemId] = []
    confidence: float | None = None
    extensions: ReferenceExtensionsOut = ReferenceExtensionsOut()


class ProgressUpdateOut(BaseModel):
    """Một lời nói về việc cũ trong MỘT chủ đề: báo cáo, chỉ đạo, đổi/bỏ hạn hoặc giao cho bên khác.

    ``primary``/``collaborators``: bên nhận việc mới khi lời này giao việc cho bên khác (theo agent
    khai, chưa định danh), không thì null/[]. ``deciding``: lời quyết định trạng thái của việc.
    ``flag``: "uncertain" khi Decisions không xác nhận trạng thái agent khai.
    """

    topic_id: str
    status: str
    summary: str = ""
    directive: str = ""
    blockers: list[str] = []
    due: DueOut | None = None
    deadline_extended: bool = False
    primary: AssignmentTarget | None = None
    collaborators: list[AssignmentTarget] = []
    deciding: bool = False
    flag: str | None = None
    verification: str | None = None
    segment_ids: list[ItemId] = []
    turn_ids: list[str] = []


class TaskProgressOut(BaseModel):
    """Tiến độ của việc cũ sau phiên họp.

    ``updates``: mọi lời nói về việc này trong phiên, theo thứ tự lượt nói. ``reassigned``: việc được
    giao cho bên khác (``extracted.assignment`` là bên mới).
    """

    previous_status: str | None = None
    status: str
    previous_due: str | None = None
    status_conflict: bool = False
    uncertain: bool = False
    overdue: bool = False
    reassigned: bool = False
    summary: str = ""
    blockers: list[str] = []
    directive: str = ""
    deadline_extended: bool = False
    updates: list[ProgressUpdateOut] = []


class TaskExtractedOut(BaseModel):
    content: TaskContentOut
    assignment: TaskAssignmentOut
    due: DueOut | None = None
    priority: str | None = None
    references: TaskReferencesOut
    progress: TaskProgressOut | None = None


class TaskOut(BaseModel):
    task_id: str
    source_uri: str | None = None
    extracted: TaskExtractedOut


class TasksDataOut(BaseModel):
    tasks: list[TaskOut]


class TasksDocument(_DocumentOut):
    """``POST /v3/meetings/tasks``: việc giao mới và tiến độ việc cũ (theo ``outputs/giaoviec.json``)."""

    document_type: Literal["meeting_tasks"] = "meeting_tasks"
    data: TasksDataOut


# ----- Kết luận -----


class DecisionItemOut(BaseModel):
    """Một kết luận: ``id`` là số thứ tự trong cuộc họp (từ 1). ``original_segment_ids`` giữ trích
    dẫn gốc khi người duyệt sửa ``segment_ids``."""

    id: int
    content: str
    segment_ids: list[ItemId]
    original_segment_ids: list[ItemId]
    turn_ids: list[str]


class DecisionsDataOut(BaseModel):
    items: list[DecisionItemOut]


class DecisionsDocument(_DocumentOut):
    """``POST /v3/meetings/decisions``: kết luận cuộc họp."""

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
        roster: danh sách tham dự, None nếu không có.
        agenda: danh sách việc cần báo cáo, None nếu không có (hoặc document không dùng).
    """

    meeting_id: str
    turns: tuple[SpeakerTurn, ...]
    segments: tuple[TopicSegment, ...]
    labels: tuple[TopicLabel, ...]
    items: Sequence[Mapping]
    meeting_date: str | None = None
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
        self._speaker_id_of_turn: dict[str, str | None] = {}
        self._speaker_id_of_name: dict[str, str] = {}
        for turn in turns:
            self.items_of_turn[turn.turn_id] = tuple(item_id for item_id, _ in turn.source_items)
            items = self.items_of_turn[turn.turn_id]
            speaker_id = turn.speaker_id or (self._speaker_id.get(items[0]) if items else None)
            self._speaker_id_of_turn[turn.turn_id] = speaker_id
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
        """``speaker_id`` của lượt (``SpeakerTurn.speaker_id``, thiếu thì của item đầu), None nếu không có."""

        return self._speaker_id_of_turn.get(turn_id or "")

    def speaker_id_of_name(self, speaker: str) -> str | None:
        """``speaker_id`` của người nói có nhãn ``speaker`` trong các lượt, None nếu không có.

        Nhãn là duy nhất theo người (người trùng họ tên đã được thêm hậu tố " #2" khi dựng lượt nói).
        """

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

    Việc chưa qua định danh actor (không phải ``ActionItem``, hoặc không có ``assignees``) lấy
    ``actor`` làm bên chính.
    """

    assignees = item.assignees if isinstance(item, ActionItem) else ()
    if not assignees:
        if not item.actor:
            return None, []
        resolution = {
            "mention": item.actor,
            "role": "lead",
            "flag": getattr(item, "actor_flag", None),
            "candidates": _candidates(getattr(item, "actor_candidates", ())),
        }
        return _target(item.actor, getattr(item, "actor_type", None), None, resolution), []
    return _assignee_targets(assignees)


def _assignee_targets(assignees: Sequence[ActorAssignee]) -> tuple[dict | None, list[dict]]:
    """(bên chính, các bên còn lại) từ các bên đã định danh; không có bên nào thì (None, [])."""

    targets = [
        _target(
            assignee.name or assignee.mention,
            assignee.actor_type if assignee.name else "unknown",
            assignee.ref_id,
            {
                "mention": assignee.mention,
                "role": assignee.role,
                "flag": assignee.flag,
                "candidates": _candidates(assignee.candidates),
            },
        )
        for assignee in assignees
    ]
    return (targets[0], targets[1:]) if targets else (None, [])


def _target_name(target: Mapping | None) -> str | None:
    if target is None:
        return None
    return target.get("unit_name") or target.get("person_name") or target.get("name")


def _new_task(item: ActionItemCandidate, citations: _Citations, context: MeetingContext, used_ids: set[str]) -> dict:
    """Một việc giao mới thành ``TaskOut``.

    ``task_id`` = "task_" + sha256(meeting_id, lượt chốt, bên chính)[:16], ổn định qua các lần tính
    khi lượt chốt và bên nhận việc không đổi.
    """

    primary, collaborators = _assignment_targets(item)
    confirm_turn_id = item.confirm_turn_id or next(iter(item.evidence_turn_ids), None)
    task_id = _stable_id("task_", (context.meeting_id, confirm_turn_id, _target_name(primary)), used_ids)
    citation = _citation(citations, item.item_ids, item.evidence_turn_ids)
    due = _due(item.deadline_raw, item.deadline_date, item.deadline_kind)
    references_extensions = {
        "source_event_id": None,
        "evidence_ids": citation["turn_ids"],
        "source_segment_refs": citation["source_segment_refs"],
    }
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
            "references": {"segment_ids": citation["segment_ids"], "confidence": None, "extensions": references_extensions},
            "progress": None,
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


def _progress_update(update: ProgressUpdate, deciding: bool, citations: _Citations) -> dict:
    """Một cập nhật của việc cũ thành ``ProgressUpdateOut``."""

    targets = [_target(mention.name, None, None, None) for mention in update.mentions]
    citation = _citation(citations, update.item_ids, update.evidence_turn_ids)
    return {
        "topic_id": update.segment_id,
        "status": update.status,
        "summary": update.summary,
        "directive": update.directive,
        "blockers": list(update.blockers),
        "due": _due(update.deadline_raw, update.deadline_date, update.deadline_kind),
        "deadline_extended": update.deadline_extended,
        "primary": targets[0] if targets else None,
        "collaborators": targets[1:],
        "deciding": deciding,
        "flag": "uncertain" if update.verification == "fallback" else None,
        "verification": update.verification,
        "segment_ids": citation["segment_ids"],
        "turn_ids": citation["turn_ids"],
    }


def _backlog_task(
    progress: TaskProgress, task: AgendaTask | None, citations: _Citations, context: MeetingContext
) -> dict:
    """Một việc cũ trong danh sách cần báo cáo thành ``TaskOut``.

    Bên nhận việc là bên mới khi cuộc họp giao việc cho bên khác (``progress.assignees``), không
    thì bên cũ; hạn là hạn mới, không thì hạn cũ (cả khi gia hạn chưa có hạn mới: người dùng sửa sau).
    """

    deciding = progress.deciding_update
    if progress.assignees:
        primary, collaborators = _assignee_targets(progress.assignees)
    elif task is not None:
        primary = _party_target(task.owner, context.roster)
        collaborators = [_party_target(party, context.roster) for party in task.support]
    else:
        primary, collaborators = _target(progress.owner, None, None, None), []

    due = _due(progress.deadline_raw, progress.deadline_date, progress.deadline_kind) or _due(
        None, progress.previous_due, "exact"
    )

    items = citations.ordered(
        item_id for update in progress.updates for item_id in citations.cited(update.item_ids, update.evidence_turn_ids)
    )
    references_extensions = {
        "source_event_id": None,
        "evidence_ids": citations.turns(items),
        "source_segment_refs": citations.refs(items),
    }
    reassign = progress.reassign_update
    return {
        "task_id": progress.task_id,
        "source_uri": None,
        "extracted": {
            "content": {"title": progress.title, "description": (deciding.summary if deciding else "") or progress.title},
            "assignment": {
                "primary": primary,
                "collaborators": collaborators,
                "assigned_by_speaker_id": citations.speaker_id_of_turn(reassign.status_turn_id if reassign else None),
            },
            "due": due,
            "priority": None,
            "references": {"segment_ids": citations.original(items), "confidence": None, "extensions": references_extensions},
            "progress": {
                "previous_status": progress.previous_status,
                "status": progress.status,
                "previous_due": progress.previous_due,
                "status_conflict": progress.status_conflict,
                "uncertain": progress.uncertain,
                "overdue": progress.overdue,
                "reassigned": bool(progress.assignees),
                "summary": deciding.summary if deciding else "",
                "blockers": list(deciding.blockers) if deciding else [],
                "directive": deciding.directive if deciding else "",
                "deadline_extended": progress.deadline_extended,
                "updates": [_progress_update(update, update is deciding, citations) for update in progress.updates],
            },
        },
    }


def _tasks_data(report: MeetingReport, context: MeetingContext, citations: _Citations) -> dict:
    """``data.tasks``: việc giao mới theo thứ tự lượt nói, rồi việc cũ theo thứ tự danh sách."""

    used_ids = {progress.task_id for progress in report.task_progress}
    tasks = [_new_task(item, citations, context, used_ids) for item in report.assignments]
    agenda = context.agenda or TaskAgenda()
    tasks += [
        _backlog_task(progress, agenda.find(progress.task_id), citations, context) for progress in report.task_progress
    ]
    return {"tasks": tasks}


# ----- Kết luận -----


def _decisions_data(report: MeetingReport, context: MeetingContext, citations: _Citations) -> dict:
    items = []
    for index, decision in enumerate(report.decisions, start=1):
        citation = _citation(citations, decision.item_ids, decision.evidence_turn_ids)
        items.append(
            {
                "id": index,
                "content": decision.text,
                "segment_ids": citation["segment_ids"],
                "original_segment_ids": list(citation["segment_ids"]),
                "turn_ids": citation["turn_ids"],
            }
        )
    return {"items": items}


# ----- Diễn biến -----


def _discussion_point(point: DiscussionPoint, point_id: str, citations: _Citations) -> dict:
    citation = _citation(citations, point.item_ids, point.evidence_turn_ids)
    return {
        "point_id": point_id,
        "text": point.text,
        "speakers": list(point.speakers),
        # Mã lấy từ lượt nói được trích; thiếu (bản phân tích cũ trong cache, lượt không mã) thì tra theo tên.
        "speaker_ids": [
            (point.speaker_ids[index] if index < len(point.speaker_ids) else None)
            or citations.speaker_id_of_name(speaker)
            for index, speaker in enumerate(point.speakers)
        ],
        **citation,
    }


def _content_data(report: MeetingReport, context: MeetingContext, citations: _Citations) -> dict:
    labels = {label.segment_id: label for label in context.labels}
    points: dict[str, list[DiscussionPoint]] = {}
    for point in report.discussion_points:
        points.setdefault(point.segment_id, []).append(point)
    topics = []
    for order, segment in enumerate(context.segments, start=1):
        label = labels.get(segment.segment_id)
        turn_ids = list(segment.turn_ids or ())
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


# ----- Độ phủ -----


def _coverage(report: MeetingReport, context: MeetingContext, citations: _Citations) -> dict:
    """Số item thuộc các chủ đề mà mọi agent của document đều chạy xong / tổng số item."""

    failed_topics = {failure.segment_id for failure in report.failures}
    total = processed = 0
    for segment in context.segments:
        count = citations.item_count(segment.turn_ids or ())
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
    Đầu ra: dict JSON gồm ``data``, ``coverage``, ``warnings`` và ``complete`` (không có chủ đề lỗi).
    """

    citations = _Citations(context.turns, context.items)
    return {
        "complete": not report.failures,
        "data": _DATA_BUILDERS[document](report, context, citations),
        "coverage": _coverage(report, context, citations),
        "warnings": [
            {"code": "topic_failed", "topic_id": f.segment_id, "agent": f.agent, "message": f.error}
            for f in report.failures
        ],
    }


def build_document(
    document: str,
    *,
    meeting_id: str,
    entry: Mapping,
    source: Mapping | None,
) -> dict:
    """Document đủ khung từ mục cache (``build_document_entry`` + thông tin lần tính).

    Đầu vào:
        document: tasks | decisions | content.
        meeting_id: mã cuộc họp của nền.
        entry: mục document (``data``, ``coverage``, ``warnings``, ``generation``, ``computed_at``,
            ``source``).
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
    }
    return _MODELS[document].model_validate(document_dict).model_dump(mode="json")


__all__ = [
    "ContentDocument",
    "DecisionsDocument",
    "MeetingContext",
    "MeetingDocument",
    "SourceIn",
    "TasksDocument",
    "build_document",
    "build_document_entry",
]
