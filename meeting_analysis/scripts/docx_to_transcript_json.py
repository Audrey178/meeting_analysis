"""Convert a speaker-turn meeting-minutes .docx into the bien-ban-vdt-trang-v1.json schema.

The source .docx has no audio, so start_time/end_time are SYNTHETIC, paced at a
fixed rate derived from bien-ban-vdt-trang-v1.json (2.3 words/sec, 0.25s gap
between same-turn segments, 1.0s gap between turns). Each docx paragraph is one
speaker turn; there are no natural sub-utterance boundaries to split on, so each
turn becomes exactly one item (one point_id/ref_id pair per turn).
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import docx

WORDS_PER_SECOND = 2.3
TURN_GAP_SECONDS = 1.0
INITIAL_OFFSET_SECONDS = 0.25

TURN_PATTERN = re.compile(r"^(.+?):\n(.*)$", re.DOTALL)
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "bien-ban-tong-hop")


def parse_turns(docx_path: Path) -> list[tuple[str, str]]:
    document = docx.Document(docx_path)
    turns = []
    for paragraph in document.paragraphs:
        text = paragraph.text
        if not text.strip():
            continue
        match = TURN_PATTERN.match(text)
        if not match:
            raise ValueError(f"Paragraph does not match 'Speaker (Org):\\nText' pattern: {text[:80]!r}")
        speaker_name = match.group(1).strip()
        segment = match.group(2).strip()
        turns.append((speaker_name, segment))
    return turns


def build_items(turns: list[tuple[str, str]]) -> list[dict]:
    items = []
    cursor = INITIAL_OFFSET_SECONDS
    for index, (speaker_name, segment) in enumerate(turns):
        word_count = len(segment.split())
        duration = word_count / WORDS_PER_SECOND
        start_time = cursor
        end_time = start_time + duration
        point_id = str(uuid.uuid5(NAMESPACE, f"point-{index}"))
        ref_id = str(uuid.uuid5(NAMESPACE, f"ref-{index}"))
        items.append(
            {
                "id": index,
                "segment": segment,
                "segment_html": segment,
                "speaker_name": speaker_name,
                "speaker_org_unit": None,
                "start_time": round(start_time, 3),
                "end_time": round(end_time, 3),
                "point_id": point_id,
                "ref_id": [ref_id],
                "recording_id": None,
            }
        )
        cursor = end_time + TURN_GAP_SECONDS
    return items


def convert(docx_path: Path) -> dict:
    turns = parse_turns(docx_path)
    items = build_items(turns)
    transcript = " ".join(item["segment"] for item in items)
    return {
        "transcript": transcript,
        "items": items,
        "full_text": transcript,
        "metadata": {
            "last_edited": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "has_edits": False,
            "source_note": (
                f"Converted from {docx_path.name} (plain speaker-turn minutes, no audio). "
                "start_time/end_time are SYNTHETIC (word-count-paced at 2.3 words/sec, "
                "1.0s gap between turns, matching the pacing model in bien-ban-vdt-trang-v1.json). "
                "point_id/ref_id are TURN-level: one pair per docx paragraph/turn. No sub-turn "
                "segmentation was applied since the source has no natural sub-utterance boundaries."
            ),
        },
    }


if __name__ == "__main__":
    src = Path("inputs/Biên bản tổng hợp.docx")
    dst = Path("inputs/bien-ban-tong-hop-v1.json")
    result = convert(src)
    dst.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(result['items'])} items to {dst}")
