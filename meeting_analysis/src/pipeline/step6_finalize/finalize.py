"""Tổng hợp kết quả mọi chủ đề thành báo cáo cuộc họp (bước 6): sắp theo thứ tự chủ đề, xác định bên
nhận cho các việc chưa được xác định, gộp mục trùng, đối chiếu kết luận, và gộp tiến độ theo việc.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ...utils.contracts import SpeakerTurn, TopicLabel, TopicSegment
from ..shared.actors.resolution import resolve_actor
from ..shared.schemas import (
    ActionItem,
    ActionItemCandidate,
    AnalysisPart,
    DecisionCandidate,
    DiscussionPoint,
    MeetingReport,
    ProgressUpdate,
    SpeakerRegistry,
    TopicFailure,
    VerificationRecord,
)
from .reconcile import TextEmbedder, reconcile_assignments, reconcile_decisions
from .progress_merge import merge_task_progress


def _resolve_actor_once(item, registry, meeting_turns) -> ActionItem:
    """Định danh bên nhận việc bằng luật cho việc giao chưa được định danh.

    Việc giao CLEAR đi thẳng từ bước gắn nhãn nên chưa được định danh; việc đã qua Verifier thì đã được
    định danh kèm lý do, nên giữ nguyên.

    Args:
        item: Việc giao, đã hoặc chưa định danh.
        registry: Danh bạ người nói.
        meeting_turns: Toàn bộ lượt nói của cuộc họp.

    Returns:
        Việc giao đã định danh bên nhận việc.
    """

    if isinstance(item, ActionItem):
        return item
    return resolve_actor(item, registry, meeting_turns)


def build_meeting_report(
    *,
    segments: Iterable[TopicSegment],
    turns_by_id: Mapping[str, SpeakerTurn],
    registry: SpeakerRegistry,
    parts: frozenset[AnalysisPart],
    meeting_date: str | None,
    labels: Iterable[TopicLabel],
    discussion_points: Iterable[DiscussionPoint],
    assignments: Iterable[ActionItemCandidate],
    decisions: Iterable[DecisionCandidate],
    verification_records: Iterable[VerificationRecord],
    progress_updates: Iterable[ProgressUpdate],
    failures: Iterable[TopicFailure],
    judge: object | None = None,
    embedder: TextEmbedder | None = None,
) -> MeetingReport:
    """Tổng hợp kết quả của mọi chủ đề thành báo cáo cuộc họp.

    Các bước: định danh bên nhận cho việc giao còn thiếu; đối chiếu việc giao và kết luận trên cả cuộc
    họp để mỗi vấn đề còn một mục; gộp tiến độ thành một dòng mỗi việc (chỉ khi phần tiến độ được yêu
    cầu); cuối cùng sắp mọi danh sách theo thứ tự chủ đề.

    Args:
        segments: Các chủ đề của cuộc họp, theo thứ tự; quyết định thứ tự trong báo cáo.
        turns_by_id: Lượt nói của cả cuộc họp theo mã, giữ thứ tự thời gian.
        registry: Danh bạ người nói, kèm danh sách việc tồn đọng.
        parts: Các phần phân tích được yêu cầu; có "progress" thì mới gộp tiến độ.
        meeting_date: Ngày họp dạng ISO, dùng để đánh dấu việc quá hạn; None nếu không biết.
        labels: Tên chủ đề.
        discussion_points: Ý thảo luận của mọi chủ đề.
        assignments: Việc giao đã kiểm chứng của mọi chủ đề.
        decisions: Kết luận đã kiểm chứng của mọi chủ đề.
        verification_records: Bản ghi kiểm chứng của bước 5.
        progress_updates: Cập nhật tiến độ đã kiểm chứng của mọi chủ đề.
        failures: Ghi nhận các chủ đề không trích được.
        judge: Bộ phân loại qua Decisions API, dùng để đối chiếu việc giao/kết luận và phân biệt lượt chỉ
            đạo khi gộp tiến độ; None thì chỉ gộp mục trùng theo chữ.
        embedder: Bộ tạo vector câu, tuỳ chọn; có thì chỉ hỏi các nhóm gần nghĩa nhất, bớt lời gọi API.

    Returns:
        Báo cáo cuộc họp, gồm cả bản ghi các mục bị thay hoặc gộp khi đối chiếu.
    """

    order = {segment.segment_id: index for index, segment in enumerate(segments)}

    def by_topic(items):
        return sorted(items, key=lambda item: order.get(item.segment_id, len(order)))

    meeting_turns = tuple(turns_by_id.values())
    resolved = by_topic(_resolve_actor_once(item, registry, meeting_turns) for item in assignments)
    actions = reconcile_assignments(resolved, turns_by_id, judge, embedder=embedder)
    reconciled = reconcile_decisions(by_topic(decisions), turns_by_id, judge, embedder=embedder)
    records: list[VerificationRecord] = [*verification_records, *actions.records, *reconciled.records]
    task_progress: tuple = ()
    if "progress" in parts:
        task_progress = merge_task_progress(
            registry.agenda, list(progress_updates), registry, meeting_turns, meeting_date, turn_judge=judge,
        )

    return MeetingReport(
        labels=tuple(by_topic(labels)),
        discussion_points=tuple(by_topic(discussion_points)),
        assignments=tuple(by_topic(actions.items)),
        decisions=tuple(by_topic(reconciled.items)),
        verification_records=tuple(by_topic(records)),
        failures=tuple(by_topic(failures)),
        task_progress=task_progress,
    )


__all__ = [
    "build_meeting_report",
]
