"""Kiểu dữ liệu riêng của v3. Candidate, luận điểm và lỗi dùng lại nguyên kiểu của
``src.agentic.schemas`` để tầng trình bày (``be/services``) serialize như v1.

``verification`` của candidate trong v3 có thêm hai giá trị ngoài ``Verification``
của v1: ``"consensus"`` (Verifier và agent trích xuất đồng thuận) và ``"verifier"``
(hết số vòng mà chưa đồng thuận, lấy kết luận cuối của Verifier). Trường này là
``str`` ở API nên không cần đổi schema phản hồi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from ..agentic.schemas import (
    ActionItemCandidate,
    CandidateKind,
    DecisionCandidate,
    SpeakerSection,
    TopicFailure,
)
from ..utils.contracts import SpeakerTurn, TopicLabel
from .actors.attendees import AttendeeRoster

VerifierVerdict = Literal["keep", "revise", "drop", "unresolved"]
ProposerStance = Literal["accept", "amend", "defend"]
ActorType = Literal["person", "organization", "unknown"]
AssigneeRole = Literal["lead", "support", "joint"]


@dataclass(frozen=True, slots=True)
class SpeakerRegistry:
    """Danh bạ người nói của CẢ cuộc họp, dựng một lần trước khi các chủ đề chạy song song.

    Thay cho ``known_names`` chạy dồn của v1: chủ đề nào cũng đọc cùng một danh bạ,
    nên không chủ đề nào phải chờ chủ đề trước.

    Các trường:
        names: tên người nói không trùng, theo thứ tự xuất hiện đầu tiên.
        roster: danh sách người/đơn vị tham dự (file ``*.attendees.json``); rỗng nếu
            cuộc họp không có file đi kèm.
    """

    names: tuple[str, ...]
    roster: AttendeeRoster = AttendeeRoster()


@dataclass(frozen=True, slots=True)
class ActorCandidate:
    """Một ứng viên cho actor của việc giao, do ``lookup_speaker``/luật chấm điểm.

    Các trường:
        name: tên chuẩn (họ tên trong danh sách, tên người nói, hoặc tên đơn vị).
        actor_type: "person" hoặc "organization".
        score: điểm trong [0, 1]; càng cao càng khớp.
        reason: các tín hiệu đã cộng điểm (để Verifier và người đọc kiểm tra).
        ref_id: mã trong file danh sách (P1, O3...), None nếu chỉ là người nói trong bản ghi.
    """

    name: str
    actor_type: ActorType
    score: float
    reason: str
    ref_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActorAssignee:
    """MỘT người/đơn vị nhận việc trong một việc giao (việc có thể giao cho nhiều bên).

    Các trường:
        mention: cách gọi nguyên văn trong actor ("anh Sơn", "Sở Xây dựng").
        role: "lead" (chủ trì / người nhận chính), "support" (phối hợp), "joint" (cùng
            thực hiện, không phân chủ trì).
        name: tên chuẩn sau khi định danh; None nếu chưa xác định.
        actor_type: người, đơn vị hay chưa xác định.
        candidates: các ứng viên đã xét, điểm giảm dần.
        flag: "ambiguous" khi không có ứng viên đủ rõ.
        reason: lý do chọn (Verifier hoặc luật chấm điểm).
        ref_id: mã trong file danh sách (P1, O3...) nếu có.
    """

    mention: str
    role: AssigneeRole
    name: str | None
    actor_type: ActorType
    candidates: tuple[ActorCandidate, ...] = ()
    flag: str | None = None
    reason: str = ""
    ref_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActionItemV3(ActionItemCandidate):
    """Việc giao của v3: ``ActionItemCandidate`` của v1 cộng phần định danh actor.

    Là lớp con nên mọi chỗ của v1 nhận ``ActionItemCandidate`` (gộp trùng, serialize)
    vẫn dùng được; v1 không cần sửa.

    Các trường thêm (tóm tắt theo bên nhận việc CHÍNH = assignee đầu tiên, chủ trì trước):
        actor_type: actor chính là người, đơn vị hay chưa xác định.
        actor_candidates: các ứng viên của actor chính, điểm giảm dần (giữ để audit).
        actor_flag: "ambiguous" khi CÓ một bên nhận việc chưa đủ rõ.
        actor_reason: lý do chọn actor chính (của Verifier, hoặc luật chấm điểm).
        assignees: mọi bên nhận việc kèm vai trò (chủ trì/phối hợp/cùng thực hiện).
    """

    actor_type: ActorType = "unknown"
    actor_candidates: tuple[ActorCandidate, ...] = ()
    actor_flag: str | None = None
    actor_reason: str = ""
    assignees: tuple[ActorAssignee, ...] = ()


@dataclass(frozen=True, slots=True)
class TopicPlan:
    """Kế hoạch chạy agent cho MỘT chủ đề, do Planner (luật, 0 token) lập.

    Các trường:
        segment_id: mã chủ đề.
        run_action / run_decision: có chạy Action / Decision agent cho chủ đề này không.
        action_cues / decision_cues: các cụm từ đã khớp (để audit vì sao chạy/bỏ).
    """

    segment_id: str
    run_action: bool
    run_decision: bool
    action_cues: tuple[str, ...] = ()
    decision_cues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkippedAgent:
    """Một agent trích xuất bị Planner bỏ qua ở một chủ đề (để audit/đo recall)."""

    segment_id: str
    agent: str


@dataclass(frozen=True, slots=True)
class VerifierStep:
    """Một bước ReAct của Verifier: hành động, tham số và kết quả tool trả về."""

    thought: str
    action: str
    argument: str
    observation: str


@dataclass(frozen=True, slots=True)
class ConsensusRound:
    """Một vòng trao đổi Verifier -> agent trích xuất cho MỘT candidate.

    Các trường:
        candidate_text: candidate Verifier xét ở vòng này (có thể đã được sửa ở vòng trước).
        steps: chuỗi tra cứu ReAct của Verifier ở vòng này.
        verdict: kết luận của Verifier sau luật hậu kiểm (keep/revise/drop/unresolved).
        feedback: lý do Verifier gửi lại cho agent trích xuất.
        deciding_turn_id: lượt nói giao/chốt Verifier chỉ ra (nếu có).
        stance: phản hồi của agent trích xuất (accept/amend/defend); rỗng khi Verifier
            đã giữ (keep) nên không cần hỏi lại.
        response: lập luận của agent trích xuất.
        confirm_turn_id: lượt giao/chốt agent trích xuất chỉ ra (nếu có).
    """

    candidate_text: str
    steps: tuple[VerifierStep, ...]
    verdict: str
    feedback: str
    deciding_turn_id: str | None = None
    stance: str = ""
    response: str = ""
    confirm_turn_id: str | None = None


@dataclass(frozen=True, slots=True)
class VerificationRecord:
    """Bản ghi kiểm chứng một candidate uncertain (thay ``DebateRecord`` của v1).

    Các trường:
        item_key, segment_id, kind: định danh candidate.
        candidate_text: nội dung candidate lúc vào Verifier.
        reasons: lý do Evidence-Check gắn cờ.
        steps: mọi bước tra cứu của Verifier, nối qua các vòng.
        verdict: kết luận cuối (keep/revise/drop), hoặc "unresolved" khi giữ theo luật an toàn.
        reasoning: giải thích cuối (feedback vòng cuối của Verifier, hoặc ghi chú lỗi).
        final_text: nội dung sau khi sửa, rỗng nếu bỏ.
        deciding_turn_id: lượt nói giao/chốt Verifier chỉ ra.
        decided_by: "consensus" (hai bên đồng thuận), "verifier" (hết vòng, lấy kết luận
            của Verifier) hoặc "fallback" (lỗi LLM / vẫn không kết luận được).
        rounds: các vòng trao đổi Verifier <-> agent trích xuất.
    """

    item_key: str
    segment_id: str
    kind: CandidateKind
    candidate_text: str
    reasons: tuple[str, ...]
    steps: tuple[VerifierStep, ...]
    verdict: str
    reasoning: str
    final_text: str = ""
    deciding_turn_id: str | None = None
    decided_by: str = "consensus"
    rounds: tuple[ConsensusRound, ...] = ()


class VerifyTask(TypedDict):
    """Gói dữ liệu ``Send`` cho Verifier: MỘT candidate uncertain.

    ``meeting_turns``/``registry`` là của CẢ cuộc họp để tool tra được bằng chứng
    nằm ở chủ đề khác (vd. việc được chốt ở chủ đề sau).
    """

    item_key: str
    segment_id: str
    kind: CandidateKind
    candidate: ActionItemCandidate | DecisionCandidate
    reasons: tuple[str, ...]
    turns: tuple[SpeakerTurn, ...]
    meeting_turns: tuple[SpeakerTurn, ...]
    registry: SpeakerRegistry


@dataclass(frozen=True, slots=True)
class MeetingReport:
    """Kết quả cuối của graph v3, đã sắp theo thứ tự chủ đề và gộp mục trùng.

    Các trường:
        labels: nhãn chủ đề theo thứ tự ``segments``.
        meeting_development: luận điểm theo người nói (Diễn biến họp).
        assignments: việc được giao đã kiểm chứng (Giao việc).
        decisions: quyết định đã kiểm chứng (Kết luận họp).
        verification_records: bản ghi kiểm chứng (kèm các vòng trao đổi).
        failures: lời gọi trích xuất vẫn lỗi sau mọi lượt thử.
        skipped_agents: agent bị Planner bỏ qua.
    """

    labels: tuple[TopicLabel, ...]
    meeting_development: tuple[SpeakerSection, ...]
    assignments: tuple[ActionItemCandidate, ...]
    decisions: tuple[DecisionCandidate, ...]
    verification_records: tuple[VerificationRecord, ...]
    failures: tuple[TopicFailure, ...]
    skipped_agents: tuple[SkippedAgent, ...]


__all__ = [
    "ActionItemV3",
    "ActorAssignee",
    "ActorCandidate",
    "ActorType",
    "AssigneeRole",
    "ConsensusRound",
    "MeetingReport",
    "ProposerStance",
    "SkippedAgent",
    "SpeakerRegistry",
    "TopicPlan",
    "VerificationRecord",
    "VerifierStep",
    "VerifierVerdict",
    "VerifyTask",
]
