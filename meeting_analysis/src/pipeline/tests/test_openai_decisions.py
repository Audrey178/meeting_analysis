"""Kiểm phần kết nối tới dịch vụ chọn đáp án của OpenAI, không gọi mạng."""

from __future__ import annotations

import httpx
import pytest

from ...utils.openai_decisions import OpenAIDecisionsClient

QUESTION = {
    "type": "choice", "name": "turn_act", "instructions": "Phân loại",
    "choices": [{"value": "assignment", "description": "Giao"}, {"value": "other", "description": "Khác"}],
}
PAYLOAD = {
    "model": "gpt-6-luna",
    "answers": [{"type": "choice", "name": "turn_act", "choice": "assignment", "confidence": 0.98,
                 "probabilities": [{"value": "assignment", "probability": 0.99}, {"value": "other", "probability": 0.01}]}],
    "usage": {"input_tokens": 146, "output_tokens": 0},
}


class _Response:
    def __init__(self, status=200, payload=PAYLOAD):
        self.status_code, self._payload = status, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://x")
            raise httpx.HTTPStatusError("err", request=request, response=httpx.Response(self.status_code, request=request))

    def json(self):
        return self._payload


class _HTTP:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_create_posts_questions_as_list_and_returns_sdk_shaped_answer():
    http = _HTTP([_Response()])
    client = OpenAIDecisionsClient(api_key="k", base_url="https://api.openai.com/v1/", client=http)

    response = client.decisions.create(model="gpt-6-luna", input="LƯỢT CẦN XÉT: ...", questions=[QUESTION])

    url, kwargs = http.calls[0]
    assert url == "https://api.openai.com/v1/decisions"
    assert kwargs["json"] == {"model": "gpt-6-luna", "input": "LƯỢT CẦN XÉT: ...", "questions": [QUESTION]}
    answer = response.answers[0]
    assert (answer.type, answer.choice) == ("choice", "assignment")
    assert {p.value: p.probability for p in answer.probabilities} == pytest.approx({"assignment": 0.99, "other": 0.01})
    assert response.usage.prompt_tokens == 146


def test_retries_server_errors_but_not_auth_errors():
    http = _HTTP([_Response(503), _Response()])
    client = OpenAIDecisionsClient(api_key="k", client=http, max_retries=2)
    assert client.decisions.create(model="m", input="x", questions=[QUESTION]).answers[0].choice == "assignment"
    assert len(http.calls) == 2

    http = _HTTP([_Response(401)])
    client = OpenAIDecisionsClient(api_key="k", client=http, max_retries=2)
    with pytest.raises(httpx.HTTPStatusError):
        client.decisions.create(model="m", input="x", questions=[QUESTION])
    assert len(http.calls) == 1


def test_rejects_empty_questions_and_malformed_answers():
    client = OpenAIDecisionsClient(api_key="k", client=_HTTP([_Response(payload={"answers": {}})]))
    with pytest.raises(ValueError, match="ít nhất một"):
        client.decisions.create(model="m", input="x", questions=[])
    with pytest.raises(ValueError, match="answers"):
        client.decisions.create(model="m", input="x", questions=[QUESTION])
