"""Điều phối LangGraph cho các agent phía sau: Content / Action / Decision /
Evidence-Check / Debate+Judge -- xem thêm ``be/DESIGN.md``.

Hình dạng graph: các chủ đề được xử lý TUẦN TỰ, từng chủ đề một. Chủ đề N+1
chỉ được gửi đi sau khi BA nhánh của chủ đề N (Content, Action, Decision)
đều xong VÀ mọi candidate uncertain của chủ đề N đã qua Debate+Judge. Trong
một chủ đề, ba nhánh trích xuất chạy song song với nhau; Evidence-Check
(luật) tách candidate CLEAR/UNCERTAIN; chỉ candidate UNCERTAIN mới đi qua
Debate+Judge (LLM, có thể 0 lần nếu chủ đề không có gì đáng nghi). Sau chủ
đề cuối, cả cuộc họp chỉ còn một việc: thử lại chủ đề lỗi (nếu có), rồi KẾT
THÚC -- không có node "dựng báo cáo" nào nữa (xem "M6" trong ``be/DESIGN.md``
cho lý do bỏ ``group_task_assignments``/``conclusion_agent``/
``assemble_report_structure`` của bản trước).

    START/advance_topic --gửi chủ đề i--> content_agent   ---\\
                                       \\-> action_agent    ---\\-> check_topic_evidence
                                       \\-> decision_agent  ---/        │
                                                          (candidate UNCERTAIN)
                                                                        ▼
                                                          debate_and_judge_agent (0..N lần)
                                                                        │
                                                                        ▼
                                                                 advance_topic
                                              lặp sang chủ đề i+1, hoặc
                                              retry_failed_topics -> END

``MeetingState`` cuối cùng (``graph.invoke()``'s return value) CHÍNH LÀ kết
quả: ``meeting_development``/``verified_assignments``/``verified_decisions``
là đúng ba ô output của sơ đồ gốc (Diễn biến họp / Giao việc / Kết luận
họp). Người gọi đọc thẳng ba trường này; việc gộp theo người phụ trách hay
viết đoạn văn kết luận hành chính (nếu một định dạng hiển thị cụ thể cần)
là việc của tầng trình bày bên ngoài graph, không phải của agent pipeline.

Vì sao tuần tự giữa các chủ đề: mỗi chủ đề mang theo bản tóm tắt ngắn
``known_names``/``known_assignments`` (xem ``state.py``) để chủ đề SAU quy được
các cách xưng hô "em"/"anh"/"bọn em" về tên thật đã biết ở chủ đề TRƯỚC. Chạy
song song mọi chủ đề thì không làm được điều này. Ngữ cảnh này được dựng từ
candidate ĐÃ KIỂM CHỨNG (sau Evidence-Check/Debate), không phải candidate
thô, đổi lại thời gian chạy tăng theo số chủ đề VÀ số candidate uncertain
mỗi chủ đề.

Vì sao ``advance_topic``/``check_topic_evidence`` là node thường có nhiều
cạnh đi vào: các nhánh cách điểm gửi đúng MỘT bước, nên LangGraph
(Pregel/BSP) ghi kết quả của chúng trong CÙNG một superstep và node đích
chạy đúng một lần mỗi chủ đề (hoặc mỗi candidate, với debate). Mỗi node vẫn
kiểm tra lại bằng các dấu hoàn thành tương ứng (không suy từ việc danh sách
kết quả có thêm phần tử, vì một chủ đề/candidate có thể hợp lệ mà cho ra 0
kết quả) như một lớp bảo vệ phụ.

Chủ đề lỗi: nếu lời gọi LLM của một agent trích xuất (content/action/decision)
bỏ cuộc (sau khi adapter tự retry), agent trả kết quả rỗng kèm ``TopicFailure``;
vòng lặp đi tiếp, và ``retry_failed_topics`` chạy lại đúng các lời gọi đó MỘT
lần sau chủ đề cuối (lúc đó gateway thường đã phục hồi), rồi áp evidence-check
bằng luật cho candidate phục hồi được (KHÔNG chạy debate cho chúng -- giới
hạn đã biết, xem ``nodes/debate_judge_agent.py``). Phần vẫn lỗi được báo
trong ``unrecovered_failures`` thay vì biến mất vào một dòng log.

Debate/Judge lỗi LLM: KHÔNG có lượt retry riêng, giữ candidate theo luật an
toàn (xem ``nodes/debate_judge_agent.py``), không nằm trong ``topic_failures``.

Chi phí: ``3N + 3M`` lời gọi LLM mỗi cuộc họp (N = số chủ đề, M = số
candidate bị Evidence-Check gắn cờ uncertain): Content/Action/Decision cho
mỗi chủ đề (3N), Debate(Agent A+B)+Judge cho mỗi candidate uncertain (3M).
Evidence-Check là luật, 0 token. Không còn lời gọi Conclusion (bỏ ở M6).

Các node gọi ``LLMAdapter.generate_json`` (giao thức nhỏ mà stage07/08 cũng
dùng, ``src/utils/ports.py``), nên đổi adapter cụ thể (OpenAI, Claude...) không
phải sửa file này.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ._shared import (
    check_action_evidence,
    check_decision_evidence,
    collect_names_and_assignments_of_topic,
    format_previous_context,
    get_turns_of_segment,
)
from ..utils.contracts import TopicSegment
from ..utils.ports import LLMAdapter
from .nodes import (
    check_topic_evidence,
    make_action_agent,
    make_content_agent,
    make_debate_and_judge_agent,
    make_decision_agent,
)
from .state import MeetingState
from .schemas import SegmentTask, TopicFailure

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Các bước dùng luật (0 token)
# ---------------------------------------------------------------------------


def _build_segment_task(segment: TopicSegment, state: MeetingState, previous_context: str) -> SegmentTask:
    """Đóng gói dữ liệu của MỘT đoạn chủ đề thành ``SegmentTask`` để gửi cho agent.

    Đầu vào:
        segment: đoạn chủ đề cần xử lý.
        state: trạng thái graph (lấy nhãn chủ đề và bảng lượt nói).
        previous_context: khối văn bản tóm tắt ngữ cảnh từ các chủ đề trước.

    Đầu ra: SegmentTask; đoạn chưa có nhãn thì title/summary là chuỗi rỗng.
    """

    label = state["labels_by_segment"].get(segment.segment_id)
    return {
        "segment_id": segment.segment_id,
        "title": label.title if label else "",
        "summary": label.summary if label else "",
        "turns": get_turns_of_segment(segment, state["turns_by_id"]),
        "previous_context": previous_context,
        "meeting_date": state.get("meeting_date"),
    }


def _dispatch_current_topic_to_agents(state: MeetingState) -> str | list[Send]:
    """Quyết định bước kế tiếp của graph: gửi chủ đề hiện tại cho ba agent, hoặc sang bước thử lại.

    Chỉ gửi ĐÚNG MỘT chủ đề tại ``state["segments"][state["next_segment_index"]]``
    mỗi lần (lý do xem docstring module).

    Khi mọi chủ đề đã xong, trả về TÊN NODE dạng chuỗi ``"retry_failed_topics"``
    chứ KHÔNG trả ``[]``. Đã kiểm chứng: hàm cạnh có điều kiện mà trả ``[]`` sẽ
    làm nhánh đó chết im lặng (node đích không bao giờ được gọi), còn trả tên
    node thì đi đúng và node nhận được toàn bộ ``MeetingState``.

    Đầu vào: state - trạng thái graph hiện tại.
    Đầu ra: list gồm ba ``Send`` (content_agent, action_agent, decision_agent)
        cho chủ đề hiện tại, hoặc chuỗi ``"retry_failed_topics"`` khi đã hết chủ đề.
    """

    index = state["next_segment_index"]
    if index >= len(state["segments"]):
        return "retry_failed_topics"
    previous_context = format_previous_context(state["known_names"], state["known_assignments"])
    task = _build_segment_task(state["segments"][index], state, previous_context)
    return [
        Send("content_agent", task),
        Send("action_agent", task),
        Send("decision_agent", task),
    ]


def _dispatch_debate_or_advance(state: MeetingState) -> str | list[Send]:
    """Cạnh có điều kiện sau ``check_topic_evidence``: gửi từng candidate
    UNCERTAIN của chủ đề hiện tại cho ``debate_and_judge_agent``, hoặc đi
    thẳng tới ``advance_topic`` nếu chủ đề này không có candidate nào uncertain.

    Cùng lưu ý như ``_dispatch_current_topic_to_agents``: trả TÊN NODE dạng
    chuỗi khi không có gì để gửi, không trả ``[]`` (xem docstring module).

    Đầu vào: state - trạng thái graph ngay sau ``check_topic_evidence``.
    Đầu ra: list ``Send`` (một phần tử mỗi candidate uncertain), hoặc chuỗi
        ``"advance_topic"``.
    """

    tasks = state["pending_debate_tasks"]
    if not tasks:
        return "advance_topic"
    return [Send("debate_and_judge_agent", task) for task in tasks]


def advance_topic(state: MeetingState) -> dict:
    """Node hội tụ (fan-in) sau khi chủ đề hiện tại đã được kiểm chứng đầy đủ, rồi chuyển sang chủ đề kế.

    Chức năng: tăng ``next_segment_index`` và gộp tên/việc giao ĐÃ KIỂM CHỨNG
    của chủ đề vừa xong vào ngữ cảnh chạy dồn giữa các chủ đề, CHỈ KHI:
    (1) cả ba dấu hoàn thành (``completed_content_topics``/
    ``completed_action_topics``/``completed_decision_topics``) đều đã chứa
    segment_id của chủ đề này, VÀ (2) mọi candidate uncertain mà
    ``check_topic_evidence`` vừa gửi đi debate (``pending_debate_tasks``) đều
    đã có mặt trong ``completed_debate_items``. Nếu chưa thì không làm gì
    (lớp bảo vệ phụ; bình thường điều kiện này luôn đúng khi node chạy).

    Lưu ý: trả ``{}`` nghĩa là ``next_segment_index`` không tăng, nên cạnh có
    điều kiện phía sau sẽ gửi lại đúng chủ đề đó. Nếu điều kiện chưa đủ xảy ra
    thật, graph sẽ lặp đến khi chạm giới hạn đệ quy của LangGraph.

    Đầu vào: state - trạng thái graph sau khi chủ đề hiện tại đã qua đủ
        Content/Action/Decision + Evidence-Check (+ Debate/Judge nếu có).
    Đầu ra: dict cập nhật ``next_segment_index``, ``known_names``,
        ``known_assignments``; hoặc ``{}`` nếu chưa đủ điều kiện/đã hết chủ đề.
    """

    index = state["next_segment_index"]
    if index >= len(state["segments"]):
        return {}
    segment_id = state["segments"][index].segment_id
    if (
        segment_id not in state["completed_content_topics"]
        or segment_id not in state["completed_action_topics"]
        or segment_id not in state["completed_decision_topics"]
    ):
        return {}
    expected_debate_keys = {task["item_key"] for task in state["pending_debate_tasks"]}
    if not expected_debate_keys.issubset(set(state["completed_debate_items"])):
        return {}

    this_topic_sections = tuple(
        s for s in state["meeting_development"] if s.segment_id == segment_id
    )
    this_topic_items = tuple(
        a for a in state["verified_assignments"] if a.segment_id == segment_id
    )
    new_names, new_assignments = collect_names_and_assignments_of_topic(
        this_topic_sections, this_topic_items
    )
    known_names = state["known_names"] + tuple(
        name for name in new_names if name not in state["known_names"]
    )
    known_assignments = state["known_assignments"] + new_assignments

    return {
        "next_segment_index": index + 1,
        "known_names": known_names,
        "known_assignments": known_assignments,
    }


_RETRIED_RAW_KEY_BY_AGENT = {
    "content_agent": "meeting_development",
    "action_agent": "action_item_candidates_raw",
    "decision_agent": "decision_candidates_raw",
}
_VERIFIED_KEY_BY_AGENT = {
    "action_agent": "verified_assignments",
    "decision_agent": "verified_decisions",
}


def make_retry_failed_topics(agents: dict[str, Callable[[SegmentTask], dict]]):
    """Tạo node ``retry_failed_topics``: chạy lại MỘT lần các lời gọi agent đã lỗi.

    Đầu vào: agents - bảng tên node agent trích xuất
        (content_agent/action_agent/decision_agent) -> hàm agent, để chạy lại
        đúng agent đã lỗi.
    Đầu ra: hàm node ``retry_failed_topics(state)``.
    """

    def retry_failed_topics(state: MeetingState) -> dict:
        """Chạy lại các chủ đề lỗi ở vòng chính (sau chủ đề cuối) -- node CUỐI
        CÙNG của graph (nối thẳng ``END``, xem ``build_graph``).

        Kết quả retry thành công được cộng vào các danh sách kết quả ĐÃ KIỂM
        CHỨNG trực tiếp: candidate action/decision phục hồi được vẫn qua
        evidence-check bằng luật (``check_action_evidence``/
        ``check_decision_evidence``) trước khi được thêm vào, nhưng KHÔNG
        qua debate+judge nếu bị gắn cờ uncertain -- chấp nhận giữ nguyên
        (không có gì phản biện) thay vì thêm một vòng Send debate nữa ở đây
        (giới hạn đã biết, xem ``nodes/debate_judge_agent.py``). Agent nào
        lỗi lần nữa (hoặc không tìm được đoạn/agent tương ứng) được ghi vào
        ``unrecovered_failures`` để người gọi báo ra.

        Lưu ý: ngữ cảnh ``previous_context`` khi retry được dựng từ trạng thái
        CUỐI của cả cuộc họp, nên đã chứa tên/việc của cả các chủ đề đứng SAU chủ
        đề được retry; điều này khác với lần chạy gốc.

        Đầu vào: state - trạng thái graph sau khi hết chủ đề.
        Đầu ra: dict gồm các danh sách kết quả (đúng 3 ô output cuối) phục
            hồi được, và ``unrecovered_failures``.
        """

        failures = state["topic_failures"]
        if not failures:
            return {"unrecovered_failures": ()}
        segments_by_id = {segment.segment_id: segment for segment in state["segments"]}
        previous_context = format_previous_context(state["known_names"], state["known_assignments"])
        recovered: dict[str, list] = {
            "meeting_development": [],
            "verified_assignments": [],
            "verified_decisions": [],
        }
        unrecovered: list[TopicFailure] = []
        for failure in failures:
            segment = segments_by_id.get(failure.segment_id)
            agent = agents.get(failure.agent)
            if segment is None or agent is None:
                unrecovered.append(failure)
                continue
            result = agent(_build_segment_task(segment, state, previous_context))
            again = result.get("topic_failures", ())
            if again:
                unrecovered.extend(again)
                continue
            raw_key = _RETRIED_RAW_KEY_BY_AGENT[failure.agent]
            items = result.get(raw_key, ())
            if failure.agent == "content_agent":
                recovered["meeting_development"].extend(items)
                continue
            result_key = _VERIFIED_KEY_BY_AGENT[failure.agent]
            turns = get_turns_of_segment(segment, state["turns_by_id"])
            for item in items:
                flag = (
                    check_action_evidence(item, turns, state["known_names"])
                    if failure.agent == "action_agent"
                    else check_decision_evidence(item, turns)
                )
                if flag.verdict == "uncertain":
                    logger.warning(
                        "retry_failed_topics: candidate '%s' của segment %s vẫn UNCERTAIN (%s) "
                        "nhưng được giữ vì lượt retry không chạy debate (giới hạn đã biết)",
                        item.text, failure.segment_id, "; ".join(flag.reasons),
                    )
                    item = replace(item, verification="fallback")
                recovered[result_key].append(item)
        return {**recovered, "unrecovered_failures": tuple(unrecovered)}

    return retry_failed_topics


# ---------------------------------------------------------------------------
# Nối các node thành graph
# ---------------------------------------------------------------------------


def build_graph(
    content_llm: LLMAdapter,
    action_llm: LLMAdapter,
    decision_llm: LLMAdapter,
    debate_judge_llm: LLMAdapter,
):
    """Dựng và biên dịch graph LangGraph xử lý một cuộc họp.

    Có nhiều tham số ``LLMAdapter`` riêng (thay vì một instance dùng chung) là cố ý:
    nghiên cứu CoVe/self-refine (xem DESIGN.md) cho thấy dùng lại đúng cùng model
    và ngữ cảnh cho cả bước trích xuất lẫn bước kiểm chứng dễ gây thiên vị tự
    đồng ý. Người gọi có thể truyền cùng một instance cho mọi tham số nếu
    chấp nhận đánh đổi đó để giảm chi phí.

    Đầu vào:
        content_llm: LLM cho agent trích luận điểm theo người nói.
        action_llm: LLM cho agent trích việc giao.
        decision_llm: LLM cho agent trích quyết định/chốt phương án.
        debate_judge_llm: LLM cho node Debate+Judge (cả 3 vai trò Agent
            A/B/Judge dùng chung adapter này, xem
            ``nodes/debate_judge_agent.py``).

    Đầu ra: graph đã ``compile()``, gọi bằng ``graph.invoke(state_ban_dau)``.
        Kết quả trả về CHÍNH LÀ ``MeetingState`` cuối -- đọc thẳng
        ``meeting_development``/``verified_assignments``/``verified_decisions``,
        không có bước "assemble" nào sau đó.
    """

    content_agent = make_content_agent(content_llm)
    action_agent = make_action_agent(action_llm)
    decision_agent = make_decision_agent(decision_llm)
    debate_and_judge_agent = make_debate_and_judge_agent(debate_judge_llm)
    retry_failed_topics = make_retry_failed_topics(
        {
            "content_agent": content_agent,
            "action_agent": action_agent,
            "decision_agent": decision_agent,
        }
    )

    graph = StateGraph(MeetingState)
    graph.add_node("content_agent", content_agent)
    graph.add_node("action_agent", action_agent)
    graph.add_node("decision_agent", decision_agent)
    graph.add_node("check_topic_evidence", check_topic_evidence)
    graph.add_node("debate_and_judge_agent", debate_and_judge_agent)
    graph.add_node("advance_topic", advance_topic)
    graph.add_node("retry_failed_topics", retry_failed_topics)

    dispatch_targets = ["content_agent", "action_agent", "decision_agent", "retry_failed_topics"]
    graph.add_conditional_edges(START, _dispatch_current_topic_to_agents, dispatch_targets)
    graph.add_edge("content_agent", "check_topic_evidence")
    graph.add_edge("action_agent", "check_topic_evidence")
    graph.add_edge("decision_agent", "check_topic_evidence")
    graph.add_conditional_edges(
        "check_topic_evidence",
        _dispatch_debate_or_advance,
        ["debate_and_judge_agent", "advance_topic"],
    )
    graph.add_edge("debate_and_judge_agent", "advance_topic")
    graph.add_conditional_edges("advance_topic", _dispatch_current_topic_to_agents, dispatch_targets)
    graph.add_edge("retry_failed_topics", END)

    return graph.compile()


__all__ = ["build_graph"]
