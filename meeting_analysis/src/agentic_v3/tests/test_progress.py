"""Test danh sách việc cần báo cáo và tiến độ (``actors/agenda.py``, ``nodes/progress.py``).

Không gọi mạng: LLM giả dựa trên ``test_pipeline.FakeLLM``, Decisions giả trả phân bố
xác suất định sẵn.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.agentic_v3 import MeetingAnalyzerV3, plan_meeting
from src.agentic_v3.actors.agenda import (
    TaskAgenda,
    load_task_agenda,
    parse_task_agenda,
    task_path_for,
)
from src.agentic_v3.actors.attendees import parse_attendee_roster
from src.agentic_v3.core._shared import merge_duplicate_assignments
from src.agentic_v3.core.schemas import ActionItemCandidate
from src.agentic_v3.core.nodes.action_agent import ACTION_SCHEMA
from src.agentic_v3.core.turn_act import MAX_TURN_CHARS, TurnActJudgement
from src.agentic_v3.nodes.extractors import make_extractor
from src.agentic_v3.nodes.planner import build_speaker_registry, format_registry_context
from src.agentic_v3.nodes.progress import (
    check_progress_updates,
    link_assignment_to_agenda,
    make_progress_agent,
    summarize_task_progress,
)
from src.agentic_v3.nodes.progress_act import DecisionsProgressActJudge, ProgressActJudgement, split_turn_text
from src.agentic_v3.nodes.prompts import ACTION_SYSTEM_PROMPT, ACTION_TASK_ID_RULE
from src.agentic_v3.schemas import ActionItemV3, ActorAssignee, ProgressUpdate
from src.agentic_v3.tests.test_pipeline import SEGMENTS, TURNS, FakeLabeler, FakeLLM, _verifier_final
from src.utils.contracts import SpeakerTurn
from src.utils.ports import LLMUpstreamError

ROSTER = parse_attendee_roster({
    "people": [{"id": "P1", "full_name": "Phạm Hồng Sơn", "position": "Phó Bí thư", "org_id": "O1"}],
    "organizations": [
        {"id": "O1", "name": "Ban Thường vụ Thành ủy"},
        {"id": "O2", "name": "Đảng ủy UBND Thành phố", "aliases": ["Đảng ủy ban"]},
        {"id": "O7", "name": "Đơn vị tư vấn"},
    ],
})

AGENDA_PAYLOAD = {
    "tasks": [
        {"id": "T1", "title": "Đẩy nhanh khối lượng thi công", "owner": "Anh Phong", "due": "2026-10-31",
         "last_status": "in_progress"},
        {"id": "T2", "title": "Lập báo cáo đánh giá môi trường chiến lược", "owner": "Hiếu", "due": "2026-10-01",
         "last_status": "not_started"},
    ]
}
AGENDA = parse_task_agenda(AGENDA_PAYLOAD)


def _turn(turn_id: str, speaker: str, text: str) -> SpeakerTurn:
    return SpeakerTurn(turn_id, speaker, text, (), None, None)


def _update(task_id: str, status: str, turn_id: str | None, segment_id: str = "S1", **changes) -> ProgressUpdate:
    evidence_ids = changes.pop("evidence_ids", (turn_id,) if turn_id else ("T1",))
    return ProgressUpdate(
        segment_id=segment_id, task_id=task_id, status=status, status_turn_id=turn_id,
        evidence_ids=evidence_ids, quotes=("...",) * len(evidence_ids), **changes,
    )


class FakeProgressJudge:
    """Decisions giả cho lượt nêu trạng thái: turn_id -> phân bố, hoặc exception.

    Việc có tên trong ``report_tasks`` coi như chỉ là báo cáo tại cuộc họp (câu hỏi ``report_act``).
    """

    def __init__(self, answers: dict, report_tasks: frozenset[str] = frozenset()):
        self.answers = answers
        self.report_tasks = report_tasks
        self.calls: list[tuple[str, str]] = []

    def judge(self, task_title, turn, context):
        self.calls.append((task_title, turn.turn_id))
        answer = self.answers[turn.turn_id]
        if isinstance(answer, Exception):
            raise answer
        return ProgressActJudgement(
            label=max(answer, key=answer.get), probabilities=answer, report_task=task_title in self.report_tasks
        )


class FakeDecisionsClient:
    """Client Decisions giả: tên câu hỏi -> phân bố (hoặc hàm của input); ghi (tên câu hỏi, input)."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.calls: list[tuple[str, str]] = []
        self.decisions = self

    def create(self, model, input, questions):
        name = questions[0]["name"]
        self.calls.append((name, input))
        answer = self.answers[name]
        probabilities = answer(input) if callable(answer) else answer
        choice = SimpleNamespace(
            type="choice",
            choice=max(probabilities, key=probabilities.get),
            probabilities=[SimpleNamespace(value=value, probability=p) for value, p in probabilities.items()],
        )
        return SimpleNamespace(answers=[choice])


class TextProgressJudge:
    """Decisions giả xét theo nội dung: đoạn có "đã xong" là báo cáo xong, còn lại không nói về việc.

    Ghi lại (độ dài đoạn, nội dung lượt ngữ cảnh cuối) của mỗi lời gọi.
    """

    def __init__(self):
        self.calls: list[tuple[int, str]] = []

    def judge(self, task_title, turn, context):
        self.calls.append((len(turn.text_exact), context[-1].text_exact if context else ""))
        if "đã xong" in turn.text_exact:
            return ProgressActJudgement("bao_cao_xong", {"bao_cao_xong": 0.9, "khac": 0.1})
        return ProgressActJudgement("khac", {"khac": 0.95, "chi_nhac_hoi": 0.05})


class FakeTurnJudge:
    """Decisions giả cho lượt chốt: turn_id -> p_commit."""

    def __init__(self, p_commit: dict[str, float]):
        self.p_commit = p_commit

    def judge(self, turn, context):
        p = self.p_commit[turn.turn_id]
        return TurnActJudgement(label="ket_luan", probabilities={"ket_luan": p, "thao_luan": 1 - p})


# ---------------------------------------------------------------------------
# Danh sách việc
# ---------------------------------------------------------------------------


def test_agenda_resolves_roster_ids_and_keeps_free_text_names():
    agenda = parse_task_agenda(
        {"tasks": [{"id": "T1", "title": "Trình tờ trình", "owner": "O2", "support": ["O7", "Bộ Xây dựng"],
                    "reporter": "P1", "due": "2026-01-31", "last_status": "in_progress"}]},
        ROSTER,
    )

    (task,) = agenda.tasks
    assert (task.owner.name, task.owner.ref_id) == ("Đảng ủy UBND Thành phố", "O2")
    assert [(p.name, p.ref_id) for p in task.support] == [("Đơn vị tư vấn", "O7"), ("Bộ Xây dựng", None)]
    assert task.reporter.name == "Phạm Hồng Sơn"
    assert agenda.find("T1") is task and agenda.find("T9") is None


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"tasks": [{"id": "T1", "title": "x"}]}, "thiếu id/title/owner"),
        ({"tasks": [{"id": "T1", "title": "x", "owner": "A"}, {"id": "T1", "title": "y", "owner": "B"}]}, "Trùng"),
        ({"tasks": [{"id": "T1", "title": "x", "owner": "O9"}]}, "không có trong danh sách tham dự"),
        ({"tasks": [{"id": "T1", "title": "x", "owner": "A", "due": "31/01/2026"}]}, "YYYY-MM-DD"),
        ({"tasks": [{"id": "T1", "title": "x", "owner": "A", "last_status": "late"}]}, "last_status"),
        ({"tasks": "T1"}, "danh sách"),
    ],
)
def test_malformed_agenda_is_rejected(payload, message):
    with pytest.raises(ValueError, match=message):
        parse_task_agenda(payload, ROSTER)


def test_agenda_file_follows_naming_convention(tmp_path):
    transcript = tmp_path / "meeting-v1.json"
    assert task_path_for(transcript).name == "meeting-v1.tasks.json"
    assert load_task_agenda(transcript) is None

    task_path_for(transcript).write_text(json.dumps(AGENDA_PAYLOAD), encoding="utf-8")
    assert load_task_agenda(transcript).task_ids == ("T1", "T2")


def test_sample_agenda_file_matches_its_attendees():
    from pathlib import Path

    from src.agentic_v3.actors.attendees import load_attendee_roster

    transcript = Path(__file__).resolve().parents[3] / "inputs" / "bien-ban-vdt-trang-copy-v1.json"
    agenda = load_task_agenda(transcript, load_attendee_roster(transcript))

    assert agenda.task_ids == ("T1", "T3", "T5", "X1")


def test_planner_runs_progress_only_with_agenda_and_shows_tasks_in_context():
    turns_by_id = {t.turn_id: t for t in TURNS}
    _, without = plan_meeting(SEGMENTS, turns_by_id)
    registry, with_agenda = plan_meeting(SEGMENTS, turns_by_id, agenda=AGENDA)

    assert not any(plan.run_progress for plan in without.values())
    assert all(plan.run_progress for plan in with_agenda.values())
    context = format_registry_context(registry)
    assert "- T1: Đẩy nhanh khối lượng thi công (chủ trì: Anh Phong; hạn: 2026-10-31" in context


# ---------------------------------------------------------------------------
# Agent tiến độ: đọc output
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    def __init__(self, answer):
        self.answer = answer
        self.calls: list[dict] = []

    def generate_json(self, *, system_prompt, user_prompt, schema):
        self.calls.append({"system": system_prompt, "user": user_prompt, "schema": schema})
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _task(turns):
    return {"segment_id": "S3", "title": "Tiến độ", "summary": "", "turns": turns,
            "previous_context": "", "meeting_date": "2026-10-08"}


def test_progress_agent_validates_task_ids_turns_and_merges_duplicates():
    turns = (TURNS[4], TURNS[5])
    llm = _ScriptedLLM({"updates": [
        {"task_id": "T9", "status": "done", "status_turn_id": "T5", "evidence_turn_ids": ["T5"]},
        {"task_id": "T1", "status": "in_progress", "status_turn_id": "T5", "evidence_turn_ids": ["T5"],
         "deadline": None, "deadline_removed": True, "summary": "Đạt 55%.", "blockers": ["", "thiếu vốn", "a", "b"]},
        {"task_id": "T1", "status": "weird", "status_turn_id": "T99", "evidence_turn_ids": ["T6"]},
        {"task_id": "T2", "status": "done", "status_turn_id": "T1", "evidence_turn_ids": []},
    ]})
    registry = build_speaker_registry(TURNS, agenda=AGENDA)

    result = make_progress_agent(llm)(_task(turns), registry)

    (update,) = result["progress_updates_raw"]  # T9 lạ, T2 không có bằng chứng thuộc đoạn
    assert (update.task_id, update.status, update.status_turn_id) == ("T1", "in_progress", "T5")
    assert update.evidence_ids == ("T5", "T6")  # gộp mục trùng task_id
    assert update.deadline_removed and update.blockers == ("thiếu vốn", "a")
    assert llm.calls[0]["schema"]["properties"]["updates"]["items"]["properties"]["task_id"]["enum"] == ["T1", "T2"]
    assert "Việc cần báo cáo tiến độ" in llm.calls[0]["user"]


def test_progress_agent_reports_llm_error_as_failure():
    registry = build_speaker_registry(TURNS, agenda=AGENDA)
    result = make_progress_agent(_ScriptedLLM(LLMUpstreamError("down")))(_task(TURNS[4:]), registry)

    assert result["progress_updates_raw"] == []
    assert result["topic_failures"][0].agent == "progress_agent"


# ---------------------------------------------------------------------------
# Kiểm lượt nêu trạng thái
# ---------------------------------------------------------------------------


def test_decisions_confirms_revises_or_downgrades_status():
    turns = (_turn("A", "X", "a"), _turn("B", "X", "b"), _turn("C", "X", "c"), _turn("D", "X", "d"))
    judge = FakeProgressJudge({
        "A": {"bao_cao_dang_lam": 0.9, "khac": 0.1},
        "B": {"yeu_cau_lam_lai": 0.85, "bao_cao_xong": 0.15},
        "C": {"bao_cao_xong": 0.5, "chi_nhac_hoi": 0.5},
        "D": RuntimeError("timeout"),
    })
    agenda = parse_task_agenda({"tasks": [{"id": k, "title": k, "owner": "A"} for k in ("K1", "K2", "K3", "K4", "K5")]})
    updates = [
        _update("K1", "in_progress", "A"),
        _update("K2", "done", "B"),
        _update("K3", "done", "C"),
        _update("K4", "done", "D"),
        _update("K5", "done", None),
    ]

    checked = check_progress_updates(updates, turns, agenda, judge)

    assert [u.task_id for u in checked] == ["K1", "K2", "K3", "K4", "K5"]  # kiểm song song, giữ thứ tự
    checked = {u.task_id: u for u in checked}
    assert (checked["K1"].status, checked["K1"].verification, checked["K1"].status_flag) == ("in_progress", "decisions", None)
    assert (checked["K2"].status, checked["K2"].proposed_status, checked["K2"].status_flag) == ("returned", "done", "revised")
    assert (checked["K3"].status, checked["K3"].proposed_status, checked["K3"].status_flag) == ("mentioned", "done", "uncertain")
    assert (checked["K4"].status, checked["K4"].verification) == ("done", "unchecked")
    assert (checked["K5"].status, checked["K5"].status_flag) == ("mentioned", "uncertain")
    assert sorted(call[1] for call in judge.calls) == ["A", "B", "C", "D"]


def test_mention_is_dropped_only_when_every_evidence_turn_is_unrelated():
    turns = (_turn("A", "X", "a"), _turn("B", "X", "b"), _turn("C", "X", "c"), _turn("D", "X", "d"))
    judge = FakeProgressJudge({
        "A": {"chi_nhac_hoi": 0.7, "khac": 0.3},
        "B": {"khac": 0.95, "chi_nhac_hoi": 0.05},
        "C": {"khac": 0.9, "yeu_cau_lam_lai": 0.1},
        "D": RuntimeError("timeout"),
    })
    agenda = parse_task_agenda({"tasks": [{"id": k, "title": k, "owner": "A"} for k in ("M1", "M2", "M3")]})
    updates = [
        _update("M1", "mentioned", None, evidence_ids=("A", "B")),
        _update("M2", "mentioned", None, evidence_ids=("B", "C")),
        _update("M3", "mentioned", None, evidence_ids=("D",)),
    ]

    checked = {u.task_id: u for u in check_progress_updates(updates, turns, agenda, judge)}

    assert set(checked) == {"M1", "M3"}  # M2: mọi lượt bằng chứng đều không nói về việc -> bỏ
    assert (checked["M1"].status, checked["M1"].verification) == ("mentioned", "decisions")
    assert checked["M1"].status_probabilities == (("chi_nhac_hoi", 0.7), ("khac", 0.3))
    assert (checked["M3"].verification, checked["M3"].reason) == ("unchecked", "Decisions lỗi: timeout")
    # Xét từ lượt muộn nhất; gặp lượt có nói về việc thì dừng. Không nâng trạng thái.
    assert [turn for title, turn in judge.calls if title == "M1"] == ["B", "A"]
    assert [turn for title, turn in judge.calls if title == "M2"] == ["C", "B"]

    (unchecked,) = check_progress_updates(updates[:1], turns, agenda, None)
    assert (unchecked.status, unchecked.verification) == ("mentioned", "unchecked")


def test_mention_is_raised_to_report_and_to_directive_only_on_commit_turns():
    turns = (_turn("A", "X", "a"), _turn("B", "X", "b"), _turn("C", "X", "c"))
    judge = FakeProgressJudge({
        "A": {"bao_cao_dang_lam": 0.9, "chi_nhac_hoi": 0.1},
        "B": {"yeu_cau_lam_lai": 0.9, "khac": 0.1},
        "C": {"yeu_cau_lam_lai": 0.85, "chi_nhac_hoi": 0.15},
    })
    turn_judge = FakeTurnJudge({"A": 0.1, "B": 0.9, "C": 0.3})  # B: kết luận của chủ trì; C: kiến nghị
    agenda = parse_task_agenda({"tasks": [{"id": k, "title": k, "owner": "A"} for k in ("R1", "R2", "R3")]})
    updates = [
        _update("R1", "mentioned", None, evidence_ids=("A",)),
        _update("R2", "mentioned", None, evidence_ids=("B",)),
        _update("R3", "mentioned", None, evidence_ids=("C",)),
    ]

    checked = {u.task_id: u for u in check_progress_updates(updates, turns, agenda, judge, turn_judge)}

    r1, r2, r3 = checked["R1"], checked["R2"], checked["R3"]
    assert (r1.status, r1.status_turn_id, r1.proposed_status, r1.status_flag) == ("in_progress", "A", "mentioned", "revised")
    assert (r2.status, r2.status_turn_id, r2.p_directive) == ("returned", "B", 0.9)
    assert r3.status == "mentioned" and "p_commit 0.30" in r3.reason  # kiến nghị của thành viên: không nâng
    (unmeasured,) = check_progress_updates(updates[1:2], turns, agenda, judge)
    assert unmeasured.status == "mentioned"  # không đo được lượt chỉ đạo thì không nâng


def test_status_check_falls_back_to_other_evidence_turns():
    turns = (_turn("A", "X", "a"), _turn("B", "X", "b"), _turn("C", "X", "c"))
    judge = FakeProgressJudge({
        "A": {"bao_cao_xong": 0.9, "khac": 0.1},
        "B": {"chi_nhac_hoi": 0.9, "khac": 0.1},
        "C": {"yeu_cau_lam_lai": 0.9, "chi_nhac_hoi": 0.1},
    })
    agenda = parse_task_agenda({"tasks": [{"id": k, "title": k, "owner": "A"} for k in ("F1", "F2")]})
    updates = [
        _update("F1", "done", None, evidence_ids=("A", "B")),  # agent để status_turn_id null
        _update("F2", "returned", "B", evidence_ids=("A", "B", "C")),  # agent chọn lượt nói chung
    ]

    checked = {u.task_id: u for u in check_progress_updates(updates, turns, agenda, judge)}

    assert (checked["F1"].status, checked["F1"].status_turn_id, checked["F1"].verification) == ("done", "A", "decisions")
    assert "không chỉ ra" in checked["F1"].reason
    assert (checked["F2"].status, checked["F2"].status_turn_id, checked["F2"].status_flag) == ("returned", "C", None)
    # Lượt agent chỉ ra trước, rồi các lượt bằng chứng khác từ lượt muộn nhất; dừng khi xác nhận.
    assert [turn for title, turn in judge.calls if title == "F2"] == ["B", "C"]


def test_generic_question_keeps_agent_report_status_instead_of_flipping_it():
    # Cái Mép T3: agent khai "done", câu hỏi chung xếp lượt là "đang làm" 0.89 vì đoạn đó nói đề án
    # "tiếp tục hoàn thiện" -> giữ "done" (cờ kept), vẫn tính là đã xác nhận khi gộp.
    turns = (_turn("A", "X", "a"), _turn("B", "X", "b"), _turn("C", "X", "c"))
    judge = FakeProgressJudge({
        "A": {"bao_cao_dang_lam": 0.89, "bao_cao_xong": 0.06, "khac": 0.05},
        "B": {"bao_cao_dang_lam": 0.5, "chi_nhac_hoi": 0.5},
        "C": {"yeu_cau_lam_lai": 0.85, "bao_cao_dang_lam": 0.15},
    })
    agenda = parse_task_agenda({"tasks": [{"id": k, "title": k, "owner": "A"} for k in ("P1", "P2", "P3")]})
    updates = [
        _update("P1", "done", "A"),
        _update("P2", "blocked", "B"),  # nhóm báo cáo chỉ 0.5: hạ như cũ
        _update("P3", "done", "C"),  # sang chỉ đạo thì vẫn sửa
    ]

    checked = {u.task_id: u for u in check_progress_updates(updates, turns, agenda, judge)}

    p1 = checked["P1"]
    assert (p1.status, p1.status_flag, p1.proposed_status, p1.verification) == ("done", "kept", None, "decisions")
    assert "bao_cao_dang_lam 0.89" in p1.reason
    assert (checked["P2"].status, checked["P2"].status_flag) == ("mentioned", "uncertain")
    assert (checked["P3"].status, checked["P3"].status_flag) == ("returned", "revised")
    (progress,) = summarize_task_progress(agenda.__class__(tasks=agenda.tasks[:1]), [p1], turns, None)
    assert (progress.status, progress.uncertain) == ("done", False)


def test_report_task_question_may_change_report_status():
    # Việc chỉ là báo cáo tại cuộc họp (Cái Mép T5): câu hỏi riêng xếp lượt trả lời là "đã báo cáo",
    # nên "đang làm" được sửa thành "done" và "mentioned" được nâng lên "done".
    turns = (_turn("A", "X", "a"), _turn("B", "X", "b"), _turn("C", "X", "c"))
    title = "Báo cáo tình hình các dự án cảng"
    judge = FakeProgressJudge({
        "A": {"da_bao_cao": 0.99, "khac": 0.01},
        "B": {"da_bao_cao": 0.96, "chi_nhac_hoi": 0.04},
        "C": {"chua_co_bao_cao": 0.86, "xin_hoan_bao_cao": 0.14},
    }, report_tasks=frozenset({title}))
    agenda = parse_task_agenda({"tasks": [{"id": k, "title": title, "owner": "A"} for k in ("Q1", "Q2", "Q3")]})
    updates = [
        _update("Q1", "in_progress", "A"),
        _update("Q2", "mentioned", None, evidence_ids=("B",)),
        _update("Q3", "done", "C"),
    ]

    checked = {u.task_id: u for u in check_progress_updates(updates, turns, agenda, judge)}

    assert (checked["Q1"].status, checked["Q1"].proposed_status, checked["Q1"].status_flag) == ("done", "in_progress", "revised")
    assert (checked["Q2"].status, checked["Q2"].status_turn_id, checked["Q2"].status_flag) == ("done", "B", "revised")
    assert (checked["Q3"].status, checked["Q3"].proposed_status, checked["Q3"].status_flag) == ("in_progress", "done", "revised")


def test_decisions_judge_picks_question_by_task_kind_once_per_title():
    client = FakeDecisionsClient({
        "task_kind": lambda text: (
            {"bao_cao_tai_hop": 0.95, "lam_san_pham": 0.05} if "Báo cáo" in text
            else {"bao_cao_tai_hop": 0.35, "lam_san_pham": 0.65}
        ),
        "report_act": {"da_bao_cao": 0.97, "khac": 0.03},
        "progress_act": {"bao_cao_dang_lam": 0.92, "khac": 0.08},
    })
    judge = DecisionsProgressActJudge(client, model="m")
    a, b = _turn("A", "X", "Hiện nay có 3 dự án, đang làm thủ tục."), _turn("B", "X", "b")

    report = judge.judge("Báo cáo tình hình 3 dự án cảng", a, ())
    again = judge.judge("Báo cáo tình hình 3 dự án cảng", a, ())
    later = judge.judge("Báo cáo tình hình 3 dự án cảng", b, (a,))
    product = judge.judge("Trình Ban Thường vụ tờ trình", a, ())

    assert (report.report_task, report.p_status("done")) == (True, 0.97)
    assert again is report and later.report_task
    assert (product.report_task, product.p_status("in_progress")) == (False, 0.92)
    # Mỗi tên việc chỉ xếp kiểu một lần; lượt đã hỏi thì lấy từ cache.
    assert [name for name, _ in client.calls] == ["task_kind", "report_act", "report_act", "task_kind", "progress_act"]
    assert client.calls[0][1] == "VIỆC:\nBáo cáo tình hình 3 dự án cảng"


def test_split_turn_text_keeps_sentences_whole():
    text = "Mở đầu báo cáo. " * 200 + "Việc giải trình ý kiến của Bộ đã xong."

    windows = split_turn_text(text, max_chars=1000)

    assert len(windows) == 4 and all(len(window) <= 1000 for window in windows)
    assert windows[-1].endswith("Việc giải trình ý kiến của Bộ đã xong.")  # câu cuối không bị cắt giữa
    assert " ".join(windows).split() == text.split()
    unpunctuated = split_turn_text("chữ " * 600, max_chars=1000)  # câu dài hơn trần: cắt ở khoảng trắng
    assert all(len(window) <= 1000 for window in unpunctuated) and " ".join(unpunctuated).split() == ["chữ"] * 600
    assert split_turn_text("ngắn") == ("ngắn",)


def test_long_status_turn_is_judged_window_by_window():
    previous = _turn("A", "Y", "đầu lượt trước " * 300 + "CUỐI LƯỢT TRƯỚC")  # > 2500 ký tự
    long_turn = _turn("B", "X", "Báo cáo bối cảnh đề án. " * 120 + "Việc giải trình đã xong.")  # câu nêu trạng thái sau ký tự 2500
    agenda = parse_task_agenda({"tasks": [{"id": "K1", "title": "Giải trình ý kiến", "owner": "A"}]})
    judge = TextProgressJudge()

    (checked,) = check_progress_updates([_update("K1", "done", "B")], (previous, long_turn), agenda, judge)

    assert (checked.status, checked.verification, checked.status_flag) == ("done", "decisions", None)
    (first_len, first_context), (second_len, second_context) = judge.calls
    assert first_len <= MAX_TURN_CHARS and second_len <= MAX_TURN_CHARS
    assert first_context.endswith("CUỐI LƯỢT TRƯỚC") and len(first_context) <= MAX_TURN_CHARS  # ngữ cảnh: phần cuối
    assert second_context.startswith("Báo cáo bối cảnh đề án.")  # đoạn trước làm ngữ cảnh cho đoạn sau


def test_no_judge_keeps_agent_status_unchecked_and_turn_judge_measures_directive():
    turns = (_turn("A", "X", "a"),)
    agenda = parse_task_agenda({"tasks": [{"id": "K1", "title": "k", "owner": "A"}]})

    (checked,) = check_progress_updates([_update("K1", "returned", "A")], turns, agenda, None, FakeTurnJudge({"A": 0.9}))

    assert (checked.status, checked.verification, checked.p_directive) == ("returned", "unchecked", 0.9)


# ---------------------------------------------------------------------------
# Gộp theo việc (finalize)
# ---------------------------------------------------------------------------

MEETING_TURNS = tuple(_turn(f"M{i}", "X", str(i)) for i in range(1, 7))


def test_directive_beats_report_and_conflict_is_flagged():
    agenda = parse_task_agenda({"tasks": [{"id": "K1", "title": "k", "owner": "A", "due": "2026-01-10",
                                           "last_status": "in_progress"}]})
    report = _update("K1", "done", "M5", segment_id="S2", p_directive=0.1, verification="decisions")
    directive = _update("K1", "returned", "M2", segment_id="S1", p_directive=0.95, verification="decisions",
                        deadline_removed=True)

    (progress,) = summarize_task_progress(agenda, [report, directive], MEETING_TURNS, "2026-01-15")

    assert progress.status == "returned"  # chỉ đạo thắng dù nói trước lượt báo cáo
    assert progress.status_conflict and not progress.uncertain
    assert progress.deadline_removed and progress.overdue
    assert [u.status_turn_id for u in progress.updates] == ["M2", "M5"]  # theo thứ tự lượt nói


def test_later_report_wins_and_unreported_task_is_marked():
    early = _update("T1", "blocked", "M1")
    late = _update("T1", "in_progress", "M4", deadline_raw="cuối tháng", deadline_date="2026-10-31",
                   deadline_kind="end_of_period")
    mention = _update("T1", "mentioned", "M6")

    t1, t2 = summarize_task_progress(AGENDA, [late, mention, early], MEETING_TURNS, "2026-10-08")

    assert (t1.status, t1.deciding_update, t1.deadline_date) == ("in_progress", late, "2026-10-31")
    assert not t1.status_conflict  # vướng rồi đang làm: diễn tiến, không mâu thuẫn
    assert (t2.status, t2.updates, t2.overdue) == ("not_reported", (), True)  # hạn 2026-10-01 đã qua


def test_returned_after_in_progress_report_is_not_a_conflict():
    report = _update("T1", "in_progress", "M1", verification="decisions")
    directive = _update("T1", "returned", "M5", p_directive=0.9, verification="decisions")

    t1, _ = summarize_task_progress(AGENDA, [report, directive], MEETING_TURNS, "2026-10-08")

    assert (t1.status, t1.status_conflict) == ("returned", False)


def test_only_uncertain_updates_give_mentioned_and_flag():
    downgraded = _update("T1", "mentioned", "M3", proposed_status="done", status_flag="uncertain")

    t1, _ = summarize_task_progress(AGENDA, [downgraded], MEETING_TURNS, None)

    assert (t1.status, t1.uncertain, t1.status_conflict, t1.overdue) == ("mentioned", True, False, False)


# ---------------------------------------------------------------------------
# Việc giao <-> việc cũ
# ---------------------------------------------------------------------------


def _assignment(task_id=None, assignee=None, deadline_date=None, status="assigned") -> ActionItemV3:
    assignees = (ActorAssignee(mention=assignee, role="lead", name=assignee, actor_type="person"),) if assignee else ()
    return ActionItemV3(segment_id="S1", actor=assignee, text="Làm tiếp", evidence_ids=("T1",), quotes=("...",),
                        deadline_date=deadline_date, task_id=task_id, assignees=assignees, status=status)


def test_assignment_relation_is_derived_from_fields():
    assert link_assignment_to_agenda(_assignment("T1", "Anh Phong"), TaskAgenda()).relation is None
    assert link_assignment_to_agenda(_assignment(None, "Anh Phong"), AGENDA).relation == "new"
    unknown = link_assignment_to_agenda(_assignment("T9", "Anh Phong"), AGENDA)
    assert (unknown.relation, unknown.task_id) == ("new", None)
    assert link_assignment_to_agenda(_assignment("T1", "Chị Mai"), AGENDA).relation == "reassign"
    assert link_assignment_to_agenda(_assignment("T1", "Chị Mai", status="proposed"), AGENDA).relation == "reassign"
    # Một bên khác tự nhận hay báo cáo về việc cũ: không ai giao lại.
    assert link_assignment_to_agenda(_assignment("T1", "Chị Mai", status="self_committed"), AGENDA).relation == "follow_up"
    assert link_assignment_to_agenda(_assignment("T1", "Chị Mai", status="reported"), AGENDA).relation == "follow_up"
    assert link_assignment_to_agenda(_assignment("T1", "Anh Phong", "2026-11-30"), AGENDA).relation == "reschedule"
    assert link_assignment_to_agenda(_assignment("T1", "Anh Phong", "2026-10-31"), AGENDA).relation == "follow_up"
    assert link_assignment_to_agenda(_assignment("T1", None), AGENDA).relation == "follow_up"  # chưa rõ ai: không coi là giao lại


class RecordingActionLLM:
    """LLM giả cho Action agent: ghi system prompt + schema, trả ba việc (task_id "T1", "new", thiếu)."""

    def __init__(self):
        self.calls: list[dict] = []

    def generate_json(self, *, system_prompt, user_prompt, schema):
        self.calls.append({"system_prompt": system_prompt, "schema": schema})
        item = {"evidence_turn_ids": ["A"], "confirm_turn_id": "A", "status": "assigned", "actor": "Hiếu",
                "deadline": None, "deadline_date": None, "deadline_kind": "unknown"}
        return {"action_items": [
            {**item, "text": "Làm tiếp việc cũ", "task_id": "T1"},
            {**item, "text": "Làm việc mới", "task_id": "new"},
            {**item, "text": "Làm việc khác"},
        ]}


def test_action_agent_gets_task_id_field_and_rule_only_with_agenda():
    turns = (_turn("A", "Anh Phong", "Giao Hiếu làm tiếp."),)
    task = {"segment_id": "S1", "title": "", "summary": "", "turns": turns, "previous_context": "", "meeting_date": None}
    llm = RecordingActionLLM()
    extractor = make_extractor("action_agent", llm)

    extractor(task, build_speaker_registry(turns))
    result = extractor(task, build_speaker_registry(turns, agenda=AGENDA))

    without, with_agenda = llm.calls
    # Không có danh sách việc: prompt và schema của Action agent như trước khi có tính năng này.
    assert without["schema"] == ACTION_SCHEMA and without["system_prompt"] == ACTION_SYSTEM_PROMPT
    assert "task_id" not in without["system_prompt"]
    item = with_agenda["schema"]["properties"]["action_items"]["items"]
    assert list(item["properties"])[4:6] == ["text", "task_id"]  # chọn mã sau khi đã viết nội dung việc
    assert item["properties"]["task_id"]["enum"] == ["T1", "T2", "new"] and "task_id" in item["required"]
    assert with_agenda["system_prompt"] == f"{ACTION_SYSTEM_PROMPT}\n\n{ACTION_TASK_ID_RULE}"
    assert [c.task_id for c in result["action_item_candidates_raw"]] == ["T1", None, None]  # "new" -> không gắn việc
    assert "task_id" not in ACTION_SCHEMA["properties"]["action_items"]["items"]["properties"]  # schema gốc không bị sửa


def test_assignments_for_different_tasks_are_not_merged():
    first = ActionItemCandidate("S1", "Hiếu", "Rà soát lại số liệu báo cáo", ("T1",), ("a",), task_id="T1")
    second = ActionItemCandidate("S2", "Hiếu", "Rà soát lại số liệu báo cáo", ("T2",), ("b",), task_id="T2")
    untagged = ActionItemCandidate("S3", "Hiếu", "Rà soát lại số liệu của báo cáo", ("T3",), ("c",))

    merged = merge_duplicate_assignments([first, second, untagged])

    assert [item.task_id for item in merged] == ["T1", "T2"]  # mục không gắn việc gộp vào mục đầu, giữ T1
    assert set(merged[0].evidence_ids) == {"T1", "T3"}


# ---------------------------------------------------------------------------
# End-to-end với LLM giả
# ---------------------------------------------------------------------------


class FakeProgressLLM(FakeLLM):
    """``FakeLLM`` thêm vai agent tiến độ: S3 (T5 "đạt 55%") báo cáo việc T1."""

    @staticmethod
    def _kind(system_prompt, schema):
        if "updates" in schema["properties"]:
            return "progress"
        return FakeLLM._kind(system_prompt, schema)

    def _answer(self, kind, user_prompt):
        if kind == "progress":
            if "[T5|" in user_prompt:
                return {"updates": [{
                    "task_id": "T1", "status": "in_progress", "status_turn_id": "T5", "evidence_turn_ids": ["T5"],
                    "deadline": None, "deadline_date": None, "deadline_kind": "unknown", "deadline_removed": False,
                    "summary": "Đạt khoảng 55% khối lượng.", "blockers": [], "directive": None,
                }]}
            return {"updates": []}
        answer = super()._answer(kind, user_prompt)
        if kind == "action" and "[T1|" in user_prompt:
            answer["action_items"][0]["task_id"] = "T1"
        return answer


def _analyzer(llm, **kwargs) -> MeetingAnalyzerV3:
    return MeetingAnalyzerV3(content_llm=llm, action_llm=llm, decision_llm=llm, verifier_llm=llm,
                             labeler=FakeLabeler(), **kwargs)


def test_pipeline_reports_progress_per_task_with_agenda():
    llm = FakeProgressLLM(verifier_script=[_verifier_final("drop")])
    judge = FakeProgressJudge({"T5": {"bao_cao_dang_lam": 0.92, "chi_nhac_hoi": 0.08}})

    report = _analyzer(llm, progress_judge=judge).analyze(
        meeting_id="M1", meeting_date="2026-10-08", turns=TURNS, segments=SEGMENTS, task_agenda=AGENDA
    )

    assert llm.calls.count("progress") == len(SEGMENTS)  # mọi chủ đề, không lọc theo từ khoá
    t1, t2 = report.task_progress
    assert (t1.task_id, t1.status, t1.deciding_update.verification) == ("T1", "in_progress", "decisions")
    assert (t2.status, t2.overdue) == ("not_reported", True)
    assert judge.calls == [("Đẩy nhanh khối lượng thi công", "T5")]
    (assignment,) = report.assignments
    assert (assignment.task_id, assignment.relation) == ("T1", "reassign")  # T1 của Anh Phong, giao cho Hiếu


def test_pipeline_without_agenda_makes_no_progress_calls():
    llm = FakeProgressLLM(verifier_script=[_verifier_final("drop")])

    report = _analyzer(llm).analyze(meeting_id="M1", turns=TURNS, segments=SEGMENTS)

    assert "progress" not in llm.calls
    assert report.task_progress == ()
    assert all(getattr(a, "relation", None) is None for a in report.assignments)


def test_progress_llm_can_be_a_separate_adapter():
    main = FakeProgressLLM(verifier_script=[_verifier_final("drop")])
    progress = FakeProgressLLM()

    _analyzer(main, progress_llm=progress).analyze(meeting_id="M1", turns=TURNS, segments=SEGMENTS, task_agenda=AGENDA)

    assert "progress" not in main.calls and progress.calls.count("progress") == len(SEGMENTS)
