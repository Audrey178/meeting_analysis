"""Danh sách việc cần báo cáo tiến độ trong phiên họp, đọc từ file đi kèm transcript.

Quy ước đặt tên giống ``attendees.py``: transcript ``inputs/<tên>.json`` có danh sách
việc ở ``inputs/<tên>.tasks.json`` cùng thư mục. Không có file thì pipeline chạy như cũ
(không có agent tiến độ, không tốn thêm lời gọi nào).

Dạng file::

    {
      "tasks": [
        {"id": "T1", "title": "...", "owner": "O2", "support": ["O7"], "reporter": "P3",
         "due": "2026-01-31", "last_status": "in_progress", "source": "..."}
      ]
    }

``id``, ``title``, ``owner`` là bắt buộc. ``owner``/``support``/``reporter`` là mã người
(``P*``) hoặc đơn vị (``O*``) trong file attendees; không có attendees, hoặc giá trị không
có dạng mã, thì được giữ như tên tự do. Không có trường từ khoá: việc được khớp với bản
ghi theo nghĩa (agent tiến độ + Decisions API), không theo chữ.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from .attendees import AttendeeRoster

TASK_FILE_SUFFIX = ".tasks.json"

TaskStatus = Literal["not_started", "in_progress", "done", "blocked"]
TASK_STATUSES: tuple[str, ...] = ("not_started", "in_progress", "done", "blocked")

# Giá trị có dạng mã trong file attendees ("P1", "O12"): phải tra được trong danh sách.
_REF_ID_PATTERN = re.compile(r"^[PO]\d+$")


@dataclass(frozen=True, slots=True)
class TaskParty:
    """Một bên liên quan tới việc (chủ trì, phối hợp, người báo cáo).

    Các trường:
        name: tên người/đơn vị (đã tra từ mã nếu có attendees).
        ref_id: mã trong file attendees (P1, O3...), None nếu là tên tự do.
    """

    name: str
    ref_id: str | None = None


@dataclass(frozen=True, slots=True)
class AgendaTask:
    """Một việc cần báo cáo tiến độ.

    Các trường:
        task_id: mã việc trong file danh sách.
        title: tên việc.
        owner: bên chủ trì.
        support: các bên phối hợp.
        reporter: người dự kiến báo cáo (chỉ là gợi ý cho prompt), None nếu không nêu.
        due: hạn hiện tại, ngày ISO; None nếu không có hạn.
        last_status: trạng thái gần nhất trước phiên họp, None nếu không nêu.
        source: văn bản/phiên họp đã giao việc.
    """

    task_id: str
    title: str
    owner: TaskParty
    support: tuple[TaskParty, ...] = ()
    reporter: TaskParty | None = None
    due: str | None = None
    last_status: TaskStatus | None = None
    source: str = ""

    @property
    def parties(self) -> tuple[TaskParty, ...]:
        """Bên chủ trì rồi các bên phối hợp."""

        return (self.owner, *self.support)


@dataclass(frozen=True, slots=True)
class TaskAgenda:
    """Danh sách việc cần báo cáo của một phiên họp (rỗng nếu không có file)."""

    tasks: tuple[AgendaTask, ...] = ()

    @property
    def task_ids(self) -> tuple[str, ...]:
        """Mã các việc, theo thứ tự trong file."""

        return tuple(task.task_id for task in self.tasks)

    def find(self, task_id: str | None) -> AgendaTask | None:
        """Tra việc theo mã.

        Đầu vào: task_id - mã việc (None thì trả None).
        Đầu ra: AgendaTask hoặc None nếu không có.
        """

        return next((task for task in self.tasks if task.task_id == task_id), None)


def _resolve_party(value: object, roster: AttendeeRoster | None, *, task_id: str, field: str) -> TaskParty:
    """Quy một giá trị ``owner``/``support``/``reporter`` về ``TaskParty``.

    Đầu vào: value - mã P*/O* hoặc tên tự do; roster - danh sách tham dự (None nếu không có);
        task_id, field - để báo lỗi.
    Đầu ra: TaskParty.
    Lỗi: ValueError nếu giá trị rỗng/sai kiểu, hoặc có dạng mã mà không có trong attendees.
    """

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Việc {task_id}: {field} phải là chuỗi khác rỗng")
    value = value.strip()
    if roster is not None:
        person = next((p for p in roster.people if p.person_id == value), None)
        if person is not None:
            return TaskParty(person.full_name, value)
        organization = roster.find_organization(value)
        if organization is not None:
            return TaskParty(organization.name, value)
    if _REF_ID_PATTERN.match(value):
        raise ValueError(f"Việc {task_id}: {field} '{value}' không có trong danh sách tham dự")
    return TaskParty(value)


def _read_due(value: object, task_id: str) -> str | None:
    """Đọc ``due``: ngày ISO hoặc None.

    Lỗi: ValueError nếu có giá trị mà không phải ngày "YYYY-MM-DD" hợp lệ.
    """

    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError(f"Việc {task_id}: due '{value}' không phải ngày YYYY-MM-DD") from exc


def parse_task_agenda(payload: dict, roster: AttendeeRoster | None = None) -> TaskAgenda:
    """Dựng ``TaskAgenda`` từ dict theo dạng file danh sách việc.

    Đầu vào: payload - dict có ``tasks`` (thiếu coi như rỗng); roster - danh sách tham dự
        để tra mã người/đơn vị (None nếu không có).
    Đầu ra: TaskAgenda.
    Lỗi: ValueError nếu một việc thiếu ``id``/``title``/``owner``, trùng ``id``, ``due`` không
        phải ngày, ``last_status`` lạ, hoặc mã người/đơn vị không có trong attendees.
    """

    entries = payload.get("tasks", [])
    if not isinstance(entries, list):
        raise ValueError("tasks phải là danh sách")
    tasks: list[AgendaTask] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("title") or not entry.get("owner"):
            raise ValueError(f"Việc thiếu id/title/owner: {entry}")
        task_id = str(entry["id"]).strip()
        if task_id in seen:
            raise ValueError(f"Trùng mã việc: {task_id}")
        seen.add(task_id)
        support = entry.get("support") or []
        if not isinstance(support, list):
            raise ValueError(f"Việc {task_id}: support phải là danh sách")
        last_status = entry.get("last_status") or None
        if last_status is not None and last_status not in TASK_STATUSES:
            raise ValueError(f"Việc {task_id}: last_status '{last_status}' không thuộc {TASK_STATUSES}")
        reporter = entry.get("reporter")
        tasks.append(
            AgendaTask(
                task_id=task_id,
                title=str(entry["title"]).strip(),
                owner=_resolve_party(entry["owner"], roster, task_id=task_id, field="owner"),
                support=tuple(
                    _resolve_party(value, roster, task_id=task_id, field="support") for value in support
                ),
                reporter=_resolve_party(reporter, roster, task_id=task_id, field="reporter") if reporter else None,
                due=_read_due(entry.get("due"), task_id),
                last_status=last_status,
                source=str(entry.get("source") or "").strip(),
            )
        )
    return TaskAgenda(tasks=tuple(tasks))


def task_path_for(transcript_path: str | Path) -> Path:
    """Đường dẫn file danh sách việc theo quy ước đặt tên.

    Đầu vào: transcript_path - đường dẫn transcript, vd ``inputs/x-v1.json``.
    Đầu ra: Path, vd ``inputs/x-v1.tasks.json``.
    """

    path = Path(transcript_path)
    return path.with_name(path.stem + TASK_FILE_SUFFIX)


def load_task_agenda(transcript_path: str | Path, roster: AttendeeRoster | None = None) -> TaskAgenda | None:
    """Đọc danh sách việc đi kèm một transcript (theo quy ước đặt tên).

    Đầu vào: transcript_path - đường dẫn transcript; roster - danh sách tham dự (tra mã).
    Đầu ra: TaskAgenda, hoặc None nếu không có file đi kèm.
    Lỗi: ValueError nếu file có nhưng sai dạng.
    """

    path = task_path_for(transcript_path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"File danh sách việc {path} không phải JSON hợp lệ: {exc}") from exc
    return parse_task_agenda(payload, roster)


__all__ = [
    "AgendaTask",
    "TASK_FILE_SUFFIX",
    "TASK_STATUSES",
    "TaskAgenda",
    "TaskParty",
    "TaskStatus",
    "load_task_agenda",
    "parse_task_agenda",
    "task_path_for",
]
