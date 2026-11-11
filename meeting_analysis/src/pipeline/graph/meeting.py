"""Luồng chạy của cả cuộc họp cho bước 4-6.

Đầu tiên dựng danh bạ người nói của cả cuộc họp, để các chủ đề sau đó có thể chạy độc lập. Tiếp
theo mọi chủ đề được xử lý cùng lúc, mỗi chủ đề theo luồng con riêng; tổng số lời gọi mô hình chạy
đồng thời vẫn bị giới hạn chung. Cuối cùng kết quả được sắp lại theo thứ tự chủ đề, gộp mục trùng
và tổng hợp thành báo cáo.

Có thể yêu cầu chỉ tính một phần kết quả (ví dụ chỉ phần kết luận) thay vì tất cả.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..deps import GraphDeps
from ..shared.transcript import get_turns_of_segment
from .nodes import finalize, build_registry
from .state import MeetingState
from .topic import build_topic_graph


def dispatch_topics(state: MeetingState) -> list[Send] | str:
    """Gửi mọi chủ đề vào luồng con cùng lúc, mỗi chủ đề một gói dữ liệu riêng.

    Mỗi gói mang theo lượt nói của riêng chủ đề, lượt nói của cả cuộc họp (để Verifier tra bằng
    chứng ở chủ đề khác), danh bạ người nói và nhãn của chủ đề.

    Args:
        state: Trạng thái cuộc họp sau khi đã dựng danh bạ người nói.

    Returns:
        Danh sách lệnh gửi, mỗi chủ đề một lệnh; hoặc tên bước tổng hợp nếu cuộc họp không có chủ
        đề nào, để luồng chạy vẫn đi tới báo cáo (rỗng).
    """

    if not state["segments"]:
        return "finalize"
    meeting_turns = tuple(state["turns_by_id"].values())
    return [
        Send(
            "topic",
            {
                "segment": segment,
                "turns": get_turns_of_segment(segment, state["turns_by_id"]),
                "meeting_turns": meeting_turns,
                "registry": state["registry"],
                "meeting_date": state.get("meeting_date"),
                "parts": state["parts"],
                "label": state["topic_labels"][segment.segment_id],
            },
        )
        for segment in state["segments"]
    ]


def build_meeting_graph(*, checkpointer=None):
    """Dựng và biên dịch luồng chạy bước 4-6 của cả cuộc họp.

    Thứ tự: dựng danh bạ người nói, chạy song song luồng con của mọi chủ đề, rồi tổng hợp báo cáo.
    Khi chạy, truyền ``GraphDeps`` qua tham số ``context`` của ``invoke``.

    Args:
        checkpointer: Bộ lưu trạng thái giữa chừng, tuỳ chọn; luồng chạy không dừng giữa chừng nên
            thường để None.

    Returns:
        Luồng chạy đã biên dịch, kết quả nằm ở khoá ``report`` của trạng thái đầu ra.
    """

    graph = StateGraph(MeetingState, context_schema=GraphDeps)
    graph.add_node("build_registry", build_registry)
    graph.add_node("topic", build_topic_graph())
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "build_registry")
    graph.add_conditional_edges("build_registry", dispatch_topics, ["topic", "finalize"])
    graph.add_edge("topic", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


__all__ = [
    "build_meeting_graph",
]
