"""Bước 1.2: gộp các dòng hiệu lực liền nhau của cùng một người thành một lượt nói.

Người nói được phân biệt theo mã chứ không theo tên, nên hai người trùng họ tên không bị gộp làm
một; tên hiển thị của người thứ hai trở đi được thêm số thứ tự để phân biệt.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from ...utils.config import TurnBuilderConfig
from ...utils.contracts import EffectiveTranscriptItem, SpeakerTurn


def known_min(values: Iterable[int | None]) -> int | None:
    """Trả giá trị nhỏ nhất trong các giá trị đã biết, bỏ qua None.

    Dùng cho mốc thời gian vốn là tuỳ chọn: "chưa biết" phải khác 0, nên không thay None bằng 0.

    Args:
        values: Các giá trị (ví dụ mốc bắt đầu tính bằng mili giây), có thể lẫn None.

    Returns:
        Giá trị nhỏ nhất; None nếu mọi giá trị đều None hoặc ``values`` rỗng.
    """

    known = [value for value in values if value is not None]
    return min(known) if known else None


def known_max(values: Iterable[int | None]) -> int | None:
    """Trả giá trị lớn nhất trong các giá trị đã biết, bỏ qua None; None nếu không có giá trị nào."""

    known = [value for value in values if value is not None]
    return max(known) if known else None

def _should_merge_into_same_turn(
    previous: EffectiveTranscriptItem,
    current: EffectiveTranscriptItem,
    config: TurnBuilderConfig,
) -> bool:
    """Quyết định dòng ``current`` có được gộp vào cùng lượt nói với dòng ``previous`` ngay trước nó.

    Hai dòng chỉ được gộp khi là cùng một người và cùng vai trò. Cùng người được xét theo mã người
    nói nếu cả hai dòng đều có mã, nếu không thì so theo tên. Dòng của người không xác định (không
    mã, không tên) chỉ được gộp khi cấu hình cho phép. Cuối cùng, khoảng nghỉ giữa hai dòng phải
    không vượt ngưỡng; thiếu mốc thời gian thì làm theo cấu hình.

    Args:
        previous: Dòng cuối của lượt nói đang dựng.
        current: Dòng kế tiếp cần xét.
        config: Cấu hình dựng lượt nói (khoảng nghỉ tối đa, cách xử lý người lạ và mốc thiếu).

    Returns:
        True nếu nên gộp vào cùng lượt nói.
    """

    if previous.speaker_id and current.speaker_id:
        if previous.speaker_id != current.speaker_id:
            return False
    elif previous.speaker != current.speaker:
        return False
    if previous.speaker_role != current.speaker_role:
        return False
    if previous.speaker_id is None and previous.speaker is None and not config.merge_unknown_speakers:
        return False
    if previous.end_ms is None or current.start_ms is None:
        return config.merge_when_timestamp_missing
    return current.start_ms - previous.end_ms <= config.max_gap_ms


TURN_ITEM_SEPARATOR = " "
"""Chuỗi ``build_speaker_turns`` chèn giữa hai dòng liên tiếp trong cùng một lượt nói."""


def build_speaker_turns(
    items: tuple[EffectiveTranscriptItem, ...],
    config: TurnBuilderConfig,
) -> tuple[SpeakerTurn, ...]:
    """Gộp các dòng hiệu lực liền kề của cùng một người nói thành các lượt nói.

    Dòng chỉ toàn khoảng trắng bị bỏ trước khi gộp. Nội dung lượt nói là các dòng nối bằng
    ``TURN_ITEM_SEPARATOR``; mốc thời gian là mốc sớm nhất và muộn nhất đã biết trong nhóm; tên,
    vai trò và mã người nói lấy theo dòng đầu nhóm. Mã lượt đánh số từ ``TURN_000001``. Hai người
    khác mã nhưng trùng tên hiển thị sẽ được thêm hậu tố " #2", " #3"... để tên là duy nhất.

    Args:
        items: Các dòng hiệu lực theo thứ tự thời gian.
        config: Cấu hình dựng lượt nói (khoảng nghỉ tối đa, có gộp người không xác định không...).

    Returns:
        Tuple lượt nói theo thứ tự, mỗi lượt giữ danh sách (mã dòng, nguyên văn) của các dòng
        nguồn; tuple rỗng nếu không dòng nào có nội dung.
    """

    items = tuple(item for item in items if item.text.strip())
    if not items:
        return ()

    groups: list[list[EffectiveTranscriptItem]] = [[items[0]]]
    for item in items[1:]:
        if _should_merge_into_same_turn(groups[-1][-1], item, config):
            groups[-1].append(item)
        else:
            groups.append([item])

    turns: list[SpeakerTurn] = []
    for index, group in enumerate(groups, start=1):
        turns.append(
            SpeakerTurn(
                turn_id=f"TURN_{index:06d}",
                speaker=group[0].speaker,
                text_exact=TURN_ITEM_SEPARATOR.join(item.text for item in group),
                start_ms=known_min([item.start_ms for item in group]),
                end_ms=known_max([item.end_ms for item in group]),
                speaker_role=group[0].speaker_role,
                speaker_id=group[0].speaker_id,
                source_items=tuple((item.item_id, item.text) for item in group),
            )
        )
    return _disambiguate_speaker_labels(turns)


def _disambiguate_speaker_labels(turns: list[SpeakerTurn]) -> tuple[SpeakerTurn, ...]:
    """Thêm hậu tố " #2", " #3"... vào tên của những người khác mã nhưng trùng tên hiển thị.

    Người xuất hiện đầu tiên giữ nguyên tên; người thứ hai trở đi (theo thứ tự xuất hiện) được
    đánh số. Lượt nói thiếu tên hoặc thiếu mã người nói không bị đổi.

    Args:
        turns: Lượt nói theo thứ tự.

    Returns:
        Tuple lượt nói cùng thứ tự, tên hiển thị đã duy nhất theo mã người nói.
    """

    ids_of_label: dict[str, list[str]] = {}
    for turn in turns:
        if turn.speaker and turn.speaker_id:
            ids = ids_of_label.setdefault(turn.speaker, [])
            if turn.speaker_id not in ids:
                ids.append(turn.speaker_id)
    labeled: list[SpeakerTurn] = []
    for turn in turns:
        rank = ids_of_label[turn.speaker].index(turn.speaker_id) if turn.speaker and turn.speaker_id else 0
        labeled.append(replace(turn, speaker=f"{turn.speaker} #{rank + 1}") if rank else turn)
    return tuple(labeled)



__all__ = [
    "TURN_ITEM_SEPARATOR",
    "build_speaker_turns",
]
