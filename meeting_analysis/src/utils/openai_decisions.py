"""Kết nối trực tiếp tới dịch vụ chọn đáp án của OpenAI (dùng cho các bộ phân loại câu nói theo nghĩa),
tự thử lại khi lỗi mạng hoặc máy chủ quá tải.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.openai.com/v1"
_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class OpenAIDecisionsClient:
    """Gọi OpenAI Decisions API qua HTTP, trả kết quả cùng hình dạng như SDK của OpenAI.

    Các bộ phân loại câu nói gọi ``client.decisions.create(...)`` như với SDK; đối tượng này tự trỏ
    ``decisions`` về chính nó để cách gọi đó vẫn đúng.

    Args:
        api_key: Khoá OpenAI dành cho Decisions API.
        base_url: Địa chỉ gốc của API, mặc định ``https://api.openai.com/v1``.
        timeout: Thời gian chờ mỗi lời gọi (giây).
        max_retries: Số lần thử lại thêm khi lỗi mạng hoặc mã HTTP 408/409/429/5xx; 0 là không thử lại.
        client: httpx client thay thế, dùng trong test; None thì tự tạo client kèm khoá.

    Attributes:
        url: Địa chỉ đầy đủ của endpoint ``/decisions``.
        max_retries: Số lần thử lại thêm.
        decisions: Chính đối tượng này, để gọi được ``client.decisions.create``.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30,
        max_retries: int = 2,
        client: Any | None = None,
    ) -> None:
        self.url = base_url.rstrip("/") + "/decisions"
        self.max_retries = max_retries
        self._client = client or httpx.Client(
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=timeout,
        )
        self.decisions = self

    def create(self, *, model: str, input: Any, questions: list[dict[str, Any]], **_: Any) -> Any:
        """Gửi một hoặc nhiều câu hỏi lựa chọn và nhận đáp án kèm xác suất.

        Thử lại ngay (không chờ) khi lỗi mạng hoặc mã HTTP tạm thời, tối đa ``max_retries`` lần.

        Args:
            model: Tên mô hình.
            input: Nội dung cần phân loại (ví dụ đoạn hội thoại), gửi nguyên văn.
            questions: Danh sách câu hỏi theo định dạng Decisions API; phải có ít nhất một câu.
            **_: Tham số khác của SDK, bị bỏ qua.

        Returns:
            ``SimpleNamespace`` có ``answers`` (một đáp án cho mỗi câu hỏi, đúng thứ tự), ``usage``
            (``prompt_tokens``, ``completion_tokens``) và ``model``.

        Raises:
            ValueError: Khi ``questions`` rỗng, hoặc API trả thiếu/sai dạng đáp án.
            httpx.HTTPStatusError: Khi mã HTTP không thử lại được (ví dụ 401), hoặc đã hết lượt thử.
            httpx.TransportError: Khi lỗi mạng vẫn còn sau lượt thử cuối.
        """

        if not questions:
            raise ValueError("Decisions API cần ít nhất một câu hỏi")
        response = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(self.url, json={"model": model, "input": input, "questions": questions})
                response.raise_for_status()
                break
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                retryable = isinstance(exc, httpx.TransportError) or exc.response.status_code in _RETRYABLE_STATUS
                if not retryable or attempt == self.max_retries:
                    raise
        assert response is not None
        payload = response.json()
        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, list) or len(raw_answers) != len(questions):
            raise ValueError("OpenAI Decisions API không trả đủ answers dạng list")
        answers = [_answer(raw) for raw in raw_answers]
        usage = payload.get("usage") or {}
        return SimpleNamespace(
            answers=answers,
            usage=SimpleNamespace(
                prompt_tokens=int(usage.get("input_tokens") or 0),
                completion_tokens=int(usage.get("output_tokens") or 0),
            ),
            model=payload.get("model", model),
        )


def _answer(raw: Any) -> SimpleNamespace:
    """Đổi một đáp án JSON thô thành ``SimpleNamespace`` giống SDK.

    Kết quả có ``type``, ``name``, ``choice``, ``confidence`` và ``probabilities`` (danh sách các
    phần tử có ``value`` và ``probability``).

    Raises:
        ValueError: Khi đáp án không phải object hoặc ``probabilities`` không phải danh sách.
    """

    if not isinstance(raw, dict):
        raise ValueError("OpenAI Decisions API trả answer không phải object")
    probabilities = raw.get("probabilities") or []
    if not isinstance(probabilities, list):
        raise ValueError("OpenAI Decisions API trả probabilities không phải list")
    return SimpleNamespace(
        type=raw.get("type"),
        name=raw.get("name"),
        choice=raw.get("choice"),
        confidence=raw.get("confidence"),
        probabilities=[
            SimpleNamespace(value=item["value"], probability=float(item["probability"])) for item in probabilities
        ],
    )


__all__ = ["DEFAULT_BASE_URL", "OpenAIDecisionsClient"]
