"""Kiểm bộ chấm Bảng 1: gold làm dự đoán phải đạt điểm tối đa, output rỗng phải về 0."""

from __future__ import annotations

import pytest

from benchmark.data import DEV_IDS, Meeting, Turn, load_meeting
from benchmark.score import (
    actor_matches,
    deadline_matches,
    holm,
    normalize_name,
    paired_bootstrap,
    score_meeting,
    summarize,
)


def oracle_output(meeting: Meeting) -> dict:
    """Chuyển gold sang schema chung §5, như một phương pháp hoàn hảo."""

    gold = meeting.gold
    return {
        "topics": [{"start_turn": meeting.turns[b].turn_id, "title": ""} for b in [0, *gold["boundaries"]]],
        "assignments": [
            {"actor": a["actor"], "task": a["task"], "deadline": a["deadline"], "evidence_turn_ids": a["evidence_turn_ids"]}
            for a in gold["assignments"]
        ],
        "decisions": [{"text": d["text"], "evidence_turn_ids": d["evidence_turn_ids"]} for d in gold["decisions"]],
        "discussion": [
            {"text": k["point"], "speakers": [k["speaker"]], "evidence_turn_ids": k["evidence_turn_ids"]}
            for k in gold["key_points"]
        ],
    }


@pytest.fixture(scope="module")
def dev_meetings() -> list[Meeting]:
    return [load_meeting(meeting_id) for meeting_id in DEV_IDS]


def test_oracle_scores_perfectly(dev_meetings):
    row = summarize([score_meeting(m, oracle_output(m)) for m in dev_meetings])
    assert row["assign_f1"] == row["assign_actor_f1"] == row["decision_f1"] == 1.0
    assert row["coverage"] == 1.0 and row["deadline_acc"] == 1.0
    assert row["trap_rate"] == 0.0 and row["pk"] == 0.0 and row["average"] == 1.0


def test_empty_output_scores_zero_and_trap_undefined(dev_meetings):
    row = summarize([score_meeting(m, {}) for m in dev_meetings])
    assert row["assign_f1"] == row["decision_f1"] == row["coverage"] == 0.0
    assert row["trap_rate"] is None and row["average"] is None


def test_invalid_evidence_is_dropped(dev_meetings):
    meeting = dev_meetings[0]
    output = oracle_output(meeting)
    output["assignments"][0]["evidence_turn_ids"] = ["TURN_999999"]
    output["assignments"][1]["evidence_turn_ids"] = []
    counts = score_meeting(meeting, output).counts
    assert counts.dropped_invalid_evidence == 2
    assert counts.assign_tp == len(meeting.gold["assignments"]) - 2


def test_evidence_window_tolerates_one_turn(dev_meetings):
    meeting = dev_meetings[11]  # synth_012: nhiều việc giao ở lượt cuối
    output = oracle_output(meeting)
    index_of = {t.turn_id: i for i, t in enumerate(meeting.turns)}
    shifted = output["assignments"][0]
    last = max(index_of[t] for t in shifted["evidence_turn_ids"])
    shifted["evidence_turn_ids"] = [meeting.turns[min(last + 1, len(meeting.turns) - 1)].turn_id]
    assert score_meeting(meeting, output, window=1).counts.assign_tp == len(meeting.gold["assignments"])
    shifted["evidence_turn_ids"] = [meeting.turns[0].turn_id]
    assert score_meeting(meeting, output, window=1).counts.assign_tp == len(meeting.gold["assignments"]) - 1


def test_trap_counted_only_for_unmatched_items():
    turns = tuple(Turn(f"TURN_{i:06d}", "A", "x") for i in range(1, 6))
    gold = {
        "assignments": [],
        "decisions": [],
        "key_points": [],
        "negatives": [{"type": "rejected_task", "text": "viết lại toàn bộ module thanh toán", "evidence_turn_ids": ["TURN_000003"]}],
    }
    meeting = Meeting("toy", turns, None, gold)
    output = {"assignments": [{"actor": "Nam", "task": "Viết lại toàn bộ module thanh toán", "deadline": None, "evidence_turn_ids": ["TURN_000003"]}]}
    row = summarize([score_meeting(meeting, output)])
    assert row["trap_rate"] == 1.0


def test_unassigned_task_without_actor_is_not_a_trap():
    turns = tuple(Turn(f"TURN_{i:06d}", "A", "x") for i in range(1, 4))
    gold = {
        "assignments": [],
        "decisions": [],
        "key_points": [],
        "negatives": [{"type": "unassigned_task", "text": "rà soát quy trình tiếp nhận", "evidence_turn_ids": ["TURN_000002"]}],
    }
    meeting = Meeting("toy", turns, None, gold)
    item = {"task": "Rà soát quy trình tiếp nhận", "deadline": None, "evidence_turn_ids": ["TURN_000002"]}
    assert score_meeting(meeting, {"assignments": [{**item, "actor": None}]}).counts.trapped == 0
    assert score_meeting(meeting, {"assignments": [{**item, "actor": "Hùng"}]}).counts.trapped == 1


@pytest.mark.parametrize(
    ("pred", "gold", "aliases", "expected"),
    [
        ("Ông Bình", "Ông Bình (Chỉ huy trưởng nhà thầu)", (), True),
        ("bình", "Ông Bình (Chỉ huy trưởng nhà thầu)", (), True),
        ("SPEAKER_02", "Toàn", ("SPEAKER_02", "em"), True),
        ("em", "Toàn", ("SPEAKER_02", "em"), False),
        ("Anh Lực", "Anh Đông (Giám sát)", (), False),
        (None, "Toàn", (), False),
    ],
)
def test_actor_matching(pred, gold, aliases, expected):
    assert actor_matches(pred, gold, aliases) is expected


def test_normalize_name_strips_stacked_honorifics():
    assert normalize_name("Đ/c anh Tuấn (Giám đốc)") == "tuấn"


@pytest.mark.parametrize(
    ("pred", "gold", "expected"),
    [
        (None, None, True),
        ("chậm nhất thứ Sáu", "17h thứ Sáu tuần này", True),
        ("15/12", "phát hành chậm nhất 15/12", True),
        ("thứ Hai", "trước 31/12", False),
        (None, "thứ Hai", False),
    ],
)
def test_deadline_matching(pred, gold, expected):
    assert deadline_matches(pred, gold, None) is expected


def test_paired_bootstrap_and_holm(dev_meetings):
    subset = dev_meetings[:6]
    perfect = [score_meeting(m, oracle_output(m)) for m in subset]
    empty = [score_meeting(m, {"decisions": []}) for m in subset]
    result = paired_bootstrap(perfect, empty, "decision_f1", n_resamples=200)
    assert result["diff"] == 1.0 and result["ci_low"] > 0 and result["p"] == 0.0
    assert holm({"a": 0.01, "b": 0.04, "c": 0.03}) == {"a": True, "c": False, "b": False}
