"""Giới hạn số lời gọi LLM đồng thời cho CẢ cuộc họp (gán nhãn + trích xuất + Verifier).

Khi mọi chủ đề chạy song song, số lời gọi cùng lúc có thể vượt ``max_connections=10``
của client OpenAI (``utils/openai_adapters._client``) và gây timeout/rate-limit. Mọi
adapter đi qua cùng một ``LLMConcurrencyGate`` nên dùng chung một hạn mức, bất kể
lời gọi đến từ node nào.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from ..utils.ports import LLMAdapter, TopicLabelAdapter

# Mặc định dưới max_connections của client OpenAI (OPENAI_MAX_CONNECTIONS, mặc định 10).
DEFAULT_LLM_CONCURRENCY = 8


class LLMConcurrencyGate:
    """Semaphore dùng chung, bọc các adapter LLM để mỗi lời gọi phải giữ một suất.

    Đầu vào khi tạo: limit - số lời gọi LLM tối đa chạy cùng lúc (>= 1).
    """

    def __init__(self, limit: int = DEFAULT_LLM_CONCURRENCY) -> None:
        if limit < 1:
            raise ValueError("limit phải >= 1")
        self.limit = limit
        self._semaphore = threading.BoundedSemaphore(limit)

    def wrap_llm(self, llm: LLMAdapter) -> LLMAdapter:
        """Bọc một ``LLMAdapter`` (``generate_json``) qua gate.

        Đầu vào: llm - adapter gốc.
        Đầu ra: adapter có cùng giao thức, mỗi lời gọi giữ một suất của gate.
        """

        return _ThrottledLLMAdapter(llm, self._semaphore)

    def wrap_topic_labeler(self, adapter: TopicLabelAdapter) -> TopicLabelAdapter:
        """Bọc một ``TopicLabelAdapter`` (``label_topic``) qua gate.

        Đầu vào: adapter - adapter gán nhãn gốc.
        Đầu ra: adapter có cùng giao thức, mỗi lời gọi giữ một suất của gate.
        """

        return _ThrottledTopicLabelAdapter(adapter, self._semaphore)


class _ThrottledLLMAdapter:
    """``LLMAdapter`` chờ suất của semaphore trước mỗi ``generate_json``."""

    def __init__(self, inner: LLMAdapter, semaphore: threading.BoundedSemaphore) -> None:
        self._inner = inner
        self._semaphore = semaphore

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema: Mapping[str, object]
    ) -> Mapping[str, object]:
        with self._semaphore:
            return self._inner.generate_json(
                system_prompt=system_prompt, user_prompt=user_prompt, schema=schema
            )


class _ThrottledTopicLabelAdapter:
    """``TopicLabelAdapter`` chờ suất của semaphore trước mỗi ``label_topic``."""

    def __init__(self, inner: TopicLabelAdapter, semaphore: threading.BoundedSemaphore) -> None:
        self._inner = inner
        self._semaphore = semaphore

    def label_topic(self, *args, **kwargs):
        with self._semaphore:
            return self._inner.label_topic(*args, **kwargs)


__all__ = ["DEFAULT_LLM_CONCURRENCY", "LLMConcurrencyGate"]
