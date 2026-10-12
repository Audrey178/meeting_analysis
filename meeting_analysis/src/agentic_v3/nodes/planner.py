"""Planner: lập những gì các chủ đề cần trước khi trích xuất.

1. ``SpeakerRegistry`` (luật, 0 token, MỘT lần trước khi các chủ đề tách song song) -- danh
   bạ người nói của cả cuộc họp. Thay ngữ cảnh ``known_names``/``known_assignments`` chạy dồn
   của v1 (lý do duy nhất khiến v1 phải xử lý chủ đề tuần tự). Khác v1: danh bạ thấy cả người
   chỉ xuất hiện ở chủ đề SAU; đổi lại không còn tên do agent tự gán (có thể sai) lan sang
   chủ đề sau.
2. Có chạy Action/Decision agent ở một chủ đề không (``may_assign_or_decide``, trong subgraph
   của từng chủ đề): hỏi Decisions (``core/turn_act.py``) xem có lượt nào CÓ THỂ là giao/nhận/
   chốt việc, theo nghĩa chứ không theo từ khoá. Bỏ agent chỉ khi mọi lượt đều rõ là không
   (p_commit < ``COMMIT_REJECT_MAX``: trên eval/synthetic chỉ 4% lượt vùng này là lượt chốt,
   và ngưỡng này không làm mất mục gold nào khi mô phỏng). Lượt chốt thường ở cuối chủ đề nên
   xét từ cuối lên và dừng ở lượt đầu tiên vượt ngưỡng. Lọc riêng theo nhãn thì mất kết luận
   (p(ket_luan) >= 0.2 bỏ sót 5/166 kết luận, lượt chốt của cả 5 đều được xếp ``giao_viec``),
   nên cả hai agent dùng chung p_commit.
   Content agent không bao giờ bị bỏ; agent tiến độ chạy ở MỌI chủ đề khi phiên họp có danh
   sách việc cần báo cáo (agent tự chọn việc nào chủ đề có nhắc).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ..core._shared import list_distinct_speaker_names, match_claimed_name_to_real_speaker
from ..core.turn_act import COMMIT_REJECT_MAX, TurnActJudge, turn_windows
from ...utils.contracts import SpeakerTurn
from ..actors.agenda import TaskAgenda
from ..actors.attendees import AttendeeRoster
from ..schemas import AnalysisPart, SpeakerRegistry

logger = logging.getLogger(__name__)

# Phần kết quả do Action/Decision agent sinh: Planner có thể bỏ agent của chúng ở một chủ đề.
COMMIT_PARTS: tuple[AnalysisPart, ...] = ("assignments", "decisions")


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


def may_assign_or_decide(turns: Sequence[SpeakerTurn], judge: TurnActJudge) -> bool:
    """Chủ đề có lượt nào CÓ THỂ là giao/nhận/chốt việc không (cần chạy Action/Decision agent).

    Xét từ lượt cuối lên, mỗi lượt kèm các lượt đứng trước trong chủ đề làm ngữ cảnh: với lượt
    ngắn, input giống hệt lúc evidence-check xét lượt chốt nên judge nhớ kết quả dùng lại được.
    Lượt dài xét từng đoạn (``turn_windows``), đoạn sau trước. Dừng ở đoạn đầu tiên có p_commit >= ``COMMIT_REJECT_MAX``.
    Judge lỗi thì trả True: chạy thừa chỉ tốn lời gọi, bỏ nhầm thì mất kết quả.

    Đầu vào: turns - lượt nói của chủ đề, theo thứ tự; judge - bộ phân loại lượt nói.
    Đầu ra: bool.
    """

    turns = tuple(turns)
    for index in reversed(range(len(turns))):
        for part, context in reversed(turn_windows(turns[index], turns[:index])):
            try:
                p_commit = judge.judge(part, context).p_commit
            except Exception as exc:  # noqa: BLE001 -- lỗi mạng/API bất kỳ: chạy agent cho chắc
                logger.warning("turn_act lỗi ở lượt %s, vẫn chạy Action/Decision agent: %s", part.turn_id, exc)
                return True
            if p_commit >= COMMIT_REJECT_MAX:
                return True
    return False


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
    "COMMIT_PARTS",
    "build_speaker_registry",
    "format_agenda",
    "format_registry_context",
    "may_assign_or_decide",
]
