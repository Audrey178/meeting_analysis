"""Agent kết luận (bước 4): tìm các lời KẾT LUẬN hoặc CHỐT PHƯƠNG ÁN trong một đoạn chủ đề."""

from __future__ import annotations

import logging

from ...utils.llm_call_log import llm_call
from ...utils.ports import LLMAdapter, LLMUpstreamError
from ..shared.meeting_inputs.attendees import MeetingChair
from ..shared.llm_output import (
    read_turn_id,
    read_list_or_empty,
    read_stripped_text,
    split_dict_entries,
    validate_evidence_items,
)
from ..shared.schemas import DecisionCandidate, ExtractorInput, TopicFailure
from .extractor_input import format_topic_prompt
from .member_input import POINT_KINDS, RESPONSES, accepted_member_inputs

logger = logging.getLogger(__name__)


BASIS_STATUS = {
    "closing_statement": "agreed",
    "mutual_agreement": "agreed",
    "unconfirmed": "proposed",
}

_MEMBER_POINT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "turn_id": {"type": "string"},
        "requester": {"type": "string"},
        "point_kind": {"type": "string", "enum": list(POINT_KINDS)},
        "response": {"type": "string", "enum": list(RESPONSES)},
        "response_turn_id": {"type": ["string", "null"]},
        "text": {"type": "string"},
    },
    "required": ["turn_id", "requester", "point_kind", "response", "response_turn_id", "text"],
}

DECISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "member_points": {"type": "array", "items": _MEMBER_POINT_SCHEMA},
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
                    "basis": {"type": "string", "enum": list(BASIS_STATUS)},
                    "request_turn_id": {"type": ["string", "null"]},
                    "confirm_turn_id": {"type": ["string", "null"]},
                    "text": {"type": "string"},
                },
                "required": ["evidence_segment_ids", "basis", "request_turn_id", "confirm_turn_id", "text"],
            },
        },
    },
    "required": ["member_points", "decisions"],
}

_DECISION_STATUSES = frozenset({"agreed", "proposed", "reported"})


def _accepted_member_points(points: object, turns, chair: MeetingChair | None) -> list[dict]:
    """Chuyển các góp ý được tiếp nhận thành mục kết luận, như thể mô hình tự ghi.

    Chỉ lấy ý loại "feedback". Mỗi mục được coi là chốt bằng lời kết luận; lượt nêu góp ý làm bằng
    chứng và lượt tiếp nhận làm lượt chốt.

    Args:
        points: Giá trị ``member_points`` mô hình trả về; có thể sai dạng.
        turns: Các lượt nói của chủ đề.
        chair: Người chủ trì do phiên họp cung cấp. None nếu không có.

    Returns:
        Danh sách dict cùng dạng với mục trong ``decisions``.
    """

    return [
        {
            "evidence_segment_ids": [accepted.request_turn_id] if accepted.request_turn_id else [],
            "basis": "closing_statement",
            "request_turn_id": accepted.request_turn_id,
            "confirm_turn_id": accepted.response_turn_id,
            "text": accepted.entry.get("text"),
        }
        for accepted in accepted_member_inputs(points, turns, chair, members_only=True)
    ]


def run_decision_agent(
    llm: LLMAdapter, system_prompt: str, topic: ExtractorInput, chair: MeetingChair | None = None
) -> dict:
    """Tìm các kết luận, phương án được chốt trong một chủ đề (chưa kiểm chứng).

    Ngoài các kết luận mô hình tự ghi, góp ý của thành viên được tiếp nhận cũng thành kết luận. Lượt
    chốt và lượt nêu luôn được thêm vào bằng chứng; mục không có nội dung hoặc không có bằng chứng hợp
    lệ bị loại. Trạng thái suy từ ``basis`` theo ``BASIS_STATUS``; không suy được thì là "unknown".

    Args:
        llm: Adapter LLM.
        system_prompt: System prompt của agent kết luận.
        topic: Gói dữ liệu của chủ đề.
        chair: Người chủ trì do phiên họp cung cấp. None nếu không có; khi đó góp ý không bị lọc
            theo người nói.

    Returns:
        Dict có ``decision_candidates_raw``; khi LLM lỗi tạm thời thì danh sách rỗng và có thêm
        ``topic_failures``.

    Raises:
        LLMUpstreamError: Khi LLM lỗi loại ``fatal``.
    """

    segment_id = topic["segment_id"]
    user_prompt = format_topic_prompt(topic)
    try:
        with llm_call("decision_agent", segment_id=segment_id, prompt_chars=len(user_prompt)):
            result = llm.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=DECISION_SCHEMA,
            )
    except LLMUpstreamError as exc:
        if exc.fatal:
            raise
        logger.warning("decision_agent bỏ qua segment %s vì LLM lỗi: %s", segment_id, exc)
        failure = TopicFailure(segment_id, "decision_agent", str(exc), exc.kind)
        return {"decision_candidates_raw": [], "topic_failures": (failure,)}

    entries, dropped = split_dict_entries(result.get("decisions"))
    entries += _accepted_member_points(result.get("member_points"), topic["turns"], chair)
    decisions: list[DecisionCandidate] = []
    for item in entries:
        basis = item.get("basis")
        text = read_stripped_text(item.get("text"))
        confirm_turn_id = read_turn_id(topic["turns"], item.get("confirm_turn_id"))
        request_turn_id = read_turn_id(topic["turns"], item.get("request_turn_id"))
        # Lượt chốt và lượt nêu luôn là bằng chứng, kể cả khi model quên liệt kê chúng.
        evidence_turn_ids, quotes, item_ids = validate_evidence_items(
            topic["turns"], read_list_or_empty(item.get("evidence_segment_ids")), [confirm_turn_id, request_turn_id]
        )
        if not text or not evidence_turn_ids:
            dropped += 1
            continue
        status = BASIS_STATUS.get(basis) if isinstance(basis, str) else None
        status = status or item.get("status")
        decisions.append(
            DecisionCandidate(
                segment_id=segment_id,
                text=text,
                evidence_turn_ids=evidence_turn_ids,
                quotes=quotes,
                status=status if status in _DECISION_STATUSES else "unknown",
                confirm_turn_id=confirm_turn_id,
                item_ids=item_ids,
                request_turn_id=request_turn_id,
            )
        )
    if dropped:
        logger.warning(
            "decision_agent segment %s: bỏ %d mục không có text/trích dẫn hợp lệ",
            segment_id,
            dropped,
        )
    return {"decision_candidates_raw": decisions}


__all__ = [
    "BASIS_STATUS",
    "DECISION_SCHEMA",
    "run_decision_agent",
]
