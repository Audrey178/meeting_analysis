"""JSON-loadable, dependency-free pipeline configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


def _positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _non_negative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _finite_number(name: str, value: float | int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    numeric = float(value)
    if numeric != numeric or numeric in {float("inf"), float("-inf")}:
        raise ValueError(f"{name} must be finite")
    return numeric


@dataclass(frozen=True, slots=True)
class TurnBuilderConfig:
    max_gap_ms: int = 1_500
    merge_when_timestamp_missing: bool = False
    merge_unknown_speakers: bool = False

    def __post_init__(self) -> None:
        _non_negative_int("turn_builder.max_gap_ms", self.max_gap_ms)
        if not isinstance(self.merge_when_timestamp_missing, bool):
            raise ValueError(
                "turn_builder.merge_when_timestamp_missing must be a boolean"
            )
        if not isinstance(self.merge_unknown_speakers, bool):
            raise ValueError("turn_builder.merge_unknown_speakers must be a boolean")

    @property
    def merge_missing_timestamps(self) -> bool:
        """Short-name compatibility alias."""

        return self.merge_when_timestamp_missing


_DEFAULT_CANDIDATE_SOURCES: tuple[str, ...] = (
    "item_boundary",
    "sentence_punct",
    "weak_punct",
    "discourse_marker",
    "pause",
    "model",
)
_KNOWN_CANDIDATE_SOURCES = frozenset(_DEFAULT_CANDIDATE_SOURCES)
_KNOWN_SCORERS = frozenset({"lexical_coherence"})


@dataclass(frozen=True, slots=True)
class AtomBuilderConfig:
    """Stage 4 (Analysis Atom Builder) settings -- see docs/stage4-5-plan.md D3/D10.

    ``mode`` is gone (D10): candidate sources are additive, not an exclusive
    choice between a rule path and a model path. ``"model"`` in
    ``candidate_sources`` only takes effect when a ``ClauseBoundaryAdapter``
    is actually injected into ``build_analysis_atoms``; unlike the old
    ``mode``, an absent adapter is silently dropped from the source list
    (recorded in provenance) instead of raising.
    """

    min_chars: int = 40
    target_chars: int = 280
    # Renamed from `max_chars` (see run_to_stage4.py Completion Report):
    # Stage 4's packer no longer hard-enforces this -- it's the target the
    # cost function optimizes toward, exceeded (and flagged, see
    # stage04_boundary.packing.PackedAtom.packing_method) only when no real
    # boundary candidate makes a shorter split possible.
    soft_cap_chars: int = 600
    candidate_sources: tuple[str, ...] = _DEFAULT_CANDIDATE_SOURCES
    # Now actually wired into generate_candidates()'s "item_boundary" source
    # (see stage04_boundary/candidates.py) -- 0.3 matches the value already
    # configured in configs/default.json.
    item_boundary_prior: float = 0.3
    scorer: str = "lexical_coherence"
    llm_tiebreak: bool = False
    max_llm_boundary_calls: int = 50

    def __post_init__(self) -> None:
        _positive_int("atom_builder.min_chars", self.min_chars)
        _positive_int("atom_builder.target_chars", self.target_chars)
        _positive_int("atom_builder.soft_cap_chars", self.soft_cap_chars)
        if self.min_chars > self.soft_cap_chars:
            raise ValueError(
                "atom_builder.min_chars must not exceed atom_builder.soft_cap_chars"
            )
        if not isinstance(self.candidate_sources, tuple) or not all(
            isinstance(source, str) for source in self.candidate_sources
        ):
            raise ValueError("atom_builder.candidate_sources must be a tuple of str")
        unknown = sorted(set(self.candidate_sources) - _KNOWN_CANDIDATE_SOURCES)
        if unknown:
            raise ValueError(
                "unknown atom_builder.candidate_sources: " + ", ".join(unknown)
            )
        if len(set(self.candidate_sources)) != len(self.candidate_sources):
            raise ValueError("atom_builder.candidate_sources must not repeat entries")
        prior = _finite_number("atom_builder.item_boundary_prior", self.item_boundary_prior)
        if not 0.0 <= prior <= 1.0:
            raise ValueError("atom_builder.item_boundary_prior must be between 0 and 1")
        if self.scorer not in _KNOWN_SCORERS:
            raise ValueError(
                "atom_builder.scorer must be one of: " + ", ".join(sorted(_KNOWN_SCORERS))
            )
        if not isinstance(self.llm_tiebreak, bool):
            raise ValueError("atom_builder.llm_tiebreak must be a boolean")
        _positive_int("atom_builder.max_llm_boundary_calls", self.max_llm_boundary_calls)


@dataclass(frozen=True, slots=True)
class TopicSegmenterConfig:
    """Paper-inspired turn/atom segmentation settings.

    ``paper_chunked_linear`` is the default because it was the strongest of the
    paper's three reported variants. The cosine modes require a semantic scorer
    for a faithful MPNet-style implementation; the bundled fallback is lexical.
    """

    strategy: str = "paper_chunked_linear"
    max_tokens: int = 1_024
    similarity_threshold: float = 0.0
    respect_turn_boundaries: bool = True
    keyword_weight: float = 0.5
    semantic_weight: float = 0.5
    """Only used by ``strategy="hybrid_bm25_semantic"``: weights for the BM25
    keyword component and the cosine semantic component of the combined
    boundary score. Must each be in ``[0, 1]`` and sum to at most 1, so the
    combined score stays within the ``[-1, 1]`` range every strategy is
    validated against. These are unbenchmarked starting defaults, not tuned
    production values -- see ``docs/paper-segmentation-notes.md``."""

    def __post_init__(self) -> None:
        allowed = {
            "paper_chunked_linear",
            "paper_simple_cosine",
            "paper_complex_cosine",
            "hybrid_bm25_semantic",
            # TIP-004: DP-optimal Gram-matrix segmenter in stages/segmentation.py.
            # A new strategy value, not a replacement -- the four above are
            # unchanged and still needed for the PR5 baselines/ablation.
            "hybrid_bm25_semantic_v2",
        }
        if self.strategy not in allowed:
            raise ValueError(
                "topic_segmenter.strategy must be one of " + ", ".join(sorted(allowed))
            )
        _positive_int("topic_segmenter.max_tokens", self.max_tokens)
        threshold = _finite_number(
            "topic_segmenter.similarity_threshold", self.similarity_threshold
        )
        if not -1.0 <= threshold <= 1.0:
            raise ValueError(
                "topic_segmenter.similarity_threshold must be between -1 and 1"
            )
        if not isinstance(self.respect_turn_boundaries, bool):
            raise ValueError(
                "topic_segmenter.respect_turn_boundaries must be a boolean"
            )
        keyword_weight = _finite_number(
            "topic_segmenter.keyword_weight", self.keyword_weight
        )
        semantic_weight = _finite_number(
            "topic_segmenter.semantic_weight", self.semantic_weight
        )
        if not 0.0 <= keyword_weight <= 1.0:
            raise ValueError("topic_segmenter.keyword_weight must be between 0 and 1")
        if not 0.0 <= semantic_weight <= 1.0:
            raise ValueError("topic_segmenter.semantic_weight must be between 0 and 1")
        if keyword_weight + semantic_weight > 1.0 + 1e-9:
            raise ValueError(
                "topic_segmenter.keyword_weight + semantic_weight must not exceed 1"
            )


_DEFAULT_TITLE_BLACKLIST: tuple[str, ...] = (
    "thảo luận",
    "các vấn đề khác",
    "vấn đề khác",
    "nội dung khác",
    "nội dung thảo luận",
    "thảo luận chung",
    "khác",
)


@dataclass(frozen=True, slots=True)
class TopicLabelerConfig:
    mode: str = "llm"
    allow_extract_fallback: bool = True
    max_title_chars: int = 80
    title_blacklist: tuple[str, ...] = _DEFAULT_TITLE_BLACKLIST
    max_retry_attempts: int = 3
    fallback_keyphrase_count: int = 3
    blacklist_subset_check: bool = True

    def __post_init__(self) -> None:
        if self.mode != "llm":
            raise ValueError("topic_labeler.mode must be 'llm'")
        if not isinstance(self.allow_extract_fallback, bool):
            raise ValueError(
                "topic_labeler.allow_extract_fallback must be a boolean"
            )
        _positive_int("topic_labeler.max_title_chars", self.max_title_chars)
        if not isinstance(self.title_blacklist, tuple) or not all(
            isinstance(entry, str) and entry.strip() for entry in self.title_blacklist
        ):
            raise ValueError(
                "topic_labeler.title_blacklist must be a tuple of non-empty strings"
            )
        _non_negative_int(
            "topic_labeler.max_retry_attempts", self.max_retry_attempts
        )
        _positive_int(
            "topic_labeler.fallback_keyphrase_count", self.fallback_keyphrase_count
        )
        if not isinstance(self.blacklist_subset_check, bool):
            raise ValueError(
                "topic_labeler.blacklist_subset_check must be a boolean"
            )


@dataclass(frozen=True, slots=True)
class TopicRecurrenceConfig:
    semantic_threshold: float = 0.72
    semantic_high_confidence: float = 0.90
    join_policy: str = "consensus"
    max_candidate_pairs: int = 200
    must_not_link_requires_explicit_judgment: bool = True
    llm_max_workers: int = 4
    max_judge_chars: int = 6000
    use_gram_similarity: bool = True

    def __post_init__(self) -> None:
        semantic_threshold = _finite_number(
            "topic_recurrence.semantic_threshold", self.semantic_threshold
        )
        high_confidence = _finite_number(
            "topic_recurrence.semantic_high_confidence",
            self.semantic_high_confidence,
        )
        if not 0.0 <= semantic_threshold <= 1.0:
            raise ValueError(
                "topic_recurrence.semantic_threshold must be between 0 and 1"
            )
        if not semantic_threshold <= high_confidence <= 1.0:
            raise ValueError(
                "topic_recurrence.semantic_high_confidence must be between "
                "semantic_threshold and 1"
            )
        if not isinstance(self.must_not_link_requires_explicit_judgment, bool):
            raise ValueError(
                "topic_recurrence.must_not_link_requires_explicit_judgment "
                "must be a boolean"
            )
        _positive_int("topic_recurrence.llm_max_workers", self.llm_max_workers)
        _positive_int("topic_recurrence.max_judge_chars", self.max_judge_chars)
        if not isinstance(self.use_gram_similarity, bool):
            raise ValueError("topic_recurrence.use_gram_similarity must be a boolean")
        if self.join_policy not in {"consensus", "consensus_or_semantic_high"}:
            raise ValueError(
                "topic_recurrence.join_policy must be 'consensus' or "
                "'consensus_or_semantic_high'"
            )
        _positive_int(
            "topic_recurrence.max_candidate_pairs", self.max_candidate_pairs
        )


@dataclass(frozen=True, slots=True)
class EventGuardConfig:
    max_rounds: int = 3

    def __post_init__(self) -> None:
        _positive_int("event_guard.max_rounds", self.max_rounds)
        if self.max_rounds > 3:
            raise ValueError("event_guard.max_rounds must not exceed 3")


@dataclass(frozen=True, slots=True)
class InputDomainConfig:
    """Conservative deterministic gate for meeting-only downstream stages."""

    enabled: bool = True
    broadcast_signal_threshold: int = 2
    max_known_speaker_fraction: float = 0.25
    min_named_speakers: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("input_domain.enabled must be a boolean")
        _positive_int(
            "input_domain.broadcast_signal_threshold",
            self.broadcast_signal_threshold,
        )
        fraction = _finite_number(
            "input_domain.max_known_speaker_fraction",
            self.max_known_speaker_fraction,
        )
        if not 0.0 <= fraction <= 1.0:
            raise ValueError(
                "input_domain.max_known_speaker_fraction must be between 0 and 1"
            )
        _positive_int("input_domain.min_named_speakers", self.min_named_speakers)


@dataclass(frozen=True, slots=True)
class WindowBuilderConfig:
    core_max_chars: int = 2_400
    context_atoms: int = 2

    def __post_init__(self) -> None:
        _positive_int("window_builder.core_max_chars", self.core_max_chars)
        _non_negative_int("window_builder.context_atoms", self.context_atoms)

    @property
    def core_chars(self) -> int:
        """Short-name compatibility alias."""

        return self.core_max_chars


@dataclass(frozen=True, slots=True)
class FeatureBuilderConfig:
    """Stage 5 (Atom Feature Builder) settings -- see stage4-5-plan.md D9.

    ``emit_features`` controls whether the independently computed Stage 5
    artifact is serialized.  The in-memory representation may still be used
    by Stage 6 when emission is disabled.

    ``emit_top_k_terms`` only cuts the ``lex_syllable``/``lex_char`` weights
    serialized onto ``AtomFeatures`` (TIP-002) -- Stage 5 always computes the
    full, uncut BM25 table internally (keyphrase scoring needs it) and only
    cuts to this many terms per channel at the very end.
    """

    emit_features: bool = True
    emit_top_k_terms: int = 10
    top_k_keyphrases: int = 5
    char_ngram_range: tuple[int, int] = (3, 6)
    use_syllable_bigrams: bool = True
    bm25_k1: float = 1.5
    bm25_b: float = 0.75

    def __post_init__(self) -> None:
        if not isinstance(self.emit_features, bool):
            raise ValueError("feature_builder.emit_features must be a boolean")
        _positive_int("feature_builder.emit_top_k_terms", self.emit_top_k_terms)
        _positive_int("feature_builder.top_k_keyphrases", self.top_k_keyphrases)
        if (
            not isinstance(self.char_ngram_range, tuple)
            or len(self.char_ngram_range) != 2
            or not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in self.char_ngram_range
            )
        ):
            raise ValueError(
                "feature_builder.char_ngram_range must be a (start, end) tuple of integers"
            )
        start, end = self.char_ngram_range
        if start <= 0 or end <= 0:
            raise ValueError("feature_builder.char_ngram_range values must be positive")
        if start >= end:
            raise ValueError("feature_builder.char_ngram_range must have start < end")
        if not isinstance(self.use_syllable_bigrams, bool):
            raise ValueError("feature_builder.use_syllable_bigrams must be a boolean")
        bm25_k1 = _finite_number("feature_builder.bm25_k1", self.bm25_k1)
        if bm25_k1 <= 0:
            raise ValueError("feature_builder.bm25_k1 must be positive")
        bm25_b = _finite_number("feature_builder.bm25_b", self.bm25_b)
        if not 0.0 <= bm25_b <= 1.0:
            raise ValueError("feature_builder.bm25_b must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class EventExtractorConfig:
    mode: str = "rule"

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str) or not self.mode.strip():
            raise ValueError("event_extractor.mode must be a non-empty string")


@dataclass(frozen=True, slots=True)
class PublishPolicyConfig:
    allow_unknown_actor: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.allow_unknown_actor, bool):
            raise ValueError("publish_policy.allow_unknown_actor must be a boolean")

    @property
    def publish_unknown_actor(self) -> bool:
        """Short-name compatibility alias."""

        return self.allow_unknown_actor


@dataclass(frozen=True, slots=True)
class SegmentationConfig:
    """TIP-004 (plan.md §3.7): settings for ``stages.segmentation.segment()``,
    the DP-optimal Gram-matrix hybrid segmenter. Independent from
    ``TopicSegmenterConfig`` -- see stage06_topic_segmentation.py's
    ``"hybrid_bm25_semantic_v2"`` strategy for how the two are wired together.
    """

    beta_dense: float = 0.55
    beta_syllable: float = 0.35
    beta_char: float = 0.10
    gamma: float = 0.35
    lam: float = 0.8
    min_len: int = 2
    max_len: int = 120
    smoothing_window: int = 1
    k_mode: str = "penalty"
    k_fixed: int | None = None
    k_max: int = 30

    def __post_init__(self) -> None:
        beta_dense = _finite_number("segmentation.beta_dense", self.beta_dense)
        beta_syllable = _finite_number("segmentation.beta_syllable", self.beta_syllable)
        beta_char = _finite_number("segmentation.beta_char", self.beta_char)
        if beta_dense < 0.0 or beta_syllable < 0.0 or beta_char < 0.0:
            raise ValueError(
                "segmentation.beta_dense/beta_syllable/beta_char must not be negative"
            )
        if abs((beta_dense + beta_syllable + beta_char) - 1.0) > 1e-9:
            raise ValueError(
                "segmentation.beta_dense + beta_syllable + beta_char must sum to 1"
            )
        lam = _finite_number("segmentation.lam", self.lam)
        if not 0.0 <= lam < 1.0:
            raise ValueError("segmentation.lam must be in [0, 1)")
        _finite_number("segmentation.gamma", self.gamma)
        _positive_int("segmentation.min_len", self.min_len)
        _positive_int("segmentation.max_len", self.max_len)
        if self.min_len > self.max_len:
            raise ValueError("segmentation.min_len must be <= segmentation.max_len")
        _non_negative_int("segmentation.smoothing_window", self.smoothing_window)
        allowed_k_modes = {"fixed", "elbow", "penalty"}
        if self.k_mode not in allowed_k_modes:
            raise ValueError(
                "segmentation.k_mode must be one of " + ", ".join(sorted(allowed_k_modes))
            )
        if self.k_mode == "fixed":
            if self.k_fixed is None:
                raise ValueError(
                    "segmentation.k_fixed is required when k_mode='fixed'"
                )
            _positive_int("segmentation.k_fixed", self.k_fixed)
        elif self.k_fixed is not None:
            _positive_int("segmentation.k_fixed", self.k_fixed)
        _positive_int("segmentation.k_max", self.k_max)
        # beta_dense > 0 with no embedding_adapter is validated in
        # stages.segmentation.segment() itself, not here -- this dataclass
        # has no way to know whether the caller will supply an adapter.


def _mapping_section(
    data: Mapping[str, Any], primary: str, alias: str | None = None
) -> dict[str, Any]:
    section = data.get(primary)
    if section is None and alias is not None:
        section = data.get(alias)
    if section is None:
        return {}
    if not isinstance(section, Mapping):
        raise ValueError(f"config section {primary!r} must be a JSON object")
    return dict(section)


def _rename_alias(
    section: dict[str, Any], canonical: str, alias: str
) -> dict[str, Any]:
    if canonical in section and alias in section:
        raise ValueError(f"config cannot set both {canonical!r} and {alias!r}")
    if alias in section:
        section[canonical] = section.pop(alias)
    return section


def _only_keys(section: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unexpected = sorted(set(section) - allowed)
    if unexpected:
        joined = ", ".join(unexpected)
        raise ValueError(f"unknown key(s) in {name}: {joined}")


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    turn_builder: TurnBuilderConfig = TurnBuilderConfig()
    atom_builder: AtomBuilderConfig = AtomBuilderConfig()
    feature_builder: FeatureBuilderConfig = FeatureBuilderConfig()
    topic_segmenter: TopicSegmenterConfig = TopicSegmenterConfig()
    topic_labeler: TopicLabelerConfig = TopicLabelerConfig()
    topic_recurrence: TopicRecurrenceConfig = TopicRecurrenceConfig()
    input_domain: InputDomainConfig = InputDomainConfig()
    window_builder: WindowBuilderConfig = WindowBuilderConfig()
    event_extractor: EventExtractorConfig = EventExtractorConfig()
    event_guard: EventGuardConfig = EventGuardConfig()
    publish_policy: PublishPolicyConfig = PublishPolicyConfig()
    segmentation: SegmentationConfig = SegmentationConfig()

    # NOTE: previously enforced `atom_builder.max_chars <= window_builder.core_max_chars`
    # here. Removed deliberately, not an oversight: `soft_cap_chars` (the
    # renamed `max_chars`) is no longer a hard ceiling on atom length --
    # Stage 4 can now emit an atom longer than it when no real boundary
    # exists -- so this config-time check no longer protects a real runtime
    # invariant. Stage 9's `build_topic_windows` tolerates an over-length
    # atom directly instead (see stage09_windows.py).

    @property
    def turn(self) -> TurnBuilderConfig:
        return self.turn_builder

    @property
    def speaker_turn(self) -> TurnBuilderConfig:
        return self.turn_builder

    @property
    def atom(self) -> AtomBuilderConfig:
        return self.atom_builder

    @property
    def window(self) -> WindowBuilderConfig:
        return self.window_builder

    @property
    def publish(self) -> PublishPolicyConfig:
        return self.publish_policy

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PipelineConfig:
        if not isinstance(data, Mapping):
            raise ValueError("pipeline config must be a JSON object")

        known_root = {
            "turn_builder",
            "turn",
            "speaker_turn",
            "atom_builder",
            "atom",
            "feature_builder",
            "topic_segmenter",
            "topic_labeler",
            "topic_recurrence",
            "input_domain",
            "window_builder",
            "window",
            "event_extractor",
            "event_guard",
            "publish_policy",
            "publish",
            "segmentation",
        }
        _only_keys(data, known_root, "root config")

        for names in (
            ("turn_builder", "turn", "speaker_turn"),
            ("atom_builder", "atom"),
            ("window_builder", "window"),
            ("publish_policy", "publish"),
        ):
            present = [name for name in names if name in data]
            if len(present) > 1:
                raise ValueError(
                    "config cannot set equivalent sections together: "
                    + ", ".join(present)
                )

        turn_alias = "turn" if "turn" in data else "speaker_turn"
        turn = _mapping_section(data, "turn_builder", turn_alias)
        atom = _mapping_section(data, "atom_builder", "atom")
        feature = _mapping_section(data, "feature_builder")
        topic_segmenter = _mapping_section(data, "topic_segmenter")
        topic_labeler = _mapping_section(data, "topic_labeler")
        topic_recurrence = _mapping_section(data, "topic_recurrence")
        input_domain = _mapping_section(data, "input_domain")
        window = _mapping_section(data, "window_builder", "window")
        event = _mapping_section(data, "event_extractor")
        event_guard = _mapping_section(data, "event_guard")
        publish = _mapping_section(data, "publish_policy", "publish")
        segmentation = _mapping_section(data, "segmentation")

        _rename_alias(
            turn,
            "merge_when_timestamp_missing",
            "merge_missing_timestamps",
        )
        _rename_alias(window, "core_max_chars", "core_chars")
        _rename_alias(publish, "allow_unknown_actor", "publish_unknown_actor")

        _only_keys(
            turn,
            {
                "max_gap_ms",
                "merge_when_timestamp_missing",
                "merge_unknown_speakers",
            },
            "turn_builder",
        )
        if "candidate_sources" in atom:
            sources = atom["candidate_sources"]
            if not isinstance(sources, list) or not all(
                isinstance(entry, str) for entry in sources
            ):
                raise ValueError(
                    "atom_builder.candidate_sources must be a JSON array of strings"
                )
            atom["candidate_sources"] = tuple(sources)
        if "max_chars" in atom:
            # Deliberately not a silent _rename_alias() migration: max_chars
            # stopped being a hard cap (it's now atom_builder.soft_cap_chars,
            # a soft target), so a config still using the old name should
            # fail with a clear reason, not the generic "unknown key(s)"
            # message _only_keys() would otherwise give it.
            raise ValueError(
                "atom_builder.max_chars was renamed to atom_builder.soft_cap_chars "
                "(it is no longer a hard cap); update your config file"
            )
        _only_keys(
            atom,
            {
                "min_chars",
                "target_chars",
                "soft_cap_chars",
                "candidate_sources",
                "item_boundary_prior",
                "scorer",
                "llm_tiebreak",
                "max_llm_boundary_calls",
            },
            "atom_builder",
        )
        if "char_ngram_range" in feature:
            # Same JSON-array -> tuple convention as atom_builder.candidate_sources
            # above: the dataclass field type is a tuple, not a list.
            ngram_range = feature["char_ngram_range"]
            if (
                not isinstance(ngram_range, list)
                or len(ngram_range) != 2
                or not all(
                    isinstance(value, int) and not isinstance(value, bool)
                    for value in ngram_range
                )
            ):
                raise ValueError(
                    "feature_builder.char_ngram_range must be a JSON array of "
                    "exactly 2 integers"
                )
            feature["char_ngram_range"] = tuple(ngram_range)
        _only_keys(
            feature,
            {
                "emit_features",
                "emit_top_k_terms",
                "top_k_keyphrases",
                "char_ngram_range",
                "use_syllable_bigrams",
                "bm25_k1",
                "bm25_b",
            },
            "feature_builder",
        )
        _only_keys(
            topic_segmenter,
            {
                "strategy",
                "max_tokens",
                "similarity_threshold",
                "respect_turn_boundaries",
                "keyword_weight",
                "semantic_weight",
            },
            "topic_segmenter",
        )
        _only_keys(
            topic_labeler,
            {
                "mode",
                "allow_extract_fallback",
                "max_title_chars",
                "title_blacklist",
                "max_retry_attempts",
                "fallback_keyphrase_count",
                "blacklist_subset_check",
            },
            "topic_labeler",
        )
        if "title_blacklist" in topic_labeler:
            blacklist = topic_labeler["title_blacklist"]
            if not isinstance(blacklist, list) or not all(
                isinstance(entry, str) for entry in blacklist
            ):
                raise ValueError(
                    "topic_labeler.title_blacklist must be a JSON array of strings"
                )
            topic_labeler["title_blacklist"] = tuple(blacklist)
        _only_keys(
            topic_recurrence,
            {
                "semantic_threshold",
                "semantic_high_confidence",
                "join_policy",
                "max_candidate_pairs",
                "must_not_link_requires_explicit_judgment",
                "llm_max_workers",
                "max_judge_chars",
                "use_gram_similarity",
            },
            "topic_recurrence",
        )
        _only_keys(
            input_domain,
            {
                "enabled",
                "broadcast_signal_threshold",
                "max_known_speaker_fraction",
                "min_named_speakers",
            },
            "input_domain",
        )
        _only_keys(window, {"core_max_chars", "context_atoms"}, "window_builder")
        _only_keys(event, {"mode"}, "event_extractor")
        _only_keys(event_guard, {"max_rounds"}, "event_guard")
        _only_keys(publish, {"allow_unknown_actor"}, "publish_policy")
        _only_keys(
            segmentation,
            {
                "beta_dense",
                "beta_syllable",
                "beta_char",
                "gamma",
                "lam",
                "min_len",
                "max_len",
                "smoothing_window",
                "k_mode",
                "k_fixed",
                "k_max",
            },
            "segmentation",
        )

        return cls(
            turn_builder=TurnBuilderConfig(**turn),
            atom_builder=AtomBuilderConfig(**atom),
            feature_builder=FeatureBuilderConfig(**feature),
            topic_segmenter=TopicSegmenterConfig(**topic_segmenter),
            topic_labeler=TopicLabelerConfig(**topic_labeler),
            topic_recurrence=TopicRecurrenceConfig(**topic_recurrence),
            input_domain=InputDomainConfig(**input_domain),
            window_builder=WindowBuilderConfig(**window),
            segmentation=SegmentationConfig(**segmentation),
            event_extractor=EventExtractorConfig(**event),
            event_guard=EventGuardConfig(**event_guard),
            publish_policy=PublishPolicyConfig(**publish),
        )

    @classmethod
    def load(cls, path: str | Path) -> PipelineConfig:
        config_path = Path(path)
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON config {config_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("pipeline config must be a JSON object")
        return cls.from_mapping(payload)


# Compact aliases retained for callers that prefer stage-agnostic names.
TurnConfig = TurnBuilderConfig
SpeakerTurnConfig = TurnBuilderConfig
AtomConfig = AtomBuilderConfig
WindowConfig = WindowBuilderConfig
PublishConfig = PublishPolicyConfig


def load_config(path: str | Path | None = None) -> PipelineConfig:
    """Load a JSON config, or return validated defaults when ``path`` is absent."""

    return PipelineConfig() if path is None else PipelineConfig.load(path)


__all__ = [
    "AtomBuilderConfig",
    "AtomConfig",
    "EventGuardConfig",
    "FeatureBuilderConfig",
    "EventExtractorConfig",
    "InputDomainConfig",
    "PipelineConfig",
    "PublishConfig",
    "PublishPolicyConfig",
    "SegmentationConfig",
    "SpeakerTurnConfig",
    "TopicLabelerConfig",
    "TopicRecurrenceConfig",
    "TopicSegmenterConfig",
    "TurnBuilderConfig",
    "TurnConfig",
    "WindowBuilderConfig",
    "WindowConfig",
    "load_config",
]
