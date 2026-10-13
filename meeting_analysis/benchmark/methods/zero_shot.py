"""Base LLM / Zero-shot: một lời gọi cho cả cuộc họp (``PLAN.md`` §3.1)."""

from __future__ import annotations

from benchmark.data import Meeting
from benchmark.llm import BenchLLM, Usage
from benchmark.methods.common import OUTPUT_SCHEMA, Method, system_prompt, to_common_schema, user_prompt

SYSTEM_PROMPT = system_prompt()


def run(meeting: Meeting, llm: BenchLLM, usage: Usage) -> dict:
    raw = llm.generate(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt(meeting), schema=OUTPUT_SCHEMA, usage=usage)
    return to_common_schema(raw)


METHOD = Method("zero_shot", run, SYSTEM_PROMPT)
