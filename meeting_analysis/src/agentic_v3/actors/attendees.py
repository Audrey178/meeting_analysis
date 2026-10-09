"""Danh sách người tham dự phiên họp (người + đơn vị), đọc từ file đi kèm transcript.

Quy ước đặt tên: transcript ``inputs/<tên>.json`` có danh sách ở
``inputs/<tên>.attendees.json`` cùng thư mục. Không có file thì pipeline chạy như cũ
(chỉ dùng người nói trong bản ghi).

Dạng file::

    {
      "people": [{"id": "P1", "full_name": "...", "position": "...", "org_id": "O1"}],
      "organizations": [{"id": "O1", "name": "...", "aliases": ["..."], "functions": ["...", "..."]}]
    }

``position`` là chức vị; ``functions`` là các mảng việc đơn vị phụ trách, dùng làm tín
hiệu dự phòng khi tên gọi trong bản ghi không đủ để chọn đúng người/đơn vị.
``aliases`` (tuỳ chọn) là các tên gọi tắt của đơn vị trong bản ghi ("Đảng ủy ban" cho
"Đảng ủy UBND Thành phố") mà luật viết tắt không suy ra được.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ATTENDEE_FILE_SUFFIX = ".attendees.json"


@dataclass(frozen=True, slots=True)
class AttendeePerson:
    """Một người tham dự.

    Các trường:
        person_id: mã trong file danh sách.
        full_name: họ tên đầy đủ.
        position: chức vị.
        org_id: mã đơn vị công tác (có thể None).
    """

    person_id: str
    full_name: str
    position: str = ""
    org_id: str | None = None


@dataclass(frozen=True, slots=True)
class AttendeeOrganization:
    """Một đơn vị tham dự hoặc có thể được giao việc.

    Các trường:
        org_id: mã trong file danh sách.
        name: tên đơn vị.
        functions: các mảng việc đơn vị phụ trách.
        aliases: các tên gọi tắt trong bản ghi, khớp như tên đơn vị.
    """

    org_id: str
    name: str
    functions: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AttendeeRoster:
    """Danh sách người và đơn vị tham dự một phiên họp (rỗng nếu không có file)."""

    people: tuple[AttendeePerson, ...] = ()
    organizations: tuple[AttendeeOrganization, ...] = ()

    def find_organization(self, org_id: str | None) -> AttendeeOrganization | None:
        """Tra đơn vị theo mã.

        Đầu vào: org_id - mã đơn vị (None thì trả None).
        Đầu ra: AttendeeOrganization hoặc None nếu không có.
        """

        return next((org for org in self.organizations if org.org_id == org_id), None)


def parse_attendee_roster(payload: dict) -> AttendeeRoster:
    """Dựng ``AttendeeRoster`` từ dict theo dạng file danh sách.

    Đầu vào: payload - dict có ``people`` và ``organizations`` (thiếu khoá nào coi như rỗng).
    Đầu ra: AttendeeRoster.
    Lỗi: ValueError nếu một người thiếu ``id``/``full_name`` hoặc một đơn vị thiếu ``id``/``name``.
    """

    people = []
    for entry in payload.get("people", []):
        if not entry.get("id") or not entry.get("full_name"):
            raise ValueError(f"Người tham dự thiếu id/full_name: {entry}")
        people.append(
            AttendeePerson(
                person_id=entry["id"],
                full_name=entry["full_name"].strip(),
                position=(entry.get("position") or "").strip(),
                org_id=entry.get("org_id"),
            )
        )
    organizations = []
    for entry in payload.get("organizations", []):
        if not entry.get("id") or not entry.get("name"):
            raise ValueError(f"Đơn vị tham dự thiếu id/name: {entry}")
        organizations.append(
            AttendeeOrganization(
                org_id=entry["id"],
                name=entry["name"].strip(),
                functions=tuple(function.strip() for function in entry.get("functions", [])),
                aliases=tuple(alias.strip() for alias in entry.get("aliases", []) if alias.strip()),
            )
        )
    return AttendeeRoster(people=tuple(people), organizations=tuple(organizations))


def attendee_path_for(transcript_path: str | Path) -> Path:
    """Đường dẫn file danh sách theo quy ước đặt tên.

    Đầu vào: transcript_path - đường dẫn transcript, vd ``inputs/x-v1.json``.
    Đầu ra: Path, vd ``inputs/x-v1.attendees.json``.
    """

    path = Path(transcript_path)
    return path.with_name(path.stem + ATTENDEE_FILE_SUFFIX)


def load_attendee_roster(transcript_path: str | Path) -> AttendeeRoster | None:
    """Đọc danh sách người tham dự đi kèm một transcript (theo quy ước đặt tên).

    Đầu vào: transcript_path - đường dẫn transcript.
    Đầu ra: AttendeeRoster, hoặc None nếu không có file đi kèm.
    Lỗi: ValueError nếu file có nhưng sai dạng (JSON hỏng hoặc thiếu trường bắt buộc).
    """

    path = attendee_path_for(transcript_path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"File danh sách {path} không phải JSON hợp lệ: {exc}") from exc
    return parse_attendee_roster(payload)


__all__ = [
    "ATTENDEE_FILE_SUFFIX",
    "AttendeeOrganization",
    "AttendeePerson",
    "AttendeeRoster",
    "attendee_path_for",
    "load_attendee_roster",
    "parse_attendee_roster",
]
