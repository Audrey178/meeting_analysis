"""Test phần hạn chót của ``action_agent``: ngày họp vào prompt, LLM quy hạn theo
QUY TẮC CHUẨN HOÁ HẠN, luật ``normalize_deadline`` làm dự phòng, bỏ hạn lặp trong text."""

from __future__ import annotations

from src.agentic.nodes.action_agent import (
    ACTION_SYSTEM_PROMPT,
    _strip_deadline_echo,
    make_action_agent,
)
from src.utils.contracts import SpeakerTurn

TURNS = (SpeakerTurn("T1", "Anh Tuấn", "Thiện làm phần Billing, khoảng 3 tuần nhé.", (), None, None),)


class _ScriptedLLM:
    def __init__(self, item: dict):
        self.item = item
        self.user_prompts: list[str] = []

    def generate_json(self, *, system_prompt, user_prompt, schema):
        self.user_prompts.append(user_prompt)
        base = {"evidence_turn_ids": ["T1"], "confirm_turn_id": "T1", "status": "assigned",
                "actor": "Thiện", "text": "Làm phần Billing"}
        return {"action_items": [{**base, **self.item}]}


def _run(item: dict, meeting_date: str | None = "2026-10-08"):
    llm = _ScriptedLLM(item)
    task = {"segment_id": "S1", "title": "", "summary": "", "turns": TURNS,
            "previous_context": "", "meeting_date": meeting_date}
    (candidate,) = make_action_agent(llm)(task)["action_item_candidates_raw"]
    return candidate, llm.user_prompts[0]


def test_meeting_date_and_rules_are_in_prompt():
    _, prompt = _run({"deadline": None, "deadline_date": None, "deadline_kind": "unknown"})

    assert "Ngày họp: 2026-10-08 (thứ Năm)" in prompt
    assert "QUY TẮC CHUẨN HOÁ HẠN" in ACTION_SYSTEM_PROMPT


def test_missing_meeting_date_is_marked_unknown_in_prompt():
    _, prompt = _run({"deadline": None, "deadline_date": None, "deadline_kind": "unknown"}, meeting_date=None)

    assert "Ngày họp: (không rõ)" in prompt


def test_llm_resolved_deadline_is_kept():
    candidate, _ = _run({"deadline": "khoảng 3 tuần", "deadline_date": "2026-10-29", "deadline_kind": "relative"})

    assert (candidate.deadline_raw, candidate.deadline_date, candidate.deadline_kind) == (
        "khoảng 3 tuần", "2026-10-29", "relative",
    )


def test_invalid_llm_date_falls_back_to_rules():
    candidate, _ = _run({"deadline": "trước 25/11", "deadline_date": "25/11/2026", "deadline_kind": "before"})

    assert (candidate.deadline_date, candidate.deadline_kind) == ("2026-11-25", "before")


def test_llm_without_deadline_fields_falls_back_to_rules():
    candidate, _ = _run({"deadline": "sang tuần"})

    assert (candidate.deadline_date, candidate.deadline_kind) == ("2026-10-18", "relative")


def test_no_raw_deadline_ignores_llm_date():
    candidate, _ = _run({"deadline": None, "deadline_date": "2026-10-29", "deadline_kind": "relative"})

    assert (candidate.deadline_date, candidate.deadline_kind) == (None, "unknown")


def test_deadline_echo_is_stripped_from_text():
    text = "Làm phần Billing và Payment (cẩn thận vì phức tạp) (hạn: khoảng 3 tuần)"

    assert _strip_deadline_echo(text, "khoảng 3 tuần") == "Làm phần Billing và Payment (cẩn thận vì phức tạp)"
    assert _strip_deadline_echo("Làm phần A, hạn: tuần sau", "tuần sau") == "Làm phần A"
    assert _strip_deadline_echo("Rà soát quy trình (hạn chế lỗi)", "tuần sau") == "Rà soát quy trình (hạn chế lỗi)"
    assert _strip_deadline_echo("Làm phần A (hạn: tuần sau)", None) == "Làm phần A (hạn: tuần sau)"
