"""Đọc danh sách việc cần báo cáo tiến độ trong cuộc họp, từ file đặt cạnh bản ghi và cùng tên với
bản ghi.

Mỗi việc có mã, tên việc và đơn vị chủ trì (bắt buộc), cùng các thông tin tuỳ chọn như đơn vị phối
hợp, người báo cáo, hạn chót và trạng thái lần trước. Người và đơn vị được ghi bằng mã trong danh
sách tham dự; nếu không có danh sách tham dự thì giữ như tên tự do.

Không có file thì pipeline bỏ qua phần tiến độ và không tốn thêm lời gọi nào. Việc được khớp với
lời nói trong cuộc họp theo nghĩa, không theo từ khoá.
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
    """Một bên liên quan tới việc: bên chủ trì, bên phối hợp hoặc người báo cáo.

    Attributes:
        name: Tên người hoặc đơn vị; đã tra từ mã nếu có danh sách tham dự.
        ref_id: Mã trong danh sách tham dự (P1, O3...); None nếu file ghi tên tự do.
    """

    name: str
    ref_id: str | None = None


@dataclass(frozen=True, slots=True)
class AgendaTask:
    """Một việc cần báo cáo tiến độ trong phiên họp, được giao từ trước.

    Attributes:
        task_id: Mã việc trong file danh sách.
        title: Tên việc.
        owner: Bên chủ trì.
        support: Các bên phối hợp; rỗng nếu không có.
        reporter: Người dự kiến báo cáo, chỉ dùng làm gợi ý trong prompt; None nếu không nêu.
        due: Hạn hiện tại dạng "YYYY-MM-DD"; None nếu không có hạn.
        last_status: Trạng thái gần nhất trước phiên họp; None nếu không nêu.
        source: Văn bản hoặc phiên họp đã giao việc; rỗng nếu không nêu.
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
        """Trả về bên chủ trì rồi tới các bên phối hợp."""

        return (self.owner, *self.support)


@dataclass(frozen=True, slots=True)
class TaskAgenda:
    """Danh sách việc cần báo cáo tiến độ của một phiên họp.

    Rỗng khi phiên họp không gửi kèm file; khi đó pipeline bỏ qua phần tiến độ.

    Attributes:
        tasks: Các việc theo thứ tự trong file.
    """

    tasks: tuple[AgendaTask, ...] = ()

    @property
    def task_ids(self) -> tuple[str, ...]:
        """Trả về mã các việc, theo thứ tự trong file."""

        return tuple(task.task_id for task in self.tasks)

    def find(self, task_id: str | None) -> AgendaTask | None:
        """Tra một việc theo mã.

        Args:
            task_id: Mã việc; None thì trả None.

        Returns:
            Việc có mã tương ứng, hoặc None nếu không có.
        """

        return next((task for task in self.tasks if task.task_id == task_id), None)


def _resolve_party(value: object, roster: AttendeeRoster | None, *, task_id: str, field: str) -> TaskParty:
    """Quy một giá trị bên chủ trì, phối hợp hoặc người báo cáo về ``TaskParty``.

    Giá trị trùng mã người hoặc đơn vị trong danh sách tham dự thì lấy tên từ đó; còn lại giữ như
    tên tự do, trừ khi nó có dạng mã (P*, O*) mà không tra được.

    Args:
        value: Mã người hoặc đơn vị, hoặc tên tự do.
        roster: Danh sách tham dự; None nếu không có.
        task_id: Mã việc, chỉ dùng để báo lỗi.
        field: Tên trường đang đọc, chỉ dùng để báo lỗi.

    Returns:
        Bên liên quan đã quy đổi.

    Raises:
        ValueError: Khi giá trị rỗng hoặc không phải chuỗi, hoặc có dạng mã mà không có trong danh
            sách tham dự.
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
    """Đọc hạn của việc thành ngày "YYYY-MM-DD", hoặc None nếu bỏ trống.

    Raises:
        ValueError: Khi có giá trị mà không phải ngày "YYYY-MM-DD" hợp lệ.
    """

    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError(f"Việc {task_id}: due '{value}' không phải ngày YYYY-MM-DD") from exc


def parse_task_agenda(payload: dict, roster: AttendeeRoster | None = None) -> TaskAgenda:
    """Dựng danh sách việc từ dữ liệu đã đọc của file danh sách việc.

    Args:
        payload: Dữ liệu file, có khoá ``tasks``; thiếu khoá thì coi như danh sách rỗng.
        roster: Danh sách tham dự để tra mã người và đơn vị; None nếu không có.

    Returns:
        Danh sách việc theo thứ tự trong file.

    Raises:
        ValueError: Khi ``tasks`` không phải danh sách, một việc thiếu mã, tên hoặc bên chủ trì, trùng
            mã việc, hạn không phải ngày, trạng thái cũ không hợp lệ, hoặc mã người/đơn vị không có
            trong danh sách tham dự.
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
    """Tính đường dẫn file danh sách việc đi kèm một bản ghi, theo quy ước đặt tên.

    Ví dụ bản ghi ``inputs/x-v1.json`` đi kèm file ``inputs/x-v1.tasks.json``.

    Args:
        transcript_path: Đường dẫn file bản ghi.

    Returns:
        Đường dẫn file danh sách việc (file có thể chưa tồn tại).
    """

    path = Path(transcript_path)
    return path.with_name(path.stem + TASK_FILE_SUFFIX)


def load_task_agenda(transcript_path: str | Path, roster: AttendeeRoster | None = None) -> TaskAgenda | None:
    """Đọc danh sách việc đi kèm một bản ghi, nếu có.

    Args:
        transcript_path: Đường dẫn file bản ghi.
        roster: Danh sách tham dự để tra mã người và đơn vị; None nếu không có.

    Returns:
        Danh sách việc, hoặc None nếu không có file đi kèm.

    Raises:
        ValueError: Khi file có nhưng không phải JSON hợp lệ hoặc sai khuôn dạng.
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
