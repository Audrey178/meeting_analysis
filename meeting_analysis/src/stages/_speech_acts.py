"""Speech-act cues shared by stage 11 and stage 12.

Stage 11 classifies an atom with these cues; stage 12's deterministic
checker re-applies the same tables to decide whether the extracted kind
still holds. They live here so the two can never drift apart -- a guard
judging by different cues than the extractor used would reject correct
events and pass wrong ones.
"""

from __future__ import annotations

import re
import unicodedata

from ..utils.contracts import EventKind

SPACE_RE = re.compile(r"\s+")


_NUMBER_RE = re.compile(r"\d+(?:[.,/:-]\d+)*")
_PROPOSAL_CUES = ("đề nghị", "kiến nghị", "đề xuất")
_COMMITMENT_CUES = ("cam kết",)
_NON_PERFORMATIVE_CUE_CONTEXTS = (
    (
        EventKind.DECISION,
        re.compile(r"\bkết\s+luận\s+thanh\s+tra\b", re.IGNORECASE),
    ),
    (
        EventKind.DECISION,
        re.compile(r"\bkết\s+luận\s+của\b", re.IGNORECASE),
    ),
    (
        EventKind.PROPOSAL,
        re.compile(
            r"\bkiến\s+nghị(?:\s+của)?\s+cử\s+tri\b",
            re.IGNORECASE,
        ),
    ),
    (
        EventKind.DECISION,
        re.compile(r"\bmang\s+tính\s+quyết\s+định\b", re.IGNORECASE),
    ),
    (
        EventKind.DECISION,
        re.compile(r"\bnghị\s+quyết\s+định\s+hướng\b", re.IGNORECASE),
    ),
    (
        EventKind.PROPOSAL,
        re.compile(
            r"\btham\s+mưu(?:\s*,\s*|\s+)đề\s+xuất\b",
            re.IGNORECASE,
        ),
    ),
)
_NEGATED_STRONG_RE = re.compile(
    r"\b(?:không|chưa)(?:\s+\w+){0,3}\s+"
    r"(?:quyết định|thống nhất|kết luận|chốt|giao|yêu cầu|phân công)\b",
    re.IGNORECASE,
)


def _normalized(text: str) -> str:
    return SPACE_RE.sub(" ", unicodedata.normalize("NFC", text)).strip().lower()


def _contains_any(text: str, cues: tuple[str, ...]) -> bool:
    return any(cue in text for cue in cues)


def _literal_actor_mention(actor: str, text: str) -> bool:
    """Match a complete normalized actor mention, not a substring like ``A``."""

    normalized_actor = _normalized(actor)
    normalized_text = _normalized(text)
    if not normalized_actor or not normalized_text:
        return False
    return re.search(
        rf"(?<!\w){re.escape(normalized_actor)}(?!\w)", normalized_text
    ) is not None


def _without_non_performative_cue_contexts(text: str) -> str:
    """Mask cue-shaped noun phrases before dialogue-act classification.

    The phrases remain untouched in evidence and propositions.  Only the
    classifier view is masked, so a real performative elsewhere in the same
    sentence can still support an event.
    """

    classified_text = _normalized(text)
    for _, pattern in _NON_PERFORMATIVE_CUE_CONTEXTS:
        classified_text = pattern.sub(" ", classified_text)
    return SPACE_RE.sub(" ", classified_text).strip()


def _non_performative_cue_kinds(text: str) -> frozenset[EventKind]:
    normalized = _normalized(text)
    return frozenset(
        kind
        for kind, pattern in _NON_PERFORMATIVE_CUE_CONTEXTS
        if pattern.search(normalized)
    )


def _classify(text: str) -> EventKind | None:
    lowered = _without_non_performative_cue_contexts(text)
    # Modality-sensitive cues take precedence over stronger-looking verbs that
    # may occur later in the same proposal sentence.
    if _contains_any(lowered, _PROPOSAL_CUES):
        return EventKind.PROPOSAL
    if _NEGATED_STRONG_RE.search(lowered):
        return EventKind.CLARIFICATION
    if "phản đối" in lowered or "không đồng ý" in lowered:
        return EventKind.OBJECTION
    if "?" in text or _contains_any(lowered, ("xin hỏi", "cho hỏi", "khi nào")):
        return EventKind.QUESTION
    if _contains_any(lowered, ("giao ", "yêu cầu", "phân công")):
        return EventKind.ASSIGNMENT
    if _contains_any(lowered, ("thống nhất", "kết luận", "quyết định", "chốt ")):
        return EventKind.DECISION
    if _contains_any(lowered, _COMMITMENT_CUES):
        return EventKind.COMMITMENT
    if _contains_any(lowered, ("trả lời", "xin trả lời")):
        return EventKind.ANSWER
    if _contains_any(lowered, ("báo cáo", "tờ trình", "theo kế hoạch", "xin trình")):
        return EventKind.REPORT
    return None



def _literal_mention(value: str, text: str) -> bool:
    normalized_value = _normalized(value)
    normalized_text = _normalized(text)
    if not normalized_value or not normalized_text:
        return False
    return re.search(
        rf"(?<!\w){re.escape(normalized_value)}(?!\w)", normalized_text
    ) is not None


def _modality(kind: EventKind) -> str:
    return {
        EventKind.PROPOSAL: "proposal",
        EventKind.QUESTION: "interrogative",
        EventKind.DECISION: "assertive",
        EventKind.ASSIGNMENT: "directive",
        EventKind.COMMITMENT: "commitment",
    }.get(kind, "reported")


__all__ = [
    "SPACE_RE",
    "_NUMBER_RE",
    "_classify",
    "_contains_any",
    "_literal_actor_mention",
    "_literal_mention",
    "_modality",
    "_non_performative_cue_kinds",
    "_PROPOSAL_CUES",
    "_normalized",
    "_without_non_performative_cue_contexts",
]
