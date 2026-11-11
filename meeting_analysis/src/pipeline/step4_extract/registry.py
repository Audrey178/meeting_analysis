"""Dựng danh bạ người nói của cả cuộc họp (một lần mỗi cuộc họp, không gọi mô hình): ai đã phát biểu,
kèm thông tin từ danh sách tham dự, người chủ trì và danh sách việc cần báo cáo.

Danh bạ được trình bày thành đoạn văn bản đưa vào prompt, mỗi người/đơn vị có một mã ngắn để agent
ghi lại khi nêu bên nhận việc.
"""



from __future__ import annotations

from collections.abc import Sequence
from xml.sax.saxutils import escape, quoteattr

from ...utils.contracts import SpeakerTurn
from ..shared.meeting_inputs.agenda import TaskAgenda
from ..shared.meeting_inputs.attendees import AttendeeRoster, MeetingChair
from ..shared.actors.resolution import DirectoryEntry, build_actor_directory
from ..shared.schemas import SpeakerRegistry
from ..shared.transcript import list_distinct_speaker_names


def build_speaker_registry(
    turns: Sequence[SpeakerTurn],
    roster: AttendeeRoster | None = None,
    *,
    chair: MeetingChair | None = None,
    agenda: TaskAgenda | None = None,
) -> SpeakerRegistry:
    """Dựng danh bạ người nói của cả cuộc họp từ các lượt nói và thông tin đầu vào của phiên họp.

    Mỗi tên người nói được gắn với mã người nói ở lượt đầu tiên người đó xuất hiện. Nếu mã người chủ trì
    không trùng mã người nói nào thì mã bị xoá, chỉ giữ tên, để vẫn nhận ra lượt của người chủ trì theo
    tên. Người chủ trì có tên rỗng thì coi như không có.

    Args:
        turns: Toàn bộ lượt nói của cuộc họp, theo thứ tự thời gian.
        roster: Danh sách tham dự (người và đơn vị). None thì dùng danh sách rỗng.
        chair: Người chủ trì do phiên họp cung cấp. None nếu không có; pipeline không tự đoán.
        agenda: Danh sách việc cần báo cáo tiến độ. None thì dùng danh sách rỗng.

    Returns:
        Danh bạ gồm tên người nói (không trùng, theo thứ tự xuất hiện), mã người nói tương ứng, danh
        sách tham dự, người chủ trì và danh sách việc.
    """

    names = list_distinct_speaker_names(tuple(turns))
    speaker_id_of_name: dict[str, str | None] = {}
    for turn in turns:
        speaker_id_of_name.setdefault((turn.speaker or "").strip(), turn.speaker_id)
    if chair is not None and chair.person_id not in {turn.speaker_id for turn in turns if turn.speaker_id}:
        chair = MeetingChair(person_id="", full_name=chair.full_name)
    return SpeakerRegistry(
        names=names,
        speaker_ids=tuple(speaker_id_of_name.get(name) for name in names),
        roster=roster or AttendeeRoster(),
        chair=chair if chair is not None and chair.full_name.strip() else None,
        agenda=agenda or TaskAgenda(),
    )


def format_registry_context(registry: SpeakerRegistry) -> str:
    """Trình bày danh bạ thành khối "bối cảnh cuộc họp" cho prompt của agent giao việc.

    Khối gồm danh sách người nói, danh bạ bên nhận việc (mỗi bên một mã ngắn để agent ghi mã thay vì
    tự viết tên) và danh sách việc cần báo cáo nếu có.

    Args:
        registry: Danh bạ người nói của cả cuộc họp.

    Returns:
        Các thẻ XML ``<speakers>``, ``<assignee_directory>`` (mỗi bên một ``<party id=...>``) và
        ``<progress_tasks>``, mỗi thẻ có khi có dữ liệu; một câu báo "không có danh sách người nói" nếu
        danh bạ hoàn toàn rỗng.
    """

    roster = registry.roster
    if not registry.names and not roster.people and not roster.organizations and not registry.agenda.tasks:
        return "(No speaker list.)"
    lines = []
    if registry.names:
        lines.append(f"<speakers>{escape(', '.join(registry.names))}</speakers>")
    directory = build_actor_directory(registry)
    if directory:
        lines.append("<assignee_directory>")
        lines.extend(
            f"<party id={quoteattr(entry.code)}>{escape(_describe_entry(entry, roster))}</party>" for entry in directory
        )
        lines.append("</assignee_directory>")
    if registry.agenda.tasks:
        lines.append(format_agenda(registry.agenda))
    return "\n".join(lines)


def _describe_entry(entry: DirectoryEntry, roster: AttendeeRoster) -> str:
    """Viết phần mô tả một mục danh bạ: tên kèm chức vụ, đơn vị, nhãn người nói khác hoặc tên gọi tắt."""

    if entry.actor_type == "organization":
        org = roster.find_organization(entry.ref_id)
        aliases = org.aliases if org else ()
        # Thiếu chức năng function
        return f"{entry.name} (unit; also called: {', '.join(aliases)})" if aliases else f"{entry.name} (unit)"
    person = next((person for person in roster.people if person.person_id == entry.ref_id), None)
    if person is None:
        return f"{entry.name} (speaker, not in the attendee list)"
    org = roster.find_organization(person.org_id)
    details = [part for part in (person.position, org.name if org else "") if part]
    other_labels = sorted(label for label in entry.speaker_names if label != entry.name)
    if other_labels:
        details.append("speaker label: " + ", ".join(other_labels))
    return f"{entry.name} ({', '.join(details)})" if details else entry.name


def format_agenda(agenda: TaskAgenda) -> str:
    """Trình bày danh sách việc cần báo cáo tiến độ thành khối XML ``<progress_tasks>`` cho prompt.

    Mỗi việc một thẻ ``<task id=...>`` chứa tên việc, kèm thuộc tính bên chủ trì, bên phối hợp, hạn và
    trạng thái trước phiên họp; thuộc tính nào trống thì bỏ.

    Args:
        agenda: Danh sách việc. Nên khác rỗng, vì thẻ bao ngoài luôn được in.

    Returns:
        Khối XML nhiều dòng.
    """

    lines = ["<progress_tasks>"]
    for task in agenda.tasks:
        attrs = {"id": task.task_id, "lead": task.owner.name}
        if task.support:
            attrs["support"] = ", ".join(party.name for party in task.support)
        if task.due:
            attrs["deadline"] = task.due
        if task.last_status:
            attrs["status_before_session"] = task.last_status
        rendered = " ".join(f"{key}={quoteattr(str(value))}" for key, value in attrs.items())
        lines.append(f"<task {rendered}>{escape(task.title)}</task>")
    lines.append("</progress_tasks>")
    return "\n".join(lines)


__all__ = [
    "build_speaker_registry",
    "format_agenda",
    "format_registry_context",
]
