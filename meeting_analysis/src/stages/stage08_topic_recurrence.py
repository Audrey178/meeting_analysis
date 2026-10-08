"""Stage 8: decide which segments are the same topic coming back.

The semantic-similarity branch runs first (needed to decide what the LLM
branch can skip), then the LLM-judge branch -- SEQUENTIAL between the two
branches, not parallel (TIP-010, TASK-GRAPH-stage7-8.md D-104). What IS
parallelized is the LLM branch's per-pair calls, which are independent of
each other. The default ``consensus`` policy merges only when both branches
agree and clear the threshold. Disagreement and abstention are preserved as
audit decisions rather than silently resolved, and recurrence never
reorders events.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
import dataclasses
from dataclasses import replace
from itertools import islice
import json
import math

from ..utils.config import TopicRecurrenceConfig
from ..utils.contracts import (
    AnalysisAtom,
    SegmentGram,
    TopicLabel,
    TopicMap,
    TopicRecurrenceDecision,
    TopicRecurrenceVote,
    TopicSegment,
)
from ..utils.ports import LLMAdapter, SemanticSimilarityAdapter, TopicRecurrenceLLMAdapter
from ._shared import LexicalCosineSimilarity, join_atoms
from .stage07_topic_labeling import _FALLBACK_METHODS

# Reason codes llm_branch() sets when it never actually called the LLM for a
# pair -- these must never be conflated with a genuine model abstention
# (TIP-009, plan_stage_7_8.md §3.1).
_LLM_SKIP_REASONS = frozenset(
    {"skipped_below_threshold", "skipped_high_confidence", "llm_adapter_unavailable"}
)


class StructuredLLMTopicRecurrenceChecker:
    """Structured LLM judge for the recurrence branch; it may abstain."""

    def __init__(self, llm: LLMAdapter, *, model_name: str = "configured-llm") -> None:
        self.llm = llm
        self.model_name = model_name

    def check_same_topic(
        self,
        source_label: TopicLabel,
        target_label: TopicLabel,
        source_text: str,
        target_text: str,
    ) -> tuple[bool | None, str | None]:
        result = self.llm.generate_json(
            system_prompt=(
                "Xác định hai đoạn không liền kề có quay lại cùng một topic hay "
                "không. Không suy diễn từ agenda.\n"
                "- 'same': có bằng chứng cụ thể cho thấy hai đoạn nói về cùng "
                "một chủ đề/sự việc (trùng tên, sự kiện, hoặc mạch nội dung "
                "nối tiếp rõ ràng).\n"
                "- 'different': bạn có đủ căn cứ để kết luận hai đoạn nói về "
                "chủ đề khác nhau -- kể cả khi lý do chỉ là 'không có điểm "
                "chung nào về sự kiện/nhân vật/chủ đề'. Đây vẫn là một kết "
                "luận có căn cứ, không phải abstain.\n"
                "- 'abstain': CHỈ dùng khi bản thân bạn không đủ thông tin để "
                "kết luận theo bất kỳ hướng nào (ví dụ nội dung quá ngắn hoặc "
                "quá mơ hồ để phân tích) -- không dùng khi bạn tin là "
                "'different' nhưng chỉ thiếu bằng chứng cho 'same'."
            ),
            user_prompt=json.dumps(
                {
                    "source": {
                        "title": source_label.title,
                        "summary": source_label.summary,
                        "text_exact": source_text,
                    },
                    "target": {
                        "title": target_label.title,
                        "summary": target_label.summary,
                        "text_exact": target_text,
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            schema={
                "type": "object",
                "required": ["decision", "reason"],
                "properties": {
                    "decision": {"enum": ["same", "different", "abstain"]},
                    "reason": {"type": "string"},
                },
            },
        )
        decision = result.get("decision")
        reason = result.get("reason")
        if not isinstance(reason, str):
            raise ValueError("topic recurrence LLM reason must be a string")
        if decision == "same":
            return True, reason
        if decision == "different":
            return False, reason
        if decision == "abstain":
            return None, reason
        raise ValueError(
            "topic recurrence LLM decision must be same, different, or abstain"
        )


def _segment_texts(
    segments: tuple[TopicSegment, ...], atoms: tuple[AnalysisAtom, ...]
) -> dict[str, str]:
    registry = {atom.atom_id: atom for atom in atoms}
    return {
        segment.segment_id: join_atoms(
            tuple(registry[atom_id] for atom_id in segment.atom_ids)
        )
        for segment in segments
    }


def _candidate_pairs(
    segments: tuple[TopicSegment, ...],
) -> Iterator[tuple[TopicSegment, TopicSegment]]:
    """Enumerate non-adjacent candidates fairly by recurrence distance.

    Near recurrences are evaluated across the whole transcript before more
    distant pairs, so a pair cap does not systematically favor early topics.
    """

    for distance in range(2, len(segments)):
        for left in range(0, len(segments) - distance):
            yield segments[left], segments[left + distance]


def _block_sum(
    prefix: tuple[tuple[float, ...], ...], a0: int, a1: int, b0: int, b1: int
) -> float:
    """Generic 2-D prefix-sum range query: sum of ``gram[a0:a1, b0:b1]``.
    Same inclusion-exclusion formula ``segmentation._make_cost_fn`` uses for
    its diagonal-only ``cost(a, b)``, generalized to two independent
    (possibly disjoint) ranges."""

    return prefix[a1][b1] - prefix[a0][b1] - prefix[a1][b0] + prefix[a0][b0]


def _atom_span(atom_ids: tuple[str, ...], index_of: Mapping[str, int]) -> tuple[int, int]:
    indices = [index_of[atom_id] for atom_id in atom_ids]
    start, end = indices[0], indices[-1] + 1
    if indices != list(range(start, end)):
        raise ValueError(
            "GramSegmentSimilarity requires a segment's atom_ids to map to a "
            "contiguous, increasing range in the Gram matrix's atom_order -- "
            "topic segments never reorder atoms, so this indicates a bug "
            "upstream, not a data condition to silently handle"
        )
    return start, end


class _GramSegmentSimilarity:
    """cos(mu_a, mu_b) via Stage 6's Gram-matrix prefix sums
    (plan_stage_7_8.md §3.2). NOT a ``SemanticSimilarityAdapter``: it needs
    atom-id membership, not raw text, so :func:`resolve_topic_recurrence`
    selects it by segment_id pair rather than routing it through the
    generic text-based Protocol (TASK-GRAPH-stage7-8.md D-105 point 4)."""

    model_name = "gram-segment-cosine-v1"

    def __init__(self, gram: SegmentGram, segments: tuple[TopicSegment, ...]) -> None:
        index_of = {atom_id: index for index, atom_id in enumerate(gram.atom_order)}
        self._prefix = gram.prefix
        self._spans: dict[str, tuple[int, int]] = {
            segment.segment_id: _atom_span(segment.atom_ids, index_of)
            for segment in segments
        }

    def score(self, source_segment_id: str, target_segment_id: str) -> tuple[float, str | None]:
        a0, a1 = self._spans[source_segment_id]
        b0, b1 = self._spans[target_segment_id]
        b_aa = _block_sum(self._prefix, a0, a1, a0, a1)
        b_bb = _block_sum(self._prefix, b0, b1, b0, b1)
        if b_aa <= 0.0 or b_bb <= 0.0:
            return 0.0, "empty_segment_vector"
        b_ab = _block_sum(self._prefix, a0, a1, b0, b1)
        cosine = b_ab / math.sqrt(b_aa * b_bb)
        # Dense embeddings can yield a slightly negative cosine; the
        # contract is 0.0 <= score <= 1.0 and a negative value already means
        # "clearly unrelated" -- clamp to 0, do NOT affine-map (x+1)/2,
        # which would push a confidently-negative pair up toward 0.5 and
        # corrupt semantic_threshold (plan_stage_7_8.md §3.2).
        return max(0.0, cosine), None


def _truncate_for_judge(text: str, max_chars: int) -> tuple[str, bool]:
    """60/40 head/tail split with a "[...]" gap marker so an oversized
    segment does not blow up the judge prompt (plan_stage_7_8.md §3.5).
    Never summarizes -- that would risk losing the grounding the judge is
    supposed to check against. Returns ``(text, was_truncated)``."""

    if len(text) <= max_chars:
        return text, False
    marker = "[...]"
    budget = max_chars - len(marker)
    if budget <= 0:
        return text[:max_chars], True
    head_len = int(budget * 0.6)
    tail_len = budget - head_len
    return text[:head_len] + marker + text[len(text) - tail_len :], True


def _judge_safe_label(label: TopicLabel) -> TopicLabel:
    """Blank out title/summary for a judge payload when Stage 7 fell back
    to a deterministic label (plan_stage_7_8.md §3.6) -- the judge still
    has ``text_exact``, the real grounding, so it is not blind, just no
    longer led astray by a degraded/generic title."""

    if label.method in _FALLBACK_METHODS:
        return dataclasses.replace(label, title="", summary="")
    return label


def resolve_topic_recurrence(
    segments: tuple[TopicSegment, ...],
    labels: tuple[TopicLabel, ...],
    atoms: tuple[AnalysisAtom, ...],
    config: TopicRecurrenceConfig,
    *,
    semantic_adapter: SemanticSimilarityAdapter | None = None,
    llm_adapter: TopicRecurrenceLLMAdapter | None = None,
    gram: SegmentGram | None = None,
) -> TopicMap:
    """Score candidate pairs with the semantic branch, then judge the ones
    that need it with the LLM branch. The two branches run SEQUENTIALLY --
    ``llm_branch`` needs every semantic score first to decide what to skip,
    so they cannot run concurrently (see TASK-GRAPH-stage7-8.md D-104). The
    genuinely parallel part is the per-pair LLM calls INSIDE ``llm_branch``,
    which are independent of each other (``config.llm_max_workers``)."""

    segment_ids = tuple(segment.segment_id for segment in segments)
    if len(segment_ids) != len(set(segment_ids)):
        raise ValueError("topic recurrence requires unique segment IDs")
    atom_registry_ids = {atom.atom_id for atom in atoms}
    for segment in segments:
        missing = tuple(
            atom_id for atom_id in segment.atom_ids if atom_id not in atom_registry_ids
        )
        if missing:
            raise ValueError(
                f"topic recurrence segment {segment.segment_id!r} references "
                f"unknown atom_ids: {', '.join(missing)}"
            )
    if len(labels) != len(segments):
        raise ValueError("topic recurrence requires exactly one label per segment")
    label_by_segment = {label.segment_id: label for label in labels}
    if len(label_by_segment) != len(labels):
        raise ValueError("topic recurrence labels must have unique segment IDs")
    if set(label_by_segment) != {segment.segment_id for segment in segments}:
        raise ValueError("topic recurrence requires exactly one label per segment")
    texts = _segment_texts(segments, atoms)
    candidate_pair_count = (
        0
        if len(segments) < 3
        else (len(segments) - 1) * (len(segments) - 2) // 2
    )
    pairs = tuple(
        islice(_candidate_pairs(segments), config.max_candidate_pairs)
    )
    use_gram = config.use_gram_similarity and gram is not None
    gram_scorer = _GramSegmentSimilarity(gram, segments) if use_gram else None
    scorer = None if use_gram else (semantic_adapter or LexicalCosineSimilarity())

    def semantic_branch() -> tuple[TopicRecurrenceVote, ...]:
        votes: list[TopicRecurrenceVote] = []
        for source, target in pairs:
            if gram_scorer is not None:
                score, reason = gram_scorer.score(source.segment_id, target.segment_id)
                model_name = gram_scorer.model_name
            else:
                score = float(
                    scorer.similarity(texts[source.segment_id], texts[target.segment_id])
                )
                reason = None
                model_name = getattr(scorer, "model_name", type(scorer).__name__)
            if not 0.0 <= score <= 1.0:
                raise ValueError("semantic recurrence score must be between 0 and 1")
            votes.append(
                TopicRecurrenceVote(
                    branch="semantic",
                    source_segment_id=source.segment_id,
                    target_segment_id=target.segment_id,
                    same_topic=score >= config.semantic_threshold,
                    score=score,
                    reason=reason,
                    model_name=model_name,
                )
            )
        return tuple(votes)

    def llm_branch(
        semantic_votes: tuple[TopicRecurrenceVote, ...]
    ) -> tuple[TopicRecurrenceVote, ...]:
        """Call the LLM only for the gray zone; the outcome outside it is
        already fixed by the semantic vote under every supported join policy,
        so skipping the call there changes cost, not merge decisions. The
        per-pair calls that DO happen are independent of each other and run
        on a thread pool (config.llm_max_workers) -- results are re-joined
        by INDEX, never by completion order, so this stays deterministic."""

        def needs_llm(index: int) -> bool:
            score = semantic_votes[index].score
            below_threshold = score is not None and score < config.semantic_threshold
            # High-confidence skip is safe only for the join policy designed
            # to treat "score high + LLM abstained" as a merge; the strict
            # consensus default must still see a real LLM vote at high
            # score, since it never merges on semantic score alone.
            high_confidence_skip = (
                score is not None
                and score >= config.semantic_high_confidence
                and config.join_policy == "consensus_or_semantic_high"
            )
            return not below_threshold and not high_confidence_skip and llm_adapter is not None

        def skipped_vote(index: int) -> TopicRecurrenceVote:
            source, target = pairs[index]
            score = semantic_votes[index].score
            below_threshold = score is not None and score < config.semantic_threshold
            high_confidence_skip = (
                score is not None
                and score >= config.semantic_high_confidence
                and config.join_policy == "consensus_or_semantic_high"
            )
            if below_threshold:
                reason = "skipped_below_threshold"
            elif high_confidence_skip:
                reason = "skipped_high_confidence"
            else:
                reason = "llm_adapter_unavailable"
            return TopicRecurrenceVote(
                branch="llm",
                source_segment_id=source.segment_id,
                target_segment_id=target.segment_id,
                same_topic=None,
                reason=reason,
                model_name=None,
            )

        def judge(index: int) -> TopicRecurrenceVote:
            source, target = pairs[index]
            source_text, source_truncated = _truncate_for_judge(
                texts[source.segment_id], config.max_judge_chars
            )
            target_text, target_truncated = _truncate_for_judge(
                texts[target.segment_id], config.max_judge_chars
            )
            source_label = _judge_safe_label(label_by_segment[source.segment_id])
            target_label = _judge_safe_label(label_by_segment[target.segment_id])
            same_topic, model_reason = llm_adapter.check_same_topic(
                source_label, target_label, source_text, target_text
            )
            if same_topic is not None and not isinstance(same_topic, bool):
                raise ValueError("LLM recurrence decision must be bool or None")
            if model_reason is not None and not isinstance(model_reason, str):
                raise ValueError("LLM recurrence reason must be a string or None")
            extra_reasons = []
            if source_truncated:
                extra_reasons.append("source_truncated")
            if target_truncated:
                extra_reasons.append("target_truncated")
            if source_label.method in _FALLBACK_METHODS or target_label.method in _FALLBACK_METHODS:
                extra_reasons.append("degraded_label_input")
            if extra_reasons:
                reason = (
                    model_reason + " | " + ",".join(extra_reasons)
                    if model_reason
                    else ",".join(extra_reasons)
                )
            else:
                reason = model_reason
            return TopicRecurrenceVote(
                branch="llm",
                source_segment_id=source.segment_id,
                target_segment_id=target.segment_id,
                same_topic=same_topic,
                reason=reason,
                model_name=getattr(llm_adapter, "model_name", type(llm_adapter).__name__),
            )

        with ThreadPoolExecutor(
            max_workers=config.llm_max_workers, thread_name_prefix="topic-recurrence-llm"
        ) as pool:
            futures = {
                index: pool.submit(judge, index)
                for index in range(len(pairs))
                if needs_llm(index)
            }
            return tuple(
                skipped_vote(index) if index not in futures else futures[index].result()
                for index in range(len(pairs))
            )

    semantic_votes = semantic_branch()
    llm_votes = llm_branch(semantic_votes)

    # Upper bound is strict: a score exactly == semantic_high_confidence is
    # the boundary `high_confidence_skip` (llm_branch) uses with `>=`, so a
    # `<=` here double-counted that point as both gray-zone AND skipped
    # (plan_stage_7_8.md §3.4).
    gray_zone_pair_count = sum(
        1
        for vote in semantic_votes
        if vote.score is not None
        and config.semantic_threshold <= vote.score < config.semantic_high_confidence
    )

    parents = {segment.segment_id: segment.segment_id for segment in segments}
    members = {
        segment.segment_id: {segment.segment_id} for segment in segments
    }
    segment_order = {
        segment.segment_id: index for index, segment in enumerate(segments)
    }

    def find(segment_id: str) -> str:
        while parents[segment_id] != segment_id:
            parents[segment_id] = parents[parents[segment_id]]
            segment_id = parents[segment_id]
        return segment_id

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            if segment_order[left_root] <= segment_order[right_root]:
                parents[right_root] = left_root
                members[left_root].update(members.pop(right_root))
            else:
                parents[left_root] = right_root
                members[right_root].update(members.pop(left_root))

    decisions: list[TopicRecurrenceDecision] = []
    for index, (semantic_vote, llm_vote) in enumerate(
        zip(semantic_votes, llm_votes), start=1
    ):
        llm_skipped = (
            llm_vote.same_topic is None and llm_vote.reason in _LLM_SKIP_REASONS
        )
        consensus = semantic_vote.same_topic is True and llm_vote.same_topic is True
        semantic_high = (
            semantic_vote.score is not None
            and semantic_vote.score >= config.semantic_high_confidence
            and llm_vote.same_topic is None
        )
        same_topic = consensus or (
            config.join_policy == "consensus_or_semantic_high" and semantic_high
        )
        reasons: list[str] = []
        if consensus:
            reasons.append("semantic_llm_consensus")
        elif semantic_high and same_topic:
            reasons.append("semantic_high_llm_abstained")
        elif llm_vote.same_topic is None and not llm_skipped:
            # A GENUINE model abstention, distinct from a pair the LLM
            # branch never even called (llm_skipped) -- see relation="
            # abstained" below (TIP-009).
            reasons.append("llm_abstained")
        elif semantic_vote.same_topic != llm_vote.same_topic:
            reasons.append("branch_disagreement")

        if config.must_not_link_requires_explicit_judgment:
            # Fixed relation taxonomy (plan_stage_7_8.md §3.1,
            # TASK-GRAPH-stage7-8.md D-108): a pair the LLM branch SKIPPED
            # (below threshold / high-confidence skip / no adapter) must
            # never become "distinct" -- absence of evidence is not evidence
            # of absence, and only "distinct" feeds must_not_link below. A
            # genuine LLM abstention is likewise excluded from
            # must_not_link, under its own "abstained" relation.
            if same_topic:
                relation = "recurrence"
            elif llm_skipped and semantic_vote.same_topic is False:
                relation = "not_assessed"
                reasons.append("pair_not_evaluated")
            elif semantic_vote.same_topic is True or llm_vote.same_topic is True:
                relation = "related_candidate"
            elif llm_vote.same_topic is False:
                relation = "distinct"
            else:
                relation = "abstained"
        else:
            # Pre-fix behaviour, kept ONLY for the ablation table comparing
            # must_not_link_requires_explicit_judgment on/off -- see
            # plan_stage_7_8.md §8. A skipped OR genuinely-abstained pair is
            # silently treated as "distinct" here, which is the exact bug
            # TIP-009 fixes. Do not "clean this up" -- it is load-bearing
            # for the thesis ablation.
            relation = (
                "recurrence"
                if same_topic
                else (
                    "related_candidate"
                    if semantic_vote.same_topic is True or llm_vote.same_topic is True
                    else "distinct"
                )
            )
        decision = TopicRecurrenceDecision(
            decision_id=f"TOPIC_REC_{index:06d}",
            source_segment_id=semantic_vote.source_segment_id,
            target_segment_id=semantic_vote.target_segment_id,
            semantic_vote=semantic_vote,
            llm_vote=llm_vote,
            same_topic=same_topic,
            relation=relation,
            reason_codes=tuple(reasons),
        )
        decisions.append(decision)

    # Treat direct "distinct" outcomes as must-not-link constraints before any
    # transitive union. This prevents A~C and C~E from silently overriding an
    # explicit A!=E judgment.
    must_not_link = {
        frozenset((decision.source_segment_id, decision.target_segment_id))
        for decision in decisions
        if decision.relation == "distinct"
    }
    for index, decision in enumerate(decisions):
        if not decision.same_topic:
            continue
        left_root = find(decision.source_segment_id)
        right_root = find(decision.target_segment_id)
        has_conflict = any(
            frozenset((left_member, right_member)) in must_not_link
            for left_member in members[left_root]
            for right_member in members[right_root]
        )
        if has_conflict:
            decisions[index] = replace(
                decision,
                same_topic=False,
                relation="review_conflict",
                reason_codes=decision.reason_codes
                + ("transitive_distinct_conflict",),
            )
            continue
        union(decision.source_segment_id, decision.target_segment_id)

    root_to_topic: dict[str, str] = {}
    memberships: list[tuple[str, str]] = []
    for segment in segments:
        root = find(segment.segment_id)
        topic_id = root_to_topic.setdefault(root, f"TOPIC_{len(root_to_topic) + 1:06d}")
        memberships.append((segment.segment_id, topic_id))
    not_assessed_pair_count = sum(
        1 for decision in decisions if decision.relation == "not_assessed"
    )
    return TopicMap(
        memberships=tuple(memberships),
        decisions=tuple(decisions),
        candidate_pair_count=candidate_pair_count,
        evaluated_pair_count=len(pairs),
        truncated=len(pairs) < candidate_pair_count,
        gray_zone_pair_count=gray_zone_pair_count,
        not_assessed_pair_count=not_assessed_pair_count,
    )


__all__ = [
    "StructuredLLMTopicRecurrenceChecker",
    "resolve_topic_recurrence",
]
