"""Dependency-free extension ports for optional models and services."""

from __future__ import annotations

from typing import Literal, Mapping, Protocol, TypeAlias, runtime_checkable, Optional

from .contracts import (
    AnalysisAtom,
    AnalysisWindow,
    AtomicClaim,
    Citation,
    EvidenceItem,
    Scalar,
    TopicLabel,
    TopicSegment,
    VerifiedClaim,
)


FeatureValue: TypeAlias = Scalar | tuple[str, ...] | tuple[float, ...]
FeatureRecord: TypeAlias = tuple[tuple[str, FeatureValue], ...]
AtomFeatureRecord: TypeAlias = tuple[str, FeatureRecord]
TopicAssignment: TypeAlias = tuple[str, str]
ItemSpan: TypeAlias = tuple[int, int]
BoundaryCandidate: TypeAlias = tuple[int, float | None]
BoundaryTiebreakVerdict: TypeAlias = Literal["MERGE", "SPLIT", "ABSTAIN"]


@runtime_checkable
class ClauseBoundaryAdapter(Protocol):
    """Propose candidate cut positions in ONE speaker turn (stage4-5-plan.md D7 Opt.2).

    This adapter CONTRIBUTES candidates to Stage 4a; it does not decide the
    final atom boundaries -- ``ConstrainedPacker`` (4c) does. ``item_spans``
    is the explicit, tamper-proof boundary of every source ``EvidenceItem``
    inside ``text_exact`` (D2(b)): with ``TURN_ITEM_SEPARATOR`` no longer a
    distinguishable character (`" "`), this is the only way an adapter can
    see where one evidence item ends and the next begins.
    """

    def propose_boundaries(
        self,
        text_exact: str,
        item_spans: Optional[tuple[ItemSpan, ...]] = None,
    ) -> tuple[BoundaryCandidate, ...]: ...


@runtime_checkable
class LLMBoundaryTiebreakAdapter(Protocol):
    """Judge only the ambiguous-band candidates of one turn (D6).

    Batched per turn (never per meeting, never per candidate) to keep a hard
    cost ceiling. Each pair is ``(left_text, right_text, candidate_source)``;
    the adapter MUST return one of ``"MERGE"``, ``"SPLIT"``, ``"ABSTAIN"`` per
    pair, in the same order -- never free text, matching the existing
    invariant that models only ever predict a boundary, never author one.
    """

    def judge_boundaries(
        self, pairs: tuple[tuple[str, str, str], ...]
    ) -> tuple[BoundaryTiebreakVerdict, ...]: ...


@runtime_checkable
class CosineSimilarityAdapter(Protocol):
    """Return cosine similarity in [-1, 1] for paper-style segmentation."""

    def similarity(self, left_text: str, right_text: str) -> float: ...


@runtime_checkable
class SemanticSimilarityAdapter(Protocol):
    """Compute a calibrated semantic similarity in the closed interval [0, 1]."""

    def similarity(self, left_text: str, right_text: str) -> float: ...


@runtime_checkable
class EmbeddingAdapter(Protocol):
    """Shared embedding service """

    def embed(self, text: str) -> tuple[float, ...]: ...


@runtime_checkable
class FeatureAdapter(Protocol):
    """Build optional lexical, entity, or dense features for atoms."""

    def build_features(
        self, atoms: tuple[AnalysisAtom, ...]
    ) -> tuple[AtomFeatureRecord, ...]: ...


@runtime_checkable
class TopicAdapter(Protocol):
    """Assign atoms to opaque topic IDs without changing atom boundaries."""

    def assign_topics(
        self,
        atoms: tuple[AnalysisAtom, ...],
        features: tuple[AtomFeatureRecord, ...] = (),
    ) -> tuple[TopicAssignment, ...]: ...


@runtime_checkable
class TopicLabelAdapter(Protocol):
    """Generate one structured LLM label without changing segment boundaries."""

    def label_topic(
        self,
        segment: TopicSegment,
        prev_segment: TopicSegment | None,
        prev_topic: TopicLabel | None,
        atoms: tuple[AnalysisAtom, ...],
        evidence: tuple[EvidenceItem, ...],
        *,
        prior_issues: tuple[str, ...] = (),
    ) -> TopicLabel: ...


@runtime_checkable
class TopicRecurrenceLLMAdapter(Protocol):
    """Judge one candidate pair independently from the semantic branch."""

    def check_same_topic(
        self,
        source_label: TopicLabel,
        target_label: TopicLabel,
        source_text: str,
        target_text: str,
    ) -> tuple[bool | None, str | None]: ...


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


@runtime_checkable
class EventAdapter(Protocol):
    """Extract evidence-grounded events from one analysis window.

    Evidence-first decoding: if an implementation uses guided decoding /
    structured JSON output, ``evidence_ids`` MUST be ordered before
    ``proposition`` in the schema's ``properties``/``required`` order. Making
    the model commit to which evidence it is using before it writes the
    proposition text anchors generation in evidence; writing the proposition
    first lets the model rationalize evidence after the fact, which is the
    single cheapest, highest-leverage change against hallucination in this
    stage. This constrains the prompt/schema contract only -- it does not
    change ``LocalEvent``'s dataclass field order, which is an internal
    contract unrelated to any adapter's wire schema.
    """

    def extract_events(
        self,
        window: AnalysisWindow,
        atoms: tuple[AnalysisAtom, ...],
        evidence: tuple[EvidenceItem, ...],
    ) -> tuple[LocalEvent, ...]: ...


@runtime_checkable
class EventGuardReviewer(Protocol):
    """LLM reviewer in a bounded reviewer -> checker loop."""

    def review_event(
        self,
        event: LocalEvent,
        evidence: tuple[GuardEvidenceExcerpt, ...],
        checker_result: GuardedEvent,
        round_index: int,
    ) -> LocalEvent | None: ...


@runtime_checkable
class ActionAdapter(Protocol):
    """Optional action-focused extractor using the shared event contract."""

    def extract_action_events(
        self,
        window: AnalysisWindow,
        atoms: tuple[AnalysisAtom, ...],
        evidence: tuple[EvidenceItem, ...],
    ) -> tuple[LocalEvent, ...]: ...


@runtime_checkable
class VerifierAdapter(Protocol):
    """Verify one atomic claim against only its supplied citations."""

    def verify_claim(
        self, claim: AtomicClaim, citations: tuple[Citation, ...]
    ) -> VerifiedClaim: ...


AtomFeatureAdapter = FeatureAdapter
StructuredLLMAdapter = LLMAdapter
EventExtractorAdapter = EventAdapter
ActionExtractorAdapter = ActionAdapter
ClaimVerifierAdapter = VerifierAdapter


__all__ = [
    "ActionAdapter",
    "ActionExtractorAdapter",
    "AtomFeatureAdapter",
    "AtomFeatureRecord",
    "BoundaryCandidate",
    "BoundaryTiebreakVerdict",
    "ClauseBoundaryAdapter",
    "CosineSimilarityAdapter",
    "ClaimVerifierAdapter",
    "EmbeddingAdapter",
    "EventAdapter",
    "EventExtractorAdapter",
    "EventGuardReviewer",
    "FeatureAdapter",
    "FeatureRecord",
    "FeatureValue",
    "ItemSpan",
    "LLMAdapter",
    "LLMBoundaryTiebreakAdapter",
    "LLMUpstreamError",
    "SemanticSimilarityAdapter",
    "StructuredLLMAdapter",
    "TopicAdapter",
    "TopicAssignment",
    "TopicLabelAdapter",
    "TopicRecurrenceLLMAdapter",
    "VerifierAdapter",
]
