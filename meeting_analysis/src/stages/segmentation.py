"""TIP-004 (plan.md §3): DP-optimal topic segmentation over a fused
dense + syllable-BM25 + char-BM25 Gram matrix.

Three channels are fused at the VECTOR level (via a Gram matrix, never at
the similarity-score level -- see ``_gram_matrix``), smoothed with a small
sliding window (§3.2), then split with a globally-optimal DP over contiguous
segments (§3.3/§3.4) that gives a configurable discount to boundaries
falling on a strong cue (chair transition, enumeration, closing, speaker
change, long silence -- see ``utils.cues``/``AtomFeatures.cues``, TIP-003).

This module is a new, independent strategy for Stage 6, not a replacement:
``stage06_topic_segmentation.py``'s four existing strategies (including the
older, sequential-threshold ``hybrid_bm25_semantic``) are untouched and keep
running exactly as before -- see that module's ``"hybrid_bm25_semantic_v2"``
branch for how the two are wired together (TASK-GRAPH.md D-002).

Segmentation is strictly linear/contiguous by design: a meeting revisiting
an earlier agenda item at the end produces two separate segments. That is
correct behaviour, not a bug -- grouping non-contiguous same-topic segments
is a later stage's job (plan.md §6), not this module's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math

import numpy as np

from ..utils.config import FeatureBuilderConfig, SegmentationConfig
from ..utils.contracts import (
    AnalysisAtom,
    AtomFeatures,
    HybridSegmentationResult,
    HybridTopicSegment,
    SegmentGram,
)
from ..utils.embeddings import EmbeddingCache
from ..utils.ports import EmbeddingAdapter
from .stage05_atom_features import (
    _CHAR_TOKENIZER_ID,
    _SYLLABLE_TOKENIZER_ID,
    build_full_lexical_weights,
)

# cue_score's "long silence" component (plan.md §3.4) needs a threshold that
# plan.md leaves unspecified. 2000ms is a Thợ-chosen, documented default: an
# ordinary breath/pause in fluent speech rarely exceeds ~1s, so >=2s is a
# reasonably confident "something changed" signal without being so long it
# only fires on already-obvious silences. Not currently exposed on
# SegmentationConfig -- see TIP-004's Completion Report SUGGESTIONS.
_LONG_SILENCE_MS = 2000

# cue_score weights, verbatim from plan.md §3.4.
_CUE_WEIGHT_TRANSITION = 0.45
_CUE_WEIGHT_ENUMERATION = 0.25
_CUE_WEIGHT_CLOSING = 0.20
_CUE_WEIGHT_SPEAKER_CHANGE = 0.25
_CUE_WEIGHT_LONG_SILENCE = 0.15


# ---------------------------------------------------------------------------
# §3.1 Gram matrix
# ---------------------------------------------------------------------------


def _smooth_rows(matrix: np.ndarray, window: int) -> np.ndarray:
    """Sum each row with its +/-``window`` neighbours (plan.md §3.2), clipped
    at the sequence ends -- never crossing the meeting boundary, since one
    call to :func:`segment` is always exactly one meeting."""

    if window <= 0:
        return matrix
    n = matrix.shape[0]
    smoothed = np.zeros_like(matrix)
    for index in range(n):
        lo = max(0, index - window)
        hi = min(n - 1, index + window)
        smoothed[index] = matrix[lo : hi + 1].sum(axis=0)
    return smoothed


def _l2_normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """L2-normalize each row; a genuinely all-zero row (an atom with no
    signal at all on this channel -- e.g. punctuation-only text, or a missing
    embedding dimension) stays exactly zero instead of becoming NaN/Inf. A
    zero vector then contributes 0 cosine similarity to every pair, which is
    the correct "no signal" behaviour, never a false "perfectly similar"."""

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    safe_norms = np.where(norms > 0.0, norms, 1.0)
    return matrix / safe_norms


def _cosine_matrix_from_sparse(
    weight_dicts: Sequence[Mapping[str, float]],
    *,
    smoothing_window: int,
) -> np.ndarray:
    """Dense (n, n) cosine matrix for one lexical channel, built from a
    dense vocabulary-indexed matrix (deterministic column order via
    ``sorted()``, never raw ``set``/``dict`` iteration order) -- see
    :func:`segment`'s module docstring on why this must be the FULL
    per-atom BM25 table, not the top-k-cut ``AtomFeatures`` fields.
    """

    n = len(weight_dicts)
    vocabulary = sorted({term for weights in weight_dicts for term in weights})
    vocab_index = {term: index for index, term in enumerate(vocabulary)}
    matrix = np.zeros((n, len(vocabulary)), dtype=np.float64)
    for row, weights in enumerate(weight_dicts):
        for term, weight in weights.items():
            matrix[row, vocab_index[term]] = weight
    matrix = _smooth_rows(matrix, smoothing_window)
    matrix = _l2_normalize_rows(matrix)
    return matrix @ matrix.T


def _cosine_matrix_from_dense(
    vectors: tuple[tuple[float, ...], ...],
    *,
    smoothing_window: int,
) -> np.ndarray:
    dims = {len(vector) for vector in vectors}
    if len(dims) > 1:
        raise ValueError("EmbeddingAdapter returned inconsistent vector dimensions")
    matrix = np.array(vectors, dtype=np.float64)
    matrix = _smooth_rows(matrix, smoothing_window)
    matrix = _l2_normalize_rows(matrix)
    return matrix @ matrix.T


def _gram_matrix(
    atoms: tuple[AnalysisAtom, ...],
    config: SegmentationConfig,
    feature_config: FeatureBuilderConfig,
    embedding_adapter: EmbeddingAdapter | EmbeddingCache | None,
) -> np.ndarray:
    """``G = beta_dense*S_dense + beta_syllable*S_syllable + beta_char*S_char``
    (plan.md §3.1). Channels are fused as vectors (via this Gram matrix),
    never as separately-computed similarity scores averaged together --
    see the module docstring's warning about asymmetric BM25-as-query use,
    which this deliberately avoids: BM25 weights are used purely as vector
    coordinates, L2-normalized, then dotted -- symmetric, and compatible
    with the DP's prefix-sum cost function below.
    """

    n = len(atoms)
    lexical_weights = build_full_lexical_weights(atoms, feature_config)
    syllable_weights = tuple(pair[0] for pair in lexical_weights)
    char_weights = tuple(pair[1] for pair in lexical_weights)

    s_syllable = _cosine_matrix_from_sparse(
        syllable_weights, smoothing_window=config.smoothing_window
    )
    s_char = _cosine_matrix_from_sparse(
        char_weights, smoothing_window=config.smoothing_window
    )

    if config.beta_dense > 0.0:
        cache = (
            embedding_adapter
            if isinstance(embedding_adapter, EmbeddingCache)
            else EmbeddingCache(embedding_adapter)
        )
        vectors = cache.embed_batch(atom.text_exact for atom in atoms)
        s_dense = _cosine_matrix_from_dense(
            vectors, smoothing_window=config.smoothing_window
        )
        gram = config.beta_dense * s_dense
    else:
        gram = np.zeros((n, n), dtype=np.float64)

    gram = gram + config.beta_syllable * s_syllable + config.beta_char * s_char
    return gram


# ---------------------------------------------------------------------------
# §3.3 cost() via 2-D prefix sums
# ---------------------------------------------------------------------------


def _prefix_sums(gram: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = gram.shape[0]
    prefix = np.zeros((n + 1, n + 1), dtype=np.float64)
    prefix[1:, 1:] = gram.cumsum(axis=0).cumsum(axis=1)
    diagonal = np.concatenate([[0.0], np.cumsum(np.diag(gram))])
    return prefix, diagonal


def _make_cost_fn(prefix: np.ndarray, diagonal: np.ndarray):
    def cost(a: int, b: int) -> float:
        """Contiguous-cluster cost for atoms ``[a, b)``: ``sum(G_ii) -
        (sum of the G block)/span``. Deliberately the general form, not the
        ``(b - a)`` shortcut: ``G_ii`` can be < 1 whenever a channel is
        degenerate for that atom (punctuation-only lexical content, or no
        embedding), and the shortcut assumes every ``G_ii == 1``.
        """

        span = b - a
        block = prefix[b, b] - prefix[a, b] - prefix[b, a] + prefix[a, a]
        return float(diagonal[b] - diagonal[a] - block / span)

    return cost


# ---------------------------------------------------------------------------
# §3.4 cue_score
# ---------------------------------------------------------------------------


def _cue_scores(atom_features: tuple[AtomFeatures, ...]) -> np.ndarray:
    """``cue_score[a]`` per plan.md §3.4's formula, clipped to [0, 1]."""

    scores = np.zeros(len(atom_features), dtype=np.float64)
    for index, feature in enumerate(atom_features):
        cues = feature.cues
        raw = (
            _CUE_WEIGHT_TRANSITION * float(cues.transition_cue)
            + _CUE_WEIGHT_ENUMERATION * float(cues.enumeration_cue)
            + _CUE_WEIGHT_CLOSING * float(cues.closing_cue)
            + _CUE_WEIGHT_SPEAKER_CHANGE * float(cues.speaker_change)
        )
        scores[index] = min(1.0, max(0.0, raw))
    return scores


def _boundary_penalty(a: int, cue_score: np.ndarray, *, gamma: float, lam: float) -> float:
    # a == 0 is the start of the sequence, not a real boundary -- never
    # penalized (plan.md §3.4).
    return 0.0 if a == 0 else gamma * (1.0 - lam * float(cue_score[a]))


# ---------------------------------------------------------------------------
# §3.4 DP: unconstrained K ("penalty" mode)
# ---------------------------------------------------------------------------


def _dp_penalty(
    n: int,
    cost,
    cue_score: np.ndarray,
    *,
    min_len: int,
    max_len: int,
    gamma: float,
    lam: float,
) -> tuple[list[float], list[int]]:
    best = [math.inf] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for b in range(min_len, n + 1):
        lo = max(0, b - max_len)
        hi = b - min_len
        for a in range(lo, hi + 1):
            if best[a] == math.inf:
                continue
            penalty = _boundary_penalty(a, cue_score, gamma=gamma, lam=lam)
            candidate = best[a] + cost(a, b) + penalty
            if candidate < best[b]:
                best[b], back[b] = candidate, a
    return best, back


def _backtrack(back: list[int], n: int) -> list[tuple[int, int]]:
    boundaries: list[tuple[int, int]] = []
    b = n
    while b > 0:
        a = back[b]
        boundaries.append((a, b))
        b = a
    boundaries.reverse()
    return boundaries


# ---------------------------------------------------------------------------
# §3.5 DP: exactly K segments ("fixed" and "elbow" modes)
# ---------------------------------------------------------------------------


def _dp_fixed_k(
    n: int,
    cost,
    cue_score: np.ndarray,
    *,
    min_len: int,
    max_len: int,
    gamma: float,
    lam: float,
    k: int,
) -> tuple[list[list[float]], list[list[int]]]:
    """Same recurrence as :func:`_dp_penalty`, with an added ``k`` dimension
    forcing exactly ``count`` segments to reach ``best[count][b]``. O(n^2*k),
    matching plan.md §3.5's stated complexity."""

    best = [[math.inf] * (n + 1) for _ in range(k + 1)]
    back = [[0] * (n + 1) for _ in range(k + 1)]
    best[0][0] = 0.0
    for count in range(1, k + 1):
        for b in range(min_len, n + 1):
            lo = max(0, b - max_len)
            hi = b - min_len
            for a in range(lo, hi + 1):
                previous = best[count - 1][a]
                if previous == math.inf:
                    continue
                penalty = _boundary_penalty(a, cue_score, gamma=gamma, lam=lam)
                candidate = previous + cost(a, b) + penalty
                if candidate < best[count][b]:
                    best[count][b] = candidate
                    back[count][b] = a
    return best, back


def _backtrack_fixed_k(back: list[list[int]], k: int, n: int) -> list[tuple[int, int]]:
    boundaries: list[tuple[int, int]] = []
    count, b = k, n
    while count > 0:
        a = back[count][b]
        boundaries.append((a, b))
        b = a
        count -= 1
    boundaries.reverse()
    return boundaries


def _solve_fixed(
    n: int, cost, cue_score: np.ndarray, config: SegmentationConfig
) -> list[tuple[int, int]]:
    k = config.k_fixed
    assert k is not None  # SegmentationConfig.__post_init__ guarantees this
    best, back = _dp_fixed_k(
        n,
        cost,
        cue_score,
        min_len=config.min_len,
        max_len=config.max_len,
        gamma=config.gamma,
        lam=config.lam,
        k=k,
    )
    if best[k][n] == math.inf:
        raise ValueError(
            f"segmentation.k_fixed={k} is infeasible for n={n} atoms given "
            f"min_len={config.min_len}/max_len={config.max_len}"
        )
    return _backtrack_fixed_k(back, k, n)


def _reachable_k_range(n: int, min_len: int, max_len: int, k_max: int) -> tuple[int, int]:
    """K values for which SOME partition into exactly K segments respects
    min_len/max_len -- plan.md's elbow spec (§3.5) does not address this, so
    this is a Thợ addition: without it, K near 1 or near k_max is often
    infeasible (e.g. K=1 needs n <= max_len) and best[K][n] is +inf, which
    would corrupt the elbow line-distance calculation below.
    """

    lo = max(1, math.ceil(n / max_len))
    hi = max(lo, min(k_max, n // min_len))
    return lo, hi


def _solve_elbow(
    n: int, cost, cue_score: np.ndarray, config: SegmentationConfig
) -> list[tuple[int, int]]:
    lo, hi = _reachable_k_range(n, config.min_len, config.max_len, config.k_max)
    points: list[tuple[int, float, list[tuple[int, int]]]] = []
    for k in range(lo, hi + 1):
        best, back = _dp_fixed_k(
            n,
            cost,
            cue_score,
            min_len=config.min_len,
            max_len=config.max_len,
            gamma=config.gamma,
            lam=config.lam,
            k=k,
        )
        if best[k][n] == math.inf:
            continue
        points.append((k, best[k][n], _backtrack_fixed_k(back, k, n)))

    if not points:
        raise ValueError(
            "segmentation: no feasible K found for k_mode='elbow' given "
            f"n={n}, min_len={config.min_len}, max_len={config.max_len}, "
            f"k_max={config.k_max}"
        )
    if len(points) == 1:
        return points[0][2]

    # Standard elbow method: normalize both axes to [0, 1], then pick the
    # point with the largest perpendicular distance to the line joining the
    # first and last points. Deterministic (no randomness); ties keep the
    # first (smallest K) point found, via strict ">" below.
    ks = [point[0] for point in points]
    costs = [point[1] for point in points]
    k_min, k_max_reached = min(ks), max(ks)
    cost_min, cost_max = min(costs), max(costs)
    k_range = (k_max_reached - k_min) or 1
    cost_range = (cost_max - cost_min) or 1.0

    x1, y1 = 0.0, (costs[0] - cost_min) / cost_range
    x2, y2 = 1.0, (costs[-1] - cost_min) / cost_range
    line_dx, line_dy = x2 - x1, y2 - y1
    line_length = math.sqrt(line_dx**2 + line_dy**2) or 1.0

    best_index = 0
    best_distance = -1.0
    for index, (k, point_cost, _boundaries) in enumerate(points):
        x0 = (k - k_min) / k_range
        y0 = (point_cost - cost_min) / cost_range
        distance = abs(line_dy * x0 - line_dx * y0 + x2 * y1 - y2 * x1) / line_length
        if distance > best_distance:
            best_distance = distance
            best_index = index
    return points[best_index][2]


def _solve_penalty(
    n: int, cost, cue_score: np.ndarray, config: SegmentationConfig
) -> list[tuple[int, int]]:
    _best, back = _dp_penalty(
        n,
        cost,
        cue_score,
        min_len=config.min_len,
        max_len=config.max_len,
        gamma=config.gamma,
        lam=config.lam,
    )
    return _backtrack(back, n)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _config_fingerprint(
    config: SegmentationConfig,
    embedding_adapter: EmbeddingAdapter | EmbeddingCache | None,
) -> str:
    if embedding_adapter is None:
        model_id = "none"
    else:
        model_id = str(
            getattr(embedding_adapter, "model_id", None)
            or getattr(embedding_adapter, "model", None)
            or type(embedding_adapter).__name__
        )
    payload = "|".join(
        [
            f"beta_dense={config.beta_dense}",
            f"beta_syllable={config.beta_syllable}",
            f"beta_char={config.beta_char}",
            f"gamma={config.gamma}",
            f"lam={config.lam}",
            f"min_len={config.min_len}",
            f"max_len={config.max_len}",
            f"smoothing_window={config.smoothing_window}",
            f"k_mode={config.k_mode}",
            f"k_fixed={config.k_fixed}",
            f"k_max={config.k_max}",
            f"syllable_tokenizer={_SYLLABLE_TOKENIZER_ID}",
            f"char_tokenizer={_CHAR_TOKENIZER_ID}",
            f"model_id={model_id}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _segment_id(config_fingerprint: str, start_index: int) -> str:
    return f"HSEG_{config_fingerprint[:12]}_{start_index:06d}"


def _validate_atom_features(
    atoms: tuple[AnalysisAtom, ...], atom_features: tuple[AtomFeatures, ...]
) -> tuple[AtomFeatures, ...]:
    feature_by_id: dict[str, AtomFeatures] = {}
    for feature in atom_features:
        if feature.atom_id in feature_by_id:
            raise ValueError("segmentation requires unique feature atom IDs")
        feature_by_id[feature.atom_id] = feature
    atom_ids = tuple(atom.atom_id for atom in atoms)
    expected = set(atom_ids)
    actual = set(feature_by_id)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise ValueError(
            "segmentation atom_features must align one-to-one with atoms"
            + (": " + "; ".join(details) if details else "")
        )
    return tuple(feature_by_id[atom_id] for atom_id in atom_ids)


def segment(
    atoms: tuple[AnalysisAtom, ...],
    atom_features: tuple[AtomFeatures, ...],
    config: SegmentationConfig,
    *,
    embedding_adapter: EmbeddingAdapter | EmbeddingCache | None = None,
    feature_config: FeatureBuilderConfig | None = None,
) -> HybridSegmentationResult:
    """Run the DP-optimal hybrid segmenter (plan.md §3) over one meeting's
    atom stream. Never reorders/merges/splits atoms outside the returned
    segment boundaries -- boundaries are on atom INDICES only.

    ``feature_config`` (TIP-004 addition -- see ``build_full_lexical_weights``'s
    docstring) controls the full-support lexical BM25 recomputation used for
    the Gram matrix's syllable/char channels; it defaults to
    ``FeatureBuilderConfig()`` when omitted. It intentionally does not need to
    be the exact config used to build ``atom_features`` -- ``atom_features``
    is only consulted here for ``AtomFeatures.cues``, never for its (top-k
    cut) ``lex_syllable``/``lex_char`` fields.
    """

    atom_ids = tuple(atom.atom_id for atom in atoms)
    if len(atom_ids) != len(set(atom_ids)):
        raise ValueError("segmentation requires unique atom IDs")
    ordered_features = _validate_atom_features(atoms, atom_features)

    config_fingerprint = _config_fingerprint(config, embedding_adapter)
    n = len(atoms)
    if n == 0:
        return HybridSegmentationResult((), 0.0, config_fingerprint)

    if config.beta_dense > 0.0 and embedding_adapter is None:
        raise ValueError(
            "segmentation.beta_dense > 0 requires an embedding_adapter; "
            "pass one, or set beta_dense=0 to run lexical-only"
        )

    resolved_feature_config = feature_config or FeatureBuilderConfig()
    gram = _gram_matrix(atoms, config, resolved_feature_config, embedding_adapter)
    prefix, diagonal = _prefix_sums(gram)
    cost = _make_cost_fn(prefix, diagonal)
    cue_score = _cue_scores(ordered_features)

    if n < config.min_len:
        single_cost = cost(0, n)
        segment_obj = HybridTopicSegment(
            segment_id=_segment_id(config_fingerprint, 0),
            atom_ids=atom_ids,
            start_index=0,
            end_index=n,
            cost=single_cost,
            boundary_cue_score=float(cue_score[0]),
        )
        return HybridSegmentationResult((segment_obj,), single_cost, config_fingerprint)

    if config.k_mode == "fixed":
        boundaries = _solve_fixed(n, cost, cue_score, config)
    elif config.k_mode == "elbow":
        boundaries = _solve_elbow(n, cost, cue_score, config)
    else:
        boundaries = _solve_penalty(n, cost, cue_score, config)

    segments: list[HybridTopicSegment] = []
    for a, b in boundaries:
        segments.append(
            HybridTopicSegment(
                segment_id=_segment_id(config_fingerprint, a),
                atom_ids=atom_ids[a:b],
                start_index=a,
                end_index=b,
                cost=cost(a, b),
                boundary_cue_score=float(cue_score[a]),
            )
        )

    owned = tuple(atom_id for segment_obj in segments for atom_id in segment_obj.atom_ids)
    if owned != atom_ids or len(owned) != len(set(owned)):
        raise AssertionError("hybrid segments must own every atom exactly once, in order")

    total_cost = sum(segment_obj.cost for segment_obj in segments)
    return HybridSegmentationResult(tuple(segments), total_cost, config_fingerprint)


def build_segment_gram(
    atoms: tuple[AnalysisAtom, ...],
    config: SegmentationConfig,
    *,
    embedding_adapter: EmbeddingAdapter | EmbeddingCache | None = None,
    feature_config: FeatureBuilderConfig | None = None,
) -> SegmentGram:
    """Export the same fused Gram matrix + prefix sums :func:`segment`
    computes internally, so Stage 8's recurrence semantic branch can score
    arbitrary (non-adjacent) segment pairs on the same channels/scale as
    Stage 6's boundary cost (plan_stage_7_8.md §3.2,
    TASK-GRAPH-stage7-8.md D-105).

    Deliberately NOT threaded through :class:`HybridSegmentationResult` --
    that TIP-004/005 contract stays untouched, so this recomputes the Gram
    matrix rather than reusing one already built by a :func:`segment` call
    (not free, but zero blast radius on Stage 6/eval). Same error behaviour
    as :func:`segment`: ``beta_dense > 0`` without an ``embedding_adapter``
    raises ``ValueError`` -- callers must not catch it silently, since it
    means "same_similarity requested a channel with no data source", a
    configuration error, not a runtime condition to fall back from.
    """

    atom_ids = tuple(atom.atom_id for atom in atoms)
    if len(atom_ids) != len(set(atom_ids)):
        raise ValueError("segmentation requires unique atom IDs")
    if config.beta_dense > 0.0 and embedding_adapter is None:
        raise ValueError(
            "segmentation.beta_dense > 0 requires an embedding_adapter; "
            "pass one, or set beta_dense=0 to run lexical-only"
        )
    resolved_feature_config = feature_config or FeatureBuilderConfig()
    gram = _gram_matrix(atoms, config, resolved_feature_config, embedding_adapter)
    prefix, _diagonal = _prefix_sums(gram)
    return SegmentGram(
        atom_order=atom_ids,
        prefix=tuple(tuple(float(value) for value in row) for row in prefix.tolist()),
    )


__all__ = ["build_segment_gram", "segment"]
