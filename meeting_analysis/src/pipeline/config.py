"""Các thông số chỉnh được của bước 4-6: số lần thử lại, số vòng trao đổi khi kiểm chứng, số bước
tra cứu của agent kiểm chứng và số chủ đề xử lý cùng lúc.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisConfig:
    """Gom các thông số chỉnh được của bước 4-6 vào một chỗ.

    Đối tượng bất biến; giá trị sai miền bị từ chối ngay khi tạo. Mọi trường đều có mặc định
    dùng được cho chạy thật.

    Attributes:
        extract_attempts: Số lần gọi tối đa cho mỗi agent trích xuất trong một chủ đề. Lỗi mạng
            tạm thời đã được tầng kết nối LLM tự thử lại; đây là lượt thử lại ở tầng agent.
        verifier_max_tool_calls: Số lần Verifier được gọi công cụ tra cứu trước khi buộc phải
            kết luận; mỗi lượt xét của Verifier tốn tối đa giá trị này + 1 lời gọi LLM.
        search_top_k: Số lượt nói công cụ tìm kiếm của Verifier trả về mỗi lần.
        consensus_max_rounds: Số vòng tối đa Verifier gửi nhận xét lại cho agent trích xuất để hai
            bên đồng thuận. Hết vòng mà chưa đồng thuận: nếu Verifier vẫn muốn bỏ thì bỏ, còn lại giữ
            bản cuối của agent trích xuất. Mỗi vòng tốn tối đa ``verifier_max_tool_calls + 2`` lời
            gọi LLM.
        max_concurrency: Số tác vụ của luồng chạy được chạy song song mỗi nhịp, tức số chủ đề xử lý
            cùng lúc. Số lời gọi LLM đồng thời thực sự do bộ giới hạn chung quyết định, không phải
            giá trị này.
    """

    extract_attempts: int = 2
    verifier_max_tool_calls: int = 3
    search_top_k: int = 5
    consensus_max_rounds: int = 3
    max_concurrency: int = 16

    def __post_init__(self) -> None:
        """Kiểm tra mọi thông số nằm trong miền cho phép.

        Raises:
            ValueError: Khi một thông số nhỏ hơn giá trị tối thiểu (0 với số lần gọi công cụ,
                1 với các thông số còn lại).
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


__all__ = [
    "AnalysisConfig",
]
