"""Kiểm phần danh sách việc cần báo cáo và tiến độ: đọc file danh sách, agent giao việc ghi tiến độ,
kiểm và gộp tiến độ.

Không gọi mạng: mô hình và bộ phân loại đều được giả lập trả kết quả định sẵn.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ...utils.contracts import SpeakerTurn
from ...utils.ports import LLMUpstreamError
from ..run import MeetingAnalyzer
from ..shared.meeting_inputs.agenda import (
    load_task_agenda,
    parse_task_agenda,
    task_path_for,
)
from ..shared.meeting_inputs.attendees import parse_attendee_roster
from ..shared.prompts import ACTION_AGENDA_RULE, ACTION_SYSTEM_PROMPT
from ..shared.schemas import AssigneeMention, ProgressUpdate
from ..step4_extract.action import ACTION_SCHEMA
from ..step4_extract.extractors import call_extractor, render_system_prompt
from ..step4_extract.registry import (
    build_speaker_registry,
    format_registry_context,
)
from ..step5_verify.check.progress_check import check_progress_updates
from ..shared.judges.progress_act import (
    DecisionsApiProgressActJudge,
    ProgressActJudgement,
)
from ..shared.judges.turn_act import (
    MAX_TURN_CHARS,
    TurnActJudgement,
    split_turn_text,
)
from ..step6_finalize.progress_merge import merge_task_progress
from .test_pipeline import (
    SEGMENTS,
    TURN_JUDGE,
    TURNS,
    FakeLabeler,
    FakeLLM,
    _has_turn,
    _verifier_final,
)

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
    return SpeakerTurn(turn_id, speaker, text, None, None)


def _update(task_id: str, status: str, turn_id: str | None, segment_id: str = "S1", **changes) -> ProgressUpdate:
    evidence_turn_ids = changes.pop("evidence_turn_ids", (turn_id,) if turn_id else ("T1",))
    return ProgressUpdate(
        segment_id=segment_id, task_id=task_id, status=status, status_turn_id=turn_id,
        evidence_turn_ids=evidence_turn_ids, quotes=("...",) * len(evidence_turn_ids), **changes,
    )


class FakeProgressJudge:
    """Decisions API giả cho lượt nêu trạng thái: turn_id -> phân bố, hoặc exception.

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
    """Client Decisions API giả: tên câu hỏi -> phân bố (hoặc hàm của input); ghi (tên câu hỏi, input)."""

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
    """Decisions API giả xét theo nội dung: đoạn có "đã xong" là báo cáo xong, còn lại không nói về việc.

    Ghi lại (độ dài đoạn, nội dung lượt ngữ cảnh cuối) của mỗi lời gọi.
    """

    def __init__(self):
        self.calls: list[tuple[int, str]] = []

    def judge(self, task_title, turn, context):
        self.calls.append((len(turn.text_exact), context[-1].text_exact if context else ""))
        if "đã xong" in turn.text_exact:
            return ProgressActJudgement("reported_done", {"reported_done": 0.9, "other": 0.1})
        return ProgressActJudgement("other", {"other": 0.95, "mention_only": 0.05})


class FakeTurnJudge:
    """Decisions API giả cho lượt chốt: turn_id -> p_commit."""

    def __init__(self, p_commit: dict[str, float]):
        self.p_commit = p_commit

    def judge(self, turn, context):
        p = self.p_commit[turn.turn_id]
        return TurnActJudgement(label="conclusion", probabilities={"conclusion": p, "discussion": 1 - p})


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

    from ..shared.meeting_inputs.attendees import load_attendee_roster

    transcript = Path(__file__).resolve().parents[3] / "inputs" / "bien-ban-vdt-trang-copy-v1.json"
    agenda = load_task_agenda(transcript, load_attendee_roster(transcript))

    assert agenda.task_ids == ("T1", "T3", "T5", "X1")


def test_registry_context_shows_agenda_tasks():
    context = format_registry_context(build_speaker_registry(TURNS, agenda=AGENDA))
    assert '<task id="T1" lead="Anh Phong" deadline="2026-10-31"' in context
    assert "Đẩy nhanh khối lượng thi công</task>" in context


# ---------------------------------------------------------------------------
# Action agent: đọc phần tiến độ (updates)
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
            "meeting_context": "", "meeting_date": "2026-10-08"}


def test_action_agent_reads_updates_validating_task_ids_and_turns():
    turns = (TURNS[4], TURNS[5])
    llm = _ScriptedLLM({"action_items": [], "updates": {
        "T9": {"status": "done", "status_turn_id": "T5", "evidence_segment_ids": ["T5"]},
        "T1": {"status": "in_progress", "status_turn_id": "T5", "evidence_segment_ids": ["T5", "T6"],
               "deadline": None, "deadline_extended": True, "summary": "Đạt 55%.",
               "blockers": ["", "thiếu vốn", "a", "b"],
               "assignees": [{"name": "Sở Xây dựng", "role": "lead", "type": "organization"}]},
        "T2": {"status": "done", "status_turn_id": "T1", "evidence_segment_ids": []},
    }})
    task = {**_task(turns), "meeting_context": format_registry_context(build_speaker_registry(TURNS, agenda=AGENDA))}

    result = call_extractor("action_agent", llm, task, build_speaker_registry(TURNS, agenda=AGENDA))

    (update,) = result["progress_updates_raw"]  # T9 lạ, T2 không có bằng chứng thuộc đoạn
    assert (update.task_id, update.status, update.status_turn_id) == ("T1", "in_progress", "T5")
    assert update.evidence_turn_ids == ("T5", "T6")
    assert update.deadline_extended and update.blockers == ("thiếu vốn", "a")
    assert update.mentions == (AssigneeMention("Sở Xây dựng", "lead", "organization"),)
    (call,) = llm.calls  # MỘT lời gọi cho cả việc giao lẫn tiến độ
    updates_schema = call["schema"]["properties"]["updates"]
    assert updates_schema["required"] == ["T1", "T2"]  # mỗi việc một mục bắt buộc
    assert "not_discussed" in updates_schema["properties"]["T1"]["properties"]["status"]["enum"]
    assert "<progress_tasks>" in call["user"]


def test_action_agent_reads_member_request_turn_into_evidence():
    turns = (TURNS[4], TURNS[5])
    llm = _ScriptedLLM({"action_items": [], "updates": {
        "T1": {"status": "cancelled", "status_turn_id": "T6", "request_turn_id": "T5",
               "evidence_segment_ids": ["T6"]},
        "T2": {"status": "cancelled", "status_turn_id": "T6", "request_turn_id": "T6",
               "evidence_segment_ids": ["T6"]},
    }})
    task = {**_task(turns), "meeting_context": ""}

    result = call_extractor("action_agent", llm, task, build_speaker_registry(TURNS, agenda=AGENDA))

    t1, t2 = result["progress_updates_raw"]
    assert (t1.request_turn_id, t1.evidence_turn_ids) == ("T5", ("T5", "T6"))  # lượt đề xuất vào bằng chứng
    assert t2.request_turn_id is None  # trùng lượt nêu trạng thái: không phải đề xuất riêng


def test_action_agent_skips_not_discussed_tasks():
    turns = (TURNS[4], TURNS[5])
    llm = _ScriptedLLM({"action_items": [], "updates": {
        "T1": {"status": "not_discussed", "status_turn_id": None, "evidence_segment_ids": []},
        "T2": {"status": "not_discussed", "status_turn_id": "T5", "evidence_segment_ids": ["T5"]},
    }})

    result = call_extractor("action_agent", llm, _task(turns), build_speaker_registry(TURNS, agenda=AGENDA))

    assert result["progress_updates_raw"] == []


def test_action_agent_without_agenda_ignores_updates():
    llm = _ScriptedLLM({"action_items": [], "updates": {
        "T1": {"status": "done", "status_turn_id": "T5", "evidence_segment_ids": ["T5"]},
    }})

    result = call_extractor("action_agent", llm, _task((TURNS[4],)), build_speaker_registry(TURNS))

    assert result["progress_updates_raw"] == []
    assert "updates" not in llm.calls[0]["schema"]["properties"]


def test_action_agent_reports_llm_error_as_failure():
    registry = build_speaker_registry(TURNS, agenda=AGENDA)
    result = call_extractor("action_agent", _ScriptedLLM(LLMUpstreamError("down")), _task(TURNS[4:]), registry)

    assert result["progress_updates_raw"] == [] and result["action_item_candidates_raw"] == []
    assert result["topic_failures"][0].agent == "action_agent"


# ---------------------------------------------------------------------------
# Kiểm lượt nêu trạng thái
# ---------------------------------------------------------------------------


def test_decisions_confirms_or_sends_to_verifier():
    turns = (_turn("A", "X", "a"), _turn("B", "X", "b"), _turn("C", "X", "c"), _turn("D", "X", "d"))
    judge = FakeProgressJudge({
        "A": {"reported_in_progress": 0.9, "other": 0.1},
        "B": {"redo_requested": 0.85, "reported_done": 0.15},
        "C": {"reported_done": 0.5, "mention_only": 0.5},
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

    assert [u.task_id for u, _ in checked] == ["K1", "K2", "K3", "K4", "K5"]  # kiểm song song, giữ thứ tự
    assert [u for u, _ in checked] == updates  # chỉ gắn nhãn, không sửa cập nhật nào
    verdicts = {u.task_id: flag.verdict for u, flag in checked}
    # Decisions API chắc chắn là trạng thái khác / lỗi / không có lượt: Verifier quyết định.
    assert verdicts == {"K1": "clear", "K2": "uncertain", "K3": "uncertain", "K4": "uncertain", "K5": "uncertain"}
    # Chỉ xét đúng lượt agent khai.
    assert sorted(call[1] for call in judge.calls) == ["A", "B", "C", "D"]


def test_status_ranked_first_by_decisions_is_confirmed_below_clear_threshold():
    # Nhiều lựa chọn quy về cùng một trạng thái: in_progress = redo_requested + reported_in_progress.
    turns = (_turn("A", "X", "a"), _turn("B", "X", "b"))
    judge = FakeProgressJudge({
        "A": {"redo_requested": 0.4, "reported_in_progress": 0.25, "reported_done": 0.25, "mention_only": 0.1},
        "B": {"reported_done": 0.45, "redo_requested": 0.4, "other": 0.15},
    })
    agenda = parse_task_agenda({"tasks": [{"id": k, "title": k, "owner": "A"} for k in ("K1", "K2")]})

    verdicts = {u.task_id: flag.verdict for u, flag in check_progress_updates(
        [_update("K1", "in_progress", "A"), _update("K2", "in_progress", "B")], turns, agenda, judge
    )}

    assert verdicts == {"K1": "clear", "K2": "uncertain"}


class LabelTurnJudge:
    """Decisions API giả cho turn_act: turn_id -> nhãn cao nhất (0.9)."""

    def __init__(self, labels: dict[str, str]):
        self.labels = labels

    def judge(self, turn, context):
        label = self.labels[turn.turn_id]
        return TurnActJudgement(label=label, probabilities={label: 0.9, "other": 0.1})


def test_confirmed_status_at_a_proposal_turn_goes_to_verifier():
    # Cái Mép lượt 26: thành viên viện dẫn góp ý của Bộ để đề nghị việc khác; progress_act đọc thành "làm lại".
    turns = (_turn("A", "X", "a"), _turn("B", "Y", "b"))
    judge = FakeProgressJudge({"A": {"redo_requested": 0.9, "other": 0.1}, "B": {"reported_done": 0.9, "other": 0.1}})
    agenda = parse_task_agenda({"tasks": [{"id": k, "title": k, "owner": "A"} for k in ("K1", "K2")]})
    updates = [_update("K1", "in_progress", "A"), _update("K2", "done", "B")]

    checked = check_progress_updates(updates, turns, agenda, judge,
                                     turn_judge=LabelTurnJudge({"A": "proposal", "B": "discussion"}))

    flags = {u.task_id: flag for u, flag in checked}
    assert (flags["K1"].verdict, flags["K2"].verdict) == ("uncertain", "clear")
    assert "đề xuất" in flags["K1"].reasons[0]


def test_mention_is_kept_as_is_without_asking():
    turns = (_turn("A", "X", "a"),)
    judge = FakeProgressJudge({"A": {"reported_in_progress": 0.9, "other": 0.1}})
    agenda = parse_task_agenda({"tasks": [{"id": "M1", "title": "M1", "owner": "A"}]})

    raw = _update("M1", "mentioned", None, evidence_turn_ids=("A",))
    ((checked, flag),) = check_progress_updates([raw], turns, agenda, judge)

    assert (checked, flag.verdict) == (raw, "clear")
    assert judge.calls == []


def test_report_task_question_confirms_report_status():
    # Việc chỉ là báo cáo tại cuộc họp (Cái Mép T5): câu hỏi riêng xếp lượt trả lời là "đã báo cáo".
    turns = (_turn("A", "X", "a"),)
    title = "Báo cáo tình hình các dự án cảng"
    judge = FakeProgressJudge({"A": {"report_given": 0.99, "other": 0.01}}, report_tasks=frozenset({title}))
    agenda = parse_task_agenda({"tasks": [{"id": "Q1", "title": title, "owner": "A"}]})

    ((_, flag),) = check_progress_updates([_update("Q1", "done", "A")], turns, agenda, judge)

    assert flag.verdict == "clear"


def test_decisions_judge_picks_question_by_task_kind_once_per_title():
    client = FakeDecisionsClient({
        "task_kind": lambda text: (
            {"report_at_meeting": 0.95, "deliverable": 0.05} if "Báo cáo" in text
            else {"report_at_meeting": 0.35, "deliverable": 0.65}
        ),
        "report_act": {"report_given": 0.97, "other": 0.03},
        "progress_act": {"reported_in_progress": 0.92, "other": 0.08},
    })
    judge = DecisionsApiProgressActJudge(client, model="m")
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
    assert client.calls[0][1] == "TASK:\nBáo cáo tình hình 3 dự án cảng"


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

    ((_, flag),) = check_progress_updates([_update("K1", "done", "B")], (previous, long_turn), agenda, judge)

    assert flag.verdict == "clear"
    (first_len, first_context), (second_len, second_context) = judge.calls
    assert first_len <= MAX_TURN_CHARS and second_len <= MAX_TURN_CHARS
    assert first_context == previous.text_exact  # ngữ cảnh gửi nguyên văn, không rút gọn
    assert second_context.startswith("Báo cáo bối cảnh đề án.")  # đoạn trước làm ngữ cảnh cho đoạn sau


def test_no_judge_sends_agent_status_to_verifier_unchanged():
    turns = (_turn("A", "X", "a"),)
    agenda = parse_task_agenda({"tasks": [{"id": "K1", "title": "k", "owner": "A"}]})
    raw = _update("K1", "in_progress", "A")

    ((checked, flag),) = check_progress_updates([raw], turns, agenda, None)

    assert (checked, flag.verdict) == (raw, "uncertain")


# ---------------------------------------------------------------------------
# Gộp theo việc (finalize)
# ---------------------------------------------------------------------------

MEETING_TURNS = tuple(_turn(f"M{i}", "X", str(i)) for i in range(1, 7))


def _merge(agenda, updates, turns=MEETING_TURNS, meeting_date=None, roster=None, turn_judge=None):
    registry = build_speaker_registry(turns, roster, agenda=agenda)
    return merge_task_progress(agenda, updates, registry, turns, meeting_date, turn_judge=turn_judge)


def test_directive_beats_report_and_conflict_is_flagged():
    agenda = parse_task_agenda({"tasks": [{"id": "K1", "title": "k", "owner": "A", "due": "2026-01-10",
                                           "last_status": "in_progress"}]})
    report = _update("K1", "done", "M5", segment_id="S2")
    directive = _update("K1", "in_progress", "M2", segment_id="S1", deadline_extended=True)

    # finalize tự hỏi Decisions API lượt nào là chỉ đạo/kết luận.
    (progress,) = _merge(agenda, [report, directive], meeting_date="2026-01-15",
                         turn_judge=FakeTurnJudge({"M5": 0.1, "M2": 0.95}))

    assert progress.status == "in_progress"  # chỉ đạo thắng dù nói trước lượt báo cáo
    assert progress.status_conflict and not progress.uncertain
    assert progress.deadline_extended and progress.overdue
    assert [u.status_turn_id for u in progress.updates] == ["M2", "M5"]  # theo thứ tự lượt nói


def test_later_report_wins_and_unreported_task_is_marked():
    early = _update("T1", "in_progress", "M1")
    late = _update("T1", "in_progress", "M4", deadline_raw="cuối tháng", deadline_date="2026-10-31",
                   deadline_kind="end_of_period")
    mention = _update("T1", "mentioned", "M6")

    t1, t2 = _merge(AGENDA, [late, mention, early], meeting_date="2026-10-08")

    assert (t1.status, t1.deciding_update, t1.deadline_date) == ("in_progress", late, "2026-10-31")
    assert not t1.status_conflict  # hai lời cùng đang thực hiện: không mâu thuẫn
    assert (t2.status, t2.updates, t2.overdue) == ("not_reported", (), True)  # hạn 2026-10-01 đã qua
    assert (t1.assignees, t1.reassign_update) == ((), None)  # không ai giao lại: giữ bên cũ


def test_redo_directive_after_in_progress_report_is_not_a_conflict():
    report = _update("T1", "in_progress", "M1")
    directive = _update("T1", "in_progress", "M5")

    t1, _ = _merge(AGENDA, [report, directive], meeting_date="2026-10-08", turn_judge=FakeTurnJudge({"M1": 0.1, "M5": 0.9}))

    assert (t1.status, t1.status_conflict) == ("in_progress", False)


def test_only_fallback_updates_keep_agent_status_flagged_uncertain():
    # Verifier không kết luận được (lỗi LLM/chưa đồng thuận): giữ trạng thái agent khai, gắn cờ chưa chắc.
    fallback = _update("T1", "done", "M3", verification="fallback")

    t1, _ = _merge(AGENDA, [fallback])

    assert (t1.status, t1.uncertain, t1.status_conflict, t1.overdue) == ("done", True, False, False)


def test_latest_reassignment_names_the_new_owner():
    early = _update("T1", "mentioned", "M1", mentions=(AssigneeMention("Hiếu", "lead"),))
    late = _update("T1", "mentioned", "M4", mentions=(AssigneeMention("Đảng ủy ban", "lead", "organization"),))
    report = _update("T1", "in_progress", "M6", verification="decisions")

    t1, _ = _merge(AGENDA, [report, late, early], roster=ROSTER)

    assert t1.status == "in_progress" and t1.reassign_update is late  # lời giao muộn nhất
    assert [(a.mention, a.name, a.ref_id) for a in t1.assignees] == [("Đảng ủy ban", "Đảng ủy UBND Thành phố", "O2")]


def test_naming_the_old_owner_again_is_not_a_reassignment():
    same = _update("T1", "in_progress", "M2", mentions=(AssigneeMention("Anh Phong", "lead"),))

    t1, _ = _merge(AGENDA, [same])

    assert (t1.assignees, t1.reassign_update) == ((), None)


def test_action_agent_gets_updates_and_rule_only_with_agenda():
    turns = (_turn("A", "Anh Phong", "Giao Hiếu làm việc mới."),)
    task = {"segment_id": "S1", "title": "", "summary": "", "turns": turns, "meeting_context": "", "meeting_date": None}
    llm = _ScriptedLLM({"action_items": [], "updates": {}})
    call_extractor("action_agent", llm, task, build_speaker_registry(turns))
    call_extractor("action_agent", llm, task, build_speaker_registry(turns, agenda=AGENDA))

    without, with_agenda = llm.calls
    # Không có danh sách việc: prompt và schema của Action agent như trước khi có tính năng này.
    assert without["schema"] == ACTION_SCHEMA
    assert without["system"] == render_system_prompt(ACTION_SYSTEM_PROMPT, ACTION_SCHEMA)
    assert "updates" not in without["schema"]["properties"]
    # Có danh sách: chỉ thêm updates, ĐỨNG ĐẦU schema; việc giao không mang mã việc cũ.
    assert list(with_agenda["schema"]["properties"]) == ["updates", "member_requests", "action_items", "summary_turn_id"]
    assert with_agenda["schema"]["required"][0] == "updates"
    assert with_agenda["schema"]["properties"]["action_items"] == ACTION_SCHEMA["properties"]["action_items"]
    update = with_agenda["schema"]["properties"]["updates"]["properties"]["T1"]
    assert "assignees" in update["properties"] and "assignees" in update["required"]
    assert with_agenda["system"] == render_system_prompt(
        ACTION_SYSTEM_PROMPT, with_agenda["schema"], progress=ACTION_AGENDA_RULE
    )
    assert ACTION_AGENDA_RULE not in without["system"]
    assert "updates" not in ACTION_SCHEMA["properties"]  # schema gốc không bị sửa


# ---------------------------------------------------------------------------
# End-to-end với LLM giả
# ---------------------------------------------------------------------------


class FakeProgressLLM(FakeLLM):
    """``FakeLLM`` có phần tiến độ của Action agent: S3 (T5 "đạt 55%") báo cáo việc T1.

    ``progress_calls`` đếm lời gọi Action agent có mảng ``updates`` trong schema.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.progress_calls = 0

    def generate_json(self, *, system_prompt, user_prompt, schema):
        answer = super().generate_json(system_prompt=system_prompt, user_prompt=user_prompt, schema=schema)
        if "updates" not in schema["properties"]:
            return answer
        with self._lock:
            self.progress_calls += 1
        updates = {}
        if _has_turn(user_prompt, "T5"):
            updates = {"T1": {
                "status": "in_progress", "status_turn_id": "T5", "evidence_segment_ids": ["T5"],
                "deadline": None, "deadline_date": None, "deadline_kind": "unknown", "deadline_extended": False,
                "assignees": [], "summary": "Đạt khoảng 55% khối lượng.", "blockers": [], "directive": None,
            }}
        return {**answer, "updates": updates}


def _analyzer(llm, **kwargs) -> MeetingAnalyzer:
    return MeetingAnalyzer(content_llm=llm, action_llm=llm, decision_llm=llm, verifier_llm=llm,
                             labeler=FakeLabeler(), **{"turn_judge": TURN_JUDGE, **kwargs})


def test_pipeline_reports_progress_per_task_with_agenda():
    llm = FakeProgressLLM(verifier_script=[_verifier_final("drop")])
    judge = FakeProgressJudge({"T5": {"reported_in_progress": 0.92, "mention_only": 0.08}})

    report = _analyzer(llm, progress_judge=judge).analyze(
        meeting_id="M1", meeting_date="2026-10-08", turns=TURNS, segments=SEGMENTS, task_agenda=AGENDA
    )

    # Mọi chủ đề, không lọc theo từ khoá; tiến độ đi cùng lời gọi Action, không có lời gọi riêng.
    assert llm.progress_calls == llm.calls.count("action") == len(SEGMENTS)
    t1, t2 = report.task_progress
    assert (t1.task_id, t1.status, t1.deciding_update.verification) == ("T1", "in_progress", "rule")  # clear: evidence check không ghi gì lên cập nhật
    assert (t2.status, t2.overdue) == ("not_reported", True)
    assert judge.calls == [("Đẩy nhanh khối lượng thi công", "T5")]


def test_pipeline_without_agenda_makes_no_progress_calls():
    llm = FakeProgressLLM(verifier_script=[_verifier_final("drop")])

    report = _analyzer(llm).analyze(meeting_id="M1", turns=TURNS, segments=SEGMENTS)

    assert llm.progress_calls == 0
    assert report.task_progress == ()


def test_progress_only_part_drops_assignments_from_the_shared_call():
    llm = FakeProgressLLM(verifier_script=[_verifier_final("drop")])
    judge = FakeProgressJudge({"T5": {"reported_in_progress": 0.92, "mention_only": 0.08}})

    report = _analyzer(llm, progress_judge=judge).analyze(
        meeting_id="M1", turns=TURNS, segments=SEGMENTS, task_agenda=AGENDA, parts={"progress"}
    )

    assert llm.progress_calls == len(SEGMENTS)
    assert report.assignments == () and "verifier" not in llm.calls  # việc giao bị bỏ, không đi Verifier
    assert report.task_progress[0].status == "in_progress"


class FakeProgressVerifierLLM(FakeProgressLLM):
    """Như ``FakeProgressLLM``, thêm Verifier tiến độ (schema có ``revised_status``) trả lời theo kịch bản."""

    def __init__(self, progress_script, **kwargs):
        super().__init__(**kwargs)
        self.progress_script = list(progress_script)

    def generate_json(self, *, system_prompt, user_prompt, schema):
        if "revised_status" in schema["properties"]:
            with self._lock:
                self.calls.append("progress_verifier")
                return self.progress_script.pop(0)
        return super().generate_json(system_prompt=system_prompt, user_prompt=user_prompt, schema=schema)


def test_pipeline_sends_unconfirmed_progress_to_verifier():
    # JEV không xác nhận "in_progress" ở T5 -> Verifier tra lại, giữ trạng thái kèm lượt T5.
    keep = {"thought": "đủ", "action": "final", "argument": None, "deciding_turn_id": "T5", "verdict": "keep",
            "revised_status": None, "reasoning": "T5 báo đạt 55%."}
    llm = FakeProgressVerifierLLM([keep], verifier_script=[_verifier_final("drop")])
    judge = FakeProgressJudge({"T5": {"mention_only": 0.6, "reported_in_progress": 0.4}})

    report = _analyzer(llm, progress_judge=judge).analyze(
        meeting_id="M1", meeting_date="2026-10-08", turns=TURNS, segments=SEGMENTS, task_agenda=AGENDA
    )

    assert llm.calls.count("progress_verifier") == 1
    t1 = next(task for task in report.task_progress if task.task_id == "T1")
    assert (t1.status, t1.deciding_update.verification) == ("in_progress", "consensus")
    assert any(record.kind == "progress" and record.verdict == "keep" for record in report.verification_records)
