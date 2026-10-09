"""Subgraph xử lý MỘT chủ đề, từ gán nhãn đến kiểm chứng. Graph cha ``Send`` mọi chủ
đề vào subgraph này cùng lúc (xem ``graph.py``).

    START -> label_topic -> content_agent  ------------------\\
                         -> action_agent   (nếu plan cho phép) -> evidence_check
                         -> decision_agent (nếu plan cho phép) -/       │
                                                       (candidate UNCERTAIN, Send)
                                                                        ▼
                                                               verifier (0..N) -> END
                                                    (mỗi candidate: Verifier <-> agent trích
                                                     xuất trao đổi tới khi đồng thuận)

Gán nhãn nằm TRONG subgraph (không chạy hết stage07 trước như v1): chủ đề nào có nhãn
thì trích xuất ngay, không chờ nhãn của chủ đề chậm nhất.

Ba agent trích xuất dùng lại nguyên các node của v1 (cùng prompt, cùng luật làm sạch
output); ``previous_context`` của Action agent được thay bằng danh bạ người nói của cả
cuộc họp (``planner.format_registry_context``). Lỗi LLM được thử lại ngay trong chủ
đề (``extract_attempts``) thay vì đợi tới sau chủ đề cuối như v1.

Vì sao ba nhánh nối thẳng vào ``evidence_check`` (không dùng ``add_edge([...], ...)``
chờ đủ ba): số nhánh thay đổi theo ``TopicPlan``; mọi nhánh cách điểm phân nhánh
đúng một bước nên LangGraph ghi kết quả của chúng trong cùng một superstep và
``evidence_check`` chạy đúng một lần.
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ...agentic._shared import check_action_evidence, check_decision_evidence
from ...agentic.nodes import make_action_agent, make_content_agent, make_decision_agent
from ...agentic.schemas import SegmentTask
from ...stages.stage07_topic_labeling import label_topics
from ...utils.config import TopicLabelerConfig
from ...utils.ports import LLMAdapter, TopicLabelAdapter
from ..config import V3Config
from ..nodes.planner import format_registry_context
from ..schemas import SkippedAgent, VerifyTask
from .state import TopicInput, TopicOutput, TopicState
from ..nodes.verifier import make_verifier

# Tên node agent trích xuất -> (khoá kết quả của node v1, khoá trong TopicState).
_EXTRACTORS = {
    "content_agent": ("meeting_development", "meeting_development"),
    "action_agent": ("action_item_candidates_raw", "action_candidates_raw"),
    "decision_agent": ("decision_candidates_raw", "decision_candidates_raw"),
}


def _wrap_extractor(
    name: str, agent: Callable[[SegmentTask], dict], attempts: int
) -> Callable[[TopicState], dict]:
    """Bọc một node trích xuất của v1 thành node của subgraph, kèm thử lại tại chỗ.

    Node v1 trả kết quả rỗng + ``TopicFailure`` khi LLM lỗi (không raise); wrapper gọi
    lại tối đa ``attempts`` lần và chỉ ghi lỗi của lần cuối.

    Đầu vào: name - tên node; agent - node v1; attempts - số lần gọi tối đa.
    Đầu ra: hàm node đọc ``task`` trong TopicState.
    """

    source_key, target_key = _EXTRACTORS[name]

    def extractor(state: TopicState) -> dict:
        result: dict = {}
        for _ in range(attempts):
            result = agent(state["task"])
            if not result.get("topic_failures"):
                break
        update: dict = {target_key: list(result.get(source_key, []))}
        failures = result.get("topic_failures", ())
        if failures:
            update["topic_failures"] = list(failures)
        return update

    extractor.__name__ = name
    return extractor


def _make_label_node(labeler: TopicLabelAdapter, labeler_config: TopicLabelerConfig):
    """Tạo node ``label_topic``: gán nhãn chủ đề (stage07, có guard + fallback) và dựng ``task``.

    Đầu vào: labeler - adapter gán nhãn; labeler_config - cấu hình stage07.
    Đầu ra: hàm node.
    """

    def label_topic(state: TopicState) -> dict:
        segment = state["segment"]
        plan = state["plan"]
        (label,) = label_topics((segment,), config=labeler_config, adapter=labeler)
        task: SegmentTask = {
            "segment_id": segment.segment_id,
            "title": label.title,
            "summary": label.summary,
            "turns": state["turns"],
            "previous_context": format_registry_context(state["registry"]),
            "meeting_date": state.get("meeting_date"),
        }
        skipped = [
            SkippedAgent(segment.segment_id, agent)
            for agent, run in (("action_agent", plan.run_action), ("decision_agent", plan.run_decision))
            if not run
        ]
        return {"labels": [label], "task": task, "skipped_agents": skipped}

    return label_topic


def _route_extractors(state: TopicState) -> list[str]:
    """Chọn các agent trích xuất cần chạy cho chủ đề theo ``TopicPlan``.

    Đầu vào: state - sau ``label_topic``.
    Đầu ra: list tên node (luôn có ``content_agent``).
    """

    plan = state["plan"]
    targets = ["content_agent"]
    if plan.run_action:
        targets.append("action_agent")
    if plan.run_decision:
        targets.append("decision_agent")
    return targets


def evidence_check(state: TopicState) -> dict:
    """Tách candidate thô của chủ đề thành CLEAR (vào kết quả) / UNCERTAIN (đi Verifier).

    Luật của v1 (0 token); tên đã biết lấy từ danh bạ cả cuộc họp thay vì ngữ cảnh
    chạy dồn.

    Đầu vào: state - sau khi các agent trích xuất của chủ đề đã xong.
    Đầu ra: dict cập nhật ``verified_*`` (phần CLEAR) và ``pending_verify`` (ghi đè).
    """

    segment_id = state["segment"].segment_id
    turns = state["turns"]
    known_names = state["registry"].names
    clear_actions, clear_decisions, pending = [], [], []

    def _verify_task(kind: str, index: int, item, reasons) -> VerifyTask:
        return {
            "item_key": f"{segment_id}:{kind}:{index}",
            "segment_id": segment_id,
            "kind": kind,
            "candidate": item,
            "reasons": reasons,
            "turns": turns,
            "meeting_turns": state["meeting_turns"],
            "registry": state["registry"],
        }

    for index, item in enumerate(state.get("action_candidates_raw", [])):
        flag = check_action_evidence(item, turns, known_names)
        if flag.verdict == "clear":
            clear_actions.append(item)
        else:
            pending.append(_verify_task("action", index, item, flag.reasons))
    for index, item in enumerate(state.get("decision_candidates_raw", [])):
        flag = check_decision_evidence(item, turns)
        if flag.verdict == "clear":
            clear_decisions.append(item)
        else:
            pending.append(_verify_task("decision", index, item, flag.reasons))
    return {
        "verified_assignments": clear_actions,
        "verified_decisions": clear_decisions,
        "pending_verify": tuple(pending),
    }


def _route_verify(state: TopicState) -> list[Send] | str:
    """Gửi từng candidate UNCERTAIN cho Verifier (song song), hoặc kết thúc subgraph.

    Trả TÊN node (``END``) khi không có gì để gửi, không trả ``[]`` (xem ``src/agentic/graph.py``).

    Đầu vào: state - sau ``evidence_check``.
    Đầu ra: list ``Send`` hoặc ``END``.
    """

    tasks = state["pending_verify"]
    if not tasks:
        return END
    return [Send("verifier", task) for task in tasks]


def build_topic_graph(
    content_llm: LLMAdapter,
    action_llm: LLMAdapter,
    decision_llm: LLMAdapter,
    verifier_llm: LLMAdapter,
    labeler: TopicLabelAdapter,
    labeler_config: TopicLabelerConfig,
    config: V3Config,
):
    """Dựng và biên dịch subgraph một chủ đề.

    Các adapter nên đã đi qua ``LLMConcurrencyGate`` (graph này không tự giới hạn).

    Đầu vào: bốn LLM (content/action/decision/verifier), adapter gán nhãn, cấu hình
        stage07 và cấu hình v3.
    Đầu ra: subgraph đã compile; đầu vào ``TopicInput``, đầu ra ``TopicOutput``.
    """

    attempts = config.extract_attempts
    graph = StateGraph(TopicState, input_schema=TopicInput, output_schema=TopicOutput)
    graph.add_node("label_topic", _make_label_node(labeler, labeler_config))
    graph.add_node("content_agent", _wrap_extractor("content_agent", make_content_agent(content_llm), attempts))
    graph.add_node("action_agent", _wrap_extractor("action_agent", make_action_agent(action_llm), attempts))
    graph.add_node("decision_agent", _wrap_extractor("decision_agent", make_decision_agent(decision_llm), attempts))
    graph.add_node("evidence_check", evidence_check)
    proposer_llms = {"action": action_llm, "decision": decision_llm}
    graph.add_node("verifier", make_verifier(verifier_llm, proposer_llms, config))

    graph.add_edge(START, "label_topic")
    graph.add_conditional_edges(
        "label_topic", _route_extractors, ["content_agent", "action_agent", "decision_agent"]
    )
    for name in _EXTRACTORS:
        graph.add_edge(name, "evidence_check")
    graph.add_conditional_edges("evidence_check", _route_verify, ["verifier", END])
    graph.add_edge("verifier", END)
    return graph.compile()


__all__ = ["build_topic_graph", "evidence_check"]
