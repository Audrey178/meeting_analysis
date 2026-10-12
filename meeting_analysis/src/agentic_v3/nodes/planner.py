"""Planner (Plan-and-Execute, luật, 0 token): chạy MỘT lần trước khi các chủ đề tách song song.

Lập hai thứ:

1. ``SpeakerRegistry`` -- danh bạ người nói của cả cuộc họp. Thay ngữ cảnh
   ``known_names``/``known_assignments`` chạy dồn của v1 (lý do duy nhất khiến v1
   phải xử lý chủ đề tuần tự). Khác v1: danh bạ thấy cả người chỉ xuất hiện ở chủ
   đề SAU; đổi lại không còn tên do agent tự gán (có thể sai) lan sang chủ đề sau.
2. ``TopicPlan`` cho từng chủ đề -- có chạy Action/Decision agent không. Chủ đề
   không có cụm giao/nhận/chốt việc nào thì bỏ agent tương ứng. Cue cố ý RỘNG
   (gồm cả "sẽ", "nhận", "làm") vì bỏ nhầm làm mất kết quả (giảm recall), còn
   chạy thừa chỉ tốn một lời gọi. Content agent không bao giờ bị bỏ.
   Agent tiến độ chạy ở MỌI chủ đề khi phiên họp có danh sách việc cần báo cáo
   (``SpeakerRegistry.agenda``): agent tự chọn việc nào chủ đề có nhắc, Planner không
   lọc theo từ khoá.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from ..core._shared import (
    get_turns_of_segment,
    list_distinct_speaker_names,
    match_claimed_name_to_real_speaker,
)
from ...utils.contracts import SpeakerTurn, TopicSegment
from ..actors.agenda import TaskAgenda
from ..actors.attendees import AttendeeRoster
from ..schemas import SpeakerRegistry, TopicPlan

# Cụm cho thấy CÓ THỂ có việc được giao/nhận trong chủ đề.
ACTION_CUES: tuple[str, ...] = (
    "giao", "phân công", "phụ trách", "đảm nhận", "đảm nhiệm", "chủ trì", "phối hợp",
    "yêu cầu", "chỉ đạo", "đề nghị", "đề xuất", "kiến nghị", "nhờ", "nhận", "sẽ", "làm", "xử lý", "triển khai",
    "hoàn thành", "hoàn chỉnh", "trình", "báo cáo lại", "gửi", "chuẩn bị", "rà soát", "cập nhật",
    "bổ sung", "làm rõ", "đánh giá lại", "xây dựng lại", "nhóm việc",
    "trước ngày", "thời hạn", "hạn chót", "deadline", "trong tuần", "tuần sau", "tháng sau",
)

# Cụm cho thấy CÓ THỂ có kết luận/thống nhất trong chủ đề.
DECISION_CUES: tuple[str, ...] = (
    "chốt", "thống nhất", "kết luận", "quyết định", "nhất trí", "đồng ý", "phê duyệt",
    "thông qua", "chấp thuận", "đề xuất", "kiến nghị", "chọn", "áp dụng", "giữ nguyên", "dừng", "tạm dừng",
    "không làm", "bỏ", "giao", "triển khai", "theo phương án", "như vậy",
    "tinh thần chung", "ghi nhận", "thẩm quyền",
)


def _normalize(text: str) -> str:
    """Chuẩn hoá để so khớp cue: NFC, hạ chữ thường, gộp khoảng trắng.

    Đầu vào: text - chuỗi bất kỳ.
    Đầu ra: str đã chuẩn hoá.
    """

    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).casefold()).strip()


def find_cues(text: str, cues: Sequence[str]) -> tuple[str, ...]:
    """Liệt kê các cụm trong ``cues`` xuất hiện trọn âm tiết trong ``text``.

    Đầu vào: text - chuỗi đã chuẩn hoá (``_normalize``); cues - các cụm cần tìm.
    Đầu ra: tuple cụm đã khớp, theo thứ tự trong ``cues``.
    """

    return tuple(cue for cue in cues if re.search(rf"(?<!\w){re.escape(cue)}(?!\w)", text))


def build_speaker_registry(
    turns: Sequence[SpeakerTurn],
    roster: AttendeeRoster | None = None,
    *,
    chair: str | None = None,
    agenda: TaskAgenda | None = None,
) -> SpeakerRegistry:
    """Dựng danh bạ người nói từ toàn bộ lượt nói của cuộc họp, kèm danh sách tham dự.

    Tên người chủ trì được quy về đúng nhãn người nói nếu khớp duy nhất một người
    ("Phạm Hồng Sơn" -> "Phạm Hồng Sơn (HNI)"); không khớp thì giữ nguyên tên phiên họp
    cung cấp (người chủ trì có thể không phát biểu).

    Đầu vào: turns - mọi lượt nói, theo thứ tự; roster - danh sách tham dự (None nếu không có);
        chair - người chủ trì hoặc None; agenda - danh sách việc cần báo cáo (None nếu không có).
    Đầu ra: SpeakerRegistry.
    """

    turns = tuple(turns)
    chair = (chair or "").strip() or None
    if chair:
        chair = match_claimed_name_to_real_speaker(chair, turns) or chair
    return SpeakerRegistry(
        names=list_distinct_speaker_names(turns),
        roster=roster or AttendeeRoster(),
        chair=chair,
        agenda=agenda or TaskAgenda(),
    )


def plan_topic(
    segment_id: str,
    turns: Sequence[SpeakerTurn],
    *,
    skip_without_cues: bool = True,
    run_progress: bool = False,
) -> TopicPlan:
    """Lập kế hoạch agent cho MỘT chủ đề theo cue trong nguyên văn lượt nói.

    Đầu vào:
        segment_id: mã chủ đề.
        turns: lượt nói của chủ đề.
        skip_without_cues: False thì luôn chạy đủ ba agent (ablation/tắt tính năng).
        run_progress: chạy agent tiến độ (khi phiên họp có danh sách việc).
    Đầu ra: TopicPlan.
    """

    text = _normalize(" ".join(turn.text_exact for turn in turns))
    action_cues = find_cues(text, ACTION_CUES)
    decision_cues = find_cues(text, DECISION_CUES)
    return TopicPlan(
        segment_id=segment_id,
        run_action=bool(action_cues) or not skip_without_cues,
        run_decision=bool(decision_cues) or not skip_without_cues,
        action_cues=action_cues,
        decision_cues=decision_cues,
        run_progress=run_progress,
    )


def plan_meeting(
    segments: Sequence[TopicSegment],
    turns_by_id: dict[str, SpeakerTurn],
    *,
    skip_without_cues: bool = True,
    roster: AttendeeRoster | None = None,
    chair: str | None = None,
    agenda: TaskAgenda | None = None,
) -> tuple[SpeakerRegistry, dict[str, TopicPlan]]:
    """Lập danh bạ người nói và kế hoạch agent cho mọi chủ đề.

    Đầu vào:
        segments: các chủ đề theo thứ tự.
        turns_by_id: turn_id -> SpeakerTurn của cả cuộc họp.
        skip_without_cues: xem ``plan_topic``.
        roster: danh sách tham dự (None nếu không có).
        chair: người chủ trì phiên họp cung cấp, hoặc None (xem ``build_speaker_registry``).
        agenda: danh sách việc cần báo cáo, hoặc None; có việc thì mọi chủ đề chạy agent tiến độ.
    Đầu ra: (SpeakerRegistry, segment_id -> TopicPlan).
    """

    registry = build_speaker_registry(tuple(turns_by_id.values()), roster, chair=chair, agenda=agenda)
    run_progress = bool(registry.agenda.tasks)
    plans = {
        segment.segment_id: plan_topic(
            segment.segment_id,
            get_turns_of_segment(segment, turns_by_id),
            skip_without_cues=skip_without_cues,
            run_progress=run_progress,
        )
        for segment in segments
    }
    return registry, plans


def format_registry_context(registry: SpeakerRegistry) -> str:
    """Biến danh bạ thành khối ngữ cảnh cho prompt Action agent (ô ``previous_context`` của v1).

    Có danh sách tham dự thì thêm người (kèm chức vị, đơn vị) và đơn vị, để agent ghi
    được actor là đơn vị ("Sở Tài chính") hoặc họ tên đầy đủ thay vì chỉ tên gọi. Có danh
    sách việc cần báo cáo thì thêm các việc (``format_agenda``), để Action agent ghi được
    ``task_id`` cho việc giao tiếp nối một việc cũ.

    Đầu vào: registry - danh bạ người nói + danh sách tham dự.
    Đầu ra: str cho prompt.
    """

    roster = registry.roster
    if not registry.names and not roster.people and not roster.organizations and not registry.agenda.tasks:
        return "(Không có danh sách người nói.)"
    lines = []
    if registry.names:
        lines.append("Người nói trong cả cuộc họp: " + ", ".join(registry.names) + ".")
    if roster.people:
        people = []
        for person in roster.people:
            org = roster.find_organization(person.org_id)
            details = ", ".join(part for part in (person.position, org.name if org else "") if part)
            people.append(f"{person.full_name} ({details})" if details else person.full_name)
        lines.append("Người tham dự: " + "; ".join(people) + ".")
    if roster.organizations:
        organizations = [
            f"{org.name} (còn gọi: {', '.join(org.aliases)})" if org.aliases else org.name
            for org in roster.organizations
        ]
        lines.append("Đơn vị tham dự (actor có thể là đơn vị): " + ", ".join(organizations) + ".")
    if registry.agenda.tasks:
        lines.append(format_agenda(registry.agenda))
    return "\n".join(lines)


def format_agenda(agenda: TaskAgenda) -> str:
    """Biến danh sách việc cần báo cáo thành khối văn bản cho prompt.

    Mỗi việc một dòng: mã, tên, bên chủ trì/phối hợp, hạn, trạng thái trước phiên họp.

    Đầu vào: agenda - danh sách việc (không rỗng).
    Đầu ra: str nhiều dòng.
    """

    lines = ["Việc cần báo cáo tiến độ trong phiên họp (mã: tên việc):"]
    for task in agenda.tasks:
        details = [f"chủ trì: {task.owner.name}"]
        if task.support:
            details.append("phối hợp: " + ", ".join(party.name for party in task.support))
        if task.due:
            details.append(f"hạn: {task.due}")
        if task.last_status:
            details.append(f"trạng thái trước họp: {task.last_status}")
        lines.append(f"- {task.task_id}: {task.title} ({'; '.join(details)})")
    return "\n".join(lines)


__all__ = [
    "ACTION_CUES",
    "DECISION_CUES",
    "build_speaker_registry",
    "find_cues",
    "format_agenda",
    "format_registry_context",
    "plan_meeting",
    "plan_topic",
]
