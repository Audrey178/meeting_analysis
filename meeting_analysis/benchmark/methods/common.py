"""Phần dùng chung của các baseline: định nghĩa nghiệp vụ, schema output chung, prompt cơ sở.

Định nghĩa viết theo ``eval/synthetic/README.md`` (§3 của ``PLAN.md``), **không** chép prompt đã
tune của v3. Chỉ dùng chung luật định dạng JSON một dòng của v3 (luật kỹ thuật cho gemma/vLLM,
không phải nội dung nghiệp vụ).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from benchmark.data import Meeting
from benchmark.llm import BenchLLM, Usage
from src.agentic_v3.nodes.prompts import JSON_ONE_LINE_RULE

TASK_DEFINITIONS = """Bạn đọc biên bản một cuộc họp tiếng Việt (mỗi dòng: [TURN_xxxxxx] người nói: nội dung) và trích xuất:

1. CHỦ ĐỀ (topics): chia cuộc họp thành các đoạn liền mạch theo nội dung. Ranh giới đặt ở chỗ nội dung thực sự chuyển (đổi hạng mục/module, hoặc đổi giai đoạn trình bày → góp ý → kết luận). Chen ngang ngắn (≤ 3 lượt, thủ tục, mời phát biểu) không phải ranh giới. Mỗi chủ đề ghi lượt bắt đầu và tiêu đề ngắn.
2. VIỆC GIAO (assignments): chỉ tính khi có người nhận hoặc được chỉ định rõ. Ghi người phụ trách (tên như trong biên bản hoặc tên người được nhắc tới), nội dung việc, hạn (nguyên văn, null nếu không nêu). Việc cần làm mà không ai nhận thì actor = null. Việc được nêu rồi bị gạt đi thì KHÔNG đưa vào.
3. KẾT LUẬN (decisions): chỉ những gì đã được CHỐT. Đề xuất chưa được chấp nhận không phải kết luận. Nếu một kết luận bị đảo lại sau đó thì chỉ lấy bản cuối.
4. DIỄN BIẾN (discussion): các ý chính mỗi người nói chính nêu ra trong từng chủ đề, kèm tên người nói.

Mọi mục phải kèm evidence_turn_ids là các TURN_xxxxxx có thật trong biên bản, nơi nội dung đó được nói ra."""

_EVIDENCE = {"type": "array", "items": {"type": "string"}}

OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"start_turn": {"type": "string"}, "title": {"type": "string"}},
                "required": ["start_turn", "title"],
            },
        },
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "actor": {"type": ["string", "null"]},
                    "task": {"type": "string"},
                    "deadline": {"type": ["string", "null"]},
                    "evidence_turn_ids": _EVIDENCE,
                },
                "required": ["actor", "task", "deadline", "evidence_turn_ids"],
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "evidence_turn_ids": _EVIDENCE},
                "required": ["text", "evidence_turn_ids"],
            },
        },
        "discussion": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "speakers": {"type": "array", "items": {"type": "string"}},
                    "evidence_turn_ids": _EVIDENCE,
                },
                "required": ["text", "speakers", "evidence_turn_ids"],
            },
        },
    },
    "required": ["topics", "assignments", "decisions", "discussion"],
}

OUTPUT_KEYS = ("topics", "assignments", "decisions", "discussion")


def meeting_header(meeting: Meeting) -> str:
    """Thông tin chung đưa vào prompt: ngày họp nếu có."""

    return f"Ngày họp: {meeting.meeting_date}\n" if meeting.meeting_date else ""


def system_prompt(extra: str = "") -> str:
    parts = [TASK_DEFINITIONS, extra.strip(), JSON_ONE_LINE_RULE]
    return "\n\n".join(part for part in parts if part)


def user_prompt(meeting: Meeting) -> str:
    return f"{meeting_header(meeting)}BIÊN BẢN:\n{meeting.render()}"


def to_common_schema(raw: dict) -> dict:
    """Giữ đúng 4 khoá của schema chung (bỏ ``reasoning`` hay khoá thừa)."""

    return {key: list(raw.get(key) or []) for key in OUTPUT_KEYS}


@dataclass(frozen=True, slots=True)
class Method:
    """Một hàng của Bảng 1.

    Các trường:
        name: tên hàng, dùng làm thư mục kết quả.
        run: (meeting, llm, usage) -> output theo schema chung.
        prompt_fingerprint: chuỗi đại diện prompt/tham số, băm vào khoá cache.
    """

    name: str
    run: Callable[[Meeting, BenchLLM, Usage], dict]
    prompt_fingerprint: str
