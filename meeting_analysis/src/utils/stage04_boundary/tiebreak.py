"""Stage 4b (optional) -- LLM tie-break between near-equal candidates.

Opt-in and budgeted. The adapter only ever picks between candidate offsets
4a already produced; it cannot introduce an offset of its own. Every
decision, including a fallback when the budget runs out or the adapter
declines, is recorded as an ``LLMTiebreakDecision`` and carried on the atom
for audit -- a tie-break is never evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..ports import LLMBoundaryTiebreakAdapter
from .scoring import (
    _CONTEXT_CHARS,
    _TIEBREAK_DELTA,
    _TIEBREAK_TAU,
    ScoredCandidate,
)


class LLMTiebreakBudget:
    """Hard per-meeting cap on LLM boundary calls (D6): shared across every
    turn in one ``build_analysis_atoms`` call, never reset per-turn."""

    __slots__ = ("remaining",)

    def __init__(self, limit: int) -> None:
        self.remaining = max(0, limit)

    def consume(self, requested: int) -> int:
        used = max(0, min(requested, self.remaining))
        self.remaining -= used
        return used


@dataclass(frozen=True, slots=True)
class LLMTiebreakDecision:
    """Audit record for one ambiguous boundary considered by T11.

    One adapter invocation is batched per turn, but budget is charged per
    boundary decision so ``max_llm_boundary_calls`` remains a hard per-meeting
    ceiling independent of turn chunking. Candidates beyond that ceiling are
    recorded with ``reason_code="budget_exhausted"`` and retain their base
    score instead of silently disappearing from the audit trail.
    """

    pos: int
    source: str
    base_score: float
    verdict: str
    final_score: float
    reason_code: str

    @property
    def used(self) -> bool:
        return self.verdict in {"MERGE", "SPLIT"}


def apply_llm_tiebreak(
    text: str,
    scored: tuple[ScoredCandidate, ...],
    *,
    adapter: LLMBoundaryTiebreakAdapter,
    budget: LLMTiebreakBudget,
) -> tuple[tuple[ScoredCandidate, ...], tuple[LLMTiebreakDecision, ...]]:
    """Send only the ambiguous-band candidates of ONE turn to the LLM,
    batched in a single call (D6). ``ABSTAIN`` or an exhausted budget leaves
    the rule/model score untouched -- this never blocks packing.
    """

    n = len(text)
    ambiguous = [
        index
        for index, candidate in enumerate(scored)
        if 0 < candidate.pos < n
        and _TIEBREAK_TAU - _TIEBREAK_DELTA
        <= candidate.split_score
        <= _TIEBREAK_TAU + _TIEBREAK_DELTA
    ]
    if not ambiguous:
        return scored, ()

    usable = budget.consume(len(ambiguous))
    called = ambiguous[:usable]

    pairs = tuple(
        (
            text[max(0, scored[index].pos - _CONTEXT_CHARS): scored[index].pos],
            text[scored[index].pos: scored[index].pos + _CONTEXT_CHARS],
            scored[index].source,
        )
        for index in called
    )
    verdicts: tuple[str, ...] = ()
    if pairs:
        verdicts = adapter.judge_boundaries(pairs)
        if not isinstance(verdicts, tuple) or len(verdicts) != len(pairs):
            raise ValueError(
                "LLMBoundaryTiebreakAdapter.judge_boundaries() must return exactly "
                "one verdict per pair"
            )

    updated = list(scored)
    decisions: list[LLMTiebreakDecision] = []
    for index, verdict in zip(called, verdicts):
        base = updated[index]
        if verdict == "SPLIT":
            updated[index] = replace(updated[index], split_score=1.0)
            reason_code = "llm_split"
        elif verdict == "MERGE":
            updated[index] = replace(updated[index], split_score=0.0)
            reason_code = "llm_merge"
        elif verdict == "ABSTAIN":
            reason_code = "llm_abstain_rule_fallback"
        else:
            raise ValueError(f"invalid LLM tie-break verdict: {verdict!r}")
        decisions.append(
            LLMTiebreakDecision(
                pos=base.pos,
                source=base.source,
                base_score=base.split_score,
                verdict=verdict,
                final_score=updated[index].split_score,
                reason_code=reason_code,
            )
        )

    for index in ambiguous[usable:]:
        candidate = updated[index]
        decisions.append(
            LLMTiebreakDecision(
                pos=candidate.pos,
                source=candidate.source,
                base_score=candidate.split_score,
                verdict="ABSTAIN",
                final_score=candidate.split_score,
                reason_code="budget_exhausted",
            )
        )
    decisions.sort(key=lambda decision: decision.pos)
    return tuple(updated), tuple(decisions)
