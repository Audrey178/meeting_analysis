"""Kiểm cách thử lại khi gọi mô hình bị lỗi: phân loại lỗi tạm thời hay vĩnh viễn, thử lại ở tầng kết
nối, thử lại ở tầng agent, và việc giới hạn số lời gọi cùng lúc chỉ giữ chỗ trong lúc gọi.

Không gọi mạng: dịch vụ được giả lập trả lần lượt các phản hồi hoặc lỗi định sẵn.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import httpx
import openai
import pytest

from ...utils import openai_adapters
from ...utils.openai_adapters import OpenAIChatJSONAdapter
from ...utils.ports import LLMUpstreamError
from ..shared.throttle import LLMConcurrencyGate
from ..step4_extract import extractors
from ..step4_extract.extractors import extract_topic
from ..step4_extract.registry import build_speaker_registry
from .test_progress import TURNS, _ScriptedLLM, _task

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "string"}}, "note": {"type": "string"}},
    "required": ["items"],
}


def _status_error(cls, status: int):
    request = httpx.Request("POST", "http://gateway/v1/chat/completions")
    return cls(f"HTTP {status}", response=httpx.Response(status, request=request), body=None)


def _reply(payload) -> SimpleNamespace:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class _FakeClient:
    """``client.chat.completions.create`` trả lần lượt ``script`` (phần tử Exception thì ném)."""

    def __init__(self, script, on_create=None):
        self.script = list(script)
        self.temperatures: list[float] = []
        self._on_create = on_create
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.temperatures.append(kwargs["temperature"])
        if self._on_create:
            self._on_create()
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return _reply(item)


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(openai_adapters.time, "sleep", sleeps.append)
    return sleeps


def _adapter(monkeypatch, client, attempts: int = 3) -> OpenAIChatJSONAdapter:
    monkeypatch.setenv("OPENAI_GENERATE_MAX_ATTEMPTS", str(attempts))
    return OpenAIChatJSONAdapter(model="m", client=client, response_mode="json_object")


def _generate(adapter):
    return adapter.generate_json(system_prompt="s", user_prompt="u", schema=SCHEMA)


# ---------------------------------------------------------------------------
# LLMUpstreamError
# ---------------------------------------------------------------------------


def test_error_kind_defaults_keep_timed_out_compatible():
    assert LLMUpstreamError("x").kind == "unknown"
    assert LLMUpstreamError("x", timed_out=True).kind == "timeout"
    assert LLMUpstreamError("x", kind="timeout").timed_out is True
    assert LLMUpstreamError("x", kind="client").retryable is False
    assert LLMUpstreamError("x", kind="fatal").fatal and not LLMUpstreamError("x", kind="server").fatal


# ---------------------------------------------------------------------------
# Adapter OpenAI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (_status_error(openai.AuthenticationError, 401), "fatal"),
        (_status_error(openai.PermissionDeniedError, 403), "fatal"),
        (_status_error(openai.BadRequestError, 400), "client"),
    ],
)
def test_non_retryable_status_raises_classified_error_after_one_call(monkeypatch, no_sleep, error, kind):
    client = _FakeClient([error])

    with pytest.raises(LLMUpstreamError) as caught:
        _generate(_adapter(monkeypatch, client))

    assert caught.value.kind == kind
    assert len(client.temperatures) == 1


def test_exhausted_server_errors_raise_server_kind(monkeypatch, no_sleep):
    client = _FakeClient([_status_error(openai.InternalServerError, 503)] * 3)

    with pytest.raises(LLMUpstreamError) as caught:
        _generate(_adapter(monkeypatch, client))

    assert caught.value.kind == "server" and caught.value.retryable
    assert len(client.temperatures) == 3


def test_off_schema_reply_is_retried_at_higher_temperature(monkeypatch, no_sleep):
    client = _FakeClient([{"note": "thiếu items"}, {"items": ["a"]}])

    assert _generate(_adapter(monkeypatch, client)) == {"items": ["a"]}
    assert client.temperatures[0] == 0.0 and client.temperatures[1] >= 0.4


def test_wrong_container_type_counts_as_off_schema(monkeypatch, no_sleep):
    client = _FakeClient([{"items": "a"}, {"items": ["a"]}])

    assert _generate(_adapter(monkeypatch, client)) == {"items": ["a"]}


def test_off_schema_reply_is_used_when_retries_run_out(monkeypatch, no_sleep):
    # Lần cuối lỗi gateway: vẫn trả câu trả lời lệch schema đã nhận thay vì mất cả chủ đề.
    client = _FakeClient([{"note": "1"}, {"note": "2"}, _status_error(openai.InternalServerError, 500)])

    assert _generate(_adapter(monkeypatch, client)) == {"note": "2"}


def test_request_guard_is_released_while_sleeping_between_retries(monkeypatch):
    semaphore = threading.BoundedSemaphore(1)
    held_during_create: list[bool] = []
    free_during_sleep: list[bool] = []

    def on_create():
        # Suất duy nhất đang bị giữ: thử lấy thêm thì thất bại.
        held_during_create.append(not semaphore.acquire(blocking=False))

    def sleep(_seconds):
        free = semaphore.acquire(blocking=False)
        if free:
            semaphore.release()
        free_during_sleep.append(free)

    monkeypatch.setattr(openai_adapters.time, "sleep", sleep)
    client = _FakeClient([_status_error(openai.InternalServerError, 500), {"items": []}], on_create=on_create)
    adapter = _adapter(monkeypatch, client).with_request_guard(semaphore)

    assert _generate(adapter) == {"items": []}
    assert held_during_create == [True, True]
    assert free_during_sleep == [True]


def test_gate_wraps_openai_adapter_per_request_and_keeps_original_unguarded(monkeypatch):
    original = _adapter(monkeypatch, _FakeClient([]))

    wrapped = LLMConcurrencyGate(2).wrap_llm(original)

    assert isinstance(wrapped, OpenAIChatJSONAdapter) and wrapped is not original
    assert wrapped._client is original._client
    assert original._request_guard().__class__.__name__ == "nullcontext"


# ---------------------------------------------------------------------------
# Vòng extract_attempts của agent
# ---------------------------------------------------------------------------


def _extract(llm):
    return extract_topic(
        "content_agent", llm, _task(TURNS[4:]), build_speaker_registry(TURNS), frozenset({"content"}), attempts=3
    )


@pytest.mark.parametrize(("kind", "calls"), [("unknown", 3), ("server", 3), ("client", 1)])
def test_extract_topic_retries_only_retryable_failures(kind, calls):
    llm = _ScriptedLLM(LLMUpstreamError("lỗi", kind=kind))

    update = _extract(llm)

    assert len(llm.calls) == calls
    assert update["topic_failures"][0].kind == kind


def test_extract_topic_raises_fatal_errors():
    llm = _ScriptedLLM(LLMUpstreamError("401 invalid key", kind="fatal"))

    with pytest.raises(LLMUpstreamError):
        _extract(llm)
    assert len(llm.calls) == 1


def test_extract_topic_isolates_agent_parse_errors(monkeypatch):
    calls: list[str] = []

    def broken(name, llm, task, registry):
        calls.append(name)
        raise TypeError("'NoneType' object is not iterable")

    monkeypatch.setattr(extractors, "call_extractor", broken)

    update = _extract(_ScriptedLLM({}))

    assert calls == ["content_agent"]
    failure = update["topic_failures"][0]
    assert failure.kind == "malformed_output" and "TypeError" in failure.error
    assert update["discussion_points"] == []
