"""Kiểm phần hạn chót của agent giao việc: ngày họp được đưa vào prompt, hạn tính bằng luật được ưu
tiên, ngày do mô hình tự tính chỉ dùng khi luật không ra kết quả, và hạn bị lặp trong câu việc giao
được bỏ đi.
"""

from __future__ import annotations

from ...utils.contracts import SpeakerTurn
from ..shared.prompts import ACTION_SYSTEM_PROMPT
from ..step4_extract.action import run_action_agent

TURNS = (SpeakerTurn("T1", "Anh Tuấn", "Thiện làm phần Billing, khoảng 3 tuần nhé.", None, None),)


class _ScriptedLLM:
    def __init__(self, item: dict):
        self.item = item
        self.user_prompts: list[str] = []

    def generate_json(self, *, system_prompt, user_prompt, schema):
        self.user_prompts.append(user_prompt)
        base = {"evidence_segment_ids": ["T1"], "confirm_turn_id": "T1", "status": "assigned",
                "actor": "Thiện", "text": "Làm phần Billing"}
        return {"action_items": [{**base, **self.item}]}


def _run(item: dict, meeting_date: str | None = "2026-10-08"):
    llm = _ScriptedLLM(item)
    task = {"segment_id": "S1", "title": "", "summary": "", "turns": TURNS,
            "meeting_context": "", "meeting_date": meeting_date}
    (candidate,) = run_action_agent(llm, ACTION_SYSTEM_PROMPT, task)["action_item_candidates_raw"]
    return candidate, llm.user_prompts[0]


def test_meeting_date_and_rules_are_in_prompt():
    _, prompt = _run({"deadline": None, "deadline_date": None, "deadline_kind": "unknown"})

    assert "Meeting date: 2026-10-08 (thứ Năm)" in prompt
    assert "DEADLINE NORMALIZATION RULES" in ACTION_SYSTEM_PROMPT


def test_missing_meeting_date_is_marked_unknown_in_prompt():
    _, prompt = _run({"deadline": None, "deadline_date": None, "deadline_kind": "unknown"}, meeting_date=None)

    assert "Meeting date: (unknown)" in prompt


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


def test_text_is_kept_as_the_model_wrote_it():
    # Không còn luật cắt đuôi "(hạn: ...)" hay tiền tố "giao <actor>": prompt/schema lo việc đó.
    candidate, _ = _run({"text": "Giao Thiện làm phần Billing (hạn: khoảng 3 tuần)", "deadline": "khoảng 3 tuần"})

    assert candidate.text == "Giao Thiện làm phần Billing (hạn: khoảng 3 tuần)"
