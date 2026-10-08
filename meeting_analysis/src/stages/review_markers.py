"""Runtime-quality projections that belong to no single stage.

These summarise what the run could not do -- evidence that failed integrity
checks, and stages that fell back, abstained or ran checker-only because an
adapter was absent. They are audit output, never evidence, and are capped at
one marker per stage so a systematic gap cannot flood the artifact.
"""

from __future__ import annotations

import hashlib

from ..utils.contracts import EvidenceItem, Metadata, ReviewMarker



def evidence_integrity_review_markers(
    meeting_id: str,
    evidence: tuple[EvidenceItem, ...],
) -> tuple[ReviewMarker, ...]:
    """Flag edge whitespace without rewriting evidence text (Stage 2).

    Speaker-turn offsets depend on exact source lengths, so silently stripping
    these characters would break exact-span reconstruction.  The marker makes
    unusual input auditable while preserving the immutable source slice.
    """

    markers: list[ReviewMarker] = []
    for item in evidence:
        exact = item.text_exact if item.text_exact is not None else item.text
        leading = bool(exact[:1].isspace())
        trailing = bool(exact[-1:].isspace())
        if not leading and not trailing:
            continue
        digest = hashlib.sha256(
            f"{meeting_id}\0{item.evidence_id}\0edge_whitespace".encode("utf-8")
        ).hexdigest()[:16]
        markers.append(
            ReviewMarker(
                marker_id=f"REVIEW_EVIDENCE_WS_{digest}",
                stage="2",
                artifact_id=item.evidence_id,
                code="evidence_edge_whitespace",
                message=(
                    "Evidence text has leading/trailing whitespace; exact text "
                    "was preserved and should be reviewed at the source."
                ),
                evidence_ids=(item.evidence_id,),
                details=(("leading", leading), ("trailing", trailing)),
            )
        )
    return tuple(markers)


def model_stage_review_markers(
    meeting_id: str,
    *,
    topic_strategy: str,
    has_topic_similarity_adapter: bool,
    has_topic_label_adapter: bool,
    has_recurrence_semantic_adapter: bool,
    has_recurrence_llm_adapter: bool,
    has_event_guard_reviewer: bool,
) -> tuple[ReviewMarker, ...]:
    """Emit at most one concise audit marker for each degraded model stage."""

    markers: list[ReviewMarker] = []
    meeting_token = hashlib.sha256(meeting_id.encode("utf-8")).hexdigest()[:8]

    def add(stage: str, code: str, message: str, details: Metadata = ()) -> None:
        markers.append(
            ReviewMarker(
                marker_id=f"REVIEW_RUNTIME_{meeting_token}_{stage.upper()}",
                stage=stage,
                artifact_id=meeting_id,
                code=code,
                message=message,
                severity="info",
                details=details,
            )
        )

    if topic_strategy in {"paper_simple_cosine", "paper_complex_cosine"} and not (
        has_topic_similarity_adapter
    ):
        add(
            "topic_segmentation",
            "lexical_similarity_fallback",
            "Topic segmentation used lexical cosine because no model adapter was supplied.",
        )
    if not has_topic_label_adapter:
        add(
            "topic_labeling",
            "extractive_fallback",
            "Topic labels used the extractive offline fallback; no LLM labeler ran.",
        )
    if not has_recurrence_semantic_adapter or not has_recurrence_llm_adapter:
        semantic_mode = (
            "model" if has_recurrence_semantic_adapter else "lexical_fallback"
        )
        llm_mode = "model" if has_recurrence_llm_adapter else "abstained"
        if not has_recurrence_semantic_adapter and not has_recurrence_llm_adapter:
            recurrence_code = "semantic_fallback_llm_abstained"
        elif not has_recurrence_semantic_adapter:
            recurrence_code = "semantic_fallback"
        else:
            recurrence_code = "llm_abstained"
        add(
            "topic_recurrence",
            recurrence_code,
            "Topic recurrence ran with at least one unavailable model branch.",
            details=(("semantic_branch", semantic_mode), ("llm_branch", llm_mode)),
        )
    if not has_event_guard_reviewer:
        add(
            "event_guard",
            "checker_only",
            "Event guard used the deterministic checker without an LLM reviewer.",
        )
    return tuple(markers)



__all__ = [
    "evidence_integrity_review_markers",
    "model_stage_review_markers",
]
