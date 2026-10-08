"""Immutable data contracts shared by the meeting-analysis pipeline.

Times are represented as integer milliseconds.  Text offsets use Python's
half-open convention: ``start_char`` is inclusive and ``end_char`` is
exclusive.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any, TypeAlias


Scalar: TypeAlias = str | int | float | bool | None
Metadata: TypeAlias = tuple[tuple[str, Scalar], ...]


class Provenance(StrEnum):
    """Origin of an effective field value."""

    RAW_STT = "raw_stt"
    SPEAKER_MODEL = "speaker_model"
    HUMAN_REVIEW = "human_review"
    NORMALIZED = "normalized"
    DERIVED = "derived"
    SOURCE_EXPORT_EFFECTIVE = "source_export_effective"
    UNKNOWN = "unknown"


class EventKind(StrEnum):
    """Communication-act ontology used by local extraction."""

    REPORT = "report"
    QUESTION = "question"
    ANSWER = "answer"
    PROPOSAL = "proposal"
    OBJECTION = "objection"
    DECISION = "decision"
    ASSIGNMENT = "assignment"
    COMMITMENT = "commitment"
    CLARIFICATION = "clarification"
    OTHER = "other"


class GuardStatus(StrEnum):
    """Result of deterministic validation of an extracted event."""

    ACCEPTED = "accepted"
    DEGRADED = "degraded"
    REJECTED = "rejected"
    REVIEW_REQUIRED = "review_required"


class VerificationStatus(StrEnum):
    """Evidence support level for a claim or one of its fields."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    INSUFFICIENT = "insufficient"
    CONTRADICTED = "contradicted"


class VerificationScope(StrEnum):
    """Evidence operation that produced a verification status.

    ``UNSPECIFIED`` is deliberately the default for adapter-produced results:
    callers must opt in before claiming semantic entailment or another stronger
    verification operation.
    """

    UNSPECIFIED = "unspecified"
    EXACT_GROUNDING = "exact_grounding"
    SEMANTIC_ENTAILMENT = "semantic_entailment"
    HYBRID = "hybrid"


class InputDomainStatus(StrEnum):
    """Applicability of the meeting-specific downstream pipeline."""

    MEETING = "meeting"
    OUT_OF_DOMAIN = "out_of_domain"
    UNCERTAIN = "uncertain"
    NOT_ASSESSED = "not_assessed"


class InputDomainSignalType(StrEnum):
    """Direction of one deterministic input-domain signal."""

    BROADCAST = "broadcast"
    CONVERSATION = "conversation"


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    text: Provenance
    speaker: Provenance
    start_ms: Provenance = Provenance.RAW_STT
    end_ms: Provenance = Provenance.RAW_STT


@dataclass(frozen=True, slots=True)
class RawTranscriptItem:
    """One unmodified STT item plus optional field-level review overlays."""

    item_id: str
    text: str
    speaker: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    point_id: str | None = None
    ref_id: str | None = None
    reviewed_text: str | None = None
    reviewed_speaker: str | None = None
    revision: int = 0
    metadata: Metadata = ()
    ref_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EffectiveTranscriptItem:
    """Resolved snapshot; ``source`` retains the untouched raw item."""

    item_id: str
    text: str
    speaker: str | None
    start_ms: int | None
    end_ms: int | None
    point_id: str | None
    ref_id: str | None
    provenance: FieldProvenance
    source: RawTranscriptItem
    revision: int = 0
    speaker_role: str | None = None
    speaker_track: str | None = None
    ref_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """Normalized, stable evidence registry entry."""

    evidence_id: str
    source_item_id: str
    text: str
    speaker: str | None
    start_ms: int | None
    end_ms: int | None
    point_id: str | None
    ref_id: str | None
    provenance: FieldProvenance
    revision: int = 0
    text_exact: str | None = None
    content_hash: str = ""
    speaker_role: str | None = None
    speaker_track: str | None = None
    ref_ids: tuple[str, ...] = ()

    @property
    def text_normalized(self) -> str:
        """Normalized comparison text; ``text_exact`` remains the citation source."""

        return self.text


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Exact half-open slice of one evidence item."""

    evidence_id: str
    source_item_id: str
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    turn_id: str
    speaker: str | None
    text_exact: str
    evidence_ids: tuple[str, ...]
    start_ms: int | None
    end_ms: int | None
    speaker_role: str | None = None
    speaker_track: str | None = None


@dataclass(frozen=True, slots=True)
class BoundaryTiebreakDecision:
    """One auditable LLM decision at an offset inside a speaker turn.

    The record is stored on the atom that opens at or swallows ``position``.
    No generated text is accepted: ``verdict`` is one of MERGE/SPLIT/ABSTAIN,
    while ``reason_code`` also makes deterministic fallbacks such as an
    exhausted meeting budget explicit.
    """

    position: int
    candidate_source: str
    base_score: float
    verdict: str
    final_score: float
    reason_code: str


@dataclass(frozen=True, slots=True)
class InputDomainSignal:
    """Auditable cue used by the deterministic applicability assessor."""

    signal_type: InputDomainSignalType
    code: str
    matched_text: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InputDomainAssessment:
    """Conservative decision on whether meeting-only stages are applicable."""

    assessment_id: str
    status: InputDomainStatus
    is_applicable: bool
    assessor_name: str
    reason_codes: tuple[str, ...]
    signals: tuple[InputDomainSignal, ...]
    known_speaker_fraction: float
    unique_known_speakers: int
    speaker_turn_count: int


@dataclass(frozen=True, slots=True)
class AnalysisAtom:
    atom_id: str
    turn_id: str
    text_exact: str
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None
    speaker_role: str | None = None
    speaker_track: str | None = None
    segmentation_method: str = "rule_clause_v1"
    boundary_confidence: float | None = None
    boundary_source: str = "turn_edge"
    packing_method: str = "rule_pack_v1"
    llm_tiebreak_used: bool = False
    boundary_tiebreak_decisions: tuple[BoundaryTiebreakDecision, ...] = ()
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EntityMention:
    """One entity occurrence, anchored to an exact character span inside its
    atom's ``text_exact`` so Stage 12 checkers can verify "actor appears
    verbatim in anchor" from stored data instead of a fresh substring search
    (stage4-5-plan.md section 2, point 1)."""

    text: str
    start_char: int
    end_char: int
    entity_type: str
    canonical: str | None = None


@dataclass(frozen=True, slots=True)
class CueFlags:
    speaker_change: bool          # atom này mở đầu một lượt nói mới
    transition_cue: bool   # các cụm từ chuyển nội dung 
    enumeration_cue: bool  # các cụm từ liệt kê
    closing_cue: bool       # các cụm từ kết thúc, tạm biệt, chào tạm biệt


# All flags off -- the correct value when neither AtomMeta nor a cue match is
# available (see build_atom_features's atom_meta parameter, TIP-003).
_NO_CUES = CueFlags(
    speaker_change=False,
    transition_cue=False,
    enumeration_cue=False,
    closing_cue=False,
)


@dataclass(frozen=True, slots=True)
class AtomFeatures:
    """
       - vector đặc trưng của một atom
       - lex_syllable: bm25 trên âm tiết TV unigram và bigram từ đơn và từ ghép
       - lex_char: bm25 trên 3-5gram. chịu lỗi chính tả và lỗi ASR
       - entities — các mention thực thể đã trích xuất.
       - keyphrases — cụm từ khoá đã xếp hạng, tuple[str, ...], không mang điểm số.
    """
    atom_id: str
    lex_syllable: tuple[tuple[str, float], ...] = () 
    lex_char: tuple[tuple[str, float], ...] = ()
    entities: tuple[EntityMention, ...] = ()
    keyphrases: tuple[str, ...] = ()
    cues: CueFlags = field(default_factory=lambda: _NO_CUES)
    embedding_model_id: str | None = None
    embedding_dim: int | None = None
    embedding_vector_ref: str | None = None


@dataclass(frozen=True, slots=True)
class LexicalStats:
    """Đi kèm artifact để tái lập được điểm số BM25."""

    tokenizer_id: str
    doc_count: int
    avg_length: float
    k1: float
    b: float


@dataclass(frozen=True, slots=True)
class AtomMeta:
    """Optional, externally-supplied per-atom metadata (TIP-003).

    ``AnalysisAtom`` deliberately carries no ``speaker_id``/timestamps of its
    own (see plan.md §1/§2.4) -- when a caller has this information, it is
    passed alongside atoms via ``build_atom_features(..., atom_meta=...)``,
    keyed by ``atom_id``, instead of widening the atom contract.
    """

    speaker_id: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass(frozen=True, slots=True)
class TopicSegment:
    """One contiguous, atom-aligned segment produced before topic labeling.
        - segment_id: str, id của segment
        - atom_ids: tuple[str, ...], danh sách các atom_id trong segment
        - start_ms: int | None, thời gian bắt đầu của segment
        - end_ms: int | None, thời gian kết thúc của segment
        - token_count: int, số lượng token trong segment
        - segmentation_method: str, phương pháp phân đoạn
        - boundary_score: float | None, điểm số biên giới của segment
    """

    segment_id: str
    atom_ids: tuple[str, ...] | None = None
    text: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    token_count: int | None = None
    segmentation_method: str | None = None
    boundary_score: float | None = None


@dataclass(frozen=True, slots=True)
class HybridTopicSegment:
    """
    """

    segment_id: str
    atom_ids: tuple[str, ...]
    start_index: int              # inclusive
    end_index: int                # exclusive
    cost: float
    boundary_cue_score: float     # cue_score tại start_index


@dataclass(frozen=True, slots=True)
class HybridSegmentationResult:
    """Full output of ``stages.segmentation.segment()`` (TIP-004)."""

    segments: tuple[HybridTopicSegment, ...]
    total_cost: float
    config_fingerprint: str       # hash của SegmentationConfig + tokenizer_id + model_id


@dataclass(frozen=True, slots=True)
class TopicLabel:
    """Structured label for one segment; production labels come from an LLM."""

    segment_id: str
    title: str
    summary: str
    text: str
    evidence_ids: tuple[str, ...]
    method: str
    model_name: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class TopicRecurrenceVote:
    """One independent semantic or LLM vote for a recurrence candidate."""

    branch: str
    source_segment_id: str
    target_segment_id: str
    same_topic: bool | None
    score: float | None = None
    reason: str | None = None
    model_name: str | None = None


@dataclass(frozen=True, slots=True)
class TopicRecurrenceDecision:
    """Conservative join of the two independently computed recurrence votes."""

    decision_id: str
    source_segment_id: str
    target_segment_id: str
    semantic_vote: TopicRecurrenceVote
    llm_vote: TopicRecurrenceVote
    same_topic: bool
    relation: str
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TopicMap:
    """Canonical topic membership plus the auditable branch decisions."""

    memberships: tuple[tuple[str, str], ...]
    decisions: tuple[TopicRecurrenceDecision, ...]
    candidate_pair_count: int = 0
    evaluated_pair_count: int = 0
    truncated: bool = False
    gray_zone_pair_count: int = 0
    not_assessed_pair_count: int = 0


@dataclass(frozen=True, slots=True)
class SegmentGram:
    """Fused Gram matrix (TIP-004 §3.1) + 2-D prefix sums, exported so Stage
    8's semantic recurrence branch can score arbitrary (non-adjacent)
    segment pairs on the SAME fused dense+syllable+char representation as
    Stage 6's boundary cost -- see plan_stage_7_8.md §3.2 and
    TASK-GRAPH-stage7-8.md D-105. ``atom_order[i]`` is the atom_id at
    row/col ``i`` of the matrix; ``prefix`` has shape ``(n+1, n+1)``, same
    convention as ``segmentation._prefix_sums`` (``prefix[a][b]`` = sum of
    ``gram[0:a, 0:b]``)."""

    atom_order: tuple[str, ...]
    prefix: tuple[tuple[float, ...], ...]


@dataclass(frozen=True, slots=True)
class AnalysisWindow:
    window_id: str
    left_context_atom_ids: tuple[str, ...]
    core_atom_ids: tuple[str, ...]
    right_context_atom_ids: tuple[str, ...]
    start_ms: int | None
    end_ms: int | None
    topic_ids: tuple[str, ...] = ()



@dataclass(frozen=True, slots=True)
class AtomicClaim:
    claim_id: str
    text: str
    evidence_ids: tuple[str, ...]
    event_ids: tuple[str, ...] = ()
    subject: str | None = None
    predicate: str | None = None
    object_text: str | None = None
    actor: str | None = None
    source_speaker: str | None = None
    modality: str | None = None
    event_kind: EventKind | None = None
    component_texts: tuple[str, ...] = ()
    """For a claim spanning more than one event (``len(event_ids) > 1``),
    each entry is the exact proposition text contributed by the
    correspondingly-positioned ``event_ids`` entry. Verification checks each
    component against only its own event's anchor evidence -- a composite
    claim can never be marked ``SUPPORTED`` by borrowing another component's
    grounding. Empty (the default) for an ordinary single-event claim, whose
    ``text`` is checked directly against its own anchor evidence instead."""


@dataclass(frozen=True, slots=True)
class CitationFragment:
    fragment_id: str
    evidence_id: str
    source_item_id: str
    text_exact: str
    speaker: str | None
    start_ms: int | None
    end_ms: int | None
    start_char: int
    end_char: int
    point_id: str | None = None
    ref_id: str | None = None
    ref_ids: tuple[str, ...] = ()
    is_anchor: bool = True
    event_id: str | None = None
    """Which claim-linked event this fragment's span came from. Populated by
    ``build_citations`` so a composite (multi-event) claim's verifier can
    attribute each fragment back to the specific event it grounds, instead of
    treating the citation as one flat, unattributed text blob."""


@dataclass(frozen=True, slots=True)
class Citation:
    citation_id: str
    claim_id: str
    fragments: tuple[CitationFragment, ...]
    label: str | None = None


@dataclass(frozen=True, slots=True)
class VerifiedClaim:
    claim: AtomicClaim
    citations: tuple[Citation, ...]
    status: VerificationStatus
    field_statuses: tuple[tuple[str, VerificationStatus], ...] = ()
    reason_codes: tuple[str, ...] = ()
    score: float | None = None
    verifier_name: str | None = None
    verification_scope: VerificationScope = VerificationScope.UNSPECIFIED


@dataclass(frozen=True, slots=True)
class PublishableClaim:
    claim_id: str
    text: str
    citation_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    verification_status: VerificationStatus
    actor: str | None = None
    source_speaker: str | None = None
    actor_redacted: bool = False
    review_marker_ids: tuple[str, ...] = ()
    event_kind: EventKind | None = None
    verification_scope: VerificationScope = VerificationScope.UNSPECIFIED


@dataclass(frozen=True, slots=True)
class ReviewMarker:
    marker_id: str
    stage: str
    artifact_id: str
    code: str
    message: str
    evidence_ids: tuple[str, ...] = ()
    severity: str = "warning"
    details: Metadata = ()


def to_jsonable(value: Any) -> Any:
    """Recursively convert contract values into ``json.dumps``-ready values."""

    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {
            str(to_jsonable(key)): to_jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"Unsupported JSON value: {type(value).__qualname__}")


__all__ = [
    "AnalysisAtom",
    "AnalysisWindow",
    "AtomFeatures",
    "AtomMeta",
    "AtomicClaim",
    "BoundaryTiebreakDecision",
    "Citation",
    "CitationFragment",
    "CueFlags",
    "EffectiveTranscriptItem",
    "EntityMention",
    "FieldProvenance",
    "HybridSegmentationResult",
    "HybridTopicSegment",
    "InputDomainAssessment",
    "InputDomainSignal",
    "InputDomainSignalType",
    "InputDomainStatus",
    "LexicalStats",
    "Provenance",
    "PublishableClaim",
    "RawTranscriptItem",
    "Scalar",
    "SourceSpan",
    "SpeakerTurn",
    "TopicLabel",
    "TopicMap",
    "TopicRecurrenceDecision",
    "TopicRecurrenceVote",
    "TopicSegment",
    "VerificationScope",
    "VerificationStatus",
    "VerifiedClaim",
    "to_jsonable",
]
