"""Ba agent trích xuất của v3: node của v1 (giữ nguyên phần làm sạch output) chạy với prompt v3.

Mỗi node v1 gọi ``llm.generate_json`` đúng MỘT lần với system prompt của v1. v3 đưa cho
node v1 một adapter bọc (``_V3PromptLLM``): adapter này thay system prompt bằng bản v3
(``prompts.py``) và thêm dòng người chủ trì vào đầu user prompt. Schema và phần đọc kết
quả vẫn là của v1.

Node v1 được dựng lại ở mỗi lần chạy (rẻ: chỉ là một closure) vì dòng người chủ trì đổi
theo cuộc họp, trong khi graph dùng chung cho mọi cuộc họp chạy song song.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ...agentic.nodes import make_action_agent, make_content_agent, make_decision_agent
from ...agentic.schemas import SegmentTask
from ...utils.ports import LLMAdapter
from ..schemas import SpeakerRegistry
from .prompts import (
    ACTION_SYSTEM_PROMPT,
    CONTENT_SYSTEM_PROMPT,
    DECISION_SYSTEM_PROMPT,
    format_chair_line,
)

# Tên node -> (hàm tạo node v1, system prompt v3).
_AGENTS = {
    "content_agent": (make_content_agent, CONTENT_SYSTEM_PROMPT),
    "action_agent": (make_action_agent, ACTION_SYSTEM_PROMPT),
    "decision_agent": (make_decision_agent, DECISION_SYSTEM_PROMPT),
}


class _V3PromptLLM:
    """``LLMAdapter`` thay system prompt và thêm phần đầu user prompt trước khi gọi LLM thật.

    Đầu vào khi tạo: llm - adapter thật; system_prompt - system prompt v3; user_prefix -
        dòng đặt trước user prompt của v1.
    """

    def __init__(self, llm: LLMAdapter, system_prompt: str, user_prefix: str) -> None:
        self._llm = llm
        self._system_prompt = system_prompt
        self._user_prefix = user_prefix

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema: Mapping[str, object]):
        del system_prompt  # prompt v1, thay bằng bản v3
        return self._llm.generate_json(
            system_prompt=self._system_prompt,
            user_prompt=f"{self._user_prefix}\n\n{user_prompt}",
            schema=schema,
        )


def make_extractor(name: str, llm: LLMAdapter) -> Callable[[SegmentTask, SpeakerRegistry], dict]:
    """Tạo agent trích xuất ``name`` ("content_agent"/"action_agent"/"decision_agent") của v3.

    Đầu vào: name - tên agent; llm - adapter LLM.
    Đầu ra: hàm ``(task, registry) -> dict`` trả đúng kết quả của node v1.
    """

    factory, system_prompt = _AGENTS[name]

    def extractor(task: SegmentTask, registry: SpeakerRegistry) -> dict:
        prompted = _V3PromptLLM(llm, system_prompt, format_chair_line(registry.chair))
        return factory(prompted)(task)

    return extractor


__all__ = ["make_extractor"]
