"""Tiến độ các việc cần báo cáo (bước 4), chỉ dùng khi cuộc họp có danh sách việc.

Không có agent riêng: agent giao việc ghi cả việc mới lẫn tiến độ trong cùng một lời gọi. Mọi lời
nói về một việc cũ (báo cáo, làm lại, giao cho bên khác, đổi hay bỏ hạn, hoãn) chỉ được ghi vào
tiến độ, nên mỗi lời nói chỉ nằm ở một chỗ. Mô hình được xem toàn bộ danh sách việc và phải ghi cho
TỪNG việc: hoặc "không được nhắc tới", hoặc trạng thái kèm lượt nói nêu trạng thái đó.

Tiến độ đi qua cùng các chặng như việc giao và kết luận: trích ra ở đây, kiểm ở bước 5, gộp theo
việc ở bước 6.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from ..shared.actors.assignees import ASSIGNEES_SCHEMA, read_assignee_mentions
from ..shared.llm_output import (
    read_turn_id,
    read_list_or_empty,
    read_stripped_text,
    validate_evidence_items,
)
from ..shared.meeting_inputs.agenda import TaskAgenda
from ..shared.prompts import VIETNAMESE_VALUE
from ..shared.schemas import UPDATE_STATUSES, ActionItemCandidate, ProgressUpdate, ExtractorInput
from .deadline import resolve_deadline

logger = logging.getLogger(__name__)

# Giới hạn độ dài các trường văn bản tự do (model trên gemma từng sinh chuỗi vô tận).
_MAX_SUMMARY_CHARS = 400
_MAX_BLOCKERS = 2
_MAX_BLOCKER_CHARS = 200

_DEADLINE_KINDS = ["exact", "before", "end_of_period", "relative", "unknown"]
# Trạng thái chỉ có trong schema: đoạn không nêu tình trạng việc; mục này không được đọc.
_NOT_DISCUSSED = "not_discussed"


def build_update_schema(task_ids: Sequence[str]) -> dict:
    """Dựng schema JSON cho trường tiến độ ``updates``: một khoá bắt buộc cho mỗi việc trong danh sách.

    Mô hình phải điền cho từng việc (được phép ghi "not_discussed") thay vì một mảng tuỳ chọn, vì với
    mảng tuỳ chọn mô hình hay bỏ sót việc. ``summary`` đứng đầu để mô hình viết điều đoạn họp nói về
    việc trước rồi mới chọn trạng thái (Cái Mép 2026-11-11: trạng thái đứng trước thì T3 ra
    "in_progress" dù tóm tắt ghi "đã giải trình, tiếp thu"); các trường còn lại giữ thứ tự cũ.

    Args:
        task_ids: Mã các việc trong danh sách; không rỗng.

    Returns:
        Schema của trường ``updates``.
    """

    item = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": VIETNAMESE_VALUE},
            "status": {"type": "string", "enum": [*UPDATE_STATUSES, _NOT_DISCUSSED]},
            "status_turn_id": {"type": ["string", "null"]},
            "request_turn_id": {"type": ["string", "null"]},
            "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
            "deadline": {"type": ["string", "null"], "description": VIETNAMESE_VALUE},
            "deadline_date": {"type": ["string", "null"]},
            "deadline_kind": {"type": "string", "enum": _DEADLINE_KINDS},
            "deadline_extended": {"type": "boolean"},
            "assignees": ASSIGNEES_SCHEMA,
            "blockers": {"type": "array", "items": {"type": "string", "description": VIETNAMESE_VALUE}},
            "directive": {"type": ["string", "null"], "description": VIETNAMESE_VALUE},
        },
    }
    item["required"] = list(item["properties"])
    return {
        "type": "object",
        "properties": {task_id: item for task_id in task_ids},
        "required": list(task_ids),
    }


def _read_blockers(value: object) -> tuple[str, ...]:
    """Đọc danh sách vướng mắc: tối đa ``_MAX_BLOCKERS`` chuỗi khác rỗng, mỗi chuỗi đã cắt bớt."""

    blockers = [read_stripped_text(entry)[:_MAX_BLOCKER_CHARS] for entry in read_list_or_empty(value)]
    return tuple(blocker for blocker in blockers if blocker)[:_MAX_BLOCKERS]


def as_assignment(update: ProgressUpdate, task_title: str) -> ActionItemCandidate:
    """Biểu diễn phần giao lại trong một cập nhật tiến độ dưới dạng việc giao.

    Dùng để xác định bên nhận của lời giao lại theo cùng cách như với việc giao mới.

    Args:
        update: Cập nhật tiến độ.
        task_title: Tên việc trong danh sách, dùng khi cập nhật không có cả chỉ đạo lẫn tóm tắt.

    Returns:
        Việc giao có nội dung là chỉ đạo, tóm tắt hoặc tên việc (theo thứ tự ưu tiên); lượt chốt là
        lượt nêu trạng thái.
    """

    return ActionItemCandidate(
        segment_id=update.segment_id,
        actor=None,
        text=update.directive or update.summary or task_title,
        evidence_turn_ids=update.evidence_turn_ids,
        quotes=update.quotes,
        confirm_turn_id=update.status_turn_id,
        mentions=update.mentions,
    )


def update_position(update: ProgressUpdate, positions: Mapping[str, int]) -> int:
    """Xác định vị trí của một cập nhật tiến độ trong bản ghi.

    Lấy vị trí lượt nêu trạng thái; không có thì lấy lượt bằng chứng muộn nhất.

    Args:
        update: Cập nhật tiến độ.
        positions: Vị trí của từng lượt nói trong bản ghi, theo mã lượt.

    Returns:
        Vị trí tìm được, hoặc -1 nếu không lượt nào có trong ``positions``.
    """

    if update.status_turn_id in positions:
        return positions[update.status_turn_id]
    return max((positions.get(turn_id, -1) for turn_id in update.evidence_turn_ids), default=-1)


def read_progress_updates(value: object, topic: ExtractorInput, agenda: TaskAgenda) -> list[ProgressUpdate]:
    """Đọc tiến độ mô hình ghi cho từng việc trong một chủ đề (chưa kiểm chứng).

    Việc được ghi "not_discussed" bị bỏ qua. Mục có mã việc ngoài danh sách, sai dạng hoặc không có
    bằng chứng hợp lệ bị loại và ghi log. Trạng thái lạ thành "mentioned". Lượt nêu trạng thái không
    thuộc chủ đề thành None để bước kiểm chứng xử lý tiếp; lượt nêu yêu cầu trùng lượt nêu trạng thái
    thì bỏ. Cờ gia hạn chỉ được giữ khi lời nói không kèm hạn mới.

    Args:
        value: Giá trị ``updates`` mô hình trả về, khoá là mã việc; có thể sai dạng.
        topic: Gói dữ liệu của chủ đề.
        agenda: Danh sách việc cần báo cáo.

    Returns:
        Danh sách cập nhật tiến độ, mỗi việc tối đa một mục.
    """

    segment_id = topic["segment_id"]
    entries = value if isinstance(value, Mapping) else {}
    dropped = 0 if isinstance(value, Mapping) or value is None else 1
    updates: list[ProgressUpdate] = []
    turns = topic["turns"]
    for task_id, item in entries.items():
        if agenda.find(task_id) is None or not isinstance(item, Mapping):
            dropped += 1
            continue
        if item.get("status") == _NOT_DISCUSSED:
            continue
        status_turn_id = read_turn_id(turns, item.get("status_turn_id"))
        request_turn_id = read_turn_id(turns, item.get("request_turn_id"))
        if request_turn_id == status_turn_id:
            request_turn_id = None
        evidence_turn_ids, quotes, item_ids = validate_evidence_items(
            turns, read_list_or_empty(item.get("evidence_segment_ids")), [status_turn_id, request_turn_id]
        )
        if not evidence_turn_ids:
            dropped += 1
            continue
        status = item.get("status")
        deadline_raw = read_stripped_text(item.get("deadline")) or None
        deadline = resolve_deadline(item, deadline_raw, topic.get("meeting_date"))
        updates.append(
            ProgressUpdate(
                segment_id=segment_id,
                task_id=task_id,
                status=status if status in UPDATE_STATUSES else "mentioned",
                status_turn_id=status_turn_id,
                evidence_turn_ids=evidence_turn_ids,
                quotes=quotes,
                item_ids=item_ids,
                summary=read_stripped_text(item.get("summary"))[:_MAX_SUMMARY_CHARS],
                blockers=_read_blockers(item.get("blockers")),
                directive=read_stripped_text(item.get("directive"))[:_MAX_SUMMARY_CHARS],
                deadline_raw=deadline_raw,
                deadline_date=deadline.deadline_date,
                deadline_kind=deadline.deadline_kind,
                deadline_extended=item.get("deadline_extended") is True and deadline_raw is None,
                mentions=read_assignee_mentions(item.get("assignees")),
                request_turn_id=request_turn_id,
            )
        )
    if dropped:
        logger.warning("action_agent segment %s: bỏ %d cập nhật tiến độ sai mã việc/không có bằng chứng", segment_id, dropped)
    return updates


__all__ = [
    "as_assignment",
    "build_update_schema",
    "read_progress_updates",
    "update_position",
]
