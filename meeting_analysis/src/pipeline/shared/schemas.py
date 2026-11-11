"""Mọi kiểu dữ liệu của bước 4-6, xếp theo bước tạo ra chúng:

  - Bước 4: danh bạ người nói của cả cuộc họp, gói dữ liệu đưa cho mỗi agent, và các mục trích ra
    còn chưa kiểm chứng (ý thảo luận, việc giao, kết luận, cập nhật tiến độ); thêm ghi nhận lỗi khi
    một chủ đề không trích được.
  - Bước 5: nhãn chắc chắn/nghi ngờ, yêu cầu gửi agent kiểm chứng, nhận xét của agent kiểm chứng,
    trả lời của agent trích xuất, và nhật ký các vòng trao đổi.
  - Xác định bên nhận việc: các ứng viên và bên nhận việc đã xác định.
  - Bước 6: việc giao hoàn chỉnh, tiến độ theo từng việc, và báo cáo cuộc họp.

Mỗi mục trong kết quả đều ghi lại nó được giữ theo cách nào: qua luật kiểm tra, qua đồng thuận giữa
agent kiểm chứng và agent trích xuất, theo quyết định của agent kiểm chứng khi hết số vòng, hoặc giữ
nguyên bản của agent khi việc kiểm chứng không ra kết quả.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from ...utils.contracts import SpeakerTurn, TopicLabel
from ..step4_extract.deadline import DeadlineKind
from .meeting_inputs.agenda import TaskAgenda
from .meeting_inputs.attendees import AttendeeRoster, MeetingChair

# ---------------------------------------------------------------------------
# Phần kết quả
# ---------------------------------------------------------------------------

AnalysisPart = Literal["content", "assignments", "decisions", "progress"]
ANALYSIS_PARTS: tuple[AnalysisPart, ...] = ("content", "assignments", "decisions", "progress")

AGENT_OF_PART: dict[AnalysisPart, str] = {
    "content": "content_agent",
    "assignments": "action_agent",
    "decisions": "decision_agent",
    "progress": "action_agent",
}


# ---------------------------------------------------------------------------
# Bước 4: danh bạ (step4_extract)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpeakerRegistry:
    """Danh bạ người nói của cả cuộc họp, dựng một lần trước khi các chủ đề chạy song song.

    Mọi chủ đề đọc chung một danh bạ, nên không chủ đề nào phải chờ chủ đề trước. Danh bạ cũng mang
    theo các file đi kèm bản ghi để mọi bước sau tra cứu ở một chỗ.

    Attributes:
        names: Tên người nói không trùng, theo thứ tự xuất hiện đầu tiên trong bản ghi.
        roster: Danh sách người và đơn vị tham dự; rỗng nếu phiên họp không gửi kèm.
        speaker_ids: ``speaker_ids[i]`` là mã người nói của ``names[i]``; None nếu người đó không có mã.
        chair: Người chủ trì do phiên họp cung cấp, tên đã tra theo danh sách tham dự; None nếu không có.
        agenda: Danh sách việc cần báo cáo tiến độ; rỗng nếu phiên họp không gửi kèm.
    """

    names: tuple[str, ...]
    roster: AttendeeRoster = AttendeeRoster()
    speaker_ids: tuple[str | None, ...] = ()
    chair: MeetingChair | None = None
    agenda: TaskAgenda = TaskAgenda()


# ---------------------------------------------------------------------------
# Bước 4: agent trích xuất (step4_extract)
# ---------------------------------------------------------------------------


class ExtractorInput(TypedDict):
    """Gói dữ liệu đưa cho các agent trích xuất khi xử lý một đoạn chủ đề.

    Attributes:
        segment_id: Mã đoạn chủ đề.
        title: Tiêu đề chủ đề do bước gán nhãn tạo ra.
        summary: Tóm tắt chủ đề do bước gán nhãn tạo ra.
        turns: Các lượt nói thuộc đoạn, theo thứ tự.
        meeting_context: Bối cảnh cuộc họp dạng văn bản: tên người nói, người và đơn vị tham dự,
            các việc cũ cần báo cáo.
        meeting_date: Ngày họp dạng "YYYY-MM-DD", để Action agent quy hạn chót về ngày; None nếu
            không biết.
    """

    segment_id: str
    title: str
    summary: str
    turns: tuple[SpeakerTurn, ...]
    meeting_context: str
    meeting_date: str | None


@dataclass(frozen=True, slots=True)
class TopicFailure:
    """Ghi nhận một lần agent trích xuất của một chủ đề thất bại.

    Attributes:
        segment_id: Mã đoạn chủ đề bị lỗi.
        agent: Tên agent bị lỗi, ví dụ "action_agent".
        error: Thông báo lỗi.
        kind: Loại lỗi, quyết định có nên thử lại hay không (xem ``retryable``).
    """

    segment_id: str
    agent: str
    error: str
    kind: str = "unknown"

    @property
    def retryable(self) -> bool:
        """Cho biết gọi lại agent có thể ra kết quả khác hay không.

        Không thử lại với lỗi phía yêu cầu (``"client"``) hoặc lỗi nghiêm trọng (``"fatal"``), vì gửi lại
        y hệt sẽ lỗi y hệt; cũng không thử lại khi mô hình trả kết quả không đọc được
        (``"malformed_output"``), vì cùng prompt thường cho lại đúng kết quả đó.
        """

        return self.kind not in ("client", "fatal", "malformed_output")


@dataclass(frozen=True, slots=True)
class DiscussionPoint:
    """Một ý thảo luận trong đoạn chủ đề: điều các bên đang bàn hoặc tranh luận, và ai tham gia.

    Các trường về người nói và trích dẫn luôn do code điền từ bằng chứng, không lấy thẳng từ LLM,
    để tránh mô hình gán nhầm người hoặc chép sai lời.

    Attributes:
        segment_id: Mã đoạn chủ đề.
        text: Tóm tắt ý thảo luận ở ngôi thứ ba, nêu vấn đề và các quan điểm.
        speakers: Người tham gia ý này, theo thứ tự lên tiếng, lấy từ các lượt trong
            ``evidence_turn_ids``.
        evidence_turn_ids: Mã các lượt nói làm bằng chứng.
        quotes: Nguyên văn lượt nói ứng với từng phần tử của ``evidence_turn_ids`` (cùng thứ tự,
            cùng độ dài).
        item_ids: Mã các dòng bản ghi gốc mô hình trích dẫn, theo thứ tự bản ghi; ``evidence_turn_ids``
            là các lượt nói chứa những dòng này.
        speaker_ids: ``speaker_ids[i]`` là mã người nói của ``speakers[i]``; None nếu lượt không có mã.
    """

    segment_id: str
    text: str
    speakers: tuple[str, ...]
    evidence_turn_ids: tuple[str, ...]
    quotes: tuple[str, ...]
    item_ids: tuple[str, ...] = ()
    speaker_ids: tuple[str | None, ...] = ()


# Trạng thái do agent trích xuất TỰ KHAI cho từng candidate. Đây là tín hiệu
# cho Evidence-Check: luật không đọc được ý định từ ``text`` (LLM đã viết lại
# thành câu khẳng định "Thống nhất..."/"giao X..." nên mất dấu hedge), nhưng
# đọc được nhãn này cùng lượt nói chốt (``confirm_turn_id``) nguyên văn.
ActionStatus = Literal["assigned", "self_committed", "proposed", "reported", "unknown"]
DecisionStatus = Literal["agreed", "proposed", "reported", "unknown"]
# Candidate đi vào kết quả bằng đường nào (xem docstring module).
Verification = Literal["rule", "consensus", "verifier", "fallback"]


@dataclass(frozen=True, slots=True)
class DecisionCandidate:
    """Một kết luận hoặc phương án được chốt, cố ý không gắn với người chịu trách nhiệm.

    Lời giao việc cho một bên cụ thể thuộc ``ActionItemCandidate``, không thuộc kiểu này. Ví dụ
    "Thống nhất lùi khởi công sang quý II" là kết luận; "Giao Sở Xây dựng trình phương án" là việc giao.

    Attributes:
        segment_id: Mã đoạn chủ đề.
        text: Nội dung kết luận.
        evidence_turn_ids: Mã các lượt nói làm bằng chứng.
        quotes: Nguyên văn lượt nói ứng với từng phần tử của ``evidence_turn_ids``.
        status: Agent tự khai đã chốt (``"agreed"``) hay mới là đề xuất, báo cáo. Đây là tín hiệu cho
            bước gắn nhãn CLEAR/UNCERTAIN, vì câu ``text`` đã được viết lại dạng khẳng định.
        confirm_turn_id: Lượt chốt; đã kiểm là thuộc đoạn này. None nếu agent không nêu hoặc nêu sai.
        verification: Con đường candidate đi vào kết quả (luật, đồng thuận, Verifier hay dự phòng).
        item_ids: Mã các dòng bản ghi gốc được trích dẫn; ``evidence_turn_ids`` là các lượt chứa chúng.
        request_turn_id: Lượt nêu nội dung, thường là lượt thành viên đề xuất; trùng
            ``confirm_turn_id`` khi người chốt tự nêu. None nếu agent không nêu hoặc nêu sai.
    """

    segment_id: str
    text: str
    evidence_turn_ids: tuple[str, ...]
    quotes: tuple[str, ...]
    status: DecisionStatus = "unknown"
    confirm_turn_id: str | None = None
    verification: Verification = "rule"
    item_ids: tuple[str, ...] = ()
    request_turn_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActionItemCandidate:
    """Một lời giao việc: bên nào được giao làm gì, hạn khi nào.

    Attributes:
        segment_id: Mã đoạn chủ đề.
        actor: Tên các bên nhận việc nối bằng ", "; None nếu chưa rõ.
        text: Nội dung việc.
        evidence_turn_ids: Mã các lượt nói làm bằng chứng.
        quotes: Nguyên văn lượt nói ứng với từng phần tử của ``evidence_turn_ids``.
        deadline_raw: Hạn chót nguyên văn trong lời nói, ví dụ "trước 15/11"; None nếu không nêu.
        deadline_date: ``deadline_raw`` quy về ngày "YYYY-MM-DD" theo ngày họp; None nếu không quy được.
        deadline_kind: Loại hạn: ``"exact"``, ``"before"``, ``"end_of_period"``, ``"relative"`` hoặc
            ``"unknown"``.
        status: Agent tự khai là việc được giao, tự nhận, hay chỉ là đề xuất, báo cáo.
        confirm_turn_id: Lượt giao hoặc nhận việc; đã kiểm là thuộc đoạn này.
        verification: Con đường candidate đi vào kết quả (luật, đồng thuận, Verifier hay dự phòng).
        item_ids: Mã các dòng bản ghi gốc được trích dẫn.
        mentions: Các bên nhận việc agent (hoặc Verifier) khai, kèm vai trò và loại. Rỗng với
            candidate dựng tay chỉ có ``actor``; khi đó ``actor`` được hiểu là một bên chủ trì.
        request_turn_id: Lượt nêu việc: lượt giao, lượt tự nhận, hoặc lượt thành viên đề xuất. None
            nếu agent không nêu hoặc nêu sai.
    """

    segment_id: str
    actor: str | None
    text: str
    evidence_turn_ids: tuple[str, ...]
    quotes: tuple[str, ...]
    deadline_raw: str | None = None
    deadline_date: str | None = None
    deadline_kind: DeadlineKind = "unknown"
    status: ActionStatus = "unknown"
    confirm_turn_id: str | None = None
    verification: Verification = "rule"
    item_ids: tuple[str, ...] = ()
    mentions: tuple[AssigneeMention, ...] = ()
    request_turn_id: str | None = None


# Ba trạng thái đầu ra: đang thực hiện (cả vướng, làm lại, gia hạn), đã hoàn thành, huỷ (cả hoãn, tạm
# dừng). "mentioned" chỉ dùng nội bộ: lời giao lại mà không nêu tình trạng, không quyết định trạng thái.
UpdateStatus = Literal["done", "in_progress", "cancelled", "mentioned"]
UPDATE_STATUSES: tuple[str, ...] = ("done", "in_progress", "cancelled", "mentioned")


@dataclass(frozen=True, slots=True)
class ProgressUpdate:
    """Một cập nhật về một việc cũ trong một chủ đề.

    Cập nhật có thể là báo cáo tình trạng, chỉ đạo, đổi hoặc gia hạn, hay giao việc cho bên khác. Mọi
    lời nói về việc cũ chỉ nằm ở đây, không trở thành việc giao mới.

    Attributes:
        segment_id: Mã đoạn chủ đề.
        task_id: Mã việc trong danh sách việc cần báo cáo.
        status: Trạng thái: ``"done"``, ``"in_progress"`` (kể cả đang vướng, phải làm lại, được gia
            hạn), ``"cancelled"`` (kể cả hoãn, tạm dừng), hoặc ``"mentioned"`` (chỉ dùng nội bộ: có
            nhắc tới việc nhưng không nêu tình trạng, không dùng để quyết định trạng thái).
        status_turn_id: Lượt nói nêu trạng thái; None nếu agent không chỉ ra.
        evidence_turn_ids: Mã các lượt nói làm bằng chứng.
        quotes: Nguyên văn lượt nói ứng với từng phần tử của ``evidence_turn_ids``.
        summary: Tóm tắt nội dung báo cáo.
        blockers: Các vướng mắc được nêu.
        directive: Chỉ đạo về việc này, nếu có.
        deadline_raw: Hạn mới nguyên văn; None nếu không đổi hạn.
        deadline_date: Hạn mới quy về ngày "YYYY-MM-DD"; None nếu không quy được.
        deadline_kind: Loại của hạn mới.
        deadline_extended: True khi việc chưa xong và được thêm thời gian nhưng chưa có hạn mới cụ thể
            (người dùng sẽ sửa hạn sau).
        verification: Con đường cập nhật đi vào kết quả, cùng các giá trị như ở việc giao.
        reason: Lý do kèm theo của bước kiểm chứng.
        item_ids: Mã các dòng bản ghi gốc được trích dẫn.
        mentions: Bên nhận việc mới khi cuộc họp giao việc cho bên khác; rỗng nếu không đổi.
        request_turn_id: Lượt thành viên đề xuất trạng thái, đổi hạn hoặc giao lại mà người chủ trì
            chấp nhận ở ``status_turn_id``; None nếu không có.
    """

    segment_id: str
    task_id: str
    status: UpdateStatus
    status_turn_id: str | None
    evidence_turn_ids: tuple[str, ...]
    quotes: tuple[str, ...]
    summary: str = ""
    blockers: tuple[str, ...] = ()
    directive: str = ""
    deadline_raw: str | None = None
    deadline_date: str | None = None
    deadline_kind: DeadlineKind = "unknown"
    deadline_extended: bool = False
    verification: str = "rule"
    reason: str = ""
    item_ids: tuple[str, ...] = ()
    mentions: tuple[AssigneeMention, ...] = ()
    request_turn_id: str | None = None


# ---------------------------------------------------------------------------
# Bước 5: evidence-check (step5_verify)
# ---------------------------------------------------------------------------

CandidateKind = Literal["action", "decision", "progress"]

# Contract của bước 4-6 (extractor -> evidence check -> verifier -> finalize):
# - ``Claim``: điều agent trích xuất khai (nội dung + trạng thái). CHỈ agent trích xuất viết/sửa Claim.
# - ``Check``: nhãn evidence check gắn cho một Claim, không sửa Claim.
# - ``Review``: kết luận + feedback của Verifier cho một Claim, không sửa Claim.
# - ``Response``: trả lời của agent trích xuất cho một Review, kèm Claim (có thể đã sửa).
# ``finalize`` gộp các Claim đã giữ thành kết quả cuối.
Claim = ActionItemCandidate | DecisionCandidate | ProgressUpdate


@dataclass(frozen=True, slots=True)
class Check:
    """Nhãn CLEAR/UNCERTAIN mà bước kiểm tra bằng luật và Decisions API gắn cho một Claim.

    Nhãn chỉ đánh giá, không sửa Claim. Claim ``"clear"`` vào thẳng kết quả; Claim ``"uncertain"``
    được gói thành ``VerifyTask`` và gửi Verifier.

    Attributes:
        verdict: ``"clear"`` hoặc ``"uncertain"``.
        reasons: Lý do bị gắn cờ, rỗng nếu clear; được đưa vào prompt của Verifier làm điểm khởi đầu.
    """

    verdict: Literal["clear", "uncertain"]
    reasons: tuple[str, ...] = ()


class VerifyTask(TypedDict):
    """Yêu cầu kiểm chứng gửi cho Verifier, mỗi yêu cầu chứa đúng một candidate UNCERTAIN.

    Attributes:
        item_key: Khoá định danh candidate trong cuộc họp.
        segment_id: Mã đoạn chủ đề chứa candidate.
        kind: ``"action"``, ``"decision"`` hoặc ``"progress"``; với ``"progress"`` thì ``candidate``
            là ``ProgressUpdate``.
        candidate: Claim cần kiểm chứng.
        reasons: Lý do candidate bị gắn UNCERTAIN.
        turns: Lượt nói của chủ đề chứa candidate.
        meeting_turns: Lượt nói của cả cuộc họp, để công cụ tra được bằng chứng nằm ở chủ đề khác
            (ví dụ việc được chốt ở chủ đề sau).
        registry: Danh bạ người nói của cả cuộc họp.
    """

    item_key: str
    segment_id: str
    kind: CandidateKind
    candidate: Claim
    reasons: tuple[str, ...]  # ``Check.reasons``
    turns: tuple[SpeakerTurn, ...]
    meeting_turns: tuple[SpeakerTurn, ...]
    registry: SpeakerRegistry


# ---------------------------------------------------------------------------
# Bước 5: Verifier (step5_verify)
# ---------------------------------------------------------------------------


class VerdictInput(TypedDict):
    """Đầu vào của luật hậu kiểm kết luận Verifier cho việc giao hoặc kết luận.

    Attributes:
        kind: ``"action"`` hoặc ``"decision"``.
        candidate: Việc giao hoặc kết luận đang xét.
        turns: Các lượt nói mà lượt giao hoặc lượt chốt phải thuộc về; Verifier truyền cả cuộc họp.
    """

    kind: CandidateKind
    candidate: "ActionItemCandidate | DecisionCandidate"
    turns: tuple[SpeakerTurn, ...]


# keep: giữ nguyên; revise: giữ nhưng sửa người phụ trách (chỉ action);
# drop: bỏ khỏi kết quả cuối.
JudgeVerdict = Literal["keep", "revise", "drop"]


@dataclass(frozen=True, slots=True)
class VerifierStep:
    """Một bước tra cứu của Verifier: suy nghĩ, công cụ đã gọi, tham số và kết quả trả về.

    Attributes:
        thought: Suy luận của Verifier trước khi gọi công cụ.
        action: Tên công cụ được gọi.
        argument: Tham số truyền cho công cụ.
        observation: Kết quả công cụ trả về.
    """

    thought: str
    action: str
    argument: str
    observation: str


@dataclass(frozen=True, slots=True)
class Review:
    """Nhận xét của Verifier cho một Claim trong một vòng trao đổi; không sửa Claim.

    Attributes:
        verdict: ``"keep"``, ``"revise"``, ``"drop"`` hoặc ``"unresolved"``, sau luật hậu kiểm.
        deciding_turn_id: Lượt giao, lượt chốt hoặc lượt nêu trạng thái Verifier chỉ ra; None nếu không có.
        feedback: Lý do, gửi lại cho agent trích xuất.
        steps: Các bước tra cứu của vòng này.
        suggestion: Phần sửa Verifier đề xuất (việc giao: các bên nhận việc; tiến độ: mã trạng thái);
            rỗng nếu không đề xuất. Chỉ agent trích xuất mới áp đề xuất này lên Claim.
        suggestion_reason: Lý do của đề xuất.
    """

    verdict: str
    deciding_turn_id: str | None
    feedback: str
    steps: tuple[VerifierStep, ...] = ()
    suggestion: str = ""
    suggestion_reason: str = ""


@dataclass(frozen=True, slots=True)
class Response:
    """Trả lời của agent trích xuất cho một nhận xét của Verifier.

    Attributes:
        stance: ``"accept"`` (đồng ý), ``"amend"`` (sửa), ``"defend"`` (giữ ý kiến), hoặc chuỗi rỗng nếu
            mô hình trả lập trường không hợp lệ.
        confirm_turn_id: Lượt căn cứ agent chỉ ra; None nếu không có.
        argument: Lập luận của agent.
        claim: Claim sau khi agent sửa; trùng Claim cũ nếu không sửa gì.
        edit_reason: Lý do sửa cần giữ đến kết quả cuối (việc giao: lý do chọn bên nhận việc); rỗng nếu
            không có.
    """

    stance: str
    confirm_turn_id: str | None
    argument: str
    claim: Claim
    edit_reason: str = ""


@dataclass(frozen=True, slots=True)
class ConsensusRound:
    """Một vòng trao đổi giữa Verifier và agent trích xuất cho một candidate.

    Attributes:
        candidate_text: Candidate Verifier xét ở vòng này, có thể đã được sửa ở vòng trước.
        steps: Các bước tra cứu của Verifier ở vòng này.
        verdict: Kết luận của Verifier sau luật hậu kiểm (keep/revise/drop/unresolved).
        feedback: Lý do Verifier gửi lại cho agent trích xuất.
        deciding_turn_id: Lượt giao hoặc chốt Verifier chỉ ra; None nếu không có.
        stance: Phản hồi của agent trích xuất (accept/amend/defend); rỗng khi Verifier đã giữ nên
            không cần hỏi lại.
        response: Lập luận của agent trích xuất.
        confirm_turn_id: Lượt giao hoặc chốt agent trích xuất chỉ ra; None nếu không có.
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
    """Bản ghi toàn bộ quá trình kiểm chứng một candidate UNCERTAIN, dùng để tra soát kết quả.

    Attributes:
        item_key: Khoá định danh candidate.
        segment_id: Mã đoạn chủ đề chứa candidate.
        kind: Loại candidate (việc giao, kết luận hay tiến độ).
        candidate_text: Nội dung candidate lúc vào Verifier.
        reasons: Lý do candidate bị gắn UNCERTAIN.
        steps: Mọi bước tra cứu của Verifier, nối qua các vòng.
        verdict: Kết luận cuối (keep/revise/drop), hoặc ``"unresolved"`` khi không kết luận được và
            candidate được giữ theo hướng an toàn.
        reasoning: Giải thích cuối: nhận xét vòng cuối của Verifier, hoặc ghi chú lỗi.
        final_text: Nội dung sau khi sửa; rỗng nếu candidate bị bỏ.
        deciding_turn_id: Lượt giao hoặc chốt Verifier chỉ ra.
        decided_by: ``"consensus"`` (hai bên đồng thuận), ``"verifier"`` (hết vòng, theo kết luận của
            Verifier) hoặc ``"fallback"`` (lỗi LLM hoặc vẫn không kết luận được).
        rounds: Các vòng trao đổi giữa Verifier và agent trích xuất.
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


# ---------------------------------------------------------------------------
# Định danh actor (actors/, dùng ở bước 5-6)
# ---------------------------------------------------------------------------

ActorType = Literal["person", "organization", "unknown"]
AssigneeRole = Literal["lead", "support", "joint"]
ASSIGNEE_ROLES: tuple[str, ...] = ("lead", "support", "joint")
ASSIGNEE_TYPES: tuple[str, ...] = ("person", "organization")


@dataclass(frozen=True, slots=True)
class AssigneeMention:
    """Một bên nhận việc do agent khai, chưa được đối chiếu với danh bạ.

    Việc đối chiếu với danh bạ để ra tên chuẩn làm ở bước sau.

    Attributes:
        name: Tên agent chép: đúng tên trong danh bạ nếu có, không thì cách gọi trong bản ghi.
        role: ``"lead"`` (chủ trì, nhận chính), ``"support"`` (phối hợp) hoặc ``"joint"`` (cùng thực hiện).
        actor_type: Người hay đơn vị theo agent; ``"unknown"`` khi agent không nói.
        code: Mã ngắn của bên đó trong danh bạ bên nhận việc gửi kèm prompt (ví dụ "N1", "D2"); None
            nếu agent không khai (bên ngoài danh bạ hoặc không chắc là ai). Chưa được kiểm; mã không
            có trong danh bạ sẽ bị bỏ qua khi đối chiếu.
    """

    name: str
    role: AssigneeRole = "lead"
    actor_type: ActorType = "unknown"
    code: str | None = None


@dataclass(frozen=True, slots=True)
class ActorCandidate:
    """Một ứng viên cho bên nhận việc, được chấm điểm bằng luật.

    Attributes:
        name: Tên chuẩn: họ tên trong danh sách tham dự, tên người nói, hoặc tên đơn vị.
        actor_type: ``"person"`` hoặc ``"organization"``.
        score: Điểm trong [0, 1]; càng cao càng khớp.
        reason: Các tín hiệu đã cộng điểm, để Verifier và người đọc kiểm tra.
        ref_id: Mã trong danh sách tham dự (P1, O3...); None nếu chỉ là người nói trong bản ghi.
    """

    name: str
    actor_type: ActorType
    score: float
    reason: str
    ref_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActorAssignee:
    """Một người hoặc đơn vị nhận việc đã định danh; một việc có thể giao cho nhiều bên.

    Attributes:
        mention: Cách gọi nguyên văn, ví dụ "anh Sơn", "Sở Xây dựng".
        role: ``"lead"`` (chủ trì, nhận chính), ``"support"`` (phối hợp) hoặc ``"joint"`` (cùng thực
            hiện, không phân chủ trì).
        name: Tên chuẩn sau khi định danh; None nếu chưa xác định.
        actor_type: Người, đơn vị hay chưa xác định.
        candidates: Các ứng viên đã xét, điểm giảm dần.
        flag: ``"ambiguous"`` khi không có ứng viên đủ rõ; None nếu đã rõ.
        reason: Lý do chọn, từ Verifier hoặc từ luật chấm điểm.
        ref_id: Mã trong danh sách tham dự (P1, O3...) nếu có.
    """

    mention: str
    role: AssigneeRole
    name: str | None
    actor_type: ActorType
    candidates: tuple[ActorCandidate, ...] = ()
    flag: str | None = None
    reason: str = ""
    ref_id: str | None = None


# ---------------------------------------------------------------------------
# Bước 6: kết quả cuối (step6_finalize)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ActionItem(ActionItemCandidate):
    """Việc giao cuối cùng: việc giao đã kiểm chứng cộng phần định danh bên nhận việc.

    Là lớp con của ``ActionItemCandidate`` nên mọi chỗ nhận kiểu cha (gộp trùng, chuyển sang JSON)
    dùng được ngay. Các trường ``actor_*`` tóm tắt theo bên nhận việc chính, tức bên đầu tiên trong
    ``assignees`` (bên chủ trì đứng trước).

    Attributes:
        actor_type: Bên chính là người, đơn vị hay chưa xác định.
        actor_candidates: Các ứng viên của bên chính, điểm giảm dần, giữ lại để tra soát.
        actor_flag: ``"ambiguous"`` khi có ít nhất một bên nhận việc chưa đủ rõ.
        actor_reason: Lý do chọn bên chính, từ Verifier hoặc từ luật chấm điểm.
        assignees: Mọi bên nhận việc kèm vai trò (chủ trì, phối hợp, cùng thực hiện).
    """

    actor_type: ActorType = "unknown"
    actor_candidates: tuple[ActorCandidate, ...] = ()
    actor_flag: str | None = None
    actor_reason: str = ""
    assignees: tuple[ActorAssignee, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskProgress:
    """Tiến độ của một việc trong danh sách việc cần báo cáo, gộp từ mọi chủ đề.

    Attributes:
        task_id: Mã việc.
        title: Tên việc.
        owner: Tên bên chủ trì.
        previous_status: Trạng thái gần nhất trước phiên họp, lấy từ danh sách việc.
        status: Trạng thái sau phiên họp, hoặc ``"not_reported"`` nếu không ai báo cáo.
        previous_due: Hạn trước phiên họp.
        deadline_raw: Hạn mới nguyên văn, lấy từ cập nhật quyết định hoặc cập nhật gần nhất có nêu hạn;
            None nếu không đổi.
        deadline_date: Hạn mới dạng "YYYY-MM-DD"; None nếu không đổi hoặc không quy được.
        deadline_kind: Loại của hạn mới.
        deadline_extended: Được gia hạn nhưng chưa có hạn mới; hạn hiển thị vẫn là hạn cũ để người
            dùng sửa.
        status_conflict: Có báo cáo "done" đã xác nhận cùng với một cập nhật đã xác nhận nêu trạng thái
            khác, ví dụ báo cáo xong nhưng bị yêu cầu làm lại.
        uncertain: Cập nhật quyết định trạng thái chưa được xác nhận (giữ theo đường dự phòng).
        overdue: Hạn cũ đã qua so với ngày họp mà việc chưa xong và chưa bị huỷ.
        deciding_update: Cập nhật quyết định trạng thái; None nếu việc không được báo cáo.
        updates: Mọi cập nhật của việc, theo thứ tự lượt nói.
        reassign_update: Cập nhật gần nhất giao việc cho bên khác; None nếu không giao lại.
        assignees: Bên nhận việc mới của ``reassign_update`` đã định danh; rỗng nếu không giao lại.
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
    deadline_extended: bool = False
    status_conflict: bool = False
    uncertain: bool = False
    overdue: bool = False
    deciding_update: ProgressUpdate | None = None
    updates: tuple[ProgressUpdate, ...] = ()
    reassign_update: ProgressUpdate | None = None
    assignees: tuple[ActorAssignee, ...] = ()


@dataclass(frozen=True, slots=True)
class MeetingReport:
    """Báo cáo cuối của cuộc họp, đã sắp theo thứ tự chủ đề và gộp mục trùng.

    Phần kết quả không được yêu cầu khi chạy để rỗng.

    Attributes:
        labels: Nhãn chủ đề theo thứ tự chủ đề.
        discussion_points: Các ý thảo luận, mỗi ý gắn người tham gia (phần Diễn biến họp).
        assignments: Việc giao đã kiểm chứng (phần Giao việc).
        decisions: Kết luận đã kiểm chứng (phần Kết luận họp).
        verification_records: Bản ghi kiểm chứng, kèm các vòng trao đổi.
        failures: Các lần agent trích xuất vẫn lỗi sau mọi lượt thử.
        task_progress: Tiến độ từng việc trong danh sách việc cần báo cáo, theo thứ tự trong danh sách;
            rỗng nếu phiên họp không có danh sách việc.
    """

    labels: tuple[TopicLabel, ...]
    discussion_points: tuple[DiscussionPoint, ...]
    assignments: tuple[ActionItemCandidate, ...]
    decisions: tuple[DecisionCandidate, ...]
    verification_records: tuple[VerificationRecord, ...]
    failures: tuple[TopicFailure, ...]
    task_progress: tuple[TaskProgress, ...] = ()


__all__ = [
    "AGENT_OF_PART",
    "ANALYSIS_PARTS",
    "ActionItemCandidate",
    "ActionItem",
    "ActionStatus",
    "ActorAssignee",
    "ActorCandidate",
    "ActorType",
    "AnalysisPart",
    "AssigneeRole",
    "CandidateKind",
    "Check",
    "Claim",
    "ConsensusRound",
    "Response",
    "Review",
    "VerdictInput",
    "DecisionCandidate",
    "DecisionStatus",
    "DiscussionPoint",
    "JudgeVerdict",
    "MeetingReport",
    "ProgressUpdate",
    "ExtractorInput",
    "SpeakerRegistry",
    "TaskProgress",
    "TopicFailure",
    "UPDATE_STATUSES",
    "UpdateStatus",
    "Verification",
    "VerificationRecord",
    "VerifierStep",
    "VerifyTask",
]
