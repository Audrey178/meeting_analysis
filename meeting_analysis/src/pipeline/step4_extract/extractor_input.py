"""Chuẩn bị gói dữ liệu của một chủ đề cho các agent trích xuất: tên và tóm tắt chủ đề (đã có từ bước
3), các lượt nói, và danh bạ người nói của cả cuộc họp. Không gọi mô hình.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from ...utils.contracts import SpeakerTurn, TopicLabel, TopicSegment
from ..shared.schemas import ExtractorInput, SpeakerRegistry
from ..shared.transcript import format_turns_as_xml
from .registry import format_registry_context


def build_extractor_input(
    segment: TopicSegment,
    label: TopicLabel,
    turns: tuple[SpeakerTurn, ...],
    registry: SpeakerRegistry,
    meeting_date: str | None,
) -> ExtractorInput:
    """Gom dữ liệu của một chủ đề thành gói đầu vào chung cho các agent trích xuất.

    Args:
        segment: Đoạn chủ đề; chỉ dùng mã đoạn.
        label: Tên và tóm tắt chủ đề từ bước đặt tên chủ đề.
        turns: Các lượt nói thuộc chủ đề.
        registry: Danh bạ người nói của cả cuộc họp, được trình bày sẵn thành văn bản cho prompt.
        meeting_date: Ngày họp ISO "YYYY-MM-DD", làm mốc tính hạn chót. None nếu không biết.

    Returns:
        Gói ``ExtractorInput`` của chủ đề.
    """

    return {
        "segment_id": segment.segment_id,
        "title": label.title,
        "summary": label.summary,
        "turns": turns,
        "meeting_context": format_registry_context(registry),
        "meeting_date": meeting_date,
    }


def format_topic_prompt(topic: ExtractorInput) -> str:
    """Dựng phần chung cuối user prompt của mọi agent trích xuất: khối ``<segment>`` gồm tiêu đề, tóm tắt
    và bản ghi XML."""

    return (
        "<segment>\n"
        f"<title>{escape(topic['title'])}</title>\n"
        f"<summary>{escape(topic['summary'])}</summary>\n"
        f"{format_turns_as_xml(topic['turns'])}\n"
        "</segment>"
    )


__all__ = [
    "build_extractor_input",
    "format_topic_prompt",
]
