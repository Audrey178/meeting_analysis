"""Đọc các trường phụ của request v3 (ngày họp, chủ trì, danh sách tham dự, danh sách việc)."""

from __future__ import annotations

import sys
from pathlib import Path

# Thiết lập sys.path viết trực tiếp tại đây; lý do không đưa vào module dùng chung xem
# khối tương tự trong main.py.
_BE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BE_DIR.parent
for _dir in (_BE_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from src.pipeline.shared.meeting_inputs.agenda import TaskAgenda, parse_task_agenda
from src.pipeline.shared.meeting_inputs.attendees import (
    AttendeeRoster,
    MeetingChair,
    parse_attendee_roster,
    parse_meeting_chair,
)


def read_meeting_date(payload: dict) -> str | None:
    """Lấy ngày họp ISO "YYYY-MM-DD" từ payload (``AnalyzeV3Request.model_dump()`` cho ra ``date``).

    Đầu vào: payload - transcript dạng dict.
    Đầu ra: chuỗi ISO, hoặc None nếu payload không có ngày họp.
    """

    value = payload.get("meeting_date")
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def read_chair(payload: dict) -> MeetingChair | None:
    """Người chủ trì từ ``chair`` (``{id, full_name}``) của request, None nếu không có.

    Tên được tra theo ``id`` trong danh sách tham dự lúc ``analyze`` chạy.

    Đầu vào: payload - ``AnalyzeV3Request.model_dump()``.
    Đầu ra: MeetingChair, hoặc None.
    """

    return parse_meeting_chair(payload.get("chair"))


def read_attendee_roster(payload: dict) -> AttendeeRoster | None:
    """Đọc danh sách tham dự (``attendees``) gửi kèm request, None nếu không có.

    Đầu vào: payload - ``AnalyzeRequest.model_dump()``.
    Đầu ra: AttendeeRoster hoặc None.
    Lỗi: ValueError nếu danh sách sai dạng (router trả 422).
    """

    attendees = payload.get("attendees")
    return parse_attendee_roster(attendees) if attendees else None


def read_task_agenda(payload: dict, roster: AttendeeRoster | None) -> TaskAgenda | None:
    """Đọc danh sách việc cần báo cáo (``tasks``) gửi kèm request, None nếu không có/rỗng.

    Đầu vào: payload - ``AnalyzeV3Request.model_dump()``; roster - danh sách tham dự để tra
        mã người/đơn vị.
    Đầu ra: TaskAgenda hoặc None.
    Lỗi: ValueError nếu danh sách sai dạng (router trả 422).
    """

    tasks = payload.get("tasks")
    if not tasks or not tasks.get("tasks"):
        return None
    return parse_task_agenda(tasks, roster)


__all__ = [
    "read_attendee_roster",
    "read_chair",
    "read_meeting_date",
    "read_task_agenda",
]
