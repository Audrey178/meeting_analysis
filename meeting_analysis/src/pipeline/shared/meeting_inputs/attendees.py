"""Đọc danh sách người và đơn vị tham dự cuộc họp, từ file đặt cạnh bản ghi và cùng tên với bản ghi.

Với mỗi người: mã (trùng với mã người nói trong bản ghi), họ tên, chức vụ và đơn vị. Với mỗi đơn
vị: mã, tên, đơn vị cấp trên (nếu có), các tên gọi tắt hay dùng trong cuộc họp, và các lĩnh vực
phụ trách. Lĩnh vực phụ trách chỉ dùng làm tín hiệu dự phòng khi tên gọi không đủ để chọn đúng bên
nhận việc.

Không có file thì pipeline chỉ dựa vào những người đã phát biểu trong bản ghi.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..actors.names import name_key

ATTENDEE_FILE_SUFFIX = ".attendees.json"


@dataclass(frozen=True, slots=True)
class AttendeePerson:
    """Một người tham dự cuộc họp.

    Attributes:
        person_id: Mã trong file danh sách, trùng với mã người nói của người đó trong bản ghi.
        full_name: Họ tên đầy đủ.
        position: Chức vụ; rỗng nếu không nêu.
        org_id: Mã đơn vị công tác; None nếu không nêu.
    """

    person_id: str
    full_name: str
    position: str = ""
    org_id: str | None = None


@dataclass(frozen=True, slots=True)
class AttendeeOrganization:
    """Một đơn vị tham dự hoặc có thể được giao việc.

    Attributes:
        org_id: Mã trong file danh sách.
        name: Tên đơn vị.
        parent_id: Mã đơn vị cấp trên; None nếu là đơn vị cấp cao nhất.
        functions: Các lĩnh vực đơn vị phụ trách, chỉ dùng làm tín hiệu dự phòng khi chọn bên nhận việc.
        aliases: Các tên gọi tắt hay dùng trong cuộc họp, được khớp như tên đơn vị.
    """

    org_id: str
    name: str
    parent_id: str | None = None
    functions: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AttendeeRoster:
    """Danh sách người và đơn vị tham dự một phiên họp.

    Rỗng khi phiên họp không gửi kèm file; khi đó bên nhận việc chỉ được xác định trong số người
    đã phát biểu.

    Attributes:
        people: Người tham dự, theo thứ tự trong file.
        organizations: Đơn vị tham dự, theo thứ tự trong file.
    """

    people: tuple[AttendeePerson, ...] = ()
    organizations: tuple[AttendeeOrganization, ...] = ()

    def find_organization(self, org_id: str | None) -> AttendeeOrganization | None:
        """Tra một đơn vị theo mã.

        Args:
            org_id: Mã đơn vị; None thì trả None.

        Returns:
            Đơn vị có mã tương ứng, hoặc None nếu không có.
        """

        return next((org for org in self.organizations if org.org_id == org_id), None)


@dataclass(frozen=True, slots=True)
class MeetingChair:
    """Người chủ trì do phiên họp cung cấp trong request, không do pipeline đoán.

    Attributes:
        person_id: Mã người, cùng hệ mã với mã người nói trong bản ghi và mã trong danh sách tham dự;
            rỗng nếu không biết.
        full_name: Họ tên; rỗng nếu không biết.
    """

    person_id: str
    full_name: str = ""

    def resolve_name(self, roster: AttendeeRoster | None) -> str | None:
        """Lấy tên người chủ trì: ưu tiên tên trong danh sách tham dự, sau đó tới ``full_name``.

        Args:
            roster: Danh sách tham dự; None nếu không có.

        Returns:
            Tên đã bỏ khoảng trắng thừa, hoặc None nếu không có tên nào.
        """

        person = next((person for person in (roster.people if roster else ()) if person.person_id == self.person_id), None)
        return (person.full_name if person else self.full_name).strip() or None

    def with_roster_name(self, roster: AttendeeRoster | None) -> MeetingChair | None:
        """Trả bản sao có ``full_name`` là tên đã tra theo danh sách tham dự.

        Args:
            roster: Danh sách tham dự; None nếu không có.

        Returns:
            Bản sao người chủ trì, hoặc None nếu không có tên nào.
        """

        name = self.resolve_name(roster)
        return MeetingChair(person_id=self.person_id, full_name=name) if name else None

    def is_speaker(self, speaker: str | None, speaker_id: str | None = None) -> bool:
        """Kiểm tra một người nói có phải người chủ trì không.

        So theo mã khi cả hai bên đều có mã; thiếu mã thì so tên sau khi chuẩn hoá (viết thường, bỏ
    từ xưng hô đứng đầu như "anh", "chị").

        Args:
            speaker: Tên người nói như trong bản ghi.
            speaker_id: Mã người nói; None nếu lượt không có mã.

        Returns:
            True nếu người nói là người chủ trì.
        """

        if self.person_id and speaker_id:
            return speaker_id == self.person_id
        return bool(speaker) and name_key(speaker) == name_key(self.full_name)


def parse_meeting_chair(payload: dict | None) -> MeetingChair | None:
    """Dựng người chủ trì từ trường ``chair`` của request (dạng ``{id, full_name}``).

    Args:
        payload: Dữ liệu người chủ trì; None hoặc rỗng nếu phiên họp không cung cấp.

    Returns:
        Người chủ trì, hoặc None nếu không có.
    """

    if not payload:
        return None
    return MeetingChair(person_id=payload.get("id") or "", full_name=(payload.get("full_name") or "").strip())


def parse_attendee_roster(payload: dict) -> AttendeeRoster:
    """Dựng danh sách tham dự từ dữ liệu đã đọc của file danh sách tham dự.

    Args:
        payload: Dữ liệu file, có khoá ``people`` và ``organizations``; thiếu khoá nào coi như rỗng.

    Returns:
        Danh sách tham dự theo thứ tự trong file.

    Raises:
        ValueError: Khi một người thiếu mã hoặc họ tên, hoặc một đơn vị thiếu mã hoặc tên.
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
                parent_id=entry.get("parent_id") or None,
                functions=tuple(function.strip() for function in entry.get("functions", [])),
                aliases=tuple(alias.strip() for alias in entry.get("aliases", []) if alias.strip()),
            )
        )
    return AttendeeRoster(people=tuple(people), organizations=tuple(organizations))


def attendee_path_for(transcript_path: str | Path) -> Path:
    """Tính đường dẫn file danh sách tham dự đi kèm một bản ghi, theo quy ước đặt tên.

    Ví dụ bản ghi ``inputs/x-v1.json`` đi kèm file ``inputs/x-v1.attendees.json``.

    Args:
        transcript_path: Đường dẫn file bản ghi.

    Returns:
        Đường dẫn file danh sách tham dự (file có thể chưa tồn tại).
    """

    path = Path(transcript_path)
    return path.with_name(path.stem + ATTENDEE_FILE_SUFFIX)


def load_attendee_roster(transcript_path: str | Path) -> AttendeeRoster | None:
    """Đọc danh sách tham dự đi kèm một bản ghi, nếu có.

    Args:
        transcript_path: Đường dẫn file bản ghi.

    Returns:
        Danh sách tham dự, hoặc None nếu không có file đi kèm.

    Raises:
        ValueError: Khi file có nhưng không phải JSON hợp lệ hoặc thiếu trường bắt buộc.
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
    "MeetingChair",
    "attendee_path_for",
    "load_attendee_roster",
    "parse_attendee_roster",
    "parse_meeting_chair",
]
