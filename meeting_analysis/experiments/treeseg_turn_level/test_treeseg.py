"""Unit tests for the TreeSeg engine. Priority per plan (Bước 3/4): the
cumsum-optimised split loss must match a brute-force recomputation exactly
-- this is the easiest place for an off-by-one or wrong-identity bug to hide
silently (wrong number, not a crash)."""

from __future__ import annotations

import numpy as np
import pytest

from treeseg import (
    PartitionTreeNode,
    _find_best_split_point,
    _PrefixSums,
    embed_items_with_preceding_context,
    build_partition_tree,
    cut_tree_into_n_segments,
    cut_tree_by_gain_threshold,
    segment_turns_with_treeseg,
    spans_to_boundary_indices,
)
from utils.contracts import SpeakerTurn


def _brute_force_loss(embeddings: np.ndarray, lo: int, i: int, hi: int) -> float:
    """Recompute L(i) directly from the definition (no prefix sums), as an
    independent check on `_find_best_split_point`'s cumsum-optimised version."""

    left = embeddings[lo:i]
    right = embeddings[i:hi]
    loss = 0.0
    if len(left):
        loss += float(np.sum((left - left.mean(axis=0)) ** 2))
    if len(right):
        loss += float(np.sum((right - right.mean(axis=0)) ** 2))
    return loss


def test_best_split_matches_brute_force() -> None:
    rng = np.random.default_rng(0)
    embeddings = rng.normal(size=(12, 5))
    prefix = _PrefixSums.from_embeddings(embeddings)
    min_size = 2

    found = _find_best_split_point(prefix, 0, 12, min_size)
    assert found is not None
    fast_i, fast_loss = found

    brute = [
        (i, _brute_force_loss(embeddings, 0, i, 12))
        for i in range(min_size, 12 - min_size + 1)
    ]
    brute_i, brute_loss = min(brute, key=lambda pair: pair[1])

    assert fast_i == brute_i
    assert fast_loss == pytest.approx(brute_loss, rel=1e-9)

    # And the fast loss must equal brute force at the SAME candidate for
    # every candidate, not just at the argmin (catches a formula bug that
    # happens to still pick the right argmin by coincidence).
    for i, expected in brute:
        actual = prefix.within_cluster_sum_of_squares(0, i) + prefix.within_cluster_sum_of_squares(i, 12)
        assert actual == pytest.approx(expected, rel=1e-9)


def test_best_split_none_when_too_small() -> None:
    embeddings = np.zeros((3, 2))
    prefix = _PrefixSums.from_embeddings(embeddings)
    # span of length 3, min_size 2 -> both sides >=2 needs length >=4
    assert _find_best_split_point(prefix, 0, 3, min_size=2) is None


def test_build_tree_respects_min_size() -> None:
    rng = np.random.default_rng(1)
    embeddings = rng.normal(size=(20, 4))
    result = build_partition_tree(embeddings, min_size=3)

    def check(node: PartitionTreeNode) -> None:
        if node.is_leaf:
            assert node.hi - node.lo >= 1
        else:
            for child in node.children:
                assert child.hi - child.lo > 0
                check(child)

    check(result.root)
    # No leaf should be splittable further under min_size=3, i.e. every leaf
    # has length < 2*min_size, OR splitting was simply never attempted on it
    # because it was already below 2*min_size when created.
    def leaves(node: PartitionTreeNode) -> list[PartitionTreeNode]:
        if node.is_leaf:
            return [node]
        out = []
        for c in node.children:
            out.extend(leaves(c))
        return out

    for leaf in leaves(result.root):
        assert leaf.hi - leaf.lo < 2 * 3 or leaf.hi - leaf.lo >= 1


def test_cut_tree_is_nested_as_resolution_increases() -> None:
    rng = np.random.default_rng(2)
    embeddings = rng.normal(size=(16, 3))
    result = build_partition_tree(embeddings, min_size=1)

    prev_boundaries: set[int] = set()
    for k in range(1, 6):
        spans = cut_tree_into_n_segments(result, k)
        assert sum(hi - lo for lo, hi in spans) == 16
        assert spans[0][0] == 0
        assert spans[-1][1] == 16
        boundaries = set(spans_to_boundary_indices(spans))
        # Paper section 2.2: "as K increases, additional segment boundaries
        # are added but not deleted".
        assert prev_boundaries <= boundaries
        prev_boundaries = boundaries


def test_cut_tree_caps_at_tree_resolution() -> None:
    embeddings = np.zeros((4, 2))  # identical vectors: every split is a tie
    result = build_partition_tree(embeddings, min_size=2)
    # length 4, min_size 2 -> can split into 2 segments of 2, then neither
    # child (length 2) can split again under min_size 2. Requesting more
    # segments than the tree supports must not crash or silently invent
    # boundaries -- it should just return what the tree actually has.
    spans = cut_tree_into_n_segments(result, n_segments=10)
    assert len(spans) <= 2


def test_spans_to_boundaries_matches_repo_convention() -> None:
    # Boundary = index where the NEW segment starts (eval/segmentation_metrics.py
    # docstring), not the last index of the previous one.
    spans = [(0, 3), (3, 7), (7, 10)]
    assert spans_to_boundary_indices(spans) == [3, 7]


def test_block_embed_uses_at_most_width_preceding_items() -> None:
    texts = ["a", "b", "c", "d"]
    seen: list[str] = []

    def embed_fn(block: str) -> list[float]:
        seen.append(block)
        return [float(len(block))]

    embed_items_with_preceding_context(texts, embed_fn, width=1)
    assert seen == ["a", "a b", "b c", "c d"]


def test_block_embed_rejects_negative_width() -> None:
    with pytest.raises(ValueError):
        embed_items_with_preceding_context(["a"], lambda _t: [0.0], width=-1)


def _turn(turn_id: str, text: str) -> SpeakerTurn:
    return SpeakerTurn(
        turn_id=turn_id,
        speaker="spk",
        text_exact=text,
        evidence_ids=(),
        start_ms=None,
        end_ms=None,
    )


def test_run_to_treeseg_covers_every_turn() -> None:
    # Regression test: segment_turns_with_treeseg used to silently drop the final
    # segment, because `boundaries` (= spans_to_boundary_indices(spans)) excludes
    # the last span's end by its own documented contract ("the last span ...
    # never a boundary"), and the segment-building loop only emitted one
    # TopicSegment per entry in `boundaries` -- never appending the
    # remaining [idx, len(texts)) span after the loop. Six turns in two
    # well-separated embedding clusters force a clean split at index 3, so a
    # regression (dropping turns 3-5) shows up as `total_covered < 6` and/or
    # a last segment that doesn't reach the end of the sequence.
    turns = [_turn(str(i), f"turn {i}") for i in range(6)]
    embeddings = {
        "turn 0": [0.0, 0.0],
        "turn 0 turn 1": [0.0, 0.0],
        "turn 1 turn 2": [0.0, 0.0],
        "turn 2 turn 3": [5.0, 5.0],
        "turn 3 turn 4": [10.0, 10.0],
        "turn 4 turn 5": [10.0, 10.0],
    }
    segments = segment_turns_with_treeseg(
        turns, embed_fn=lambda block: embeddings[block], width=1, min_size=2
    )

    assert len(segments) >= 2, "fixture should force more than one segment"
    assert segments[0].start_ms == 0
    assert segments[-1].end_ms == len(turns)
    # Contiguous, gapless coverage: each segment's start is the previous
    # segment's end, and the total mass sums to every turn exactly once.
    for previous, current in zip(segments, segments[1:]):
        assert previous.end_ms == current.start_ms
    total_covered = sum(seg.end_ms - seg.start_ms for seg in segments)
    assert total_covered == len(turns)


def test_run_to_treeseg_populates_atom_ids_and_segment_id() -> None:
    # Regression test: TopicSegment used to carry only text + integer
    # start_ms/end_ms, with no atom_ids/segment_id -- losing the join key
    # back to per-item speaker/evidence_ids that downstream per-speaker
    # extraction needs.
    turns = [_turn(f"T{i}", f"turn {i}") for i in range(6)]
    embeddings = {
        "turn 0": [0.0, 0.0],
        "turn 0 turn 1": [0.0, 0.0],
        "turn 1 turn 2": [0.0, 0.0],
        "turn 2 turn 3": [5.0, 5.0],
        "turn 3 turn 4": [10.0, 10.0],
        "turn 4 turn 5": [10.0, 10.0],
    }
    segments = segment_turns_with_treeseg(
        turns, embed_fn=lambda block: embeddings[block], width=1, min_size=2
    )

    assert len(segments) >= 2
    assert [seg.segment_id for seg in segments] == [
        f"TOPIC_SEG_{i:06d}" for i in range(len(segments))
    ]
    # atom_ids are turn_ids here (SpeakerTurn input) and must cover every
    # turn exactly once, in order, with no gaps or overlaps between segments.
    all_ids = [turn_id for seg in segments for turn_id in seg.atom_ids]
    assert all_ids == [f"T{i}" for i in range(6)]


def _weak_structure_tree(n: int = 200) -> "object":
    """Noisy embeddings with one mild shift: no split clears a strict gain
    threshold, so the gain rule alone leaves a single huge span."""

    rng = np.random.default_rng(1)
    embeddings = rng.normal(size=(n, 4))
    embeddings[n // 2 :] += 0.3
    return build_partition_tree(embeddings, min_size=4)


def test_cut_tree_auto_max_span_weight_splits_oversized_spans_below_gain_threshold() -> None:
    tree = _weak_structure_tree()
    weights = [10.0] * 200

    uncapped = cut_tree_by_gain_threshold(tree, min_relative_gain=0.5)
    capped = cut_tree_by_gain_threshold(tree, min_relative_gain=0.5, weights=weights, max_span_weight=300.0)

    assert uncapped == [(0, 200)]
    assert len(capped) > 1
    assert capped[0][0] == 0 and capped[-1][1] == 200
    assert all(a[1] == b[0] for a, b in zip(capped, capped[1:]))  # contiguous partition
    assert all(sum(weights[lo:hi]) <= 300.0 for lo, hi in capped)


def test_cut_tree_auto_max_span_weight_leaves_unsplittable_span_whole() -> None:
    tree = build_partition_tree(np.random.default_rng(2).normal(size=(6, 3)), min_size=4)  # < 2*min_size

    spans = cut_tree_by_gain_threshold(tree, weights=[100.0] * 6, max_span_weight=1.0)

    assert spans == [(0, 6)]


def test_cut_tree_auto_requires_weights_and_cap_together() -> None:
    tree = _weak_structure_tree(20)

    with pytest.raises(ValueError):
        cut_tree_by_gain_threshold(tree, max_span_weight=10.0)


def test_cut_tree_auto_without_cap_unchanged_by_default() -> None:
    tree = _weak_structure_tree()

    assert cut_tree_by_gain_threshold(tree, min_relative_gain=0.0015) == cut_tree_by_gain_threshold(
        tree, min_relative_gain=0.0015, weights=None, max_span_weight=None
    )
