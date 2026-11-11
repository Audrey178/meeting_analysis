"""Kiểm các luật không gọi mô hình của bước 4-6: phân loại chắc chắn/nghi ngờ, làm sạch kết quả của
agent (ví dụ ý thảo luận thực ra chỉ là câu giao việc), gộp mục trùng, và luật kiểm lại kết luận
của agent kiểm chứng.

Các ca được rút gọn từ những lỗi thật đã gặp khi đánh giá.
"""

from __future__ import annotations

from ...utils.contracts import SpeakerTurn
from ..shared.actors.assignees import format_actor, read_assignee_mentions
from ..shared.schemas import ActionItemCandidate, DecisionCandidate
from ..shared.transcript import match_claimed_name_to_real_speaker
from ..step4_extract.content import (
    _build_discussion_points_from_llm_result,
)
from ..step5_verify.check.rules import check_evidence
from ..shared.judges.turn_act import (
    TurnActJudgement,
)
from ..step5_verify.verifier.verdict import resolve_verdict
from ..step6_finalize.dedup import (
    merge_duplicate_assignments,
    merge_duplicate_decisions,
)


def _turn(turn_id: str, speaker: str, text: str) -> SpeakerTurn:
    return SpeakerTurn(turn_id, speaker, text, None, None)


TURNS = (
    _turn("T1", "Anh Tuấn", "Mời anh Quý điều phối phần tiếp theo."),
    _turn("T2", "Chị Mai", "Em đề xuất có thể tự động mở lại phản ánh khi người dân không hài lòng."),
    _turn("T3", "Anh Tuấn", "Chốt lại, giao Hiếu map lại nhãn sang 12 lĩnh vực, trước ngày 25/11."),
    _turn("T4", "Hiếu", "Dạ em làm việc với nhà cung cấp, xong trong tuần."),
    _turn("T5", "Anh Phong", "Tiến độ hiện đạt khoảng 55% khối lượng."),
    _turn("T6", "Anh Tuấn", "Hay là mình dùng LLM tự host?"),
    _turn("T7", "Đ/c Hiền", "Tôi đề nghị kỳ họp cuối năm báo cáo nêu rõ danh mục dự án điều giảm vốn."),
    _turn("T8", "Đ/c Sơn", "Dạ Sở Tài chính xin ghi nhận ý kiến của đồng chí đại biểu."),
)


class FakeTurnJudge:
    """Decisions API giả: nhãn cố định theo turn_id (xác suất 0.95)."""

    LABELS = {"T1": "discussion", "T2": "proposal", "T3": "assignment", "T4": "assignment",
              "T5": "discussion", "T6": "discussion", "T7": "proposal", "T8": "proposal"}

    def judge(self, turn, context):
        label = self.LABELS[turn.turn_id]
        return TurnActJudgement(label=label, probabilities={label: 0.95, "other": 0.05})


JUDGE = FakeTurnJudge()


def _flag(item, turns, **kwargs):
    return check_evidence(item, turns, **kwargs)


def _action(**overrides) -> ActionItemCandidate:
    base = dict(
        segment_id="S0", actor="Hiếu", text="Map lại nhãn sang 12 lĩnh vực", evidence_turn_ids=("T3",),
        quotes=(TURNS[2].text_exact,), deadline_raw="trước ngày 25/11", status="assigned", confirm_turn_id="T3",
    )
    return ActionItemCandidate(**{**base, **overrides})


def _decision(**overrides) -> DecisionCandidate:
    base = dict(
        segment_id="S0", text="Dùng danh mục 12 lĩnh vực mới", evidence_turn_ids=("T3",),
        quotes=(TURNS[2].text_exact,), status="agreed", confirm_turn_id="T3",
    )
    return DecisionCandidate(**{**base, **overrides})


# ----- Evidence-Check: action -----

def test_action_assigned_by_chair_is_clear() -> None:
    assert _flag(_action(), TURNS, judge=JUDGE).verdict == "clear"


def test_action_self_commitment_by_actor_is_clear() -> None:
    item = _action(status="self_committed", confirm_turn_id="T4", text="Làm việc với nhà cung cấp")
    assert _flag(item, TURNS, judge=JUDGE).verdict == "clear"


def test_action_self_reported_proposal_is_uncertain() -> None:
    # Đề xuất của thành viên bị viết lại thành việc giao: actor có tên nên bản cũ để lọt.
    item = _action(actor="Chị Mai", status="proposed", confirm_turn_id="T2", text="Tự động mở lại phản ánh")
    flag = _flag(item, TURNS, judge=JUDGE)
    assert flag.verdict == "uncertain"
    assert any("proposed" in reason for reason in flag.reasons)
    assert any("'proposal'" in reason for reason in flag.reasons)


def test_action_hedged_confirm_turn_is_uncertain_even_if_status_claims_assigned() -> None:
    item = _action(actor="Chị Mai", confirm_turn_id="T2", text="Tự động mở lại phản ánh")
    assert _flag(item, TURNS, judge=JUDGE).verdict == "uncertain"


def test_action_confirmed_by_non_commit_turn_is_uncertain() -> None:
    # Kiến nghị của đại biểu + "xin ghi nhận ý kiến": không ai nhận việc (lỗi thật synth_013/a0).
    for confirm in ("T7", "T8"):
        item = _action(actor="Sở Tài chính", confirm_turn_id=confirm, text="Báo cáo nêu rõ danh mục dự án")
        flag = _flag(item, TURNS, judge=JUDGE)
        assert flag.verdict == "uncertain", confirm
        assert any("chưa chắc là lời chốt" in reason for reason in flag.reasons)


def test_action_without_confirm_turn_is_uncertain() -> None:
    assert _flag(_action(confirm_turn_id=None), TURNS, judge=JUDGE).verdict == "uncertain"


def test_action_actor_reasons_from_resolution_make_it_uncertain() -> None:
    # Bên nhận việc không khớp ai trong danh bạ/bản ghi: ``evidence_check`` tính lý do bằng
    # ``actors.resolution`` (xem test_actors) rồi truyền vào; rules chỉ gom lại.
    item = _action(actor="hộ dân")
    reason = "Bên nhận việc 'hộ dân' không khớp người/đơn vị nào trong danh bạ hay bản ghi (WHO)."
    flag = _flag(item, TURNS, judge=JUDGE, actor_reasons=[reason])
    assert flag.verdict == "uncertain" and reason in flag.reasons
    assert _flag(item, TURNS, judge=JUDGE).verdict == "clear"


def test_action_self_commitment_spoken_by_someone_else_is_uncertain() -> None:
    item = _action(actor="Chị Mai", status="self_committed", confirm_turn_id="T4")
    assert _flag(item, TURNS, judge=JUDGE).verdict == "uncertain"


def test_action_without_actor_is_uncertain() -> None:
    assert _flag(_action(actor=None), TURNS, judge=JUDGE).verdict == "uncertain"


# ----- Evidence-Check: decision -----

def test_decision_agreed_with_chair_confirmation_is_clear() -> None:
    assert _flag(_decision(), TURNS, judge=JUDGE).verdict == "clear"


def test_decision_status_report_rewritten_as_agreement_is_uncertain() -> None:
    # Câu agent viết nghe như kết luận, nhưng lượt chốt là báo cáo -> status do agent khai.
    item = _decision(text="Thống nhất tiến độ đạt 55%", status="reported", confirm_turn_id="T5")
    assert _flag(item, TURNS, judge=JUDGE).verdict == "uncertain"


def test_decision_confirmed_by_question_is_uncertain() -> None:
    item = _decision(text="Thống nhất dùng LLM tự host", confirm_turn_id="T6")
    flag = _flag(item, TURNS, judge=JUDGE)
    assert flag.verdict == "uncertain"


# ----- Đọc output của Content agent -----

def test_discussion_point_tags_speakers_of_cited_turns_in_speaking_order() -> None:
    task = {"segment_id": "S1", "turns": TURNS}
    result = {"discussion_points": [
        {"evidence_segment_ids": ["T6", "T2", "[T4|Hiếu]", "T6"], "text": "Có nên dùng LLM tự host."},
        {"evidence_segment_ids": ["T99"], "text": "Ý không có trích dẫn hợp lệ."},
        "không phải dict",
    ]}

    points, dropped = _build_discussion_points_from_llm_result(task, result)

    assert [(p.segment_id, p.text) for p in points] == [("S1", "Có nên dùng LLM tự host.")]
    assert points[0].speakers == ("Chị Mai", "Hiếu", "Anh Tuấn")
    assert points[0].evidence_turn_ids == ("T2", "T4", "T6")
    assert points[0].quotes == tuple(t.text_exact for t in (TURNS[1], TURNS[3], TURNS[5]))
    # Ý không trích dẫn và mục sai kiểu bị đếm.
    assert dropped == 2


def test_discussion_point_speaker_ids_follow_cited_turns() -> None:
    turns = (
        SpeakerTurn("T1", "Anh Tuấn", "Hay là mình dùng LLM tự host?", None, None, speaker_id="P1"),
        SpeakerTurn("T2", "Chị Mai", "Em thấy chi phí GPU cao.", None, None),
        SpeakerTurn("T3", "Anh Tuấn #2", "Tôi nghĩ thuê API rẻ hơn.", None, None, speaker_id="P3"),
    )
    result = {"discussion_points": [{"evidence_segment_ids": ["T1", "T2", "T3"], "text": "Tự host hay thuê API."}]}

    points, _ = _build_discussion_points_from_llm_result({"segment_id": "S1", "turns": turns}, result)

    assert points[0].speakers == ("Anh Tuấn", "Chị Mai", "Anh Tuấn #2")
    assert points[0].speaker_ids == ("P1", None, "P3")


# ----- Gộp trùng -----

def test_merge_duplicate_assignments_prefers_item_with_deadline() -> None:
    first = _action(
        segment_id="S0", actor="Anh Tuấn", deadline_raw=None, evidence_turn_ids=("T1",), quotes=("q1",),
        text="Làm phụ lục đề xuất riêng gửi anh Phong về việc chuyển ứng dụng di động sang giai đoạn 2",
    )
    second = _action(
        segment_id="S1", actor="Anh Tuấn", deadline_raw="trong tháng 12", evidence_turn_ids=("T3",), quotes=("q3",),
        text="Làm phụ lục đề xuất ứng dụng di động cho giai đoạn 2 gửi Anh Phong",
    )
    merged = merge_duplicate_assignments([first, second])
    assert len(merged) == 1
    assert merged[0].deadline_raw == "trong tháng 12"
    assert merged[0].segment_id == "S0"
    assert merged[0].evidence_turn_ids == ("T3", "T1")


def test_merge_duplicate_assignments_keeps_different_people_and_tasks() -> None:
    a = _action(actor="Hiếu", text="Map lại nhãn sang 12 lĩnh vực")
    b = _action(actor="Nam", text="Map lại nhãn sang 12 lĩnh vực")
    c = _action(actor="Hiếu", text="Bóc dữ liệu từ báo cáo giám sát")
    assert len(merge_duplicate_assignments([a, b, c])) == 3


def test_merge_duplicate_decisions() -> None:
    a = _decision(text="Thống nhất lộ trình: hoàn thành các nội dung đã thống nhất trước 15/12, vận hành thử 30 ngày")
    b = _decision(text="Thống nhất lộ trình triển khai và nghiệm thu: hoàn thành các nội dung trước 15/12, vận hành thử 30 ngày rồi nghiệm thu")
    c = _decision(text="Không hiển thị họ tên người kiến nghị trên trang công khai")
    merged = merge_duplicate_decisions([a, b, c])
    assert [d.text for d in merged] == [b.text, c.text]


# ----- Luật áp lên verdict của judge -----

def _task(candidate, kind="action"):
    return {"kind": kind, "candidate": candidate, "turns": TURNS}


def test_judge_keep_without_valid_deciding_turn_becomes_drop() -> None:
    verdict, turn_id = resolve_verdict(_task(_action()), {"verdict": "keep", "deciding_turn_id": "T99"})
    assert (verdict, turn_id) == ("drop", None)


def test_judge_suggests_actor_but_never_edits_candidate() -> None:
    # Verifier chỉ đề xuất bên nhận việc; agent trích xuất mới sửa candidate.
    candidate = _action(actor="một thành viên")
    revised = [{"name": "Hiếu", "role": "lead", "type": "person"}]
    for raw_verdict in ("revise", "keep"):  # keep kèm đề xuất bên khác cũng thành revise
        verdict, turn_id = resolve_verdict(
            _task(candidate), {"verdict": raw_verdict, "deciding_turn_id": "[T3|Anh Tuấn]", "revised_assignees": revised}
        )
        assert (verdict, turn_id) == ("revise", "T3")
    assert candidate.actor == "một thành viên"


def test_judge_revise_without_assignees_or_with_unknown_falls_back_to_keep() -> None:
    task = _task(_action(actor="một thành viên"))
    for revised in ([], [{"name": "một thành viên", "role": "lead", "type": "unknown"}]):
        verdict, _ = resolve_verdict(
            task, {"verdict": "revise", "deciding_turn_id": "T3", "revised_assignees": revised}
        )
        assert verdict == "keep"


def test_judge_revise_on_decision_is_keep_and_unknown_verdict_is_drop() -> None:
    assert resolve_verdict(_task(_decision(), "decision"), {"verdict": "revise", "deciding_turn_id": "T3"})[0] == "keep"
    assert resolve_verdict(_task(_decision(), "decision"), {"verdict": "maybe", "deciding_turn_id": "T3"})[0] == "drop"


# ----- Gộp trùng theo tập bên nhận việc / khớp nhãn người nói -----


def test_merge_duplicate_assignments_ignores_order_of_assignees() -> None:
    def declared(names: list[str], text: str, **overrides) -> ActionItemCandidate:
        mentions = read_assignee_mentions([{"name": n, "role": "joint", "type": "organization"} for n in names])
        return _action(actor=format_actor(mentions), mentions=mentions, text=text, **overrides)

    a = declared(["Sở Tài chính", "Sở Xây dựng"], "Rà soát danh mục vốn đầu tư công", deadline_raw=None)
    b = declared(["Sở Xây dựng", "Sở Tài chính"], "Rà soát danh mục vốn đầu tư công trước 30/11")
    c = declared(["Sở Tài chính"], "Rà soát danh mục vốn đầu tư công")

    merged = merge_duplicate_assignments([a, b, c])
    assert [i.actor for i in merged] == ["Sở Xây dựng, Sở Tài chính", "Sở Tài chính"]  # b có hạn nên được giữ


def test_claimed_speaker_name_matches_label_with_brackets_unless_two_labels_collide() -> None:
    turns = (_turn("T1", "Phạm Hồng Sơn (HNI)", "x"), _turn("T2", "Hiếu", "y"))
    assert match_claimed_name_to_real_speaker("Phạm Hồng Sơn", turns) == "Phạm Hồng Sơn (HNI)"
    assert match_claimed_name_to_real_speaker("Sơn", turns) == "Phạm Hồng Sơn (HNI)"
    collide = (_turn("T1", "Sơn (A)", "x"), _turn("T2", "Sơn (B)", "y"))
    assert match_claimed_name_to_real_speaker("Sơn", collide) is None
