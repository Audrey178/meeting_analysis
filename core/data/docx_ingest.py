"""Ingest a Vietnamese ASR meeting-transcript .docx into a MeetingRecord.

Source format observed (Vietnamese_datasets/input/*.docx): one paragraph per
turn, laid out as a speaker header line, a line break, then the spoken text —

    Phạm Hồng Sơn (Thành uỷ HCMC):
    Có lần coi không?

There are no timestamps and no turn IDs in the source, so this loader
assigns sequential IDs and leaves t_start at 0.0 (unknown). It does NOT
attempt to infer role_inferred from content (e.g. guessing who is "chủ trì"
from how they're addressed) — that requires semantic understanding out of
scope for a mechanical ingest step; role_inferred is left "" for every turn.

Usage:
    python3 -m core.data.docx_ingest "Vietnamese_datasets/input/FILE.docx"
    python3 -m core.data.docx_ingest FILE.docx -o out.json --chair "..." --date 2026-07-28
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from docx import Document

from core.data.models import MeetingInfo, MeetingRecord, Turn, dump_json


def _split_turn_paragraph(text: str) -> tuple[str, str] | None:
    """Split a paragraph into (speaker_raw, turn_text) if it looks like a
    speaker header ("Name (role):") followed by spoken text. Returns None
    if the paragraph doesn't match — i.e. it's a continuation line."""
    if "\n" not in text:
        return None
    speaker_line, rest = text.split("\n", 1)
    speaker_line = speaker_line.strip()
    if not speaker_line.endswith(":"):
        return None
    speaker_raw = speaker_line[:-1].strip()
    turn_text = rest.strip()
    if not speaker_raw or not turn_text:
        return None
    return speaker_raw, turn_text


def parse_meeting_docx(
    path: str,
    *,
    doc_type: str = "",
    meeting_date: date | None = None,
    chair: str = "",
    participants: list[str] | None = None,
    session_number: str = "",
) -> MeetingRecord:
    """Parse a transcript .docx into a MeetingRecord. `docs` and `entities`
    are left empty — this loader only covers the `turns` ingestion step."""
    document = Document(path)

    turns: list[Turn] = []
    skipped_continuations = 0
    for para in document.paragraphs:
        raw = para.text
        if not raw.strip():
            continue

        parsed = _split_turn_paragraph(raw)
        if parsed is not None:
            speaker_raw, turn_text = parsed
            turns.append(Turn(
                id=f"t{len(turns) + 1:03d}",
                speaker_raw=speaker_raw,
                role_inferred="",
                text=turn_text,
                t_start=0.0,
            ))
        elif turns:
            # Continuation of the previous speaker's turn (no header found).
            turns[-1].text = f"{turns[-1].text} {raw.strip()}".strip()
            skipped_continuations += 1
        else:
            # Stray paragraph before any recognized turn — drop it rather
            # than fabricate a speaker.
            skipped_continuations += 1

    meeting = MeetingInfo(
        type=doc_type,
        date=meeting_date,
        chair=chair,
        participants=participants or [],
        session_number=session_number,
    )
    return MeetingRecord(meeting=meeting, turns=turns, docs=[], entities=[])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a Vietnamese ASR meeting transcript (.docx) into a MeetingRecord JSON."
    )
    parser.add_argument("input", help="Path to the .docx transcript")
    parser.add_argument("-o", "--output", help="Output JSON path (default: <input stem>.meetingrecord.json)")
    parser.add_argument("--type", dest="doc_type", default="", help="loại cuộc họp")
    parser.add_argument("--date", dest="meeting_date", default=None, help="ngày họp, ISO YYYY-MM-DD")
    parser.add_argument("--chair", default="", help="chủ trì")
    parser.add_argument("--participants", default="", help="thành phần, phân tách bằng dấu phẩy")
    parser.add_argument("--session-number", dest="session_number", default="", help="số thứ tự phiên")
    args = parser.parse_args()

    meeting_date = None
    if args.meeting_date:
        try:
            meeting_date = date.fromisoformat(args.meeting_date)
        except ValueError:
            parser.error(f"--date must be ISO format YYYY-MM-DD, got {args.meeting_date!r}")

    participants = [p.strip() for p in args.participants.split(",") if p.strip()]

    record = parse_meeting_docx(
        args.input,
        doc_type=args.doc_type,
        meeting_date=meeting_date,
        chair=args.chair,
        participants=participants,
        session_number=args.session_number,
    )

    output_path = Path(args.output) if args.output else Path(args.input).with_suffix(".meetingrecord.json")
    output_path.write_text(dump_json(record), encoding="utf-8")

    unidentified = sum(1 for t in record.turns if "không xác định" in t.speaker_raw.lower())
    print(f"Parsed {len(record.turns)} turns ({unidentified} from an unidentified speaker) -> {output_path}")


if __name__ == "__main__":
    main()
