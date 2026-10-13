"""Lời gọi LLM của benchmark: structured output, thử lại khi JSON hỏng, ghi token mỗi lời gọi.

Dùng lại client và chuẩn hoá schema của ``src/utils/openai_adapters.py`` để mọi hàng chạy
trên gemma có cùng cấu hình kết nối với v3, nhưng tự đọc ``usage`` cho bảng chi phí (§4).
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

from openai import APIStatusError

from src.utils.openai_adapters import (
    _RETRYABLE_EXCEPTIONS,
    _client,
    _InvalidJSONResponse,
    _openai_strict_schema,
    _parse_json_response,
)
from src.utils.ports import LLMUpstreamError


@dataclass(slots=True)
class Usage:
    """Số đếm cộng dồn của một phương pháp trên một cuộc họp."""

    calls: int = 0
    failed_attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "failed_attempts": self.failed_attempts,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "seconds": round(self.seconds, 1),
        }


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Một model trong ``config.yaml``: tên, endpoint, số lời gọi đồng thời tối đa."""

    name: str
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    max_concurrency: int = 6
    max_output_tokens: int = 8192
    response_mode: str = "json_schema"


@dataclass
class BenchLLM:
    """Client cho một model, dùng chung giữa các luồng (giới hạn đồng thời bằng semaphore).

    Đầu vào: ``ModelConfig``. Mỗi ``generate`` ghi số token vào ``usage`` truyền vào.
    """

    config: ModelConfig
    max_attempts: int = 3
    _semaphore: threading.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self._semaphore = threading.Semaphore(self.config.max_concurrency)
        self._client = _client(
            api_key=os.environ.get(self.config.api_key_env),
            base_url=self.config.base_url or os.environ.get("OPENAI_BASE_URL"),
        )

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: Mapping[str, object],
        usage: Usage,
        temperature: float = 0.0,
    ) -> dict:
        """Một lời gọi structured output; trả dict JSON đã parse.

        Lỗi: ``LLMUpstreamError`` khi hết số lần thử (JSON hỏng, timeout, 5xx) hoặc lỗi không thử lại được.
        """

        if self.config.response_mode == "json_schema":
            response_format: dict = {
                "type": "json_schema",
                "json_schema": {"name": "output", "strict": True, "schema": _openai_strict_schema(schema)},
            }
        else:
            response_format = {"type": "json_object"}
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            try:
                with self._semaphore:
                    response = self._client.chat.completions.create(
                        model=self.config.name,
                        temperature=temperature,
                        messages=messages,
                        response_format=response_format,
                        max_tokens=self.config.max_output_tokens,
                    )
                self._record(usage, response, started)
                return _parse_json_response(response.choices[0].message.content)
            except (_InvalidJSONResponse, *_RETRYABLE_EXCEPTIONS) as exc:
                last_error = exc
            except APIStatusError as exc:
                if exc.status_code < 500:
                    raise LLMUpstreamError(f"{self.config.name}: {exc}") from exc
                last_error = exc
            usage.failed_attempts += 1
            usage.seconds += time.monotonic() - started
            time.sleep(min(30.0, 2.0**attempt))
        raise LLMUpstreamError(f"{self.config.name}: hết {self.max_attempts} lần thử: {last_error}") from last_error

    @staticmethod
    def _record(usage: Usage, response, started: float) -> None:
        usage.calls += 1
        usage.seconds += time.monotonic() - started
        if response.usage is not None:
            usage.prompt_tokens += response.usage.prompt_tokens or 0
            usage.completion_tokens += response.usage.completion_tokens or 0
