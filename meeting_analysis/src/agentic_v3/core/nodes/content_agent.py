"""Node Content Agent: tóm tắt các ý thảo luận trong MỘT đoạn chủ đề.

Mỗi ý thảo luận là một vấn đề mọi người đang bàn/tranh luận (không phải ý kiến riêng
của từng người), gắn với tất cả người nói tham gia. Người tham gia lấy theo luật từ
người nói của các lượt được trích dẫn, không tin tên do LLM viết. Cách nối vào graph
xem ``..graph``. Node chạy một lần cho mỗi đoạn chủ đề (được gửi qua ``Send``), không
bao giờ thấy cả cuộc họp, chỉ thấy các lượt nói của đúng đoạn của nó
(``..schemas.SegmentTask``).

Khác với Action/Decision Agent: output của Content Agent đi THẲNG vào
``meeting_development`` (không qua evidence-check/debate) -- sơ đồ gốc không
vẽ Evidence Check cho Content, vì "diễn biến họp" là tường thuật lại nội dung
đã bàn, không phải một khẳng định cần xác nhận đúng/sai như action/decision.
"""

from __future__ import annotations

import logging

from .._shared import (
    is_assignment_point,
    validate_evidence_by_segment_ids,
    format_turns_as_transcript,
    list_distinct_speaker_names,
    read_list_or_empty,
    read_stripped_text,
    split_dict_entries,
)
from ..schemas import DiscussionPoint, SegmentTask, TopicFailure
from ....utils.llm_call_log import llm_call
from ....utils.ports import LLMAdapter, LLMUpstreamError

logger = logging.getLogger(__name__)

CONTENT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "discussion_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
                    "text": {"type": "string"},
                },
                "required": ["evidence_segment_ids", "text"],
            },
        }
    },
    "required": ["discussion_points"],
}


def _build_content_user_prompt(task: SegmentTask) -> str:
    """Dựng phần user prompt cho Content Agent: tiêu đề, tóm tắt và bản ghi của đoạn.

    Đầu vào: task - gói dữ liệu của một đoạn chủ đề.
    Đầu ra: str - nội dung user prompt.
    """

    return (
        f"Tiêu đề đoạn: {task['title']}\n"
        f"Tóm tắt đoạn: {task['summary']}\n\n"
        f"Bản ghi:\n{format_turns_as_transcript(task['turns'])}"
    )


def _build_discussion_points_from_llm_result(task: SegmentTask, result: dict) -> tuple[list[DiscussionPoint], int]:
    """Chuyển JSON của model thành các ``DiscussionPoint`` đã kiểm chứng, kèm số ý bị loại.

    Một ý chỉ được giữ nếu: có nội dung, có ít nhất một trích dẫn hợp lệ (ý không
    trích dẫn thì không kiểm chứng được), và nó không chỉ là câu giao việc
    (``is_assignment_point`` -- đã có ở Giao việc, không đếm vào ``dropped``).
    Người tham gia là người nói của các lượt được trích dẫn, theo thứ tự lên tiếng.

    Chịu được JSON sai hình dạng (``null``, sai kiểu phần tử, ``text`` không phải chuỗi...):
    mục xấu chỉ bị loại và tính vào ``dropped``, không làm sập cả đoạn.

    Đầu vào:
        task: gói dữ liệu của đoạn chủ đề (lấy các lượt nói để đối chiếu).
        result: JSON do model trả về theo ``CONTENT_SCHEMA``.

    Đầu ra: tuple ``(points, dropped)``, gồm danh sách DiscussionPoint và số ý đã bị loại.
    """

    turns = task["turns"]
    points: list[DiscussionPoint] = []
    entries, dropped = split_dict_entries(result.get("discussion_points"))
    for entry in entries:
        text = read_stripped_text(entry.get("text"))
        evidence_ids, quotes, segment_ids = validate_evidence_by_segment_ids(
            turns, read_list_or_empty(entry.get("evidence_segment_ids"))
        )
        if not text or not evidence_ids:
            dropped += 1
            continue
        if is_assignment_point(text):
            # Đã có ở Giao việc (Action Agent); không tính là ý lỗi.
            continue
        cited_turns = tuple(turn for turn in turns if turn.turn_id in evidence_ids)
        points.append(
            DiscussionPoint(
                segment_id=task["segment_id"],
                text=text,
                speakers=list_distinct_speaker_names(cited_turns),
                evidence_ids=evidence_ids,
                quotes=quotes,
                segment_ids=segment_ids,
            )
        )
    return points, dropped


def make_content_agent(llm: LLMAdapter, system_prompt: str):
    """Tạo node ``content_agent`` gắn với một LLM và system prompt cụ thể.

    Đầu vào: llm - adapter LLM có ``generate_json``; system_prompt - system prompt của agent
        (bản v3 ở ``agentic_v3/nodes/prompts.py``).
    Đầu ra: hàm node ``content_agent(task)`` để đăng ký vào graph.
    """

    def content_agent(task: SegmentTask) -> dict:
        """Tóm tắt các ý thảo luận cho MỘT đoạn chủ đề.

        Nếu LLM lỗi (``LLMUpstreamError``), trả kết quả rỗng kèm ``TopicFailure``
        để graph thử lại sau, thay vì làm hỏng cả cuộc họp.

        Đầu vào: task - gói dữ liệu của đoạn chủ đề.
        Đầu ra: dict cập nhật state gồm ``meeting_development``, dấu hoàn
            thành ``completed_content_topics`` và (khi lỗi) ``topic_failures``.
        """

        segment_id = task["segment_id"]
        # Dấu rõ ràng "nhánh Content của chủ đề này đã xong"
        # (xem ``..graph.advance_topic``); trả cả ở đường lỗi.
        done = {"completed_content_topics": (segment_id,)}
        user_prompt = _build_content_user_prompt(task)
        try:
            with llm_call("content_agent", segment_id=segment_id, prompt_chars=len(user_prompt)):
                result = llm.generate_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema=CONTENT_SCHEMA,
                )
        except LLMUpstreamError as exc:
            logger.warning(
                "content_agent bỏ qua segment %s vì LLM lỗi: %s", segment_id, exc
            )
            failure = TopicFailure(segment_id, "content_agent", str(exc))
            return {"meeting_development": [], "topic_failures": (failure,), **done}
        points, dropped = _build_discussion_points_from_llm_result(task, result)
        if dropped:
            logger.warning(
                "content_agent segment %s: bỏ %d ý thảo luận không có text/trích dẫn hợp lệ",
                segment_id,
                dropped,
            )
        return {"meeting_development": points, **done}

    return content_agent


__all__ = [
    "CONTENT_SCHEMA",
    "make_content_agent",
]
