"""Kiểu dữ liệu riêng của v3. Candidate, luận điểm và lỗi dùng lại nguyên kiểu của
``.core.schemas`` (chép từ ``src.agentic.schemas`` của v1, đã xóa) để tầng trình bày (``be/services``) serialize chung.

``verification`` của candidate trong v3 có thêm hai giá trị ngoài ``Verification``
của v1: ``"consensus"`` (Verifier và agent trích xuất đồng thuận) và ``"verifier"``
(hết số vòng mà chưa đồng thuận, lấy kết luận cuối của Verifier). Trường này là
``str`` ở API nên không cần đổi schema phản hồi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from .core.deadline import DeadlineKind
from .core.schemas import (
    ActionItemCandidate,
    CandidateKind,
    DecisionCandidate,
    SpeakerSection,
    TopicFailure,
)
from ..utils.contracts import SpeakerTurn, TopicLabel
from .actors.agenda import TaskAgenda
from .actors.attendees import AttendeeRoster

ActorType = Literal["person", "organization", "unknown"]
AssigneeRole = Literal["lead", "support", "joint"]
# Trạng thái agent tiến độ khai cho một việc trong một chủ đề (xem ``nodes/progress.py``).
UpdateStatus = Literal["done", "in_progress", "blocked", "returned", "deferred", "mentioned"]
UPDATE_STATUSES: tuple[str, ...] = ("done", "in_progress", "blocked", "returned", "deferred", "mentioned")
# Quan hệ của một việc giao với danh sách việc cần báo cáo (gán ở ``finalize``).
AssignmentRelation = Literal["new", "follow_up", "reassign", "reschedule"]
# Phần kết quả tính được riêng trên cùng nền cắt chủ đề + nhãn (``MeetingAnalyzerV3.analyze``):
# Diễn biến (Content agent), Giao việc (Action), Kết luận (Decision), Tiến độ (agent tiến độ).
AnalysisPart = Literal["development", "assignments", "decisions", "progress"]
ANALYSIS_PARTS: tuple[AnalysisPart, ...] = ("development", "assignments", "decisions", "progress")
# Agent trích xuất sinh ra từng phần: tên node trong ``graph/topic.py``, cũng là ``agent`` của
# ``TopicFailure``/``SkippedAgent`` thuộc phần đó.
AGENT_OF_PART: dict[AnalysisPart, str] = {
    "development": "content_agent",
    "assignments": "action_agent",
    "decisions": "decision_agent",
    "progress": "progress_agent",
}


@dataclass(frozen=True, slots=True)
class SpeakerRegistry:
    """Danh bạ người nói của CẢ cuộc họp, dựng một lần trước khi các chủ đề chạy song song.

    Thay cho ``known_names`` chạy dồn của v1: chủ đề nào cũng đọc cùng một danh bạ,
    nên không chủ đề nào phải chờ chủ đề trước.

    Các trường:
        names: tên người nói không trùng, theo thứ tự xuất hiện đầu tiên.
        roster: danh sách người/đơn vị tham dự (file ``*.attendees.json``); rỗng nếu
            cuộc họp không có file đi kèm.
        chair: người chủ trì do phiên họp cung cấp (đã quy về tên người nói nếu khớp
            duy nhất một người), None nếu không có. Agent trích xuất và Verifier đều
            thấy dòng này ở đầu prompt.
        agenda: danh sách việc cần báo cáo tiến độ (file ``*.tasks.json``); rỗng nếu
            không có, khi đó không chạy agent tiến độ.
    """

    names: tuple[str, ...]
    roster: AttendeeRoster = AttendeeRoster()
    chair: str | None = None
    agenda: TaskAgenda = TaskAgenda()


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
        relation: quan hệ với danh sách việc cần báo cáo ("new", "follow_up",
            "reassign", "reschedule"); None khi phiên họp không có danh sách việc.
    """

    actor_type: ActorType = "unknown"
    actor_candidates: tuple[ActorCandidate, ...] = ()
    actor_flag: str | None = None
    actor_reason: str = ""
    assignees: tuple[ActorAssignee, ...] = ()
    relation: AssignmentRelation | None = None


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


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    """Một cập nhật tiến độ của MỘT việc trong MỘT chủ đề (``nodes/progress.py``).

    Các trường:
        segment_id: chủ đề chứa cập nhật.
        task_id: mã việc trong danh sách việc cần báo cáo.
        status: trạng thái sau khi kiểm (xem ``UpdateStatus``).
        status_turn_id: lượt nói nêu trạng thái; None nếu agent không chỉ ra được.
        evidence_ids, quotes: bằng chứng (turn_id + nguyên văn).
        summary: một câu tóm tắt nội dung báo cáo/chỉ đạo về việc.
        blockers: vướng mắc được nêu.
        directive: chỉ đạo của người chủ trì về việc, rỗng nếu không có.
        deadline_raw, deadline_date, deadline_kind: hạn MỚI được nêu (cùng cách chuẩn hoá
            với việc giao, xem ``core/deadline.py``).
        deadline_removed: True khi cuộc họp bỏ hạn ("không kết luận về thời gian").
        proposed_status: trạng thái agent khai, khi khác ``status`` (bị sửa/hạ).
        status_flag: "revised" (Decisions sửa trạng thái), "uncertain" (không xác
            nhận được, đã hạ về "mentioned") hoặc "kept" (Decisions xác nhận lượt là báo cáo
            về việc nhưng không xác nhận đúng trạng thái agent khai; vẫn giữ trạng thái đó);
            None nếu Decisions xác nhận hoặc chưa kiểm.
        status_probabilities: phân bố xác suất Decisions cho lượt nêu trạng thái (lượt dài:
            đoạn quyết định); với "mentioned" là đoạn nói về việc rõ nhất.
        p_directive: xác suất lượt nêu trạng thái là chỉ đạo/kết luận (``turn_judge``),
            None nếu không đo; ``finalize`` dùng để chỉ đạo thắng báo cáo.
        verification: "decisions" (đã qua Decisions), "unchecked" (Decisions tắt/lỗi, giữ
            nguyên điều agent khai) hoặc "rule" (mặc định khi mới trích, chưa qua bước kiểm).
        reason: lý do sửa/hạ trạng thái (để audit).
    """

    segment_id: str
    task_id: str
    status: UpdateStatus
    status_turn_id: str | None
    evidence_ids: tuple[str, ...]
    quotes: tuple[str, ...]
    summary: str = ""
    blockers: tuple[str, ...] = ()
    directive: str = ""
    deadline_raw: str | None = None
    deadline_date: str | None = None
    deadline_kind: DeadlineKind = "unknown"
    deadline_removed: bool = False
    proposed_status: str | None = None
    status_flag: str | None = None
    status_probabilities: tuple[tuple[str, float], ...] = ()
    p_directive: float | None = None
    verification: str = "rule"
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TaskProgress:
    """Tiến độ của MỘT việc trong danh sách, gộp từ mọi chủ đề (``finalize``).

    Các trường:
        task_id, title, owner: thông tin việc (owner là tên bên chủ trì).
        previous_status: trạng thái gần nhất trước phiên họp (từ file danh sách).
        status: trạng thái sau phiên họp (``UpdateStatus``) hoặc "not_reported".
        previous_due: hạn trước phiên họp.
        deadline_raw, deadline_date, deadline_kind, deadline_removed: hạn mới (theo cập
            nhật thắng), None/False nếu không đổi.
        status_conflict: có báo cáo "done" đã xác nhận cùng một cập nhật đã xác nhận nêu
            trạng thái khác (vd. báo cáo xong nhưng bị yêu cầu làm lại).
        uncertain: cập nhật thắng chưa được xác nhận (``status_flag == "uncertain"``).
        overdue: hạn cũ đã qua so với ngày họp mà việc chưa xong.
        deciding_update: cập nhật quyết định trạng thái, None nếu không được báo cáo.
        updates: mọi cập nhật của việc, theo thứ tự lượt nói (để audit).
    """

    task_id: str
    title: str
    owner: str
    previous_status: str | None
    status: str
    previous_due: str | None = None
    deadline_raw: str | None = None
    deadline_date: str | None = None
    deadline_kind: DeadlineKind = "unknown"
    deadline_removed: bool = False
    status_conflict: bool = False
    uncertain: bool = False
    overdue: bool = False
    deciding_update: ProgressUpdate | None = None
    updates: tuple[ProgressUpdate, ...] = ()


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
        task_progress: tiến độ từng việc trong danh sách việc cần báo cáo, theo thứ tự
            của file; rỗng nếu phiên họp không có danh sách việc.
    """

    labels: tuple[TopicLabel, ...]
    meeting_development: tuple[SpeakerSection, ...]
    assignments: tuple[ActionItemCandidate, ...]
    decisions: tuple[DecisionCandidate, ...]
    verification_records: tuple[VerificationRecord, ...]
    failures: tuple[TopicFailure, ...]
    skipped_agents: tuple[SkippedAgent, ...]
    task_progress: tuple[TaskProgress, ...] = ()


__all__ = [
    "AGENT_OF_PART",
    "ANALYSIS_PARTS",
    "ActionItemV3",
    "ActorAssignee",
    "ActorCandidate",
    "ActorType",
    "AnalysisPart",
    "AssigneeRole",
    "AssignmentRelation",
    "ConsensusRound",
    "MeetingReport",
    "ProgressUpdate",
    "SkippedAgent",
    "SpeakerRegistry",
    "TaskProgress",
    "UPDATE_STATUSES",
    "UpdateStatus",
    "VerificationRecord",
    "VerifierStep",
    "VerifyTask",
]
