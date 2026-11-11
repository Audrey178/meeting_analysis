"""Phần chung của agent giao việc và agent kết luận: các góp ý, đề xuất của thành viên được người chủ
trì tiếp nhận.

Cả hai agent liệt kê các góp ý kèm phản hồi trước khi viết kết quả. Góp ý nào được tiếp nhận thì
trở thành một mục ngay khi đọc, thay vì trông vào mô hình tự chép sang, vì thực nghiệm cho thấy mô
hình liệt kê đủ nhưng hay chép thiếu.

Không đoán ai là người chủ trì. Ý do chính người chủ trì nêu thì không tính ở đây, vì đó đã là lời
giao việc hay chốt trực tiếp. Việc góp ý có thật được tiếp nhận hay không sẽ được kiểm ở bước 5.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ...utils.contracts import SpeakerTurn
from ..shared.meeting_inputs.attendees import MeetingChair
from ..shared.llm_output import (
    read_turn_id,
    split_dict_entries,
)

# Phản hồi với một ý góp ý.
RESPONSES = ("accepted", "rejected", "not_addressed")
# Loại lời nêu ý do model tự khai theo NỘI DUNG lượt nói, không theo vai người nói (``member_points``):
# chỉ góp ý mới có thể được tiếp nhận. Thiếu trường này model coi nội dung đơn vị trình tự giới thiệu là
# ý góp ý được tiếp nhận (Cái Mép: 6 kết luận thừa ở lượt trình bày).
POINT_KINDS = ("feedback", "presentation", "closing_statement")


@dataclass(frozen=True, slots=True)
class AcceptedMemberInput:
    """Một góp ý, đề xuất của thành viên mà mô hình ghi là được tiếp nhận.

    Attributes:
        entry: Mục nguyên bản mô hình trả về; mỗi agent tự đọc các trường riêng của mình từ đây.
        request_turn_id: Lượt nêu góp ý. None nếu mô hình ghi lượt không thuộc chủ đề hoặc sai dạng.
        response_turn_id: Lượt tiếp nhận. None nếu mô hình ghi lượt không thuộc chủ đề hoặc sai dạng.
    """

    entry: dict
    request_turn_id: str | None
    response_turn_id: str | None


def accepted_member_inputs(
    entries: object,
    turns: Sequence[SpeakerTurn],
    chair: MeetingChair | None,
    *,
    members_only: bool = False,
) -> list[AcceptedMemberInput]:
    """Lọc các góp ý mà mô hình ghi phản hồi là "accepted".

    Góp ý có lượt nêu do chính người chủ trì nói thì bị bỏ, vì lời người chủ trì tự nêu đã là lời giao
    việc hay chốt trực tiếp. Mục sai dạng bị bỏ qua. Góp ý có thật được tiếp nhận hay không chưa được
    kiểm ở đây mà ở bước kiểm chứng.

    Args:
        entries: Giá trị mảng góp ý mô hình trả về; có thể sai dạng.
        turns: Các lượt nói của chủ đề, dùng để kiểm mã lượt mô hình ghi.
        chair: Người chủ trì do phiên họp cung cấp. None thì không lọc theo người nói.
        members_only: True thì chỉ giữ ý mô hình xếp loại "feedback" (bỏ phần trình bày và lời
            phát biểu kết luận); agent kết luận bật cờ này, agent giao việc thì không.

    Returns:
        Danh sách góp ý được tiếp nhận, giữ thứ tự mô hình trả về.
    """

    items, _ = split_dict_entries(entries)
    accepted = []
    for entry in items:
        if entry.get("response") != "accepted":
            continue
        if members_only and entry.get("point_kind") != "feedback":
            continue
        request_turn_id = read_turn_id(turns, entry.get("turn_id"))
        request_turn = next((turn for turn in turns if turn.turn_id == request_turn_id), None)
        if chair and request_turn and chair.is_speaker(request_turn.speaker, request_turn.speaker_id):
            continue
        response_turn_id = read_turn_id(turns, entry.get("response_turn_id"))
        accepted.append(AcceptedMemberInput(entry, request_turn_id, response_turn_id))
    return accepted


__all__ = [
    "AcceptedMemberInput",
    "POINT_KINDS",
    "RESPONSES",
    "accepted_member_inputs",
]
