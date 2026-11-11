"""Kiểm trọn luồng bước 4-6 với mô hình giả (không gọi mạng).

Gồm: dựng danh bạ cả cuộc họp, mọi agent chạy ở mọi chủ đề, công cụ tra cứu của agent kiểm chứng,
các chủ đề chạy song song mà không vượt giới hạn số lời gọi, agent kiểm chứng tra cứu rồi kết luận,
vòng trao đổi giữa hai agent tới khi thống nhất, thử lại khi lỗi, và thứ tự kết quả.
"""

from __future__ import annotations

import threading
import time

import pytest

from ...utils.contracts import SpeakerTurn, TopicLabel, TopicSegment
from ...utils.ports import LLMUpstreamError
from ..config import AnalysisConfig
from ..run import MeetingAnalyzer
from ..shared import prompts
from ..shared.meeting_inputs.agenda import parse_task_agenda
from ..shared.meeting_inputs.attendees import AttendeePerson, AttendeeRoster, MeetingChair, parse_meeting_chair
from ..shared.schemas import SpeakerRegistry
from ..step4_extract.action import (
    BASIS_STATUS,
    NOT_ASSIGNMENT_BASES,
    run_action_agent,
)
from ..step4_extract.decision import run_decision_agent
from ..step4_extract.registry import build_speaker_registry
from ..step5_verify.verifier.tools import MeetingTools
from ..shared.judges.turn_act import ClaimSupportJudgement, DecisionRelationJudgement, TurnActJudgement
from ..step5_verify.verifier.verifier import VERIFIER_SCHEMA


def _turn(turn_id: str, speaker: str, text: str) -> SpeakerTurn:
    return SpeakerTurn(turn_id, speaker, text, None, None)


TURNS = (
    _turn("T1", "Anh Tuấn", "Chốt lại, giao Hiếu map lại nhãn sang 12 lĩnh vực, trước ngày 25/11."),
    _turn("T2", "Hiếu", "Dạ em nhận."),
    _turn("T3", "Chị Mai", "Em đề xuất có thể tự động mở lại phản ánh khi người dân không hài lòng."),
    _turn("T4", "Anh Tuấn", "Để tính sau."),
    _turn("T5", "Anh Phong", "Tiến độ hiện đạt khoảng 55% khối lượng."),
    _turn("T6", "Anh Tuấn", "Cảm ơn anh Phong."),
)


def _segment(segment_id: str, turn_ids: tuple[str, ...]) -> TopicSegment:
    by_id = {turn.turn_id: turn for turn in TURNS}
    return TopicSegment(
        segment_id=segment_id,
        turn_ids=turn_ids,
        text="\n".join(f"{by_id[t].speaker}: {by_id[t].text_exact}" for t in turn_ids),
    )


SEGMENTS = (
    _segment("S1", ("T1", "T2")),
    _segment("S2", ("T3", "T4")),
    _segment("S3", ("T5", "T6")),
)

PROPOSAL_TEXT = "Tự động mở lại phản ánh khi người dân không hài lòng"


class FakeLLM:
    """LLM giả: trả lời theo loại agent (nhận ra qua schema/system prompt).

    Đếm số lời gọi đang chạy cùng lúc để kiểm tính song song và giới hạn của gate.

    Đầu vào khi tạo:
        delay: số giây mỗi lời gọi "chạy".
        verifier_script: list câu trả lời lần lượt cho Verifier (phần tử là exception thì raise).
        proposer_script: list câu trả lời lần lượt của agent trích xuất cho feedback;
            hết script thì trả "accept".
        fail_action_once: True thì lời gọi Action đầu tiên raise ``LLMUpstreamError``.
    """

    def __init__(self, delay: float = 0.0, verifier_script=None, proposer_script=None, fail_action_once: bool = False):
        self.delay = delay
        self.verifier_script = list(verifier_script or [])
        self.proposer_script = list(proposer_script or [])
        self.fail_action_once = fail_action_once
        self.calls: list[str] = []
        self.prompts: list[tuple[str, str, str]] = []  # (vai, system prompt, user prompt)
        self.in_flight = 0
        self.max_in_flight = 0
        self.segments_in_flight: set[str] = set()
        self.max_segments_in_flight = 0
        self._lock = threading.Lock()

    def generate_json(self, *, system_prompt, user_prompt, schema):
        kind = self._kind(system_prompt, schema)
        segment = next((s.segment_id for s in SEGMENTS if any(f"[{t}|" in user_prompt for t in s.turn_ids)), "?")
        with self._lock:
            self.calls.append(kind)
            self.prompts.append((kind, system_prompt, user_prompt))
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self.segments_in_flight.add(segment)
            self.max_segments_in_flight = max(self.max_segments_in_flight, len(self.segments_in_flight))
        try:
            time.sleep(self.delay)
            return self._answer(kind, user_prompt)
        finally:
            with self._lock:
                self.in_flight -= 1
                self.segments_in_flight.discard(segment)

    @staticmethod
    def _kind(system_prompt: str, schema: dict) -> str:
        if "stance" in schema["properties"]:
            return "proposer"
        if "KIỂM CHỨNG VIÊN" in system_prompt:
            return "verifier"
        return {"discussion_points": "content", "member_requests": "action", "updates": "action", "member_points": "decision",
                "stance": "proposer"}[
            next(iter(schema["properties"]))
        ]

    def _answer(self, kind: str, user_prompt: str) -> dict:
        if kind == "content":
            turn_id = next(t.turn_id for t in TURNS if f"[{t.turn_id}|" in user_prompt)
            return {"discussion_points": [{"evidence_segment_ids": [turn_id], "text": "Ý kiến."}]}
        if kind == "action":
            with self._lock:
                if self.fail_action_once:
                    self.fail_action_once = False
                    raise LLMUpstreamError("gateway down")
            if "[T1|" in user_prompt:
                return {"action_items": [{
                    "evidence_segment_ids": ["T1", "T2"], "confirm_turn_id": "T1", "status": "assigned",
                    "assignees": [{"name": "Hiếu", "role": "lead", "type": "person"}],
                    "text": "Map lại nhãn sang 12 lĩnh vực", "deadline": "trước ngày 25/11",
                }]}
            if "[T3|" in user_prompt:
                return {"action_items": [{
                    "evidence_segment_ids": ["T3"], "confirm_turn_id": "T3", "status": "proposed",
                    "assignees": [{"name": "Chị Mai", "role": "lead", "type": "person"}],
                    "text": PROPOSAL_TEXT, "deadline": None,
                }]}
            return {"action_items": []}
        if kind == "decision":
            return {"decisions": []}
        with self._lock:
            if kind == "proposer":
                return self.proposer_script.pop(0) if self.proposer_script else _proposer("accept")
            answer = self.verifier_script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeLabeler:
    """Adapter gán nhãn giả: tiêu đề cố định theo segment."""

    def label_topic(self, segment):
        return TopicLabel(
            segment_id=segment.segment_id,
            title=f"Bàn về nội dung {segment.segment_id}",
            summary="Tóm tắt.",
            text=segment.text or "",
            evidence_turn_ids=(),
            method="llm",
        )


def _verifier_step(action: str, argument: str | None, thought: str = "tra") -> dict:
    return {"thought": thought, "action": action, "argument": argument, "verdict": None,
            "deciding_turn_id": None, "revised_assignees": [], "reasoning": None}


def _verifier_final(verdict: str, deciding_turn_id: str | None = None, reasoning: str = "ok") -> dict:
    return {"thought": "đủ", "action": "final", "argument": None, "verdict": verdict,
            "deciding_turn_id": deciding_turn_id, "revised_assignees": [], "reasoning": reasoning}


def _proposer(stance: str, confirm_turn_id: str | None = None, text: str | None = None, actor: str | None = None,
              argument: str = "lập luận") -> dict:
    assignees = [{"name": actor, "role": "lead", "type": "person"}] if actor else []
    return {"stance": stance, "argument": argument, "confirm_turn_id": confirm_turn_id,
            "revised_text": text, "revised_assignees": assignees}


class CommitTurnJudge:
    """Decisions API giả: lượt trong ``commit_ids`` là giao việc (p_commit 0.95), còn lại là thảo luận."""

    def __init__(self, commit_ids: set[str]):
        self.commit_ids = commit_ids

    def judge(self, turn, context):
        if turn.turn_id in self.commit_ids:
            return TurnActJudgement(label="assignment", probabilities={"assignment": 0.95, "discussion": 0.05})
        return TurnActJudgement(label="discussion", probabilities={"discussion": 1.0})


class ClaimAwareCommitTurnJudge(CommitTurnJudge):
    """Ngoài loại hành vi, bắt lượt chốt phải khớp chính nội dung candidate."""

    def judge_claim(self, claim, turn, evidence):
        supported = (
            claim == "Map lại nhãn sang 12 lĩnh vực"
            and turn.turn_id == "T1"
        )
        probs = {"direct": 0.96, "unsupported": 0.04} if supported else {
            "unsupported": 0.97, "direct": 0.03
        }
        return ClaimSupportJudgement(max(probs, key=probs.get), probs)


class FixedClaimSupportJudge(CommitTurnJudge):
    def __init__(self, p_support: float):
        super().__init__({"T1", "T2"})
        self.p_support = p_support

    def judge_claim(self, claim, turn, evidence):
        probs = {"direct": self.p_support, "unsupported": 1 - self.p_support}
        return ClaimSupportJudgement(max(probs, key=probs.get), probs)


# T1 giao việc, T2 nhận việc; các lượt khác chỉ là thảo luận/báo cáo.
TURN_JUDGE = CommitTurnJudge({"T1", "T2"})


def _analyzer(
    llm: FakeLLM, config: AnalysisConfig | None = None, llm_concurrency: int = 8, turn_judge=TURN_JUDGE
) -> MeetingAnalyzer:
    return MeetingAnalyzer(
        content_llm=llm, action_llm=llm, decision_llm=llm, verifier_llm=llm,
        labeler=FakeLabeler(), config=config, llm_concurrency=llm_concurrency, turn_judge=turn_judge,
    )


def _start(analyzer: MeetingAnalyzer):
    return analyzer.analyze(meeting_id="M1", turns=TURNS, segments=SEGMENTS)


def test_planner_registry_lists_speakers_of_whole_meeting():
    assert build_speaker_registry(TURNS).names == ("Anh Tuấn", "Hiếu", "Chị Mai", "Anh Phong")


class NoCommitTurnJudge:
    """Decisions API giả xếp mọi lượt là thảo luận (p_commit = 0)."""

    def judge(self, turn, context):
        return TurnActJudgement(label="discussion", probabilities={"discussion": 1.0})


def test_action_and_decision_agents_run_on_every_topic_even_without_commit_turns():
    llm = FakeLLM(verifier_script=[_verifier_final("drop")] * 8)
    _start(_analyzer(llm, turn_judge=NoCommitTurnJudge()))

    assert [llm.calls.count(kind) for kind in ("content", "action", "decision")] == [len(SEGMENTS)] * 3


def test_tools_read_whole_meeting_and_report_errors_as_observations():
    tools = MeetingTools(TURNS, SpeakerRegistry(("Anh Tuấn", "Hiếu", "Chị Mai", "Anh Phong")))

    assert tools.run("get_turn", "[T4|Anh Tuấn]").startswith("[T4|Anh Tuấn]")
    assert "LỖI" in tools.run("get_turn", "T99")
    assert "LỖI" in tools.run("delete_turn", "T1")
    assert "[T3|" in tools.run("search_meeting", "mở lại phản ánh")
    assert "Anh Phong" in tools.run("lookup_speaker", "Phong")


def test_topics_run_in_parallel_within_gate_limit():
    # Gate rộng hơn số agent trích xuất của một chủ đề (3): lúc gate đầy, các lời gọi phải đến từ
    # >= 2 chủ đề. Gate đúng 3 thì một chủ đề có thể chiếm hết suất (semaphore không theo thứ tự).
    llm = FakeLLM(delay=0.05, verifier_script=[_verifier_final("drop")])
    result = _start(_analyzer(llm, llm_concurrency=4))

    assert result.labels
    assert llm.max_segments_in_flight > 1  # nhiều chủ đề cùng gọi LLM một lúc
    assert llm.max_in_flight <= 4  # nhưng không vượt gate


def test_verifier_uses_tool_then_drops_unaccepted_proposal():
    llm = FakeLLM(verifier_script=[_verifier_step("search_meeting", "mở lại phản ánh"), _verifier_final("drop")])
    report = _start(_analyzer(llm))

    assert [a.actor for a in report.assignments] == ["Hiếu"]
    (record,) = report.verification_records
    assert record.verdict == "drop"
    assert record.steps[0].action == "search_meeting"
    assert "[T3|" in record.steps[0].observation


def test_keep_without_deciding_turn_is_downgraded_to_drop():
    llm = FakeLLM(verifier_script=[_verifier_final("keep", deciding_turn_id=None)])
    report = _start(_analyzer(llm))

    assert all(a.text != PROPOSAL_TEXT for a in report.assignments)
    assert report.verification_records[0].verdict == "drop"


def test_verifier_keep_is_not_vetoed_by_claim_support():
    # JEV chỉ định tuyến ở evidence-check: p_khớp thấp ở lượt Verifier dẫn không hạ keep thành drop.
    llm = FakeLLM(verifier_script=[_verifier_final("keep", deciding_turn_id="T1")])
    judge = ClaimAwareCommitTurnJudge({"T1", "T2"})
    report = _start(_analyzer(llm, turn_judge=judge))

    assert any(a.text == PROPOSAL_TEXT for a in report.assignments)
    (record,) = report.verification_records
    assert record.verdict == "keep" and "không xác nhận đúng nội dung" not in record.reasoning


def test_verifier_decides_claim_support_gray_zone_instead_of_automatic_drop():
    # Cả việc rõ ở S1 và candidate đề xuất ở S2 đi Verifier vì 0.79 chưa đạt ngưỡng
    # CLEAR 0.8; verdict keep của Verifier phải thắng trong vùng xám này.
    llm = FakeLLM(verifier_script=[_verifier_final("keep", deciding_turn_id="T1")] * 2)
    report = _start(_analyzer(llm, turn_judge=FixedClaimSupportJudge(0.79)))

    assert any(a.text == PROPOSAL_TEXT for a in report.assignments)
    assert report.verification_records[0].verdict == "keep"


def test_proposer_amends_after_feedback_then_verifier_agrees():
    llm = FakeLLM(
        verifier_script=[_verifier_final("unresolved", reasoning="chưa ai giao"), _verifier_final("keep", "T4")],
        proposer_script=[_proposer("amend", "T4", text="Nghiên cứu mở lại phản ánh", actor="Anh Tuấn")],
    )
    report = _start(_analyzer(llm))

    amended = [a for a in report.assignments if a.verification == "consensus"]
    assert [(a.actor, a.text) for a in amended] == [("Anh Tuấn", "Nghiên cứu mở lại phản ánh")]
    (record,) = report.verification_records
    assert record.decided_by == "consensus" and record.verdict == "keep"
    assert [(r.verdict, r.stance) for r in record.rounds] == [("unresolved", "amend"), ("keep", "")]


def test_proposer_accepting_feedback_drops_candidate():
    llm = FakeLLM(verifier_script=[_verifier_final("drop", reasoning="chỉ là đề xuất")])
    report = _start(_analyzer(llm))

    assert all(a.text != PROPOSAL_TEXT for a in report.assignments)
    (record,) = report.verification_records
    assert record.decided_by == "consensus" and record.verdict == "drop"
    assert record.rounds[0].stance == "accept"


def test_no_consensus_falls_back_to_verifier_last_verdict():
    llm = FakeLLM(
        verifier_script=[_verifier_final("drop")] * 2,
        proposer_script=[_proposer("defend", "T4")] * 2,
    )
    report = _start(_analyzer(llm, AnalysisConfig(consensus_max_rounds=2)))

    assert all(a.text != PROPOSAL_TEXT for a in report.assignments)
    (record,) = report.verification_records
    assert record.decided_by == "verifier" and len(record.rounds) == 2
    assert llm.calls.count("verifier") == 2 and llm.calls.count("proposer") == 2


def test_no_consensus_drop_is_not_overturned_by_a_directive_turn():
    # Hết vòng Verifier vẫn bỏ; agent dẫn lượt giao việc thật (T1) cũng không lật được kết luận Verifier.
    llm = FakeLLM(
        verifier_script=[_verifier_final("drop")] * 2,
        proposer_script=[_proposer("defend", "T1")] * 2,
    )
    report = _start(_analyzer(llm, AnalysisConfig(consensus_max_rounds=2)))

    assert all(a.text != PROPOSAL_TEXT for a in report.assignments)
    (record,) = report.verification_records
    assert record.decided_by == "verifier" and record.verdict == "drop"


def test_no_consensus_on_a_revision_keeps_the_extractor_version():
    # Verifier chỉ được quyết giữ/bỏ: hết vòng mà không phải drop thì giữ bản của agent trích xuất,
    # không áp bên nhận việc Verifier đề xuất.
    suggestion = {**_verifier_final("revise", "T4"),
                  "revised_assignees": [{"name": "Anh Tuấn", "role": "lead", "type": "person"}]}
    llm = FakeLLM(verifier_script=[suggestion] * 2, proposer_script=[_proposer("defend", "T4")] * 2)
    report = _start(_analyzer(llm, AnalysisConfig(consensus_max_rounds=2)))

    (kept,) = [a for a in report.assignments if a.text == PROPOSAL_TEXT]
    assert kept.actor != "Anh Tuấn"
    (record,) = report.verification_records
    assert (record.verdict, record.decided_by) == ("revise", "verifier")


def test_still_unresolved_after_rounds_is_kept_as_fallback():
    llm = FakeLLM(verifier_script=[_verifier_step("get_turn", "T4")] * 3, proposer_script=[_proposer("defend")])
    config = AnalysisConfig(consensus_max_rounds=1, verifier_max_tool_calls=2)
    report = _start(_analyzer(llm, config))

    kept = [a for a in report.assignments if a.text == PROPOSAL_TEXT]
    assert kept and kept[0].verification == "fallback"
    assert llm.calls.count("verifier") == 3  # 2 lần tool + 1 lượt bắt buộc kết luận


def test_llm_error_keeps_original_candidate_as_fallback():
    llm = FakeLLM(
        verifier_script=[_verifier_final("unresolved"), LLMUpstreamError("402 Insufficient Balance")],
        proposer_script=[_proposer("amend", text="Bản tự sửa chưa được kiểm")],
    )
    report = _start(_analyzer(llm))

    kept = [a for a in report.assignments if a.verification == "fallback"]
    assert [a.text for a in kept] == [PROPOSAL_TEXT]
    assert report.verification_records[0].decided_by == "fallback"


def test_failed_extractor_is_retried_in_place():
    llm = FakeLLM(verifier_script=[_verifier_final("drop")], fail_action_once=True)
    report = _start(_analyzer(llm))

    assert report.failures == ()
    assert [a.actor for a in report.assignments] == ["Hiếu"]


def test_report_is_ordered_by_topic():
    llm = FakeLLM(delay=0.01, verifier_script=[_verifier_final("drop")])
    report = _start(_analyzer(llm))

    assert [label.segment_id for label in report.labels] == ["S1", "S2", "S3"]
    assert [s.segment_id for s in report.discussion_points] == ["S1", "S2", "S3"]


def test_assignment_deadline_is_normalized_against_meeting_date():
    llm = FakeLLM(verifier_script=[_verifier_final("drop")])
    report = _analyzer(llm).analyze(meeting_id="M1", meeting_date="2026-10-08", turns=TURNS, segments=SEGMENTS)

    (assignment,) = report.assignments
    assert (assignment.deadline_raw, assignment.deadline_date, assignment.deadline_kind) == (
        "trước ngày 25/11", "2026-11-25", "before",
    )


def test_assignment_deadline_without_meeting_date_keeps_kind_only():
    llm = FakeLLM(verifier_script=[_verifier_final("drop")])
    (assignment,) = _start(_analyzer(llm)).assignments

    assert (assignment.deadline_date, assignment.deadline_kind) == (None, "before")


def test_accept_that_cites_a_turn_is_treated_as_defend():
    llm = FakeLLM(
        verifier_script=[_verifier_final("drop", reasoning="chỉ là đề xuất"), _verifier_final("keep", "T4")],
        proposer_script=[_proposer("accept", "T4")],
    )
    report = _start(_analyzer(llm))

    (record,) = report.verification_records
    assert [(r.verdict, r.stance, r.confirm_turn_id) for r in record.rounds] == [
        ("drop", "defend", "T4"), ("keep", "", None),
    ]
    assert record.decided_by == "consensus" and record.verdict == "keep"
    second_verifier_prompt = [user for kind, _, user in llm.prompts if kind == "verifier"][1]
    assert "giữ nguyên, phản biện, lượt T4" in second_verifier_prompt


def test_invalid_stance_gets_another_round_with_a_readable_label():
    llm = FakeLLM(
        verifier_script=[_verifier_final("drop"), _verifier_final("keep", "T4")],
        proposer_script=[{**_proposer("accept"), "stance": "maybe"}],
    )
    report = _start(_analyzer(llm))

    (record,) = report.verification_records
    assert [(r.verdict, r.stance) for r in record.rounds] == [("drop", ""), ("keep", "")]
    second_verifier_prompt = [user for kind, _, user in llm.prompts if kind == "verifier"][1]
    assert "Agent trích xuất (không rõ lập trường)" in second_verifier_prompt


def test_accept_of_a_revision_with_a_turn_stays_accept():
    llm = FakeLLM(verifier_script=[{**_verifier_final("revise", "T4"),
                                  "revised_assignees": [{"name": "Anh Tuấn", "role": "lead", "type": "person"}]}],
                  proposer_script=[_proposer("accept", "T4", actor="Anh Tuấn")])
    report = _start(_analyzer(llm))

    (record,) = report.verification_records
    assert record.rounds[0].stance == "accept" and record.verdict == "revise"
    proposer_prompt = next(user for kind, _, user in llm.prompts if kind == "proposer")
    assert "Kiểm chứng viên đề xuất bên nhận việc: Anh Tuấn (lead, person)" in proposer_prompt
    assert [a.actor for a in report.assignments if a.text == PROPOSAL_TEXT] == ["Anh Tuấn"]


def test_filter_reasons_are_presented_as_hints_not_evidence():
    llm = FakeLLM(verifier_script=[_verifier_final("drop")])
    _start(_analyzer(llm))

    verifier_prompt = next(user for kind, _, user in llm.prompts if kind == "verifier")
    assert "Cờ của bộ lọc tự động (chỉ là gợi ý, có thể sai, KHÔNG phải bằng chứng)" in verifier_prompt
    assert "Lý do bị đánh dấu chưa chắc chắn" not in verifier_prompt


def test_repeated_tool_call_is_not_run_again():
    llm = FakeLLM(verifier_script=[_verifier_step("search_meeting", "mở lại phản ánh"),
                                   _verifier_step("search_meeting", "  Mở lại  phản ánh "), _verifier_final("drop")])
    report = _start(_analyzer(llm))

    first, second = report.verification_records[0].steps
    assert "[T3|" in first.observation
    assert second.observation.startswith("LỖI: đã tra search_meeting") and "Bước 1" in second.observation


def test_search_prefers_short_on_topic_turn_over_long_rambling_turn():
    filler = "Báo cáo tình hình đề án cảng biển, hạ tầng, nguồn hàng và quy hoạch vùng. " * 30
    turns = (
        _turn("L1", "Anh Sinh", filler + "Đảng ủy ban xây dựng lại tờ trình rồi."),
        _turn("L2", "Anh Sinh", filler),
        _turn("L3", "Anh Sơn", "Đề nghị Đảng ủy ban xây dựng lại tờ trình rồi báo cáo thường vụ."),
    )
    tools = MeetingTools(turns, SpeakerRegistry(("Anh Sinh", "Anh Sơn")), search_top_k=1)

    assert tools.run("search_meeting", "Đảng ủy ban xây dựng lại tờ trình").startswith("[L3|")


def test_search_snippet_is_cut_around_the_match():
    filler = "Báo cáo tình hình chung của cảng biển. " * 40
    turns = (_turn("L1", "Anh Sơn", filler + "Giao Đảng ủy ban chuẩn bị lại tờ trình."),)
    tools = MeetingTools(turns, SpeakerRegistry(("Anh Sơn",)))

    line = tools.run("search_meeting", "chuẩn bị lại tờ trình")
    assert line.startswith("[L1|Anh Sơn] …") and "chuẩn bị lại tờ trình" in line


def test_chair_is_shown_to_extractors_and_verifier():
    llm = FakeLLM(verifier_script=[_verifier_final("drop")])
    _analyzer(llm).analyze(
        meeting_id="M1", turns=TURNS, segments=SEGMENTS, chair=MeetingChair(person_id="P1", full_name="Anh Tuấn")
    )

    action_prompt = next(user for kind, _, user in llm.prompts if kind == "action")
    verifier_prompt = next(user for kind, _, user in llm.prompts if kind == "verifier")
    assert action_prompt.startswith("Người chủ trì: Anh Tuấn\n")
    assert verifier_prompt.startswith("Người chủ trì: Anh Tuấn\n")


def test_chair_name_comes_from_roster_by_id():
    roster = AttendeeRoster(people=(AttendeePerson("P1", "Nguyễn Văn Tuấn"),))
    chair = parse_meeting_chair({"id": "P1", "full_name": "Anh Tuấn"})

    assert chair.resolve_name(roster) == "Nguyễn Văn Tuấn"
    assert chair.resolve_name(None) == "Anh Tuấn"
    assert parse_meeting_chair({"id": "P9", "full_name": " "}).resolve_name(roster) is None
    assert parse_meeting_chair(None) is None


def test_chair_is_kept_as_given():
    chair = MeetingChair(person_id="", full_name="Chị Lan")
    assert build_speaker_registry(TURNS, chair=chair).chair == chair
    assert build_speaker_registry(TURNS, chair=MeetingChair(person_id="", full_name="  ")).chair is None


def test_registry_keeps_chair_id_only_when_a_speaker_has_it():
    turns = (SpeakerTurn("T1", "Đ/c Tuấn (HNI)", "Chốt lại.", None, None, speaker_id="u-tuan"),)

    kept = build_speaker_registry(turns, chair=MeetingChair(person_id="u-tuan", full_name="Nguyễn Văn Tuấn")).chair
    dropped = build_speaker_registry(turns, chair=MeetingChair(person_id="P1", full_name="Nguyễn Văn Tuấn")).chair

    assert kept == MeetingChair(person_id="u-tuan", full_name="Nguyễn Văn Tuấn")
    assert dropped == MeetingChair(person_id="", full_name="Nguyễn Văn Tuấn")


def test_chair_is_recognised_by_speaker_id_before_name():
    chair = MeetingChair(person_id="u-tuan", full_name="Nguyễn Văn Tuấn")

    # Nhãn khác họ tên nhưng cùng mã: vẫn là người chủ trì.
    assert chair.is_speaker("Đ/c Tuấn (HNI)", "u-tuan")
    # Trùng họ tên nhưng khác mã: người khác.
    assert not chair.is_speaker("Nguyễn Văn Tuấn", "u-khac")
    # Thiếu mã thì so tên.
    assert chair.is_speaker("Nguyễn Văn Tuấn (HNI)")
    assert not MeetingChair(person_id="", full_name="Nguyễn Văn Tuấn").is_speaker("Đ/c Tuấn", "u-tuan")


def test_extractors_run_with_v3_prompts():
    llm = FakeLLM(verifier_script=[_verifier_final("drop")])
    _start(_analyzer(llm))

    systems = {kind: system for kind, system, _ in llm.prompts}
    assert systems["content"] == prompts.CONTENT_SYSTEM_PROMPT
    assert systems["action"] == prompts.ACTION_SYSTEM_PROMPT
    assert systems["decision"] == prompts.DECISION_SYSTEM_PROMPT
    assert prompts.CHAIR_ASSIGNMENT_RULE in systems["action"]
    assert prompts.CHAIR_ASSIGNMENT_RULE in systems["verifier"]
    action_prompt = next(user for kind, _, user in llm.prompts if kind == "action")
    assert action_prompt.startswith("Người chủ trì: (phiên họp không cung cấp; KHÔNG đoán ai là người chủ trì)\n")


def test_chair_conclusion_rule_is_shared_by_decision_agent_and_verifier():
    assert prompts.CHAIR_CONCLUSION_RULE in prompts.DECISION_SYSTEM_PROMPT
    assert prompts.CHAIR_CONCLUSION_RULE in prompts.VERIFY_RUBRICS["decision"]
    # Content agent chỉ cần biết bỏ lời giao việc/kết luận, không cần cả hệ quy tắc (và không
    # có trường turn_id): hai quy tắc dài đó chỉ làm prompt phình và lệch trọng tâm.
    assert prompts.CHAIR_ASSIGNMENT_RULE not in prompts.CONTENT_SYSTEM_PROMPT
    assert prompts.CHAIR_CONCLUSION_RULE not in prompts.CONTENT_SYSTEM_PROMPT
    assert prompts.TURN_ID_RULE not in prompts.CONTENT_SYSTEM_PROMPT


def test_shared_rules_appear_once_per_extractor_prompt():
    for system in (prompts.ACTION_SYSTEM_PROMPT, prompts.DECISION_SYSTEM_PROMPT):
        assert system.count(prompts.TURN_ID_RULE) == 1
    for system in (prompts.CONTENT_SYSTEM_PROMPT, prompts.ACTION_SYSTEM_PROMPT, prompts.DECISION_SYSTEM_PROMPT):
        assert system.count(prompts.THIRD_PERSON_RULE) == 1
        assert all(line == line.rstrip() for line in system.splitlines())


def test_verifier_history_keeps_thoughts_and_turn_comes_before_verdict():
    llm = FakeLLM(verifier_script=[_verifier_step("search_meeting", "mở lại phản ánh", thought="tìm lượt chốt"),
                                   _verifier_final("drop")])
    _start(_analyzer(llm))

    second_verifier_prompt = [user for kind, _, user in llm.prompts if kind == "verifier"][1]
    assert "Suy nghĩ: tìm lượt chốt\nHành động: search_meeting(mở lại phản ánh)" in second_verifier_prompt
    fields = list(VERIFIER_SCHEMA["properties"])
    assert fields.index("deciding_turn_id") < fields.index("verdict")


def test_tools_accept_short_turn_ids_from_the_verifier():
    turns = (
        _turn("TURN_000009", "Anh Tuấn", "Phải thông qua Ban Thường vụ đúng không?"),
        _turn("TURN_000030", "Anh Tuấn", "Đề nghị Đảng ủy ban lưu ý các ý kiến góp ý."),
    )
    tools = MeetingTools(turns, SpeakerRegistry(("Anh Tuấn",)))

    for alias in ("T30", "000030", "30", "[TURN_000030|Anh Tuấn]"):
        assert tools.run("get_turn", alias).startswith("[TURN_000030|Anh Tuấn]")
    assert "LỖI" not in tools.run("lookup_speaker", "Anh Tuấn @T9")
    assert "LỖI" in tools.run("get_turn", "T31")


def test_amend_keeps_the_revised_text_and_rejects_switching_to_another_task():
    from ..shared.schemas import ActionItemCandidate
    from ..step5_verify.verifier.verifier import _apply_proposal

    turns = (_turn("T1", "Anh Tuấn", "Đề nghị Đảng ủy, Ban lưu ý các ý kiến góp ý."),)
    original = ActionItemCandidate(
        "S1", "Đảng ủy, Ban", "nghiên cứu cơ chế miễn giảm thuế, giá dịch vụ để đưa vào Luật Đô thị đặc biệt",
        ("T1",), ("",), status="assigned", confirm_turn_id=None,
    )

    reworded = _apply_proposal(original, "action", {
        "stance": "amend", "confirm_turn_id": "T1",
        "revised_text": "Nghiên cứu cơ chế miễn giảm thuế, giá dịch vụ để đề xuất đưa vào Luật Đô thị đặc biệt",
    }, turns)
    assert reworded.text.startswith("Nghiên cứu cơ chế miễn giảm thuế")  # giữ nguyên văn agent viết
    assert reworded.confirm_turn_id == "T1"

    switched = _apply_proposal(original, "action", {
        "stance": "amend", "confirm_turn_id": "T1",
        "revised_text": "đánh giá tác động của đề án đối với Thành phố trong không gian phát triển mới",
    }, turns)
    assert switched.text == original.text
    assert switched.confirm_turn_id == "T1"

    broadened_to_whole_summary = _apply_proposal(original, "action", {
        "stance": "amend", "confirm_turn_id": "T1",
        "revised_text": (
            "Nghiên cứu cơ chế miễn giảm thuế, giá dịch vụ để đưa vào Luật Đô thị đặc biệt; "
            "đánh giá tác động của đề án trong không gian phát triển mới; xác định trách nhiệm "
            "của Thành phố và đề xuất với Thủ tướng Chính phủ; đổi tên đề án gắn với Cần Giờ"
        ),
    }, turns)
    assert broadened_to_whole_summary.text == original.text

    reassigned = _apply_proposal(original, "action", {
        "stance": "amend", "confirm_turn_id": "T1",
        "revised_assignees": [{"name": "Đảng ủy", "role": "lead", "type": "organization"},
                              {"name": "Ban Thường vụ", "role": "support", "type": "organization"}],
    }, turns)
    assert reassigned.actor == "Đảng ủy, Ban Thường vụ"
    assert [(m.name, m.role) for m in reassigned.mentions] == [("Đảng ủy", "lead"), ("Ban Thường vụ", "support")]


def test_assignment_rule_names_every_basis_and_limits_blanket_acceptance():
    def flat(text: str) -> str:
        return " ".join(text.split())

    rule = flat(prompts.CHAIR_ASSIGNMENT_RULE)
    for basis in (*BASIS_STATUS, *NOT_ASSIGNMENT_BASES):
        assert f'"{basis}"' in rule
    assert "Không có người chủ trì vẫn có việc giao" in rule
    assert "lưu ý các ý kiến góp ý" in rule
    # Tiếp nhận chung không biến lời trình bày (lộ trình của đề án) thành việc giao.
    assert "không áp cho lời trình bày của đơn vị trình" in rule
    assert "đơn vị trình/soạn thảo là lead" in rule
    assert "KHÔNG bỏ vì không nêu cá nhân" in flat(prompts.VERIFY_RUBRICS["action"])
    assert prompts.VERIFY_ACCEPTANCE_NOTE in prompts.VERIFY_RUBRICS["action"]
    note = flat(prompts.VERIFY_ACCEPTANCE_NOTE)
    assert "như anh X nói" in note
    assert "KHÔNG biến nội dung văn bản đang trình" in note


def test_action_basis_sets_status_and_drops_document_content_and_reports():
    turns = (
        _turn("T1", "Anh Sinh", "Đề án sẽ trình cấp trên phê duyệt; trước đây đã cập nhật số liệu."),
        _turn("T2", "Anh Phong", "Đề nghị xem lại tên đề án."),
        _turn("T3", "Anh Tuấn", "Tinh thần chung là các đồng chí lưu ý các ý kiến góp ý."),
    )

    class _ScriptedLLM:
        def generate_json(self, *, system_prompt, user_prompt, schema):
            assert "basis" in schema["properties"]["action_items"]["items"]["required"]

            def item(basis, text, turn):
                return {"evidence_segment_ids": [turn], "basis": basis, "confirm_turn_id": turn, "assignees": [],
                        "deadline": None, "deadline_date": None, "deadline_kind": "unknown", "text": text}

            return {"action_items": [
                item("document_content", "Trình cấp trên phê duyệt đề án", "T1"),
                item("status_report", "Cập nhật số liệu", "T1"),
                item("member_request_accepted", "Xem lại tên đề án", "T3"),
                item("volunteered", "Gửi số liệu bổ sung", "T2"),
                item("member_request_pending", "Bổ sung phụ lục", "T2"),
            ]}

    task = {"segment_id": "S1", "title": "", "summary": "", "turns": turns, "meeting_context": "", "meeting_date": None}
    candidates = run_action_agent(_ScriptedLLM(), prompts.ACTION_SYSTEM_PROMPT, task)["action_item_candidates_raw"]

    assert [(c.text, c.status) for c in candidates] == [
        ("Xem lại tên đề án", "assigned"), ("Gửi số liệu bổ sung", "self_committed"), ("Bổ sung phụ lục", "proposed"),
    ]


def test_action_agent_keeps_the_declared_closing_and_request_turns():
    turns = (
        _turn("T1", "Anh Phong", "Đề nghị xem lại tên đề án."),
        _turn("T2", "Anh Tuấn", "Tinh thần chung là các đồng chí lưu ý các ý kiến góp ý."),
        _turn("T3", "Anh Sinh", "Vâng."),
    )

    class _ScriptedLLM:
        def generate_json(self, *, system_prompt, user_prompt, schema):
            assert "summary_turn_id" in schema["required"]

            def item(basis, text, request, confirm):
                return {"evidence_segment_ids": [request], "basis": basis, "request_turn_id": request,
                        "confirm_turn_id": confirm, "assignees": [], "deadline": None, "deadline_date": None,
                        "deadline_kind": "unknown", "text": text}

            return {"summary_turn_id": "T2", "action_items": [
                item("member_request_accepted", "Xem lại tên đề án", "T1", "T2"),
                item("member_request_accepted", "Khai lượt nêu làm lượt chốt", "T1", "T1"),
                item("volunteered", "Gửi số liệu", "T3", "T3"),
            ]}

    task = {"segment_id": "S1", "title": "", "summary": "", "turns": turns, "meeting_context": "", "meeting_date": None}
    name, wrong, self_commit = run_action_agent(_ScriptedLLM(), prompts.ACTION_SYSTEM_PROMPT, task)["action_item_candidates_raw"]

    assert (name.request_turn_id, name.confirm_turn_id, name.evidence_turn_ids) == ("T1", "T2", ("T1", "T2"))
    # Lượt chốt sai (lượt nêu) không bị thay bằng lượt tổng kết: ``check_evidence`` gắn cờ cho Verifier.
    assert wrong.confirm_turn_id == "T1"
    assert self_commit.confirm_turn_id == "T3"


def test_accepted_member_requests_become_assignments_at_the_summary_turn():
    turns = (
        _turn("T1", "Anh Tuấn", "Mời các ý kiến."),
        _turn("T2", "Anh Phong", "Thứ nhất xem lại tên đề án, thứ hai cập nhật theo Luật Đô thị đặc biệt."),
        _turn("T3", "Anh Tuấn", "Rồi, cảm ơn. Mời ý kiến khác."),
        _turn("T4", "Anh Thông", "Đề nghị di dời các cảng nội ô."),
        _turn("T5", "Anh Tuấn", "Tinh thần chung là các đồng chí lưu ý các ý kiến góp ý."),
    )

    class _ScriptedLLM:
        def generate_json(self, *, system_prompt, user_prompt, schema):
            assert next(iter(schema["properties"])) == "member_requests"  # liệt kê trước khi viết việc giao

            def request(turn, requester, response, text):
                return {"turn_id": turn, "requester": requester, "response": response, "response_turn_id": "T5",
                        "assignees": [], "deadline": None, "deadline_date": None, "deadline_kind": "unknown",
                        "text": text}

            return {"summary_turn_id": "T5", "action_items": [], "member_requests": [
                request("T2", "Anh Phong", "accepted", "Xem lại tên đề án"),
                request("T2", "Anh Phong", "accepted", "Cập nhật theo Luật Đô thị đặc biệt"),
                request("T4", "Anh Thông", "rejected", "Di dời các cảng nội ô"),
                request("T1", "Anh Tuấn", "accepted", "Lời của chính người chủ trì"),
                "không phải dict",
            ]}

    task = {"segment_id": "S1", "title": "", "summary": "", "turns": turns, "meeting_context": "", "meeting_date": None}
    candidates = run_action_agent(_ScriptedLLM(), prompts.ACTION_SYSTEM_PROMPT, task, chair=MeetingChair(person_id="", full_name="Anh Tuấn"))[
        "action_item_candidates_raw"
    ]

    # Chỉ yêu cầu "accepted" của thành viên; yêu cầu bị gạt và yêu cầu của người chủ trì bị bỏ.
    assert [(c.text, c.status, c.confirm_turn_id) for c in candidates] == [
        ("Xem lại tên đề án", "assigned", "T5"), ("Cập nhật theo Luật Đô thị đặc biệt", "assigned", "T5"),
    ]
    assert [c.evidence_turn_ids for c in candidates] == [("T2", "T5"), ("T2", "T5")]


def test_accepted_member_points_become_decisions_only_for_members():
    turns = (
        _turn("T1", "Anh Quân", "Đề án gồm 5 phần, sẽ cập nhật cảng Cần Giờ."),
        _turn("T2", "Anh Phong", "Đề nghị xem lại tên đề án."),
        _turn("T3", "Anh Tuấn", "Rồi. Mời ý kiến khác."),
        _turn("T4", "Anh Thông", "Đề nghị di dời các cảng nội ô."),
        _turn("T5", "Anh Tuấn", "Như anh Phong nói cái tên, các đồng chí lưu ý."),
    )

    class _ScriptedLLM:
        def generate_json(self, *, system_prompt, user_prompt, schema):
            assert next(iter(schema["properties"])) == "member_points"  # liệt kê trước khi viết kết luận

            def point(turn, requester, role, response, text, chair_turn="T5"):
                return {"turn_id": turn, "requester": requester, "point_kind": role, "response": response,
                        "response_turn_id": chair_turn, "text": text}

            return {"decisions": [], "member_points": [
                point("T1", "Anh Quân", "presentation", "accepted", "Đề án cập nhật cảng Cần Giờ"),
                point("T2", "Anh Phong", "feedback", "accepted", "Đề án cần xem lại tên gọi"),
                point("T4", "Anh Thông", "feedback", "rejected", "Di dời các cảng nội ô"),
                point("T5", "Anh Tuấn", "feedback", "accepted", "Lời của chính người chủ trì"),
                point("T4", "Anh Thông", "feedback", "accepted", "Đề án cần tính việc di dời cảng nội ô", chair_turn="T4"),
                "không phải dict",
            ]}

    task = {"segment_id": "S1", "title": "", "summary": "", "turns": turns, "meeting_context": "", "meeting_date": None}
    candidates = run_decision_agent(_ScriptedLLM(), prompts.DECISION_SYSTEM_PROMPT, task, chair=MeetingChair(person_id="", full_name="Anh Tuấn"))[
        "decision_candidates_raw"
    ]

    # Chỉ ý "accepted" của thành viên; ý đơn vị trình tự nêu, ý bị gạt và ý của người chủ trì bị bỏ.
    # Lượt tiếp nhận model khai được giữ nguyên, kể cả khi sai (T4 là lượt của chính người nêu):
    # ``check_evidence`` kiểm và gắn cờ cho Verifier (test_anchor).
    assert [(c.text, c.status, c.confirm_turn_id) for c in candidates] == [
        ("Đề án cần xem lại tên gọi", "agreed", "T5"), ("Đề án cần tính việc di dời cảng nội ô", "agreed", "T4"),
    ]
    assert candidates[0].evidence_turn_ids == ("T2", "T5")

    # Không có người chủ trì: không đoán Anh Tuấn là người chủ trì, nên ý Anh Tuấn tự nêu ở T5 cũng là
    # một mục (lượt chốt trùng lượt nêu: ``check_evidence`` xét như lời chốt thường).
    candidates = run_decision_agent(_ScriptedLLM(), prompts.DECISION_SYSTEM_PROMPT, task)["decision_candidates_raw"]
    assert [(c.text, c.confirm_turn_id) for c in candidates] == [
        ("Đề án cần xem lại tên gọi", "T5"),
        ("Lời của chính người chủ trì", "T5"),
        ("Đề án cần tính việc di dời cảng nội ô", "T4"),
    ]


# Tính riêng từng phần trên nhãn nạp sẵn (tầng dịch vụ dùng để chạy lại một phần)


class CountingLabeler(FakeLabeler):
    """``FakeLabeler`` đếm số lần được gọi."""

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def label_topic(self, segment, *args, **kwargs):
        with self._lock:
            self.calls += 1
        return super().label_topic(segment, *args, **kwargs)


def test_single_part_runs_only_its_agent_on_preset_labels():
    llm, labeler = FakeLLM(), CountingLabeler()
    analyzer = MeetingAnalyzer(content_llm=llm, action_llm=llm, decision_llm=llm, verifier_llm=llm, labeler=labeler)
    labels = analyzer.label_segments(SEGMENTS)

    report = analyzer.analyze(meeting_id="M1", turns=TURNS, segments=SEGMENTS, parts={"decisions"}, labels=labels)

    assert labeler.calls == 3  # chỉ lần gán nhãn nền; graph dùng lại nhãn nạp sẵn
    assert llm.calls == ["decision"] * len(SEGMENTS)
    assert report.labels == labels
    assert report.discussion_points == () and report.assignments == ()


def test_parts_computed_separately_match_one_pass_run():
    full = _start(_analyzer(FakeLLM(verifier_script=[_verifier_final("drop")])))

    analyzer = _analyzer(FakeLLM(verifier_script=[_verifier_final("drop")]))
    labels = analyzer.label_segments(SEGMENTS)
    split = {
        part: analyzer.analyze(meeting_id="M1", turns=TURNS, segments=SEGMENTS, parts={part}, labels=labels)
        for part in ("content", "assignments", "decisions")
    }

    assert labels == full.labels
    assert split["content"].discussion_points == full.discussion_points
    assert split["assignments"].assignments == full.assignments
    assert split["assignments"].verification_records == full.verification_records
    assert split["decisions"].decisions == full.decisions


def test_task_progress_is_left_out_when_progress_part_is_not_requested():
    agenda = parse_task_agenda({"tasks": [{"id": "K1", "title": "Map nhãn", "owner": "Hiếu"}]})
    analyzer = _analyzer(FakeLLM(verifier_script=[_verifier_final("drop")]))

    report = analyzer.analyze(
        meeting_id="M1", turns=TURNS, segments=SEGMENTS, task_agenda=agenda, parts={"assignments"}
    )

    assert report.task_progress == ()
    assert [a.actor for a in report.assignments] == ["Hiếu"]


def test_unknown_part_is_rejected():
    with pytest.raises(ValueError, match="summary"):
        _analyzer(FakeLLM()).analyze(meeting_id="M1", turns=TURNS, segments=SEGMENTS, parts={"summary"})


class _RelationTurnJudge(CommitTurnJudge):
    """Lượt chốt T1, T2, T6; kết luận ở S3 thay đổi kết luận ở S1."""

    def __init__(self):
        super().__init__({"T1", "T2", "T6"})
        self.relations = []

    def judge_relation(self, earlier, later):
        self.relations.append((earlier, later))
        probs = {"changed": 0.9, "unchanged": 0.05, "different_matter": 0.05}
        return DecisionRelationJudgement("changed", probs)


def test_finalize_keeps_only_the_last_conclusion_of_an_issue_across_topics():
    class _DecisionLLM(FakeLLM):
        def _answer(self, kind, user_prompt):
            if kind != "decision":
                return super()._answer(kind, user_prompt)
            for turn_id, text in (("T1", "Trình đề án lên Thủ tướng"), ("T6", "Làm lại đề án trước khi trình")):
                if f"[{turn_id}|" in user_prompt:
                    return {"member_points": [], "decisions": [{
                        "evidence_segment_ids": [turn_id], "basis": "closing_statement", "request_turn_id": turn_id,
                        "confirm_turn_id": turn_id, "text": text,
                    }]}
            return {"member_points": [], "decisions": []}

    judge = _RelationTurnJudge()
    report = _start(_analyzer(_DecisionLLM(verifier_script=[_verifier_final("drop")]), turn_judge=judge))

    assert [d.text for d in report.decisions] == ["Làm lại đề án trước khi trình"]
    assert judge.relations == [("Trình đề án lên Thủ tướng", "Làm lại đề án trước khi trình")]
    superseded = [r for r in report.verification_records if r.verdict == "superseded"]
    assert [(r.candidate_text, r.deciding_turn_id) for r in superseded] == [("Trình đề án lên Thủ tướng", "T6")]


def test_accept_turned_defend_does_not_apply_revised_text():
    """Agent chọn "accept" nhưng chỉ ra lượt chốt thì thành "defend": giữ nội dung, chỉ ghi lượt chốt."""

    from ..shared.schemas import ActionItemCandidate, Review
    from ..step5_verify.verifier.verifier import Verifier

    class Proposer:
        def generate_json(self, *, system_prompt, user_prompt, schema):
            return {"stance": "accept", "confirm_turn_id": "T1", "argument": "",
                    "revised_text": "Lập báo cáo tiến độ dự án gửi Thành ủy",
                    "revised_assignees": [{"name": "Sở Xây dựng", "role": "lead", "type": "organization"}]}

    turns = (_turn("T1", "Anh Tuấn", "Giao anh Sơn lập báo cáo tiến độ dự án."),)
    claim = ActionItemCandidate("S1", "anh Sơn", "lập báo cáo tiến độ dự án", ("T1",), ("",),
                                status="assigned", confirm_turn_id=None)
    task = {"item_key": "S1:action:0", "segment_id": "S1", "kind": "action", "candidate": claim,
            "reasons": (), "turns": turns, "meeting_turns": turns, "registry": SpeakerRegistry(("Anh Tuấn",))}

    response = Verifier(Proposer(), {"action": Proposer()}, AnalysisConfig()).respond(
        task, claim, Review("drop", None, "Không thấy lời giao."), [])

    assert response.stance == "defend"
    assert response.claim.text == claim.text
    assert response.claim.actor == claim.actor
    assert response.claim.confirm_turn_id == "T1"
