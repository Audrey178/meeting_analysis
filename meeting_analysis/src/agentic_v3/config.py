"""Cấu hình của pipeline agentic v3 -- xem ``graph/meeting.py`` cho hình dạng graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VerifierMode = Literal["on", "keep_uncertain", "drop_uncertain"]
VERIFIER_MODES: tuple[VerifierMode, ...] = ("on", "keep_uncertain", "drop_uncertain")


@dataclass(frozen=True)
class V3Config:
    """Các núm chỉnh của pipeline v3.

    Các trường:
        extract_attempts: số lần gọi tối đa cho MỖI agent trích xuất của một chủ đề
            (adapter đã tự retry lỗi tạm thời; đây là lượt thử lại ở tầng agent,
            thay cho ``retry_failed_topics`` chạy sau chủ đề cuối của v1).
        verifier_max_tool_calls: số lần Verifier được gọi tool trước khi buộc phải
            kết luận; tổng lời gọi LLM mỗi candidate <= giá trị này + 1.
        search_top_k: số lượt nói ``search_meeting`` trả về mỗi lần.
        consensus_max_rounds: số vòng tối đa Verifier gửi feedback lại cho agent trích
            xuất để hai bên đồng thuận (xem ``nodes/verifier.py``). Hết vòng mà chưa đồng thuận
            thì lấy kết luận cuối của Verifier. Mỗi vòng tốn tối đa
            ``verifier_max_tool_calls + 2`` lời gọi LLM.
        max_concurrency: số task LangGraph chạy song song mỗi superstep (số chủ đề
            xử lý cùng lúc). Số lời gọi LLM đồng thời thực sự do
            ``LLMConcurrencyGate`` giới hạn, không phải giá trị này.
        verifier_mode: candidate UNCERTAIN sau evidence-check đi đâu. ``on`` (production): gửi
            Verifier. ``keep_uncertain``/``drop_uncertain``: không chạy Verifier, giữ hết/bỏ hết
            -- chỉ dùng cho ablation đo Verifier tăng precision/cứu recall bao nhiêu.
        evidence_check: True (production) thì luật 0 token tách candidate CLEAR/UNCERTAIN. Tắt
            (ablation) thì mọi candidate coi là UNCERTAIN và đi theo ``verifier_mode``.
    """

    extract_attempts: int = 2
    verifier_max_tool_calls: int = 3
    search_top_k: int = 5
    consensus_max_rounds: int = 3
    max_concurrency: int = 16
    verifier_mode: VerifierMode = "on"
    evidence_check: bool = True

    def __post_init__(self) -> None:
        """Kiểm tra giá trị hợp lệ.

        Lỗi: ValueError nếu một giá trị số nằm ngoài miền cho phép.
        """

        if self.extract_attempts < 1:
            raise ValueError("extract_attempts phải >= 1")
        if self.verifier_max_tool_calls < 0:
            raise ValueError("verifier_max_tool_calls phải >= 0")
        if self.consensus_max_rounds < 1:
            raise ValueError("consensus_max_rounds phải >= 1")
        if self.search_top_k < 1:
            raise ValueError("search_top_k phải >= 1")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency phải >= 1")
        if self.verifier_mode not in VERIFIER_MODES:
            raise ValueError(f"verifier_mode phải là một trong {VERIFIER_MODES}")


__all__ = ["VERIFIER_MODES", "V3Config", "VerifierMode"]
