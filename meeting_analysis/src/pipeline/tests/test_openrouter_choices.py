"""Kiểm phần kết nối tới dịch vụ chọn đáp án qua OpenRouter, không gọi mạng."""

from __future__ import annotations

import pytest

from ...utils.openrouter_decisions import OpenRouterDecisionsClient


def test_openrouter_choices_returns_decisions_compatible_answer():
    captured = {}
    payload = {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {
            "test_choice": {
                "type": "choice",
                "choice": "yes",
                "confidence": 0.8,
                "probabilities": {"yes": 0.8, "no": 0.2},
            },
        },
        "usage": {"inputTokens": 12, "outputTokens": 0, "cost": 0.00001},
    }

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class HTTPClient:
        def post(self, url, **kwargs):
            captured.update(url=url, **kwargs)
            return Response()

    client = OpenRouterDecisionsClient(api_key="test", client=HTTPClient())
    response = client.decisions.create(
        model="typesafe/jev-1.13",
        input="du lieu",
        questions=[{
            "type": "choice",
            "name": "test_choice",
            "instructions": "Chon mot muc",
            "choices": [
                {"value": "yes", "description": "Co"},
                {"value": "no", "description": "Khong"},
            ],
        }],
    )

    answer = response.answers[0]
    assert answer.type == "choice" and answer.choice == "yes"
    assert {p.value: p.probability for p in answer.probabilities} == pytest.approx({"yes": 0.8, "no": 0.2})
    assert response.usage.prompt_tokens == 12
    assert captured["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert captured["json"] == {
        "model": "typesafe/jev-1.13",
        "state": "du lieu",
        "questions": {
            "test_choice": {
                "type": "choice",
                "instructions": "Chon mot muc",
                "criteria": {"yes": "Co", "no": "Khong"},
            },
        },
    }


def test_openrouter_choices_rejects_multiple_questions():
    client = OpenRouterDecisionsClient(api_key="test", client=object())
    with pytest.raises(ValueError, match="ít nhất một"):
        client.decisions.create(model="m", input="x", questions=[])
