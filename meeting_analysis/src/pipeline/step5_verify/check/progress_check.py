"""Kiểm các cập nhật tiến độ của một chủ đề, theo cùng cách với việc giao và kết luận: CHỈ gắn nhãn
chắc chắn hoặc nghi ngờ, không sửa nội dung.

Một cập nhật là chắc chắn khi lượt nói được dẫn ra thật sự nêu đúng trạng thái đó cho đúng việc đó.
Nếu lượt nói ấy chỉ là một đề xuất (chưa ai đồng ý), thì nó chưa tự xác nhận được; khi đó xét tiếp
xem có lượt nào sau đó tiếp nhận đề xuất không, giống như với góp ý của thành viên trong việc giao.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from ....utils.contracts import SpeakerTurn
from ...shared.judges.turn_act import TurnActJudge, judge_turn
from ...shared.meeting_inputs.agenda import AgendaTask, TaskAgenda
from ...shared.meeting_inputs.attendees import MeetingChair
from ...shared.schemas import Check, ProgressUpdate
from ...shared.transcript import turn_positions
from ...shared.judges.progress_act import STATUS_CLEAR_MIN, ProgressActJudge, ProgressActJudgement, judge_turn_windows
from .rules import acceptance_reasons

logger = logging.getLogger(__name__)

# Số cập nhật của MỘT chủ đề được kiểm song song (mỗi cập nhật vài lời gọi Decisions API).
_MAX_PARALLEL_CHECKS = 4


def _describe(judgements: Sequence[ProgressActJudgement]) -> str:
    """Ghép phân bố xác suất của các kết quả phân loại thành một chuỗi để ghi log.

    Lượt nói dài bị cắt thành nhiều đoạn; khi đó mỗi đoạn được ghi riêng, đánh số từ 1.
    """

    if len(judgements) == 1:
        return judgements[0].describe()
    return "; ".join(f"đoạn {number}: {j.describe()}" for number, j in enumerate(judgements, start=1))


def _status_reasons(
    update: ProgressUpdate,
    task: AgendaTask,
    turns: tuple[SpeakerTurn, ...],
    progress_judge: ProgressActJudge | None,
) -> list[str]:
    """Kiểm xem lượt nói agent chỉ ra có thật sự nêu trạng thái agent khai cho việc này không.

    Lượt dài được xét từng đoạn và lấy đoạn ủng hộ trạng thái mạnh nhất. Trạng thái được xác nhận khi
    xác suất đủ cao, hoặc khi nó là lựa chọn được Decisions API xếp cao nhất rõ rệt. Lý do trả về là câu
    hỏi cho Verifier và cố ý không kèm xác suất, vì mô hình dễ bám vào con số mà bỏ lời đúng; phân bố
    xác suất chỉ ghi log.

    Args:
        update: Cập nhật tiến độ cần kiểm.
        task: Việc trong danh sách tồn đọng mà cập nhật nhắm tới.
        turns: Lượt nói của chủ đề; lượt nêu trạng thái phải nằm trong đây.
        progress_judge: Bộ phân loại trạng thái tiến độ; None thì không kiểm được.

    Returns:
        Danh sách lý do; rỗng nếu trạng thái được xác nhận. Thiếu lượt nêu trạng thái, thiếu bộ phân
        loại hoặc lời gọi API lỗi đều sinh lý do để Verifier xét.
    """

    if update.status_turn_id is None:
        return ["Agent không chỉ ra lượt nói nêu trạng thái."]
    if progress_judge is None:
        return ["Chưa xét được lượt nêu trạng thái."]
    index = turn_positions(turns)[update.status_turn_id]
    try:
        judgements = judge_turn_windows(progress_judge, task.title, turns[index], turns[:index])
    except Exception as exc:  # noqa: BLE001 -- lỗi mạng/API: để Verifier xét
        logger.warning("progress_act lỗi ở %s/%s: %s", update.segment_id, update.task_id, exc)
        return [f"Decisions API lỗi: {exc}"]
    support = max(judgements, key=lambda judgement: judgement.p_status(update.status))
    if support.p_status(update.status) >= STATUS_CLEAR_MIN or support.agrees_with(update.status):
        return []
    # Lý do là câu hỏi cho Verifier, không kèm xác suất: gpt-4o bám vào "mention_only 0.51" để bỏ lời đúng
    # (T3 Cái Mép). Phân bố xác suất chỉ ghi log.
    logger.info("progress_act không xác nhận %s/%s %s ở %s: %s", update.segment_id, update.task_id,
                update.status, update.status_turn_id, _describe(judgements))
    return [f"Lượt {update.status_turn_id} có nêu trạng thái {update.status} cho CHÍNH việc này không "
            "(bộ lọc tự động chưa xác nhận được)."]


def _proposal_reasons(
    update: ProgressUpdate, turns: tuple[SpeakerTurn, ...], turn_judge: TurnActJudge | None
) -> list[str]:
    """Gắn cờ khi lượt nêu trạng thái thực ra chỉ là một đề xuất, chưa phải lời xác nhận.

    Ví dụ: "Tôi đề nghị coi như xong hạng mục này" chưa đủ để ghi việc là đã xong nếu chưa ai đồng ý.

    Args:
        update: Cập nhật tiến độ đang kiểm.
        turns: Lượt nói của chủ đề.
        turn_judge: Bộ phân loại hành vi lượt nói; None thì bỏ qua bước này.

    Returns:
        Một lý do nếu lượt nói được xếp là đề xuất hoặc lời gọi API lỗi; rỗng nếu không phải đề xuất,
        không có bộ phân loại, hoặc cập nhật không chỉ ra lượt nêu trạng thái.
    """

    index = turn_positions(turns).get(update.status_turn_id or "")
    if turn_judge is None or index is None:
        return []
    try:
        label = judge_turn(turn_judge, turns[index], turns[:index]).label
    except Exception as exc:  # noqa: BLE001 -- lỗi mạng/API: để Verifier xét
        logger.warning("turn_act lỗi ở %s/%s: %s", update.segment_id, update.task_id, exc)
        return [f"Decisions API lỗi: {exc}"]
    if label != "proposal":
        return []
    return [f"Lượt {update.status_turn_id} mới là ý kiến/đề xuất: nó có nêu trạng thái {update.status} của CHÍNH "
            "việc này và được tiếp nhận không, hay chỉ viện dẫn việc này để đề nghị việc khác."]


def _check_update(
    update: ProgressUpdate,
    task: AgendaTask,
    turns: tuple[SpeakerTurn, ...],
    progress_judge: ProgressActJudge | None,
    turn_judge: TurnActJudge | None,
    chair: MeetingChair | None,
) -> Check:
    """Gắn nhãn CLEAR hoặc UNCERTAIN cho một cập nhật tiến độ.

    Thứ tự kiểm: lượt nêu trạng thái có nêu đúng trạng thái không; nếu có, lượt đó có phải chỉ là đề
    xuất không. Khi còn lý do nghi ngờ mà agent có khai lượt nêu đề xuất khác lượt nêu trạng thái, thì
    xét lượt nêu trạng thái như lượt tiếp nhận đề xuất: được tiếp nhận thì chỉ giữ lý do của bước tiếp
    nhận (nếu có), không thì cộng thêm vào lý do cũ. Cập nhật agent khai là "mentioned" (chỉ nhắc tới)
    không có trạng thái để kiểm nên luôn CLEAR.

    Args:
        update: Cập nhật tiến độ cần gắn nhãn.
        task: Việc trong danh sách tồn đọng mà cập nhật nhắm tới.
        turns: Lượt nói của chủ đề.
        progress_judge: Bộ phân loại trạng thái tiến độ, có thể None.
        turn_judge: Bộ phân loại hành vi lượt nói, có thể None.
        chair: Người chủ trì nếu được cung cấp; khi có, chỉ người chủ trì mới tiếp nhận được đề xuất.

    Returns:
        Nhãn kèm lý do (lý do rỗng khi CLEAR).
    """

    if update.status == "mentioned":
        return Check("clear")
    reasons = _status_reasons(update, task, turns, progress_judge)
    if not reasons:
        reasons = _proposal_reasons(update, turns, turn_judge)
    by_id = {turn.turn_id: turn for turn in turns}
    origin, closing = by_id.get(update.request_turn_id or ""), by_id.get(update.status_turn_id or "")
    if reasons and origin is not None and closing is not None and turn_judge is not None:
        claim = update.summary or update.directive or task.title
        accepted, accept_reasons = acceptance_reasons(claim, origin, closing, turns, turn_judge, chair)
        reasons = accept_reasons if accepted else [*reasons, *accept_reasons]
    return Check("uncertain", tuple(reasons)) if reasons else Check("clear")


def check_progress_updates(
    updates: Sequence[ProgressUpdate],
    turns: Sequence[SpeakerTurn],
    agenda: TaskAgenda,
    progress_judge: ProgressActJudge | None = None,
    turn_judge: TurnActJudge | None = None,
    chair: MeetingChair | None = None,
) -> list[tuple[ProgressUpdate, Check]]:
    """Gắn nhãn CLEAR hoặc UNCERTAIN cho mọi cập nhật tiến độ của một chủ đề.

    Các cập nhật được kiểm song song (giới hạn vài luồng) vì mỗi cập nhật cần vài lời gọi Decisions API.
    Nội dung cập nhật được giữ nguyên; chỉ nhãn được sinh thêm.

    Args:
        updates: Cập nhật tiến độ thô của chủ đề.
        turns: Lượt nói của chủ đề.
        agenda: Danh sách việc tồn đọng trước cuộc họp, dùng để tra tên việc.
        progress_judge: Bộ phân loại trạng thái tiến độ; None thì mọi cập nhật có trạng thái bị gắn cờ.
        turn_judge: Bộ phân loại hành vi lượt nói, dùng để phát hiện đề xuất và xét lượt tiếp nhận.
        chair: Người chủ trì nếu được cung cấp, None nếu không.

    Returns:
        Danh sách cặp (cập nhật nguyên vẹn, nhãn) theo thứ tự đầu vào. Cập nhật nhắm tới việc không có
        trong danh sách bị bỏ qua.
    """

    turns = tuple(turns)

    def check(update: ProgressUpdate) -> tuple[ProgressUpdate, Check] | None:
        task = agenda.find(update.task_id)
        if task is None:  # parser đã lọc; phòng khi danh sách việc đổi giữa chừng
            return None
        return update, _check_update(update, task, turns, progress_judge, turn_judge, chair)

    if not updates:
        return []
    with ThreadPoolExecutor(max_workers=min(len(updates), _MAX_PARALLEL_CHECKS)) as pool:
        checked = list(pool.map(check, updates))
    return [pair for pair in checked if pair is not None]


__all__ = [
    "check_progress_updates",
]
