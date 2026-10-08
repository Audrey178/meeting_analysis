"""Stage 4: cut speaker turns into evidence-preserving analysis atoms.

The only public contract producer for module 4. Internally it is three
layers -- CandidateGenerator (4a) -> BoundaryScorer (4b) -> ConstrainedPacker
(4c), in ``stage04_boundary`` -- but that split is an implementation detail,
not three catalog stages. See docs/stage4-5-plan.md section 1.

Atoms are packed from exact transcript spans under a hard minimum length and
a soft-target maximum (``AtomBuilderConfig.soft_cap_chars``): the packer will
exceed the target rather than force a cut through a word/phrase when no real
boundary candidate makes a shorter split possible (flagged via
``AnalysisAtom.packing_method``). A model may contribute boundary candidates
and break ties; it may never
generate text or choose a final span, and every tie-break it decides is
recorded in ``AnalysisAtom.boundary_tiebreak_decisions`` for audit rather
than becoming evidence.
"""

from __future__ import annotations
import logging

from ..utils.config import AtomBuilderConfig
from ..utils.contracts import (
    AnalysisAtom,
    BoundaryTiebreakDecision,
    EvidenceItem,
    SpeakerTurn,
)
from ..utils.ports import ClauseBoundaryAdapter, LLMBoundaryTiebreakAdapter
from ._shared import known_max, known_min
from ..utils.stage04_boundary import (
    LLMTiebreakBudget,
    HybridCoherenceScorer,
    SemanticCoherenceScorer,
    apply_llm_tiebreak,
    candidate_windows,
    generate_candidates,
    pack_atoms,
    score_candidates,
)
from .stage03_speaker_turns import TURN_ITEM_SEPARATOR as _TURN_ITEM_SEPARATOR



def _overlapping_evidence_ids(
    turn_evidence_ids: tuple[str, ...],
    item_spans: list[tuple[int, int]],
    start: int,
    end: int,
) -> tuple[str, ...]:
    """Every source EvidenceItem whose character span (in ``turn.text_exact``,
    as recomputed by ``build_analysis_atoms``) overlaps the packed atom span
    ``[start, end)`` -- more than one entry means the packer crossed an ASR
    chunk boundary to reach ``min_chars``. Pure and side-effect free so it is
    testable without the semantic coherence model ``build_analysis_atoms``
    otherwise loads on every call."""

    return tuple(
        turn_evidence_ids[index]
        for index, (span_start, span_end) in enumerate(item_spans)
        if span_start < end and start < span_end
    )


def build_analysis_atoms(
    turns: tuple[SpeakerTurn, ...],
    evidence: tuple[EvidenceItem, ...],
    config: AtomBuilderConfig,
    *,
    clause_adapter: ClauseBoundaryAdapter | None = None,
    llm_tiebreak_adapter: LLMBoundaryTiebreakAdapter | None = None,
) -> tuple[AnalysisAtom, ...]:
    """Build one exact, evidence-backed atom per turn slice.

    ``candidate_sources`` requesting ``"model"`` with no ``clause_adapter``
    injected is not an error (D10): that source is silently dropped.  The
    pipeline-level caller records requested/adapter/candidate/selection state
    in ``PipelineResult.metadata``; direct callers can still infer selected
    model boundaries from ``AnalysisAtom.boundary_source``.

    ``evidence`` is needed to recompute each turn's per-item character spans
    for the ``"item_boundary"`` candidate source -- real ASR pause points,
    reconstructed the same way ``stage03_speaker_turns.py`` built
    ``turn.text_exact`` in the first place (join by ``TURN_ITEM_SEPARATOR``),
    so the two can never drift apart.
    """

    atoms: list[AnalysisAtom] = []
    previous_end_ms: int | None = None
    previous_evidence_ids: frozenset[str] = frozenset()

    evidence_by_id = {item.evidence_id: item for item in evidence}

    sources = frozenset(config.candidate_sources)
    if clause_adapter is None:
        sources = sources - {"model"}
    # NOTE (bug fix, see run_to_stage4.py Completion Report): this call site
    # previously did HybridCoherenceScorer() with no arguments, but that
    # class requires a `semantic` scorer. Per decision (real semantic model,
    # not a lexical fallback), wire in the actual VoVanPhuc SimCSE PhoBERT
    # scorer -- first call in a fresh environment downloads that model from
    # HuggingFace.
    logging.info("Initializing HybridCoherenceScorer with SemanticCoherenceScorer()")
    coherence_scorer = HybridCoherenceScorer(SemanticCoherenceScorer())
    logging.info("HybridCoherenceScorer initialized successfully")
    llm_budget = (
        LLMTiebreakBudget(config.max_llm_boundary_calls)
        if config.llm_tiebreak and llm_tiebreak_adapter is not None
        else None
    )
    
    logging.info("Starting build_analysis_atoms with %d turns", len(turns))

    # 4a for every turn up front, then warm the coherence scorer's embedding
    # cache with ALL turns' candidate windows in one batched encode() call
    # (SemanticCoherenceScorer.warm_cache) before scoring any of them.
    # Warming per-turn instead (i.e. leaving this to score_candidates' own
    # warm_cache call below) still works but batches far fewer texts per
    # encode() call on short turns, which on CPU costs more in per-call
    # model overhead than it saves -- pooling across the whole session
    # keeps batches large regardless of individual turn length.
    item_spans_by_turn: dict[str, list[tuple[int, int]]] = {}
    candidates_by_turn: dict[str, tuple] = {}
    all_windows: list[str] = []
    for turn in turns:
        # Recompute each source EvidenceItem's exact character span inside
        # turn.text_exact -- mirrors stage03_speaker_turns.py's own join
        # (TURN_ITEM_SEPARATOR.join(item.text_exact or item.text ...)) so the
        # spans can never drift from what's actually in the joined text.
        item_spans: list[tuple[int, int]] = []
        offset = 0
        for evidence_id in turn.evidence_ids:
            item = evidence_by_id[evidence_id]
            item_text = item.text_exact if item.text_exact is not None else item.text
            span_start = offset
            span_end = offset + len(item_text)
            item_spans.append((span_start, span_end))
            offset = span_end + len(_TURN_ITEM_SEPARATOR)

        candidates = generate_candidates(
            turn,
            sources=sources,
            clause_adapter=clause_adapter,
            item_spans=tuple(item_spans),
            item_boundary_prior=config.item_boundary_prior,
        )
        item_spans_by_turn[turn.turn_id] = item_spans
        candidates_by_turn[turn.turn_id] = candidates
        all_windows.extend(candidate_windows(turn.text_exact, candidates))

    logging.info("Warming coherence scorer cache with %d candidate windows", len(all_windows))
    coherence_scorer.warm_cache(all_windows)

    for turn in turns:
        item_spans = item_spans_by_turn[turn.turn_id]
        candidates = candidates_by_turn[turn.turn_id]

        # 4b: score candidates with lexical coherence and optional model tie-breaks
        # (warm_cache above already populated the embedding cache for every
        # window used here, so this call's own warm_cache is a no-op lookup)
        scored = score_candidates(
            turn.text_exact, candidates, coherence_scorer=coherence_scorer
        )

        llm_decisions = ()
        if llm_budget is not None and llm_tiebreak_adapter is not None:
            scored, llm_decisions = apply_llm_tiebreak(
                turn.text_exact,
                scored,
                adapter=llm_tiebreak_adapter,
                budget=llm_budget,
            )
        packed = pack_atoms(
            turn.text_exact,
            scored,
            min_chars=config.min_chars,
            target_chars=config.target_chars,
            soft_cap_chars=config.soft_cap_chars,
        )

        for piece in packed:
            start, end = piece.start, piece.end
            piece_tiebreak_decisions = tuple(
                BoundaryTiebreakDecision(
                    position=decision.pos,
                    candidate_source=decision.source,
                    base_score=decision.base_score,
                    verdict=decision.verdict,
                    final_score=decision.final_score,
                    reason_code=decision.reason_code,
                )
                for decision in llm_decisions
                if start <= decision.pos < piece.partition_end
            )
            text_exact = turn.text_exact[start:end]
            piece_evidence_ids = _overlapping_evidence_ids(
                turn.evidence_ids, item_spans, start, end
            )

            segmentation_method = (
                "model_clause"
                if "model" in piece.boundary_source.split("+")
                else "rule_clause_v1"
            )
            atoms.append(
                AnalysisAtom(
                    atom_id=f"{turn.turn_id}@{start:06d}",
                    turn_id=turn.turn_id,
                    text_exact=text_exact,
                    start_ms=turn.start_ms,
                    end_ms=turn.end_ms,
                    speaker=turn.speaker,
                    speaker_role=turn.speaker_role,
                    speaker_track=turn.speaker_track,
                    segmentation_method=segmentation_method,
                    boundary_confidence=piece.boundary_confidence,
                    boundary_source=piece.boundary_source,
                    packing_method=piece.packing_method,
                    llm_tiebreak_used=any(
                        decision.verdict in {"MERGE", "SPLIT"}
                        for decision in piece_tiebreak_decisions
                    ),
                    boundary_tiebreak_decisions=piece_tiebreak_decisions,
                    evidence_ids=piece_evidence_ids,
                )
            )

    return tuple(atoms)


__all__ = ["build_analysis_atoms"]
