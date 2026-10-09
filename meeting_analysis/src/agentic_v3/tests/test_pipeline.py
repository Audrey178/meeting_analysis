"""Test end-to-end của ``src.agentic_v3`` với LLM giả (không gọi mạng).

Kiểm: Planner bỏ agent đúng chỗ, tool của Verifier, các chủ đề chạy song song nhưng
không vượt gate, Verifier ReAct (tra tool rồi kết luận), vòng feedback Verifier <->
agent trích xuất tới khi đồng thuận, thử lại agent tại chỗ, và thứ tự kết quả.
"""

from __future__ import annotations

import threading
import time

from src.agentic_v3 import MeetingAnalyzerV3, V3Config, plan_meeting
from src.agentic_v3.nodes.verifier_tools import MeetingTools
from src.agentic_v3.schemas import SpeakerRegistry
from src.agentic_v3.nodes.verifier_tools import MeetingTools
from src.utils.contracts import SpeakerTurn, TopicLabel, TopicSegment
from src.utils.ports import LLMUpstreamError


def _turn(turn_id: str, speaker: str, text: str) -> SpeakerTurn:
    return SpeakerTurn(turn_id, speaker, text, (), None, None)


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
        atom_ids=turn_ids,
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
        self.prompts: list[tuple[str, str]] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.segments_in_flight: set[str] = set()
        self.max_segments_in_flight = 0
        self._lock = threading.Lock()

    def generate_json(self, *, system_prompt, user_prompt, schema):
        kind = self._kind(system_prompt, schema)
        segment = next((s.segment_id for s in SEGMENTS if any(f"[{t}|" in user_prompt for t in s.atom_ids)), "?")
        with self._lock:
            self.calls.append(kind)
            self.prompts.append((kind, user_prompt))
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
        return {"speakers": "content", "action_items": "action", "decisions": "decision", "stance": "proposer"}[
            next(iter(schema["properties"]))
        ]

    def _answer(self, kind: str, user_prompt: str) -> dict:
        if kind == "content":
            turn_id, speaker = next(
                (t.turn_id, t.speaker) for t in TURNS if f"[{t.turn_id}|" in user_prompt
            )
            return {"speakers": [{"full_name": speaker, "points": [{"evidence_turn_ids": [turn_id], "text": "Ý kiến."}]}]}
        if kind == "action":
            with self._lock:
                if self.fail_action_once:
                    self.fail_action_once = False
                    raise LLMUpstreamError("gateway down")
            if "[T1|" in user_prompt:
                return {"action_items": [{
                    "evidence_turn_ids": ["T1", "T2"], "confirm_turn_id": "T1", "status": "assigned",
                    "actor": "Hiếu", "text": "Map lại nhãn sang 12 lĩnh vực", "deadline": "trước ngày 25/11",
                }]}
            if "[T3|" in user_prompt:
                return {"action_items": [{
                    "evidence_turn_ids": ["T3"], "confirm_turn_id": "T3", "status": "proposed",
                    "actor": "Chị Mai", "text": PROPOSAL_TEXT, "deadline": None,
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

    def label_topic(self, segment, prev_segment, prev_topic, atoms, evidence, *, prior_issues=()):
        return TopicLabel(
            segment_id=segment.segment_id,
            title=f"Bàn về nội dung {segment.segment_id}",
            summary="Tóm tắt.",
            text=segment.text or "",
            evidence_ids=(),
            method="llm",
        )


def _verifier_step(action: str, argument: str | None) -> dict:
    return {"thought": "tra", "action": action, "argument": argument, "verdict": None,
            "deciding_turn_id": None, "revised_actor": None, "reasoning": None}


def _verifier_final(verdict: str, deciding_turn_id: str | None = None, reasoning: str = "ok") -> dict:
    return {"thought": "đủ", "action": "final", "argument": None, "verdict": verdict,
            "deciding_turn_id": deciding_turn_id, "revised_actor": None, "reasoning": reasoning}


def _proposer(stance: str, confirm_turn_id: str | None = None, text: str | None = None, actor: str | None = None) -> dict:
    return {"stance": stance, "argument": "lập luận", "confirm_turn_id": confirm_turn_id,
            "revised_text": text, "revised_actor": actor}


def _analyzer(llm: FakeLLM, config: V3Config | None = None, llm_concurrency: int = 8) -> MeetingAnalyzerV3:
    return MeetingAnalyzerV3(
        content_llm=llm, action_llm=llm, decision_llm=llm, verifier_llm=llm,
        labeler=FakeLabeler(), config=config, llm_concurrency=llm_concurrency,
    )


def _start(analyzer: MeetingAnalyzerV3):
    return analyzer.analyze(meeting_id="M1", turns=TURNS, segments=SEGMENTS)


def test_planner_skips_agents_only_where_no_cue():
    registry, plans = plan_meeting(SEGMENTS, {t.turn_id: t for t in TURNS})

    assert registry.names == ("Anh Tuấn", "Hiếu", "Chị Mai", "Anh Phong")
    assert plans["S1"].run_action and plans["S1"].run_decision
    assert not plans["S3"].run_action and not plans["S3"].run_decision


def test_planner_never_skips_when_disabled():
    _, plans = plan_meeting(SEGMENTS, {t.turn_id: t for t in TURNS}, skip_without_cues=False)

    assert all(plan.run_action and plan.run_decision for plan in plans.values())


def test_tools_read_whole_meeting_and_report_errors_as_observations():
    tools = MeetingTools(TURNS, SpeakerRegistry(("Anh Tuấn", "Hiếu", "Chị Mai", "Anh Phong")))

    assert tools.run("get_turn", "[T4|Anh Tuấn]").startswith("[T4|Anh Tuấn]")
    assert "LỖI" in tools.run("get_turn", "T99")
    assert "LỖI" in tools.run("delete_turn", "T1")
    assert "[T3|" in tools.run("search_meeting", "mở lại phản ánh")
    assert "Anh Phong" in tools.run("lookup_speaker", "Phong")


def test_topics_run_in_parallel_within_gate_limit():
    llm = FakeLLM(delay=0.05, verifier_script=[_verifier_final("drop")])
    result = _start(_analyzer(llm, llm_concurrency=3))

    assert result.labels
    assert llm.max_segments_in_flight > 1  # nhiều chủ đề cùng gọi LLM một lúc
    assert llm.max_in_flight <= 3  # nhưng không vượt gate


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
    report = _start(_analyzer(llm, V3Config(consensus_max_rounds=2)))

    assert all(a.text != PROPOSAL_TEXT for a in report.assignments)
    (record,) = report.verification_records
    assert record.decided_by == "verifier" and len(record.rounds) == 2
    assert llm.calls.count("verifier") == 2 and llm.calls.count("proposer") == 2


def test_still_unresolved_after_rounds_is_kept_as_fallback():
    llm = FakeLLM(verifier_script=[_verifier_step("get_turn", "T4")] * 3, proposer_script=[_proposer("defend")])
    config = V3Config(consensus_max_rounds=1, verifier_max_tool_calls=2)
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


def test_report_is_ordered_by_topic_and_skips_are_recorded():
    llm = FakeLLM(delay=0.01, verifier_script=[_verifier_final("drop")])
    report = _start(_analyzer(llm))

    assert [label.segment_id for label in report.labels] == ["S1", "S2", "S3"]
    assert [s.segment_id for s in report.meeting_development] == ["S1", "S2", "S3"]
    assert {(s.segment_id, s.agent) for s in report.skipped_agents} == {
        ("S3", "action_agent"), ("S3", "decision_agent"),
    }


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
    second_verifier_prompt = [p for kind, p in llm.prompts if kind == "verifier"][1]
    assert "giữ nguyên, phản biện, lượt T4" in second_verifier_prompt


def test_accept_of_a_revision_with_a_turn_stays_accept():
    llm = FakeLLM(verifier_script=[{**_verifier_final("revise", "T4"), "revised_actor": "Anh Tuấn"}],
                  proposer_script=[_proposer("accept", "T4")])
    report = _start(_analyzer(llm))

    (record,) = report.verification_records
    assert record.rounds[0].stance == "accept" and record.verdict == "revise"
    assert [a.actor for a in report.assignments if a.text == PROPOSAL_TEXT] == ["Anh Tuấn"]


def test_filter_reasons_are_presented_as_hints_not_evidence():
    llm = FakeLLM(verifier_script=[_verifier_final("drop")])
    _start(_analyzer(llm))

    verifier_prompt = next(p for kind, p in llm.prompts if kind == "verifier")
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
