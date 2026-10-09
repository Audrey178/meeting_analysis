"""Unit test cho evidence-check khi có ``TurnActJudge`` (xét lượt chốt theo nghĩa).

Judge giả trả phân bố xác suất cố định theo turn_id, nên test chỉ kiểm luật ba vùng,
ngữ cảnh truyền vào judge, đường quay về luật từ khoá khi judge lỗi và
``DecisionsTurnActJudge`` (client giả, không gọi mạng).
"""

from __future__ import annotations

from types import SimpleNamespace

from src.agentic._shared import check_action_evidence, check_decision_evidence
from src.agentic.schemas import ActionItemCandidate, DecisionCandidate
from src.agentic.turn_act import DecisionsTurnActJudge, TurnActJudgement, render_turn_act_input
from src.utils.contracts import SpeakerTurn


def _turn(turn_id: str, speaker: str, text: str) -> SpeakerTurn:
    return SpeakerTurn(turn_id, speaker, text, (), None, None)


TURNS = (
    _turn("T1", "Anh Sơn", "Cái TAT này quan trọng đấy."),
    _turn("T2", "Anh Sơn", "Thế thì cứ làm cái TAT này nhá, Hùng cho anh khoảng 2 đến 3 tuần đi."),
    _turn("T3", "Hùng", "Bản word hay là bản pdf cái gì cũng được ạ?"),
    _turn("T4", "Anh Sơn", "Không, không để em trình bày một cái."),
)


class FakeJudge:
    def __init__(self, probs_by_turn: dict[str, dict[str, float]], fail: bool = False) -> None:
        self.probs_by_turn = probs_by_turn
        self.fail = fail
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def judge(self, turn, context):
        self.calls.append((turn.turn_id, tuple(t.turn_id for t in context)))
        if self.fail:
            raise TimeoutError("decisions timeout")
        probs = self.probs_by_turn[turn.turn_id]
        return TurnActJudgement(max(probs, key=probs.get), probs)


JUDGE = FakeJudge({
    "T2": {"giao_viec": 0.97, "de_xuat": 0.02, "thao_luan": 0.01},
    "T3": {"giao_viec": 0.27, "ket_luan": 0.06, "de_xuat": 0.24, "thao_luan": 0.32, "khac": 0.11},
    "T4": {"thao_luan": 0.96, "giao_viec": 0.02, "ket_luan": 0.02},
})


def _action(confirm_turn_id: str) -> ActionItemCandidate:
    return ActionItemCandidate(
        segment_id="S0", actor="Hùng", text="Làm TAT", evidence_ids=(confirm_turn_id,), quotes=(),
        deadline_raw=None, status="assigned", confirm_turn_id=confirm_turn_id,
    )


def _decision(confirm_turn_id: str, text: str = "Làm TAT") -> DecisionCandidate:
    return DecisionCandidate(
        segment_id="S0", text=text, evidence_ids=(confirm_turn_id,), quotes=(),
        status="agreed", confirm_turn_id=confirm_turn_id,
    )


def test_colloquial_assignment_is_clear_with_judge_but_not_with_cues() -> None:
    assert check_action_evidence(_action("T2"), TURNS).verdict == "uncertain"
    assert check_action_evidence(_action("T2"), TURNS, judge=JUDGE).verdict == "clear"


def test_ambiguous_turn_is_flagged_with_distribution() -> None:
    flag = check_action_evidence(_action("T3"), TURNS, judge=JUDGE)
    assert flag.verdict == "uncertain"
    assert any("chưa rõ" in reason and "p_chốt=0.33" in reason for reason in flag.reasons)


def test_non_commit_turn_is_flagged_even_if_cue_matches() -> None:
    # "để em" khớp _COMMIT_CUES nên luật từ khoá coi là CLEAR; judge thì không.
    assert check_action_evidence(_action("T4"), TURNS).verdict == "clear"
    flag = check_action_evidence(_action("T4"), TURNS, judge=JUDGE)
    assert flag.verdict == "uncertain"
    assert any("'thao_luan'" in reason for reason in flag.reasons)


def test_judge_receives_preceding_turns_as_context() -> None:
    judge = FakeJudge(JUDGE.probs_by_turn)
    check_action_evidence(_action("T3"), TURNS, judge=judge)
    assert judge.calls == [("T3", ("T1", "T2"))]


def test_judge_failure_falls_back_to_cues() -> None:
    judge = FakeJudge({}, fail=True)
    assert check_action_evidence(_action("T4"), TURNS, judge=judge).verdict == "clear"
    assert check_action_evidence(_action("T2"), TURNS, judge=judge).verdict == "uncertain"


def test_decision_hedge_cue_in_text_ignored_when_judged() -> None:
    item = _decision("T2", text="Làm TAT trước, có thể nâng cấp sau")
    assert check_decision_evidence(item, TURNS).verdict == "uncertain"
    assert check_decision_evidence(item, TURNS, judge=JUDGE).verdict == "clear"


def test_decisions_judge_parses_answer_and_caches() -> None:
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        answer = SimpleNamespace(
            type="choice", choice="giao_viec",
            probabilities=[SimpleNamespace(value="giao_viec", probability=0.9),
                           SimpleNamespace(value="de_xuat", probability=0.1)],
        )
        return SimpleNamespace(answers=[answer])

    judge = DecisionsTurnActJudge(SimpleNamespace(decisions=SimpleNamespace(create=create)), model="m")
    first = judge.judge(TURNS[1], TURNS[:1])
    second = judge.judge(TURNS[1], TURNS[:1])
    assert first == second and first.label == "giao_viec" and abs(first.p_commit - 0.9) < 1e-9
    assert len(calls) == 1
    assert calls[0]["model"] == "m"
    assert calls[0]["input"] == render_turn_act_input(TURNS[1], TURNS[:1])
    assert "LƯỢT CẦN XÉT:\nAnh Sơn: Thế thì cứ làm" in calls[0]["input"]
