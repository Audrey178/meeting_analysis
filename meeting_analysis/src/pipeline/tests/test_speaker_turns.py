"""Kiểm việc dựng lượt nói theo mã người nói: hai người trùng họ tên không bị gộp làm một."""

from __future__ import annotations

from ...utils.adapters import parse_transcript_payload
from ...utils.config import TurnBuilderConfig
from ..step1_turns.effective_transcript import resolve_effective_transcript
from ..step1_turns.speaker_turns import build_speaker_turns


def _turns(items: list[dict]):
    _, raw_items = parse_transcript_payload({"meeting_id": "m", "items": items})
    return build_speaker_turns(resolve_effective_transcript(raw_items), TurnBuilderConfig())


def _stt_item(index: int, speaker: str, ref_id: str, start: float) -> dict:
    return {
        "id": index,
        "segment": f"câu {index}",
        "speaker_name": speaker,
        "ref_id": [ref_id],
        "start_time": start,
        "end_time": start + 1,
    }


def test_same_name_different_ref_id_are_split_and_labeled():
    turns = _turns(
        [
            _stt_item(1, "Nguyễn Văn A", "p1", 0),
            _stt_item(2, "Nguyễn Văn A", "p2", 1),
            _stt_item(3, "Nguyễn Văn A", "p1", 5),
        ]
    )

    assert [(turn.speaker, turn.speaker_id) for turn in turns] == [
        ("Nguyễn Văn A", "p1"),
        ("Nguyễn Văn A #2", "p2"),
        ("Nguyễn Văn A", "p1"),
    ]


def test_same_ref_id_merges_into_one_turn():
    turns = _turns([_stt_item(1, "Nguyễn Văn A", "p1", 0), _stt_item(2, "Nguyễn Văn A", "p1", 1)])

    assert len(turns) == 1
    assert turns[0].speaker == "Nguyễn Văn A"
    assert turns[0].speaker_id == "p1"


def test_ref_id_takes_precedence_over_speaker_id():
    turns = _turns(
        [
            {"id": "i1", "text": "a", "speaker": "B", "speaker_id": "s1", "ref_id": "r1", "start_ms": 0, "end_ms": 10},
            {"id": "i2", "text": "b", "speaker": "B", "ref_id": "r1", "start_ms": 20, "end_ms": 30},
            {"id": "i3", "text": "c", "speaker": "B", "speaker_id": "s2", "start_ms": 5000, "end_ms": 5010},
        ]
    )

    assert [(turn.speaker, turn.speaker_id) for turn in turns] == [("B", "r1"), ("B #2", "s2")]


def test_duplicate_item_ids_are_renamed_not_kept_twice():
    _, raw_items = parse_transcript_payload({"meeting_id": "m", "items": [
        _stt_item(1, "Nguyễn Văn A", "p1", 0),
        _stt_item(1, "Nguyễn Văn B", "p2", 2),
        _stt_item(2, "Nguyễn Văn A", "p1", 4),
    ]})

    assert [item.item_id for item in raw_items] == ["1", "1-1", "2"]
