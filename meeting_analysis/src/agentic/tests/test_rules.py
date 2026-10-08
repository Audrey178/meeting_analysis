"""Unit test cho các luật 0 token của ``src.agentic``: Evidence-Check, làm sạch
output ("giao <actor>", luận điểm giao việc), gộp trùng và luật áp lên verdict
của judge.

Các ca lấy từ lỗi thật judge eval đã gắn cờ (``eval/results/dialtreeseg_v1``),
rút gọn thành vài lượt nói.
"""

from __future__ import annotations

from src.agentic._shared import (
    check_action_evidence,
    check_decision_evidence,
    is_assignment_point,
    merge_duplicate_assignments,
    merge_duplicate_decisions,
    strip_assignment_prefix,
)
from src.agentic.nodes.debate_judge_agent import _resolve_verdict
from src.agentic.schemas import ActionItemCandidate, DecisionCandidate
from src.utils.contracts import SpeakerTurn


def _turn(turn_id: str, speaker: str, text: str) -> SpeakerTurn:
    return SpeakerTurn(turn_id, speaker, text, (), None, None)


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


def _action(**overrides) -> ActionItemCandidate:
    base = dict(
        segment_id="S0", actor="Hiếu", text="Map lại nhãn sang 12 lĩnh vực", evidence_ids=("T3",),
        quotes=(TURNS[2].text_exact,), deadline_raw="trước ngày 25/11", status="assigned", confirm_turn_id="T3",
    )
    return ActionItemCandidate(**{**base, **overrides})


def _decision(**overrides) -> DecisionCandidate:
    base = dict(
        segment_id="S0", text="Dùng danh mục 12 lĩnh vực mới", evidence_ids=("T3",),
        quotes=(TURNS[2].text_exact,), status="agreed", confirm_turn_id="T3",
    )
    return DecisionCandidate(**{**base, **overrides})


# ----- Evidence-Check: action -----

def test_action_assigned_by_chair_is_clear() -> None:
    assert check_action_evidence(_action(), TURNS).verdict == "clear"


def test_action_self_commitment_by_actor_is_clear() -> None:
    item = _action(status="self_committed", confirm_turn_id="T4", text="Làm việc với nhà cung cấp")
    assert check_action_evidence(item, TURNS).verdict == "clear"


def test_action_self_reported_proposal_is_uncertain() -> None:
    # Đề xuất của thành viên bị viết lại thành việc giao: actor có tên nên bản cũ để lọt.
    item = _action(actor="Chị Mai", status="proposed", confirm_turn_id="T2", text="Tự động mở lại phản ánh")
    flag = check_action_evidence(item, TURNS)
    assert flag.verdict == "uncertain"
    assert any("proposed" in reason for reason in flag.reasons)
    assert any("đề xuất" in reason for reason in flag.reasons)


def test_action_hedged_confirm_turn_is_uncertain_even_if_status_claims_assigned() -> None:
    item = _action(actor="Chị Mai", confirm_turn_id="T2", text="Tự động mở lại phản ánh")
    assert check_action_evidence(item, TURNS).verdict == "uncertain"


def test_action_without_any_commit_cue_is_uncertain() -> None:
    # Kiến nghị của đại biểu + "xin ghi nhận ý kiến": không có từ do dự nào, nhưng
    # cũng không ai nhận việc (lỗi thật synth_013/a0 mà bản luật cũ để lọt).
    for confirm in ("T7", "T8"):
        item = _action(actor="Sở Tài chính", confirm_turn_id=confirm, text="Báo cáo nêu rõ danh mục dự án")
        flag = check_action_evidence(item, TURNS)
        assert flag.verdict == "uncertain", confirm
        assert any("không có từ chốt" in reason for reason in flag.reasons)


def test_action_without_confirm_turn_is_uncertain() -> None:
    assert check_action_evidence(_action(confirm_turn_id=None), TURNS).verdict == "uncertain"


def test_action_actor_not_in_segment_is_uncertain() -> None:
    flag = check_action_evidence(_action(actor="hộ dân"), TURNS)
    assert flag.verdict == "uncertain"
    assert any("không xuất hiện" in reason for reason in flag.reasons)


def test_action_actor_known_from_previous_topic_is_grounded() -> None:
    item = _action(actor="Linh")
    assert check_action_evidence(item, TURNS).verdict == "uncertain"
    assert check_action_evidence(item, TURNS, known_names=("Linh",)).verdict == "clear"


def test_action_self_commitment_spoken_by_someone_else_is_uncertain() -> None:
    item = _action(actor="Chị Mai", status="self_committed", confirm_turn_id="T4")
    assert check_action_evidence(item, TURNS).verdict == "uncertain"


def test_action_unknown_actor_is_uncertain() -> None:
    assert check_action_evidence(_action(actor=None), TURNS).verdict == "uncertain"
    assert check_action_evidence(_action(actor="một thành viên"), TURNS).verdict == "uncertain"


# ----- Evidence-Check: decision -----

def test_decision_agreed_with_chair_confirmation_is_clear() -> None:
    assert check_decision_evidence(_decision(), TURNS).verdict == "clear"


def test_decision_status_report_rewritten_as_agreement_is_uncertain() -> None:
    # Câu agent viết nghe như kết luận, nhưng lượt chốt là báo cáo -> status do agent khai.
    item = _decision(text="Thống nhất tiến độ đạt 55%", status="reported", confirm_turn_id="T5")
    assert check_decision_evidence(item, TURNS).verdict == "uncertain"


def test_decision_confirmed_by_question_is_uncertain() -> None:
    item = _decision(text="Thống nhất dùng LLM tự host", confirm_turn_id="T6")
    flag = check_decision_evidence(item, TURNS)
    assert flag.verdict == "uncertain"


def test_decision_hedge_in_text_still_flagged() -> None:
    assert check_decision_evidence(_decision(text="Dự kiến dùng PhoBERT"), TURNS).verdict == "uncertain"


def test_hedge_cue_does_not_match_inside_compound_word() -> None:
    turns = (_turn("T1", "A", "Thống nhất bổ sung dữ liệu mẫu."),)
    item = _decision(confirm_turn_id="T1", evidence_ids=("T1",))
    assert check_decision_evidence(item, turns).verdict == "clear"


# ----- Làm sạch output -----

def test_strip_assignment_prefix_removes_giao_and_actor() -> None:
    assert strip_assignment_prefix("giao Hiếu map lại nhãn", "Hiếu") == "Map lại nhãn"
    assert strip_assignment_prefix("giao Anh Tuấn làm phụ lục", "Anh Tuấn") == "Làm phụ lục"
    assert strip_assignment_prefix("Giao cho chị Mai cập nhật đặc tả", "Chị Mai") == "Cập nhật đặc tả"
    assert strip_assignment_prefix("Ông Bình phải lập tiến độ", "Ông Bình") == "Lập tiến độ"


def test_strip_assignment_prefix_keeps_clean_text_and_other_names() -> None:
    assert strip_assignment_prefix("Map lại nhãn", "Hiếu") == "Map lại nhãn"
    # Tên khác actor ở đầu câu không bị cắt.
    assert strip_assignment_prefix("Phối hợp với Nam tích hợp SMS", "Hiếu") == "Phối hợp với Nam tích hợp SMS"
    assert strip_assignment_prefix("giao", None) == "giao"


def test_is_assignment_point() -> None:
    assert is_assignment_point("Giao nhiệm vụ cho Hiếu hoàn thành map nhãn trước 25/11.")
    assert is_assignment_point("Phân công Nam tích hợp SMS.")
    assert not is_assignment_point("Đề nghị không giao cho xã thực hiện vì thiếu nhân lực.")
    assert not is_assignment_point("Giao diện tra cứu cần responsive.")


# ----- Gộp trùng -----

def test_merge_duplicate_assignments_prefers_item_with_deadline() -> None:
    first = _action(
        segment_id="S0", actor="Anh Tuấn", deadline_raw=None, evidence_ids=("T1",), quotes=("q1",),
        text="Làm phụ lục đề xuất riêng gửi anh Phong về việc chuyển ứng dụng di động sang giai đoạn 2",
    )
    second = _action(
        segment_id="S1", actor="Anh Tuấn", deadline_raw="trong tháng 12", evidence_ids=("T3",), quotes=("q3",),
        text="Làm phụ lục đề xuất ứng dụng di động cho giai đoạn 2 gửi Anh Phong",
    )
    merged = merge_duplicate_assignments([first, second])
    assert len(merged) == 1
    assert merged[0].deadline_raw == "trong tháng 12"
    assert merged[0].segment_id == "S0"
    assert merged[0].evidence_ids == ("T3", "T1")


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
    return {"item_key": "k", "segment_id": "S0", "kind": kind, "candidate": candidate, "reasons": (), "turns": TURNS}


def test_judge_keep_without_valid_deciding_turn_becomes_drop() -> None:
    verdict, turn_id, _ = _resolve_verdict(_task(_action()), {"verdict": "keep", "deciding_turn_id": "T99"})
    assert (verdict, turn_id) == ("drop", None)


def test_judge_revise_sets_actor_and_marks_debate() -> None:
    task = _task(_action(actor="một thành viên"))
    verdict, turn_id, final = _resolve_verdict(
        task, {"verdict": "revise", "deciding_turn_id": "[T3|Anh Tuấn]", "revised_actor": "Hiếu"}
    )
    assert (verdict, turn_id, final.actor, final.verification) == ("revise", "T3", "Hiếu", "debate")


def test_judge_revise_with_vague_actor_falls_back_to_keep_and_unknown_actor() -> None:
    task = _task(_action(actor="một thành viên"))
    verdict, _, final = _resolve_verdict(
        task, {"verdict": "revise", "deciding_turn_id": "T3", "revised_actor": "nhóm"}
    )
    assert (verdict, final.actor) == ("keep", None)


def test_judge_revise_on_decision_is_keep_and_unknown_verdict_is_drop() -> None:
    assert _resolve_verdict(_task(_decision(), "decision"), {"verdict": "revise", "deciding_turn_id": "T3"})[0] == "keep"
    assert _resolve_verdict(_task(_decision(), "decision"), {"verdict": "maybe", "deciding_turn_id": "T3"})[0] == "drop"
