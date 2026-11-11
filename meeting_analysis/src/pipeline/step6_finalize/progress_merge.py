"""Gộp các cập nhật tiến độ từ mọi chủ đề thành MỘT dòng cho mỗi việc trong danh sách (bước 6).

Khi một việc có nhiều cập nhật, lời chỉ đạo hay kết luận được ưu tiên hơn lời báo cáo; không
phân biệt được thì lấy cập nhật muộn hơn. Việc đã quá hạn cũ mà chưa xong
và chưa huỷ thì được đánh dấu. Nếu việc được giao lại cho bên khác, bên nhận mới cũng được xác định.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from ...utils.contracts import SpeakerTurn
from ..shared.actors.names import name_key
from ..shared.actors.resolution import resolve_actor
from ..shared.meeting_inputs.agenda import AgendaTask, TaskAgenda
from ..shared.schemas import ActorAssignee, ProgressUpdate, SpeakerRegistry, TaskProgress
from ..shared.transcript import turn_positions
from ..step4_extract.progress_extract import as_assignment, update_position
from ..shared.judges.turn_act import COMMIT_CLEAR_MIN, TurnActJudge, judge_turn
from .reconcile import Relation, reconcile

logger = logging.getLogger(__name__)


def _is_confirmed(update: ProgressUpdate) -> bool:
    """Kiểm cập nhật có trạng thái đáng tin để tranh làm trạng thái cuối của việc không.

    Loại cập nhật chỉ nhắc tới việc ("mentioned") và cập nhật Verifier chưa kết luận được (lỗi mô hình,
    hoặc hết vòng mà vẫn "unresolved").
    """

    return update.status != "mentioned" and update.verification != "fallback"


class ProgressKind:
    """Cách đối chiếu cập nhật tiến độ: chọn một cập nhật thắng cho mỗi việc.

    Chỉ so các cập nhật cùng mã việc, không cần hỏi Decisions API xem có cùng vấn đề không. Cập nhật sau
    thay cập nhật hiện hành khi nó hơn theo thứ tự: lượt chỉ đạo/kết luận thắng lượt báo cáo; ngang nhau
    thì lượt muộn hơn thắng. Ví dụ: "Đã xong" ở lượt báo cáo rồi chủ trì kết luận "cho làm lại" thì lấy
    kết luận. Không gộp nội dung (dòng tiến độ vẫn giữ mọi cập nhật) và không sinh bản ghi.

    Args:
        meeting_turns: Toàn bộ lượt nói của cuộc họp, theo thứ tự.
        positions: Bảng tra mã lượt sang vị trí trong ``meeting_turns``.
        judge: Bộ phân loại hành vi lượt nói; None thì mọi lượt coi là báo cáo, chỉ so vị trí.
    """

    def __init__(self, meeting_turns: Sequence[SpeakerTurn], positions, judge: TurnActJudge | None) -> None:
        self._turns = meeting_turns
        self._positions = positions
        self._judge = judge
        self._commit: dict[int, bool] = {}

    def position(self, update: ProgressUpdate) -> int:
        """Trả vị trí của cập nhật trong cuộc họp, dùng để sắp và so muộn/sớm."""

        return update_position(update, self._positions)

    def may_compare(self, earlier: ProgressUpdate, later: ProgressUpdate) -> bool:
        """Chỉ cho so hai cập nhật của cùng một việc."""

        return earlier.task_id == later.task_id

    def relate(self, earlier: ProgressUpdate, later: ProgressUpdate) -> Relation:
        """Luôn coi là cùng vấn đề; đánh dấu thay thế khi cập nhật sau xếp hạng cao hơn cập nhật hiện hành."""

        rank = (self._is_commit(later), self.position(later)) > (self._is_commit(earlier), self.position(earlier))
        return Relation(1.0, rank)

    def merge(self, kept: ProgressUpdate, other: ProgressUpdate) -> ProgressUpdate:
        """Giữ nguyên cập nhật hiện hành; không gộp gì từ cập nhật thua."""

        return kept

    def record(self, *_args) -> None:
        """Không sinh bản ghi cho tiến độ."""

        return None

    def _is_commit(self, update: ProgressUpdate) -> bool:
        """Kiểm lượt nêu trạng thái của cập nhật có phải lời chỉ đạo/kết luận không; kết quả được nhớ lại.

        Lượt đạt khi xác suất "chốt" của Decisions API không dưới ``COMMIT_CLEAR_MIN``. Không có bộ phân
        loại, không có lượt nêu trạng thái hoặc lời gọi API lỗi thì coi là lượt báo cáo.
        """

        if id(update) not in self._commit:
            self._commit[id(update)] = self._judge_commit(update)
        return self._commit[id(update)]

    def _judge_commit(self, update: ProgressUpdate) -> bool:
        """Gọi Decisions API cho lượt nêu trạng thái của cập nhật (không nhớ kết quả)."""

        index = self._positions.get(update.status_turn_id) if update.status_turn_id else None
        if self._judge is None or index is None:
            return False
        try:
            return judge_turn(self._judge, self._turns[index], self._turns[:index]).p_commit >= COMMIT_CLEAR_MIN
        except Exception as exc:  # noqa: BLE001 -- lỗi mạng/API: coi như lượt báo cáo
            logger.warning("turn_act lỗi khi đo chỉ đạo ở %s/%s: %s", update.segment_id, update.task_id, exc)
            return False


def _is_overdue(due: str | None, meeting_date: str | None, status: str) -> bool:
    """Kiểm việc có quá hạn cũ không: hạn trước ngày họp mà việc chưa xong và chưa bị huỷ.

    Thiếu hạn, thiếu ngày họp hoặc ngày sai định dạng ISO thì coi là không quá hạn.
    """

    if not due or not meeting_date or status in ("done", "cancelled"):
        return False
    try:
        return date.fromisoformat(due) < date.fromisoformat(meeting_date)
    except ValueError:
        return False


def _new_assignees(
    task: AgendaTask, update: ProgressUpdate, registry: SpeakerRegistry, meeting_turns: Sequence[SpeakerTurn]
) -> tuple[ActorAssignee, ...]:
    """Định danh bên nhận việc mới khi một việc tồn đọng được giao lại.

    Mỗi bên được so với các bên chủ trì/phối hợp cũ của việc theo mã người nói hoặc tên chuẩn hoá. Bên
    chưa định danh được vẫn giữ, kèm ứng viên để người xem chọn.

    Args:
        task: Việc tồn đọng trong danh sách.
        update: Cập nhật có nêu bên nhận việc mới.
        registry: Danh bạ người nói.
        meeting_turns: Toàn bộ lượt nói của cuộc họp.

    Returns:
        Các bên nhận việc đã định danh; rỗng nếu tất cả đều là bên cũ của việc (không thật sự giao lại).
    """

    assignees = resolve_actor(as_assignment(update, task.title), registry, meeting_turns).assignees
    refs = {party.ref_id for party in task.parties if party.ref_id}
    names = {name_key(party.name) for party in task.parties}
    if all(
        (assignee.ref_id and assignee.ref_id in refs) or name_key(assignee.name or assignee.mention) in names
        for assignee in assignees
    ):
        return ()
    return assignees


def merge_task_progress(
    agenda: TaskAgenda,
    updates: Sequence[ProgressUpdate],
    registry: SpeakerRegistry,
    meeting_turns: Sequence[SpeakerTurn],
    meeting_date: str | None,
    turn_judge: TurnActJudge | None = None,
) -> tuple[TaskProgress, ...]:
    """Gộp cập nhật tiến độ của mọi chủ đề thành một dòng tiến độ cho mỗi việc trong danh sách.

    Trạng thái cuối lấy từ cập nhật thắng trong số các cập nhật có trạng thái đáng tin; nếu việc chỉ có
    cập nhật chưa đáng tin thì lấy cập nhật muộn nhất. Hạn chót lấy từ cập nhật thắng nếu nó có, không
    thì từ cập nhật muộn nhất có nêu hạn. Dòng tiến độ còn đánh dấu: mâu thuẫn trạng thái (có "done" và
    trạng thái khác cùng đáng tin), chưa chắc chắn (cập nhật thắng chưa được Verifier kết luận), quá hạn
    cũ, và bên nhận việc mới nếu việc được giao lại. Việc không được nhắc tới có trạng thái
    "not_reported".

    Args:
        agenda: Danh sách việc tồn đọng trước cuộc họp.
        updates: Cập nhật tiến độ đã kiểm chứng của mọi chủ đề.
        registry: Danh bạ người nói, để định danh bên nhận việc mới.
        meeting_turns: Toàn bộ lượt nói của cuộc họp, theo thứ tự.
        meeting_date: Ngày họp dạng ISO; None nếu không biết (khi đó không đánh dấu quá hạn).
        turn_judge: Bộ phân loại hành vi lượt nói để phân biệt lượt chỉ đạo/kết luận với lượt báo cáo;
            chỉ được hỏi khi một việc có từ hai cập nhật đáng tin. None thì cập nhật muộn hơn thắng.

    Returns:
        Các dòng tiến độ, theo thứ tự của danh sách việc.
    """

    meeting_turns = tuple(meeting_turns)
    positions = turn_positions(meeting_turns)
    task_ids = {task.task_id for task in agenda.tasks}
    confirmed_all = [update for update in updates if update.task_id in task_ids and _is_confirmed(update)]
    # mỗi cập nhật chỉ so với đúng một nhóm (cùng việc): trần = số cập nhật, tức không giới hạn
    reconciled = reconcile(confirmed_all, ProgressKind(meeting_turns, positions, turn_judge),
                           max_calls=len(confirmed_all))
    winners = {update.task_id: update for update in reconciled.items}
    result = []
    for task in agenda.tasks:
        own = sorted(
            (update for update in updates if update.task_id == task.task_id),
            key=lambda update: update_position(update, positions),
        )
        base = TaskProgress(
            task_id=task.task_id,
            title=task.title,
            owner=task.owner.name,
            previous_status=task.last_status,
            status="not_reported",
            previous_due=task.due,
        )
        if not own:
            result.append(replace(base, overdue=_is_overdue(task.due, meeting_date, "not_reported")))
            continue
        confirmed = [update for update in own if _is_confirmed(update)]
        confirmed_statuses = {update.status for update in confirmed}
        winner = winners[task.task_id] if confirmed else own[-1]
        with_deadline = [u for u in (confirmed or own) if u.deadline_raw or u.deadline_extended]
        deadline_source = winner if (winner.deadline_raw or winner.deadline_extended) else (
            with_deadline[-1] if with_deadline else None
        )
        reassign = next((update for update in reversed(own) if update.mentions), None)
        assignees = _new_assignees(task, reassign, registry, meeting_turns) if reassign else ()
        result.append(
            replace(
                base,
                status=winner.status,
                deadline_raw=deadline_source.deadline_raw if deadline_source else None,
                deadline_date=deadline_source.deadline_date if deadline_source else None,
                deadline_kind=deadline_source.deadline_kind if deadline_source else "unknown",
                deadline_extended=deadline_source.deadline_extended if deadline_source else False,
                status_conflict="done" in confirmed_statuses and len(confirmed_statuses) >= 2,
                uncertain=winner.verification == "fallback",
                overdue=_is_overdue(task.due, meeting_date, winner.status),
                deciding_update=winner,
                updates=tuple(own),
                reassign_update=reassign if assignees else None,
                assignees=assignees,
            )
        )
    return tuple(result)


__all__ = [
    "ProgressKind",
    "merge_task_progress",
]
