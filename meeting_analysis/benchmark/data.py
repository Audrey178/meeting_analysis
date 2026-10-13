"""Nạp cuộc họp cho benchmark: lượt nói sau stage01–03 cộng gold (``PLAN.md`` §2).

Mọi phương pháp nhận cùng một ``Meeting``; bộ chấm dùng cùng danh sách lượt để quy
``evidence_turn_ids`` về chỉ số lượt và tính khối lượng ký tự cho Pk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.stages.stage01_effective_transcript import resolve_effective_transcript
from src.stages.stage02_evidence import build_evidence_items
from src.stages.stage03_speaker_turns import build_speaker_turns
from src.utils.adapters import parse_transcript_payload
from src.utils.config import load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_DIR = PROJECT_ROOT / "eval" / "synthetic"
REAL_GOLD_DIR = PROJECT_ROOT / "experiments" / "007_dialtreeseg" / "gold"
CONFIG_PATH = PROJECT_ROOT / "configs" / "default.json"

DEV_IDS = tuple(f"synth_{i:03d}" for i in range(1, 31))
TEST_IDS = tuple(f"synth_{i:03d}" for i in range(31, 41))
REAL_IDS = ("vdt_trang", "tong_hop", "recording")
SPLITS = {"dev": DEV_IDS, "test": TEST_IDS, "real": REAL_IDS}


@dataclass(frozen=True, slots=True)
class Turn:
    """Một lượt nói sau stage03.

    Các trường:
        turn_id: "TURN_000001"…, đúng id mà gold và pipeline dùng.
        speaker: tên người nói như trong transcript.
        text: nội dung lượt nói.
    """

    turn_id: str
    speaker: str
    text: str

    @property
    def chars(self) -> int:
        """Số ký tự của lượt khi render "speaker: text" (cùng cách đo với ``build.py``)."""

        return len(f"{self.speaker}: {self.text}") + 1


@dataclass(frozen=True, slots=True)
class Meeting:
    """Đầu vào chung cho mọi phương pháp, kèm gold cho bộ chấm.

    Các trường:
        meeting_id: "synth_012", "vdt_trang"…
        turns: lượt nói theo thứ tự.
        meeting_date: ngày họp ISO nếu biết, None nếu không.
        gold: dict gold (synthetic: đủ việc giao/kết luận/bẫy/ý chính; họp thật: chỉ ranh giới).
    """

    meeting_id: str
    turns: tuple[Turn, ...]
    meeting_date: str | None = None
    gold: dict = field(default_factory=dict)

    @property
    def total_chars(self) -> int:
        return sum(turn.chars for turn in self.turns)

    def render(self) -> str:
        """Văn bản cuộc họp đưa vào prompt: mỗi dòng "[TURN_xxxxxx] speaker: text"."""

        return "\n".join(f"[{turn.turn_id}] {turn.speaker}: {turn.text}" for turn in self.turns)


def load_turns(payload: dict) -> tuple[str, tuple[Turn, ...]]:
    """Chạy stage01–03 trên payload transcript, trả (meeting_id, lượt nói)."""

    meeting_id, _revision_id, raw_items = parse_transcript_payload(payload)
    config = load_config(str(CONFIG_PATH))
    evidence = build_evidence_items(meeting_id, resolve_effective_transcript(raw_items))
    speaker_turns = build_speaker_turns(evidence, config.turn_builder)
    turns = tuple(Turn(t.turn_id, t.speaker, t.text_exact) for t in speaker_turns)
    return meeting_id, turns


def load_meeting(meeting_id: str) -> Meeting:
    """Nạp một cuộc họp synthetic hoặc họp thật theo id.

    Lỗi: ValueError nếu số lượt sau stage03 khác ``n_turns`` của gold (gold sẽ lệch id lượt).
    """

    if meeting_id.startswith("synth_"):
        payload_path = SYNTHETIC_DIR / "transcripts" / f"{meeting_id}.json"
        gold = json.loads((SYNTHETIC_DIR / "gold" / f"{meeting_id}.json").read_text())
    else:
        gold = json.loads((REAL_GOLD_DIR / f"{meeting_id}.json").read_text())
        payload_path = PROJECT_ROOT / gold["source"]
    _, turns = load_turns(json.loads(payload_path.read_text()))
    if len(turns) != gold["n_turns"]:
        raise ValueError(f"{meeting_id}: stage03 cho {len(turns)} lượt, gold có {gold['n_turns']}")
    return Meeting(meeting_id, turns, gold.get("meeting_date"), gold)
