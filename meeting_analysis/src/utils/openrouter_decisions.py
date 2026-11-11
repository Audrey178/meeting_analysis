"""Kết nối tới dịch vụ chọn đáp án qua OpenRouter, dùng thay được cho kết nối OpenAI trong các bộ phân
loại câu nói theo nghĩa.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx


DEFAULT_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"


class OpenRouterDecisionsClient:
    """Gọi JEV trên OpenRouter nhưng giữ đúng cách gọi ``decisions.create`` của OpenAI.

    Các bộ phân loại câu nói trong pipeline viết theo dạng OpenAI Decisions API: gửi danh sách câu
    hỏi, đọc ``response.answers[0]``... OpenRouter lại dùng object khoá theo tên câu hỏi. Lớp này chỉ
    chuyển đổi qua lại giữa hai dạng đó; xác suất trả về lấy thẳng từ JEV, không phải do mô hình tự
    viết ra trong JSON. Thuộc tính không có trên lớp được chuyển tiếp sang httpx client bên trong.

    Args:
        api_key: Khoá OpenRouter.
        url: Địa chỉ endpoint decisions của OpenRouter.
        timeout: Thời gian chờ mỗi lời gọi (giây).
        max_retries: Số lần thử lại thêm khi lỗi mạng hoặc mã HTTP 408/409/429/5xx; 0 là không thử lại.
        client: httpx client thay thế, dùng trong test; None thì tự tạo client kèm khoá.

    Attributes:
        url: Địa chỉ endpoint.
        max_retries: Số lần thử lại thêm.
        decisions: Chính đối tượng này, để gọi được ``client.decisions.create``.
    """

    def __init__(
        self,
        *,
        api_key: str,
        url: str = DEFAULT_DECISIONS_URL,
        timeout: float = 30,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        self.url = url
        self.max_retries = max_retries
        self._client = client or httpx.Client(
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self.decisions = self

    def create(self, *, model: str, input: Any, questions: list[dict[str, Any]], **_: Any) -> Any:
        """Gửi các câu hỏi lựa chọn tới JEV và trả kết quả theo dạng OpenAI Decisions API.

        Chỉ hỗ trợ câu hỏi ``type="choice"`` có danh sách lựa chọn; mô tả của từng lựa chọn được gửi
        làm tiêu chí. Thử lại ngay (không chờ) khi lỗi mạng hoặc mã HTTP tạm thời.

        Args:
            model: Tên mô hình trên OpenRouter.
            input: Nội dung cần phân loại, gửi làm trạng thái (``state``) cho JEV.
            questions: Danh sách câu hỏi dạng OpenAI; tên câu hỏi không được trùng.
            **_: Tham số khác của SDK, bị bỏ qua.

        Returns:
            ``SimpleNamespace`` có ``answers`` (đúng thứ tự ``questions``; mỗi đáp án có ``type``,
            ``choice``, ``confidence``, ``probabilities``), ``choices`` (luôn rỗng), ``usage``
            (``prompt_tokens``, ``completion_tokens``), ``cost`` (có thể None) và ``model``.

        Raises:
            ValueError: Khi không có câu hỏi, tên trùng, câu hỏi không phải dạng lựa chọn, hoặc
                OpenRouter trả thiếu/sai dạng đáp án.
            httpx.HTTPStatusError: Khi mã HTTP không thử lại được, hoặc đã hết lượt thử.
            httpx.TransportError: Khi lỗi mạng vẫn còn sau lượt thử cuối.
        """
        if not questions:
            raise ValueError("JEV cần ít nhất một câu hỏi")
        question_map: dict[str, dict[str, Any]] = {}
        ordered_names: list[str] = []
        for question in questions:
            name = str(question["name"])
            if name in question_map:
                raise ValueError(f"Tên câu hỏi JEV bị trùng: {name}")
            choices = question.get("choices") or []
            if question.get("type") != "choice" or not choices:
                raise ValueError("Adapter hiện chỉ hỗ trợ câu hỏi JEV type=choice có choices")
            ordered_names.append(name)
            question_map[name] = {
                "type": "choice",
                "instructions": question.get("instructions", ""),
                "criteria": {choice["value"]: choice.get("description", "") for choice in choices},
            }

        response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(
                    self.url,
                    json={"model": model, "state": input, "questions": question_map},
                )
                response.raise_for_status()
                break
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                retryable = isinstance(exc, httpx.TransportError) or exc.response.status_code in {
                    408, 409, 429, 500, 502, 503, 504,
                }
                if not retryable or attempt == self.max_retries:
                    raise
        assert response is not None
        payload = response.json()
        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, dict):
            raise ValueError("OpenRouter Decisions API không trả answers dạng object")

        answers = []
        for name in ordered_names:
            raw = raw_answers.get(name)
            if not isinstance(raw, dict) or raw.get("type") != "choice":
                raise ValueError(f"OpenRouter Decisions API không trả choice cho câu hỏi {name}")
            probabilities = raw.get("probabilities")
            if not isinstance(probabilities, dict):
                raise ValueError(f"OpenRouter Decisions API không trả probabilities cho câu hỏi {name}")
            answers.append(SimpleNamespace(
                type="choice",
                choice=raw.get("choice"),
                confidence=raw.get("confidence"),
                probabilities=[
                    SimpleNamespace(value=value, probability=float(probability))
                    for value, probability in probabilities.items()
                ],
            ))

        usage = payload.get("usage") or {}
        prompt_tokens = _usage_value(usage, "prompt_tokens", "input_tokens", "promptTokens", "inputTokens")
        completion_tokens = _usage_value(
            usage, "completion_tokens", "output_tokens", "completionTokens", "outputTokens"
        )
        return SimpleNamespace(
            answers=answers,
            choices=[],
            usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
            cost=usage.get("cost"),
            model=payload.get("model", model),
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _usage_value(usage: dict[str, Any], *names: str) -> int:
    """Lấy số token ở khoá đầu tiên có mặt trong ``names`` (mỗi nhà cung cấp đặt tên khác); thiếu thì 0."""
    for name in names:
        value = usage.get(name)
        if value is not None:
            return int(value)
    return 0


__all__ = ["DEFAULT_DECISIONS_URL", "OpenRouterDecisionsClient"]
