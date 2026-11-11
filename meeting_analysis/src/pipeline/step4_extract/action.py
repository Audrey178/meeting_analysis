"""Agent giao việc (bước 4): tìm các lời GIAO VIỆC MỚI trong một đoạn chủ đề. Nếu cuộc họp có danh
sách việc cần báo cáo, cùng lời gọi đó cũng ghi lại tiến độ của từng việc.

Lời nói về một việc cũ (báo cáo, làm lại, giao lại, đổi hạn) chỉ được tính là cập nhật tiến độ,
không thành việc giao mới.
"""

from __future__ import annotations

import logging

from ...utils.llm_call_log import llm_call
from ...utils.ports import LLMAdapter, LLMUpstreamError
from ..shared.actors.assignees import ASSIGNEES_SCHEMA, format_actor, read_assignee_mentions
from ..shared.llm_output import (
    read_turn_id,
    read_list_or_empty,
    read_stripped_text,
    split_dict_entries,
    validate_evidence_items,
)
from ..shared.meeting_inputs.agenda import TaskAgenda
from ..shared.meeting_inputs.attendees import MeetingChair
from ..shared.prompts import VIETNAMESE_VALUE
from ..shared.schemas import ActionItemCandidate, ExtractorInput, TopicFailure
from .extractor_input import format_topic_prompt
from ..shared.transcript import (
    list_distinct_speaker_names,
)
from .deadline import format_meeting_date, resolve_deadline
from .member_input import RESPONSES, accepted_member_inputs
from .progress_extract import read_progress_updates

logger = logging.getLogger(__name__)


BASIS_STATUS = {
    "direct_request": "assigned",
    "member_request_accepted": "assigned",
    "assignee_acknowledged": "assigned",
    "volunteered": "self_committed",
    "member_request_pending": "proposed",
}
NOT_ASSIGNMENT_BASES = ("document_content", "status_report", "discussion_question")

_ASSIGNMENT_FIELDS: dict = {
    "assignees": ASSIGNEES_SCHEMA,
    "deadline": {"type": ["string", "null"], "description": VIETNAMESE_VALUE},
    "deadline_date": {"type": ["string", "null"]},
    "deadline_kind": {
        "type": "string",
        "enum": ["exact", "before", "end_of_period", "relative", "unknown"],
    },
    "text": {"type": "string", "description": VIETNAMESE_VALUE},
}

_MEMBER_REQUEST_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "turn_id": {"type": "string"},
        "requester": {"type": "string", "description": VIETNAMESE_VALUE},
        "response": {"type": "string", "enum": list(RESPONSES)},
        "response_turn_id": {"type": ["string", "null"]},
        **_ASSIGNMENT_FIELDS,
    },
    "required": ["turn_id", "requester", "response", "response_turn_id", *_ASSIGNMENT_FIELDS],
}

ACTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "member_requests": {"type": "array", "items": _MEMBER_REQUEST_SCHEMA},
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
                    "basis": {"type": "string", "enum": [*BASIS_STATUS, *NOT_ASSIGNMENT_BASES]},
                    "request_turn_id": {"type": ["string", "null"]},
                    "confirm_turn_id": {"type": ["string", "null"]},
                    **_ASSIGNMENT_FIELDS,
                },
                "required": [
                    "evidence_segment_ids", "basis", "request_turn_id", "confirm_turn_id", *_ASSIGNMENT_FIELDS,
                ],
            },
        },
        # Chỉ để model xác định lượt tổng kết trước khi điền ``confirm_turn_id`` (prompt dặn dùng lượt này);
        # code không đọc hay ghi đè lượt chốt model khai, ``check_evidence`` kiểm nó.
        "summary_turn_id": {"type": ["string", "null"]},
    },
    "required": ["member_requests", "action_items", "summary_turn_id"],
}

_ACTION_STATUSES = frozenset({"assigned", "self_committed", "proposed", "reported"})


def _accepted_member_requests(requests: object, turns, chair: MeetingChair | None) -> list[dict]:
    """Chuyển các yêu cầu của thành viên được tiếp nhận thành mục việc giao, như thể mô hình tự ghi.

    Bên nhận, hạn và nội dung lấy từ yêu cầu; lượt nêu yêu cầu và lượt tiếp nhận thành lượt nêu và
    lượt chốt của việc giao.

    Args:
        requests: Giá trị ``member_requests`` mô hình trả về; có thể sai dạng.
        turns: Các lượt nói của chủ đề.
        chair: Người chủ trì do phiên họp cung cấp. None nếu không có.

    Returns:
        Danh sách dict cùng dạng với mục trong ``action_items``.
    """

    return [
        {
            **{field: accepted.entry.get(field) for field in _ASSIGNMENT_FIELDS},
            "evidence_segment_ids": [],
            "basis": "member_request_accepted",
            "request_turn_id": accepted.request_turn_id,
            "confirm_turn_id": accepted.response_turn_id,
        }
        for accepted in accepted_member_inputs(requests, turns, chair)
    ]


def _build_action_user_prompt(topic: ExtractorInput) -> str:
    """Dựng user prompt của agent giao việc.

    Gồm ngày họp (kèm thứ), bối cảnh cuộc họp, người nói trong chủ đề, rồi phần chung của chủ đề.
    """

    speakers = ", ".join(list_distinct_speaker_names(topic["turns"])) or "(unknown)"
    return (
        f"Meeting date: {format_meeting_date(topic.get('meeting_date'))}\n\n"
        f"Meeting context:\n{topic['meeting_context']}\n\n"
        f"Speakers in this segment: {speakers}\n\n"
        f"{format_topic_prompt(topic)}"
    )


def run_action_agent(
    llm: LLMAdapter,
    system_prompt: str,
    topic: ExtractorInput,
    agenda: TaskAgenda | None = None,
    chair: MeetingChair | None = None,
) -> dict:
    """Tìm các việc mới được giao trong một chủ đề (chưa kiểm chứng), kèm tiến độ việc cũ nếu có.

    Ngoài các việc mô hình tự ghi, yêu cầu của thành viên được tiếp nhận cũng thành việc giao. Mục mô
    hình tự xếp là không phải giao việc (nội dung văn bản, báo cáo tình hình, câu hỏi thảo luận) bị bỏ.
    Lượt chốt và lượt nêu yêu cầu luôn được thêm vào bằng chứng; mục không có nội dung hoặc bằng chứng
    hợp lệ bị loại. Hạn chót được quy về ngày cụ thể, ưu tiên ngày do luật tính.

    Args:
        llm: Adapter LLM. Khi cuộc họp có danh sách việc, adapter phải tự thêm trường ``updates``
            vào schema, vì hàm này luôn gửi schema gốc.
        system_prompt: System prompt của agent giao việc.
        topic: Gói dữ liệu của chủ đề.
        agenda: Danh sách việc cần báo cáo. None hoặc rỗng thì không đọc tiến độ.
        chair: Người chủ trì do phiên họp cung cấp. None nếu không có.

    Returns:
        Dict có ``action_item_candidates_raw`` và ``progress_updates_raw``; khi LLM lỗi tạm thời thì
        cả hai rỗng và có thêm ``topic_failures``.

    Raises:
        LLMUpstreamError: Khi LLM lỗi loại ``fatal``.
    """

    with_progress = agenda is not None and bool(agenda.tasks)
    segment_id = topic["segment_id"]
    user_prompt = _build_action_user_prompt(topic)
    try:
        with llm_call("action_agent", segment_id=segment_id, prompt_chars=len(user_prompt)):
            result = llm.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=ACTION_SCHEMA,
            )
    except LLMUpstreamError as exc:
        if exc.fatal:
            raise
        logger.warning("action_agent bỏ qua segment %s vì LLM lỗi: %s", segment_id, exc)
        failure = TopicFailure(segment_id, "action_agent", str(exc), exc.kind)
        return {"action_item_candidates_raw": [], "progress_updates_raw": [], "topic_failures": (failure,)}

    entries, dropped = split_dict_entries(result.get("action_items"))
    entries += _accepted_member_requests(result.get("member_requests"), topic["turns"], chair)
    actions: list[ActionItemCandidate] = []
    not_assignments = 0
    for item in entries:
        basis = item.get("basis")
        if basis in NOT_ASSIGNMENT_BASES:
            not_assignments += 1
            continue
        text = read_stripped_text(item.get("text"))
        confirm_turn_id = read_turn_id(topic["turns"], item.get("confirm_turn_id"))
        request_turn_id = read_turn_id(topic["turns"], item.get("request_turn_id"))
        # Lượt chốt và lượt nêu yêu cầu luôn là bằng chứng, kể cả khi model quên liệt kê chúng.
        evidence_turn_ids, quotes, item_ids = validate_evidence_items(
            topic["turns"], read_list_or_empty(item.get("evidence_segment_ids")), [confirm_turn_id, request_turn_id]
        )
        if not text or not evidence_turn_ids:
            dropped += 1
            continue
        mentions = read_assignee_mentions(item.get("assignees"), item.get("actor"))
        actor = format_actor(mentions)
        status = BASIS_STATUS.get(basis) if isinstance(basis, str) else None
        status = status or item.get("status")
        deadline_raw = read_stripped_text(item.get("deadline")) or None
        deadline = resolve_deadline(item, deadline_raw, topic.get("meeting_date"))
        actions.append(
            ActionItemCandidate(
                segment_id=segment_id,
                actor=actor,
                text=text,
                evidence_turn_ids=evidence_turn_ids,
                quotes=quotes,
                deadline_raw=deadline_raw,
                deadline_date=deadline.deadline_date,
                deadline_kind=deadline.deadline_kind,
                status=status if status in _ACTION_STATUSES else "unknown",
                confirm_turn_id=confirm_turn_id,
                item_ids=item_ids,
                mentions=mentions,
                request_turn_id=request_turn_id,
            )
        )
    if dropped:
        logger.warning(
            "action_agent segment %s: bỏ %d mục không có text/trích dẫn hợp lệ",
            segment_id,
            dropped,
        )
    if not_assignments:
        logger.info(
            "action_agent segment %s: bỏ %d mục agent xếp là nội dung văn bản/báo cáo",
            segment_id,
            not_assignments,
        )
    updates = read_progress_updates(result.get("updates"), topic, agenda) if with_progress else []
    return {"action_item_candidates_raw": actions, "progress_updates_raw": updates}


__all__ = [
    "ACTION_SCHEMA",
    "BASIS_STATUS",
    "NOT_ASSIGNMENT_BASES",
    "run_action_agent",
]
