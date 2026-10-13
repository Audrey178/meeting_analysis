"""Subgraph xử lý MỘT chủ đề, từ gán nhãn đến kiểm chứng. Graph cha ``Send`` mọi chủ
đề vào subgraph này cùng lúc (xem ``meeting.py``).

    START -> label_topic -> content_agent  -----------------------------\\
                         -> action_agent   ------------------------------> evidence_check
                         -> decision_agent -----------------------------/       │
                         -> progress_agent (nếu có danh sách việc) ----/        │
                                                              (candidate UNCERTAIN, Send)
                                                                                ▼
                                                                       verifier (0..N) -> END
                                                            (mỗi candidate: Verifier <-> agent
                                                             trích xuất trao đổi tới khi đồng thuận)

Gán nhãn nằm TRONG subgraph (không chạy hết stage07 trước như v1): chủ đề nào có nhãn
thì trích xuất ngay, không chờ nhãn của chủ đề chậm nhất.

Không có bước bỏ Action/Decision agent ở chủ đề "không có lượt chốt": hỏi Decisions từng lượt
với ngưỡng đủ an toàn thì không bỏ được chủ đề nào trên eval/synthetic (0/28 chủ đề âm, 225
lời gọi Decisions cho 30 cuộc họp), xem ``experiments/010_planner_segment``.

Ba agent trích xuất dùng lại các node của v1 (cùng luật làm sạch output) nhưng chạy
với prompt của v3 và dòng người chủ trì (``nodes/extractors.py``); ``previous_context``
của Action agent được thay bằng danh bạ người nói của cả cuộc họp
(``planner.format_registry_context``). Lỗi LLM được thử lại ngay trong chủ đề
(``extract_attempts``) thay vì đợi tới sau chủ đề cuối như v1.

Agent tiến độ (``nodes/progress.py``) chỉ chạy khi phiên họp có danh sách việc cần báo
cáo; cập nhật của nó được kiểm bằng Decisions trong ``evidence_check`` và không đi Verifier.

Mỗi agent trích xuất sinh đúng một phần kết quả (``AGENT_OF_PART``), nên ``parts`` của
``TopicInput`` chọn agent nào được chạy: tầng dịch vụ tính lại riêng một phần (vd. chỉ Giao
việc) mà không đụng tới phần khác. Khi đó nhãn chủ đề được nạp sẵn (``preset_label``) để mọi
phần dùng chung một nhãn: nhãn nằm trong prompt của cả bốn agent, và giao diện gắn mọi mục vào
chủ đề theo nhãn đó.

Vì sao các nhánh nối thẳng vào ``evidence_check`` (không dùng ``add_edge([...], ...)``
chờ đủ ba): số nhánh thay đổi theo ``parts`` và danh sách việc; mọi nhánh cách điểm phân nhánh
đúng một bước nên LangGraph ghi kết quả của chúng trong cùng một superstep và
``evidence_check`` chạy đúng một lần.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import partial

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..core._shared import check_action_evidence, check_decision_evidence
from ..core.schemas import SegmentTask
from ..core.turn_act import TurnActJudge
from ...stages.stage07_topic_labeling import label_topics
from ...utils.config import TopicLabelerConfig
from ...utils.ports import LLMAdapter, TopicLabelAdapter
from ..actors.resolution import list_known_actor_names, resolve_actor, split_item_mentions
from ..config import V3Config
from ..nodes.extractors import make_extractor
from ..nodes.planner import format_registry_context
from ..nodes.progress import check_progress_updates, make_progress_agent
from ..nodes.progress_act import ProgressActJudge
from ..nodes.verifier import make_verifier
from ..schemas import AGENT_OF_PART, ANALYSIS_PARTS, SpeakerRegistry, VerifyTask
from .state import TopicInput, TopicOutput, TopicState

# Tên node agent trích xuất -> (khoá kết quả của node v1, khoá trong TopicState).
_EXTRACTORS = {
    "content_agent": ("meeting_development", "meeting_development"),
    "action_agent": ("action_item_candidates_raw", "action_candidates_raw"),
    "decision_agent": ("decision_candidates_raw", "decision_candidates_raw"),
    "progress_agent": ("progress_updates_raw", "progress_updates_raw"),
}


def _wrap_extractor(
    name: str, agent: Callable[[SegmentTask, SpeakerRegistry], dict], attempts: int
) -> Callable[[TopicState], dict]:
    """Bọc một agent trích xuất thành node của subgraph, kèm thử lại tại chỗ.


    Đầu vào: name - tên node; agent - ``extractors.make_extractor`` (hoặc
        ``progress.make_progress_agent``); attempts - số lần gọi tối đa.
    Đầu ra: hàm node đọc ``task`` trong TopicState.
    """

    source_key, target_key = _EXTRACTORS[name]

    def extractor(state: TopicState) -> dict:
        result: dict = {}
        for _ in range(attempts):
            result = agent(state["task"], state["registry"])
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

    Chủ đề đã có nhãn nạp sẵn (``preset_label``) thì dùng lại, không gọi LLM.

    Đầu vào: labeler - adapter gán nhãn; labeler_config - cấu hình stage07.
    Đầu ra: hàm node.
    """

    def label_topic(state: TopicState) -> dict:
        segment = state["segment"]
        label = state["preset_label"]
        if label is None:
            (label,) = label_topics((segment,), config=labeler_config, adapter=labeler)
        task: SegmentTask = {
            "segment_id": segment.segment_id,
            "title": label.title,
            "summary": label.summary,
            "turns": state["turns"],
            "previous_context": format_registry_context(state["registry"]),
            "meeting_date": state.get("meeting_date"),
        }
        return {"labels": [label], "task": task}

    return label_topic


def _route_extractors(state: TopicState) -> list[str] | str:
    """Chọn các agent trích xuất cần chạy cho chủ đề theo ``parts``.

    Agent tiến độ chỉ chạy khi phiên họp có danh sách việc cần báo cáo; các agent khác chạy khi
    phần của chúng nằm trong ``parts``.

    Đầu vào: state - sau ``label_topic``.
    Đầu ra: list tên node, hoặc ``END`` khi chủ đề không có agent nào phải chạy (vd. chỉ tính
        Tiến độ mà phiên họp không có danh sách việc).
    """

    has_agenda = bool(state["registry"].agenda.tasks)
    targets = [
        AGENT_OF_PART[part]
        for part in ANALYSIS_PARTS
        if part in state["parts"] and (part != "progress" or has_agenda)
    ]
    return targets or END


def _ambiguous_actor_reasons(item, state: TopicState) -> list[str]:
    """Lý do gửi Verifier cho từng bên nhận việc khớp >= 2 ứng viên mà không ai đủ rõ.

    Vd. "Sơn" khi cuộc họp có Phạm Hồng Sơn và Lê Văn Sơn: Verifier phải chọn và nêu
    lý do. Bên không có ứng viên nào thì KHÔNG gửi (``finalize`` gắn cờ ``unknown``).

    Đầu vào: item - ActionItemCandidate; state - state của chủ đề.
    Đầu ra: list lý do (rỗng nếu không bên nào mơ hồ).
    """

    resolved = resolve_actor(item, state["registry"], state["meeting_turns"])
    reasons = []
    for assignee in resolved.assignees:
        if assignee.flag and len(assignee.candidates) >= 2:
            names = ", ".join(f"{c.name} ({c.score:.2f})" for c in assignee.candidates)
            reasons.append(
                f"Actor '{assignee.mention}' mơ hồ, có thể là: {names}. Cần chọn đúng một ứng viên kèm lý do."
            )
    return reasons


def _strip_actor_roles(item, state: TopicState):
    """Bỏ từ chỉ vai trò ("chủ trì", "phối hợp với") khỏi actor trước khi kiểm căn cứ của v1.

    Luật v1 đòi mỗi phần của actor xuất hiện trong bản ghi/danh bạ; "phối hợp Sở Xây
    dựng" không xuất hiện nguyên cụm nên sẽ bị gắn cờ nhầm.

    Đầu vào: item - ActionItemCandidate; state - state của chủ đề.
    Đầu ra: candidate với actor là các bên nối bằng ", " (không đổi nếu không có actor).
    """

    mentions = split_item_mentions(item, state["registry"])
    if not mentions:
        return item
    return replace(item, actor=", ".join(mention.text for mention in mentions))


_EVIDENCE_CHECK_OFF = "evidence-check tắt (ablation): chưa kiểm căn cứ bằng luật."


def evidence_check(
    state: TopicState,
    turn_judge: TurnActJudge | None = None,
    progress_judge: ProgressActJudge | None = None,
    v3_config: V3Config | None = None,
) -> dict:
    """Tách candidate thô của chủ đề thành CLEAR (vào kết quả) / UNCERTAIN (đi Verifier).

    Luật của v1 (0 token); tên đã biết lấy từ danh bạ cả cuộc họp thay vì ngữ cảnh
    chạy dồn, cộng người và đơn vị trong danh sách tham dự (để "giao Sở Tài chính"
    không bị coi là actor không có căn cứ). Việc mà luật v1 coi là CLEAR nhưng actor
    mơ hồ giữa nhiều ứng viên vẫn đi Verifier. Có ``turn_judge`` thì lượt chốt được
    xét theo nghĩa thay cho từ khoá (xem ``core/turn_act.py``). Cập nhật tiến độ được
    kiểm bằng ``progress_judge`` trên lượt nêu trạng thái (``nodes/progress.py``), không
    đi Verifier.

    Hai núm ablation của ``V3Config`` (production để mặc định): ``evidence_check=False`` coi mọi
    candidate là UNCERTAIN; ``verifier_mode`` khác ``"on"`` thì giữ hết/bỏ hết candidate UNCERTAIN
    ngay tại đây thay vì gửi Verifier.

    Đầu vào: state - sau khi các agent trích xuất của chủ đề đã xong;
        turn_judge - bộ phân loại lượt chốt (tuỳ chọn);
        progress_judge - bộ phân loại lượt nêu trạng thái tiến độ (tuỳ chọn);
        v3_config - cấu hình v3 (None thì mặc định). Không đặt tên ``config``: LangGraph dành tên
            đó cho ``RunnableConfig`` của node.
    Đầu ra: dict cập nhật ``verified_*`` (phần CLEAR), ``progress_updates`` và
        ``pending_verify`` (ghi đè).
    """

    segment_id = state["segment"].segment_id
    turns = state["turns"]
    known_names = list_known_actor_names(state["registry"])
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

    config = v3_config or V3Config()
    for index, item in enumerate(state.get("action_candidates_raw", [])):
        if not config.evidence_check:
            pending.append(_verify_task("action", index, item, (_EVIDENCE_CHECK_OFF,)))
            continue
        flag = check_action_evidence(_strip_actor_roles(item, state), turns, known_names, turn_judge)
        ambiguity = _ambiguous_actor_reasons(item, state)
        reasons = [*flag.reasons, *ambiguity]
        if flag.verdict == "clear" and not ambiguity:
            clear_actions.append(item)
        else:
            pending.append(_verify_task("action", index, item, tuple(reasons)))
    for index, item in enumerate(state.get("decision_candidates_raw", [])):
        if not config.evidence_check:
            pending.append(_verify_task("decision", index, item, (_EVIDENCE_CHECK_OFF,)))
            continue
        flag = check_decision_evidence(item, turns, turn_judge)
        if flag.verdict == "clear":
            clear_decisions.append(item)
        else:
            pending.append(_verify_task("decision", index, item, flag.reasons))
    progress_updates = check_progress_updates(
        state.get("progress_updates_raw", []), turns, state["registry"].agenda, progress_judge, turn_judge
    )
    if config.verifier_mode == "keep_uncertain":
        clear_actions += [task["candidate"] for task in pending if task["kind"] == "action"]
        clear_decisions += [task["candidate"] for task in pending if task["kind"] == "decision"]
    if config.verifier_mode != "on":
        pending = []
    return {
        "verified_assignments": clear_actions,
        "verified_decisions": clear_decisions,
        "progress_updates": progress_updates,
        "pending_verify": tuple(pending),
    }


def _route_verify(state: TopicState) -> list[Send] | str:
    """Gửi từng candidate UNCERTAIN cho Verifier (song song), hoặc kết thúc subgraph.

    Trả TÊN node (``END``) khi không có gì để gửi, không trả ``[]``: đã kiểm chứng ở v1 rằng
    hàm cạnh có điều kiện trả ``[]`` làm nhánh đó chết im lặng (node đích không bao giờ chạy).

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
    turn_judge: TurnActJudge | None = None,
    *,
    progress_llm: LLMAdapter | None = None,
    progress_judge: ProgressActJudge | None = None,
):
    """Dựng và biên dịch subgraph một chủ đề.

    Các adapter nên đã đi qua ``LLMConcurrencyGate`` (graph này không tự giới hạn).

    Đầu vào: bốn LLM (content/action/decision/verifier), adapter gán nhãn, cấu hình
        stage07, cấu hình v3 và bộ phân loại lượt chốt (cho evidence-check, None thì dùng luật từ
        khoá);
        progress_llm - LLM của agent tiến độ (None thì dùng ``action_llm``);
        progress_judge - Decisions cho lượt nêu trạng thái (None thì không kiểm).
    Đầu ra: subgraph đã compile; đầu vào ``TopicInput``, đầu ra ``TopicOutput``.
    """

    attempts = config.extract_attempts
    graph = StateGraph(TopicState, input_schema=TopicInput, output_schema=TopicOutput)
    graph.add_node("label_topic", _make_label_node(labeler, labeler_config))
    for name, llm in (("content_agent", content_llm), ("action_agent", action_llm), ("decision_agent", decision_llm)):
        graph.add_node(name, _wrap_extractor(name, make_extractor(name, llm), attempts))
    graph.add_node(
        "progress_agent", _wrap_extractor("progress_agent", make_progress_agent(progress_llm or action_llm), attempts)
    )
    graph.add_node(
        "evidence_check", partial(evidence_check, turn_judge=turn_judge, progress_judge=progress_judge, v3_config=config)
    )
    proposer_llms = {"action": action_llm, "decision": decision_llm}
    graph.add_node("verifier", make_verifier(verifier_llm, proposer_llms, config))

    graph.add_edge(START, "label_topic")
    graph.add_conditional_edges("label_topic", _route_extractors, [*_EXTRACTORS, END])
    for name in _EXTRACTORS:
        graph.add_edge(name, "evidence_check")
    graph.add_conditional_edges("evidence_check", _route_verify, ["verifier", END])
    graph.add_edge("verifier", END)
    return graph.compile()


__all__ = ["build_topic_graph", "evidence_check"]
