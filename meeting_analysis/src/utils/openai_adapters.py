"""Kết nối tới các dịch vụ mô hình tương thích chuẩn OpenAI (ví dụ một máy chủ tự dựng chạy mô hình
Qwen), dùng để sinh kết quả dạng JSON.

Phần này không bắt buộc: chỉ cần khi dùng đúng các kết nối này, và có thể thay bằng bất kỳ cách
kết nối nào khác có cùng cách dùng. Khi gọi lỗi, nó tự thử lại với lỗi tạm thời và phân loại lỗi để
tầng trên quyết định có dừng hay không.
"""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import os
import random
import time
from collections.abc import Callable, Mapping
from typing import ContextManager
from dotenv import load_dotenv

import httpx

from .llm_call_log import current_llm_label
from .ports import LLMErrorKind, LLMUpstreamError

load_dotenv()

try:
    from openai import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        OpenAI,
        RateLimitError,
    )
except ImportError as exc:  # pragma: no cover - exercised only without openai installed
    raise ImportError(
        "meeting_analysis.openai_adapters requires the 'openai' package "
        "(`pip install openai`). The dependency-free core does not need it "
        "unless you import this module."
    ) from exc

logger = logging.getLogger(__name__)



_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_CONNECTIONS = 10
# The SDK's own retry (httpx-level) retries blind and silent -- the caller
# only ever sees the final exception, with no sign retries even happened.
# ``OpenAIChatJSONAdapter.generate_json`` below owns retry/backoff instead
# (with a log line per attempt), so the SDK client itself defaults to no
# retries to avoid stacking two independent, invisible retry loops.
_DEFAULT_MAX_RETRIES = 0
# generate_json's own retry loop: total attempts (including the first) for
# a transient failure (timeout, connection error, 5xx) before it gives up and
# raises -- letting the caller (stage 7's label_topics) fall back to a
# non-LLM title instead of stalling forever on a wedged gateway.
_DEFAULT_GENERATE_MAX_ATTEMPTS = 4
_DEFAULT_GENERATE_BACKOFF_SECONDS = 2.0
# Rate limits (429) get their own, larger attempt budget: under concurrent
# pipeline load they're self-inflicted (too many calls in the gateway's 60s
# window) and clear on their own once the window rolls over, unlike a
# timeout/connection error which more likely means the gateway is actually
# wedged. Capping the backoff (below) keeps 8 attempts from ballooning past
# the window they're waiting out.
_DEFAULT_GENERATE_MAX_ATTEMPTS_RATE_LIMIT = 8
_MAX_RATE_LIMIT_BACKOFF_SECONDS = 30.0
# Plain connection errors (refused/reset -- NOT a timeout) fail in a fraction
# of a second, so 4 attempts only covered ~15s of backoff: a ~15s gateway
# blip was enough to make ``action_decision_agent`` lose a whole topic (seen
# in a real run: "Connection error" x4 -> segment skipped). They get a
# bigger budget with the same capped backoff as rate limits (~60s total
# with the defaults). A timeout (``APITimeoutError``, a subclass of
# ``APIConnectionError``) burns a full request timeout per attempt, so it
# keeps the small budget above.
_DEFAULT_GENERATE_MAX_ATTEMPTS_CONNECTION = 6
_RETRYABLE_EXCEPTIONS = (APITimeoutError, APIConnectionError, RateLimitError)
# At temperature 0 a malformed-JSON sample is reproduced byte for byte on
# every retry (seen: gemma broke at the same char on attempts 1 and 3, and
# the segment was dropped after 155s). Retries after an invalid-JSON response
# therefore sample at least this temperature, so the retry can differ.
_DEFAULT_INVALID_JSON_RETRY_TEMPERATURE = 0.4


def _positive_float_env(name: str, default: float) -> float:
    """Đọc số thực dương từ biến môi trường ``name``; thiếu, rỗng, sai dạng hoặc <= 0 thì trả ``default``."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _retry_after_seconds(exc: Exception) -> float | None:
    """Lấy thời gian chờ (giây) mà máy chủ gợi ý trong header của lỗi 429, nếu có.

    Đọc ``Retry-After``, rồi ``x-ratelimit-reset-requests`` (một số cổng tương thích OpenAI dùng).
    Máy chủ biết chính xác cửa sổ giới hạn còn bao lâu, nên tin con số này hơn tự đoán. Header không
    phải số (ví dụ dạng ngày giờ) bị bỏ qua.

    Returns:
        Số giây chờ (>= 0), hoặc None nếu không có header dùng được.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    for header in ("retry-after", "x-ratelimit-reset-requests"):
        raw = headers.get(header)
        if raw is None:
            continue
        try:
            return max(float(raw), 0.0)
        except ValueError:
            continue
    return None


def _non_negative_int_env(name: str, default: int) -> int:
    """Đọc số nguyên >= 0 từ biến môi trường ``name``; thiếu, rỗng, sai dạng hoặc âm thì trả ``default``."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _client(*, api_key: str | None, base_url: str | None) -> OpenAI:
    """Tạo client OpenAI với thời gian chờ ngắn, không giữ kết nối, không tự thử lại (lý do ở comment).

    Args:
        api_key: Khoá API; None thì lấy ``OPENAI_API_KEY`` từ môi trường.
        base_url: Địa chỉ máy chủ tương thích OpenAI; None thì dùng mặc định của SDK.
    """
    # Two deliberate departures from the SDK defaults, both measured against
    # the self-hosted gateway rather than assumed:
    #
    # 1. Timeout. The default is 600s with 2 retries, so a single stalled
    #    request costs ~30 minutes with nothing in the log to show for it.
    #    The gateway usually answers a healthy chat call in ~1s, but under
    #    load has been observed to genuinely take tens of seconds rather
    #    than being wedged, so 60s gives that headroom without approaching
    #    the old 30-minute worst case; retries are handled one level up in
    #    ``OpenAIChatJSONAdapter.generate_json`` instead of here (see
    #    ``_DEFAULT_MAX_RETRIES``).
    #
    # 2. No keep-alive. When one request stalls and we abandon it, the
    #    pooled connection is left mid-response; every later request that
    #    reuses it fails instantly with APIConnectionError. Labeling nine
    #    topic segments over a shared pool therefore lost segments 6-9 to a
    #    single bad segment 5, while the same nine on a fresh connection
    #    each lost only segment 5. The extra TCP+TLS handshake costs ~0.07s
    #    per call, which is not worth arguing with.
    #
    # The connection cap is a hard ceiling on concurrent calls per client:
    # callers that allow more in flight (src/pipeline's LLM gates) just queue
    # in the pool, so ``OPENAI_MAX_CONNECTIONS`` must be >= those limits.
    http_client = httpx.Client(
        limits=httpx.Limits(
            max_keepalive_connections=0,
            max_connections=_non_negative_int_env("OPENAI_MAX_CONNECTIONS", _DEFAULT_MAX_CONNECTIONS) or 1,
        ),
    )
    return OpenAI(
        api_key=api_key or os.environ.get("OPENAI_API_KEY"),
        base_url=base_url,
        http_client=http_client,
        timeout=_positive_float_env("OPENAI_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS),
        max_retries=_non_negative_int_env("OPENAI_MAX_RETRIES", _DEFAULT_MAX_RETRIES),
    )


def _openai_strict_schema(schema: Mapping[str, object]) -> dict:
    """Đổi schema ``{properties, required}`` sang dạng nghiêm ngặt của OpenAI Structured Outputs.

    Ở dạng nghiêm ngặt, mọi thuộc tính phải nằm trong ``required`` và mọi object phải có
    ``additionalProperties: False``, ở MỌI cấp lồng nhau. Vì vậy trường mà bên gọi để tuỳ chọn được
    chuyển thành "có thể null" thay vì "có thể vắng". Thứ tự thuộc tính được giữ nguyên, nên prompt
    yêu cầu mô hình viết bằng chứng trước kết luận thì thứ tự đó đi đúng tới máy chủ.

    Args:
        schema: JSON schema gốc của bên gọi; không bị sửa.

    Returns:
        Schema mới ở dạng nghiêm ngặt.
    """

    return _strict_node(dict(schema))


def _strict_node(node: dict) -> dict:
    """Chuyển một nút schema sang dạng nghiêm ngặt, đệ quy vào thuộc tính object và phần tử mảng."""
    node = dict(node)
    if node.get("type") == "object" and "properties" in node:
        properties = dict(node.get("properties", {}) or {})
        required = set(node.get("required", []) or [])
        strict_properties: dict[str, object] = {}
        for name, spec in properties.items():
            spec = _strict_node(dict(spec))
            if name not in required:
                original_type = spec.get("type")
                if isinstance(original_type, str):
                    spec["type"] = [original_type, "null"]
            strict_properties[name] = spec
        node["properties"] = strict_properties
        node["required"] = list(properties.keys())
        node["additionalProperties"] = False
    elif node.get("type") == "array" and "items" in node:
        node["items"] = _strict_node(dict(node["items"]))
    return node


class _InvalidJSONResponse(Exception):
    """Máy chủ trả thành công nhưng nội dung không phải object JSON dùng được.

    Cũng dùng khi JSON đọc được nhưng thiếu khoá bắt buộc ở cấp ngoài cùng. Ở chế độ ``json_object``
    (máy chủ không ép theo schema), object đôi khi bị cắt giữa chừng hoặc có object thứ hai theo sau.
    Lấy mẫu lại thường ổn, nên lỗi này được thử lại như lỗi tạm thời thay vì báo hỏng ngay.
    """


_CODE_FENCE_PREFIX = "```json"
_JSON_LITERALS = ("true", "false", "null")


def _quote_closes_string(text: str, pos: int) -> bool:
    """Cho biết dấu ``"`` ở vị trí ``pos`` (đang trong một chuỗi) có thật sự đóng chuỗi đó không.

    Dấu đóng chuỗi thật được theo sau bởi ``:``, ``}``, ``]``, hết văn bản, hoặc ``,`` mở đầu giá trị
    hay khoá kế tiếp. Còn lại (một chữ cái, khoảng trắng rồi một từ) nghĩa là mô hình viết dấu nháy
    nằm trong câu văn.
    """

    rest = text[pos + 1:].lstrip()
    if not rest or rest[0] in ":}]":
        return True
    if rest[0] != ",":
        return False
    after = rest[1:].lstrip()
    if not after or after[0] in '"{[-' or after[0].isdigit():
        return True
    return any(
        after.startswith(lit) and not after[len(lit):len(lit) + 1].isalpha()
        for lit in _JSON_LITERALS
    )


def _escape_inner_quotes(text: str) -> str:
    """Thêm ký tự thoát cho các dấu ``"`` chưa thoát nằm bên trong giá trị chuỗi.

    Mô hình hay trích nguyên tên gọi có dấu nháy mà không thoát, ví dụ ``tên gọi "Đề án X"``, và lấy
    mẫu lại vẫn lặp lỗi đó, nên sửa trực tiếp thay vì thử lại.
    """

    out: list[str] = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string and ch == "\\":
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == '"':
            if not in_string:
                in_string = True
            elif _quote_closes_string(text, i):
                in_string = False
            else:
                out.append('\\"')
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_json_response(content: str | None) -> dict:
    """Giải mã câu trả lời của mô hình thành dict, chịu được khung code và chữ thừa phía sau.

    Bỏ khung code Markdown, rồi giải mã object JSON ĐẦU TIÊN và bỏ qua mọi thứ phía sau (object thứ
    hai, lời giải thích). Nếu lỗi, thử sửa dấu nháy chưa thoát rồi giải mã lại; sửa được thì ghi
    cảnh báo.

    Args:
        content: Nội dung văn bản mô hình trả về; có thể None.

    Returns:
        Object JSON đã giải mã.

    Raises:
        _InvalidJSONResponse: Khi không có nội dung, không giải mã được, hoặc kết quả không phải
            object. Thông điệp kèm đoạn đầu nội dung và đoạn quanh chỗ lỗi để dễ xem log.
    """

    if content is None:
        raise _InvalidJSONResponse("OpenAI chat response had no JSON content")
    text = content.strip()
    if text.startswith(_CODE_FENCE_PREFIX):
        text = text[len(_CODE_FENCE_PREFIX):]
    text = text.strip("`").strip()
    start = max(text.find("{"), 0)
    decoder = json.JSONDecoder()
    try:
        parsed, _ = decoder.raw_decode(text, start)
    except json.JSONDecodeError as exc:
        try:
            parsed, _ = decoder.raw_decode(_escape_inner_quotes(text[start:]))
        except json.JSONDecodeError:
            # The break is often far past the first 300 chars (an unescaped quote
            # inside a long Vietnamese string), so also show the text around it.
            around = text[max(0, exc.pos - 150): exc.pos + 80]
            raise _InvalidJSONResponse(
                f"OpenAI chat response was not valid JSON: {exc}; content starts: {content[:300]!r}"
                f"; around error: {around!r}"
            ) from exc
        logger.warning("Repaired unescaped quotes in OpenAI chat JSON response")
    if not isinstance(parsed, dict):
        raise _InvalidJSONResponse("OpenAI chat response must decode to a JSON object")
    return parsed


# Statuses after which every later call fails too (bad key, no balance,
# forbidden model): ``LLMUpstreamError.fatal`` lets the pipeline stop the run.
_FATAL_STATUS_CODES = frozenset({401, 402, 403})


def _error_kind(exc: Exception) -> LLMErrorKind:
    """Phân loại một lần gọi hỏng thành ``LLMErrorKind`` để gắn vào ``LLMUpstreamError``.

    Mã 401/402/403 là ``"fatal"``; mã 4xx khác là ``"client"``; 5xx là ``"server"``.
    """

    if isinstance(exc, _InvalidJSONResponse):
        return "invalid_json"
    if isinstance(exc, APITimeoutError):
        return "timeout"
    if isinstance(exc, APIConnectionError):
        return "connection"
    if isinstance(exc, RateLimitError):
        return "rate_limit"
    if isinstance(exc, APIStatusError):
        if exc.status_code >= 500:
            return "server"
        return "fatal" if exc.status_code in _FATAL_STATUS_CODES else "client"
    return "unknown"


def _top_level_mismatch(parsed: Mapping[str, object], schema: Mapping[str, object]) -> str | None:
    """Kiểm câu trả lời có khớp cấp ngoài cùng của schema không.

    Chỉ kiểm mỗi khoá ``required`` có mặt và thuộc tính kiểu mảng/object thật sự là list/dict. Chế độ
    ``json_schema`` đã được máy chủ ép điều này; chế độ ``json_object`` thì không, và nếu không kiểm,
    câu trả lời thiếu khoá (ví dụ thiếu danh sách việc giao) sẽ bị hiểu nhầm là "không có việc nào"
    thay vì là một mẫu hỏng. Các phần tử lồng bên trong để agent tự kiểm: agent bỏ phần tử hỏng mà
    không mất phần còn lại.

    Returns:
        Mô tả lý do không khớp, hoặc None nếu khớp.
    """

    properties = schema.get("properties") or {}
    for key in schema.get("required") or ():
        if key not in parsed:
            return f"missing required key {key!r}"
    for key, spec in properties.items():
        value = parsed.get(key)
        if value is None or not isinstance(spec, Mapping):
            continue
        expected = spec.get("type")
        if expected == "array" and not isinstance(value, list):
            return f"key {key!r} must be an array, got {type(value).__name__}"
        if expected == "object" and not isinstance(value, dict):
            return f"key {key!r} must be an object, got {type(value).__name__}"
    return None


class OpenAIChatJSONAdapter:
    """Kết nối LLM theo hợp đồng ``LLMAdapter``, gọi qua API Chat Completions chuẩn OpenAI.

    Mặc định dùng chế độ JSON schema nghiêm ngặt (Structured Outputs), chạy được với cả OpenAI thật
    lẫn máy chủ tương thích như vLLM/Qwen. Với máy chủ chỉ hỗ trợ "trả JSON hợp lệ" mà không ép schema,
    dùng ``response_mode="json_object"``; khi đó schema được chép vào system prompt.

    Số lần thử lại, thời gian chờ, nhiệt độ khi thử lại... đọc từ các biến môi trường ``OPENAI_*``
    (xem các hằng mặc định ở đầu file).

    Args:
        model: Tên mô hình; None thì lấy ``MODEL_NAME`` từ môi trường, mặc định ``gpt-4o-mini``.
        api_key: Khoá API; None thì lấy ``OPENAI_API_KEY``.
        base_url: Địa chỉ máy chủ; None thì lấy ``OPENAI_BASE_URL``, không có thì dùng OpenAI.
        client: Client OpenAI có sẵn (ví dụ trong test); khi có thì bỏ qua ``api_key``/``base_url``.
        temperature: Nhiệt độ lấy mẫu cho lần gọi đầu.
        response_mode: ``"json_schema"`` hoặc ``"json_object"``.
        extra_body: Trường thêm gửi kèm mỗi yêu cầu (tuỳ máy chủ), None nếu không có.

    Raises:
        ValueError: Khi ``response_mode`` không hợp lệ.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        client: OpenAI | None = None,
        temperature: float = 0.0,
        response_mode: str = "json_schema",
        extra_body: Mapping[str, object] | None = None,
    ) -> None:
        if response_mode not in {"json_schema", "json_object"}:
            raise ValueError("response_mode must be 'json_schema' or 'json_object'")
        self.model = model or os.environ.get("MODEL_NAME", "gpt-4o-mini")
        self.temperature = temperature
        self.response_mode = response_mode
        self.extra_body = dict(extra_body) if extra_body else None

        self.max_output_tokens = _non_negative_int_env("OPENAI_MAX_OUTPUT_TOKENS", 0)
        self._client = client or _client(
            api_key=api_key,
            base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
        )
        self._generate_max_attempts = _non_negative_int_env(
            "OPENAI_GENERATE_MAX_ATTEMPTS", _DEFAULT_GENERATE_MAX_ATTEMPTS
        ) or 1
        self._generate_max_attempts_rate_limit = _non_negative_int_env(
            "OPENAI_GENERATE_MAX_ATTEMPTS_RATE_LIMIT",
            _DEFAULT_GENERATE_MAX_ATTEMPTS_RATE_LIMIT,
        ) or 1
        self._generate_max_attempts_connection = _non_negative_int_env(
            "OPENAI_GENERATE_MAX_ATTEMPTS_CONNECTION",
            _DEFAULT_GENERATE_MAX_ATTEMPTS_CONNECTION,
        ) or 1
        self._invalid_json_retry_temperature = _positive_float_env(
            "OPENAI_INVALID_JSON_RETRY_TEMPERATURE", _DEFAULT_INVALID_JSON_RETRY_TEMPERATURE
        )
        self._generate_backoff_seconds = _positive_float_env(
            "OPENAI_GENERATE_BACKOFF_SECONDS", _DEFAULT_GENERATE_BACKOFF_SECONDS
        )
        # Held around each HTTP request only, never across a backoff sleep
        # (``with_request_guard``).
        self._request_guard: Callable[[], ContextManager[object]] = contextlib.nullcontext

    def with_request_guard(self, guard: ContextManager[object]) -> OpenAIChatJSONAdapter:
        """Tạo bản sao giữ ``guard`` quanh từng yêu cầu HTTP, nhưng nhả ra khi đang chờ để thử lại.

        Dùng để giới hạn số lời gọi đồng thời (ví dụ semaphore của pipeline). Nếu giữ suất cả lúc chờ,
        khi máy chủ treo mọi suất sẽ bị chiếm bởi các lời gọi đang ngủ. Bản sao dùng chung HTTP client
        với bản gốc; bản gốc không bị đổi.

        Args:
            guard: Context manager cần giữ trong lúc gửi yêu cầu.

        Returns:
            Bản sao của kết nối này.
        """

        guarded = copy.copy(self)
        guarded._request_guard = lambda: guard
        return guarded

    @property
    def model_name(self) -> str:
        """Tên hiển thị của mô hình, dạng ``openai-chat:<tên mô hình>``."""
        return f"openai-chat:{self.model}"

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema: Mapping[str, object]
    ) -> Mapping[str, object]:
        """Gọi mô hình và trả về một object JSON khớp schema, tự thử lại khi lỗi tạm thời.

        Lỗi tạm thời (hết thời gian chờ, lỗi kết nối, giới hạn tần suất, 5xx, JSON hỏng hoặc thiếu
        khoá) được thử lại với thời gian chờ tăng gấp đôi mỗi lần, có thêm chút ngẫu nhiên. Giới hạn
        tần suất và lỗi kết nối có số lượt thử riêng, lớn hơn; giới hạn tần suất ưu tiên thời gian chờ
        máy chủ gợi ý. Sau một lần JSON hỏng, các lần sau lấy mẫu với nhiệt độ cao hơn để kết quả
        khác đi. Mỗi lần thử lại ghi một cảnh báo kèm nhãn lời gọi.

        Nếu hết lượt mà trước đó đã có một câu trả lời đọc được nhưng thiếu khoá, trả câu trả lời đó
        (agent coi khoá thiếu là rỗng) thay vì mất cả chủ đề.

        Args:
            system_prompt: Chỉ dẫn hệ thống.
            user_prompt: Nội dung người dùng (dữ liệu cuộc họp...).
            schema: JSON schema ``{"properties": ..., "required": ...}`` của kết quả mong muốn.

        Returns:
            Object JSON đã giải mã.

        Raises:
            LLMUpstreamError: Khi hết lượt thử, gặp lỗi không thử lại được (4xx, sai khoá, hết tiền),
                hoặc lỗi bất ngờ khác; ``kind`` cho biết loại lỗi.
        """
        if self.response_mode == "json_schema":
            response_format: dict = {
                "type": "json_schema",
                "json_schema": {
                    "name": "output",
                    "strict": True,
                    "schema": _openai_strict_schema(schema),
                },
            }
        else:
            # json_object mode never sends the schema to the server, so the
            # model only knows the field names if the prompt spells them out.
            response_format = {"type": "json_object"}
            system_prompt = (
                f"{system_prompt}\n\nReturn exactly one JSON object matching this JSON schema:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        attempt = 0
        temperature = self.temperature
        # Last reply that parsed but missed the top-level schema: returned if
        # the retries run out, since the agents read a missing key as empty --
        # better than losing the whole topic.
        off_schema_reply: dict | None = None
        while True:
            attempt += 1
            try:
                with self._request_guard():
                    response = self._client.chat.completions.create(
                        model=self.model,
                        temperature=temperature,
                        messages=messages,
                        response_format=response_format,
                        extra_body=self.extra_body,
                        **({"max_tokens": self.max_output_tokens} if self.max_output_tokens else {}),
                    )
                parsed = _parse_json_response(response.choices[0].message.content)
                mismatch = _top_level_mismatch(parsed, schema)
                if mismatch is None:
                    return parsed
                off_schema_reply = parsed
                raise _InvalidJSONResponse(f"OpenAI chat response off-schema: {mismatch}")
            except (_InvalidJSONResponse, *_RETRYABLE_EXCEPTIONS) as exc:
                last_exc: Exception = exc
                retryable = True
            except APIStatusError as exc:
                last_exc = exc
                retryable = exc.status_code >= 500
            except Exception as exc:
                raise LLMUpstreamError(
                    f"Error occurred while generating JSON: {exc}"
                ) from exc
            # `except ... as exc` auto-unbinds `exc` once its block exits
            # (Python deletes it to avoid a traceback reference cycle), so
            # everything below must read `last_exc`, saved inside the block,
            # not `exc`.
            if isinstance(last_exc, _InvalidJSONResponse):
                temperature = max(temperature, self._invalid_json_retry_temperature)
            is_rate_limit = isinstance(last_exc, RateLimitError)
            is_connection_error = isinstance(
                last_exc, APIConnectionError
            ) and not isinstance(last_exc, APITimeoutError)
            if is_rate_limit:
                max_attempts = self._generate_max_attempts_rate_limit
            elif is_connection_error:
                max_attempts = self._generate_max_attempts_connection
            else:
                max_attempts = self._generate_max_attempts
            if not retryable or attempt >= max_attempts:
                if retryable and off_schema_reply is not None:
                    logging.warning(
                        "LLM call [%s] gave up after %d attempt(s) (%s); using an earlier off-schema reply",
                        current_llm_label(),
                        attempt,
                        last_exc,
                    )
                    return off_schema_reply
                raise LLMUpstreamError(
                    f"Error occurred while generating JSON after {attempt} "
                    f"attempt(s): {last_exc}",
                    kind=_error_kind(last_exc),
                ) from last_exc
            if is_rate_limit:
                backoff = _retry_after_seconds(last_exc)
                if backoff is None:
                    backoff = min(
                        self._generate_backoff_seconds * (2 ** (attempt - 1)),
                        _MAX_RATE_LIMIT_BACKOFF_SECONDS,
                    )
            elif is_connection_error:
                backoff = min(
                    self._generate_backoff_seconds * (2 ** (attempt - 1)),
                    _MAX_RATE_LIMIT_BACKOFF_SECONDS,
                )
            else:
                backoff = self._generate_backoff_seconds * (2 ** (attempt - 1))
            backoff += random.uniform(0, backoff * 0.25)
            cause = last_exc.__cause__
            reason = f"{last_exc} ({type(cause).__name__}: {cause})" if cause else str(last_exc)
            logging.warning(
                "LLM call failed [%s] (attempt %d/%d): %s -- retrying in %.1fs",
                current_llm_label(),
                attempt,
                max_attempts,
                reason,
                backoff,
            )
            time.sleep(backoff)


__all__ = [
    "OpenAIChatJSONAdapter",
]
