"""Bước 2: chia dãy lượt nói thành các đoạn theo chủ đề (chưa có tên), bằng mô hình DialSTART.

Mô hình cần thư viện học sâu nặng nên không được nạp sẵn ở đây; nơi gọi tự tạo bộ chia đoạn một lần
rồi truyền vào.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ...utils.contracts import SpeakerTurn, TopicSegment

if TYPE_CHECKING:
    from .dialstart import DialStartSegmenter

# Cách DialSTART chọn ranh giới (xem ``select_boundaries`` trong ``dialstart.py``).
# Checkpoint chỉ được eval với số ranh giới oracle, nên khi chạy thật tự chọn ranh giới:
#   - làm mượt điểm khe (cửa sổ 5 lúc đo, nay 3): trên 12 cuộc họp Quốc hội có nhãn, bỏ bước này F1
#     segeval giảm 0.418 -> 0.297 -- tác động lớn nhất;
#   - ngưỡng depth mean + k*std, mỗi đoạn >= _MIN_SIZE lượt;
#   - bỏ đoạn vụn < _min_segment_chars ký tự (STT có nhiều lượt rất ngắn; chưa kiểm chứng bằng
#     nhãn vì lượt nói Quốc hội vốn dài);
#   - gộp đoạn liền kề có cosine embedding chủ đề >= _MERGE_THRESHOLD (Quốc hội: +0.025 F1);
#   - tách đoạn dài hơn _MAX_SEGMENT_CHARS ký tự để lời gọi LLM phía sau không nhận chủ đề quá lớn.
_SMOOTH_WINDOW = 3
_THRESHOLD_STD = 1.0
_MIN_SIZE = 4
_MERGE_THRESHOLD = None
_MAX_SEGMENT_CHARS = 35000
# Sàn ký tự mỗi đoạn = tổng ký tự / _MIN_SEGMENT_FRACTION, kẹp trong
# [_MIN_SEGMENT_CHARS_FLOOR, _MIN_SEGMENT_CHARS_CAP]. Cuộc họp dài (Quốc hội ~236k) chạm trần.
_MIN_SEGMENT_FRACTION = 15
_MIN_SEGMENT_CHARS_FLOOR = 1500
_MIN_SEGMENT_CHARS_CAP = 10000


def _min_segment_chars(item_chars: list[int]) -> int:
    """Tính số ký tự tối thiểu của một đoạn chủ đề, tỉ lệ theo độ dài cuộc họp.

    Args:
        item_chars: Độ dài (ký tự) của từng lượt nói.

    Returns:
        Một phần cố định của tổng số ký tự, kẹp trong khoảng sàn/trần đã cấu hình ở module.
    """

    scaled = sum(item_chars) // _MIN_SEGMENT_FRACTION
    return max(_MIN_SEGMENT_CHARS_FLOOR, min(_MIN_SEGMENT_CHARS_CAP, scaled))


def _speaker_line(turn: SpeakerTurn) -> str:
    """Dựng dòng "người nói: nội dung" của một lượt nói, đúng như dòng đưa vào prompt."""

    return f"{turn.speaker}: {turn.text_exact}" if turn.text_exact is not None else turn.text


def segment_turns(turns: Sequence[SpeakerTurn], segmenter: DialStartSegmenter) -> list[TopicSegment]:
    """Cắt dãy lượt nói thành các đoạn chủ đề liên tiếp, phủ kín ``turns``.

    Mô hình chỉ đọc nội dung lượt nói (không kèm tên người nói, giống dữ liệu huấn luyện), còn các
    ràng buộc độ dài đoạn được đo trên dòng "người nói: nội dung" vì đó là thứ vào prompt ở các
    bước sau. Các tham số chọn ranh giới lấy từ hằng số của module.

    Args:
        turns: Lượt nói từ bước 1, theo thứ tự.
        segmenter: Bộ chia đoạn DialSTART đã nạp checkpoint; nơi gọi tạo một lần rồi dùng lại.

    Returns:
        Danh sách đoạn chủ đề theo thứ tự; chỉ một đoạn nếu không tìm được ranh giới nào, rỗng
        nếu ``turns`` rỗng.
    """

    # Đo độ dài trên dòng "người nói: nội dung", vì đó là thứ vào prompt.
    item_chars = [len(_speaker_line(turn)) + 1 for turn in turns]
    boundaries = segmenter.predict_boundaries(
        [turn.text_exact for turn in turns],
        min_size=_MIN_SIZE,
        threshold_std=_THRESHOLD_STD,
        smooth_window=_SMOOTH_WINDOW,
        min_segment_chars=_min_segment_chars(item_chars),
        merge_threshold=_MERGE_THRESHOLD,
        max_segment_chars=_MAX_SEGMENT_CHARS,
        item_chars=item_chars,
    )
    return boundaries_to_topic_segments(turns, boundaries)


def boundaries_to_topic_segments(turns: Sequence[SpeakerTurn], boundaries: Sequence[int]) -> list[TopicSegment]:
    """Đóng gói dãy lượt nói đã cắt tại ``boundaries`` thành các đoạn chủ đề.

    Mã đoạn đánh số từ ``TOPIC_SEG_000000``. Nội dung đoạn là các dòng "người nói: nội dung" nối
    bằng xuống dòng; mỗi đoạn ghi mã các lượt nói của nó và chỉ số lượt đầu/cuối dạng nửa mở
    ``[start_turn, end_turn)``, tính từ 0. Khoảng rỗng (ranh giới trùng nhau) bị bỏ qua.

    Args:
        turns: Lượt nói theo thứ tự.
        boundaries: Chỉ số lượt nói bắt đầu mỗi đoạn mới, tăng dần, nằm trong ``(0, len(turns))``.

    Returns:
        Danh sách đoạn chủ đề phủ kín ``turns``; rỗng nếu ``turns`` rỗng.
    """

    lines = [_speaker_line(turn) for turn in turns]
    edges = [0, *boundaries, len(turns)]
    spans = [(lo, hi) for lo, hi in zip(edges[:-1], edges[1:]) if hi > lo]
    return [
        TopicSegment(
            segment_id=f"TOPIC_SEG_{index:06d}",
            turn_ids=tuple(turn.turn_id for turn in turns[lo:hi]),
            text="\n".join(lines[lo:hi]),
            start_turn=lo,
            end_turn=hi,
        )
        for index, (lo, hi) in enumerate(spans)
    ]


__all__ = [
    "boundaries_to_topic_segments",
    "segment_turns",
]
