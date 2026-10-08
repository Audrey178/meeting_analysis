"""Optional OpenAI(-compatible) adapters for meeting_analysis ports.

NOT part of the dependency-free core (``pyproject.toml`` keeps
``dependencies = []``): importing this module requires the ``openai`` package
to be installed, and is only needed by callers who explicitly inject one of
these adapters. Every class here implements a plain ``Protocol`` from
``ports.py`` -- any other implementation is an equally valid drop-in
replacement; this is a worked reference, not the only correct choice.

Two separate endpoints are expected, matching how this project's ``.env`` is
actually set up (verified empirically, not assumed):

- ``OPENAI_BASE_URL`` / ``OPENAI_API_KEY`` point at a **chat-only**
  OpenAI-compatible gateway (e.g. a self-hosted vLLM serving a Qwen model).
  It has no embeddings endpoint. :class:`OpenAIChatJSONAdapter` uses this.
- Embeddings need the **real** OpenAI API (``https://api.openai.com/v1``),
  which the same ``OPENAI_API_KEY`` in this project happens to also be valid
  for. :class:`OpenAIEmbeddingClient` defaults there and deliberately does
  NOT inherit ``OPENAI_BASE_URL``, so it does not silently point at the
  chat-only gateway (which 404s on ``/embeddings``). Override via
  ``OPENAI_EMBEDDING_BASE_URL`` if your embeddings live somewhere else.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import time
from collections.abc import Mapping
from openai import OpenAI
from dotenv import load_dotenv

import httpx

from .llm_call_log import current_llm_label
from .ports import LLMUpstreamError

load_dotenv()

try:
    from openai import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        BadRequestError,
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


_DEFAULT_EMBEDDING_BASE_URL = "https://api.openai.com/v1"


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


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _retry_after_seconds(exc: Exception) -> float | None:
    """Extract a server-suggested wait from a RateLimitError's headers, if any.

    A 429 with a ``Retry-After`` (or ``x-ratelimit-reset-requests``, seen on
    some OpenAI-compatible gateways) header is telling us exactly how long
    its rate-limit window has left -- trust that over our own guess.
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
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _client(*, api_key: str | None, base_url: str | None) -> OpenAI:
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
    # callers that allow more in flight (agentic_v3's LLM gates) just queue
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


class OpenAIEmbeddingClient:
    """Fetches and caches embeddings; shared by the two adapter wrappers
    below so Stage 6 (segmentation) and Stage 8 (recurrence) reuse the same
    calls instead of re-embedding identical chunk text twice per run."""

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self.model = model
        self._client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"), base_url=_DEFAULT_EMBEDDING_BASE_URL)
        self._cache: dict[str, tuple[float, ...]] = {}

    def embed(self, text: str) -> tuple[float, ...]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        try:
            vector = self._embed_with_truncation(text if text.strip() else " ")
        except (APIConnectionError, APIStatusError) as exc:
            # ``APITimeoutError`` is an ``APIConnectionError`` subclass.
            raise LLMUpstreamError(
                f"Error occurred while generating embedding: {exc}",
                timed_out=isinstance(exc, APITimeoutError),
            ) from exc
        self._cache[text] = vector
        return vector

    def _embed_with_truncation(self, body: str) -> tuple[float, ...]:
        """Call the embeddings endpoint, retrying with the input truncated
        from the front (keeping the tail) whenever it exceeds the model's
        context limit.

        Real transcript turns (e.g. a minister reading a full report into
        the record) can run well past ``text-embedding-3-small``'s 8192
        tokens on their own, and TreeSeg's ``embed_items_with_preceding_context`` (see
        ``experiments/treeseg_turn_level/treeseg.py``) joins up to
        ``width`` preceding turns on top of that -- both routine on the
        Quốc hội biên bản corpus, not an edge case. Truncating from the
        front keeps the text closest to the block's current turn, which is
        the locally relevant context ``embed_items_with_preceding_context`` is built to capture.
        """

        attempt = body
        for _ in range(6):
            try:
                response = self._client.embeddings.create(model=self.model, input=attempt)
            except BadRequestError as exc:
                if "maximum context length" not in str(exc):
                    raise
                new_len = len(attempt) // 2
                if new_len < 1 or new_len >= len(attempt):
                    raise
                attempt = attempt[-new_len:]
                continue
            if len(attempt) < len(body):
                logger.warning(
                    "embedding input truncated from %d to %d chars (kept tail) "
                    "to fit the model's context limit",
                    len(body),
                    len(attempt),
                )
            return tuple(response.data[0].embedding)
        raise RuntimeError(
            f"embedding input still exceeds context limit after repeated truncation "
            f"(original {len(body)} chars, last attempt {len(attempt)} chars)"
        )

    def cosine(self, left_text: str, right_text: str) -> float:
        left = self.embed(left_text)
        right = self.embed(right_text)
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        # Guard float drift so a caller's [-1, 1] range check never trips on
        # a value like 1.0000000000000002.
        return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


class OpenAICosineSimilarity:
    """``CosineSimilarityAdapter`` for Stage 6 segmentation, domain ``[-1, 1]``."""

    def __init__(self, embedding_client: OpenAIEmbeddingClient) -> None:
        self._embeddings = embedding_client

    @property
    def model_name(self) -> str:
        return f"openai-embedding:{self._embeddings.model}"

    def similarity(self, left_text: str, right_text: str) -> float:
        return self._embeddings.cosine(left_text, right_text)


class OpenAISemanticSimilarity:
    """``SemanticSimilarityAdapter`` for Stage 8 recurrence, domain ``[0, 1]``.

    Reuses the same embeddings (and cache) as :class:`OpenAICosineSimilarity`
    when given the same :class:`OpenAIEmbeddingClient` instance, just
    rescaled from cosine's ``[-1, 1]``.
    """

    def __init__(self, embedding_client: OpenAIEmbeddingClient) -> None:
        self._embeddings = embedding_client

    @property
    def model_name(self) -> str:
        return f"openai-embedding:{self._embeddings.model}"

    def similarity(self, left_text: str, right_text: str) -> float:
        cosine = self._embeddings.cosine(left_text, right_text)
        return (cosine + 1.0) / 2.0


def _openai_strict_schema(schema: Mapping[str, object]) -> dict:
    """Normalize a ``{properties, required}`` schema into OpenAI Structured
    Outputs' strict form, where every property must appear in ``required``
    (fields the caller left optional become nullable instead of omittable)
    and every object has ``additionalProperties: False``. Property
    insertion order is preserved from ``schema["properties"]``, so a caller
    enforcing evidence-first field order (see ``ports.EventAdapter``) has
    that order actually reach the wire request.

    Recurses into nested object/array schemas -- e.g. ``src/agentic``'s
    per-evidence-entry schema (``{"evidence": {"type": "array", "items":
    {"type": "object", "properties": {"turn_id", "quote"}, ...}}}``). The
    original version only normalized the TOP-level object, leaving nested
    object schemas without ``additionalProperties: False`` -- real OpenAI
    Structured Outputs strict mode requires that at every nesting level, so
    a self-hosted gateway enforcing the same rule could reject (or, worse,
    silently under-constrain) a nested schema this shallow version emitted.
    """

    return _strict_node(dict(schema))


def _strict_node(node: dict) -> dict:
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
    """The server answered 200 but the content is not a JSON object.

    Seen with DeepSeek in ``json_object`` mode (no schema enforcement): the
    object is occasionally cut mid-value or followed by a second object. A
    fresh sample usually parses, so ``generate_json`` retries it like a
    timeout instead of failing the caller on the first bad sample.
    """


_CODE_FENCE_PREFIX = "```json"


def _parse_json_response(content: str | None) -> dict:
    """Decode a chat response into a dict, tolerating fences and trailing text.

    Strips a Markdown code fence, then decodes the FIRST JSON object in the
    content and ignores anything after it (a second object, a trailing
    explanation). Raises ``_InvalidJSONResponse`` -- with the start of the
    raw content, so the log shows what the model actually sent -- when there
    is no decodable object.
    """

    if content is None:
        raise _InvalidJSONResponse("OpenAI chat response had no JSON content")
    text = content.strip()
    if text.startswith(_CODE_FENCE_PREFIX):
        text = text[len(_CODE_FENCE_PREFIX):]
    text = text.strip("`").strip()
    start = text.find("{")
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text, start if start >= 0 else 0)
    except json.JSONDecodeError as exc:
        raise _InvalidJSONResponse(
            f"OpenAI chat response was not valid JSON: {exc}; content starts: {content[:300]!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise _InvalidJSONResponse("OpenAI chat response must decode to a JSON object")
    return parsed


class OpenAIChatJSONAdapter:
    """``LLMAdapter`` (``generate_json``) via Chat Completions.

    Defaults to OpenAI's Structured Outputs strict JSON-schema mode
    (``response_format={"type": "json_schema", ...}``), verified against
    both the real OpenAI API and an OpenAI-compatible vLLM/Qwen gateway. Pass
    ``response_mode="json_object"`` for an OpenAI-compatible server that only
    supports the looser guaranteed-valid-JSON mode, not full schema
    constraints.
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
        # Provider-specific request fields the SDK has no parameter for, e.g.
        # DeepSeek's ``{"thinking": {"type": "disabled"}}``.
        self.extra_body = dict(extra_body) if extra_body else None
        # Caps a runaway generation (gemma on the gateway has been seen to
        # emit ~3000 lines without closing a JSON string, ~150s per attempt).
        # A capped response fails to parse and is retried like any other
        # invalid-JSON sample. 0 = no cap.
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
        self._generate_backoff_seconds = _positive_float_env(
            "OPENAI_GENERATE_BACKOFF_SECONDS", _DEFAULT_GENERATE_BACKOFF_SECONDS
        )

    @property
    def model_name(self) -> str:
        return f"openai-chat:{self.model}"

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, schema: Mapping[str, object]
    ) -> Mapping[str, object]:
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
        # Own retry/backoff here rather than leaning on the SDK's silent
        # one (see ``_DEFAULT_MAX_RETRIES``): a transient failure (gateway
        # timeout, dropped connection, rate limit, 5xx) is retried with
        # exponential backoff + jitter and logged on every attempt, so a
        # slow-but-alive gateway gets a real second/third chance instead of
        # immediately handing the caller a fallback title. Non-transient
        # errors (bad request, auth, schema rejection, ...) raise straight
        # away -- retrying those would only waste the backoff delay.
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    messages=messages,
                    response_format=response_format,
                    extra_body=self.extra_body,
                    **({"max_tokens": self.max_output_tokens} if self.max_output_tokens else {}),
                )
                return _parse_json_response(response.choices[0].message.content)
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
                raise LLMUpstreamError(
                    f"Error occurred while generating JSON after {attempt} "
                    f"attempt(s): {last_exc}",
                    timed_out=isinstance(last_exc, APITimeoutError),
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
            # The SDK wraps every transport failure as "Connection error.";
            # the wrapped httpx error (ConnectError = refused/unreachable,
            # RemoteProtocolError/ReadError = reset mid-response, ...) is
            # what tells a gateway blip from a client-side problem.
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
    "OpenAICosineSimilarity",
    "OpenAIEmbeddingClient",
    "OpenAISemanticSimilarity",
]
