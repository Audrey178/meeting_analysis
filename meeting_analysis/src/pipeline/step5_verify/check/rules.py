"""Các luật quyết định một việc giao hay một kết luận đã thật sự được giao/chốt chưa.

Một mục được coi là chắc chắn khi lượt nói được dẫn ra đúng là lời giao việc hay chốt kết luận, và
nói đúng nội dung mục đó. Nếu mục bắt nguồn từ đề xuất của một thành viên, thì cần có lượt nói sau
đó của người khác (người chủ trì, nếu biết) tiếp nhận đề xuất. Riêng việc giao còn phải có bên nhận
việc rõ ràng. Thiếu điều kiện nào thì mục được gửi agent kiểm chứng, kèm lý do.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ....utils.contracts import SpeakerTurn
from ...shared.actors.names import name_key
from ...shared.meeting_inputs.attendees import MeetingChair
from ...shared.schemas import ActionItemCandidate, DecisionCandidate, Check
from ...shared.transcript import match_claimed_name_to_real_speaker
from ...shared.judges.turn_act import (
    COMMIT_CLEAR_MIN,
    TurnActJudge,
    claim_support_is_clear,
    judge_claim_support,
    judge_proposal_response,
    judge_turn,
)

logger = logging.getLogger(__name__)

# Trạng thái agent tự khai được coi là đủ để đi thẳng (không cần đi Verifier).
_ACTION_STATUSES_CLEAR = frozenset({"assigned", "self_committed"})
_DECISION_STATUSES_CLEAR = frozenset({"agreed"})


def _confirm_turn_reasons(
    confirm_turn: SpeakerTurn | None,
    turns: tuple[SpeakerTurn, ...] = (),
    judge: TurnActJudge | None = None,
) -> list[str]:
    """Kiểm xem lượt chốt có thật sự là lời chốt, giao việc hoặc nhận việc không.

    Xét nguyên văn lượt nói (kèm các lượt trước làm ngữ cảnh), không xét câu agent viết lại. Lượt đạt khi
    xác suất "chốt" của Decisions API không dưới ``COMMIT_CLEAR_MIN``.

    Args:
        confirm_turn: Lượt chốt agent chỉ ra; None nếu agent không chỉ ra được lượt nào trong chủ đề.
        turns: Lượt nói của chủ đề, dùng để lấy ngữ cảnh phía trước lượt chốt.
        judge: Bộ phân loại hành vi lượt nói; None thì không kiểm được.

    Returns:
        Danh sách lý do; rỗng nếu lượt chốt đạt. Thiếu lượt chốt, thiếu bộ phân loại hoặc lời gọi API
        lỗi đều sinh lý do để Verifier đọc lại.
    """

    if confirm_turn is None:
        return ["Agent không chỉ ra được lượt nói chốt/giao việc thuộc đoạn này."]
    try:
        index = next((i for i, turn in enumerate(turns) if turn.turn_id == confirm_turn.turn_id), len(turns))
        judgement = judge_turn(judge, confirm_turn, turns[:index]) if judge is not None else None
    except Exception as exc:  # noqa: BLE001 -- lỗi mạng/API bất kỳ: để Verifier xét
        logger.warning("turn_act judge lỗi ở %s, chuyển Verifier xét: %s", confirm_turn.turn_id, exc)
        judgement = None
    if judgement is None:
        return [f"Chưa xét được lượt chốt {confirm_turn.turn_id} có phải lời chốt/giao/nhận việc không."]
    if judgement.p_commit >= COMMIT_CLEAR_MIN:
        return []
    return [
        f"Lượt chốt {confirm_turn.turn_id} chưa chắc là lời chốt/giao/nhận việc: '{judgement.label}' "
        f"(p_chốt={judgement.p_commit:.2f}; {judgement.describe()})."
    ]


def _turn_by_id(turns: tuple[SpeakerTurn, ...], turn_id: str | None) -> SpeakerTurn | None:
    """Tìm lượt nói theo mã trong chủ đề; None nếu mã rỗng hoặc không có trong chủ đề."""

    return next((turn for turn in turns if turn.turn_id == turn_id), None) if turn_id else None


def _claim_support_reasons(
    item: ActionItemCandidate | DecisionCandidate,
    confirm_turn: SpeakerTurn | None,
    turns: tuple[SpeakerTurn, ...],
    judge: TurnActJudge | None,
) -> list[str]:
    """Gắn cờ khi lượt chốt đúng là lời chốt nhưng lại nói về một việc khác với mục agent ghi.

    Ví dụ: lượt "Thống nhất, giao anh Nam làm" bị agent gắn cho một việc khác được bàn ngay trước đó.
    Bước này bị bỏ qua (không lý do) khi thiếu lượt chốt hoặc bộ phân loại không hỗ trợ kiểm nội dung.

    Args:
        item: Việc giao hoặc kết luận đang kiểm.
        confirm_turn: Lượt chốt agent chỉ ra.
        turns: Lượt nói của chủ đề, để lấy các lượt bằng chứng agent dẫn.
        judge: Bộ phân loại hành vi lượt nói, có thể None.

    Returns:
        Danh sách lý do; rỗng nếu lượt chốt khớp nội dung hoặc không kiểm được do thiếu điều kiện.
        Lời gọi API lỗi sinh lý do để Verifier đọc lại.
    """

    if confirm_turn is None or not callable(getattr(judge, "judge_claim", None)):
        return []
    evidence = tuple(turn for turn in turns if turn.turn_id in item.evidence_turn_ids)
    try:
        judgement = judge_claim_support(judge, item.text, confirm_turn, evidence)
    except Exception as exc: 
        logger.warning("claim_support judge lỗi ở %s, chuyển Verifier xét: %s", confirm_turn.turn_id, exc)
        return [
            f"Chưa xét được lượt chốt {confirm_turn.turn_id} có nói/tiếp nhận "
            "đúng nội dung việc hay không; cần đọc lại lượt này và bằng chứng."
        ]
    if judgement is None or claim_support_is_clear(judgement):
        return []
    return [
        f"Lượt chốt {confirm_turn.turn_id} không xác nhận đúng nội dung việc "
        f"(p_khớp={judgement.p_support:.2f}; {judgement.describe()}); có thể bị gắn nhầm lời chốt."
    ]


def _position(turns: tuple[SpeakerTurn, ...], turn: SpeakerTurn) -> int:
    """Trả vị trí của ``turn`` trong ``turns``; lượt phải có mặt trong ``turns``."""

    return next(i for i, item in enumerate(turns) if item.turn_id == turn.turn_id)


def _same_person(left: SpeakerTurn, right: SpeakerTurn) -> bool:
    """Kiểm hai lượt có cùng một người nói không: so mã người nói nếu cả hai có, không thì so tên."""

    if left.speaker_id and right.speaker_id:
        return left.speaker_id == right.speaker_id
    return bool(left.speaker) and name_key(left.speaker) == name_key(right.speaker or "")


def _by_chair(turn: SpeakerTurn, chair: MeetingChair | None) -> bool:
    """Kiểm lượt có do người chủ trì nói không; luôn False khi không có người chủ trì."""

    return chair is not None and chair.is_speaker(turn.speaker, turn.speaker_id)


def _stance(claim: str, reference: SpeakerTurn, turn: SpeakerTurn, judge: TurnActJudge) -> tuple[str, str] | None:
    """Xác định lượt ``turn`` bác, sửa hay chấp nhận nội dung ``claim`` được nêu ở lượt ``reference``.

    Args:
        claim: Nội dung cần xét (câu việc giao, kết luận hoặc tóm tắt cập nhật).
        reference: Lượt nói nêu nội dung đó (thường là đề xuất của thành viên).
        turn: Lượt nói phản hồi cần xét.
        judge: Bộ phân loại hành vi lượt nói.

    Returns:
        Cặp (thái độ "reject"/"modify"/"accept", mô tả phân bố xác suất để ghi lý do); None nếu lượt
        không phản hồi rõ nội dung này hoặc lời gọi API lỗi.
    """

    try:
        found = judge_proposal_response(judge, claim, reference, turn)
    except Exception as exc:  # noqa: BLE001 -- lỗi Decisions API: coi như không phản hồi
        logger.warning("evidence: proposal_response lỗi ở %s: %s", turn.turn_id, exc)
        return None
    if found is None:
        return None
    stance, judgement = found
    return stance, judgement.describe()


def acceptance_reasons(
    claim: str,
    origin: SpeakerTurn,
    closing: SpeakerTurn,
    turns: tuple[SpeakerTurn, ...],
    judge: TurnActJudge,
    chair: MeetingChair | None,
) -> tuple[bool, list[str]]:
    """Kiểm xem lượt ``closing`` có tiếp nhận nội dung ``claim`` đã được nêu ở lượt ``origin`` không.

    Dùng chung cho việc giao, kết luận và cập nhật tiến độ. Một lượt tiếp nhận hợp lệ phải nằm SAU lượt
    nêu, do người KHÁC người nêu nói (nếu có người chủ trì thì phải chính là người chủ trì), và được
    Decisions API xếp là chấp nhận. Ví dụ: thành viên đề xuất "Nên lùi hạn sang tháng 12", người chủ trì
    đáp "Đồng ý các ý kiến". Chấp nhận nhưng sửa nội dung vẫn tính là tiếp nhận, kèm lý do để nội dung
    được viết lại theo lượt tiếp nhận.

    Args:
        claim: Nội dung cần được tiếp nhận.
        origin: Lượt nêu nội dung (lượt đề xuất).
        closing: Lượt agent khai là lượt tiếp nhận.
        turns: Lượt nói của chủ đề; cả ``origin`` và ``closing`` phải có mặt trong đây.
        judge: Bộ phân loại hành vi lượt nói.
        chair: Người chủ trì nếu được cung cấp, None nếu không.

    Returns:
        Cặp (đã tiếp nhận hay chưa, danh sách lý do). Chưa tiếp nhận mà lý do rỗng nghĩa là lượt không
        phản hồi rõ nội dung này hoặc lời gọi API lỗi.
    """

    if (
        _position(turns, closing) <= _position(turns, origin)
        or _same_person(closing, origin)
        or (chair is not None and not _by_chair(closing, chair))
    ):
        who = "người chủ trì" if chair is not None else "người khác người nêu"
        return False, [
            f"Lượt chốt {closing.turn_id} agent khai không phải lượt sau của {who} tiếp nhận nội dung nêu ở "
            f"lượt {origin.turn_id}."
        ]
    found = _stance(claim, origin, closing, judge)
    if found is None:  # lượt không nói gì về nội dung này, hoặc API lỗi
        return False, []
    stance, detail = found
    speaker = closing.speaker or "không rõ"
    if stance == "reject":
        return False, [
            f"Lượt {closing.turn_id} ({speaker}) agent khai là lượt tiếp nhận nhưng "
            f"bác nội dung nêu ở lượt {origin.turn_id} ({detail})."
        ]
    logger.info("evidence: %s -> %s tiếp nhận ở %s (%s)", claim[:50], origin.turn_id, closing.turn_id, detail)
    if stance == "modify":
        return True, [
            f"Lượt {closing.turn_id} ({speaker}) chấp nhận nhưng đổi nội dung/phạm vi "
            f"so với lượt nêu {origin.turn_id} ({detail}); nội dung phải theo lượt {closing.turn_id}."
        ]
    return True, []


def _closing_turn_reasons(
    item: ActionItemCandidate | DecisionCandidate,
    closing: SpeakerTurn | None,
    turns: tuple[SpeakerTurn, ...],
    judge: TurnActJudge | None,
    chair: MeetingChair | None,
) -> tuple[bool, list[str]]:
    """Kiểm lượt chốt agent khai cho một việc giao hoặc kết luận.

    Đi theo hai bước:

    1. Lượt chốt tự nó là lời chốt và nói đúng nội dung thì không có lý do nào. Trường hợp này gồm cả khi
       lượt nêu khác lượt chốt nhưng chính lượt chốt đã đủ (người chủ trì giao rồi chốt lại ở lượt tổng
       kết, hoặc người được giao đáp "dạ").
    2. Nếu không, và agent có khai lượt nêu (``request_turn_id``) khác lượt chốt, thì xét lượt chốt như
       lượt tiếp nhận đề xuất. Được tiếp nhận thì chỉ giữ lý do của bước này; không thì cộng dồn lý do
       của cả hai bước.

    Args:
        item: Việc giao hoặc kết luận đang kiểm.
        closing: Lượt chốt agent khai; None nếu không tìm thấy trong chủ đề.
        turns: Lượt nói của chủ đề.
        judge: Bộ phân loại hành vi lượt nói, có thể None.
        chair: Người chủ trì nếu được cung cấp, None nếu không.

    Returns:
        Cặp (mục được chốt nhờ lượt tiếp nhận hay không, danh sách lý do về lượt chốt).
    """

    reasons = _confirm_turn_reasons(closing, turns, judge)
    if not reasons:  # chỉ tốn thêm một câu Decisions API khi lượt đã qua cổng giao/chốt
        reasons = _claim_support_reasons(item, closing, turns, judge)
    if not reasons:
        return False, []
    origin = _turn_by_id(turns, item.request_turn_id)
    if closing is None or origin is None or origin is closing or judge is None:
        return False, reasons
    accepted, accept_reasons = acceptance_reasons(item.text, origin, closing, turns, judge, chair)
    return (True, accept_reasons) if accepted else (False, [*reasons, *accept_reasons])


def _status_reasons(item: ActionItemCandidate | DecisionCandidate) -> list[str]:
    """Gắn cờ khi trạng thái agent tự khai chưa phải "đã giao/đã nhận" (việc giao) hay "đã chốt"."""

    if isinstance(item, ActionItemCandidate):
        if item.status in _ACTION_STATUSES_CLEAR:
            return []
        return [f"Agent tự đánh giá trạng thái là '{item.status}', chưa phải việc được giao/nhận."]
    if item.status in _DECISION_STATUSES_CLEAR:
        return []
    return [f"Agent tự đánh giá trạng thái là '{item.status}', chưa phải kết luận đã chốt."]


def _assignee_reasons(
    item: ActionItemCandidate, closing: SpeakerTurn | None, turns: tuple[SpeakerTurn, ...], actor_reasons: Sequence[str]
) -> list[str]:
    """Liệt kê lý do nghi ngờ về bên nhận của một việc giao.

    Gồm: chưa có bên nhận việc; các lý do định danh đã tính sẵn; và trường hợp agent ghi là "tự nhận
    việc" nhưng lượt chốt lại do người khác nói.

    Args:
        item: Việc giao đang kiểm.
        closing: Lượt chốt agent khai, có thể None.
        turns: Lượt nói của chủ đề, để đối chiếu tên bên nhận với người nói thật.
        actor_reasons: Lý do định danh bên nhận việc đã tính từ danh bạ.

    Returns:
        Danh sách lý do; rỗng nếu bên nhận việc rõ ràng.
    """

    reasons = [] if item.actor else ["Chưa xác định được người phụ trách (WHO)."]
    reasons.extend(actor_reasons)
    lead = item.mentions[0].name if item.mentions else item.actor
    if (
        item.status == "self_committed"
        and lead
        and closing is not None
        and closing.speaker
        and match_claimed_name_to_real_speaker(lead, turns) not in (None, closing.speaker.strip())
    ):
        reasons.append(
            f"Ghi là tự nhận việc nhưng lượt chốt {closing.turn_id} do '{closing.speaker}' nói, không phải '{lead}'."
        )
    return reasons


def check_evidence(
    item: ActionItemCandidate | DecisionCandidate,
    turns: tuple[SpeakerTurn, ...],
    judge: TurnActJudge | None = None,
    chair: MeetingChair | None = None,
    actor_reasons: Sequence[str] = (),
) -> Check:
    """Gắn nhãn CLEAR hoặc UNCERTAIN cho một việc giao hoặc kết luận: đã thật sự được giao/chốt chưa.

    Gộp lý do từ ba nguồn: bên nhận việc (chỉ với việc giao), trạng thái agent tự khai, và lượt chốt.
    Nếu mục được chốt nhờ một lượt tiếp nhận đề xuất thì trạng thái agent tự khai không còn bị xét.

    Args:
        item: Việc giao hoặc kết luận do agent trích.
        turns: Lượt nói của chủ đề.
        judge: Bộ phân loại hành vi lượt nói; None thì lượt chốt luôn bị gắn cờ.
        chair: Người chủ trì do phiên họp cung cấp, None nếu không có.
        actor_reasons: Lý do định danh bên nhận việc (chỉ dùng cho việc giao).

    Returns:
        Nhãn kèm danh sách lý do (rỗng khi CLEAR).
    """

    is_action = isinstance(item, ActionItemCandidate)
    closing = _turn_by_id(turns, item.confirm_turn_id)
    accepted, closing_reasons = _closing_turn_reasons(item, closing, turns, judge, chair)
    reasons = [
        *(_assignee_reasons(item, closing, turns, actor_reasons) if is_action else []),
        *([] if accepted else _status_reasons(item)),
        *closing_reasons,
    ]
    return Check("uncertain", tuple(reasons)) if reasons else Check("clear")


__all__ = [
    "acceptance_reasons",
    "check_evidence",
]
