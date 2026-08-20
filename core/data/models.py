from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum


def _parse_date(value: str | date | None) -> date | None:
    """Best-effort ISO date parsing; OCR/ASR sources are noisy so a bad
    or missing value degrades to None instead of raising."""
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class _ModelJSONEncoder(json.JSONEncoder):
    """Serializes the date/Enum types used across these dataclasses."""

    def default(self, o):
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, Enum):
            return o.value
        return super().default(o)


def dump_json(record: MeetingRecord | MinuteDoc, *, indent: int = 2) -> str:
    """Serialize a MeetingRecord or MinuteDoc (and nested dataclasses) to
    a JSON string, keeping Vietnamese text unescaped."""
    return json.dumps(asdict(record), ensure_ascii=False, indent=indent, cls=_ModelJSONEncoder)


class EntitySource(str, Enum):
    """Where an entity mention was first observed."""
    TRANSCRIPT = "transcript"
    DOC = "doc"


class Deontic(str, Enum):
    """Modality of an assignment, as spoken/written in the meeting.

    Values are the literal Vietnamese terms used in source transcripts
    and minute documents, so they round-trip untouched through OCR/NLP.
    """
    AGREED = "thống_nhất"       # thống nhất
    ASSIGNED = "giao"           # giao
    PROPOSED = "đề_nghị"        # đề nghị
    NOTED = "lưu_ý"             # lưu ý
    TO_RESEARCH = "nghiên_cứu"  # nghiên cứu


# ---------------------------------------------------------------------------
# MeetingRecord: raw/aligned evidence from a meeting (transcript + source docs)
# ---------------------------------------------------------------------------

@dataclass
class MeetingInfo:
    type: str
    date: date | None
    chair: str
    participants: list[str]
    session_number: str

    @classmethod
    def from_json(cls, json_data: dict) -> MeetingInfo:
        return cls(
            type=json_data.get("type", ""),
            date=_parse_date(json_data.get("date")),
            chair=json_data.get("chair", ""),
            participants=json_data.get("participants", []),
            session_number=json_data.get("session_number", ""),
        )


@dataclass
class Turn:
    id: str
    speaker_raw: str
    role_inferred: str
    text: str
    t_start: float

    @classmethod
    def from_json(cls, json_data: dict) -> Turn:
        return cls(
            id=json_data.get("id", ""),
            speaker_raw=json_data.get("speaker_raw", ""),
            role_inferred=json_data.get("role_inferred", ""),
            text=json_data.get("text", ""),
            t_start=float(json_data.get("t_start", 0.0)),
        )


@dataclass
class SourceDocument:
    doc_id: str
    doc_number: str
    date: date | None
    type: str
    ocr_text: str
    ocr_confidence: float

    @classmethod
    def from_json(cls, json_data: dict) -> SourceDocument:
        return cls(
            doc_id=json_data.get("doc_id", ""),
            doc_number=json_data.get("doc_number", ""),
            date=_parse_date(json_data.get("date")),
            type=json_data.get("type", ""),
            ocr_text=json_data.get("ocr_text", ""),
            ocr_confidence=float(json_data.get("ocr_confidence", 0.0)),
        )


@dataclass
class Entity:
    surface_forms: list[str]
    canonical: str
    source: EntitySource

    @classmethod
    def from_json(cls, json_data: dict) -> Entity:
        return cls(
            surface_forms=json_data.get("surface_forms", []),
            canonical=json_data.get("canonical", ""),
            source=EntitySource(json_data.get("source", EntitySource.TRANSCRIPT.value)),
        )


@dataclass
class MeetingRecord:
    meeting: MeetingInfo
    turns: list[Turn] = field(default_factory=list)
    docs: list[SourceDocument] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)

    @classmethod
    def from_json(cls, json_data: dict) -> MeetingRecord:
        return cls(
            meeting=MeetingInfo.from_json(json_data.get("meeting", {})),
            turns=[Turn.from_json(t) for t in json_data.get("turns", [])],
            docs=[SourceDocument.from_json(d) for d in json_data.get("docs", [])],
            entities=[Entity.from_json(e) for e in json_data.get("entities", [])],
        )


# ---------------------------------------------------------------------------
# MinuteDoc: the structured output — official meeting minutes
# ---------------------------------------------------------------------------

@dataclass
class DocHeader:
    agency: str
    doc_number: str
    location: str
    date: date | None

    @classmethod
    def from_json(cls, json_data: dict) -> DocHeader:
        return cls(
            agency=json_data.get("agency", ""),
            doc_number=json_data.get("doc_number", ""),
            location=json_data.get("location", ""),
            date=_parse_date(json_data.get("date")),
        )


@dataclass
class Attendees:
    chair: str
    participants: list[str]

    @classmethod
    def from_json(cls, json_data: dict) -> Attendees:
        return cls(
            chair=json_data.get("chair", ""),
            participants=json_data.get("participants", []),
        )


@dataclass
class Assignment:
    lead_unit: str
    coordinating_units: list[str]
    task: str
    deontic: Deontic
    deadline: str
    deliverable: str
    evidence: list[str]

    @classmethod
    def from_json(cls, json_data: dict) -> Assignment:
        return cls(
            lead_unit=json_data.get("lead_unit", ""),
            coordinating_units=json_data.get("coordinating_units", []),
            task=json_data.get("task", ""),
            deontic=Deontic(json_data["deontic"]),
            deadline=json_data.get("deadline", ""),
            deliverable=json_data.get("deliverable", ""),
            evidence=json_data.get("evidence", []),
        )


@dataclass
class Section:
    topic: str
    conclusion: str
    assignments: list[Assignment] = field(default_factory=list)

    @classmethod
    def from_json(cls, json_data: dict) -> Section:
        return cls(
            topic=json_data.get("topic", ""),
            conclusion=json_data.get("conclusion", ""),
            assignments=[Assignment.from_json(a) for a in json_data.get("assignments", [])],
        )


@dataclass
class DocFooter:
    recipients: list[str]
    signatory: str

    @classmethod
    def from_json(cls, json_data: dict) -> DocFooter:
        return cls(
            recipients=json_data.get("recipients", []),
            signatory=json_data.get("signatory", ""),
        )


@dataclass
class MinuteDoc:
    header: DocHeader
    attendees: Attendees
    sections: list[Section] = field(default_factory=list)
    footer: DocFooter | None = None

    @classmethod
    def from_json(cls, json_data: dict) -> MinuteDoc:
        return cls(
            header=DocHeader.from_json(json_data.get("header", {})),
            attendees=Attendees.from_json(json_data.get("attendees", {})),
            sections=[Section.from_json(s) for s in json_data.get("sections", [])],
            footer=DocFooter.from_json(json_data["footer"]) if json_data.get("footer") else None,
        )
