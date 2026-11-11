"""Kiểm phần đối chiếu cuối: mỗi vấn đề chỉ còn một kết luận, mỗi việc chỉ còn một mục trên cả cuộc
họp. Bộ phân loại được giả lập trả quan hệ cố định cho từng cặp, nên các ca chỉ kiểm luật nhóm,
thay và gộp.
"""

from __future__ import annotations

from ...utils.contracts import SpeakerTurn
from ..shared.schemas import ActionItemCandidate, DecisionCandidate
from ..shared.judges.turn_act import DecisionRelationJudgement
from ..step6_finalize.reconcile import reconcile_assignments, reconcile_decisions

TURNS = {f"T{i}": SpeakerTurn(f"T{i}", "Anh A", f"lượt {i}", None, None) for i in range(1, 11)}


def _decision(text: str, confirm: str, segment: str = "S0") -> DecisionCandidate:
    return DecisionCandidate(
        segment_id=segment, text=text, evidence_turn_ids=(confirm,), quotes=(f"trích {confirm}",),
        status="agreed", confirm_turn_id=confirm, item_ids=(confirm.lower(),),
    )


class RelationJudge:
    """Decisions API giả: quan hệ theo cặp (câu trước, câu sau); cặp không khai là khác vấn đề."""

    def __init__(self, relations: dict[tuple[str, str], str | dict[str, float]], fail: set = frozenset()):
        self.relations = relations
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def judge_relation(self, earlier, later):
        self.calls.append((earlier, later))
        if (earlier, later) in self.fail:
            raise RuntimeError("API lỗi")
        found = self.relations.get((earlier, later), "different_matter")
        probabilities = found if isinstance(found, dict) else {found: 0.9, "different_matter" if found != "different_matter" else "unchanged": 0.1}
        label = max(probabilities, key=probabilities.get)
        return DecisionRelationJudgement(label=label, probabilities=probabilities)


TRINH_TTG = "Hoàn thiện tờ trình để trình Thủ tướng"
LAM_LAI = "Làm lại tờ trình theo hướng xin ý kiến cụ thể"
TEN_DE_AN = "Xem lại tên đề án"


def test_later_conclusion_that_changes_the_earlier_one_replaces_it_across_topics() -> None:
    judge = RelationJudge({(TRINH_TTG, LAM_LAI): "changed"})

    result = reconcile_decisions(
        [_decision(TRINH_TTG, "T2", "S0"), _decision(LAM_LAI, "T9", "S2")], TURNS, judge
    )

    assert [d.text for d in result.items] == [LAM_LAI]
    assert result.items[0].segment_id == "S2"
    (record,) = result.records
    assert (record.verdict, record.candidate_text, record.final_text) == ("superseded", TRINH_TTG, LAM_LAI)
    assert record.deciding_turn_id == "T9" and record.decided_by == "reconcile"


def test_same_issue_without_change_keeps_the_earlier_text_and_merges_evidence() -> None:
    restated = "Đề án cần xem lại tên gọi"
    judge = RelationJudge({(TEN_DE_AN, restated): "unchanged"})

    result = reconcile_decisions([_decision(TEN_DE_AN, "T3"), _decision(restated, "T8", "S2")], TURNS, judge)

    (kept,) = result.items
    assert kept.text == TEN_DE_AN and kept.confirm_turn_id == "T3"
    assert kept.evidence_turn_ids == ("T3", "T8") and kept.item_ids == ("t3", "t8")
    assert [(r.verdict, r.candidate_text) for r in result.records] == [("merged", restated)]


def test_different_issues_stay_separate() -> None:
    judge = RelationJudge({})

    result = reconcile_decisions([_decision(TEN_DE_AN, "T3"), _decision(LAM_LAI, "T9")], TURNS, judge)

    assert [d.text for d in result.items] == [TEN_DE_AN, LAM_LAI]
    assert result.records == ()


def test_unsure_same_issue_is_not_grouped() -> None:
    judge = RelationJudge({(TRINH_TTG, LAM_LAI): {"changed": 0.3, "unchanged": 0.1, "different_matter": 0.6}})

    result = reconcile_decisions([_decision(TRINH_TTG, "T2"), _decision(LAM_LAI, "T9")], TURNS, judge)

    assert [d.text for d in result.items] == [TRINH_TTG, LAM_LAI]


def test_different_issue_as_top_answer_is_not_grouped_even_if_same_choices_sum_past_threshold() -> None:
    judge = RelationJudge({(TRINH_TTG, LAM_LAI): {"changed": 0.43, "unchanged": 0.12, "different_matter": 0.45}})

    result = reconcile_decisions([_decision(TRINH_TTG, "T2"), _decision(LAM_LAI, "T9")], TURNS, judge)

    assert [d.text for d in result.items] == [TRINH_TTG, LAM_LAI]
    assert result.records == ()


def test_same_issue_but_change_not_dominant_keeps_the_earlier_conclusion() -> None:
    judge = RelationJudge({(TRINH_TTG, LAM_LAI): {"changed": 0.45, "unchanged": 0.5, "different_matter": 0.05}})

    result = reconcile_decisions([_decision(TRINH_TTG, "T2"), _decision(LAM_LAI, "T9")], TURNS, judge)

    assert [d.text for d in result.items] == [TRINH_TTG]
    assert result.records[0].verdict == "merged"


def test_order_follows_the_closing_turn_not_the_input_order() -> None:
    judge = RelationJudge({(TRINH_TTG, LAM_LAI): "changed"})

    result = reconcile_decisions([_decision(LAM_LAI, "T9", "S2"), _decision(TRINH_TTG, "T2", "S0")], TURNS, judge)

    assert [d.text for d in result.items] == [LAM_LAI]
    assert judge.calls == [(TRINH_TTG, LAM_LAI)]


def test_chain_compares_against_the_current_conclusion_of_the_group() -> None:
    again = "Chuẩn bị lại tờ trình, khi nào đủ điều kiện thì báo cáo"
    judge = RelationJudge({(TRINH_TTG, LAM_LAI): "changed", (LAM_LAI, again): "unchanged"})

    result = reconcile_decisions(
        [_decision(TRINH_TTG, "T2"), _decision(LAM_LAI, "T8"), _decision(again, "T10")], TURNS, judge
    )

    (final,) = result.items
    assert final.text == LAM_LAI and final.evidence_turn_ids == ("T8", "T10")
    assert [r.verdict for r in result.records] == ["superseded", "merged"]


def test_points_of_the_same_closing_turn_are_never_compared() -> None:
    judge = RelationJudge({(TRINH_TTG, LAM_LAI): "changed"})

    result = reconcile_decisions([_decision(TRINH_TTG, "T9"), _decision(LAM_LAI, "T9")], TURNS, judge)

    assert [d.text for d in result.items] == [TRINH_TTG, LAM_LAI]
    assert judge.calls == []


def test_api_error_keeps_both_conclusions() -> None:
    judge = RelationJudge({(TRINH_TTG, LAM_LAI): "changed"}, fail={(TRINH_TTG, LAM_LAI)})

    result = reconcile_decisions([_decision(TRINH_TTG, "T2"), _decision(LAM_LAI, "T9")], TURNS, judge)

    assert [d.text for d in result.items] == [TRINH_TTG, LAM_LAI]


def test_call_budget_leaves_remaining_pairs_separate() -> None:
    judge = RelationJudge({(TRINH_TTG, LAM_LAI): "changed"})

    result = reconcile_decisions([_decision(TRINH_TTG, "T2"), _decision(LAM_LAI, "T9")], TURNS, judge, max_calls=0)

    assert [d.text for d in result.items] == [TRINH_TTG, LAM_LAI]
    assert (result.calls, result.skipped_pairs, judge.calls) == (0, 1, [])


def test_best_matching_group_wins_when_several_are_the_same_issue() -> None:
    other = "Trình đề án lên Ban Thường vụ"
    judge = RelationJudge({
        (TRINH_TTG, LAM_LAI): {"changed": 0.75, "unchanged": 0.0, "different_matter": 0.25},
        (other, LAM_LAI): {"changed": 0.95, "unchanged": 0.0, "different_matter": 0.05},
    })

    result = reconcile_decisions(
        [_decision(TRINH_TTG, "T2"), _decision(other, "T4"), _decision(LAM_LAI, "T9")], TURNS, judge
    )

    assert [d.text for d in result.items] == [TRINH_TTG, LAM_LAI]
    assert result.records[0].candidate_text == other


class _Embedder:
    vectors = {TRINH_TTG: (1.0, 0.0), LAM_LAI: (0.9, 0.1), TEN_DE_AN: (0.0, 1.0), "Bổ sung cơ chế đặc thù": (0.1, 0.9)}

    def embed_many(self, texts):
        return [self.vectors[text] for text in texts]


def test_embedder_limits_questions_to_the_nearest_groups() -> None:
    judge = RelationJudge({(TRINH_TTG, LAM_LAI): "changed"})
    items = [_decision(TEN_DE_AN, "T1"), _decision("Bổ sung cơ chế đặc thù", "T3"), _decision(TRINH_TTG, "T5"),
             _decision(LAM_LAI, "T9")]

    result = reconcile_decisions(items, TURNS, judge, embedder=_Embedder(), top_k=1)

    assert (TRINH_TTG, LAM_LAI) in judge.calls
    assert all(earlier != TEN_DE_AN for earlier, later in judge.calls if later == LAM_LAI)
    assert [d.text for d in result.items] == [TEN_DE_AN, "Bổ sung cơ chế đặc thù", LAM_LAI]


def test_without_relation_judge_falls_back_to_text_dedup() -> None:
    result = reconcile_decisions([_decision(TEN_DE_AN, "T3"), _decision(TEN_DE_AN + ".", "T8")], TURNS, None)

    assert [d.text for d in result.items] == [TEN_DE_AN + "."]
    assert result.records == ()


# ----- Việc giao (AssignmentKind) -----


def _task(text: str, confirm: str, actor: str = "Sở Xây dựng", deadline: str | None = None,
          segment: str = "S0") -> ActionItemCandidate:
    return ActionItemCandidate(
        segment_id=segment, actor=actor, text=text, evidence_turn_ids=(confirm,), quotes=(f"trích {confirm}",),
        deadline_raw=deadline, confirm_turn_id=confirm, item_ids=(confirm.lower(),),
    )


class AssignmentJudge(RelationJudge):
    """Như ``RelationJudge`` nhưng khoá theo câu việc (dòng đầu của input có kèm bên nhận việc/thời hạn)."""

    def judge_assignment_relation(self, earlier, later):
        self.calls.append((earlier, later))
        return RelationJudge.judge_relation(self, earlier.split("\n")[0], later.split("\n")[0])


def test_later_assignment_that_changes_the_earlier_one_replaces_it() -> None:
    judge = AssignmentJudge({(TRINH_TTG, LAM_LAI): "changed"})

    result = reconcile_assignments([_task(TRINH_TTG, "T2"), _task(LAM_LAI, "T9", segment="S2")], TURNS, judge)

    assert [a.text for a in result.items] == [LAM_LAI]
    (record,) = result.records
    assert (record.kind, record.verdict, record.candidate_text) == ("action", "superseded", TRINH_TTG)


def test_same_assignment_restated_keeps_earlier_text_and_takes_later_deadline() -> None:
    restated = "Làm lại tờ trình"
    judge = AssignmentJudge({(LAM_LAI, restated): "unchanged"})

    result = reconcile_assignments([_task(LAM_LAI, "T3"), _task(restated, "T8", deadline="trước 30/11")], TURNS, judge)

    (kept,) = result.items
    assert (kept.text, kept.deadline_raw, kept.evidence_turn_ids) == (LAM_LAI, "trước 30/11", ("T3", "T8"))
    assert [r.verdict for r in result.records] == ["merged"]


def test_assignments_with_different_assignees_are_never_compared() -> None:
    judge = AssignmentJudge({(LAM_LAI, LAM_LAI): "unchanged"})

    result = reconcile_assignments([_task(LAM_LAI, "T3"), _task(LAM_LAI, "T8", actor="Sở Tài chính")], TURNS, judge)

    assert len(result.items) == 2 and judge.calls == []


def test_assignment_input_carries_assignee_and_deadline() -> None:
    judge = AssignmentJudge({})

    reconcile_assignments([_task(LAM_LAI, "T3"), _task(TEN_DE_AN, "T8", deadline="tháng 12")], TURNS, judge)

    (earlier, later), _ = judge.calls
    assert "Sở Xây dựng" in earlier and "tháng 12" in later


def test_assignments_without_relation_judge_fall_back_to_text_dedup() -> None:
    result = reconcile_assignments([_task(LAM_LAI, "T3"), _task(LAM_LAI + ".", "T8")], TURNS, RelationJudge({}))

    assert [a.text for a in result.items] == [LAM_LAI + "."]
