"""Đếm lời gọi, token và chi phí USD của từng vai trò LLM trong một lần chạy benchmark.

Bọc OpenAI client mà adapter dùng (``chat.completions.create``, ``decisions.create``) thay vì bọc
``LLMAdapter``: ``generate_json`` chỉ trả JSON đã parse nên mất ``usage``. Mỗi lần thử lại của
adapter là một lời gọi thật nên được đếm riêng. Lời gọi lỗi cũng được đếm: với Decisions, một lời
gọi lỗi (sau khi SDK đã tự thử lại) chính là một lần evidence-check lặng lẽ quay về luật từ khoá.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import partial
from types import SimpleNamespace
from typing import Any

# USD cho 1M token: (input, input đã cache, output). Nguồn: bảng giá OpenAI, cần đối chiếu
# với dashboard sau lần chạy đầu.
PRICES_PER_MTOK: dict[str, tuple[float, float, float]] = {
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    # Decisions API: output miễn phí; chưa rõ giá input đã cache nên tính như input thường.
    "gpt-6-luna": (0.10, 0.10, 0.0),
}
# USD mỗi lời gọi cho model không tính theo token. Chưa biết giá thì để trống:
# lời gọi đó được đếm vào ``unpriced_paid_calls`` thay vì tính 0đ.
PRICES_PER_CALL: dict[str, float] = {}
# Model tự host, không tốn tiền.
FREE_MODEL_PREFIXES = ("google/gemma",)


@dataclass
class RoleUsage:
    """Số liệu cộng dồn của một (vai trò, model)."""

    calls: int = 0
    errors: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0


def _usage_tokens(usage: Any) -> tuple[int, int, int]:
    """(input, input đã cache, output) từ ``response.usage`` của Chat Completions hoặc Responses."""

    if usage is None:
        return 0, 0, 0
    input_tokens = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", 0) or 0
    details = getattr(usage, "prompt_tokens_details", None) or getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) or 0
    return int(input_tokens), int(cached), int(output_tokens)


def price_usd(model: str, stats: RoleUsage) -> float | None:
    """Chi phí USD của ``stats``; None nếu model trả tiền mà chưa có giá.

    Đầu vào: model - tên model như gửi lên API; stats - số liệu cộng dồn.
    Đầu ra: USD, hoặc None.
    """

    if model.startswith(FREE_MODEL_PREFIXES):
        return 0.0
    if model in PRICES_PER_CALL:
        return PRICES_PER_CALL[model] * stats.calls
    if model in PRICES_PER_MTOK:
        price_in, price_cached, price_out = PRICES_PER_MTOK[model]
        fresh = stats.input_tokens - stats.cached_input_tokens
        return (fresh * price_in + stats.cached_input_tokens * price_cached + stats.output_tokens * price_out) / 1e6
    return None


class UsageLedger:
    """Sổ ghi lời gọi LLM theo (vai trò, model), an toàn khi nhiều luồng ghi cùng lúc."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stats: dict[tuple[str, str], RoleUsage] = {}
        self._quota_exhausted = False

    def flag_quota_exhausted(self) -> None:
        """Ghi nhận tài khoản API đã hết tiền (lỗi ``insufficient_quota``)."""

        with self._lock:
            self._quota_exhausted = True

    def record(self, role: str, model: str, *, usage: Any, seconds: float, error: bool) -> None:
        """Ghi một lời gọi.

        Đầu vào: role - vai trò (content/action/...); model - tên model; usage - ``response.usage``
            (None khi lỗi); seconds - thời gian chờ; error - lời gọi có lỗi không.
        """

        input_tokens, cached, output_tokens = _usage_tokens(usage)
        with self._lock:
            stats = self._stats.setdefault((role, model), RoleUsage())
            stats.calls += 1
            stats.errors += int(error)
            stats.input_tokens += input_tokens
            stats.cached_input_tokens += cached
            stats.output_tokens += output_tokens
            stats.seconds += seconds

    def pop_summary(self) -> dict:
        """Tóm tắt mọi lời gọi từ lần gọi trước rồi xoá sổ (một cuộc họp một bản tóm tắt).

        Đầu ra: ``{"roles": [...], "usd_known": float, "unpriced_paid_calls": int, "quota_exhausted": bool}``.
            ``quota_exhausted`` True nghĩa là có lời gọi hỏng vì hết tiền: output của cuộc họp này
            KHÔNG dùng được (Verifier/Decisions lỗi thì pipeline lặng lẽ quay về fallback).
        """

        with self._lock:
            stats, self._stats = self._stats, {}
            quota_exhausted, self._quota_exhausted = self._quota_exhausted, False
        roles, usd_known, unpriced = [], 0.0, 0
        for (role, model), item in sorted(stats.items()):
            usd = price_usd(model, item)
            if usd is None:
                unpriced += item.calls
            else:
                usd_known += usd
            roles.append({"role": role, "model": model, **asdict(item), "usd": usd})
        return {"roles": roles, "usd_known": round(usd_known, 6), "unpriced_paid_calls": unpriced,
                "quota_exhausted": quota_exhausted}


def is_quota_error(exc: Exception) -> bool:
    """Lỗi do tài khoản hết tiền (OpenAI trả 429 với ``code="insufficient_quota"``)."""

    return getattr(exc, "code", None) == "insufficient_quota" or "insufficient_quota" in str(exc)


class _RecordingEndpoint:
    """Thay cho một hàm ``create`` của SDK: gọi hàm thật rồi ghi vào sổ."""

    def __init__(self, create: Callable[..., Any], record: Callable[..., None], on_quota: Callable[[], None]) -> None:
        self._create = create
        self._record = record
        self._on_quota = on_quota

    def create(self, **kwargs: Any) -> Any:
        model = str(kwargs.get("model", "?"))
        started = time.perf_counter()
        try:
            response = self._create(**kwargs)
        except Exception as exc:
            self._record(model, usage=None, seconds=time.perf_counter() - started, error=True)
            if is_quota_error(exc):
                self._on_quota()
            raise
        self._record(model, usage=getattr(response, "usage", None), seconds=time.perf_counter() - started, error=False)
        return response


class RecordingClient:
    """Thay cho ``openai.OpenAI`` trong adapter: ghi mọi lời gọi vào ``ledger`` dưới tên ``role``.

    Chỉ lộ ra hai endpoint pipeline dùng (``chat.completions`` và ``decisions``).
    """

    def __init__(self, inner: Any, ledger: UsageLedger, role: str) -> None:
        record = partial(ledger.record, role)
        on_quota = ledger.flag_quota_exhausted
        self.chat = SimpleNamespace(completions=_RecordingEndpoint(inner.chat.completions.create, record, on_quota))
        decisions = getattr(inner, "decisions", None)
        self.decisions = _RecordingEndpoint(decisions.create, record, on_quota) if decisions is not None else None


def record_adapter_calls(adapter: Any, ledger: UsageLedger, role: str) -> Any:
    """Cho ``OpenAIChatJSONAdapter`` ghi lời gọi vào ``ledger`` (đổi client nội bộ của nó).

    Đầu vào: adapter - ``OpenAIChatJSONAdapter``; ledger - sổ ghi; role - tên vai trò.
    Đầu ra: chính ``adapter``.
    """

    adapter._client = RecordingClient(adapter._client, ledger, role)
    return adapter


__all__ = ["PRICES_PER_CALL", "PRICES_PER_MTOK", "RecordingClient", "UsageLedger", "record_adapter_calls"]
