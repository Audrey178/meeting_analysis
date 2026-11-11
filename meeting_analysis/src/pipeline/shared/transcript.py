"""Làm việc với lượt nói và người nói (chỉ bằng luật): trình bày bản ghi để đưa vào prompt, lấy các
lượt nói thuộc một chủ đề, liệt kê và so khớp tên người nói.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ...utils.contracts import SpeakerTurn, TopicSegment
from .actors.names import name_key


def format_turn_text(turn: SpeakerTurn) -> str:
    """Trình bày nội dung một lượt nói, mỗi item đứng sau mã của nó để mô hình trích dẫn được.

    Ví dụ "<130> Em báo cáo tiến độ. <131> Dự kiến xong trước 15/11.". Lượt không có item nguồn thì
    trả nguyên văn lượt.

    Args:
        turn: Lượt nói.

    Returns:
        Nội dung lượt kèm mã item.
    """

    if not turn.source_items:
        return turn.text_exact
    return " ".join(f"<{item_id}> {text}" for item_id, text in turn.source_items)


def format_turns_as_transcript(turns: tuple[SpeakerTurn, ...]) -> str:
    """Dựng bản ghi văn bản đưa vào prompt, mỗi lượt nói một dòng dạng "[mã lượt|người nói] nội dung".

    Args:
        turns: Các lượt nói, theo thứ tự.

    Returns:
        Bản ghi nhiều dòng; người nói không rõ được ghi là "unknown".
    """

    return "\n".join(f"[{turn.turn_id}|{turn.speaker or 'unknown'}] {format_turn_text(turn)}" for turn in turns)


def get_turns_of_segment(
    segment: TopicSegment, turns_by_id: dict[str, SpeakerTurn]
) -> tuple[SpeakerTurn, ...]:
    """Lấy các lượt nói thuộc một đoạn chủ đề, theo đúng thứ tự trong đoạn.

    Args:
        segment: Đoạn chủ đề, chứa danh sách mã lượt.
        turns_by_id: Bảng tra mã lượt -> lượt nói của cả cuộc họp.

    Returns:
        Các lượt nói của đoạn; mã lượt không có trong bảng bị bỏ qua.
    """

    return tuple(
        turns_by_id[turn_id] for turn_id in (segment.turn_ids or ()) if turn_id in turns_by_id
    )


def turn_positions(turns: Sequence[SpeakerTurn]) -> dict[str, int]:
    """Lập bảng tra mã lượt -> vị trí (bắt đầu từ 0) trong ``turns``."""

    return {turn.turn_id: index for index, turn in enumerate(turns)}


def list_distinct_speaker_names(turns: tuple[SpeakerTurn, ...]) -> tuple[str, ...]:
    """Liệt kê tên các người nói khác nhau trong các lượt nói (một đoạn hoặc cả cuộc họp).

    Args:
        turns: Các lượt nói.

    Returns:
        Tên người nói không trùng, giữ thứ tự xuất hiện đầu tiên; bỏ người nói rỗng.
    """

    names: list[str] = []
    for turn in turns:
        speaker = (turn.speaker or "").strip()
        if speaker and speaker not in names:
            names.append(speaker)
    return tuple(names)


def match_claimed_name_to_real_speaker(
    claimed_name: str,
    turns: tuple[SpeakerTurn, ...],
    cited_turn_ids: tuple[str, ...] = (),
) -> str | None:
    """Đưa tên người do mô hình viết về đúng một người nói thật của đoạn.

    Prompt yêu cầu mô hình chép đúng tên nhưng không có gì bắt buộc, nên tên bịa có thể lọt vào kết
    quả. Hàm này chặn lại bằng cách thử lần lượt, khớp cách nào trước thì dùng cách đó:

    1. Khớp trọn tên sau khi chuẩn hoá như khi so tên (viết thường, bỏ phần trong ngoặc, bỏ xưng
       hô đứng đầu...), và chỉ một người nói có khoá đó.
    2. Tên mô hình viết là một phần nguyên từ của tên ĐÚNG MỘT người nói (ví dụ "Sơn" ứng với
       "Phạm Hồng Sơn"). Khớp nhiều người thì không đoán.
    3. Mọi lượt được trích dẫn đều do cùng một người nói: chọn người đó, vì bằng chứng đáng tin hơn
       một cái tên sai.

    Args:
        claimed_name: Tên do mô hình viết.
        turns: Các lượt nói của đoạn chủ đề.
        cited_turn_ids: Mã các lượt mà luận điểm trích dẫn; rỗng thì bỏ cách thứ 3.

    Returns:
        Tên người nói chuẩn, hoặc None nếu không khớp cách nào. Riêng đoạn hoàn toàn không có tên
        người nói thì không có gì để kiểm, trả nguyên tên mô hình viết (None nếu tên rỗng), để không
        loại hết luận điểm của bản ghi không gắn nhãn người nói.
    """

    speakers = list_distinct_speaker_names(turns)
    claimed = claimed_name.strip()
    if not speakers:
        return claimed or None

    by_key: dict[str, list[str]] = {}
    for name in speakers:
        by_key.setdefault(name_key(name), []).append(name)
    claimed_key = name_key(claimed)
    if claimed_key and len(by_key.get(claimed_key, ())) == 1:  # hai nhãn trùng khoá (chỉ khác ngoặc) thì không đoán
        return by_key[claimed_key][0]

    if claimed:
        pattern = re.compile(rf"(?<!\w){re.escape(claimed_key)}(?!\w)")
        partial = [name for key, names in by_key.items() for name in names if pattern.search(key)]
        if len(partial) == 1:
            return partial[0]

    cited = set(cited_turn_ids)
    cited_speakers = {
        (turn.speaker or "").strip() for turn in turns if turn.turn_id in cited
    }
    if len(cited_speakers) == 1 and next(iter(cited_speakers)) in speakers:
        return next(iter(cited_speakers))
    return None


__all__ = [
    "format_turn_text",
    "format_turns_as_transcript",
    "get_turns_of_segment",
    "list_distinct_speaker_names",
    "match_claimed_name_to_real_speaker",
    "turn_positions",
]
