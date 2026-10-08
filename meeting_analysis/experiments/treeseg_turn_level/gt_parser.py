"""Parse a (raw transcript .doc, groundtruth .docx) pair from
``web_crawl/{downloads,outputs}/...`` into turn-level structures.

Reuses the exact conventions documented in ``web_crawl/CLAUDE.md`` and
``.claude/skills/labeler/SKILL.md`` (the same conventions the ``/labeler``
skill used to author the groundtruth files), instead of inventing a new
parsing scheme:

- Speaker turn header in the raw transcript: 4-space-indented line
  ``"Full Name - role"`` (the exact regex the labeler workflow itself uses
  to enumerate speakers, per ``web_crawl/CLAUDE.md`` step 4).
- Groundtruth docx: ``Heading 3`` = topic title, ``Heading 4`` "Luận điểm
  thảo luận" opens the per-speaker bullet block, each speaker introduced by
  two ``Normal`` paragraphs (abbreviation, then "Full Name - role") followed
  by ``List Bullet`` points.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import subprocess

import docx

_SPEAKER_LINE_RE = re.compile(r"^\s{4}([A-ZĐÀ-Ỹ][^\n]{0,60}) - ([^\n]{2,60})$")
_LUAN_DIEM_HEADING = "Luận điểm thảo luận"


@dataclass(frozen=True)
class Turn:
    speaker: str
    role: str
    text: str


def read_doc_text(path: Path) -> str:
    """Extract plain text from a legacy .doc file via antiword (preserves
    Vietnamese diacritics -- see web_crawl/CLAUDE.md)."""

    result = subprocess.run(
        ["antiword", str(path)], capture_output=True, text=True, check=True
    )
    return result.stdout


def parse_turns(raw_text: str) -> list[Turn]:
    """Split raw transcript text into turns at speaker-header lines.

    A line matching the speaker pattern starting with "Kính thưa" is a
    salutation inside someone's speech, not a new speaker header (same
    exclusion the labeler workflow's own grep uses).
    """

    turns: list[Turn] = []
    current_speaker: str | None = None
    current_role = ""
    current_lines: list[str] = []

    def flush() -> None:
        if current_speaker is not None:
            text = " ".join(line.strip() for line in current_lines if line.strip())
            if text:
                turns.append(Turn(current_speaker, current_role, text))

    for line in raw_text.splitlines():
        match = _SPEAKER_LINE_RE.match(line)
        if match and not line.strip().startswith("Kính thưa"):
            flush()
            current_speaker, current_role = match.group(1).strip(), match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)
    flush()
    return turns


@dataclass
class GtTopic:
    title: str
    speakers: list[str] = field(default_factory=list)  # full names, order of first bullet


def parse_groundtruth(path: Path) -> list[GtTopic]:
    """Parse one ``*_groundtruth.docx`` into an ordered list of topics, each
    with the full names of speakers who have at least one bullet under it.

    Only "Diễn biễn họp:" content is topic-bearing; "Kết luận họp:" (final
    Heading 2 section) is a closing summary, not a topic segment, so parsing
    stops feeding topics once it is reached.
    """

    document = docx.Document(str(path))
    topics: list[GtTopic] = []
    current: GtTopic | None = None
    in_luan_diem = False
    stopped = False

    for para in document.paragraphs:
        if stopped:
            break
        style = para.style.name if para.style else ""
        text = para.text.strip()
        if not text:
            continue

        if style == "Heading 2":
            if text.startswith("Kết luận"):
                stopped = True
            in_luan_diem = False
            continue
        if style == "Heading 3":
            current = GtTopic(title=text)
            topics.append(current)
            in_luan_diem = False
            continue
        if style == "Heading 4":
            in_luan_diem = text.startswith(_LUAN_DIEM_HEADING)
            continue
        if style == "Normal" and in_luan_diem and current is not None:
            if " - " in text:
                full_name = text.split(" - ", 1)[0].strip()
                if full_name not in current.speakers:
                    current.speakers.append(full_name)

    return topics
