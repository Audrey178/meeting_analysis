"""Luồng xử lý MỘT chủ đề (bước 4-5).

Ba agent đọc chủ đề cùng lúc: một agent tóm tắt ý thảo luận, một agent tìm kết luận, một agent tìm
việc được giao (và tiến độ các việc cũ nếu cuộc họp có danh sách việc cần báo cáo). Sau đó các mục
trích được đem kiểm: mục chắc chắn vào thẳng kết quả, mỗi mục còn nghi ngờ được gửi riêng cho agent
kiểm chứng.

Khi chỉ cần một phần kết quả, chỉ agent phụ trách phần đó được chạy.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..deps import GraphDeps
from ..shared.schemas import AGENT_OF_PART, ANALYSIS_PARTS
from .nodes import EXTRACTOR_NODES, evidence_check, prepare_topic, verifier
from .state import TopicInput, TopicOutput, TopicState


def _route_extractors(state: TopicState) -> list[str] | str:
    """Chọn các agent trích xuất cần chạy cho chủ đề, theo các phần kết quả được yêu cầu.

    Phần tiến độ chỉ được tính khi phiên họp có danh sách việc. Một agent phụ trách nhiều phần
    (Action agent lo cả việc giao lẫn tiến độ) vẫn chỉ chạy một lần.

    Args:
        state: Trạng thái chủ đề sau khi dựng gói dữ liệu.

    Returns:
        Danh sách tên agent cần chạy; hoặc ``END`` khi không có agent nào phải chạy, ví dụ chỉ yêu
        cầu tiến độ mà phiên họp không có danh sách việc.
    """

    has_agenda = bool(state["registry"].agenda.tasks)
    targets = [
        AGENT_OF_PART[part]
        for part in ANALYSIS_PARTS
        if part in state["parts"] and (part != "progress" or has_agenda)
    ]
    return list(dict.fromkeys(targets)) or END


def _route_verify(state: TopicState) -> list[Send] | str:
    """Gửi song song từng candidate UNCERTAIN cho Verifier, hoặc kết thúc luồng con.

    Khi không có gì để gửi phải trả ``END`` chứ không trả danh sách rỗng: danh sách rỗng khiến
    nhánh đó dừng im lặng mà không báo lỗi.

    Args:
        state: Trạng thái chủ đề sau bước gắn nhãn CLEAR/UNCERTAIN.

    Returns:
        Danh sách lệnh gửi, mỗi candidate một lệnh; hoặc ``END``.
    """

    tasks = state["pending_verify"]
    if not tasks:
        return END
    return [Send("verifier", task) for task in tasks]


def build_topic_graph():
    """Dựng và biên dịch luồng con xử lý một chủ đề.

    Thứ tự: dựng gói dữ liệu, chạy song song các agent trích xuất cần thiết, gắn nhãn CLEAR/UNCERTAIN,
    rồi gửi từng candidate UNCERTAIN cho Verifier. Luồng con nhận ``TopicInput``, trả ``TopicOutput``
    và dùng chung ``GraphDeps`` của luồng cha.

    Returns:
        Luồng con đã biên dịch.
    """

    graph = StateGraph(TopicState, context_schema=GraphDeps, input_schema=TopicInput, output_schema=TopicOutput)
    graph.add_node("prepare_topic", prepare_topic)
    for name, node in EXTRACTOR_NODES.items():
        graph.add_node(name, node)
    graph.add_node("evidence_check", evidence_check)
    graph.add_node("verifier", verifier)

    graph.add_edge(START, "prepare_topic")
    graph.add_conditional_edges("prepare_topic", _route_extractors, [*EXTRACTOR_NODES, END])
    for name in EXTRACTOR_NODES:
        graph.add_edge(name, "evidence_check")
    graph.add_conditional_edges("evidence_check", _route_verify, ["verifier", END])
    graph.add_edge("verifier", END)
    return graph.compile()


__all__ = [
    "build_topic_graph",
]
