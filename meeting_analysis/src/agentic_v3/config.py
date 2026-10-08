"""Cấu hình của pipeline agentic v3 -- xem ``graph.py`` cho hình dạng graph."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class V3Config:
    """Các núm chỉnh của pipeline v3.

    Các trường:
        skip_agents_without_cues: True thì Planner bỏ Action/Decision agent ở chủ đề
            không có từ giao/nhận/chốt việc nào (Content agent không bao giờ bị bỏ).
            Tắt để làm ablation đo recall của bước bỏ qua.
        extract_attempts: số lần gọi tối đa cho MỖI agent trích xuất của một chủ đề
            (adapter đã tự retry lỗi tạm thời; đây là lượt thử lại ở tầng agent,
            thay cho ``retry_failed_topics`` chạy sau chủ đề cuối của v1).
        verifier_max_tool_calls: số lần Verifier được gọi tool trước khi buộc phải
            kết luận; tổng lời gọi LLM mỗi candidate <= giá trị này + 1.
        search_top_k: số lượt nói ``search_meeting`` trả về mỗi lần.
        consensus_max_rounds: số vòng tối đa Verifier gửi feedback lại cho agent trích
            xuất để hai bên đồng thuận (xem ``verifier.py``). Hết vòng mà chưa đồng thuận
            thì lấy kết luận cuối của Verifier. Mỗi vòng tốn tối đa
            ``verifier_max_tool_calls + 2`` lời gọi LLM.
        max_concurrency: số task LangGraph chạy song song mỗi superstep (số chủ đề
            xử lý cùng lúc). Số lời gọi LLM đồng thời thực sự do
            ``LLMConcurrencyGate`` giới hạn, không phải giá trị này.
    """

    skip_agents_without_cues: bool = True
    extract_attempts: int = 2
    verifier_max_tool_calls: int = 3
    search_top_k: int = 5
    consensus_max_rounds: int = 3
    max_concurrency: int = 16

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


__all__ = ["V3Config"]
