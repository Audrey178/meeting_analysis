"""Immutable data contracts shared by the meeting-analysis pipeline.

Times are represented as integer milliseconds.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias


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
    # (item_id, nguyên văn) của từng dòng transcript thô trong lượt, theo thứ tự: agent trích
    # dẫn theo item_id (``segment_ids`` ở API), turn_id được suy ra từ item.
    source_items: tuple[tuple[str, str], ...] = ()


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


__all__ = [
    "EffectiveTranscriptItem",
    "FieldProvenance",
    "Provenance",
    "RawTranscriptItem",
    "Scalar",
    "SpeakerTurn",
    "TopicLabel",
    "TopicSegment",
]
