"""Node Evidence-Check: lọc candidate action/decision của MỘT chủ đề thành CLEAR/UNCERTAIN.

Luật, 0 token -- xem ``_shared.check_action_evidence``/``check_decision_evidence``
cho heuristic cụ thể. Chạy sau khi ``content_agent``, ``action_agent``,
``decision_agent`` của chủ đề hiện tại đều xong (fan-in 3 nhánh, cùng lớp
bảo vệ bằng dấu hoàn thành như ``graph.advance_topic``, xem ``..graph``).

Candidate CLEAR được đưa thẳng vào danh sách kết quả đã kiểm chứng
(``verified_assignments``/``verified_decisions`` -- đây CHÍNH LÀ hai trong ba
ô output cuối của sơ đồ gốc, không có node nào xử lý tiếp); candidate
UNCERTAIN được gói thành ``DebateTask`` để cạnh có điều kiện
``graph._dispatch_debate_or_advance`` gửi cho ``debate_and_judge_agent``.

Vì sao lọc bằng luật, không LLM: các tín hiệu nghi ngờ đều MÁY tính được
trực tiếp -- actor None/không định danh/không có trong đoạn, ``status`` mà
chính agent trích xuất tự khai, và NGUYÊN VĂN lượt nói chốt
(``confirm_turn_id``). Luật cố ý KHÔNG dựa chủ yếu vào ``text``: agent đã viết
lại câu thành dạng khẳng định ("Thống nhất...", "giao X...") nên dấu hiệu đề
xuất/do dự thường đã mất ở đó (bản trước chỉ đọc ``text``/``actor`` và để lọt
mọi đề xuất/báo cáo bị viết lại). LLM chỉ tốn cho phần THẬT sự cần suy luận
trên bằng chứng đối lập -- đó là việc của ``debate_and_judge_agent``.
"""

from __future__ import annotations

from .._shared import check_action_evidence, check_decision_evidence, get_turns_of_segment
from ..schemas import ActionItemCandidate, CandidateKind, DebateTask, DecisionCandidate
from ..state import MeetingState


def _make_debate_task(
    segment_id: str,
    kind: CandidateKind,
    index: int,
    candidate: ActionItemCandidate | DecisionCandidate,
    reasons: tuple[str, ...],
    turns: tuple,
) -> DebateTask:
    """Gói một candidate uncertain thành ``DebateTask`` để ``Send`` cho debate.

    Đầu vào:
        segment_id: mã đoạn chủ đề chứa candidate.
        kind: "action" hoặc "decision".
        index: chỉ số của candidate trong danh sách uncertain CÙNG LOẠI của
            đoạn này -- chỉ dùng để dựng ``item_key`` duy nhất, không mang ý
            nghĩa thứ tự nào khác.
        candidate: candidate gốc.
        reasons: lý do evidence-check gắn cờ.
        turns: các lượt nói của đoạn, để Agent A/B/Judge tra bằng chứng.

    Đầu ra: DebateTask.
    """

    return {
        "item_key": f"{segment_id}:{kind}:{index}",
        "segment_id": segment_id,
        "kind": kind,
        "candidate": candidate,
        "reasons": reasons,
        "turns": turns,
    }


def check_topic_evidence(state: MeetingState) -> dict:
    """Chia candidate action/decision của chủ đề HIỆN TẠI thành CLEAR/UNCERTAIN.

    Đầu vào: state - trạng thái graph sau khi content/action/decision agent
        của chủ đề hiện tại (``state["next_segment_index"]``) đã chạy xong.

    Đầu ra:
        - ``{}`` nếu chưa đủ cả 3 nhánh của chủ đề này xong (lớp bảo vệ, cùng
          kiểu với ``graph.advance_topic``), hoặc đã hết chủ đề.
        - Ngược lại: dict cập nhật ``verified_assignments``/
          ``verified_decisions`` (phần CLEAR, cộng dồn qua ``operator.add``)
          và ``pending_debate_tasks`` (phần UNCERTAIN của ĐÚNG chủ đề này --
          GHI ĐÈ hoàn toàn giá trị cũ, xem ``state.py`` vì sao trường này
          không dùng reducer cộng dồn).
    """

    index = state["next_segment_index"]
    if index >= len(state["segments"]):
        return {}
    segment_id = state["segments"][index].segment_id
    if (
        segment_id not in state["completed_content_topics"]
        or segment_id not in state["completed_action_topics"]
        or segment_id not in state["completed_decision_topics"]
    ):
        return {}

    turns = get_turns_of_segment(state["segments"][index], state["turns_by_id"])
    raw_actions = [a for a in state["action_item_candidates_raw"] if a.segment_id == segment_id]
    raw_decisions = [d for d in state["decision_candidates_raw"] if d.segment_id == segment_id]

    clear_actions: list[ActionItemCandidate] = []
    clear_decisions: list[DecisionCandidate] = []
    debate_tasks: list[DebateTask] = []

    for i, item in enumerate(raw_actions):
        flag = check_action_evidence(item, turns, state["known_names"])
        if flag.verdict == "clear":
            clear_actions.append(item)
        else:
            debate_tasks.append(_make_debate_task(segment_id, "action", i, item, flag.reasons, turns))

    for i, item in enumerate(raw_decisions):
        flag = check_decision_evidence(item, turns)
        if flag.verdict == "clear":
            clear_decisions.append(item)
        else:
            debate_tasks.append(_make_debate_task(segment_id, "decision", i, item, flag.reasons, turns))

    return {
        "verified_assignments": clear_actions,
        "verified_decisions": clear_decisions,
        "pending_debate_tasks": tuple(debate_tasks),
    }


__all__ = ["check_topic_evidence"]
