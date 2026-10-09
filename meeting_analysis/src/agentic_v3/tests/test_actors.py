"""Test định danh actor của v3 (người / đơn vị / chưa xác định) với danh sách tham dự.

Kiểm: đọc file danh sách theo quy ước đặt tên, chấm điểm ứng viên (tên -> ngữ cảnh ->
chức năng), ``lookup_speaker``, lựa chọn của Verifier chỉ được nhận khi nằm trong ứng
viên, và chạy end-to-end: "giao Sở Tài chính" được giữ là đơn vị, "anh Sơn" mơ hồ đi
Verifier và được chọn kèm lý do.
"""

from __future__ import annotations

from pathlib import Path

from src.agentic.schemas import ActionItemCandidate
from src.agentic_v3 import MeetingAnalyzerV3, attendee_path_for, load_attendee_roster
from src.agentic_v3.actors.resolution import (
    apply_verifier_actor_choice,
    is_clear_choice,
    list_known_actor_names,
    rank_actor_candidates,
    resolve_actor,
)
from src.agentic_v3.actors.attendees import AttendeeRoster, parse_attendee_roster
from src.agentic_v3.nodes.planner import build_speaker_registry, format_registry_context
from src.agentic_v3.nodes.verifier_tools import MeetingTools
from src.utils.contracts import SpeakerTurn, TopicLabel, TopicSegment

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
    return SpeakerTurn(turn_id, speaker, text, (), None, None)


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
        segment_id="S1", actor=actor, text=text, evidence_ids=(confirm_turn_id or "T1",), quotes=(),
        status=status, confirm_turn_id=confirm_turn_id,
    )


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
    listed = rank_actor_candidates("Sở Tài chính", REGISTRY)
    unlisted = rank_actor_candidates("Sở Công Thương", REGISTRY)

    assert (listed[0].name, listed[0].actor_type, listed[0].ref_id) == ("Sở Tài chính", "organization", "O3")
    assert unlisted[0].actor_type == "organization" and unlisted[0].ref_id is None
    assert is_clear_choice(listed) and is_clear_choice(unlisted)


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
    choice = {"revised_actor": "Lê Văn Sơn", "revised_actor_type": "person", "actor_reason": "Phụ trách danh mục."}
    resolved = apply_verifier_actor_choice(_item("anh Sơn", "rà soát danh mục", "T3"), choice, REGISTRY, TURNS)

    assert (resolved.actor, resolved.actor_type, resolved.actor_flag) == ("Lê Văn Sơn", "person", None)
    assert resolved.actor_reason == "Verifier: Phụ trách danh mục."


def test_verifier_choice_outside_candidates_or_without_reason_is_ignored():
    item = _item("anh Sơn", "rà soát danh mục", "T3")
    invented = {"revised_actor": "Nguyễn Văn Sơn", "revised_actor_type": "person", "actor_reason": "đoán"}
    no_reason = {"revised_actor": "Lê Văn Sơn", "revised_actor_type": "person", "actor_reason": None}

    for choice in (invented, no_reason):
        resolved = apply_verifier_actor_choice(item, choice, REGISTRY, TURNS)
        assert (resolved.actor_type, resolved.actor_flag) == ("unknown", "ambiguous")


def test_verifier_unknown_keeps_candidates_and_flags():
    choice = {"revised_actor": None, "revised_actor_type": "unknown", "actor_reason": "Bản ghi không rõ."}
    resolved = apply_verifier_actor_choice(_item("anh Sơn", "rà soát", "T3"), choice, REGISTRY, TURNS)

    assert (resolved.actor_type, resolved.actor_flag, len(resolved.actor_candidates)) == ("unknown", "ambiguous", 2)


# ----- tool -----


def test_lookup_speaker_lists_scored_candidates():
    tools = MeetingTools(TURNS, REGISTRY, task_text="tổng hợp ý kiến")

    ambiguous = tools.run("lookup_speaker", "Sơn")
    resolved = tools.run("lookup_speaker", "Sơn @T5")

    assert "P1 | Phạm Hồng Sơn | person" in ambiguous and "MƠ HỒ" in ambiguous
    assert "RÕ RÀNG: 'Sơn' là Lê Văn Sơn (person)" in resolved
    assert "LỖI" in tools.run("lookup_speaker", "Sơn @T99")
    assert "O3 | Sở Tài chính | organization" in tools.run("lookup_speaker", "Sở Tài chính")


# ----- end-to-end với LLM giả -----


SEGMENTS = (
    TopicSegment(segment_id="S1", atom_ids=("T1", "T2"), text=""),
    TopicSegment(segment_id="S2", atom_ids=("T3", "T4"), text=""),
)


class FakeLLM:
    """LLM giả: Action agent trả "Sở Tài chính" (S1) và "anh Sơn" (S2); Verifier theo script."""

    def __init__(self, verifier_script):
        self.verifier_script = list(verifier_script)
        self.verifier_prompts: list[str] = []

    def generate_json(self, *, system_prompt, user_prompt, schema):
        first_field = next(iter(schema["properties"]))
        if "stance" in schema["properties"]:
            return {"stance": "accept", "argument": "đồng ý", "confirm_turn_id": None,
                    "revised_text": None, "revised_actor": None}
        if "KIỂM CHỨNG VIÊN" in system_prompt:
            self.verifier_prompts.append(user_prompt)
            return self.verifier_script.pop(0)
        if first_field == "speakers":
            turn = next(t for t in TURNS if f"[{t.turn_id}|" in user_prompt)
            return {"speakers": [{"full_name": turn.speaker, "points": [{"evidence_turn_ids": [turn.turn_id], "text": "Ý kiến."}]}]}
        if first_field == "decisions":
            return {"decisions": []}
        if "[T1|" in user_prompt:
            return {"action_items": [{"evidence_turn_ids": ["T1"], "confirm_turn_id": "T1", "status": "assigned",
                                      "actor": "Sở Tài chính", "text": "Chủ trì cân đối vốn đầu tư công", "deadline": None}]}
        return {"action_items": [{"evidence_turn_ids": ["T3"], "confirm_turn_id": "T3", "status": "assigned",
                                  "actor": "anh Sơn", "text": "Rà soát lại danh mục dự án", "deadline": "trong tuần sau"}]}


class FakeLabeler:
    def label_topic(self, segment, prev_segment, prev_topic, atoms, evidence, *, prior_issues=()):
        return TopicLabel(segment_id=segment.segment_id, title="Chủ đề", summary="Tóm tắt.",
                          text="", evidence_ids=(), method="llm")


def _verifier(action: str, argument: str | None = None, **final) -> dict:
    answer = {"thought": "xét", "action": action, "argument": argument, "verdict": None, "deciding_turn_id": None,
              "revised_actor": None, "revised_actor_type": None, "actor_reason": None, "reasoning": None}
    answer.update(final)
    return answer


def _run(llm: FakeLLM, roster: AttendeeRoster | None):
    analyzer = MeetingAnalyzerV3(content_llm=llm, action_llm=llm, decision_llm=llm, verifier_llm=llm,
                                 labeler=FakeLabeler())
    return analyzer.analyze(meeting_id="M1", turns=TURNS[:4], segments=SEGMENTS, attendee_roster=roster)


def test_end_to_end_organization_kept_and_ambiguous_son_chosen_by_verifier():
    llm = FakeLLM([
        _verifier("lookup_speaker", "Sơn @T3"),
        _verifier("final", verdict="keep", deciding_turn_id="T3", revised_actor="Lê Văn Sơn",
                  revised_actor_type="person", actor_reason="Rà soát danh mục vốn thuộc Sở Tài chính.",
                  reasoning="Đúng việc được đề nghị ở T3."),
    ])
    report = _run(llm, ROSTER)

    by_segment = {item.segment_id: item for item in report.assignments}
    assert (by_segment["S1"].actor, by_segment["S1"].actor_type, by_segment["S1"].verification) == (
        "Sở Tài chính", "organization", "rule")
    assert (by_segment["S2"].actor, by_segment["S2"].actor_type) == ("Lê Văn Sơn", "person")
    assert by_segment["S2"].actor_reason.startswith("Verifier:")
    (record,) = report.verification_records
    assert any("mơ hồ" in reason for reason in record.reasons)
    assert "P2 | Lê Văn Sơn" in record.steps[0].observation


def test_end_to_end_verifier_unknown_keeps_assignment_flagged():
    llm = FakeLLM([
        _verifier("final", verdict="keep", deciding_turn_id="T3", revised_actor_type="unknown",
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
    assert "Đảng ủy ban" in list_known_actor_names(registry)
    assert "còn gọi: Đảng ủy ban" in format_registry_context(registry)


# ----- tách actor ghép -----


def _roles(item) -> list[tuple[str | None, str, str]]:
    return [(assignee.name, assignee.role, assignee.actor_type) for assignee in item.assignees]


def test_split_lead_and_support_from_actor():
    for actor in ("Sở Tài chính chủ trì, phối hợp với Sở Xây dựng", "Sở Tài chính (chủ trì), Sở Xây dựng (phối hợp)"):
        resolved = resolve_actor(_item(actor, "Cân đối vốn", "T1"), REGISTRY, TURNS)

        assert _roles(resolved) == [("Sở Tài chính", "lead", "organization"), ("Sở Xây dựng", "support", "organization")]
        assert (resolved.actor, resolved.actor_type, resolved.actor_flag) == (
            "Sở Tài chính, Sở Xây dựng", "organization", None)


def test_support_named_in_task_text_is_added_only_if_listed():
    resolved = resolve_actor(
        _item("Sở Tài chính", "Chủ trì cân đối vốn, phối hợp với Sở Xây dựng và Sở Công Thương", "T1"), REGISTRY, TURNS
    )

    assert _roles(resolved) == [("Sở Tài chính", "lead", "organization"), ("Sở Xây dựng", "support", "organization")]


def test_joint_people_and_mixed_ambiguity():
    joint = resolve_actor(_item("anh Thông và anh Phong", "Rà soát", "T3"), REGISTRY, TURNS)
    mixed = resolve_actor(_item("anh Sơn, Sở Xây dựng", "Rà soát danh mục", "T3"), REGISTRY, TURNS)

    assert _roles(joint) == [("Trần Văn Thông", "joint", "person"), ("Đỗ Thanh Phong", "joint", "person")]
    assert _roles(mixed) == [(None, "joint", "unknown"), ("Sở Xây dựng", "joint", "organization")]
    assert (mixed.actor, mixed.actor_flag) == ("anh Sơn, Sở Xây dựng", "ambiguous")


def test_organization_name_containing_va_is_not_split():
    roster = parse_attendee_roster({"organizations": [{"id": "O9", "name": "Sở Nông nghiệp và Môi trường"}]})
    registry = build_speaker_registry(TURNS, roster)

    listed = resolve_actor(_item("Sở Nông nghiệp và Môi trường", "Rà soát", "T1"), registry, TURNS)
    unlisted = resolve_actor(_item("Sở Văn hóa và Thể thao", "Rà soát", "T1"), REGISTRY, TURNS)

    assert _roles(listed) == [("Sở Nông nghiệp và Môi trường", "lead", "organization")]
    assert _roles(unlisted) == [("Sở Văn hóa và Thể thao", "lead", "organization")]


def test_verifier_multi_assignee_choice_needs_every_part_in_candidates():
    item = _item("anh Sơn, Sở Xây dựng", "Rà soát danh mục", "T3")
    valid = {"revised_actor": "Lê Văn Sơn (chủ trì), Sở Xây dựng (phối hợp)", "revised_actor_type": None,
             "actor_reason": "T3 đề nghị anh Sơn bên Tài chính."}
    one_invented = {**valid, "revised_actor": "Lê Văn Sơn (chủ trì), Sở Giả Lập Xyz (phối hợp)"}

    chosen = apply_verifier_actor_choice(item, valid, REGISTRY, TURNS)
    fallback = apply_verifier_actor_choice(item, one_invented, REGISTRY, TURNS)

    assert _roles(chosen) == [("Lê Văn Sơn", "lead", "person"), ("Sở Xây dựng", "support", "organization")]
    assert chosen.actor_reason.startswith("Verifier:")
    assert fallback.actor_flag == "ambiguous" and fallback.assignees[0].name is None
