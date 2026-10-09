"""Graph cha của pipeline agentic v3: Planner -> mọi chủ đề song song -> tổng hợp.

    START -> plan_meeting -> Send("topic", chủ đề i) cho MỌI i cùng lúc
                                     │  (subgraph ``topic.py``: nhãn -> trích xuất
                                     │   -> evidence-check -> Verifier ReAct <-> agent
                                     │   trích xuất tới khi đồng thuận)
                                     ▼
                                 finalize -> END

So với v1 (``src/agentic/graph.py``), thời gian không còn tăng theo số chủ đề: v1 chờ
chủ đề N xong hẳn (kể cả debate) mới gửi chủ đề N+1, chỉ để mang ``known_names`` sang
chủ đề sau. v3 thay ngữ cảnh đó bằng danh bạ người nói của cả cuộc họp do Planner
dựng trước (``nodes/planner.py``), nên các chủ đề độc lập với nhau. Số lời gọi LLM
đồng thời do ``LLMConcurrencyGate`` giới hạn (``infra/throttle.py``).

Không có bước duyệt người: candidate chưa chắc chắn được Verifier gửi feedback lại cho
agent trích xuất tới khi hai bên đồng thuận (``nodes/verifier.py``), nên graph chạy một mạch
từ START tới END.

``finalize`` sắp lại kết quả theo thứ tự chủ đề (các chủ đề cộng dồn theo thứ tự hoàn
thành, không xác định), quy actor về người nói thật trong danh bạ, rồi gộp mục trùng
giữa các chủ đề (thay cho việc v1 truyền ``known_assignments`` để agent tự tránh lặp).
"""

from __future__ import annotations

from dataclasses import replace

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ...agentic._shared import (
    get_turns_of_segment,
    match_claimed_name_to_real_speaker,
    merge_duplicate_assignments,
    merge_duplicate_decisions,
)
from ...utils.config import TopicLabelerConfig
from ...utils.ports import LLMAdapter, TopicLabelAdapter
from ..config import V3Config
from ..nodes.planner import plan_meeting
from ..schemas import MeetingReport, VerificationRecord
from .state import MeetingStateV3
from .topic import build_topic_graph


def make_plan_node(config: V3Config):
    """Tạo node ``plan_meeting`` (luật, 0 token).

    Đầu vào: config - cấu hình v3.
    Đầu ra: hàm node trả ``registry`` và ``plans``.
    """

    def plan_meeting_node(state: MeetingStateV3) -> dict:
        registry, plans = plan_meeting(
            state["segments"],
            state["turns_by_id"],
            skip_without_cues=config.skip_agents_without_cues,
            chair=state.get("chair"),
        )
        return {"registry": registry, "plans": plans}

    return plan_meeting_node


def dispatch_topics(state: MeetingStateV3) -> list[Send] | str:
    """Gửi MỌI chủ đề vào subgraph ``topic`` cùng lúc.

    Đầu vào: state - sau ``plan_meeting``.
    Đầu ra: list ``Send``, hoặc ``"finalize"`` nếu cuộc họp không có chủ đề nào.
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
                "plan": state["plans"][segment.segment_id],
                "meeting_date": state.get("meeting_date"),
            },
        )
        for segment in state["segments"]
    ]


def _normalize_actor(item, meeting_turns):
    """Quy actor về đúng tên người nói trong danh bạ nếu khớp DUY NHẤT một người.

    Actor không khớp (đơn vị, nhiều người, tên không phát biểu) được giữ nguyên.

    Đầu vào: item - ActionItemCandidate; meeting_turns - lượt nói cả cuộc họp.
    Đầu ra: ActionItemCandidate (có thể đã đổi actor).
    """

    if not item.actor:
        return item
    matched = match_claimed_name_to_real_speaker(item.actor, meeting_turns)
    if matched and matched != item.actor:
        return replace(item, actor=matched)
    return item


def finalize(state: MeetingStateV3) -> dict:
    """Sắp kết quả theo thứ tự chủ đề, quy actor, gộp mục trùng và đóng gói ``MeetingReport``.

    Đầu vào: state - sau khi mọi chủ đề xong.
    Đầu ra: dict ``{"report": MeetingReport}``.
    """

    order = {segment.segment_id: index for index, segment in enumerate(state["segments"])}

    def by_topic(items):
        return sorted(items, key=lambda item: order.get(item.segment_id, len(order)))

    meeting_turns = tuple(state["turns_by_id"].values())
    assignments = by_topic(_normalize_actor(item, meeting_turns) for item in state.get("verified_assignments", []))
    decisions = by_topic(state.get("verified_decisions", []))
    records: list[VerificationRecord] = state.get("verification_records", [])

    report = MeetingReport(
        labels=tuple(by_topic(state.get("labels", []))),
        meeting_development=tuple(by_topic(state.get("meeting_development", []))),
        assignments=tuple(merge_duplicate_assignments(assignments)),
        decisions=tuple(merge_duplicate_decisions(decisions)),
        verification_records=tuple(by_topic(records)),
        failures=tuple(by_topic(state.get("topic_failures", []))),
        skipped_agents=tuple(by_topic(state.get("skipped_agents", []))),
    )
    return {"report": report}


def build_graph_v3(
    content_llm: LLMAdapter,
    action_llm: LLMAdapter,
    decision_llm: LLMAdapter,
    verifier_llm: LLMAdapter,
    labeler: TopicLabelAdapter,
    labeler_config: TopicLabelerConfig,
    config: V3Config | None = None,
    *,
    checkpointer=None,
):
    """Dựng và biên dịch graph cha v3.

    Graph không phụ thuộc cuộc họp cụ thể (mọi dữ liệu nằm trong state), nên có thể
    dựng một lần và dùng cho nhiều cuộc họp/luồng (``thread_id``) khác nhau.

    Đầu vào:
        content_llm, action_llm, decision_llm, verifier_llm, labeler: adapter (nên đã qua
            ``LLMConcurrencyGate``).
        labeler_config: cấu hình stage07.
        config: cấu hình v3; None thì dùng mặc định.
        checkpointer: tuỳ chọn (graph không dừng giữa chừng nên không bắt buộc).
    Đầu ra: graph đã compile.
    """

    config = config or V3Config()
    topic_graph = build_topic_graph(
        content_llm, action_llm, decision_llm, verifier_llm, labeler, labeler_config, config
    )
    graph = StateGraph(MeetingStateV3)
    graph.add_node("plan_meeting", make_plan_node(config))
    graph.add_node("topic", topic_graph)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "plan_meeting")
    graph.add_conditional_edges("plan_meeting", dispatch_topics, ["topic", "finalize"])
    graph.add_edge("topic", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


__all__ = ["build_graph_v3", "finalize"]
