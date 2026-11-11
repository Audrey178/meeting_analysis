"""Kiểm trường hợp lượt chốt không tự là lời chốt đúng nội dung: khi đó lượt này được xét như lượt
tiếp nhận một đề xuất nêu trước đó, cả khi biết và không biết người chủ trì. Lượt nói mà agent đã
ghi không bao giờ bị đổi. Bộ phân loại được giả lập trả kết quả cố định, nên các ca chỉ kiểm luật.
"""

from __future__ import annotations

from ...utils.contracts import SpeakerTurn
from ..shared.meeting_inputs.attendees import MeetingChair
from ..shared.schemas import ActionItemCandidate, DecisionCandidate
from ..step5_verify.check.rules import check_evidence
from ..shared.judges.turn_act import (
    ClaimSupportJudgement,
    ProposalResponseJudgement,
    TurnActJudgement,
)


def _turn(turn_id: str, speaker: str, text: str = "...") -> SpeakerTurn:
    return SpeakerTurn(turn_id, speaker, text, None, None)


class ScriptedJudge:
    """Decisions API giả: hành động lời nói, lượt chốt khớp nội dung và phản hồi, đều theo turn_id."""

    def __init__(self, acts: dict[str, str], supports: set[str] = frozenset(), responses: dict[str, str] | None = None):
        self.acts = acts
        self.supports = supports
        self.responses = responses or {}
        self.response_calls: list[str] = []

    def judge(self, turn, context):
        label = self.acts.get(turn.turn_id, "discussion")
        return TurnActJudgement(label=label, probabilities={label: 0.95, "other": 0.05})

    def judge_claim(self, claim, turn, evidence):
        label = "direct" if turn.turn_id in self.supports else "unsupported"
        return ClaimSupportJudgement(label=label, probabilities={label: 0.9, "ambiguous": 0.1})

    def judge_response(self, claim, proposal, response):
        self.response_calls.append(response.turn_id)
        label = self.responses.get(response.turn_id, "no_response")
        return ProposalResponseJudgement(label=label, probabilities={label: 0.9, "no_response": 0.1})


def _decision(
    confirm: str, evidence: tuple[str, ...], status: str = "agreed", request: str | None = "T1"
) -> DecisionCandidate:
    """Kết luận agent khai: lượt nêu ``request`` (mặc định T1, của Anh A), lượt chốt ``confirm``."""

    return DecisionCandidate(
        segment_id="S0", text="Đề án cần xem lại tên gọi", evidence_turn_ids=evidence,
        quotes=tuple("..." for _ in evidence), status=status, confirm_turn_id=confirm, request_turn_id=request,
    )


# ----- Lượt chốt tự nó là lời chốt đúng nội dung: không hỏi tiếp nhận -----

CLOSED = (_turn("T1", "Anh A"), _turn("T2", "Anh A"), _turn("T3", "Anh C"))


def test_closing_turn_that_itself_closes_the_content_needs_no_acceptance() -> None:
    # Người nêu tự chốt lại ở lượt tổng kết sau (chủ trì giao rồi tự chốt): lượt nêu khác lượt chốt, cùng người.
    judge = ScriptedJudge({"T1": "proposal", "T2": "conclusion"}, supports={"T2"})

    flag = check_evidence(_decision("T2", ("T1", "T2")), CLOSED, judge, MeetingChair("", "Anh C"))

    assert (flag.verdict, flag.reasons) == ("clear", ())
    assert judge.response_calls == []


# ----- Lượt chốt agent khai không tự là lời chốt: kiểm nó có tiếp nhận lượt nêu không -----

# A nêu ý ở T1; T2 là lời tổng kết chung "lưu ý các ý kiến" (không khớp riêng ý này).
OPEN = (_turn("T1", "Anh A"), _turn("T2", "Anh B"), _turn("T3", "Anh C"))
OPEN_ACTS = {"T1": "proposal", "T2": "conclusion"}


def test_declared_acceptance_by_another_speaker_is_clear_without_chair() -> None:
    judge = ScriptedJudge(OPEN_ACTS, responses={"T2": "general_acceptance"})

    flag = check_evidence(_decision("T2", ("T1", "T2"), status="proposed"), OPEN, judge)

    assert (flag.verdict, flag.reasons) == ("clear", ())


def test_accepted_member_request_is_clear_without_editing_its_status() -> None:
    judge = ScriptedJudge(OPEN_ACTS, responses={"T2": "direct_acceptance"})
    action = ActionItemCandidate(
        segment_id="S0", actor="Anh B", text="Xem lại tên đề án", evidence_turn_ids=("T1", "T2"),
        quotes=("...", "..."), status="proposed", confirm_turn_id="T2", request_turn_id="T1",
    )

    flag = check_evidence(action, OPEN, judge)

    # Evidence check chỉ gắn nhãn: trạng thái agent khai không bị đổi.
    assert flag.verdict == "clear" and action.status == "proposed"


def test_acceptance_is_not_searched_for_when_agent_declares_the_proposal_turn() -> None:
    # T2 có tiếp nhận, nhưng agent khai lượt chốt là T1 (lượt nêu): JEV không tự tìm lượt khác.
    judge = ScriptedJudge(OPEN_ACTS, responses={"T2": "direct_acceptance"})

    flag = check_evidence(_decision("T1", ("T1",)), OPEN, judge)

    assert flag.verdict == "uncertain" and judge.response_calls == []


def test_declared_acceptance_must_come_from_the_given_chair() -> None:
    judge = ScriptedJudge(OPEN_ACTS, responses={"T2": "general_acceptance"})

    flag = check_evidence(_decision("T2", ("T1", "T2")), OPEN, judge, MeetingChair("", "Anh C"))

    assert flag.verdict == "uncertain"
    assert any("không phải lượt sau của người chủ trì" in reason for reason in flag.reasons)


def test_own_later_turn_does_not_accept_own_proposal() -> None:
    turns = (_turn("T1", "Anh A"), _turn("T2", "Anh A"))
    judge = ScriptedJudge(OPEN_ACTS, responses={"T2": "direct_acceptance"})

    flag = check_evidence(_decision("T2", ("T1", "T2")), turns, judge)

    assert flag.verdict == "uncertain" and any("người khác người nêu" in reason for reason in flag.reasons)


def test_same_speaker_id_counts_as_the_same_person() -> None:
    turns = (
        SpeakerTurn("T1", "Anh A", "...", None, None, speaker_id="u-a"),
        SpeakerTurn("T2", "Đ/c Nguyễn Văn A", "...", None, None, speaker_id="u-a"),
    )
    judge = ScriptedJudge(OPEN_ACTS, responses={"T2": "direct_acceptance"})

    assert check_evidence(_decision("T2", ("T1", "T2")), turns, judge).verdict == "uncertain"


def test_declared_acceptance_turn_that_rejects_is_flagged() -> None:
    judge = ScriptedJudge({"T1": "proposal", "T2": "rejection"}, responses={"T2": "rejection"})

    flag = check_evidence(_decision("T2", ("T1", "T2")), OPEN, judge)

    assert flag.verdict == "uncertain" and any("bác nội dung nêu ở lượt T1" in reason for reason in flag.reasons)


def test_acceptance_with_modification_goes_to_verifier_with_only_the_modification_reason() -> None:
    judge = ScriptedJudge(OPEN_ACTS, responses={"T2": "modification"})

    flag = check_evidence(_decision("T2", ("T1", "T2"), status="proposed"), OPEN, judge)

    assert flag.verdict == "uncertain" and len(flag.reasons) == 1
    assert "đổi nội dung/phạm vi so với lượt nêu T1" in flag.reasons[0]


def test_judge_without_response_question_keeps_single_turn_rules() -> None:
    class ClaimOnlyJudge:
        def judge(self, turn, context):
            return TurnActJudgement(label="proposal", probabilities={"proposal": 0.95})

        def judge_claim(self, claim, turn, evidence):
            return ClaimSupportJudgement(label="unsupported", probabilities={"unsupported": 1.0})

    action = ActionItemCandidate(
        segment_id="S0", actor="Anh B", text="Xem lại tên đề án", evidence_turn_ids=("T1", "T2"),
        quotes=("...", "..."), status="proposed", confirm_turn_id="T2", request_turn_id="T1",
    )
    flag = check_evidence(action, OPEN, ClaimOnlyJudge())

    assert flag.verdict == "uncertain"
