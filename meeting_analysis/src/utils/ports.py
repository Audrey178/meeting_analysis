"""Dependency-free extension ports for optional models and services."""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from .contracts import EvidenceItem, TopicLabel, TopicSegment


@runtime_checkable
class EmbeddingAdapter(Protocol):
    """Shared embedding service """

    def embed(self, text: str) -> tuple[float, ...]: ...


@runtime_checkable
class TopicLabelAdapter(Protocol):
    """Generate one structured LLM label without changing segment boundaries."""

    def label_topic(
        self,
        segment: TopicSegment,
        prev_segment: TopicSegment | None,
        prev_topic: TopicLabel | None,
        atoms: tuple | None,
        evidence: tuple[EvidenceItem, ...],
        *,
        prior_issues: tuple[str, ...] = (),
    ) -> TopicLabel: ...


class LLMUpstreamError(ValueError):
    """The LLM backend itself failed (timeout, dropped connection, 5xx, auth
    or rate-limit exhaustion, unparseable reply) -- NOT bad caller input.

    Subclasses ``ValueError`` so existing ``except ValueError``/``Exception``
    fallbacks (e.g. stage 7's non-LLM title) keep working unchanged, but lets
    a caller that cares (the HTTP layer, the agent nodes) tell an upstream
    outage apart from a genuine validation error. ``timed_out`` is True when
    the failure was a request timeout, so an HTTP layer can pick 504 over 502.
    """

    def __init__(self, message: str, *, timed_out: bool = False) -> None:
        super().__init__(message)
        self.timed_out = timed_out


@runtime_checkable
class LLMAdapter(Protocol):
    """Small structured-generation surface; implementations own their SDK."""

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: Mapping[str, object],
    ) -> Mapping[str, object]: ...


__all__ = [
    "EmbeddingAdapter",
    "LLMAdapter",
    "LLMUpstreamError",
    "TopicLabelAdapter",
]
