"""Kiểm việc phân loại chắc chắn/nghi ngờ khi có bộ phân loại lượt chốt theo nghĩa.

Bộ phân loại được giả lập trả kết quả cố định, nên các ca chỉ kiểm: luật chia ba vùng chắc/không
chắc, ngữ cảnh đưa vào bộ phân loại, việc gửi agent kiểm chứng khi thiếu hoặc lỗi bộ phân loại, và
phần kết nối tới dịch vụ (giả lập, không gọi mạng).
"""

from __future__ import annotations

from types import SimpleNamespace

from ...utils.contracts import SpeakerTurn
from ..shared.schemas import ActionItemCandidate, DecisionCandidate
from ..step5_verify.check.rules import (
    check_evidence,
)
from ..shared.judges.turn_act import (
    MAX_TURN_CHARS,
    ClaimSupportJudgement,
    DecisionsApiTurnActJudge,
    TurnActJudgement,
    claim_support_is_clear,
    render_claim_support_input,
    render_turn_act_input,
)


def _turn(turn_id: str, speaker: str, text: str) -> SpeakerTurn:
    return SpeakerTurn(turn_id, speaker, text, None, None)


def _flag(item, turns, **kwargs):
    return check_evidence(item, turns, **kwargs)


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
    "T2": {"assignment": 0.97, "proposal": 0.02, "discussion": 0.01},
    "T3": {"assignment": 0.27, "conclusion": 0.06, "proposal": 0.24, "discussion": 0.32, "other": 0.11},
    "T4": {"discussion": 0.96, "assignment": 0.02, "conclusion": 0.02},
})


def _action(confirm_turn_id: str) -> ActionItemCandidate:
    return ActionItemCandidate(
        segment_id="S0", actor="Hùng", text="Làm TAT", evidence_turn_ids=(confirm_turn_id,), quotes=(),
        deadline_raw=None, status="assigned", confirm_turn_id=confirm_turn_id,
    )


def _decision(confirm_turn_id: str, text: str = "Làm TAT") -> DecisionCandidate:
    return DecisionCandidate(
        segment_id="S0", text=text, evidence_turn_ids=(confirm_turn_id,), quotes=(),
        status="agreed", confirm_turn_id=confirm_turn_id,
    )


def test_colloquial_assignment_is_clear_with_judge() -> None:
    assert _flag(_action("T2"), TURNS, judge=JUDGE).verdict == "clear"


def test_without_judge_confirm_turn_goes_to_verifier() -> None:
    for flag in (_flag(_action("T2"), TURNS), _flag(_decision("T2"), TURNS)):
        assert flag.verdict == "uncertain"
        assert any("Chưa xét được lượt chốt T2" in reason for reason in flag.reasons)


def test_ambiguous_turn_is_flagged_with_distribution() -> None:
    flag = _flag(_action("T3"), TURNS, judge=JUDGE)
    assert flag.verdict == "uncertain"
    assert any("chưa chắc" in reason and "p_chốt=0.33" in reason for reason in flag.reasons)


def test_non_commit_turn_is_flagged() -> None:
    flag = _flag(_action("T4"), TURNS, judge=JUDGE)
    assert flag.verdict == "uncertain"
    assert any("'discussion'" in reason for reason in flag.reasons)


def test_judge_receives_preceding_turns_as_context() -> None:
    judge = FakeJudge(JUDGE.probs_by_turn)
    _flag(_action("T3"), TURNS, judge=judge)
    assert judge.calls == [("T3", ("T1", "T2"))]


def test_judge_failure_goes_to_verifier() -> None:
    flag = _flag(_action("T2"), TURNS, judge=FakeJudge({}, fail=True))
    assert flag.verdict == "uncertain"
    assert any("Chưa xét được lượt chốt T2" in reason for reason in flag.reasons)


def test_decision_hedge_words_in_text_do_not_flag_when_judged() -> None:
    item = _decision("T2", text="Làm TAT trước, có thể nâng cấp sau")
    assert _flag(item, TURNS, judge=JUDGE).verdict == "clear"


def test_decisions_judge_parses_answer_and_caches() -> None:
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        answer = SimpleNamespace(
            type="choice", choice="assignment",
            probabilities=[SimpleNamespace(value="assignment", probability=0.9),
                           SimpleNamespace(value="proposal", probability=0.1)],
        )
        return SimpleNamespace(answers=[answer])

    judge = DecisionsApiTurnActJudge(SimpleNamespace(decisions=SimpleNamespace(create=create)), model="m")
    first = judge.judge(TURNS[1], TURNS[:1])
    second = judge.judge(TURNS[1], TURNS[:1])
    assert first == second and first.label == "assignment" and abs(first.p_commit - 0.9) < 1e-9
    assert len(calls) == 1
    assert calls[0]["model"] == "m"
    assert calls[0]["input"] == render_turn_act_input(TURNS[1], TURNS[:1])
    assert "LƯỢT CẦN XÉT:\nAnh Sơn: Thế thì cứ làm" in calls[0]["input"]


def test_decisions_judge_checks_claim_content_and_caches_separately() -> None:
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        answer = SimpleNamespace(
            type="choice", choice="unsupported",
            probabilities=[SimpleNamespace(value="unsupported", probability=0.94),
                           SimpleNamespace(value="direct", probability=0.06)],
        )
        return SimpleNamespace(answers=[answer])

    judge = DecisionsApiTurnActJudge(SimpleNamespace(decisions=SimpleNamespace(create=create)), model="m")
    evidence = (TURNS[0], TURNS[1])
    first = judge.judge_claim("Lấy ý kiến chuyên gia", TURNS[1], evidence)
    second = judge.judge_claim("Lấy ý kiến chuyên gia", TURNS[1], evidence)

    assert first == second and first.label == "unsupported" and abs(first.p_support - 0.06) < 1e-9
    assert len(calls) == 1
    assert calls[0]["questions"][0]["name"] == "claim_support"
    assert calls[0]["input"] == render_claim_support_input("Lấy ý kiến chuyên gia", TURNS[1], evidence)
    assert "NỘI DUNG VIỆC CẦN KIỂM:\nLấy ý kiến chuyên gia" in calls[0]["input"]


def test_claim_support_has_clear_reference_and_verifier_gray_zone() -> None:
    referenced = ClaimSupportJudgement(
        "accepted_reference", {"accepted_reference": 0.61, "ambiguous": 0.30, "unsupported": 0.09}
    )
    gray = ClaimSupportJudgement("direct", {"direct": 0.79, "unsupported": 0.21})

    assert claim_support_is_clear(referenced)
    assert not claim_support_is_clear(gray)


def test_action_accepted_by_reference_at_point_six_is_clear() -> None:
    class ReferenceJudge(FakeJudge):
        def judge_claim(self, claim, turn, evidence):
            probabilities = {"accepted_reference": 0.61, "ambiguous": 0.31, "unsupported": 0.08}
            return ClaimSupportJudgement("accepted_reference", probabilities)

    judge = ReferenceJudge(JUDGE.probs_by_turn)

    assert _flag(_action("T2"), TURNS, judge=judge).verdict == "clear"


class ClaimAwareJudge(FakeJudge):
    """Lượt vẫn là giao việc, nhưng chỉ khớp candidate TAT."""

    def judge_claim(self, claim, turn, evidence):
        supported = "TAT" in claim and "TAT" in turn.text_exact
        probs = {"direct": 0.96, "unsupported": 0.04} if supported else {
            "unsupported": 0.96, "direct": 0.04
        }
        return ClaimSupportJudgement(max(probs, key=probs.get), probs)


def test_commit_turn_for_different_work_is_not_clear() -> None:
    judge = ClaimAwareJudge(JUDGE.probs_by_turn)
    item = ActionItemCandidate(
        segment_id="S0", actor="Hùng", text="Lấy ý kiến chuyên gia", evidence_turn_ids=("T2",), quotes=(),
        deadline_raw=None, status="assigned", confirm_turn_id="T2",
    )

    flag = _flag(item, TURNS, judge=judge)

    assert flag.verdict == "uncertain"
    assert any("không xác nhận đúng nội dung" in reason and "p_khớp=0.04" in reason for reason in flag.reasons)


def test_decision_at_a_commit_turn_that_does_not_say_it_is_not_clear() -> None:
    judge = ClaimAwareJudge(JUDGE.probs_by_turn)

    def decision(text):
        return DecisionCandidate(
            segment_id="S0", text=text, evidence_turn_ids=("T2",), quotes=(), status="agreed", confirm_turn_id="T2",
        )

    flag = _flag(decision("Đề án cần lấy ý kiến chuyên gia"), TURNS, judge=judge)

    assert flag.verdict == "uncertain"
    assert any("không xác nhận đúng nội dung" in reason for reason in flag.reasons)
    assert _flag(decision("Dùng TAT cho đợt này"), TURNS, judge=judge).verdict == "clear"


class TextJudge:
    """Judge giả chấm theo NỘI DUNG đoạn: đoạn có "giao Hùng" là giao việc."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def judge(self, turn, context):
        self.texts.append(turn.text_exact)
        if "giao Hùng" in turn.text_exact:
            return TurnActJudgement("assignment", {"assignment": 0.95, "discussion": 0.05})
        return TurnActJudgement("discussion", {"discussion": 0.95, "assignment": 0.05})


def test_long_confirm_turn_is_judged_by_windows() -> None:
    # Câu giao việc nằm sau MAX_TURN_CHARS: cắt cụt thì judge không thấy nó.
    long_turn = _turn("T5", "Anh Sơn", "Báo cáo tình hình dự án. " * 150 + "Thống nhất giao Hùng làm TAT.")
    judge = TextJudge()
    assert _flag(_action("T5"), (*TURNS, long_turn), judge=judge).verdict == "clear"
    assert len(judge.texts) > 1 and all(len(text) <= MAX_TURN_CHARS for text in judge.texts)


def test_long_context_turn_is_sent_whole() -> None:
    # Lượt ngữ cảnh dài hơn MAX_TURN_CHARS vẫn gửi nguyên văn (không rút gọn), cả đầu lẫn cuối.
    long_context = _turn("T0", "Anh Sơn", "ĐẦU LƯỢT. " + "Bàn về TAT. " * 300 + "CUỐI LƯỢT.")
    text = render_turn_act_input(TURNS[1], (long_context,))
    assert len(long_context.text_exact) > MAX_TURN_CHARS
    assert f"Anh Sơn: {long_context.text_exact}\n" in text
