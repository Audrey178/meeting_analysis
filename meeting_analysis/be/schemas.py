"""Schema request/response của HTTP API (xem ``routers/meetings.py``)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    """Dữ liệu đầu vào của API phân tích cuộc họp: một transcript.

    Cùng dạng với JSON transcript gốc mà ``scripts/run_to_TreeSeg.py --input`` nhận
    (``inputs/sample_transcript.json``) và được chuyển nguyên vẹn cho
    ``parse_transcript_payload``. Vì vậy ``items`` cố ý để lỏng (``list[dict]``) thay vì
    khai lại từng trường, tránh lệch so với parser.

    ``meeting_id``/``revision_id`` PHẢI được khai báo (khác ``items``) vì Pydantic âm
    thầm bỏ mọi trường không khai báo trên model; thiếu chúng thì ``request.model_dump()``
    chỉ đưa ``{"items": [...]}`` cho ``parse_transcript_payload``.

    Cả hai đều TÙY CHỌN: ``parse_transcript_payload`` nhận diện danh sách item xuất từ
    STT (item có ``segment``/``speaker_name``, như ``inputs/recording_old.json``) và tự
    dùng ``"stt-export"``/``"export-0"`` khi thiếu. Chỉ dạng "native" mới bắt buộc hai
    trường này, và ``_parse_native_payload`` tự báo lỗi rõ ràng. Từng bắt buộc chúng vô
    điều kiện ở đây làm hỏng trường hợp STT export (payload thật giống ``recording_old.json``);
    lỗi này chỉ phát hiện khi thử payload thật vào endpoint đang chạy, vì mẫu của
    ``test_api.py`` tình cờ đã có sẵn cả hai.

    Các trường:
        meeting_id: mã cuộc họp (tùy chọn).
        revision_id: mã phiên bản transcript (tùy chọn).
        meeting_date: ngày họp (tùy chọn), neo để quy hạn chót của việc giao ("tuần sau")
            về ``deadline_date``; thiếu thì vẫn có ``deadline_kind``.
        items: danh sách các dòng transcript ở dạng dict.
    """

    meeting_id: str | None = None
    revision_id: str | None = None
    meeting_date: date | None = None
    items: list[dict]


class SpeakerPointOut(BaseModel):
    """Một luận điểm của một người nói, kèm bằng chứng để người dùng đối chiếu.

    Các trường:
        text: nội dung luận điểm.
        evidence_ids: các turn_id làm bằng chứng.
        quotes: câu trích nguyên văn ứng với từng ``evidence_ids`` (cùng thứ tự và độ
            dài); là câu thực sự được trích chứ không phải cả lượt nói (xem
            ``src.agentic._shared.validate_evidence_with_quotes``).
        citation_count: số trích dẫn (bằng số turn_id bằng chứng).
    """

    text: str
    evidence_ids: list[str]
    quotes: list[str]
    citation_count: int


class SpeakerSectionOut(BaseModel):
    """Các luận điểm của một người nói trong một chủ đề (kèm chữ viết tắt và họ tên)."""

    initials: str
    full_name: str
    points: list[SpeakerPointOut]


class TopicOut(BaseModel):
    """Một chủ đề của cuộc họp: tiêu đề, tóm tắt và luận điểm theo từng người nói."""

    segment_id: str
    title: str
    summary: str
    speakers: list[SpeakerSectionOut]


class ActionItemOut(BaseModel):
    """Một việc được giao ĐÃ KIỂM CHỨNG (qua Evidence-Check, + Debate/Judge nếu
    uncertain), kèm đoạn chủ đề nguồn và bằng chứng trích dẫn.

    ``actor`` đi kèm TỪNG item (có thể ``None`` nếu Debate/Judge giữ lại một
    candidate mà vẫn không xác định được người phụ trách) -- danh sách trả
    về KHÔNG gộp theo người nữa (xem "M6" trong ``../be/DESIGN.md``: bỏ
    ``group_task_assignments``, việc gộp hiển thị theo người phụ trách nếu
    cần là việc của tầng frontend, không phải backend).

    ``text`` chỉ là nội dung việc (không lặp "giao <actor>"), hạn chót tách
    riêng: ``deadline_raw`` (nguyên văn), ``deadline_date`` (ISO, quy theo ngày họp),
    ``deadline_kind`` (exact/before/end_of_period/relative/unknown). ``verification``:
    "rule" (CLEAR ngay), "debate" (qua Debate+Judge), "fallback" (giữ theo luật an toàn
    khi debate lỗi/không chạy).
    """

    segment_id: str
    actor: str | None
    text: str
    deadline_raw: str | None = None
    deadline_date: str | None = None
    deadline_kind: str = "unknown"
    status: str = "unknown"
    confirm_turn_id: str | None = None
    verification: str = "rule"
    evidence_ids: list[str]
    quotes: list[str]
    citation_count: int


class DecisionOut(BaseModel):
    """Một quyết định/chốt phương án ĐÃ KIỂM CHỨNG (qua Evidence-Check, +
    Debate/Judge nếu uncertain), kèm đoạn chủ đề nguồn và bằng chứng trích dẫn.

    KHÔNG có đoạn văn tổng hợp hành chính nào đi kèm -- tính năng đó (LLM
    viết "Kết luận họp" thành một câu mở đầu + bullet đã gộp) đã bị bỏ cùng
    ``conclusion_agent`` (xem "M6" trong ``../be/DESIGN.md``). Đây là danh
    sách PHẲNG, mỗi phần tử một quyết định, chưa qua tổng hợp/viết lại.
    """

    segment_id: str
    text: str
    status: str = "unknown"
    confirm_turn_id: str | None = None
    verification: str = "rule"
    evidence_ids: list[str]
    quotes: list[str]
    citation_count: int


class TurnOut(BaseModel):
    """Một ``src.utils.contracts.SpeakerTurn`` rút gọn, đủ để frontend hiển thị bảng transcript.

    Và tra ngược ``evidence_ids`` của một luận điểm về nội dung lượt nói được trích.
    Không phải toàn bộ contract (thông tin thời gian/vai trò giữ nội bộ).
    """

    turn_id: str
    speaker: str | None
    text: str


class FailedTopicOut(BaseModel):
    """Một lời gọi LLM theo chủ đề vẫn lỗi sau các lần retry VÀ sau lượt thử lại cuối.

    Kết quả của agent đó cho chủ đề này bị thiếu trong phản hồi: ``content_agent``
    thì thiếu luận điểm của người nói, ``action_agent`` thì thiếu việc được giao,
    ``decision_agent`` thì thiếu quyết định/chốt phương án.
    """

    segment_id: str
    agent: str
    error: str


class DebateRecordOut(BaseModel):
    """Bản ghi một vòng Debate+Judge cho một candidate action/decision bị đánh dấu
    chưa chắc chắn (uncertain) bởi Evidence-Check -- để người dùng đối chiếu vì
    sao candidate đó được giữ hoặc bị bỏ (xem
    ``src.agentic.nodes.debate_judge_agent``).
    """

    segment_id: str
    kind: str
    candidate_text: str
    reasons: list[str]
    support_argument: str
    oppose_argument: str
    kept: bool
    reasoning: str
    verdict: str = "keep"
    final_text: str = ""
    deciding_turn_id: str | None = None


class AnalyzeResponse(BaseModel):
    """Kết quả phân tích cuộc họp -- đúng 3 phần output của pipeline (``topics``
    = Diễn biến họp, ``verified_assignments`` = Giao việc,
    ``verified_decisions`` = Kết luận họp), cộng transcript, các chủ đề bị
    lỗi và các candidate đã qua Debate/Judge để audit."""

    meeting_id: str
    revision_id: str
    topics: list[TopicOut]
    verified_assignments: list[ActionItemOut]
    verified_decisions: list[DecisionOut]
    turns: list[TurnOut]
    failed_topics: list[FailedTopicOut] = []
    debate_records: list[DebateRecordOut] = []


# ----- Agentic v3 (src/agentic_v3) — chủ đề song song + Verifier đồng thuận với agent trích xuất -----


class AnalyzeV3Request(AnalyzeRequest):
    """Đầu vào của ``POST /v3/meetings/analyze``: transcript (như ``AnalyzeRequest``) + người chủ trì.

    Các trường thêm:
        chair: tên người chủ trì (tùy chọn). v3 quy tên này về đúng nhãn người nói nếu khớp
            duy nhất một người và đưa vào prompt của agent trích xuất và Verifier, để nhận ra
            lời giao việc/kết luận của chủ trì. None hoặc rỗng thì model tự suy ra từ bản ghi.
    """

    chair: str | None = None


class VerifierStepOut(BaseModel):
    """Một bước tra cứu (ReAct) của Verifier."""

    thought: str
    action: str
    argument: str
    observation: str


class ConsensusRoundOut(BaseModel):
    """Một vòng Verifier gửi feedback -> agent trích xuất trả lời.
    ``stance``: "accept" | "amend" | "defend", rỗng khi Verifier đã giữ (keep)."""

    candidate_text: str
    verdict: str
    feedback: str
    deciding_turn_id: str | None = None
    stance: str = ""
    response: str = ""


class VerificationRecordOut(BaseModel):
    """Bản ghi kiểm chứng một candidate uncertain (thay ``DebateRecordOut`` ở v3).
    ``decided_by``: "consensus" (đồng thuận), "verifier" (hết vòng, theo Verifier) hoặc "fallback"."""

    item_key: str
    segment_id: str
    kind: str
    candidate_text: str
    reasons: list[str]
    steps: list[VerifierStepOut]
    verdict: str
    reasoning: str
    final_text: str = ""
    deciding_turn_id: str | None = None
    decided_by: str = "consensus"
    rounds: list[ConsensusRoundOut] = []


class SkippedAgentOut(BaseModel):
    """Agent trích xuất mà Planner bỏ qua ở một chủ đề (không có cue giao/chốt việc)."""

    segment_id: str
    agent: str


class AnalyzeV3Result(BaseModel):
    """Kết quả cuối của v3: cùng ba phần output như ``AnalyzeResponse``, cộng bản ghi
    kiểm chứng và các agent đã bỏ qua."""

    meeting_id: str
    revision_id: str
    topics: list[TopicOut]
    verified_assignments: list[ActionItemOut]
    verified_decisions: list[DecisionOut]
    turns: list[TurnOut]
    failed_topics: list[FailedTopicOut] = []
    verification_records: list[VerificationRecordOut] = []
    skipped_agents: list[SkippedAgentOut] = []


# ----- MA-MRG (src/agentic_v2) — job chạy nền -----


class MrgOptions(BaseModel):
    """Cấu hình một lần chạy MA-MRG (tập con cờ ablation của ``mrg.pipeline.PipelineConfig``).

    Các trường:
        exchange: có vòng trao đổi LLM ở Stage 2 (tắt = chỉ rule hòa giải khác role).
        reviewer: "feedback" (phân xử + feedback 1 vòng) | "select" (chỉ phân xử) | "none".
        realizer: LLM diễn đạt Diễn biến và sinh văn bản Thông báo kết luận (tắt = template, không có Thông báo).
        acceptance_policy: "unconfirmed" (chỉ đạo chưa đáp vẫn vào Giao việc, gắn cờ) | "strict".
    """

    exchange: bool = True
    reviewer: Literal["feedback", "select", "none"] = "feedback"
    realizer: bool = True
    acceptance_policy: Literal["unconfirmed", "strict"] = "unconfirmed"


class MrgJobRequest(AnalyzeRequest):
    """Đầu vào tạo job MA-MRG: transcript (như ``AnalyzeRequest``) + thông tin phiên họp.

    Các trường thêm:
        meeting_date: ngày họp "YYYY-MM-DD" — BẮT BUỘC vì Giao việc chuẩn hóa hạn ("thứ Sáu tuần này") theo ngày họp.
        chair: chủ trì (canonical name); None thì KB dùng luật cue chỉ đạo để xác định chỉ đạo.
        participants: danh sách thành viên (tên đầy đủ); rỗng thì lấy các người nói ASR.
        options: ``MrgOptions``.
    """

    meeting_date: date
    chair: str | None = None
    participants: list[str] = []
    options: MrgOptions = MrgOptions()


class MrgJobStatus(BaseModel):
    """Trạng thái một job MA-MRG; ``result`` chỉ có khi ``status == "succeeded"``.

    ``result`` để dạng dict (không khai lại từng trường): nó là ``services.mrg.serialize_result`` — gồm
    ``turns``, ``segments``, ``giao_viec``, ``ket_luan``, ``dien_bien``, ``thong_bao``, ``warnings``, ``report``,
    đúng schema SPEC MA-MRG mục 10 (mọi trường có ``fold_trace`` trỏ về turn_id + span).
    """

    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: str
    stage_label: str
    progress: dict
    error: str | None = None
    elapsed_s: float
    result: dict | None = None
