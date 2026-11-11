"""Đọc file bản ghi cuộc họp ở các định dạng được hỗ trợ (định dạng chuẩn, định dạng cũ, và file xuất
từ hệ thống chuyển giọng nói thành chữ) thành dữ liệu thống nhất, không sửa được.

Phần này chỉ chép giá trị và kiểm tính hợp lệ (đúng kiểu, có mã dòng, thời gian hợp lý...). Nó không chỉnh
nội dung hay áp bản sửa của người duyệt; việc đó thuộc bước dựng bản ghi hiệu lực, nơi có thể ghi
lại nguồn gốc của từng thay đổi.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any, TypeAlias

from .contracts import RawTranscriptItem
from dataclasses import replace


TranscriptInput: TypeAlias = tuple[str, tuple[RawTranscriptItem, ...]]
_Scalar: TypeAlias = str | int | float | bool | None

_RAW_ITEM_FIELDS = frozenset(
    {
        "id",
        "item_id",
        "text",
        "speaker",
        "start_ms",
        "end_ms",
        "ref_id",
        "review",
        "revision",
    }
)
_LEGACY_TURN_FIELDS = frozenset(
    {
        "id",
        "item_id",
        "speaker_raw",
        "text",
        "t_start",
        "ref_id",
        "review",
        "revision",
    }
)
_REVIEW_FIELDS = frozenset({"text", "speaker", "revision"})
_STT_EXPORT_FIELDS = frozenset(
    {
        "id",
        "segment",
        "segment_html",
        "speaker_name",
        "speaker_org_unit",
        "start_time",
        "end_time",
        "ref_id",
        "recording_id",
    }
)


def parse_transcript_payload(
    payload: Mapping[str, Any],
    *,
    meeting_id_hint: str | None = None,
) -> TranscriptInput:
    """Đọc nội dung một file bản ghi (đã giải mã JSON) thành mã cuộc họp và các dòng thô.

    Tự nhận dạng định dạng:

    - File xuất từ hệ thống chuyển giọng nói: có ``items`` mà mỗi phần tử có ``segment`` hoặc
      ``speaker_name``, hoặc có ``transcript`` và ``full_text``.
    - Định dạng chuẩn: có ``meeting_id`` và ``items``.
    - Định dạng cũ: có ``meeting`` và ``turns``.

    Dữ liệu truyền vào chỉ được đọc, không bị sửa.

    Args:
        payload: Object gốc của file bản ghi.
        meeting_id_hint: Mã cuộc họp dự phòng (ví dụ lấy từ tên file), chỉ dùng cho file xuất khi
            trong file không có mã; None thì dùng ``"stt-export"``.

    Returns:
        Cặp (mã cuộc họp, tuple các dòng thô theo thứ tự trong file).

    Raises:
        ValueError: Khi không nhận ra định dạng, hoặc có trường sai kiểu/giá trị.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("transcript payload must be a mapping")

    if "items" in payload and _is_stt_export(payload):
        return _parse_stt_export_payload(
            payload,
            meeting_id_hint=meeting_id_hint,
        )
    if "items" in payload:
        return _parse_native_payload(payload)
    if "turns" in payload:
        return _parse_legacy_payload(payload)
    raise ValueError("unsupported transcript schema: expected 'items' or 'turns'")


def _is_stt_export(payload: Mapping[str, Any]) -> bool:
    """Nhận dạng file xuất từ hệ thống chuyển giọng nói qua phần tử object đầu tiên của ``items``.

    Nếu ``items`` không có object nào thì dựa vào việc gốc có cả ``transcript`` và ``full_text``.
    """
    items = payload.get("items")
    if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
        for item in items:
            if isinstance(item, Mapping):
                return "segment" in item or "speaker_name" in item
    return "transcript" in payload and "full_text" in payload


def _parse_stt_export_payload(
    payload: Mapping[str, Any],
    *,
    meeting_id_hint: str | None,
) -> TranscriptInput:
    """Đọc file xuất từ hệ thống chuyển giọng nói.

    Mã cuộc họp lấy theo thứ tự: ``meeting_id`` ở gốc, rồi ``meeting_id``/``recording_id`` trong
    ``metadata``, rồi ``meeting_id_hint``, cuối cùng là ``"stt-export"``.
    """
    metadata = payload.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, Mapping):
        raise ValueError("STT export field 'metadata' must be an object")

    meeting_id = _first_identifier(payload, ("meeting_id",))
    if meeting_id is None:
        meeting_id = _first_identifier(metadata, ("meeting_id", "recording_id"))
    meeting_id = meeting_id or meeting_id_hint or "stt-export"

    exported_items = _object_sequence(payload.get("items"), field="items")
    items = tuple(
        _parse_stt_export_item(item, index, metadata)
        for index, item in enumerate(exported_items)
    )
    items = _validate_unique_item_ids(items)
    return meeting_id, items


def _parse_native_payload(payload: Mapping[str, Any]) -> TranscriptInput:
    """Đọc định dạng chuẩn; ``meeting_id`` là bắt buộc."""
    meeting_id = _required_identifier(payload, "meeting_id", owner="transcript")
    raw_items = _object_sequence(payload.get("items"), field="items")

    items = tuple(_parse_native_item(item, index) for index, item in enumerate(raw_items))
    items = _validate_unique_item_ids(items)
    return meeting_id, items


def _parse_legacy_payload(payload: Mapping[str, Any]) -> TranscriptInput:
    """Đọc định dạng cũ (``meeting`` + ``turns``).

    Mã cuộc họp lấy từ ``meeting_id`` ở gốc, rồi ``meeting_id``/``id``/``session_number`` trong
    ``meeting``, cuối cùng là ``"legacy-meeting"``. Nếu mọi lượt đều có mốc bắt đầu bằng 0 hoặc thiếu
    (dấu hiệu bản ghi chuyển từ văn bản, không có thời gian) thì mốc thời gian được coi là không biết.
    """
    meeting = payload.get("meeting", {})
    if meeting is None:
        meeting = {}
    if not isinstance(meeting, Mapping):
        raise ValueError("legacy field 'meeting' must be an object")

    meeting_id = _first_identifier(payload, ("meeting_id",))
    if meeting_id is None:
        meeting_id = _first_identifier(meeting, ("meeting_id", "id", "session_number"))
    if meeting_id is None:
        meeting_id = "legacy-meeting"

    turns = _object_sequence(payload.get("turns"), field="turns")
    starts_seconds = tuple(
        _optional_seconds(turn.get("t_start", 0.0), field=f"turns[{index}].t_start")
        for index, turn in enumerate(turns)
    )
    # DOCX-derived records use 0.0 as an unknown-time sentinel on every turn.
    # A real timed transcript can legitimately begin at zero, so zero becomes
    # known whenever at least one later turn carries a non-zero timestamp.
    timeline_is_known = any(value not in (None, 0.0) for value in starts_seconds)

    items = tuple(
        _parse_legacy_turn(turn, index, starts_seconds[index], timeline_is_known)
        for index, turn in enumerate(turns)
    )
    items = _validate_unique_item_ids(items)
    return meeting_id, items


def _parse_native_item(item: Mapping[str, Any], index: int) -> RawTranscriptItem:
    """Đọc một dòng của định dạng chuẩn; ``index`` dùng để ghi vị trí trong thông điệp lỗi."""
    prefix = f"items[{index}]"
    item_id = _item_identifier(item, prefix)
    review = _review_mapping(item.get("review"), field=f"{prefix}.review")
    start_ms = _optional_milliseconds(item.get("start_ms"), field=f"{prefix}.start_ms")
    end_ms = _optional_milliseconds(item.get("end_ms"), field=f"{prefix}.end_ms")
    _validate_time_range(start_ms, end_ms, field=prefix)
    ref_ids = _reference_ids(item.get("ref_id"), field=f"{prefix}.ref_id")

    return RawTranscriptItem(
        item_id=item_id,
        text=_string(item.get("text", ""), field=f"{prefix}.text"),
        speaker=_optional_string(item.get("speaker"), field=f"{prefix}.speaker"),
        start_ms=start_ms,
        end_ms=end_ms,
        ref_id=ref_ids[0] if ref_ids else None,
        reviewed_text=_optional_string(review.get("text"), field=f"{prefix}.review.text"),
        reviewed_speaker=_optional_string(
            review.get("speaker"), field=f"{prefix}.review.speaker"
        ),
        revision=_revision(item, review, field=prefix),
        metadata=_metadata(item, review, excluded=_RAW_ITEM_FIELDS),
        ref_ids=ref_ids,
    )


def _parse_legacy_turn(
    turn: Mapping[str, Any],
    index: int,
    start_seconds: float | None,
    timeline_is_known: bool,
) -> RawTranscriptItem:
    """Đọc một lượt của định dạng cũ.

    Args:
        turn: Object của lượt.
        index: Vị trí lượt, dùng trong thông điệp lỗi.
        start_seconds: Mốc bắt đầu (giây) đã kiểm; None nếu thiếu.
        timeline_is_known: False thì bỏ mốc thời gian (để None) vì cả file không có thời gian thật.

    Returns:
        Dòng thô; ``end_ms`` luôn None vì định dạng cũ không có mốc kết thúc.
    """
    prefix = f"turns[{index}]"
    review = _review_mapping(turn.get("review"), field=f"{prefix}.review")
    start_ms = (
        round(start_seconds * 1000)
        if timeline_is_known and start_seconds is not None
        else None
    )
    ref_ids = _reference_ids(turn.get("ref_id"), field=f"{prefix}.ref_id")

    return RawTranscriptItem(
        item_id=_item_identifier(turn, prefix),
        text=_string(turn.get("text", ""), field=f"{prefix}.text"),
        speaker=_optional_string(turn.get("speaker_raw"), field=f"{prefix}.speaker_raw"),
        start_ms=start_ms,
        end_ms=None,
        ref_id=ref_ids[0] if ref_ids else None,
        reviewed_text=_optional_string(review.get("text"), field=f"{prefix}.review.text"),
        reviewed_speaker=_optional_string(
            review.get("speaker"), field=f"{prefix}.review.speaker"
        ),
        revision=_revision(turn, review, field=prefix),
        metadata=_metadata(turn, review, excluded=_LEGACY_TURN_FIELDS),
        ref_ids=ref_ids,
    )


def _parse_stt_export_item(
    item: Mapping[str, Any],
    index: int,
    root_metadata: Mapping[str, Any],
) -> RawTranscriptItem:
    """Đọc một dòng của file xuất từ hệ thống chuyển giọng nói.

    ``segment`` là nguyên văn; mốc thời gian đổi từ giây sang mili-giây; ``ref_id`` là mã người nói.
    Đơn vị công tác của người nói, mã bản ghi âm và thông tin chỉnh sửa ở cấp file được giữ lại trong
    ``metadata``, kèm dấu ``source_schema="stt_export"`` để bước sau biết nguồn.

    Args:
        item: Object của dòng; ``id`` có thể là chuỗi hoặc số nguyên.
        index: Vị trí dòng, dùng trong thông điệp lỗi.
        root_metadata: Mục ``metadata`` ở gốc file.

    Returns:
        Dòng thô.

    Raises:
        ValueError: Khi thiếu ``id``, sai kiểu, hoặc mốc kết thúc trước mốc bắt đầu.
    """

    prefix = f"items[{index}]"
    identifier = item.get("id")
    if isinstance(identifier, bool) or not isinstance(identifier, (str, int)):
        raise ValueError(f"{prefix} is missing a string or integer id")
    item_id = str(identifier).strip()
    if not item_id:
        raise ValueError(f"{prefix} is missing a non-empty id")

    start_seconds = _optional_seconds(
        item.get("start_time"), field=f"{prefix}.start_time"
    )
    end_seconds = _optional_seconds(
        item.get("end_time"), field=f"{prefix}.end_time"
    )
    start_ms = round(start_seconds * 1000) if start_seconds is not None else None
    end_ms = round(end_seconds * 1000) if end_seconds is not None else None
    _validate_time_range(start_ms, end_ms, field=prefix)

    speaker = _optional_string(
        item.get("speaker_name"), field=f"{prefix}.speaker_name"
    )
    ref_ids = _reference_ids(item.get("ref_id"), field=f"{prefix}.ref_id")
    metadata = list(_metadata(item, {}, excluded=_STT_EXPORT_FIELDS))
    metadata.append(("source_schema", "stt_export"))
    for key in ("speaker_org_unit", "recording_id"):
        value = item.get(key)
        if _is_scalar(value):
            metadata.append((key, value))
    for source_key, target_key in (
        ("has_edits", "source_has_edits"),
        ("last_edited", "source_last_edited"),
    ):
        value = root_metadata.get(source_key)
        if _is_scalar(value):
            metadata.append((target_key, value))

    return RawTranscriptItem(
        item_id=item_id,
        text=_string(item.get("segment", ""), field=f"{prefix}.segment"),
        speaker=speaker,
        start_ms=start_ms,
        end_ms=end_ms,
        ref_id=ref_ids[0] if ref_ids else None,
        metadata=tuple(metadata),
        ref_ids=ref_ids,
    )


def _object_sequence(value: Any, *, field: str) -> tuple[Mapping[str, Any], ...]:
    """Kiểm ``value`` là mảng các object và trả về dạng tuple; sai thì báo ``ValueError``."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"field '{field}' must be an array")
    objects: list[Mapping[str, Any]] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):
            raise ValueError(f"{field}[{index}] must be an object")
        objects.append(entry)
    return tuple(objects)


def _review_mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    """Lấy mục ``review`` (bản người duyệt sửa) của một dòng; None thì trả object rỗng."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _item_identifier(item: Mapping[str, Any], prefix: str) -> str:
    """Lấy mã dòng từ ``id`` (hoặc ``item_id``); phải là chuỗi khác rỗng, sai thì báo ``ValueError``."""

    # ``id`` is the documented wire field; ``item_id`` is accepted so an
    # already-materialized contract can be serialized and loaded again.
    value = item.get("id", item.get("item_id"))
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{prefix} is missing a non-empty id")
    return value


def _required_identifier(payload: Mapping[str, Any], key: str, *, owner: str) -> str:
    """Lấy chuỗi khác rỗng bắt buộc ở ``payload[key]``; thiếu thì báo ``ValueError``."""

    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner} is missing a non-empty {key}")
    return value


def _first_identifier(payload: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    """Lấy giá trị đầu tiên dùng được làm mã theo thứ tự ``keys`` (chuỗi khác rỗng hoặc số, đổi ra chuỗi).

    Returns:
        Mã tìm được, hoặc None nếu không khoá nào dùng được.
    """

    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def _validate_unique_item_ids(
    items: tuple[RawTranscriptItem, ...],
) -> tuple[RawTranscriptItem, ...]:
    """Trả bản sao ``items`` trong đó mã trùng được thêm hậu tố ``-1``, ``-2``...

    Dòng xuất hiện đầu tiên giữ mã gốc. Hàm không báo lỗi và không sửa ``items``: bên gọi phải dùng
    giá trị trả về thì mới có mã đã đổi.
    """

    seen: set[str] = set()
    result: list[RawTranscriptItem] = []

    for item in items:
        item_id = item.item_id

        if item_id in seen:
            suffix = 1
            new_id = f"{item_id}-{suffix}"

            while new_id in seen:
                suffix += 1
                new_id = f"{item_id}-{suffix}"

            item = replace(item, item_id=new_id)

        seen.add(item.item_id)
        result.append(item)

    return tuple(result)


def _string(value: Any, *, field: str) -> str:
    """Kiểm ``value`` là chuỗi và trả lại; sai thì báo ``ValueError``."""

    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _optional_string(value: Any, *, field: str) -> str | None:
    """Kiểm ``value`` là chuỗi hoặc None và trả lại; sai thì báo ``ValueError``."""

    if value is None:
        return None
    return _string(value, field=field)


def _reference_ids(value: Any, *, field: str) -> tuple[str, ...]:
    """Đọc mã người nói: một chuỗi hoặc mảng chuỗi khác rỗng; bỏ trùng, giữ thứ tự.

    Returns:
        Tuple mã người nói; rỗng nếu ``value`` là None.

    Raises:
        ValueError: Khi sai kiểu hoặc có phần tử rỗng.
    """

    if value is None:
        return ()
    values: Sequence[Any]
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = value
    else:
        raise ValueError(f"{field} must be a string, an array of strings, or null")

    result: list[str] = []
    for index, entry in enumerate(values):
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"{field}[{index}] must be a non-empty string")
        if entry not in result:
            result.append(entry)
    return tuple(result)


def _optional_milliseconds(value: Any, *, field: str) -> int | None:
    """Kiểm ``value`` là số mili-giây nguyên >= 0 (cho phép dạng ``1500.0``) hoặc None; sai thì báo lỗi."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be an integer number of milliseconds or null")
    if not math.isfinite(value) or value < 0 or not float(value).is_integer():
        raise ValueError(f"{field} must be a non-negative integer number of milliseconds")
    return int(value)


def _optional_seconds(value: Any, *, field: str) -> float | None:
    """Kiểm ``value`` là số giây hữu hạn >= 0 hoặc None, trả dạng float; sai thì báo ``ValueError``."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number of seconds or null")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be a non-negative finite number")
    return number


def _validate_time_range(start_ms: int | None, end_ms: int | None, *, field: str) -> None:
    """Báo ``ValueError`` nếu mốc kết thúc trước mốc bắt đầu; bỏ qua khi thiếu một trong hai."""

    if start_ms is not None and end_ms is not None and end_ms < start_ms:
        raise ValueError(f"{field}.end_ms must be greater than or equal to start_ms")


def _revision(
    item: Mapping[str, Any], review: Mapping[str, Any], *, field: str
) -> int:
    """Lấy số lần sửa: ưu tiên ``review.revision``, rồi ``item.revision``, mặc định 0.

    Raises:
        ValueError: Khi giá trị không phải số nguyên >= 0.
    """

    value = review.get("revision", item.get("revision", 0))
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field}.revision must be a non-negative integer")
    return value


def _metadata(
    item: Mapping[str, Any],
    review: Mapping[str, Any],
    *,
    excluded: frozenset[str],
) -> tuple[tuple[str, _Scalar], ...]:
    """Gom các trường lạ có giá trị vô hướng của dòng và của ``review`` để giữ lại.

    Nhờ vậy dữ liệu thêm của đầu vào không bị mất mà không cần mở rộng kiểu dữ liệu chung. Trường
    dạng object/mảng bị bỏ.

    Args:
        item: Object của dòng.
        review: Mục bản người duyệt sửa; khoá của nó được thêm tiền tố ``review.``.
        excluded: Các khoá đã được đọc thành trường riêng, không đưa vào.

    Returns:
        Tuple các cặp (khoá, giá trị) theo thứ tự xuất hiện.
    """

    metadata: list[tuple[str, _Scalar]] = []
    for key, value in item.items():
        if isinstance(key, str) and key not in excluded and _is_scalar(value):
            metadata.append((key, value))
    for key, value in review.items():
        if isinstance(key, str) and key not in _REVIEW_FIELDS and _is_scalar(value):
            metadata.append((f"review.{key}", value))
    return tuple(metadata)


def _is_scalar(value: Any) -> bool:
    """Cho biết ``value`` là giá trị vô hướng JSON: chuỗi, số, bool hoặc None."""

    return value is None or isinstance(value, (str, int, float, bool))


__all__ = ["TranscriptInput", "parse_transcript_payload"]
