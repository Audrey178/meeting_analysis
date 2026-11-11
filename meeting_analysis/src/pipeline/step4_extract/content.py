"""Agent nội dung (bước 4): tóm tắt các ý được thảo luận trong một đoạn chủ đề, mỗi ý kèm câu trích
dẫn làm bằng chứng.
"""

from __future__ import annotations

import logging

from ...utils.llm_call_log import llm_call
from ...utils.ports import LLMAdapter, LLMUpstreamError
from ..shared.llm_output import (
    read_list_or_empty,
    read_stripped_text,
    split_dict_entries,
    validate_evidence_items,
)
from ..shared.schemas import DiscussionPoint, ExtractorInput, TopicFailure
from .extractor_input import format_topic_prompt
from ..shared.transcript import list_distinct_speaker_names

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


def _build_discussion_points_from_llm_result(topic: ExtractorInput, result: dict) -> tuple[list[DiscussionPoint], int]:
    """Chuyển kết quả của mô hình thành các ý thảo luận có bằng chứng hợp lệ, kèm số ý bị loại.

    Ý bị loại khi không có nội dung hoặc không còn trích dẫn nào thuộc chủ đề sau khi kiểm. Người nói
    của mỗi ý lấy từ các lượt được trích dẫn, không theo lời mô hình.

    Args:
        topic: Gói dữ liệu của chủ đề, dùng để đối chiếu lượt nói.
        result: JSON mô hình trả về theo ``CONTENT_SCHEMA``.

    Returns:
        Cặp (danh sách ý thảo luận, số ý bị loại kể cả mục sai dạng).
    """

    turns = topic["turns"]
    points: list[DiscussionPoint] = []
    entries, dropped = split_dict_entries(result.get("discussion_points"))
    for entry in entries:
        text = read_stripped_text(entry.get("text"))
        evidence_turn_ids, quotes, item_ids = validate_evidence_items(
            turns, read_list_or_empty(entry.get("evidence_segment_ids"))
        )
        if not text or not evidence_turn_ids:
            dropped += 1
            continue
        cited_turns = tuple(turn for turn in turns if turn.turn_id in evidence_turn_ids)
        speakers = list_distinct_speaker_names(cited_turns)
        # Nhãn đã duy nhất theo speaker_id (hậu tố " #2"), nên mỗi nhãn ứng với đúng một mã.
        speaker_id_of = {}
        for turn in cited_turns:
            speaker_id_of.setdefault((turn.speaker or "").strip(), turn.speaker_id)
        points.append(
            DiscussionPoint(
                segment_id=topic["segment_id"],
                text=text,
                speakers=speakers,
                evidence_turn_ids=evidence_turn_ids,
                quotes=quotes,
                item_ids=item_ids,
                speaker_ids=tuple(speaker_id_of[name] for name in speakers),
            )
        )
    return points, dropped


def run_content_agent(llm: LLMAdapter, system_prompt: str, topic: ExtractorInput) -> dict:
    """Tóm tắt các ý thảo luận của một chủ đề bằng một lời gọi mô hình.

    Lỗi LLM tạm thời không bị ném ra mà được ghi thành lỗi của chủ đề, để các chủ đề khác vẫn chạy.

    Args:
        llm: Adapter LLM.
        system_prompt: System prompt của agent nội dung.
        topic: Gói dữ liệu của chủ đề.

    Returns:
        Dict có ``discussion_points``; khi LLM lỗi tạm thời thì danh sách rỗng và có thêm
        ``topic_failures``.

    Raises:
        LLMUpstreamError: Khi LLM lỗi loại ``fatal``.
    """

    segment_id = topic["segment_id"]
    user_prompt = format_topic_prompt(topic)
    try:
        with llm_call("content_agent", segment_id=segment_id, prompt_chars=len(user_prompt)):
            result = llm.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=CONTENT_SCHEMA,
            )
    except LLMUpstreamError as exc:
        if exc.fatal:
            raise
        logger.warning(
            "content_agent bỏ qua segment %s vì LLM lỗi: %s", segment_id, exc
        )
        failure = TopicFailure(segment_id, "content_agent", str(exc), exc.kind)
        return {"discussion_points": [], "topic_failures": (failure,)}
    points, dropped = _build_discussion_points_from_llm_result(topic, result)
    if dropped:
        logger.warning(
            "content_agent segment %s: bỏ %d ý thảo luận không có text/trích dẫn hợp lệ",
            segment_id,
            dropped,
        )
    return {"discussion_points": points}


__all__ = [
    "CONTENT_SCHEMA",
    "run_content_agent",
]
