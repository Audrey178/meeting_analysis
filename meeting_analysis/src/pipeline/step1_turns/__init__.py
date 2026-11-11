"""Bước 1: biến bản ghi cuộc họp thành các lượt nói.

Gồm ba việc nối tiếp: đọc file bản ghi, chọn ra nội dung "hiệu lực" của từng dòng (ưu tiên bản đã
được người duyệt sửa), rồi gộp các dòng liền nhau của cùng một người thành một lượt nói.
"""

from __future__ import annotations

from ...utils.adapters import parse_transcript_payload
from ...utils.config import load_default_config
from ...utils.contracts import SpeakerTurn
from .effective_transcript import resolve_effective_transcript
from .speaker_turns import build_speaker_turns


def build_meeting_turns(payload: dict) -> tuple[str, tuple[SpeakerTurn, ...]]:
    """Đọc bản ghi cuộc họp và dựng dãy lượt nói, điểm vào của bước 1.

    Chạy liền ba việc: đọc bản ghi, chọn nội dung hiệu lực của từng dòng (ưu tiên bản người duyệt
    đã sửa), rồi gộp các dòng liền nhau của cùng một người thành lượt nói theo cấu hình mặc định.

    Args:
        payload: Bản ghi dạng dict, đúng khuôn dữ liệu của request phân tích (ví dụ kết quả
            ``model_dump()`` của request). Chỉ được đọc, không bị sửa.

    Returns:
        Cặp (mã cuộc họp, tuple lượt nói theo thứ tự thời gian). Tuple rỗng nếu không dòng nào
        có nội dung.

    Raises:
        ValueError: Khi bản ghi không đúng khuôn dạng được hỗ trợ.
    """

    meeting_id, raw_items = parse_transcript_payload(payload)
    effective = resolve_effective_transcript(raw_items)
    turns = build_speaker_turns(effective, load_default_config().turn_builder)
    return meeting_id, tuple(turns)


__all__ = [
    "build_meeting_turns",
    "build_speaker_turns",
    "resolve_effective_transcript",
]
