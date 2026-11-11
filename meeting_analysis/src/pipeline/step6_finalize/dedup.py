"""Gộp các việc giao và kết luận trùng nội dung, trong cùng một chủ đề hoặc giữa các chủ đề. Hai mục
được coi là trùng khi phần lớn từ ngữ giống nhau (với việc giao thì còn phải cùng bên nhận việc);
khi gộp thì chỉ giữ một bản và hợp bằng chứng của cả hai.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from ..shared.actors.names import name_key
from ..shared.schemas import ActionItemCandidate, DecisionCandidate
from ..shared.text import content_tokens

_DUPLICATE_MIN_JACCARD = 0.45
_DUPLICATE_MIN_OVERLAP = 0.7


def _assignee_group(item: ActionItemCandidate) -> frozenset[str]:
    """Lấy tập khoá tên đã chuẩn hoá của các bên nhận một việc giao, không phụ thuộc thứ tự các bên.

    Ưu tiên các bên đã định danh; nếu chưa có thì dùng các cách gọi agent ghi, cuối cùng là chuỗi bên
    nhận việc. Hai việc giao chỉ được coi là cùng bên nhận khi hai tập này bằng nhau.
    """

    assignees = getattr(item, "assignees", ())
    names = [assignee.name or assignee.mention for assignee in assignees] or [m.name for m in item.mentions]
    if not names and item.actor:
        names = [item.actor]
    return frozenset(key for key in (name_key(name) for name in names) if key)


def _is_near_duplicate(left: str, right: str, drop: frozenset[str] = frozenset()) -> bool:
    """Kiểm hai câu có trùng nội dung không, theo tỉ lệ âm tiết nội dung chung.

    Phải đạt cả hai ngưỡng: phần chung so với hợp của hai tập (Jaccard) và so với tập nhỏ hơn.

    Args:
        left: Câu thứ nhất.
        right: Câu thứ hai.
        drop: Các âm tiết bỏ qua khi so, ví dụ tên bên nhận việc lẫn trong câu.

    Returns:
        True nếu trùng; False nếu một trong hai câu không còn âm tiết nội dung nào.
    """

    a, b = content_tokens(left, drop), content_tokens(right, drop)
    if not a or not b:
        return False
    shared = len(a & b)
    return shared / len(a | b) >= _DUPLICATE_MIN_JACCARD and shared / min(len(a), len(b)) >= _DUPLICATE_MIN_OVERLAP


def merge_evidence(keep, extra) -> dict:
    """Hợp bằng chứng của hai mục trùng nhau, bỏ lượt và mã item lặp, giữ thứ tự xuất hiện.

    Args:
        keep: Mục được giữ; bằng chứng của nó đứng trước.
        extra: Mục bị gộp vào; chỉ phần bằng chứng chưa có mới được thêm.

    Returns:
        Dict ``evidence_turn_ids``, ``quotes``, ``item_ids`` mới, dùng để thay vào mục được giữ.
    """

    ids, quotes = list(keep.evidence_turn_ids), list(keep.quotes)
    for turn_id, quote in zip(extra.evidence_turn_ids, extra.quotes):
        if turn_id not in ids:
            ids.append(turn_id)
            quotes.append(quote)
    item_ids = list(keep.item_ids)
    item_ids.extend(segment_id for segment_id in extra.item_ids if segment_id not in item_ids)
    return {"evidence_turn_ids": tuple(ids), "quotes": tuple(quotes), "item_ids": tuple(item_ids)}


def merge_duplicate_assignments(items: Sequence[ActionItemCandidate]) -> list[ActionItemCandidate]:
    """Gộp các việc giao trùng nội dung của cùng bên nhận việc, trong và giữa các chủ đề.

    Đây là cách gộp chỉ theo chữ, dùng khi không có Decisions API để đối chiếu. Khi gộp, bản có hạn chót
    được ưu tiên; cùng có hoặc cùng không có hạn thì lấy câu dài hơn. Mục gộp giữ chủ đề của lần xuất
    hiện đầu.

    Args:
        items: Việc giao đã kiểm chứng, theo thứ tự.

    Returns:
        Danh sách đã gộp, giữ thứ tự xuất hiện đầu tiên.
    """

    merged: list[ActionItemCandidate] = []
    for item in items:
        actor_key = _assignee_group(item)
        drop = content_tokens(item.actor or "")
        for index, kept in enumerate(merged):
            if _assignee_group(kept) != actor_key:
                continue
            if not _is_near_duplicate(kept.text, item.text, drop):
                continue
            prefer_new = (item.deadline_raw and not kept.deadline_raw) or (
                bool(item.deadline_raw) == bool(kept.deadline_raw) and len(item.text) > len(kept.text)
            )
            base, other = (item, kept) if prefer_new else (kept, item)
            merged[index] = replace(
                base,
                segment_id=kept.segment_id,
                **merge_evidence(base, other),
            )
            break
        else:
            merged.append(item)
    return merged


def merge_duplicate_decisions(items: Sequence[DecisionCandidate]) -> list[DecisionCandidate]:
    """Gộp các kết luận trùng nội dung: giữ câu dài hơn và hợp bằng chứng.

    Đây là cách gộp chỉ theo chữ, dùng khi không có Decisions API để đối chiếu. Mục gộp giữ chủ đề của
    lần xuất hiện đầu.

    Args:
        items: Kết luận đã kiểm chứng, theo thứ tự.

    Returns:
        Danh sách đã gộp, giữ thứ tự xuất hiện đầu tiên.
    """

    merged: list[DecisionCandidate] = []
    for item in items:
        for index, kept in enumerate(merged):
            if not _is_near_duplicate(kept.text, item.text):
                continue
            base, other = (item, kept) if len(item.text) > len(kept.text) else (kept, item)
            merged[index] = replace(base, segment_id=kept.segment_id, **merge_evidence(base, other))
            break
        else:
            merged.append(item)
    return merged


__all__ = [
    "merge_evidence",
    "merge_duplicate_assignments",
    "merge_duplicate_decisions",
]
