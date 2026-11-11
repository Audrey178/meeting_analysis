"""Kiểm việc gửi các cập nhật tiến độ bị nghi ngờ cho agent kiểm chứng, và vòng trao đổi giữa agent
kiểm chứng với agent giao việc.

Không gọi mạng: mô hình giả trả lời theo kịch bản cho từng bên.
"""

from __future__ import annotations

from dataclasses import replace

from ...utils.contracts import SpeakerTurn
from ...utils.ports import LLMUpstreamError
from ..config import AnalysisConfig
from ..graph.nodes import verifier as verifier_node
from ..shared.judges.progress_act import ProgressActJudgement
from ..shared.judges.turn_act import ProposalResponseJudgement
from ..shared.meeting_inputs.agenda import parse_task_agenda
from ..shared.meeting_inputs.attendees import MeetingChair
from ..shared.schemas import AssigneeMention, ProgressUpdate
from ..step4_extract.registry import build_speaker_registry
from ..step5_verify.check.evidence_check import check_topic_candidates
from ..step5_verify.verifier.progress_verifier import ProgressVerifier

TURNS = (
    SpeakerTurn("TURN_000001", "Phạm Hồng Sơn", "Đề nghị các đơn vị báo cáo lần lượt.", None, None),
    SpeakerTurn("TURN_000002", "Đỗ Thanh Phong",
                "Sở Xây dựng đã hoàn thành báo cáo đề xuất chủ trương đầu tư, nhưng còn vướng việc bố trí "
                "vốn đối ứng nên chưa trình được.", None, None),
    SpeakerTurn("TURN_000003", "Lê Văn Sơn", "Sở Tài chính đang rà soát khả năng cân đối vốn.", None, None),
    SpeakerTurn("TURN_000004", "Phạm Hồng Sơn", "Có vốn rồi thì Sở Xây dựng trình chủ trương đầu tư ngay.", None, None),
)
AGENDA = parse_task_agenda({"tasks": [
    {"id": "X1", "title": "Trình chủ trương đầu tư tuyến đường sắt Biên Hòa – Vũng Tàu", "owner": "Sở Xây dựng"},
]})
REGISTRY = build_speaker_registry(TURNS, agenda=AGENDA)
SEGMENT_ID = "TOPIC_SEG_000000"


def _uncertain(status_turn_id: str | None = "TURN_000002") -> ProgressUpdate:
    """Cập nhật agent khai "cancelled" mà JEV không xác nhận; evidence-check gửi đi NGUYÊN VẸN."""

    return ProgressUpdate(
        segment_id=SEGMENT_ID, task_id="X1", status="cancelled", status_turn_id=status_turn_id,
        evidence_turn_ids=("TURN_000002",), quotes=("...",),
    )


def _task(update: ProgressUpdate) -> dict:
    return {
        "item_key": f"{SEGMENT_ID}:progress:X1", "segment_id": SEGMENT_ID, "kind": "progress",
        "candidate": update, "reasons": ("Decisions API không xác nhận cancelled.",), "turns": TURNS, "meeting_turns": TURNS,
        "registry": REGISTRY,
    }


class ScriptLLM:
    """Trả lời lần lượt theo kịch bản; schema có ``stance`` là Proposer, còn lại là Verifier."""

    def __init__(self, verifier=(), proposer=()):
        self.verifier, self.proposer = list(verifier), list(proposer)
        self.calls: list[str] = []

    def generate_json(self, *, system_prompt, user_prompt, schema):
        role = "proposer" if "stance" in schema["properties"] else "verifier"
        self.calls.append(role)
        answer = (self.proposer if role == "proposer" else self.verifier).pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _final(verdict: str, turn_id: str | None = None, revised_status: str | None = None, assignees=()) -> dict:
    return {"thought": "đủ", "action": "final", "argument": None, "deciding_turn_id": turn_id,
            "verdict": verdict, "revised_status": revised_status, "revised_assignees": list(assignees),
            "actor_reason": "Chủ trì giao ở lượt 4" if assignees else None, "reasoning": "căn cứ"}


def _stance(stance: str, turn_id: str | None = None, revised_status: str | None = None, assignees=()) -> dict:
    return {"confirm_turn_id": turn_id, "stance": stance, "revised_status": revised_status,
            "revised_assignees": list(assignees), "argument": "lý do"}


def _run(llm: ScriptLLM, update: ProgressUpdate | None = None, **config) -> dict:
    return ProgressVerifier(llm, llm, AnalysisConfig(**config)).run(_task(update or _uncertain()))


# ---- định tuyến ở evidence-check ----

def _check(raw: list[ProgressUpdate]) -> dict:
    return check_topic_candidates(SEGMENT_ID, TURNS, TURNS, REGISTRY, [], [], raw)


def test_evidence_check_sends_unchecked_progress_to_verifier_untouched():
    # Không có JEV: trạng thái agent khai chưa kiểm được -> đi Verifier như việc giao, cập nhật giữ nguyên.
    raw = _uncertain()
    result = _check([raw])
    assert result["progress_updates"] == []
    [task] = result["pending_verify"]
    assert task["kind"] == "progress" and task["item_key"] == f"{SEGMENT_ID}:progress:X1"
    assert task["candidate"] == raw


def test_evidence_check_passes_self_declared_mention_as_clear():
    raw = replace(_uncertain(), status="mentioned")
    result = _check([raw])
    assert result["progress_updates"] == [raw] and result["pending_verify"] == ()


# ---- định tuyến: tiếp nhận đề xuất và bên nhận việc (như việc giao) ----

MEMBER_TURNS = (
    SpeakerTurn("TURN_000001", "Đỗ Thanh Phong", "Đề nghị lùi việc trình chủ trương sang quý sau.", None, None),
    SpeakerTurn("TURN_000002", "Phạm Hồng Sơn", "Đồng ý.", None, None),
)
CHAIR_REGISTRY = build_speaker_registry(MEMBER_TURNS, agenda=AGENDA, chair=MeetingChair("C1", "Phạm Hồng Sơn"))


class ProposalJudge:
    """JEV giả: lượt nêu trạng thái không tự xác nhận "cancelled"; lượt TURN_000002 phản hồi đề xuất theo ``label``."""

    def __init__(self, label: str):
        self.label = label

    def judge(self, task_title, turn, context):  # progress_act
        return ProgressActJudgement("mention_only", {"mention_only": 0.9, "other": 0.1})

    def judge_response(self, claim, proposal, response):  # turn_act
        return ProposalResponseJudgement(self.label, {self.label: 0.9, "no_response": 0.1})


def _cancelled(**changes) -> ProgressUpdate:
    return ProgressUpdate(
        segment_id=SEGMENT_ID, task_id="X1", status="cancelled", status_turn_id="TURN_000002",
        evidence_turn_ids=("TURN_000001", "TURN_000002"), quotes=("...", "..."), **changes,
    )


def _check_member(update: ProgressUpdate, label: str) -> dict:
    judge = ProposalJudge(label)
    return check_topic_candidates(SEGMENT_ID, MEMBER_TURNS, MEMBER_TURNS, CHAIR_REGISTRY, [], [], [update],
                                  turn_judge=judge, progress_judge=judge)


def test_member_proposal_accepted_by_chair_is_clear():
    update = _cancelled(request_turn_id="TURN_000001")
    result = _check_member(update, "direct_acceptance")
    assert result["progress_updates"] == [update] and result["pending_verify"] == ()


def test_member_proposal_rejected_by_chair_goes_to_verifier():
    result = _check_member(_cancelled(request_turn_id="TURN_000001"), "rejection")
    [task] = result["pending_verify"]
    assert any("bác nội dung" in reason for reason in task["reasons"])


def test_without_request_turn_the_acceptance_is_not_checked():
    [task] = _check_member(_cancelled(), "direct_acceptance")["pending_verify"]
    assert all("tiếp nhận" not in reason for reason in task["reasons"])


def test_reassignment_to_unknown_party_goes_to_verifier_even_when_status_is_mentioned():
    update = replace(_uncertain(), status="mentioned", mentions=(AssigneeMention("hộ dân", "lead"),))
    [task] = _check([update])["pending_verify"]
    assert any("không khớp người/đơn vị nào" in reason for reason in task["reasons"])


# ---- Verifier: cùng khuôn với việc giao/kết luận ----

def test_keep_keeps_agent_claim_untouched():
    # Verifier chỉ ra lượt khác cũng không ghi đè lượt agent khai (Verifier không sửa cập nhật).
    result = _run(ScriptLLM(verifier=[_final("keep", "TURN_000004")]))
    [update] = result["progress_updates"]
    assert (update.status, update.status_turn_id, update.verification) == ("cancelled", "TURN_000002", "consensus")
    [record] = result["verification_records"]
    assert (record.kind, record.verdict, record.deciding_turn_id) == ("progress", "keep", "TURN_000004")


def test_revise_accepted_by_action_agent_with_its_own_turn():
    llm = ScriptLLM(verifier=[_final("revise", "TURN_000004", "in_progress")],
                    proposer=[_stance("accept", "TURN_000004", revised_status="in_progress")])
    [update] = _run(llm)["progress_updates"]
    assert (update.status, update.status_turn_id) == ("in_progress", "TURN_000004")
    assert update.evidence_turn_ids == ("TURN_000002", "TURN_000004")


def test_verifier_suggestion_is_not_applied_when_agent_does_not_write_it():
    llm = ScriptLLM(verifier=[_final("revise", "TURN_000004", "in_progress")], proposer=[_stance("accept")])
    [update] = _run(llm)["progress_updates"]
    assert (update.status, update.status_turn_id) == ("cancelled", "TURN_000002")


def test_revise_with_same_status_is_keep():
    result = _run(ScriptLLM(verifier=[_final("revise", "TURN_000002", "cancelled")]))
    assert result["verification_records"][0].verdict == "keep"


def test_verifier_suggests_new_assignee_and_agent_writes_it():
    sxd = {"name": "Sở Xây dựng", "role": "lead", "type": "organization"}
    stc = {"name": "Sở Tài chính", "role": "lead", "type": "organization"}
    claim = replace(_uncertain(), mentions=(AssigneeMention("Sở Xây dựng", "lead", "organization"),))
    llm = ScriptLLM(verifier=[_final("keep", "TURN_000004", assignees=[stc])],
                    proposer=[_stance("accept", assignees=[stc])])
    result = _run(llm, claim)
    [update] = result["progress_updates"]
    assert [m.name for m in update.mentions] == ["Sở Tài chính"]
    [round_] = result["verification_records"][0].rounds
    assert round_.verdict == "revise"  # đổi bên nhận việc -> revise như việc giao
    same = ScriptLLM(verifier=[_final("keep", "TURN_000004", assignees=[sxd])])
    assert _run(same, claim)["verification_records"][0].verdict == "keep"


def test_no_consensus_keeps_agent_claim_unless_verifier_drops():
    llm = ScriptLLM(
        verifier=[_final("revise", "TURN_000004", "in_progress")] * 2,
        proposer=[_stance("defend", "TURN_000002")] * 2,
    )
    result = _run(llm, consensus_max_rounds=2)
    [update] = result["progress_updates"]
    assert (update.status, update.status_turn_id) == ("cancelled", "TURN_000002")
    assert result["verification_records"][0].decided_by == "verifier"
    dropped = ScriptLLM(verifier=[_final("drop")] * 2, proposer=[_stance("defend", "TURN_000002")] * 2)
    assert "progress_updates" not in _run(dropped, consensus_max_rounds=2)


def test_drop_accepted_removes_the_update():
    result = _run(ScriptLLM(verifier=[_final("drop")], proposer=[_stance("accept")]))
    assert "progress_updates" not in result
    [record] = result["verification_records"]
    assert (record.verdict, record.final_text) == ("drop", "")


def test_defend_gets_second_round_then_keep():
    llm = ScriptLLM(
        verifier=[_final("drop"), _final("keep", "TURN_000002")],
        proposer=[_stance("defend", "TURN_000002")],
    )
    result = _run(llm)
    assert llm.calls == ["verifier", "proposer", "verifier"]
    [update] = result["progress_updates"]
    assert update.status == "cancelled"
    assert len(result["verification_records"][0].rounds) == 2


def test_amend_changes_status_under_review():
    llm = ScriptLLM(
        verifier=[_final("drop"), _final("keep", "TURN_000002")],
        proposer=[_stance("amend", "TURN_000002", "in_progress")],
    )
    [update] = _run(llm)["progress_updates"]
    assert update.status == "in_progress"


def test_keep_without_real_turn_is_dropped():
    llm = ScriptLLM(verifier=[_final("keep", "TURN_999999")], proposer=[_stance("accept")])
    result = _run(llm)
    assert "progress_updates" not in result
    [record] = result["verification_records"]
    assert record.verdict == "drop" and "Hạ thành drop" in record.rounds[0].feedback


def test_llm_error_keeps_agent_claim_as_fallback():
    # Như việc giao: lỗi LLM thì giữ bản gốc của agent (finalize không coi là đã xác nhận).
    result = _run(ScriptLLM(verifier=[LLMUpstreamError("gateway down")]))
    [update] = result["progress_updates"]
    assert (update.status, update.verification) == ("cancelled", "fallback")
    assert result["verification_records"][0].decided_by == "fallback"


def test_verifier_node_dispatches_progress_tasks():
    llm = ScriptLLM(verifier=[_final("keep", "TURN_000002")])
    deps = type("Deps", (), {"verifier_llm": llm, "action_llm": llm, "decision_llm": llm, "config": AnalysisConfig()})
    runtime = type("Runtime", (), {"context": deps})
    result = verifier_node(_task(_uncertain()), runtime)
    assert result["progress_updates"][0].status == "cancelled"
    assert "verified_assignments" not in result


def test_prompt_shows_part_of_long_evidence_turn_near_the_task():
    # Cái Mép: câu nêu trạng thái nằm giữa một lượt 4415 ký tự; chỉ đưa số lượt thì Verifier đọc sót.
    filler = "Báo cáo về quy hoạch cảng và kết nối giao thông khu vực. " * 30
    long_turn = SpeakerTurn(
        "TURN_000002", "Đỗ Thanh Phong",
        f"{filler}Tuyến đường sắt Biên Hòa – Vũng Tàu đã trình chủ trương đầu tư xong. {filler}", None, None,
    )
    turns = (TURNS[0], long_turn)
    update = replace(_uncertain(), status="done", summary="Đã trình chủ trương đầu tư")
    task = {**_task(update), "turns": turns, "meeting_turns": turns}

    prompt = ProgressVerifier(ScriptLLM(), ScriptLLM(), AnalysisConfig())._base_prompt(task, update, [])

    snippet = prompt.split("Evidence excerpts:\n", 1)[1].split("\n", 1)[0]
    assert snippet.startswith("[TURN_000002|Đỗ Thanh Phong] …")
    assert "đã trình chủ trương đầu tư xong" in snippet
