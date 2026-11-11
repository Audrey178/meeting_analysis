"""Đối chiếu các mục trên cả cuộc họp để mỗi vấn đề chỉ còn MỘT mục cuối.

Trong một cuộc họp, cùng một vấn đề có thể được chốt nhiều lần, lần sau sửa hoặc thay lần trước.
Các mục được xét theo thứ tự xuất hiện; mỗi mục mới được hỏi xem có cùng vấn đề với mục nào đã có
không, và nếu có thì nó thay thế hay bổ sung mục cũ. Kết quả là mục cuối của mỗi vấn đề, kèm ghi chép
những mục đã bị thay hoặc gộp.

Cách làm này dùng chung cho kết luận, việc giao và tiến độ; mỗi loại tự quy định cặp nào cần so và
so như thế nào.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Generic, Protocol, TypeVar

from ...utils.contracts import SpeakerTurn
from ..shared.schemas import ActionItemCandidate, DecisionCandidate, VerificationRecord
from ..shared.judges.turn_act import RELATION_CHANGE_MIN, RELATION_SAME_MIN, DecisionRelationJudgement
from .dedup import _assignee_group, merge_duplicate_assignments, merge_duplicate_decisions, merge_evidence

logger = logging.getLogger(__name__)

# Số nhóm gần nghĩa nhất được hỏi cho mỗi mục khi có embedder, và trần lời gọi Decisions API mỗi cuộc
# họp (Cái Mép ~10 kết luận cần dưới 50 lời; cuộc họp 40 kết luận với top_k=3 cần dưới 120).
DEFAULT_TOP_K = 3
DEFAULT_MAX_CALLS = 300

T = TypeVar("T")


class TextEmbedder(Protocol):
    """Hợp đồng cho bộ tạo vector câu.

    ``embed_many`` phải trả đúng một vector cho mỗi câu, cùng thứ tự với đầu vào; vector nên được chuẩn
    hoá để so bằng cosine.
    """

    def embed_many(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


@dataclass(frozen=True, slots=True)
class Relation:
    """Quan hệ "cùng vấn đề" giữa một mục mới và mục hiện hành của một nhóm.

    Attributes:
        same: Độ chắc hai mục cùng vấn đề; khi nhiều nhóm cùng nhận, mục mới vào nhóm có giá trị cao nhất.
        changed: True nếu mục mới thay mục hiện hành; False thì mục mới được gộp vào mục hiện hành.
        note: Mô tả ngắn để ghi log và bản ghi đối chiếu.
    """

    same: float
    changed: bool
    note: str = ""


class ReconcileKind(Protocol[T]):
    """Hợp đồng mô tả một loại mục (kết luận, việc giao, tiến độ) cho thuật toán đối chiếu chung.

    Mỗi loại tự quy định thứ tự mục, cặp nào được so, cách hỏi quan hệ, cách gộp và cách ghi bản ghi.
    """

    def position(self, item: T) -> int:
        """Trả vị trí của mục trong cuộc họp; mục được xét theo vị trí tăng dần."""

    def may_compare(self, earlier: T, later: T) -> bool:
        """Lọc bằng luật trước khi hỏi quan hệ; False nghĩa là chắc chắn khác vấn đề, không cần hỏi."""

    def relate(self, earlier: T, later: T) -> Relation | None:
        """Xác định quan hệ của mục sau với mục hiện hành.

        Returns:
            Quan hệ nếu cùng vấn đề; None nếu khác vấn đề, chưa chắc hoặc lỗi (mục sau được để riêng).
        """

    def merge(self, kept: T, other: T) -> T:
        """Gộp ``other`` (cùng vấn đề, không thay đổi nội dung) vào mục hiện hành ``kept``."""

    def record(self, old: T, new: T, verdict: str, relation: Relation, index: int) -> VerificationRecord | None:
        """Tạo bản ghi cho mục bị thay hoặc bị gộp.

        Args:
            old: Mục bị thay (khi thay) hoặc mục bị gộp vào (khi gộp).
            new: Mục còn lại sau khi thay hoặc gộp.
            verdict: "superseded" (bị thay) hoặc "merged" (bị gộp).
            relation: Quan hệ đã xác định giữa hai mục.
            index: Số thứ tự bản ghi, dùng để tạo khoá duy nhất.

        Returns:
            Bản ghi đối chiếu; None nếu loại mục này không ghi.
        """


@dataclass(frozen=True, slots=True)
class ReconcileResult(Generic[T]):
    """Kết quả đối chiếu.

    Attributes:
        items: Mục cuối, mỗi vấn đề một mục, theo thứ tự lần đầu vấn đề xuất hiện.
        records: Bản ghi các mục bị thay hoặc bị gộp.
        calls: Số lần đã hỏi quan hệ.
        skipped_pairs: Số cặp bị bỏ qua vì hết ngân sách lời gọi (các mục đó được để riêng).
    """

    items: tuple[T, ...]
    records: tuple[VerificationRecord, ...] = ()
    calls: int = 0
    skipped_pairs: int = field(default=0)


@dataclass(slots=True)
class _Group(Generic[T]):
    """Một vấn đề đang theo dõi trong quá trình đối chiếu.

    Attributes:
        current: Mục hiện hành của vấn đề.
        vector: Vector câu của mục hiện hành (hoặc của mục trước nó nếu mục mới chưa có vector); None khi
            không dùng embedder.
        first_index: Vị trí (theo thứ tự đã sắp) của mục đầu tiên của vấn đề, dùng để sắp kết quả.
    """

    current: T
    vector: Sequence[float] | None = None
    first_index: int = 0


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Tính độ tương đồng cosine của hai vector; 0 nếu một vector có độ dài 0."""

    dot = sum(a * b for a, b in zip(left, right))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


def reconcile(
    items: Sequence[T],
    kind: ReconcileKind[T],
    *,
    embedder: TextEmbedder | None = None,
    text: Callable[[T], str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    max_calls: int = DEFAULT_MAX_CALLS,
) -> ReconcileResult[T]:
    """Gom các mục cùng vấn đề của cả cuộc họp, giữ mục cuối cùng của mỗi vấn đề.

    Mục được xét theo vị trí trong cuộc họp. Mỗi mục được so với mục hiện hành của các nhóm đã có (nhóm
    gần đây trước, hoặc ``top_k`` nhóm gần nghĩa nhất khi có embedder) và vào nhóm có độ chắc "cùng vấn
    đề" cao nhất: thay mục hiện hành nếu nó thay đổi nội dung, không thì gộp vào. Không khớp nhóm nào thì
    mở nhóm mới. Embedder lỗi thì quay về so với mọi nhóm.

    Args:
        items: Mục đã kiểm chứng của mọi chủ đề, thứ tự bất kỳ.
        kind: Mô tả loại mục (xem ``ReconcileKind``).
        embedder: Bộ tạo vector câu, tuỳ chọn; chỉ dùng khi có cả ``text`` và số mục lớn hơn ``top_k``.
        text: Hàm lấy câu của một mục để tạo vector.
        top_k: Số nhóm gần nghĩa nhất được hỏi cho mỗi mục khi có vector.
        max_calls: Trần số lần hỏi quan hệ; hết ngân sách thì các cặp còn lại bị bỏ qua và mục được để
            riêng.

    Returns:
        Mục cuối của mỗi vấn đề, bản ghi các mục bị thay/gộp và số liệu lời gọi.
    """

    ranked = sorted(enumerate(items), key=lambda pair: (kind.position(pair[1]), pair[0]))
    vectors: dict[int, Sequence[float]] = {}
    if embedder is not None and text is not None and len(ranked) > top_k:
        try:
            embedded = embedder.embed_many([text(item) for _, item in ranked])
            vectors = {index: vector for (index, _), vector in zip(ranked, embedded)}
        except Exception as exc:  # noqa: BLE001 -- embedder lỗi: hỏi mọi nhóm, vẫn chịu trần lời gọi
            logger.warning("reconcile: embedder lỗi, so với mọi nhóm: %s", exc)

    groups: list[_Group[T]] = []
    records: list[VerificationRecord] = []
    calls = skipped = 0
    for position, (index, item) in enumerate(ranked):
        vector = vectors.get(index)
        candidates = list(reversed(groups))  # nhóm gần đây trước
        if vector is not None:
            candidates = sorted(groups, key=lambda group: -_cosine(vector, group.vector or ()))[:top_k]
        best: tuple[_Group[T], Relation] | None = None
        for group in candidates:
            if not kind.may_compare(group.current, item):
                continue
            if calls >= max_calls:
                skipped += 1
                continue
            calls += 1
            relation = kind.relate(group.current, item)
            if relation is not None and (best is None or relation.same > best[1].same):
                best = (group, relation)
        if best is None:
            groups.append(_Group(item, vector, position))
            continue
        group, relation = best
        if relation.changed:
            record = kind.record(group.current, item, "superseded", relation, len(records))
            group.current, group.vector = item, vector if vector is not None else group.vector
        else:
            group.current = kind.merge(group.current, item)
            record = kind.record(item, group.current, "merged", relation, len(records))
        if record is not None:
            records.append(record)
    if skipped:
        logger.warning("reconcile: hết ngân sách %d lời gọi, bỏ qua %d cặp (để riêng)", max_calls, skipped)
    final = tuple(group.current for group in sorted(groups, key=lambda group: group.first_index))
    return ReconcileResult(final, tuple(records), calls, skipped)


class _ClosingTurnKind:
    """Phần chung của kết luận và việc giao: xếp vị trí theo lượt chốt và hỏi quan hệ qua Decisions API.

    Args:
        turns_by_id: Lượt nói của cả cuộc họp theo mã, giữ thứ tự thời gian.
        judge_relation: Hàm hỏi Decisions API quan hệ giữa hai câu (mục trước, mục sau).
    """

    def __init__(self, turns_by_id: Mapping[str, SpeakerTurn], judge_relation) -> None:
        self._order = {turn_id: index for index, turn_id in enumerate(turns_by_id)}
        self._judge_relation = judge_relation

    def position(self, item) -> int:
        """Trả vị trí lượt chốt; thiếu thì lấy lượt bằng chứng muộn nhất; không có gì thì cuối cuộc họp."""

        if item.confirm_turn_id in self._order:
            return self._order[item.confirm_turn_id]
        positions = [self._order[turn_id] for turn_id in item.evidence_turn_ids if turn_id in self._order]
        return max(positions) if positions else len(self._order)

    def may_compare(self, earlier, later) -> bool:
        """Không so hai mục có cùng lượt chốt, vì đó là các điểm khác nhau của một lời chốt."""
        # các điểm khác nhau của cùng một lời chốt: không phải cùng một vấn đề
        return not (later.confirm_turn_id and later.confirm_turn_id == earlier.confirm_turn_id)

    def _ask(self, earlier: str, later: str) -> Relation | None:
        """Hỏi Decisions API quan hệ giữa hai câu và quy về ``Relation``.

        Cùng vấn đề khi xác suất "cùng vấn đề" đủ ngưỡng và nhãn không phải "khác vấn đề"; thay đổi khi
        xác suất "thay đổi" đủ ngưỡng và lớn hơn xác suất "giữ nguyên".

        Args:
            earlier: Câu của mục hiện hành.
            later: Câu của mục mới.

        Returns:
            Quan hệ nếu cùng vấn đề; None nếu khác vấn đề, chưa chắc hoặc lời gọi API lỗi.
        """

        try:
            judgement: DecisionRelationJudgement = self._judge_relation(earlier, later)
        except Exception as exc:  # noqa: BLE001 -- Decisions API lỗi: coi như khác vấn đề
            logger.warning("reconcile: hỏi quan hệ lỗi (%s / %s): %s", earlier[:40], later[:40], exc)
            return None
    
        if judgement.p_same < RELATION_SAME_MIN or judgement.label == "different_matter":
            return None
        changed = judgement.p_change >= RELATION_CHANGE_MIN and judgement.p_change > judgement.p_keep
        return Relation(judgement.p_same, changed, judgement.describe())


class DecisionKind(_ClosingTurnKind):
    """Cách đối chiếu kết luận: so mọi cặp trừ hai điểm của cùng một lời chốt; quan hệ hỏi Decisions API.

    Ví dụ: đầu buổi chốt "Giữ phương án A", cuối buổi chốt "Chuyển sang phương án B" thì kết luận sau
    thay kết luận trước.
    """

    def relate(self, earlier: DecisionCandidate, later: DecisionCandidate) -> Relation | None:
        """Hỏi quan hệ giữa nội dung hai kết luận."""

        return self._ask(earlier.text, later.text)

    def merge(self, kept: DecisionCandidate, other: DecisionCandidate) -> DecisionCandidate:
        """Giữ câu của kết luận hiện hành, hợp thêm bằng chứng của kết luận sau."""

        return replace(kept, **merge_evidence(kept, other))

    def record(self, old: DecisionCandidate, new: DecisionCandidate, verdict: str, relation: Relation,
               index: int) -> VerificationRecord:
        """Tạo bản ghi cho kết luận bị thay (``superseded``) hoặc bị gộp vào kết luận trước (``merged``)."""

        where = f"lượt {new.confirm_turn_id}" if new.confirm_turn_id else f"chủ đề {new.segment_id}"
        if verdict == "superseded":
            logger.info("reconcile: '%s' bị thay bởi '%s' (%s)", old.text[:50], new.text[:50], relation.note)
            reason = f"Kết luận chốt sau ở {where} thay đổi kết luận này ({relation.note})."
        else:
            reason = f"Cùng vấn đề với kết luận đã có, không thay đổi nội dung ({relation.note}); gộp dẫn chứng."
        return VerificationRecord(
            item_key=f"{old.segment_id}:decision:reconcile:{index}",
            segment_id=old.segment_id,
            kind="decision",
            candidate_text=old.text,
            reasons=(reason,),
            steps=(),
            verdict=verdict,
            reasoning=reason,
            final_text=new.text,
            deciding_turn_id=new.confirm_turn_id,
            decided_by="reconcile",
        )


def _assignment_text(item: ActionItemCandidate) -> str:
    """Dựng câu mô tả việc giao kèm bên nhận việc và thời hạn để hỏi quan hệ.

    Cần kèm thời hạn vì lần giao sau có thể chỉ đổi hạn mà giữ nguyên nội dung.
    """

    return f"{item.text}\nAssignee: {item.actor or 'unknown'}\nDeadline: {item.deadline_raw or 'not stated'}"


class AssignmentKind(_ClosingTurnKind):
    """Cách đối chiếu việc giao.

    Chỉ so hai việc có cùng tập bên nhận việc và khác lượt chốt; quan hệ hỏi Decisions API, gửi kèm bên
    nhận việc và thời hạn. Khi gộp, giữ câu của việc trước, lấy thời hạn của việc sau nếu việc trước chưa
    có, và hợp bằng chứng.
    """

    def may_compare(self, earlier: ActionItemCandidate, later: ActionItemCandidate) -> bool:
        """Chỉ so hai việc cùng tập bên nhận việc và không cùng lượt chốt."""

        return _assignee_group(earlier) == _assignee_group(later) and super().may_compare(earlier, later)

    def relate(self, earlier: ActionItemCandidate, later: ActionItemCandidate) -> Relation | None:
        """Hỏi quan hệ giữa hai việc giao, gửi kèm bên nhận việc và thời hạn."""

        return self._ask(_assignment_text(earlier), _assignment_text(later))

    def merge(self, kept: ActionItemCandidate, other: ActionItemCandidate) -> ActionItemCandidate:
        """Giữ câu việc hiện hành; bổ sung thời hạn từ việc sau nếu còn thiếu, và hợp bằng chứng."""

        deadline = {}
        if other.deadline_raw and not kept.deadline_raw:
            deadline = {"deadline_raw": other.deadline_raw, "deadline_date": other.deadline_date,
                        "deadline_kind": other.deadline_kind}
        return replace(kept, **deadline, **merge_evidence(kept, other))

    def record(self, old: ActionItemCandidate, new: ActionItemCandidate, verdict: str, relation: Relation,
               index: int) -> VerificationRecord:
        """Tạo bản ghi cho việc giao bị thay (``superseded``) hoặc bị gộp vào việc trước (``merged``)."""

        where = f"lượt {new.confirm_turn_id}" if new.confirm_turn_id else f"chủ đề {new.segment_id}"
        if verdict == "superseded":
            logger.info("reconcile: việc '%s' bị thay bởi '%s' (%s)", old.text[:50], new.text[:50], relation.note)
            reason = f"Lần giao sau ở {where} thay đổi việc này ({relation.note})."
        else:
            reason = f"Cùng việc với việc đã giao, không thay đổi nội dung ({relation.note}); gộp dẫn chứng."
        return VerificationRecord(
            item_key=f"{old.segment_id}:action:reconcile:{index}",
            segment_id=old.segment_id,
            kind="action",
            candidate_text=old.text,
            reasons=(reason,),
            steps=(),
            verdict=verdict,
            reasoning=reason,
            final_text=new.text,
            deciding_turn_id=new.confirm_turn_id,
            decided_by="reconcile",
        )


def reconcile_assignments(
    assignments: Sequence[ActionItemCandidate],
    turns_by_id: Mapping[str, SpeakerTurn],
    judge: object | None,
    *,
    embedder: TextEmbedder | None = None,
    top_k: int = DEFAULT_TOP_K,
    max_calls: int = DEFAULT_MAX_CALLS,
) -> ReconcileResult[ActionItemCandidate]:
    """Đối chiếu việc giao trên cả cuộc họp để mỗi việc chỉ còn một mục cuối.

    Args:
        assignments: Việc giao đã định danh bên nhận việc của mọi chủ đề.
        turns_by_id: Lượt nói của cả cuộc họp theo mã, giữ thứ tự thời gian.
        judge: Bộ phân loại có ``judge_assignment_relation``; None hoặc thiếu phương thức này thì chỉ gộp
            mục trùng theo chữ.
        embedder: Bộ tạo vector câu, tuỳ chọn (xem ``reconcile``).
        top_k: Số nhóm gần nghĩa nhất được hỏi cho mỗi mục.
        max_calls: Trần số lần hỏi quan hệ.

    Returns:
        Kết quả đối chiếu; khi chỉ gộp theo chữ thì không có bản ghi.
    """

    method = getattr(judge, "judge_assignment_relation", None) if judge is not None else None
    if not callable(method):
        return ReconcileResult(tuple(merge_duplicate_assignments(assignments)))
    return reconcile(assignments, AssignmentKind(turns_by_id, method), embedder=embedder,
                     text=lambda item: item.text, top_k=top_k, max_calls=max_calls)


def reconcile_decisions(
    decisions: Sequence[DecisionCandidate],
    turns_by_id: Mapping[str, SpeakerTurn],
    judge: object | None,
    *,
    embedder: TextEmbedder | None = None,
    top_k: int = DEFAULT_TOP_K,
    max_calls: int = DEFAULT_MAX_CALLS,
) -> ReconcileResult[DecisionCandidate]:
    """Đối chiếu kết luận trên cả cuộc họp để mỗi vấn đề chỉ còn một kết luận cuối.

    Args:
        decisions: Kết luận đã kiểm chứng của mọi chủ đề.
        turns_by_id: Lượt nói của cả cuộc họp theo mã, giữ thứ tự thời gian.
        judge: Bộ phân loại có ``judge_relation``; None hoặc thiếu phương thức này thì chỉ gộp mục trùng
            theo chữ.
        embedder: Bộ tạo vector câu, tuỳ chọn (xem ``reconcile``).
        top_k: Số nhóm gần nghĩa nhất được hỏi cho mỗi mục.
        max_calls: Trần số lần hỏi quan hệ.

    Returns:
        Kết quả đối chiếu; khi chỉ gộp theo chữ thì không có bản ghi.
    """

    method = getattr(judge, "judge_relation", None) if judge is not None else None
    if not callable(method):
        return ReconcileResult(tuple(merge_duplicate_decisions(decisions)))
    return reconcile(decisions, DecisionKind(turns_by_id, method), embedder=embedder,
                     text=lambda item: item.text, top_k=top_k, max_calls=max_calls)


__all__ = [
    "DEFAULT_MAX_CALLS",
    "DEFAULT_TOP_K",
    "AssignmentKind",
    "DecisionKind",
    "ReconcileKind",
    "ReconcileResult",
    "Relation",
    "TextEmbedder",
    "reconcile",
    "reconcile_assignments",
    "reconcile_decisions",
]
