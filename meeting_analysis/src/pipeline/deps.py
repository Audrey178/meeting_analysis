"""Những thứ bước 4-6 cần dùng nhưng không phải dữ liệu cuộc họp: các mô hình ngôn ngữ, cấu hình và
bộ phân loại câu nói.

Chúng được truyền vào mỗi lần chạy thay vì gắn cố định, nhờ vậy cùng một luồng xử lý dùng lại
được cho mọi cuộc họp.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..utils.ports import LLMAdapter
from .config import AnalysisConfig
from .shared.judges.progress_act import ProgressActJudge
from .shared.judges.turn_act import TurnActJudge


@dataclass(frozen=True)
class GraphDeps:
    """Gom các phụ thuộc dùng chung cho mọi bước nhỏ trong một lần chạy bước 4-6.

    Đối tượng này đi kèm lần chạy (không nằm trong dữ liệu cuộc họp), nên cùng một luồng chạy dùng
    lại được cho nhiều cuộc họp với các mô hình khác nhau.

    Attributes:
        content_llm: Mô hình cho agent tóm tắt ý thảo luận.
        action_llm: Mô hình cho agent trích việc giao và tiến độ; cũng dùng để trả lời nhận xét của
            Verifier về việc giao và tiến độ.
        decision_llm: Mô hình cho agent trích kết luận; cũng dùng để trả lời nhận xét của Verifier
            về kết luận.
        verifier_llm: Mô hình cho Verifier.
        config: Thông số chỉnh được của bước 4-6.
        turn_judge: Bộ phân loại lượt nói qua Decisions API. Ở bước 5 dùng để xét lượt chốt; ở bước 6
            dùng để đối chiếu kết luận, việc giao giữa các chủ đề và nhận ra chỉ đạo trong tiến độ.
            None thì mọi candidate có lượt chốt bị gắn UNCERTAIN và bước 6 chỉ gộp trùng theo chữ.
        progress_judge: Bộ phân loại lượt nêu trạng thái tiến độ qua Decisions API, chỉ dùng ở bước 5.
            None thì mọi cập nhật tiến độ đều bị gắn UNCERTAIN và gửi cho Verifier.

    Note:
        Các mô hình nên được bọc qua bộ giới hạn số lời gọi đồng thời trước khi đưa vào đây.
    """

    content_llm: LLMAdapter
    action_llm: LLMAdapter
    decision_llm: LLMAdapter
    verifier_llm: LLMAdapter
    config: AnalysisConfig = field(default_factory=AnalysisConfig)
    turn_judge: TurnActJudge | None = None
    progress_judge: ProgressActJudge | None = None


__all__ = [
    "GraphDeps",
]
