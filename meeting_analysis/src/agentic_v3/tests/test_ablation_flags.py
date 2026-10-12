"""Hai núm ablation của ``evidence_check``: ``V3Config.evidence_check`` và ``verifier_mode``."""

from __future__ import annotations

import pytest

from src.agentic_v3 import V3Config
from src.agentic_v3.core.schemas import ActionItemCandidate, DecisionCandidate
from src.agentic_v3.graph.topic import evidence_check
from src.agentic_v3.schemas import SpeakerRegistry
from src.utils.contracts import SpeakerTurn, TopicSegment

_TURNS = (
    SpeakerTurn("TURN_000001", "Anh Kiên", "Nam làm API thanh toán trước thứ Sáu nhé.", ("i1",), None, None),
    SpeakerTurn("TURN_000002", "Nam", "Dạ em nhận.", ("i2",), None, None),
    SpeakerTurn("TURN_000003", "Lan", "Hay là mình thử đổi sang cổng khác?", ("i3",), None, None),
)


def _state() -> dict:
    return {
        "segment": TopicSegment("TOPIC_SEG_000000", atom_ids=tuple(t.turn_id for t in _TURNS)),
        "turns": _TURNS,
        "meeting_turns": _TURNS,
        "registry": SpeakerRegistry(names=("Anh Kiên", "Nam", "Lan")),
        "action_candidates_raw": [
            ActionItemCandidate("TOPIC_SEG_000000", "Nam", "Làm API thanh toán", ("TURN_000001", "TURN_000002"),
                                ("", ""), deadline_raw="thứ Sáu"),
            ActionItemCandidate("TOPIC_SEG_000000", "Bình", "Đổi cổng thanh toán", ("TURN_000003",), ("",)),
        ],
        "decision_candidates_raw": [
            DecisionCandidate("TOPIC_SEG_000000", "Đổi sang cổng khác", ("TURN_000003",), ("",)),
        ],
        "progress_updates_raw": [],
    }


def _count(result: dict) -> tuple[int, int, int]:
    return len(result["verified_assignments"]), len(result["verified_decisions"]), len(result["pending_verify"])


def test_evidence_check_off_sends_every_candidate_to_verifier():
    result = evidence_check(_state(), v3_config=V3Config(evidence_check=False))
    assert _count(result) == (0, 0, 3)
    assert all("ablation" in task["reasons"][0] for task in result["pending_verify"])


@pytest.mark.parametrize("evidence_on", [True, False])
def test_keep_and_drop_uncertain_never_reach_verifier(evidence_on):
    on = evidence_check(_state(), v3_config=V3Config(evidence_check=evidence_on))
    keep = evidence_check(_state(), v3_config=V3Config(evidence_check=evidence_on, verifier_mode="keep_uncertain"))
    drop = evidence_check(_state(), v3_config=V3Config(evidence_check=evidence_on, verifier_mode="drop_uncertain"))

    assert keep["pending_verify"] == drop["pending_verify"] == ()
    assert _count(keep)[:2] == (2, 1)  # giữ hết: CLEAR + UNCERTAIN
    assert _count(drop)[:2] == _count(on)[:2]  # bỏ hết: chỉ còn phần CLEAR như production


def test_invalid_verifier_mode_rejected():
    with pytest.raises(ValueError):
        V3Config(verifier_mode="maybe")
