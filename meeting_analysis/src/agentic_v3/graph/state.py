"""Trạng thái LangGraph của v3: graph cha (cả cuộc họp) và subgraph (MỘT chủ đề).

Mỗi chủ đề chạy trong một subgraph riêng với state riêng (``TopicState``), nên không
còn con trỏ ``next_segment_index``, dấu hoàn thành ``completed_*_topics`` hay
``pending_debate_tasks`` dùng chung như v1 -- chúng tồn tại chỉ để tuần tự hoá và
chống lặp. Subgraph chỉ trả ra các khoá của ``TopicOutput``; graph cha cộng dồn
chúng (``operator.add``) từ mọi chủ đề, theo thứ tự HOÀN THÀNH (không xác định) --
``finalize`` sắp lại theo thứ tự chủ đề.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from ..core.schemas import (
    ActionItemCandidate,
    DecisionCandidate,
    DiscussionPoint,
    SegmentTask,
    TopicFailure,
)
from ...utils.contracts import SpeakerTurn, TopicLabel, TopicSegment
from ..actors.agenda import TaskAgenda
from ..actors.attendees import AttendeeRoster
from ..schemas import (
    AnalysisPart,
    MeetingReport,
    ProgressUpdate,
    SkippedAgent,
    SpeakerRegistry,
    VerificationRecord,
    VerifyTask,
)


class TopicInput(TypedDict):
    """Gói ``Send`` cho subgraph một chủ đề."""

    segment: TopicSegment
    turns: tuple[SpeakerTurn, ...]  # lượt nói của chủ đề
    meeting_turns: tuple[SpeakerTurn, ...]  # lượt nói của cả cuộc họp (cho tool Verifier)
    registry: SpeakerRegistry
    meeting_date: str | None  # ngày họp ISO, neo chuẩn hoá hạn chót của Action agent
    parts: frozenset[AnalysisPart]  # phần kết quả cần tính: chọn agent trích xuất nào được chạy
    preset_label: TopicLabel | None  # nhãn đã có thì dùng lại, None thì gán nhãn bằng LLM


class TopicOutput(TypedDict):
    """Các khoá subgraph trả về graph cha; cùng tên và reducer với ``MeetingStateV3``."""

    labels: Annotated[list[TopicLabel], operator.add]
    meeting_development: Annotated[list[DiscussionPoint], operator.add]
    verified_assignments: Annotated[list[ActionItemCandidate], operator.add]
    verified_decisions: Annotated[list[DecisionCandidate], operator.add]
    verification_records: Annotated[list[VerificationRecord], operator.add]
    topic_failures: Annotated[list[TopicFailure], operator.add]
    skipped_agents: Annotated[list[SkippedAgent], operator.add]
    progress_updates: Annotated[list[ProgressUpdate], operator.add]  # đã kiểm (evidence_check)


class TopicState(TopicInput, TopicOutput):
    """State nội bộ của subgraph một chủ đề.

    ``task`` là gói ``SegmentTask`` kiểu v1 (có title/summary sau khi gán nhãn) để gọi
    lại nguyên các agent trích xuất của v1. ``run_commit_agents`` do ``plan_topic`` ghi: có chạy
    Action/Decision agent ở chủ đề này không. ``pending_verify`` ghi đè, chỉ đọc ngay sau
    ``evidence_check``.
    """

    task: SegmentTask
    run_commit_agents: bool
    action_candidates_raw: Annotated[list[ActionItemCandidate], operator.add]
    decision_candidates_raw: Annotated[list[DecisionCandidate], operator.add]
    progress_updates_raw: Annotated[list[ProgressUpdate], operator.add]
    pending_verify: tuple[VerifyTask, ...]


class MeetingStateV3(TopicOutput):
    """State của graph cha.

    Nhóm đầu vào: ``meeting_id``, ``revision_id``, ``meeting_date``, ``segments``, ``turns_by_id``,
    ``attendee_roster`` (danh sách tham dự, None nếu không có), ``task_agenda`` (danh sách việc
    cần báo cáo tiến độ, None nếu không có), ``parts`` (phần kết quả cần tính) và
    ``preset_labels`` (nhãn đã có theo segment_id, rỗng thì gán nhãn trong từng chủ đề).
    Nhóm Planner: ``registry``.
    Nhóm kết quả cộng dồn từ các chủ đề: các khoá của ``TopicOutput``.
    Kết quả cuối: ``report``.
    """

    meeting_id: str
    revision_id: str
    meeting_date: str | None
    chair: str | None  # người chủ trì phiên họp cung cấp; Planner đưa vào ``registry``
    segments: tuple[TopicSegment, ...]
    turns_by_id: dict[str, SpeakerTurn]
    attendee_roster: AttendeeRoster | None
    task_agenda: TaskAgenda | None
    parts: frozenset[AnalysisPart]
    preset_labels: dict[str, TopicLabel]
    registry: SpeakerRegistry
    report: MeetingReport | None


__all__ = ["MeetingStateV3", "TopicInput", "TopicOutput", "TopicState"]
