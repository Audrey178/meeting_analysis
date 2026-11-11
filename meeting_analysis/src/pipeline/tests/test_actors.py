"""Kiểm việc xác định bên nhận việc (người, đơn vị hay chưa xác định) khi có danh sách tham dự.

Gồm: đọc file danh sách đặt cạnh bản ghi, chấm điểm ứng viên theo tên, ngữ cảnh và chức năng, công
cụ tra danh bạ của agent kiểm chứng, chỉ nhận lựa chọn của agent kiểm chứng khi nằm trong số ứng
viên, và chạy trọn luồng: "giao Sở Tài chính" được giữ là đơn vị, còn "anh Sơn" mơ hồ thì được gửi
agent kiểm chứng và được chọn kèm lý do.
"""

from __future__ import annotations

from pathlib import Path

from ...utils.contracts import SpeakerTurn, TopicLabel, TopicSegment
from ..run import MeetingAnalyzer
from ..shared.actors.assignees import format_actor, read_assignee_mentions
from ..shared.actors.names import is_bare_personal_pronoun, name_key
from ..shared.actors.resolution import (
    _build_person_profiles,
    apply_verifier_actor_choice,
    build_actor_directory,
    is_clear_choice,
    rank_actor_candidates,
    resolve_actor,
)
from ..shared.meeting_inputs.attendees import (
    AttendeeRoster,
    attendee_path_for,
    load_attendee_roster,
    parse_attendee_roster,
)
from ..shared.schemas import ActionItemCandidate
from ..step4_extract.registry import build_speaker_registry, format_registry_context
from ..step5_verify.check.evidence_check import _actor_reasons
from ..step5_verify.verifier.tools import MeetingTools
from .test_pipeline import CommitTurnJudge, _has_turn

REPO_ROOT = Path(__file__).resolve().parents[3]
TRANSCRIPT_PATH = REPO_ROOT / "inputs" / "bien-ban-vdt-trang-copy-v1.json"

ROSTER = parse_attendee_roster(
    {
        "people": [
            {"id": "P1", "full_name": "Phạm Hồng Sơn", "position": "Phó Bí thư Thành ủy", "org_id": "O1"},
            {"id": "P2", "full_name": "Lê Văn Sơn", "position": "Phó Giám đốc Sở Tài chính", "org_id": "O3"},
            {"id": "P4", "full_name": "Trần Văn Thông", "position": "Ủy viên Ban Thường vụ", "org_id": "O1"},
            {"id": "P5", "full_name": "Đỗ Thanh Phong", "position": "Giám đốc Sở Xây dựng", "org_id": "O4"},
        ],
        "organizations": [
            {"id": "O1", "name": "Ban Thường vụ Thành ủy", "functions": ["cho ý kiến chủ trương"]},
            {"id": "O3", "name": "Sở Tài chính", "functions": ["ngân sách", "vốn đầu tư công"]},
            {"id": "O4", "name": "Sở Xây dựng", "functions": ["hạ tầng giao thông"]},
        ],
    }
)


def _turn(turn_id: str, speaker: str, text: str) -> SpeakerTurn:
    return SpeakerTurn(turn_id, speaker, text, None, None)


TURNS = (
    _turn("T1", "Phạm Hồng Sơn (HNI)", "Giao Sở Tài chính chủ trì cân đối vốn đầu tư công cho dự án cảng."),
    _turn("T2", "Đ/c Thông (HNI)", "Tôi thống nhất."),
    _turn("T3", "Đ/c Thông (HNI)", "Đề nghị anh Sơn rà soát lại danh mục dự án, báo cáo trong tuần sau."),
    _turn("T4", "Đ/c Phong (HNI)", "Về tên đề án thì giữ như cũ."),
    _turn("T5", "Phạm Hồng Sơn (HNI)", "Giao anh Sơn tổng hợp ý kiến."),
    _turn("T6", "Lê Văn Sơn", "Dạ tôi nhận."),
)
REGISTRY = build_speaker_registry(TURNS, ROSTER)


def _item(actor: str | None, text: str, confirm_turn_id: str | None = None, status: str = "assigned"):
    return ActionItemCandidate(
        segment_id="S1", actor=actor, text=text, evidence_turn_ids=(confirm_turn_id or "T1",), quotes=(),
        status=status, confirm_turn_id=confirm_turn_id,
    )


def _mention_item(mentions: list[tuple[str, str, str]], text: str, confirm_turn_id: str | None = None):
    """Việc giao với các bên nhận việc do agent khai, qua ``read_assignee_mentions`` như parser Action agent."""

    parsed = read_assignee_mentions([{"name": n, "role": r, "type": t} for n, r, t in mentions])
    return ActionItemCandidate(
        segment_id="S1", actor=format_actor(parsed), text=text, evidence_turn_ids=(confirm_turn_id or "T1",), quotes=(),
        status="assigned", confirm_turn_id=confirm_turn_id, mentions=parsed,
    )


def _assignee(name: str, role: str, actor_type: str) -> dict:
    return {"name": name, "role": role, "type": actor_type}


def _names(candidates) -> list[str]:
    return [candidate.name for candidate in candidates]


# ----- file danh sách -----


def test_attendee_file_is_found_by_naming_convention():
    assert attendee_path_for("inputs/x-v1.json") == Path("inputs/x-v1.attendees.json")
    roster = load_attendee_roster(TRANSCRIPT_PATH)

    assert roster is not None
    assert [p.full_name for p in roster.people if p.full_name.endswith("Sơn")] == ["Phạm Hồng Sơn", "Lê Văn Sơn"]
    assert roster.find_organization("O3").name == "Sở Tài chính"


def test_missing_attendee_file_returns_none(tmp_path):
    assert load_attendee_roster(tmp_path / "no-roster.json") is None


def test_speakers_are_merged_into_roster_people():
    candidates = rank_actor_candidates("Thông", REGISTRY)

    assert _names(candidates) == ["Trần Văn Thông"]
    assert is_clear_choice(candidates)


def test_speakers_match_roster_by_speaker_id_before_name():
    roster = parse_attendee_roster(
        {
            "people": [
                {"id": "u1", "full_name": "Nguyễn Văn A", "position": "Giám đốc Sở Tài chính"},
                {"id": "u2", "full_name": "Nguyễn Văn A", "position": "Giám đốc Sở Xây dựng"},
            ]
        }
    )
    turns = (
        SpeakerTurn("T1", "Nguyễn Văn A", "a", None, None, speaker_id="u1"),
        SpeakerTurn("T2", "Nguyễn Văn A #2", "b", None, None, speaker_id="u2"),
    )
    registry = build_speaker_registry(turns, roster)

    assert registry.speaker_ids == ("u1", "u2")
    assert {(profile.ref_id, profile.speaker_names) for profile in _build_person_profiles(registry)} == {
        ("u1", frozenset({"Nguyễn Văn A"})),
        ("u2", frozenset({"Nguyễn Văn A #2"})),
    }


# ----- chấm điểm -----


def test_two_people_named_son_without_context_are_ambiguous():
    candidates = rank_actor_candidates("anh Sơn", REGISTRY)

    assert set(_names(candidates)) == {"Phạm Hồng Sơn", "Lê Văn Sơn"}
    assert not is_clear_choice(candidates)


def test_context_resolves_before_function():
    # T5: Phạm Hồng Sơn giao việc (bị trừ), Lê Văn Sơn trả lời ngay sau (được cộng).
    candidates = rank_actor_candidates("Sơn", REGISTRY, meeting_turns=TURNS, context_turn_id="T5",
                                       task_text="tổng hợp ý kiến")

    assert candidates[0].name == "Lê Văn Sơn"
    assert is_clear_choice(candidates)
    assert "chức năng" not in candidates[0].reason


def test_function_is_fallback_when_context_cannot_decide():
    candidates = rank_actor_candidates("Sơn", REGISTRY, meeting_turns=TURNS, context_turn_id="T3",
                                       task_text="cân đối vốn đầu tư công")

    assert candidates[0].name == "Lê Văn Sơn"
    assert "chức năng khớp" in candidates[0].reason
    assert is_clear_choice(candidates)


def test_listed_and_unlisted_organizations():
    mentioning = (*TURNS, _turn("T7", "Phạm Hồng Sơn (HNI)", "Giao Sở Công Thương chủ trì phần thương mại."))
    listed = rank_actor_candidates("Sở Tài chính", REGISTRY)
    unlisted = rank_actor_candidates("Sở Công Thương", REGISTRY, meeting_turns=mentioning, declared_type="organization")

    assert (listed[0].name, listed[0].actor_type, listed[0].ref_id) == ("Sở Tài chính", "organization", "O3")
    assert unlisted[0].actor_type == "organization" and unlisted[0].ref_id is None
    assert is_clear_choice(listed) and is_clear_choice(unlisted)


def test_unlisted_name_needs_a_declared_type_and_a_mention_in_the_transcript():
    mentioning = (*TURNS, _turn("T7", "Phạm Hồng Sơn (HNI)", "Giao Sở Công Thương chủ trì phần thương mại."))

    assert rank_actor_candidates("Sở Công Thương", REGISTRY, meeting_turns=mentioning) == ()  # agent không khai loại
    assert rank_actor_candidates("Sở Công Thương", REGISTRY, declared_type="organization") == ()  # không có bản ghi
    assert rank_actor_candidates("Sở Giả Lập", REGISTRY, meeting_turns=mentioning, declared_type="organization") == ()


def test_unlisted_name_with_generic_word_is_a_normal_candidate_when_mentioned():
    # Hồi quy: "nhóm"/"team" trong tên thật không được coi là cụm không định danh.
    turns = (*TURNS, _turn("T7", "Phạm Hồng Sơn (HNI)", "Giao Nhóm dữ liệu rà soát, Team AI hỗ trợ."))
    for name in ("Nhóm dữ liệu", "Team AI"):
        (candidate,) = rank_actor_candidates(name, REGISTRY, meeting_turns=turns, declared_type="organization")
        assert (candidate.name, candidate.actor_type, candidate.score) == (name, "organization", 0.6)


def test_person_named_but_not_speaking_is_a_mentioned_only_candidate():
    turns = (*TURNS, _turn("T7", "Phạm Hồng Sơn (HNI)", "Giao Hiếu map lại nhãn."))
    (candidate,) = rank_actor_candidates("Hiếu", REGISTRY, meeting_turns=turns, declared_type="person")

    assert (candidate.name, candidate.actor_type, candidate.ref_id) == ("Hiếu", "person", None)
    assert "được nhắc tên" in candidate.reason and is_clear_choice((candidate,))


def test_organization_abbreviation_matches_full_name():
    registry = build_speaker_registry(TURNS, load_attendee_roster(TRANSCRIPT_PATH))
    candidates = rank_actor_candidates("Ủy ban nhân dân Thành phố", registry)

    assert (candidates[0].name, candidates[0].ref_id) == ("UBND Thành phố", "O5")


def test_without_roster_falls_back_to_speakers_only():
    registry = build_speaker_registry(TURNS, None)
    candidates = rank_actor_candidates("Phong", registry)

    assert registry.roster == AttendeeRoster()
    assert _names(candidates) == ["Đ/c Phong (HNI)"]


# ----- resolve_actor / lựa chọn của Verifier -----


def test_resolve_actor_marks_ambiguous_as_unknown_and_keeps_candidates():
    resolved = resolve_actor(_item("anh Sơn", "rà soát lại danh mục dự án", "T3"), REGISTRY, TURNS)

    assert (resolved.actor, resolved.actor_type, resolved.actor_flag) == ("anh Sơn", "unknown", "ambiguous")
    assert len(resolved.actor_candidates) == 2


def test_resolve_actor_maps_organization():
    resolved = resolve_actor(_item("Sở Tài chính", "cân đối vốn", "T1"), REGISTRY, TURNS)

    assert (resolved.actor, resolved.actor_type, resolved.actor_flag) == ("Sở Tài chính", "organization", None)


def test_verifier_choice_inside_candidates_with_reason_is_accepted():
    choice = {"revised_assignees": [_assignee("Lê Văn Sơn", "lead", "person")], "actor_reason": "Phụ trách danh mục."}
    resolved = apply_verifier_actor_choice(_item("anh Sơn", "rà soát danh mục", "T3"), choice, REGISTRY, TURNS)

    assert (resolved.actor, resolved.actor_type, resolved.actor_flag) == ("Lê Văn Sơn", "person", None)
    assert resolved.actor_reason == "Verifier: Phụ trách danh mục."


def test_verifier_choice_outside_candidates_or_without_reason_is_ignored():
    item = _item("anh Sơn", "rà soát danh mục", "T3")
    invented = {"revised_assignees": [_assignee("Nguyễn Văn Sơn", "lead", "person")], "actor_reason": "đoán"}
    no_reason = {"revised_assignees": [_assignee("Lê Văn Sơn", "lead", "person")], "actor_reason": None}

    for choice in (invented, no_reason):
        resolved = apply_verifier_actor_choice(item, choice, REGISTRY, TURNS)
        assert (resolved.actor_type, resolved.actor_flag) == ("unknown", "ambiguous")


def test_verifier_unknown_keeps_candidates_and_flags():
    choice = {"revised_assignees": [_assignee("anh Sơn", "lead", "unknown")], "actor_reason": "Bản ghi không rõ."}
    resolved = apply_verifier_actor_choice(_item("anh Sơn", "rà soát", "T3"), choice, REGISTRY, TURNS)

    assert (resolved.actor_type, resolved.actor_flag, len(resolved.actor_candidates)) == ("unknown", "ambiguous", 2)


# ----- tool -----


def test_lookup_speaker_lists_scored_candidates():
    tools = MeetingTools(TURNS, REGISTRY, task_text="tổng hợp ý kiến")

    ambiguous = tools.run("lookup_speaker", "Sơn")
    resolved = tools.run("lookup_speaker", "Sơn @T5")

    assert "P1 | Phạm Hồng Sơn | person" in ambiguous and "AMBIGUOUS" in ambiguous
    assert "CLEAR: 'Sơn' is Lê Văn Sơn (person)" in resolved
    assert "ERROR" in tools.run("lookup_speaker", "Sơn @T99")
    assert "O3 | Sở Tài chính | organization" in tools.run("lookup_speaker", "Sở Tài chính")


# ----- end-to-end với LLM giả -----


SEGMENTS = (
    TopicSegment(segment_id="S1", turn_ids=("T1", "T2"), text=""),
    TopicSegment(segment_id="S2", turn_ids=("T3", "T4"), text=""),
)


class FakeLLM:
    """LLM giả: Action agent trả "Sở Tài chính" (S1) và "anh Sơn" (S2); Verifier theo script."""

    def __init__(self, verifier_script):
        self.verifier_script = list(verifier_script)
        self.verifier_prompts: list[str] = []
        self.proposer_prompts: list[str] = []

    def generate_json(self, *, system_prompt, user_prompt, schema):
        first_field = next(iter(schema["properties"]))
        if "stance" in schema["properties"]:
            # Agent trích xuất tự viết lại bên nhận việc theo đề xuất của Verifier (Verifier không sửa hộ).
            self.proposer_prompts.append(user_prompt)
            adopted = [_assignee("Lê Văn Sơn", "lead", "person")] if "Verifier suggests assignees: Lê Văn Sơn" in user_prompt else []
            return {"stance": "accept", "argument": "đồng ý", "confirm_turn_id": None,
                    "revised_text": None, "revised_assignees": adopted}
        if "You are the VERIFIER" in system_prompt:
            self.verifier_prompts.append(user_prompt)
            return self.verifier_script.pop(0)
        if first_field == "discussion_points":
            turn = next(t for t in TURNS if _has_turn(user_prompt, t.turn_id))
            return {"discussion_points": [{"evidence_segment_ids": [turn.turn_id], "text": "Ý kiến."}]}
        if first_field == "decisions":
            return {"decisions": []}
        if _has_turn(user_prompt, "T1"):
            return {"action_items": [{"evidence_segment_ids": ["T1"], "confirm_turn_id": "T1", "status": "assigned",
                                      "assignees": [_assignee("Sở Tài chính", "lead", "organization")],
                                      "text": "Chủ trì cân đối vốn đầu tư công", "deadline": None}]}
        return {"action_items": [{"evidence_segment_ids": ["T3"], "confirm_turn_id": "T3", "status": "assigned",
                                  "assignees": [_assignee("anh Sơn", "lead", "person")],
                                  "text": "Rà soát lại danh mục dự án", "deadline": "trong tuần sau"}]}


class FakeLabeler:
    def label_topic(self, segment):
        return TopicLabel(segment_id=segment.segment_id, title="Chủ đề", summary="Tóm tắt.",
                          text="", evidence_turn_ids=(), method="llm")


def _verifier(action: str, argument: str | None = None, **final) -> dict:
    answer = {"thought": "xét", "action": action, "argument": argument, "verdict": None, "deciding_turn_id": None,
              "revised_assignees": [], "actor_reason": None, "reasoning": None}
    answer.update(final)
    return answer


def _run(llm: FakeLLM, roster: AttendeeRoster | None):
    analyzer = MeetingAnalyzer(content_llm=llm, action_llm=llm, decision_llm=llm, verifier_llm=llm,
                                 labeler=FakeLabeler(), turn_judge=CommitTurnJudge({"T1", "T2"}))
    return analyzer.analyze(meeting_id="M1", turns=TURNS[:4], segments=SEGMENTS, attendee_roster=roster)


def test_end_to_end_organization_kept_and_ambiguous_son_chosen_by_verifier():
    llm = FakeLLM([
        _verifier("lookup_speaker", "Sơn @T3"),
        _verifier("final", verdict="keep", deciding_turn_id="T3",
                  revised_assignees=[_assignee("Lê Văn Sơn", "lead", "person")],
                  actor_reason="Rà soát danh mục vốn thuộc Sở Tài chính.",
                  reasoning="Đúng việc được đề nghị ở T3."),
    ])
    report = _run(llm, ROSTER)

    by_segment = {item.segment_id: item for item in report.assignments}
    assert (by_segment["S1"].actor, by_segment["S1"].actor_type, by_segment["S1"].verification) == (
        "Sở Tài chính", "organization", "rule")
    assert (by_segment["S2"].actor, by_segment["S2"].actor_type) == ("Lê Văn Sơn", "person")
    assert by_segment["S2"].actor_reason.startswith("Verifier:")
    assert len(llm.proposer_prompts) == 1  # đề xuất đi qua agent trích xuất
    (record,) = report.verification_records
    assert (record.verdict, record.rounds[0].stance) == ("revise", "accept")
    assert any("mơ hồ" in reason for reason in record.reasons)
    assert "P2 | Lê Văn Sơn" in record.steps[0].observation


def test_end_to_end_verifier_unknown_keeps_assignment_flagged():
    llm = FakeLLM([
        _verifier("final", verdict="keep", deciding_turn_id="T3",
                  revised_assignees=[_assignee("anh Sơn", "lead", "unknown")],
                  actor_reason="Không rõ anh Sơn nào.", reasoning="Có giao việc ở T3."),
    ])
    report = _run(llm, ROSTER)

    son = next(item for item in report.assignments if item.segment_id == "S2")
    assert (son.actor, son.actor_type, son.actor_flag) == ("anh Sơn", "unknown", "ambiguous")
    assert {c.name for c in son.actor_candidates} == {"Phạm Hồng Sơn", "Lê Văn Sơn"}


# ----- tên đơn vị viết khác nhau -----


def test_people_committee_name_variants_match_listed_organization():
    registry = build_speaker_registry(TURNS, load_attendee_roster(TRANSCRIPT_PATH))

    for alias in ("Ủy ban Thành phố", "UBND TP", "Uỷ ban nhân dân Thành phố"):
        top = rank_actor_candidates(alias, registry)[0]
        assert (top.name, top.score) == ("UBND Thành phố", 1.0), alias
    assert rank_actor_candidates("HĐND Thành phố", registry)[0].name == "HĐND Thành phố"


def test_organization_short_alias_from_attendee_file():
    registry = build_speaker_registry(TURNS, load_attendee_roster(TRANSCRIPT_PATH))
    candidates = rank_actor_candidates("Đảng ủy ban", registry)

    assert (candidates[0].name, candidates[0].actor_type, candidates[0].ref_id, candidates[0].score) == (
        "Đảng ủy UBND Thành phố", "organization", "O2", 1.0)
    assert "tên gọi tắt" in candidates[0].reason
    assert is_clear_choice(candidates)


def test_organization_alias_is_optional_and_grounds_actor():
    roster = parse_attendee_roster(
        {"organizations": [{"id": "O2", "name": "Đảng ủy UBND Thành phố", "aliases": [" Đảng ủy ban ", ""]}]}
    )
    registry = build_speaker_registry(TURNS, roster)

    assert roster.organizations[0].aliases == ("Đảng ủy ban",)
    assert ROSTER.organizations[0].aliases == ()
    assert "also called: Đảng ủy ban" in format_registry_context(registry)


# ----- các bên nhận việc do agent khai -----


def _roles(item) -> list[tuple[str | None, str, str]]:
    return [(assignee.name, assignee.role, assignee.actor_type) for assignee in item.assignees]


def test_read_assignee_mentions_normalizes_the_agent_declaration():
    mentions = read_assignee_mentions([
        {"name": "Sở Xây dựng", "role": "support", "type": "organization"},
        {"name": "anh Sơn", "role": "joint", "type": "person"},
        {"name": "em", "role": "lead", "type": "person"},  # đại từ trần
        {"name": "Sở Xây dựng", "role": "lead", "type": "organization"},  # trùng
        {"name": "Sở Tài chính", "role": "lead", "type": "viết_bậy"},
        "không phải dict",
        {"name": "  ", "role": "lead", "type": "person"},
    ])

    # có lead/support thì "joint" thành "lead"; xếp chủ trì -> cùng thực hiện -> phối hợp
    assert [(m.name, m.role, m.actor_type) for m in mentions] == [
        ("anh Sơn", "lead", "person"), ("Sở Tài chính", "lead", "unknown"), ("Sở Xây dựng", "support", "organization")]
    assert format_actor(mentions) == "anh Sơn, Sở Tài chính, Sở Xây dựng"
    assert read_assignee_mentions([]) == () and format_actor(()) is None


def test_read_assignee_mentions_keeps_names_with_generic_words_and_joint_without_lead():
    mentions = read_assignee_mentions([
        {"name": "Nhóm dữ liệu", "role": "joint", "type": "organization"},
        {"name": "Team AI", "role": "joint", "type": "organization"},
    ])

    assert [(m.name, m.role) for m in mentions] == [("Nhóm dữ liệu", "joint"), ("Team AI", "joint")]


def test_read_assignee_mentions_falls_back_to_legacy_actor_only_when_assignees_missing():
    assert [(m.name, m.role) for m in read_assignee_mentions(None, "Hiếu")] == [("Hiếu", "lead")]
    assert read_assignee_mentions(None, "em") == ()
    assert read_assignee_mentions([], "Hiếu") == ()  # model khai rõ không có ai


def test_resolve_lead_and_support_from_declared_mentions():
    item = _mention_item([("Sở Tài chính", "lead", "organization"), ("Sở Xây dựng", "support", "organization")],
                         "Cân đối vốn", "T1")
    resolved = resolve_actor(item, REGISTRY, TURNS)

    assert _roles(resolved) == [("Sở Tài chính", "lead", "organization"), ("Sở Xây dựng", "support", "organization")]
    assert (resolved.actor, resolved.actor_type, resolved.actor_flag) == (
        "Sở Tài chính, Sở Xây dựng", "organization", None)


def test_actor_string_is_one_lead_without_declared_mentions():
    # Candidate dựng tay chỉ có ``actor``: không tách chuỗi theo "và"/"phối hợp".
    resolved = resolve_actor(_item("Sở Tài chính chủ trì, phối hợp với Sở Xây dựng", "Cân đối vốn", "T1"), REGISTRY, TURNS)

    assert len(resolved.assignees) == 1 and resolved.assignees[0].name is None
    assert resolved.actor_flag == "ambiguous"


def test_support_in_task_text_is_not_inferred_and_unlisted_support_needs_a_mention():
    mentioning = (*TURNS, _turn("T7", "Phạm Hồng Sơn (HNI)", "Sở Công Thương phối hợp."))
    item = _mention_item([("Sở Tài chính", "lead", "organization"), ("Sở Công Thương", "support", "organization")],
                         "Chủ trì cân đối vốn, phối hợp với Sở Xây dựng", "T1")

    in_transcript = resolve_actor(item, REGISTRY, mentioning)
    not_in_transcript = resolve_actor(item, REGISTRY, TURNS)

    assert _roles(in_transcript) == [("Sở Tài chính", "lead", "organization"), ("Sở Công Thương", "support", "organization")]
    assert _roles(not_in_transcript) == [("Sở Tài chính", "lead", "organization"), (None, "support", "unknown")]


def test_joint_people_and_mixed_ambiguity():
    joint = resolve_actor(_mention_item([("anh Thông", "joint", "person"), ("anh Phong", "joint", "person")], "Rà soát", "T3"),
                          REGISTRY, TURNS)
    mixed = resolve_actor(_mention_item([("anh Sơn", "joint", "person"), ("Sở Xây dựng", "joint", "organization")],
                                        "Rà soát danh mục", "T3"), REGISTRY, TURNS)

    assert _roles(joint) == [("Trần Văn Thông", "joint", "person"), ("Đỗ Thanh Phong", "joint", "person")]
    assert _roles(mixed) == [(None, "joint", "unknown"), ("Sở Xây dựng", "joint", "organization")]
    assert (mixed.actor, mixed.actor_flag) == ("anh Sơn, Sở Xây dựng", "ambiguous")


def test_organization_name_containing_va_is_one_declared_assignee():
    roster = parse_attendee_roster({"organizations": [{"id": "O9", "name": "Sở Nông nghiệp và Môi trường"}]})
    registry = build_speaker_registry(TURNS, roster)
    mentioning = (*TURNS, _turn("T7", "Phạm Hồng Sơn (HNI)", "Giao Sở Văn hóa và Thể thao rà soát."))

    listed = resolve_actor(_mention_item([("Sở Nông nghiệp và Môi trường", "lead", "organization")], "Rà soát", "T1"),
                           registry, TURNS)
    unlisted = resolve_actor(_mention_item([("Sở Văn hóa và Thể thao", "lead", "organization")], "Rà soát", "T1"),
                             REGISTRY, mentioning)

    assert _roles(listed) == [("Sở Nông nghiệp và Môi trường", "lead", "organization")]
    assert _roles(unlisted) == [("Sở Văn hóa và Thể thao", "lead", "organization")]


def test_verifier_multi_assignee_choice_needs_every_part_in_candidates():
    item = _mention_item([("anh Sơn", "joint", "person"), ("Sở Xây dựng", "joint", "organization")],
                         "Rà soát danh mục", "T3")
    valid = {"revised_assignees": [_assignee("Lê Văn Sơn", "lead", "person"), _assignee("Sở Xây dựng", "support", "organization")],
             "actor_reason": "T3 đề nghị anh Sơn bên Tài chính."}
    one_invented = {**valid, "revised_assignees": [_assignee("Lê Văn Sơn", "lead", "person"),
                                                   _assignee("Sở Giả Lập Xyz", "support", "organization")]}

    chosen = apply_verifier_actor_choice(item, valid, REGISTRY, TURNS)
    fallback = apply_verifier_actor_choice(item, one_invented, REGISTRY, TURNS)

    assert _roles(chosen) == [("Lê Văn Sơn", "lead", "person"), ("Sở Xây dựng", "support", "organization")]
    assert chosen.actor_reason.startswith("Verifier:")
    assert fallback.actor_flag == "ambiguous" and fallback.assignees[0].name is None


# ----- lý do WHO của evidence-check (thay luật "actor có căn cứ" và danh sách cụm không định danh) -----


def test_actor_reasons_flag_names_that_match_nobody_and_ambiguous_names():
    unknown = _mention_item([("hộ dân", "lead", "person")], "Làm", "T3")
    generic = _mention_item([("mọi người", "lead", "person")], "Làm", "T3")
    ambiguous = _item("anh Sơn", "rà soát", "T3")

    assert any("không khớp người/đơn vị nào" in r for r in _actor_reasons(unknown, REGISTRY, TURNS))
    assert any("không khớp người/đơn vị nào" in r for r in _actor_reasons(generic, REGISTRY, TURNS))
    assert any("mơ hồ" in r for r in _actor_reasons(ambiguous, REGISTRY, TURNS))


def test_actor_reasons_accept_names_found_in_roster_or_transcript_whatever_the_spelling():
    registry = build_speaker_registry(TURNS, load_attendee_roster(TRANSCRIPT_PATH))
    turns = (*TURNS, _turn("T7", "Phạm Hồng Sơn (HNI)", "Giao Nhóm dữ liệu rà soát, đ/c Hiếu phối hợp, UBND thành phố nghe."))
    items = [
        _mention_item([("Nhóm dữ liệu", "lead", "organization")], "Rà soát", "T7"),
        _mention_item([("đồng chí Hiếu", "lead", "person")], "Rà soát", "T7"),  # bản ghi viết "đ/c Hiếu"
        _mention_item([("Ủy ban nhân dân Thành phố", "lead", "organization")], "Rà soát", "T7"),  # bản ghi viết "UBND thành phố"
    ]

    for item in items:
        assert _actor_reasons(item, registry, turns) == [], item.actor




# ----- một hàm chuẩn hoá tên -----


def test_name_key_unifies_honorifics_abbreviations_and_brackets():
    assert name_key("đ/c Thông (HNI)") == name_key("đồng chí Thông") == name_key("Anh Thông") == "thông"
    assert name_key("UBND TP") == name_key("Ủy ban nhân dân Thành phố") == name_key("Uỷ ban Thành phố") == "ủy ban thành phố"
    assert name_key("HĐND Thành phố") != name_key("UBND Thành phố")
    assert name_key("Hải Anh") == "hải anh"  # chỉ bỏ từ xưng hô ĐỨNG ĐẦU
    assert name_key("  Sở   Tài chính ") == "sở tài chính"


def test_bare_pronoun_is_exact_match_only():
    assert is_bare_personal_pronoun("em") and is_bare_personal_pronoun("Bọn em") and is_bare_personal_pronoun("anh")
    assert not is_bare_personal_pronoun("Hải Anh") and not is_bare_personal_pronoun("Nhóm dữ liệu")


# ----- mã danh bạ do agent khai -----


def _coded_item(name: str, code: str | None, actor_type: str = "person", confirm_turn_id: str | None = None):
    parsed = read_assignee_mentions([{"name": name, "id": code, "role": "lead", "type": actor_type}])
    return ActionItemCandidate(
        segment_id="S1", actor=format_actor(parsed), text="Rà soát danh mục", evidence_turn_ids=("T1",), quotes=(),
        status="assigned", confirm_turn_id=confirm_turn_id, mentions=parsed,
    )


def test_actor_directory_codes_people_then_organizations_and_shows_them_in_context():
    directory = build_actor_directory(REGISTRY)
    context = format_registry_context(REGISTRY)

    assert [(entry.code, entry.name, entry.ref_id) for entry in directory] == [
        ("N1", "Phạm Hồng Sơn", "P1"), ("N2", "Lê Văn Sơn", "P2"), ("N3", "Trần Văn Thông", "P4"),
        ("N4", "Đỗ Thanh Phong", "P5"), ("D1", "Ban Thường vụ Thành ủy", "O1"), ("D2", "Sở Tài chính", "O3"),
        ("D3", "Sở Xây dựng", "O4"),
    ]
    assert '<party id="N3">Trần Văn Thông (Ủy viên Ban Thường vụ, Ban Thường vụ Thành ủy, speaker label: Đ/c Thông (HNI))</party>' in context
    assert '<party id="D2">Sở Tài chính (unit)</party>' in context


def test_unlisted_speaker_gets_a_code_without_ref_id():
    registry = build_speaker_registry((*TURNS, _turn("T7", "Hiếu", "Dạ em nhận.")), ROSTER)
    entry = next(entry for entry in build_actor_directory(registry) if entry.name == "Hiếu")

    assert (entry.code, entry.ref_id) == ("N5", None)
    assert '<party id="N5">Hiếu (speaker, not in the attendee list)</party>' in format_registry_context(registry)


def test_read_assignee_mentions_reads_code_and_keeps_same_name_people_with_different_codes():
    mentions = read_assignee_mentions([
        {"name": "Sơn", "id": " [n1] ", "role": "lead", "type": "person"},
        {"name": "Sơn", "id": "N2", "role": "support", "type": "person"},
        {"name": "Sở Tài chính", "id": "null", "role": "joint", "type": "organization"},
    ])

    assert [(m.name, m.code, m.role) for m in mentions] == [
        ("Sơn", "N1", "lead"), ("Sở Tài chính", None, "lead"), ("Sơn", "N2", "support")]


def test_code_picks_one_of_two_people_named_son():
    # Không có mã: hai người tên Sơn hoà điểm, việc bị gắn cờ mơ hồ.
    assert resolve_actor(_coded_item("anh Sơn", None), REGISTRY, TURNS).actor_flag == "ambiguous"

    resolved = resolve_actor(_coded_item("anh Sơn", "N2"), REGISTRY, TURNS)

    assert (resolved.actor, resolved.actor_flag, resolved.assignees[0].ref_id) == ("Lê Văn Sơn", None, "P2")
    assert resolved.assignees[0].candidates[0].reason == "agent khai mã N2"


def test_code_is_trusted_when_the_name_matches_nobody():
    resolved = resolve_actor(_coded_item("đồng chí Phó Bí thư", "N1"), REGISTRY, TURNS)

    assert (resolved.actor, resolved.assignees[0].ref_id) == ("Phạm Hồng Sơn", "P1")


def test_code_contradicting_the_name_or_unknown_code_falls_back_to_name_scoring():
    # Tên "Sở Xây dựng" mà mã D2 là Sở Tài chính: bỏ mã, định danh theo tên.
    conflict = resolve_actor(_coded_item("Sở Xây dựng", "D2", "organization"), REGISTRY, TURNS)
    unknown = resolve_actor(_coded_item("Sở Tài chính", "D99", "organization"), REGISTRY, TURNS)

    assert (conflict.actor, conflict.assignees[0].ref_id) == ("Sở Xây dựng", "O4")
    assert (unknown.actor, unknown.assignees[0].ref_id) == ("Sở Tài chính", "O3")
