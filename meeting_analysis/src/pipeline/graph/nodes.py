"""Các bước nhỏ của luồng chạy bước 4-6. Mỗi bước nhỏ chỉ lấy dữ liệu và công cụ nó cần rồi chuyển cho
phần xử lý tương ứng ở thư mục của bước đó; bản thân nó không chứa logic.
"""

from __future__ import annotations

from langgraph.runtime import Runtime

from ..deps import GraphDeps
from ..shared.schemas import VerifyTask
from ..step4_extract.extractors import extract_topic
from ..step4_extract.extractor_input import build_extractor_input
from ..step4_extract.registry import build_speaker_registry
from ..step5_verify.check.evidence_check import check_topic_candidates
from ..step5_verify.verifier.progress_verifier import ProgressVerifier
from ..step5_verify.verifier.verifier import Verifier
from ..step6_finalize.finalize import build_meeting_report
from .state import MeetingState, TopicState

# ---- graph cha, một lần mỗi cuộc họp ----

def build_registry(state: MeetingState) -> dict:
    """Dựng danh bạ người nói của cả cuộc họp (bước 4), một lần trước khi các chủ đề chạy.

    Danh bạ gồm người nói trong bản ghi, kèm danh sách tham dự, người chủ trì và danh sách việc
    nếu phiên họp cung cấp.
    """

    registry = build_speaker_registry(
        tuple(state["turns_by_id"].values()),
        state.get("attendee_roster"),
        chair=state.get("chair"),
        agenda=state.get("task_agenda"),
    )
    return {"registry": registry}


def finalize(state: MeetingState, runtime: Runtime[GraphDeps]) -> dict:
    """Tổng hợp kết quả mọi chủ đề thành báo cáo cuộc họp (bước 6).

    Không gọi LLM sinh văn bản; chỉ hỏi Decisions API (nếu có) để đối chiếu kết luận, việc giao
    giữa các chủ đề và để gộp tiến độ theo từng việc.
    """

    report = build_meeting_report(
        segments=state["segments"],
        turns_by_id=state["turns_by_id"],
        registry=state["registry"],
        parts=state["parts"],
        meeting_date=state.get("meeting_date"),
        labels=state.get("labels", []),
        discussion_points=state.get("discussion_points", []),
        assignments=state.get("verified_assignments", []),
        decisions=state.get("verified_decisions", []),
        verification_records=state.get("verification_records", []),
        progress_updates=state.get("progress_updates", []),
        failures=state.get("topic_failures", []),
        judge=runtime.context.turn_judge,
    )
    return {"report": report}


# ---- subgraph, mỗi chủ đề ----

def prepare_topic(state: TopicState) -> dict:
    """Dựng gói dữ liệu đầu vào cho các agent trích xuất của một chủ đề (bước 4).

    Dùng nhãn chủ đề đã có từ bước 3; nhãn này cũng được đẩy ra kết quả để báo cáo luôn đủ mọi
    chủ đề.
    """

    topic = build_extractor_input(
        state["segment"], state["label"], state["turns"], state["registry"], state.get("meeting_date")
    )
    return {"labels": [state["label"]], "extractor_input": topic}


def _extract(name: str, llm, state: TopicState, attempts: int) -> dict:
    """Gọi agent trích xuất ``name`` cho chủ đề, với số lần thử ``attempts``."""

    return extract_topic(name, llm, state["extractor_input"], state["registry"], state["parts"], attempts)


def content_agent(state: TopicState, runtime: Runtime[GraphDeps]) -> dict:
    """Chạy agent tóm tắt ý thảo luận của chủ đề (bước 4)."""

    deps = runtime.context
    return _extract("content_agent", deps.content_llm, state, deps.config.extract_attempts)


def action_agent(state: TopicState, runtime: Runtime[GraphDeps]) -> dict:
    """Chạy agent trích việc giao, và tiến độ việc cũ nếu phiên họp có danh sách việc (bước 4)."""

    deps = runtime.context
    return _extract("action_agent", deps.action_llm, state, deps.config.extract_attempts)


def decision_agent(state: TopicState, runtime: Runtime[GraphDeps]) -> dict:
    """Chạy agent trích kết luận của chủ đề (bước 4)."""

    deps = runtime.context
    return _extract("decision_agent", deps.decision_llm, state, deps.config.extract_attempts)


def evidence_check(state: TopicState, runtime: Runtime[GraphDeps]) -> dict:
    """Gắn nhãn CLEAR hoặc UNCERTAIN cho các candidate của chủ đề bằng luật và Decisions API (bước 5).

    Candidate CLEAR vào thẳng kết quả; candidate UNCERTAIN được gom lại để gửi Verifier.
    """

    deps = runtime.context
    return check_topic_candidates(
        state["segment"].segment_id,
        state["turns"],
        state["meeting_turns"],
        state["registry"],
        state.get("action_candidates_raw", []),
        state.get("decision_candidates_raw", []),
        state.get("progress_updates_raw", []),
        turn_judge=deps.turn_judge,
        progress_judge=deps.progress_judge,
    )


def verifier(task: VerifyTask, runtime: Runtime[GraphDeps]) -> dict:
    """Kiểm chứng một candidate UNCERTAIN qua các vòng trao đổi Verifier và agent trích xuất (bước 5).

    Cập nhật tiến độ đi luồng kiểm chứng riêng, với Action agent đóng vai bên trả lời nhận xét.
    Việc giao và kết luận đi luồng chung, bên trả lời là agent đã trích ra candidate đó.

    Args:
        task: Yêu cầu kiểm chứng cho đúng một candidate.
        runtime: Ngữ cảnh chạy, mang các mô hình và cấu hình.

    Returns:
        Phần cập nhật trạng thái: mục được giữ (nếu có) và bản ghi kiểm chứng.
    """

    deps = runtime.context
    if task["kind"] == "progress":
        return ProgressVerifier(deps.verifier_llm, deps.action_llm, deps.config).run(task)
    proposer_llms = {"action": deps.action_llm, "decision": deps.decision_llm}
    return Verifier(deps.verifier_llm, proposer_llms, deps.config).run(task)


# Node agent trích xuất theo tên (cùng tên với khoá của ``extractors.EXTRACTOR_OUTPUTS``).
EXTRACTOR_NODES = {
    "content_agent": content_agent,
    "action_agent": action_agent,
    "decision_agent": decision_agent,
}


__all__ = [
    "EXTRACTOR_NODES",
    "evidence_check",
    "finalize",
    "build_registry",
    "prepare_topic",
    "verifier",
]
