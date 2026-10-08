"""Các kiểu dữ liệu (dataclass/TypedDict) dùng chung cho trạng thái graph và các node.

Tách riêng khỏi ``state.py`` vì hai loại có vòng đời khác nhau: ``MeetingState``
(trạng thái LangGraph có reducer) chỉ tổng hợp lại, còn các kiểu ở đây do từng
node tự tạo ra trực tiếp.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, TypedDict

from ..utils.contracts import SpeakerTurn
from .deadline import DeadlineKind


class SegmentTask(TypedDict):
    """Gói dữ liệu gửi cho agent xử lý MỘT đoạn chủ đề (qua ``Send`` của LangGraph).

    Cố ý KHÔNG phải toàn bộ trạng thái graph: mỗi agent chỉ thấy các lượt nói của
    đúng đoạn của nó, không bao giờ thấy cả cuộc họp (SPEC.md AC-5.1).

    Các trường:
        segment_id: mã đoạn chủ đề.
        title: tiêu đề chủ đề do bước gán nhãn tạo ra ("" nếu chưa có nhãn).
        summary: tóm tắt chủ đề ("" nếu chưa có nhãn).
        turns: các lượt nói thuộc đoạn này, theo thứ tự.
        previous_context: tóm tắt ngắn tên người và việc đã giao ở các chủ đề TRƯỚC.
            Chỉ ``action_agent`` đọc trường này, để quy các cách xưng hô
            "em"/"anh"/"bọn em" về tên thật đã biết. Đây là ngoại lệ có chủ đích:
            các chủ đề được xử lý theo thứ tự chính là để truyền được ngữ cảnh
            này qua ranh giới chủ đề. Nó chỉ là bản tóm tắt, không phải bản ghi thô.
        meeting_date: ngày họp ISO "YYYY-MM-DD" (None nếu không biết). ``action_agent``
            đưa vào prompt làm neo cho QUY TẮC CHUẨN HOÁ HẠN và cho luật dự phòng.
    """

    segment_id: str
    title: str
    summary: str
    turns: tuple[SpeakerTurn, ...]
    previous_context: str
    meeting_date: str | None


@dataclass(frozen=True, slots=True)
class TopicFailure:
    """Ghi nhận một lời gọi LLM theo đoạn chủ đề đã bỏ cuộc (sau khi adapter tự retry hết).

    Lưu trong state (thay vì chỉ ghi log) để graph thử lại đúng một lần ở cuối
    (``graph.retry_failed_topics``) và để API báo được cho người gọi những chủ đề
    nào vẫn còn thiếu.

    Các trường:
        segment_id: mã đoạn chủ đề bị lỗi.
        agent: tên node agent bị lỗi.
        error: thông báo lỗi.
    """

    segment_id: str
    agent: str
    error: str


@dataclass(frozen=True, slots=True)
class SpeakerPoint:
    """Một luận điểm của một người nói trong một đoạn chủ đề.

    Các trường:
        text: nội dung luận điểm (ngôi thứ ba).
        evidence_ids: các turn_id làm bằng chứng cho luận điểm.
        quotes: câu trích nguyên văn ứng với từng phần tử của ``evidence_ids``
            (cùng thứ tự và độ dài). Luôn do luật điền và kiểm chứng
            (``_shared.validate_evidence_with_quotes``), không tin trực tiếp từ LLM.
    """

    text: str
    evidence_ids: tuple[str, ...]
    quotes: tuple[str, ...]

    @property
    def citation_count(self) -> int:
        """Số trích dẫn của luận điểm (bằng số turn_id bằng chứng)."""

        return len(self.evidence_ids)


@dataclass(frozen=True, slots=True)
class SpeakerSection:
    """Toàn bộ luận điểm của MỘT người nói trong MỘT đoạn chủ đề.

    Các trường:
        segment_id: mã đoạn chủ đề.
        initials: chữ viết tắt của người nói (ví dụ "PS").
        full_name: họ tên đầy đủ, đã đối chiếu với người nói thật của đoạn.
        points: các luận điểm của người này.
    """

    segment_id: str
    initials: str
    full_name: str
    points: tuple[SpeakerPoint, ...]


# Trạng thái do agent trích xuất TỰ KHAI cho từng candidate. Đây là tín hiệu
# cho Evidence-Check: luật không đọc được ý định từ ``text`` (LLM đã viết lại
# thành câu khẳng định "Thống nhất..."/"giao X..." nên mất dấu hedge), nhưng
# đọc được nhãn này cùng lượt nói chốt (``confirm_turn_id``) nguyên văn.
ActionStatus = Literal["assigned", "self_committed", "proposed", "reported", "unknown"]
DecisionStatus = Literal["agreed", "proposed", "reported", "unknown"]
# Candidate đi vào kết quả bằng đường nào: luật CLEAR, debate+judge, hoặc giữ
# theo luật an toàn khi debate lỗi LLM / lượt retry không chạy debate.
Verification = Literal["rule", "debate", "fallback"]


@dataclass(frozen=True, slots=True)
class DecisionCandidate:
    """Một phát biểu KẾT LUẬN/CHỐT PHƯƠNG ÁN, cố ý không gắn với người chịu trách nhiệm.

    Phát biểu giao việc cho một người cụ thể thuộc ``ActionItemCandidate`` (kiểu
    có trường ``actor``), không thuộc kiểu này.

    Các trường thêm (có mặc định để code cũ dựng candidate không phải đổi):
        status: agent tự khai đã chốt ("agreed") hay mới là đề xuất/báo cáo.
        confirm_turn_id: lượt nói thể hiện việc chốt; đã kiểm là thuộc đoạn
            này (None nếu agent không nêu hoặc nêu sai).
        verification: đường kiểm chứng đã đi qua (xem ``Verification``).
    """

    segment_id: str
    text: str
    evidence_ids: tuple[str, ...]
    quotes: tuple[str, ...]
    status: DecisionStatus = "unknown"
    confirm_turn_id: str | None = None
    verification: Verification = "rule"


@dataclass(frozen=True, slots=True)
class ActionItemCandidate:
    """Một phát biểu GIAO VIỆC: ai được giao làm gì.

    ``actor`` là người phụ trách, có thể None nếu không xác định chắc chắn (ví dụ
    chỉ có đại từ "em"/"anh" mà không quy được về tên thật). ``text`` chỉ là
    nội dung công việc (bắt đầu bằng động từ), KHÔNG lặp "giao <actor>" hay
    thời hạn -- hai thứ đó đã có trường riêng.

    Các trường thêm (có mặc định để code cũ dựng candidate không phải đổi):
        deadline_raw: thời hạn nguyên văn theo bản ghi, None nếu không nêu.
        deadline_date: ``deadline_raw`` quy về ngày ISO theo ngày họp (``deadline.py``),
            None nếu không quy được.
        deadline_kind: loại hạn ("exact"/"before"/"end_of_period"/"relative"/"unknown").
        status: agent tự khai là việc được giao/tự nhận hay chỉ là đề xuất/báo cáo.
        confirm_turn_id: lượt nói giao/nhận việc; đã kiểm là thuộc đoạn này.
        verification: đường kiểm chứng đã đi qua (xem ``Verification``).
    """

    segment_id: str
    actor: str | None
    text: str
    evidence_ids: tuple[str, ...]
    quotes: tuple[str, ...]
    deadline_raw: str | None = None
    deadline_date: str | None = None
    deadline_kind: DeadlineKind = "unknown"
    status: ActionStatus = "unknown"
    confirm_turn_id: str | None = None
    verification: Verification = "rule"


# ---------------------------------------------------------------------------
# Evidence-check + Debate/Judge (kiến trúc M5, xem be/DESIGN.md)
# ---------------------------------------------------------------------------

CandidateKind = Literal["action", "decision"]


@dataclass(frozen=True, slots=True)
class EvidenceFlag:
    """Kết quả evidence-check (luật, 0 token) cho MỘT candidate action/decision.

    Sinh ra bởi ``_shared.check_action_evidence``/``check_decision_evidence``.
    Candidate ``"uncertain"`` được gói thành ``DebateTask`` và gửi cho
    ``debate_and_judge_agent`` (xem ``nodes.evidence_check``, ``graph.py``);
    candidate ``"clear"`` đi thẳng vào danh sách kết quả đã kiểm chứng.

    Các trường:
        verdict: "clear" hoặc "uncertain".
        reasons: lý do bị gắn cờ (rỗng nếu clear); đưa vào prompt debate làm
            điểm khởi đầu cho bên phản biện.
    """

    verdict: Literal["clear", "uncertain"]
    reasons: tuple[str, ...] = ()


class DebateTask(TypedDict):
    """Gói dữ liệu gửi cho ``debate_and_judge_agent`` (qua ``Send``) cho MỘT candidate uncertain.

    Các trường:
        item_key: mã duy nhất trong cuộc họp (``f"{segment_id}:{kind}:{index}"``),
            dùng để đánh dấu "candidate này đã qua debate" trong
            ``MeetingState.completed_debate_items`` (xem ``graph.advance_topic``).
        segment_id: mã đoạn chủ đề chứa candidate.
        kind: "action" hoặc "decision".
        candidate: ``ActionItemCandidate`` hoặc ``DecisionCandidate`` gốc (chưa đổi).
        reasons: lý do evidence-check gắn cờ uncertain.
        turns: các lượt nói của đoạn, để Agent A/B/Judge tra bằng chứng.
    """

    item_key: str
    segment_id: str
    kind: CandidateKind
    candidate: "ActionItemCandidate | DecisionCandidate"
    reasons: tuple[str, ...]
    turns: tuple[SpeakerTurn, ...]


# keep: giữ nguyên; revise: giữ nhưng sửa người phụ trách (chỉ action);
# drop: bỏ khỏi kết quả cuối.
JudgeVerdict = Literal["keep", "revise", "drop"]


@dataclass(frozen=True, slots=True)
class DebateRecord:
    """Bản ghi đầy đủ MỘT vòng debate+judge cho một candidate uncertain, để audit.

    Không phải input cho bước nào sau -- chỉ để hiển thị minh bạch (renderer,
    API) vì sao một candidate uncertain được giữ hoặc bị bỏ.

    ``verdict``: keep / revise (sửa người phụ trách) / drop; ``kept`` = verdict
    khác drop. ``final_text``: candidate sau khi sửa ("" nếu bị bỏ).
    ``deciding_turn_id``: lượt nói giao/chốt mà judge dựa vào (None nếu không có).
    """

    segment_id: str
    kind: CandidateKind
    candidate_text: str
    reasons: tuple[str, ...]
    support_argument: str
    oppose_argument: str
    kept: bool
    reasoning: str
    verdict: JudgeVerdict = "keep"
    final_text: str = ""
    deciding_turn_id: str | None = None


__all__ = [
    "SegmentTask",
    "TopicFailure",
    "SpeakerPoint",
    "SpeakerSection",
    "DecisionCandidate",
    "ActionItemCandidate",
    "ActionStatus",
    "DecisionStatus",
    "Verification",
    "JudgeVerdict",
    "CandidateKind",
    "EvidenceFlag",
    "DebateTask",
    "DebateRecord",
]
