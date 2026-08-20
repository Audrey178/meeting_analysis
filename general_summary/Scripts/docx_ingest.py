"""
docx_ingest.py

Reads a diarized meeting transcript stored as a .docx file (one paragraph per
turn, formatted as "Speaker: text") and converts it into the same
{meeting, turns, docs, entities} JSON structure already used by the rest of
the pipeline (see Vietnamese_datasets/processed/*.meetingrecord.json).

It also infers a coarse speaker role (CHAIR vs PRESENTER) so that downstream
prompts can tell "the presiding leader's conclusions" apart from
"the presenter/consultant's report", without changing the atomic-facts /
feature-generator JSON schemas: the role is baked directly into the labeled
transcript text (see build_labeled_transcript_text), not into a new field
threaded through every downstream module.
"""

import re
import logging
from typing import Dict, List, Optional

from docx import Document

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# A speaker label that carries a parenthesized title/affiliation
# (e.g. "Phạm Hồng Sơn (Thành uỷ HCMC)") is treated as the chair / the person
# giving instructions and conclusions. Everyone else is a presenter/consultant.
_TITLE_PATTERN = re.compile(r'\(.+\)')

CHAIR = "CHAIR"
PRESENTER = "PRESENTER"


def _infer_role(speaker_raw: str) -> str:
    """Infer CHAIR vs PRESENTER from the raw speaker label."""
    return CHAIR if _TITLE_PATTERN.search(speaker_raw or "") else PRESENTER


def _normalize_text(raw: str) -> str:
    """
    Collapse any soft line breaks (Shift+Enter, rendered by python-docx as a
    literal '\\n' *within* paragraph.text) into a single space.

    Downstream chunking (ChunkProcessor.chunk_transcript) assumes one line
    of the labeled transcript == one whole turn. If a turn's `text` still
    carried an internal '\\n' from a mid-paragraph soft break, that single
    turn would silently split into multiple "lines" — e.g. a turn ending in
    "...không?" followed by its own soft-broken "?" would leak out as an
    orphan one-character chunk. Collapsing every run of whitespace that
    contains a newline into a single space guarantees a turn's text is
    always exactly one line, however many soft breaks the original .docx
    paragraph had.
    """
    return re.sub(r'\s*\n\s*', ' ', raw).strip()


def parse_transcript_docx(docx_path: str) -> Dict:
    """
    Parse a diarized transcript .docx into {meeting, turns, docs, entities}.

    Each non-empty paragraph is expected to look like "Speaker:\\ncontent"
    (a colon separates the speaker label from the spoken text, the two are
    typically split by a soft line break within the same paragraph). A
    paragraph without a ':' is treated as a continuation of the previous
    turn's text (e.g. a wrapped line) rather than a new turn.
    """
    document = Document(docx_path)

    turns: List[Dict] = []
    for paragraph in document.paragraphs:
        raw_text = paragraph.text
        if not raw_text or not raw_text.strip():
            continue

        if ':' in raw_text:
            speaker_raw, text = raw_text.split(':', 1)
            speaker_raw = speaker_raw.strip()
            text = _normalize_text(text)

            if not speaker_raw or not text:
                # Malformed line (e.g. ":" with nothing meaningful on either
                # side) — treat as continuation instead of a broken turn.
                if turns:
                    turns[-1]["text"] = (turns[-1]["text"] + " " + _normalize_text(raw_text)).strip()
                continue

            turns.append({
                "id": f"t{len(turns) + 1:03d}",
                "speaker_raw": speaker_raw,
                "role_inferred": _infer_role(speaker_raw),
                "text": text,
            })
        else:
            # Continuation of the previous turn (no new speaker on this line)
            if turns:
                turns[-1]["text"] = (turns[-1]["text"] + " " + _normalize_text(raw_text)).strip()
            else:
                logging.warning(f"Skipping paragraph with no preceding speaker: {raw_text[:80]!r}")

    logging.info(f"Parsed {len(turns)} turns from {docx_path}")

    return {
        "meeting": {
            "type": "",
            "date": None,
            "chair": "",
            "participants": [],
            "session_number": "",
        },
        "turns": turns,
        "docs": [],
        "entities": [],
    }


def build_labeled_transcript_text(parsed: Dict) -> str:
    """
    Flatten parsed turns into a single transcript string, one line per turn,
    each line tagged with the inferred role:

        [CHAIR] Phạm Hồng Sơn (Thành uỷ HCMC): ...
        [PRESENTER] Người nói không xác định 01: ...

    This is the string downstream chunking / atomic-fact / summary prompts
    consume, so the CHAIR-vs-PRESENTER distinction is visible to the model
    without requiring any schema changes further down the pipeline.
    """
    lines = []
    for turn in parsed.get("turns", []):
        role = turn.get("role_inferred") or PRESENTER
        # Normalize defensively even for turns loaded from an already
        # pre-processed JSON (e.g. Vietnamese_datasets/processed/*.json)
        # that may predate the soft-line-break fix in parse_transcript_docx
        # and still carry an embedded '\n' inside speaker_raw/text.
        speaker_raw = _normalize_text(turn.get('speaker_raw', ''))
        text = _normalize_text(turn.get('text', ''))
        lines.append(f"[{role}] {speaker_raw}: {text}")
    return "\n".join(lines) + ("\n" if lines else "")


def parse_transcript_docx_to_labeled_text(docx_path: str) -> str:
    """Convenience wrapper: docx path -> labeled transcript text directly."""
    return build_labeled_transcript_text(parse_transcript_docx(docx_path))
