"""Đọc an toàn kết quả dạng JSON mà mô hình trả về, chấp nhận các lỗi kiểu dữ liệu thường gặp (thiếu
trường, sai kiểu, chép thừa ký hiệu quanh mã lượt nói). Cũng lọc phần trích dẫn bằng chứng, chỉ
giữ những câu có thật trong bản ghi.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...utils.contracts import SpeakerTurn


def _extract_bare_turn_id(raw: str) -> str:
    """Lấy mã lượt "trần" từ giá trị mô hình trả về, kể cả khi mô hình chép cả cụm trong ngoặc.

    Ví dụ "[TURN_000020|Sơn]" thành "TURN_000020"; mã đã đúng dạng được giữ nguyên.
    """

    text = raw.strip().lstrip("[").rstrip("]")
    return text.split("|", 1)[0].strip()


def split_dict_entries(value: object) -> tuple[list[dict], int]:
    """Lấy các phần tử dạng dict từ một trường mà mô hình được yêu cầu trả về dạng danh sách.

    Args:
        value: Giá trị mô hình trả về cho trường danh sách.

    Returns:
        Cặp (các phần tử dict theo thứ tự, số phần tử bị bỏ vì sai kiểu). ``value`` là None (không
        có gì) thì số bị bỏ là 0; ``value`` không phải danh sách thì cả giá trị tính là 1 phần tử bị bỏ.
    """

    if value is None:
        return [], 0
    if not isinstance(value, list):
        return [], 1
    entries = [entry for entry in value if isinstance(entry, dict)]
    return entries, len(value) - len(entries)


def read_stripped_text(value: object) -> str:
    """Đọc một trường văn bản do mô hình trả về, đã bỏ khoảng trắng hai đầu.

    Giá trị không phải chuỗi (None, số, danh sách...) được coi là không có nội dung, thay vì bị ép
    thành chuỗi vô nghĩa như "123" hay "['a']".

    Args:
        value: Giá trị mô hình trả về.

    Returns:
        Chuỗi đã bỏ khoảng trắng hai đầu; chuỗi rỗng nếu ``value`` không phải chuỗi.
    """

    return value.strip() if isinstance(value, str) else ""


def read_list_or_empty(value: object) -> list:
    """Đọc một trường danh sách do mô hình trả về; sai kiểu hoặc thiếu thì coi là danh sách rỗng.

    Dùng cho danh sách mã bằng chứng: giá trị không phải danh sách (null, chuỗi...) nghĩa là luận
    điểm không có bằng chứng kiểm chứng được, nên sẽ bị loại ở bước sau.

    Args:
        value: Giá trị mô hình trả về.

    Returns:
        Chính ``value`` nếu là danh sách; ngược lại danh sách rỗng.
    """

    return value if isinstance(value, list) else []


def read_turn_id(turns: tuple[SpeakerTurn, ...], value: object) -> str | None:
    """Đọc một mã lượt do mô hình trả về và chỉ nhận nếu đó là lượt có thật trong đoạn.

    Args:
        turns: Các lượt nói của đoạn chủ đề đang xét.
        value: Giá trị mô hình trả về, có thể chép kèm ngoặc và tên người nói.

    Returns:
        Mã lượt trần hợp lệ; None nếu mã bịa, thuộc đoạn khác hoặc sai kiểu.
    """

    if not isinstance(value, str):
        return None
    turn_id = _extract_bare_turn_id(value)
    return turn_id if any(turn.turn_id == turn_id for turn in turns) else None


def _extract_bare_item_id(raw: object) -> str:
    """Lấy mã item "trần" từ giá trị mô hình trả về (130, "130", "<130>" đều thành "130")."""

    return str(raw).strip().strip("<>").strip()


def validate_evidence_items(
    turns: tuple[SpeakerTurn, ...], claimed_item_ids: list, required_turn_ids: Sequence[str | None] = ()
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Lọc bằng chứng mô hình trích theo mã item (dòng bản ghi thô) và suy ra các lượt nói chứa chúng.

    Mã item hợp lệ được giữ; nếu mô hình ghi mã lượt thay vì mã item thì lấy mọi item của lượt đó;
    mã không có trong đoạn bị bỏ. Các lượt bắt buộc (ví dụ lượt chốt) luôn có mặt trong danh sách
    lượt; item của chúng chỉ được thêm vào khi mô hình không trích được item hợp lệ nào. Vì vậy
    một lượt bắt buộc có thể có trong danh sách lượt mà không có item nào trong danh sách item.

    Args:
        turns: Các lượt nói của đoạn chủ đề đang xét.
        claimed_item_ids: Danh sách mã item do mô hình trả về, có thể sai dạng.
        required_turn_ids: Mã các lượt bắt buộc có trong bằng chứng; None và mã ngoài đoạn bị bỏ qua.

    Returns:
        Bộ ba (mã lượt, câu trích, mã item). Mã lượt và câu trích cùng độ dài, cùng thứ tự bản ghi;
        câu trích là nguyên văn cả lượt. Mã item theo thứ tự bản ghi.
    """

    turn_of_item = {item_id: turn.turn_id for turn in turns for item_id, _ in turn.source_items}
    turn_by_id = {turn.turn_id: turn for turn in turns}
    cited: set[str] = set()
    for raw in claimed_item_ids:
        if raw is None or isinstance(raw, bool):
            continue
        segment_id = _extract_bare_item_id(raw)
        if segment_id in turn_of_item:
            cited.add(segment_id)
            continue
        turn = turn_by_id.get(_extract_bare_turn_id(str(raw)))
        if turn is not None:
            cited.update(item_id for item_id, _ in turn.source_items)
            if not turn.source_items:
                cited.add(turn.turn_id)
    required = [turn_id for turn_id in required_turn_ids if turn_id in turn_by_id]
    if not any(segment_id in turn_of_item for segment_id in cited):
        for turn_id in required:
            cited.update(item_id for item_id, _ in turn_by_id[turn_id].source_items)
    kept_turns = {turn_of_item.get(segment_id, segment_id) for segment_id in cited} | set(required)
    ordered = [turn for turn in turns if turn.turn_id in kept_turns]
    item_ids = tuple(
        item_id for turn in ordered for item_id, _ in turn.source_items if item_id in cited
    )
    return (
        tuple(turn.turn_id for turn in ordered),
        tuple(turn.text_exact for turn in ordered),
        item_ids,
    )


__all__ = [
    "read_turn_id",
    "read_list_or_empty",
    "read_stripped_text",
    "split_dict_entries",
    "validate_evidence_items",
]
