"""Convert a plain-text bien-ban .txt transcript into the bien-ban-vdt-trang-v1.json schema.

The .txt has a header block ending with a "====" separator, then one sub-segment
per non-empty line in the form "Speaker (Org): text". There is no audio, so
start_time/end_time are SYNTHETIC, using the same pacing as bien-ban-vdt-trang-v1.json
(2.3 words/sec, 0.25s gap between sub-segments of one turn, 1.0s gap between turns).
point_id/ref_id are TURN-level: one pair per consecutive same-speaker run.

Usage: python scripts/txt_to_transcript_json.py <input.txt> <output.json>
"""

import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

WORDS_PER_SECOND = 2.3
SEGMENT_GAP_SECONDS = 0.25
TURN_GAP_SECONDS = 1.0
INITIAL_OFFSET_SECONDS = 0.25

LINE_PATTERN = re.compile(r"^(.+?\)):\s*(.*)$")


def parse_segments(txt_path: Path) -> list[tuple[str, str]]:
    lines = txt_path.read_text(encoding="utf-8").splitlines()
    separator_index = next(i for i, line in enumerate(lines) if line.startswith("===="))
    segments = []
    for line in lines[separator_index + 1:]:
        if not line.strip():
            continue
        match = LINE_PATTERN.match(line)
        if not match:
            raise ValueError(f"Line does not match 'Speaker (Org): text' pattern: {line[:80]!r}")
        segments.append((match.group(1).strip(), match.group(2).strip()))
    return segments


def build_items(segments: list[tuple[str, str]], namespace: uuid.UUID) -> list[dict]:
    items = []
    cursor = INITIAL_OFFSET_SECONDS
    turn_index = -1
    previous_speaker = None
    for index, (speaker_name, segment) in enumerate(segments):
        if speaker_name != previous_speaker:
            turn_index += 1
            if previous_speaker is not None:
                cursor += TURN_GAP_SECONDS - SEGMENT_GAP_SECONDS
        start_time = cursor
        end_time = start_time + len(segment.split()) / WORDS_PER_SECOND
        items.append(
            {
                "id": index,
                "segment": segment,
                "segment_html": segment,
                "speaker_name": speaker_name,
                "speaker_org_unit": None,
                "start_time": round(start_time, 3),
                "end_time": round(end_time, 3),
                "point_id": str(uuid.uuid5(namespace, f"point-{turn_index}")),
                "ref_id": [str(uuid.uuid5(namespace, f"ref-{turn_index}"))],
                "recording_id": None,
            }
        )
        cursor = end_time + SEGMENT_GAP_SECONDS
        previous_speaker = speaker_name
    return items


def convert(txt_path: Path) -> dict:
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, txt_path.stem)
    items = build_items(parse_segments(txt_path), namespace)
    transcript = " ".join(item["segment"] for item in items)
    return {
        "transcript": transcript,
        "items": items,
        "full_text": transcript,
        "metadata": {
            "last_edited": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "has_edits": False,
            "source_note": (
                f"Converted from {txt_path.name}; start_time/end_time are SYNTHETIC "
                "(word-count-paced at 2.3 words/sec, 0.25s gap within a turn, 1.0s gap between turns), "
                "not real ASR alignment. point_id/ref_id are TURN-level (one pair per consecutive "
                "same-speaker run)."
            ),
        },
    }


if __name__ == "__main__":
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    result = convert(src)
    dst.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    turns = len({item["point_id"] for item in result["items"]})
    print(f"Wrote {len(result['items'])} items ({turns} turns) to {dst}")
