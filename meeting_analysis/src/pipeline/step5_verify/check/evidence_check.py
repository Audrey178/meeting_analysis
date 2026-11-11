"""Chia các mục trích được của một chủ đề thành hai nhóm: chắc chắn và nghi ngờ.

Mục chắc chắn vào thẳng kết quả; mỗi mục nghi ngờ được gửi riêng cho agent kiểm chứng. Một việc
giao bị coi là nghi ngờ khi, chẳng hạn, bên nhận việc không khớp ai trong danh bạ hoặc khớp nhiều
người, hoặc lượt nói được coi là "lượt chốt" không thật sự là lời giao việc.

Bước này CHỈ gắn nhãn; nội dung các mục được giữ nguyên như agent đã ghi.
"""

from __future__ import annotations

from collections.abc import Sequence

from ....utils.contracts import SpeakerTurn
from ...shared.actors.resolution import resolve_actor
from ...shared.schemas import (
    ActionItemCandidate,
    DecisionCandidate,
    ProgressUpdate,
    SpeakerRegistry,
    VerifyTask,
)
from ...step4_extract.progress_extract import as_assignment
from .progress_check import check_progress_updates
from ...shared.judges.progress_act import ProgressActJudge
from .rules import check_evidence
from ...shared.judges.turn_act import TurnActJudge


def _actor_reasons(item, registry: SpeakerRegistry, meeting_turns: tuple[SpeakerTurn, ...]) -> list[str]:
    """Liệt kê lý do nghi ngờ về bên nhận việc (WHO) của một việc giao.

    Mỗi bên nhận việc được định danh với danh bạ và bản ghi cả cuộc họp; bên nào không khớp ai, hoặc
    khớp từ hai người trở lên, sinh một lý do để Verifier chọn lại.

    Args:
        item: Việc giao (hoặc cập nhật tiến độ đã quy về dạng việc giao) cần định danh bên nhận.
        registry: Danh bạ người nói của cuộc họp.
        meeting_turns: Toàn bộ lượt nói của cuộc họp, dùng để tra tên chưa có trong danh bạ.

    Returns:
        Danh sách lý do; rỗng nếu mọi bên nhận việc đều định danh được.
    """

    resolved = resolve_actor(item, registry, meeting_turns)
    reasons = []
    for assignee in resolved.assignees:
        if not assignee.flag:
            continue
        if not assignee.candidates:
            reasons.append(
                f"Bên nhận việc '{assignee.mention}' không khớp người/đơn vị nào trong danh bạ hay bản ghi (WHO)."
            )
        elif len(assignee.candidates) >= 2:
            names = ", ".join(f"{c.name} ({c.score:.2f})" for c in assignee.candidates)
            reasons.append(
                f"Actor '{assignee.mention}' mơ hồ, có thể là: {names}. Cần chọn đúng một ứng viên kèm lý do."
            )
    return reasons



def check_topic_candidates(
    segment_id: str,
    turns: tuple[SpeakerTurn, ...],
    meeting_turns: tuple[SpeakerTurn, ...],
    registry: SpeakerRegistry,
    action_candidates: Sequence[ActionItemCandidate],
    decision_candidates: Sequence[DecisionCandidate],
    progress_updates_raw: Sequence[ProgressUpdate],
    *,
    turn_judge: TurnActJudge | None = None,
    progress_judge: ProgressActJudge | None = None,
) -> dict:
    """Chia các candidate thô của một chủ đề thành CLEAR và UNCERTAIN, không sửa candidate nào.

    Việc giao và kết luận được kiểm bằng luật lượt chốt (kèm lý do WHO với việc giao); cập nhật tiến độ
    được kiểm riêng, và nếu cập nhật giao lại việc cho bên khác thì bên nhận mới cũng được định danh như
    một việc giao. Mỗi mục UNCERTAIN được gói thành một yêu cầu kiểm chứng riêng cho Verifier, có khoá
    dạng ``"<segment_id>:<kind>:<chỉ số hoặc mã việc>"``.

    Args:
        segment_id: Mã chủ đề đang xét.
        turns: Lượt nói thuộc chủ đề này.
        meeting_turns: Toàn bộ lượt nói của cuộc họp, để định danh bên nhận việc và để công cụ của
            Verifier tra bằng chứng nằm ở chủ đề khác.
        registry: Danh bạ người nói, kèm người chủ trì (nếu được cung cấp) và danh sách việc tồn đọng.
        action_candidates: Việc giao thô do agent trích ở bước 4.
        decision_candidates: Kết luận thô do agent trích ở bước 4.
        progress_updates_raw: Cập nhật tiến độ thô do agent trích ở bước 4.
        turn_judge: Bộ phân loại hành vi lượt nói qua Decisions API; None thì mọi lượt chốt bị gắn cờ.
        progress_judge: Bộ phân loại trạng thái tiến độ qua Decisions API; None thì mọi cập nhật có
            trạng thái bị gắn cờ.

    Returns:
        Dict gồm ``verified_assignments``, ``verified_decisions``, ``progress_updates`` (các mục CLEAR)
        và ``pending_verify`` (tuple yêu cầu kiểm chứng cho các mục UNCERTAIN).
    """

    clear_actions, clear_decisions, pending = [], [], []

    def _verify_task(kind: str, index: int | str, item, reasons) -> VerifyTask:
        return {
            "item_key": f"{segment_id}:{kind}:{index}",
            "segment_id": segment_id,
            "kind": kind,
            "candidate": item,
            "reasons": reasons,
            "turns": turns,
            "meeting_turns": meeting_turns,
            "registry": registry,
        }

    chair = registry.chair
    for kind, raw, clear in (
        ("action", action_candidates, clear_actions),
        ("decision", decision_candidates, clear_decisions),
    ):
        for index, item in enumerate(raw):
            actor_reasons = _actor_reasons(item, registry, meeting_turns) if kind == "action" else ()
            flag = check_evidence(item, turns, turn_judge, chair, actor_reasons)
            if flag.verdict == "clear":
                clear.append(item)
            else:
                pending.append(_verify_task(kind, index, item, flag.reasons))
    progress_updates = []
    for update, flag in check_progress_updates(
        progress_updates_raw, turns, registry.agenda, progress_judge, turn_judge, chair
    ):
        reasons = flag.reasons
        if update.mentions:  # giao lại cho bên khác: định danh bên nhận việc mới như việc giao
            task = registry.agenda.find(update.task_id)
            reasons = (*reasons, *_actor_reasons(as_assignment(update, task.title), registry, meeting_turns))
        if reasons:
            pending.append(_verify_task("progress", update.task_id, update, reasons))
        else:
            progress_updates.append(update)
    return {
        "verified_assignments": clear_actions,
        "verified_decisions": clear_decisions,
        "progress_updates": progress_updates,
        "pending_verify": tuple(pending),
    }


__all__ = [
    "check_topic_candidates",
]
