"""Phần còn lại của node Debate + Judge (v1) mà Verifier v3 (``nodes/verifier.py``) dùng lại.

Gồm rubric giữ/bỏ theo loại (``_RUBRICS``, nạp vào prompt Verifier), nhãn loại
(``_KIND_LABELS``), cách hiển thị một candidate (``_candidate_text``) và luật hậu kiểm verdict
(``_resolve_verdict``). Verdict có ba mức: ``keep``, ``revise`` (việc giao có thật nhưng
sai/thiếu người phụ trách -- sửa ``actor`` theo bản ghi) và ``drop``; giữ mà không chỉ ra được
lượt giao/chốt (``deciding_turn_id``) thuộc đoạn thì bị hạ thành ``drop`` bằng luật. Rubric liệt
kê đúng các lỗi judge eval đã bắt được.
"""

from __future__ import annotations

from dataclasses import replace

from .._shared import is_non_identifying_actor, read_confirm_turn_id, read_stripped_text
from ..schemas import ActionItemCandidate, DebateTask, DecisionCandidate, JudgeVerdict

_KIND_LABELS = {"action": "việc giao (action item)", "decision": "quyết định (decision)"}

# Tiêu chí giữ/bỏ theo loại -- dùng chung cho cả hai bên tranh luận và judge
# để ba vai trò tranh luận trên CÙNG một thước đo. Danh sách "BỎ" lấy từ các
# lỗi judge eval đã gắn cờ trên 30 cuộc họp (eval/results/dialtreeseg_v1).
_RUBRICS = {
    "action": """
GIỮ (keep): có lượt nói trong đoạn mà người chủ trì/cấp có thẩm quyền GIAO việc
này cho đúng người/đơn vị trong candidate, hoặc người/đơn vị đó TỰ NHẬN việc và
không ai phản đối. Người/đơn vị tự nêu việc cụ thể mình SẼ làm (kế hoạch sắp tới,
thường kèm mốc thời gian) là TỰ NHẬN việc -- không phải "báo cáo".
SỬA (revise): việc giao có thật nhưng người phụ trách trong candidate sai, thiếu
hoặc chung chung ("một thành viên", "nhóm") trong khi bản ghi cho thấy rõ ai
nhận việc -- trả revised_actor là tên/đơn vị ĐÚNG NGUYÊN VĂN bản ghi.
BỎ (drop): đề xuất/kiến nghị/yêu cầu của một thành viên chưa được ai chấp nhận;
báo cáo việc ĐÃ làm xong/ĐANG làm; câu thăm dò chưa thành cam kết ("để xem có
làm được không"); lời mời/điều phối buổi họp ("mời anh X trình
bày"); quy định/hướng dẫn chung không gắn người thực hiện; việc bị gạt đi hoặc
hoãn; nội dung không có trong bản ghi.
""".strip(),
    "decision": """
GIỮ (keep): có lượt nói trong đoạn mà người chủ trì KẾT LUẬN hoặc các bên THỐNG
NHẤT đúng nội dung này, và sau đó không bị thay bằng phương án khác.
BỎ (drop): báo cáo tình hình/số liệu/việc đã làm; ước tính, dự báo, nhận định
cá nhân; đề xuất chưa được xác nhận hoặc bị gạt đi/hoãn lại; câu mở đầu, thủ
tục, khẩu hiệu; kế hoạch/văn bản đã có từ trước chỉ được nhắc lại; phương án
đã bị thay thế bởi phương án khác ở sau; nội dung không có trong bản ghi.
(Quyết định không có "revise" -- chỉ keep hoặc drop.)
""".strip(),
}


def _candidate_text(candidate: ActionItemCandidate | DecisionCandidate, kind: str) -> str:
    """Lấy nội dung hiển thị của candidate để đưa vào prompt debate/judge và bản ghi audit.

    Đầu vào: candidate - ActionItemCandidate hoặc DecisionCandidate; kind - "action"/"decision".
    Đầu ra: str - "actor: text (hạn: ...)" cho action, hoặc "text" cho decision.
    """

    if kind == "action":
        actor = candidate.actor or "(chưa rõ người phụ trách)"
        deadline = f" (hạn: {candidate.deadline_raw})" if candidate.deadline_raw else ""
        return f"{actor}: {candidate.text}{deadline}"
    return candidate.text


def _resolve_verdict(
    task: DebateTask, judge_result: dict
) -> tuple[JudgeVerdict, str | None, ActionItemCandidate | DecisionCandidate]:
    """Áp luật lên kết quả judge: chuẩn hoá verdict, kiểm lượt quyết định, sửa actor.

    - verdict lạ -> "drop"; "revise" với decision -> "keep".
    - keep/revise mà ``deciding_turn_id`` không thuộc đoạn -> "drop" (xem docstring module).
    - revise: chỉ nhận ``revised_actor`` định danh được; không thì giữ actor cũ
      (verdict thành "keep"). Actor cuối không định danh được -> None, để
      frontend xếp vào "Chưa rõ người phụ trách" thay vì một tên giả.

    Đầu vào: task - DebateTask; judge_result - JSON judge trả về.
    Đầu ra: (verdict cuối, deciding_turn_id hợp lệ hoặc None, candidate cuối).
    """

    kind = task["kind"]
    candidate = task["candidate"]
    verdict = judge_result.get("verdict")
    if verdict not in ("keep", "revise", "drop"):
        verdict = "drop"
    if verdict == "revise" and kind == "decision":
        verdict = "keep"
    deciding_turn_id = read_confirm_turn_id(task["turns"], judge_result.get("deciding_turn_id"))
    if verdict != "drop" and deciding_turn_id is None:
        verdict = "drop"
    if kind == "action" and verdict != "drop":
        actor = candidate.actor
        revised = read_stripped_text(judge_result.get("revised_actor"))
        if verdict == "revise" and revised and not is_non_identifying_actor(revised):
            actor = revised
        else:
            verdict = "keep"
        if actor is not None and is_non_identifying_actor(actor):
            actor = None
        candidate = replace(candidate, actor=actor)
    return verdict, deciding_turn_id, replace(candidate, verification="debate")
