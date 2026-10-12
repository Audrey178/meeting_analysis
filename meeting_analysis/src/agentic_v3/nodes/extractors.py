"""Ba agent trích xuất của v3: node của v1 (giữ nguyên phần làm sạch output) chạy với prompt v3.

Mỗi node v1 gọi ``llm.generate_json`` đúng MỘT lần với system prompt của v1. v3 đưa cho
node v1 một adapter bọc (``_V3PromptLLM``): adapter này thay system prompt bằng bản v3
(``prompts.py``) và thêm dòng người chủ trì vào đầu user prompt. Schema và phần đọc kết
quả vẫn là của v1.

Node v1 được dựng lại ở mỗi lần chạy (rẻ: chỉ là một closure) vì dòng người chủ trì đổi
theo cuộc họp, trong khi graph dùng chung cho mọi cuộc họp chạy song song.

Phiên họp có danh sách việc cần báo cáo thì Action agent nhận thêm ``ACTION_TASK_ID_RULE``
và trường ``task_id`` trong schema (``with_task_id_field``); không có danh sách thì prompt
và schema giữ nguyên như khi chưa có tính năng này.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence

from ..core.nodes import make_action_agent, make_content_agent, make_decision_agent
from ..core.nodes.action_agent import NEW_TASK_ID
from ..core.schemas import SegmentTask
from ...utils.ports import LLMAdapter
from ..schemas import SpeakerRegistry
from .prompts import (
    ACTION_SYSTEM_PROMPT,
    ACTION_TASK_ID_RULE,
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
        dòng đặt trước user prompt của v1; schema_hook - hàm sửa schema của node v1 trước
        khi gọi (None = giữ nguyên).
    """

    def __init__(
        self,
        llm: LLMAdapter,
        system_prompt: str,
        user_prefix: str,
        schema_hook: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None,
    ) -> None:
        self._llm = llm
        self._system_prompt = system_prompt
        self._user_prefix = user_prefix
        self._schema_hook = schema_hook

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema: Mapping[str, object]):
        del system_prompt  # prompt v1, thay bằng bản v3
        return self._llm.generate_json(
            system_prompt=self._system_prompt,
            user_prompt=f"{self._user_prefix}\n\n{user_prompt}",
            schema=self._schema_hook(schema) if self._schema_hook else schema,
        )


def with_task_id_field(schema: Mapping[str, object], task_ids: Sequence[str]) -> dict:
    """Thêm trường ``task_id`` vào schema Action agent, đứng ngay sau ``text``.

    ``task_id`` là enum các mã việc cộng ``NEW_TASK_ID`` (việc mới). Dùng enum chuỗi, không
    dùng null trong enum, vì gateway đã chạy ổn với enum chuỗi (schema agent tiến độ).

    Đầu vào: schema - ``ACTION_SCHEMA``; task_ids - mã các việc trong danh sách.
    Đầu ra: bản sao schema đã thêm trường.
    """

    schema = copy.deepcopy(dict(schema))
    item = schema["properties"]["action_items"]["items"]
    properties: dict[str, object] = {}
    for field, spec in item["properties"].items():
        properties[field] = spec
        if field == "text":
            properties["task_id"] = {"type": "string", "enum": [*task_ids, NEW_TASK_ID]}
    item["properties"] = properties
    required = list(item["required"])
    required.insert(required.index("text") + 1, "task_id")
    item["required"] = required
    return schema


def make_extractor(name: str, llm: LLMAdapter) -> Callable[[SegmentTask, SpeakerRegistry], dict]:
    """Tạo agent trích xuất ``name`` ("content_agent"/"action_agent"/"decision_agent") của v3.

    Đầu vào: name - tên agent; llm - adapter LLM.
    Đầu ra: hàm ``(task, registry) -> dict`` trả đúng kết quả của node v1.
    """

    factory, system_prompt = _AGENTS[name]

    def extractor(task: SegmentTask, registry: SpeakerRegistry) -> dict:
        prompt, schema_hook = system_prompt, None
        task_ids = registry.agenda.task_ids
        if name == "action_agent" and task_ids:
            prompt = f"{system_prompt}\n\n{ACTION_TASK_ID_RULE}"

            def schema_hook(schema: Mapping[str, object]) -> dict:
                return with_task_id_field(schema, task_ids)

        prompted = _V3PromptLLM(llm, prompt, format_chair_line(registry.chair), schema_hook)
        return factory(prompted)(task)

    return extractor


__all__ = ["make_extractor", "with_task_id_field"]
