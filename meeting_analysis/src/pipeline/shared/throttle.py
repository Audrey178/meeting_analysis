"""Giới hạn tổng số lời gọi mô hình chạy cùng lúc cho cả cuộc họp (đặt tên chủ đề, trích xuất, kiểm
chứng).

Khi mọi chủ đề chạy song song, số lời gọi cùng lúc dễ vượt sức chịu của dịch vụ và gây quá thời
gian hoặc bị từ chối. Mọi lời gọi đều phải đi qua cùng một "cổng" nên dùng chung một hạn mức, bất
kể đến từ đâu.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Mapping

from ...utils.ports import LLMAdapter, TopicLabelAdapter

# Mặc định dưới max_connections của client OpenAI (OPENAI_MAX_CONNECTIONS, mặc định 10).
DEFAULT_LLM_CONCURRENCY = 8


class LLMConcurrencyGate:
    """Giới hạn số lời gọi mô hình chạy cùng lúc, dùng chung cho mọi adapter được bọc qua nó.

    Tạo một cổng cho cả cuộc họp rồi bọc mọi adapter gọi mô hình qua cổng đó, để tổng số lời gọi
    đồng thời của mọi chủ đề và mọi bước không vượt hạn mức.

    Args:
        limit: Số lời gọi mô hình tối đa chạy cùng lúc, phải >= 1.

    Raises:
        ValueError: Khi ``limit`` nhỏ hơn 1.
    """

    def __init__(self, limit: int = DEFAULT_LLM_CONCURRENCY) -> None:
        if limit < 1:
            raise ValueError("limit phải >= 1")
        self.limit = limit
        self._semaphore = threading.BoundedSemaphore(limit)

    def wrap_llm(self, llm: LLMAdapter) -> LLMAdapter:
        """Bọc một adapter mô hình sinh JSON để mỗi lời gọi phải giữ một suất của cổng.

        Adapter hỗ trợ giữ suất theo từng request thì chỉ giữ suất quanh từng request HTTP và nhả ra
        khi ngủ chờ thử lại; nhờ vậy khi dịch vụ treo, các lời gọi đang ngủ không chiếm hết suất. Adapter
        khác giữ suất suốt cả lời gọi.

        Args:
            llm: Adapter gốc.

        Returns:
            Adapter cùng giao thức, mỗi lời gọi giữ một suất của cổng.
        """

        with_request_guard = getattr(llm, "with_request_guard", None)
        if callable(with_request_guard):
            return with_request_guard(self._semaphore)
        return _ThrottledLLMAdapter(llm, self._semaphore)

    def wrap_topic_labeler(self, adapter: TopicLabelAdapter) -> TopicLabelAdapter:
        """Bọc một adapter đặt tên chủ đề để mỗi lời gọi phải giữ một suất của cổng.

        Nếu adapter gọi mô hình qua một adapter mô hình bên trong hỗ trợ giữ suất theo request thì bọc
        adapter bên trong đó (trên một bản sao nông, không sửa adapter gốc); nếu không thì giữ suất suốt
        cả lời gọi đặt tên.

        Args:
            adapter: Adapter đặt tên chủ đề gốc.

        Returns:
            Adapter cùng giao thức, mỗi lời gọi giữ một suất của cổng.
        """

        inner_llm = getattr(adapter, "llm", None)
        if callable(getattr(inner_llm, "with_request_guard", None)):
            guarded = copy.copy(adapter)
            guarded.llm = inner_llm.with_request_guard(self._semaphore)
            return guarded
        return _ThrottledTopicLabelAdapter(adapter, self._semaphore)


class _ThrottledLLMAdapter:
    """Adapter mô hình sinh JSON chờ một suất của cổng trước mỗi lời gọi và giữ suất tới khi xong."""

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
    """Adapter đặt tên chủ đề chờ một suất của cổng trước mỗi lời gọi và giữ suất tới khi xong."""

    def __init__(self, inner: TopicLabelAdapter, semaphore: threading.BoundedSemaphore) -> None:
        self._inner = inner
        self._semaphore = semaphore

    def label_topic(self, *args, **kwargs):
        with self._semaphore:
            return self._inner.label_topic(*args, **kwargs)


__all__ = [
    "DEFAULT_LLM_CONCURRENCY",
    "LLMConcurrencyGate",
]
