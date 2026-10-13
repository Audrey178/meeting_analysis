"""Dựng bộ test tổng hợp từ các file spec (``specs/*.md``): transcript + gold.

Mỗi spec là một cuộc họp do Claude Code viết tay, gồm các chủ đề đã biết trước ranh giới
và các việc giao / quyết định / bẫy được cài sẵn. Script này hoàn toàn tất định (không gọi
LLM), làm ba việc:

1. Chuyển spec thành transcript đúng schema ``inputs/bien-ban-*-v1.json`` (STT export):
   mỗi lượt nói tách thành các item con ~80-250 ký tự như STT, chung ``point_id``/``ref_id``;
   thời gian giả lập giống ``scripts/docx_to_transcript_json.py`` (2.3 từ/giây, cách 0.25s
   trong một lượt, 1.0s giữa các lượt).
2. Chạy đúng stage01-03 của pipeline trên transcript đó để quy ra ``TURN_xxxxxx`` mà pipeline
   thực sự thấy, và kiểm tra mỗi lượt viết tay khớp đúng một ``SpeakerTurn`` (không bị gộp
   hay tách ngoài ý muốn). Nhờ vậy gold ranh giới và ``evidence_ids`` gold dùng thẳng được
   để so với output của API.
3. Ghi ``transcripts/<id>.json``, ``gold/<id>.json`` và ``manifest.json``.

Định dạng spec (xem ``README.md`` mục "Định dạng spec"):

    ```json meta
    {"meeting_id": "...", "speakers": {"CT": "Đ/c Hùng (Sở KH&CN)", ...}, ...}
    ```
    ## TOPIC | <tiêu đề gold> | <tóm tắt gold>
    @CT: nội dung lượt nói ...
    @NAM #giao1: lượt nói có nhãn ``giao1`` để gold tham chiếu ...
    ```json gold
    {"assignments": [...], "decisions": [...], "negatives": [...], "key_points": [...]}
    ```

Chạy:  python eval/synthetic/build.py            (dựng mọi spec)
       python eval/synthetic/build.py synth_001  (chỉ một spec)
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.stages.stage01_effective_transcript import resolve_effective_transcript  # noqa: E402
from src.stages.stage02_evidence import build_evidence_items  # noqa: E402
from src.stages.stage03_speaker_turns import build_speaker_turns  # noqa: E402
from src.utils.adapters import parse_transcript_payload  # noqa: E402
from src.utils.config import load_config  # noqa: E402

SPECS_DIR = _HERE / "specs"
TRANSCRIPTS_DIR = _HERE / "transcripts"
GOLD_DIR = _HERE / "gold"
MANIFEST_PATH = _HERE / "manifest.json"
CONFIG_PATH = _REPO_ROOT / "configs" / "default.json"

WORDS_PER_SECOND = 2.3
SUBSEGMENT_GAP_SECONDS = 0.25
TURN_GAP_SECONDS = 1.0
INITIAL_OFFSET_SECONDS = 0.25
SUBSEGMENT_MIN_CHARS = 80
SUBSEGMENT_MAX_CHARS = 250

_FENCE_RE = re.compile(r"```json (meta|gold)\n(.*?)\n```", re.DOTALL)
_TOPIC_RE = re.compile(r"^## TOPIC \| (.+?) \| (.+)$")
_TURN_RE = re.compile(r"^@([A-Z0-9_]+)(?: #([\w-]+))?: ?(.*)$")
_SPLIT_RE = re.compile(r"(?<=[.?!,;:])\s+")


@dataclass
class AuthoredTurn:
    """Một lượt nói viết tay trong spec."""

    speaker_key: str
    tag: str | None
    text: str
    topic_index: int


@dataclass
class Spec:
    """Nội dung một spec đã parse."""

    meta: dict
    gold: dict
    topics: list[tuple[str, str]] = field(default_factory=list)
    turns: list[AuthoredTurn] = field(default_factory=list)


def parse_spec(path: Path) -> Spec:
    """Đọc một spec ``.md``: khối ``json meta``, các ``## TOPIC`` + lượt ``@KEY``, khối ``json gold``.

    Lỗi: ValueError nếu thiếu khối meta/gold, lượt nói nằm ngoài chủ đề, hoặc dòng không nhận diện được.
    """

    raw = path.read_text(encoding="utf-8")
    blocks = {kind: json.loads(body) for kind, body in _FENCE_RE.findall(raw)}
    if "meta" not in blocks or "gold" not in blocks:
        raise ValueError(f"{path.name}: thiếu khối ```json meta``` hoặc ```json gold```")
    spec = Spec(meta=blocks["meta"], gold=blocks["gold"])
    body = _FENCE_RE.sub("", raw)

    for line_no, line in enumerate(body.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("<!--"):
            continue
        if topic := _TOPIC_RE.match(stripped):
            spec.topics.append((topic.group(1).strip(), topic.group(2).strip()))
            continue
        if turn := _TURN_RE.match(stripped):
            if not spec.topics:
                raise ValueError(f"{path.name}:{line_no}: lượt nói trước ## TOPIC đầu tiên")
            spec.turns.append(
                AuthoredTurn(turn.group(1), turn.group(2), turn.group(3).strip(), len(spec.topics) - 1)
            )
            continue
        if spec.turns and not stripped.startswith("#"):
            spec.turns[-1].text = f"{spec.turns[-1].text} {stripped}".strip()
            continue
        raise ValueError(f"{path.name}:{line_no}: không nhận diện được dòng: {stripped[:60]!r}")
    return spec


def split_into_subsegments(text: str) -> list[str]:
    """Tách một lượt nói thành các item con ~80-250 ký tự tại dấu câu, như STT xuất ra."""

    pieces = [piece for piece in _SPLIT_RE.split(text) if piece]
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip()
        if current and len(candidate) > SUBSEGMENT_MAX_CHARS and len(current) >= SUBSEGMENT_MIN_CHARS:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        if chunks and len(current) < SUBSEGMENT_MIN_CHARS // 2:
            chunks[-1] = f"{chunks[-1]} {current}"
        else:
            chunks.append(current)
    return chunks


def build_transcript(spec: Spec) -> tuple[dict, list[int]]:
    """Dựng transcript schema v1 từ spec.

    Đầu ra: (payload transcript, chỉ số item đầu tiên của từng lượt viết tay).
    """

    meeting_id = spec.meta["meeting_id"]
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"synthetic-eval/{meeting_id}")
    speakers = spec.meta["speakers"]
    items: list[dict] = []
    first_item_of_turn: list[int] = []
    cursor = INITIAL_OFFSET_SECONDS
    for turn_index, turn in enumerate(spec.turns):
        if turn.speaker_key not in speakers:
            raise ValueError(f"{meeting_id}: người nói không khai báo trong meta: {turn.speaker_key}")
        point_id = str(uuid.uuid5(namespace, f"point-{turn_index}"))
        ref_id = str(uuid.uuid5(namespace, f"ref-{turn_index}"))
        first_item_of_turn.append(len(items))
        for sub_index, segment in enumerate(split_into_subsegments(turn.text)):
            if sub_index:
                cursor += SUBSEGMENT_GAP_SECONDS
            duration = max(len(segment.split()), 1) / WORDS_PER_SECOND
            items.append(
                {
                    "id": len(items),
                    "segment": segment,
                    "segment_html": segment,
                    "speaker_name": speakers[turn.speaker_key],
                    "speaker_org_unit": None,
                    "start_time": round(cursor, 3),
                    "end_time": round(cursor + duration, 3),
                    "point_id": point_id,
                    "ref_id": [ref_id],
                    "recording_id": None,
                }
            )
            cursor += duration
        cursor += TURN_GAP_SECONDS
    transcript = " ".join(item["segment"] for item in items)
    payload = {
        "transcript": transcript,
        "items": items,
        "full_text": transcript,
        "metadata": {
            "meeting_id": meeting_id,
            "revision_id": "synthetic-v1",
            "last_edited": "2026-10-01T00:00:00.000Z",
            "has_edits": False,
            "source_note": (
                "SYNTHETIC meeting written by Claude Code for pipeline evaluation "
                "(eval/synthetic/specs). Timestamps are synthetic (2.3 words/sec). "
                "Gold is in eval/synthetic/gold."
            ),
        },
    }
    return payload, first_item_of_turn


def map_turns_with_pipeline(payload: dict, first_item_of_turn: list[int]) -> list[dict]:
    """Chạy stage01-03 và quy mỗi lượt viết tay về đúng một ``SpeakerTurn`` của pipeline.

    Lỗi: ValueError nếu số ``SpeakerTurn`` khác số lượt viết tay hoặc ranh giới lệch
        (tức stage03 đã gộp/tách ngoài ý muốn, gold sẽ không đạt được).
    """

    meeting_id, _revision_id, raw_items = parse_transcript_payload(payload)
    config = load_config(str(CONFIG_PATH))
    evidence = build_evidence_items(meeting_id, resolve_effective_transcript(raw_items))
    turns = build_speaker_turns(evidence, config.turn_builder)
    if len(turns) != len(first_item_of_turn):
        raise ValueError(
            f"{meeting_id}: stage03 cho {len(turns)} lượt, spec có {len(first_item_of_turn)} lượt"
        )
    evidence_index = {item.evidence_id: index for index, item in enumerate(evidence)}
    mapped = []
    for authored_index, turn in enumerate(turns):
        first_evidence = evidence_index[turn.evidence_ids[0]]
        if first_evidence != first_item_of_turn[authored_index]:
            raise ValueError(f"{meeting_id}: lượt {authored_index} lệch ranh giới item sau stage03")
        mapped.append(
            {
                "turn_id": turn.turn_id,
                "speaker": turn.speaker,
                "chars": len(f"{turn.speaker}: {turn.text_exact}") + 1,
            }
        )
    return mapped


def _resolve_tags(spec: Spec, turn_ids_by_tag: dict[str, str], refs: list[str], where: str) -> list[str]:
    missing = [ref for ref in refs if ref not in turn_ids_by_tag]
    if missing:
        raise ValueError(f"{spec.meta['meeting_id']}: {where} tham chiếu tag không tồn tại: {missing}")
    return [turn_ids_by_tag[ref] for ref in refs]


def _topic_of_tags(spec: Spec, refs: list[str]) -> int:
    by_tag = {turn.tag: turn.topic_index for turn in spec.turns if turn.tag}
    return by_tag[refs[0]]


def build_gold(spec: Spec, mapped: list[dict]) -> dict:
    """Dựng file gold: ranh giới theo chỉ số ``SpeakerTurn``, chủ đề, việc giao, quyết định, bẫy."""

    turn_ids_by_tag = {
        turn.tag: mapped[index]["turn_id"] for index, turn in enumerate(spec.turns) if turn.tag
    }
    starts = [
        index
        for index, turn in enumerate(spec.turns)
        if index == 0 or turn.topic_index != spec.turns[index - 1].topic_index
    ]
    edges = [*starts, len(spec.turns)]
    char_prefix = [0]
    for turn in mapped:
        char_prefix.append(char_prefix[-1] + turn["chars"])

    topics = []
    for topic_index, (lo, hi) in enumerate(zip(edges[:-1], edges[1:])):
        title, summary = spec.topics[topic_index]
        topics.append(
            {
                "index": topic_index,
                "title": title,
                "summary": summary,
                "turn_range": [lo, hi],
                "turn_ids": [mapped[lo]["turn_id"], mapped[hi - 1]["turn_id"]],
                "chars": char_prefix[hi] - char_prefix[lo],
                "same_topic_as": spec.meta.get("revisits", {}).get(str(topic_index)),
            }
        )

    def with_evidence(entries: list[dict], kind: str) -> list[dict]:
        resolved = []
        for number, entry in enumerate(entries, start=1):
            refs = entry["turns"]
            resolved.append(
                {
                    "id": f"{kind}{number}",
                    **{key: value for key, value in entry.items() if key != "turns"},
                    "topic_index": _topic_of_tags(spec, refs),
                    "evidence_turn_ids": _resolve_tags(spec, turn_ids_by_tag, refs, kind),
                }
            )
        return resolved

    return {
        "meeting_id": spec.meta["meeting_id"],
        "n_turns": len(mapped),
        "total_chars": char_prefix[-1],
        "boundaries": starts[1:],
        "topics": topics,
        "assignments": with_evidence(spec.gold.get("assignments", []), "A"),
        "decisions": with_evidence(spec.gold.get("decisions", []), "D"),
        "negatives": with_evidence(spec.gold.get("negatives", []), "N"),
        "key_points": with_evidence(spec.gold.get("key_points", []), "K"),
        "speakers": spec.meta["speakers"],
        "tags": spec.meta.get("tags", []),
    }


def build_one(spec_path: Path) -> dict:
    """Dựng transcript + gold cho một spec, trả về dòng manifest."""

    spec = parse_spec(spec_path)
    payload, first_item_of_turn = build_transcript(spec)
    mapped = map_turns_with_pipeline(payload, first_item_of_turn)
    gold = build_gold(spec, mapped)
    meeting_id = spec.meta["meeting_id"]
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    GOLD_DIR.mkdir(exist_ok=True)
    (TRANSCRIPTS_DIR / f"{meeting_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (GOLD_DIR / f"{meeting_id}.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "meeting_id": meeting_id,
        "title": spec.meta.get("title", ""),
        "meeting_type": spec.meta.get("meeting_type", ""),
        "length_bucket": spec.meta.get("length_bucket", ""),
        # dev: 30 transcript đầu (đã xem khi phát triển pipeline); heldout: synth_031+ viết sau khi
        # chốt code benchmark, không chạy pipeline lên trước (eval/bench/run.py --split).
        "split": spec.meta.get("split", "dev"),
        "tags": spec.meta.get("tags", []),
        "n_items": len(payload["items"]),
        "n_turns": gold["n_turns"],
        "n_topics": len(gold["topics"]),
        "total_chars": gold["total_chars"],
        "topic_chars": [topic["chars"] for topic in gold["topics"]],
        "n_assignments": len(gold["assignments"]),
        "n_decisions": len(gold["decisions"]),
        "n_negatives": len(gold["negatives"]),
    }


def main(argv: list[str]) -> None:
    wanted = set(argv)
    rows = []
    existing = {}
    if MANIFEST_PATH.is_file():
        existing = {row["meeting_id"]: row for row in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))}
    for spec_path in sorted(SPECS_DIR.glob("*.md")):
        if wanted and spec_path.stem not in wanted:
            continue
        row = build_one(spec_path)
        rows.append(row)
        print(
            f"{row['meeting_id']}: {row['n_turns']} lượt, {row['n_topics']} chủ đề, "
            f"{row['total_chars']} ký tự {row['topic_chars']}, "
            f"{row['n_assignments']} việc giao, {row['n_decisions']} quyết định, {row['n_negatives']} bẫy"
        )
    existing.update({row["meeting_id"]: row for row in rows})
    MANIFEST_PATH.write_text(
        json.dumps(sorted(existing.values(), key=lambda row: row["meeting_id"]), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main(sys.argv[1:])
