"""Stage 4 internals: CandidateGenerator (4a) -> BoundaryScorer (4b) ->
ConstrainedPacker (4c).

These are layers INSIDE module 4, not catalog stages of their own:
``catalog.py`` still lists exactly one artifact producer for module 4,
``build_analysis_atoms`` in ``stage04_analysis_atoms.py``. This package has
no public artifact and is imported only by that module.

Flow: ``text -> 4a candidates -> 4b split_score -> 4c packed spans``.
4b only ever returns a *number* per candidate; 4c only ever *chooses among
existing candidate offsets*. See docs/stage4-5-plan.md section 1.
"""

from .candidates import Candidate, generate_candidates
from .packing import PackedAtom, pack_atoms
from .scoring import (
    HybridCoherenceScorer,
    ScoredCandidate,
    SemanticCoherenceScorer,
    candidate_windows,
    score_candidates,
)
from .tiebreak import LLMTiebreakBudget, LLMTiebreakDecision, apply_llm_tiebreak

__all__ = [
    "Candidate",
    "LLMTiebreakBudget",
    "LLMTiebreakDecision",
    "HybridCoherenceScorer",
    "PackedAtom",
    "ScoredCandidate",
    "SemanticCoherenceScorer",
    "apply_llm_tiebreak",
    "candidate_windows",
    "generate_candidates",
    "pack_atoms",
    "score_candidates",
]
