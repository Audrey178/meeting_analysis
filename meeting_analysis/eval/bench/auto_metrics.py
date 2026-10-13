"""Phần chấm tự động (không cần judge) của benchmark: ranh giới chủ đề và proxy trích dẫn."""

from __future__ import annotations

import numpy as np

from metrics import evaluate  # experiments/007_dialtreeseg/metrics.py (run.py thêm vào sys.path)

# Bẫy loại nào bị tính là "dính" khi output trích dẫn turn của nó trong danh sách nào.
_TRAP_TARGET = {
    "hedged_proposal": "decisions",
    "superseded_decision": "decisions",
    "rejected_task": "assignments",
    "unassigned_task": "assignments",
}


def segmentation_row(output: dict, gold: dict) -> dict:
    """Pk / WD / F1@2k / F1@5k / dK của ranh giới dự đoán so với gold (theo ký tự).

    Đầu vào: output - schema chung, có ``_segments.boundaries``; gold - file gold của cuộc họp.
    Đầu ra: dict metric kèm ranh giới hai bên.
    """

    item_chars = [len(f"{t['speaker']}: {t['text']}") + 1 for t in output["turns"]]
    char_prefix = np.concatenate([[0], np.cumsum(item_chars)])
    boundaries = output["_segments"]["boundaries"]
    row = evaluate(boundaries, gold["boundaries"], char_prefix)
    row.update({"pred_boundaries": boundaries, "gold_boundaries": gold["boundaries"], "n_turns": len(item_chars)})
    return row


def evidence_overlap(output: dict, gold: dict) -> dict:
    """Proxy rẻ cho output cuối: item gold có được output trích dẫn tới turn của nó không.

    Chỉ dùng để chạy hồi quy nhanh, không thay bảng ghép của judge: trích đúng turn chưa chắc
    đúng nội dung/người nhận, và chạm turn của bẫy chỉ là dấu hiệu (không phải kết luận) có lỗi.

    Đầu vào: output - schema chung; gold - file gold.
    Đầu ra: dict theo loại item: số gold, số bị chạm, id bị chạm; cộng bẫy bị chạm và số item dự đoán.
    """

    def cited(items: list[dict]) -> set[str]:
        return {tid for item in items for tid in item.get("evidence_ids", [])}

    point_turns = {
        tid for topic in output["topics"] for point in topic["discussion_points"] for tid in point["evidence_ids"]
    }
    sets = {
        "assignments": cited(output["verified_assignments"]),
        "decisions": cited(output["verified_decisions"]),
        "key_points": point_turns,
    }
    row: dict = {}
    for kind, turn_set in sets.items():
        hits = [g["id"] for g in gold[kind] if set(g["evidence_turn_ids"]) & turn_set]
        row[kind] = {"gold": len(gold[kind]), "touched": len(hits), "touched_ids": hits}
    row["negatives_touched"] = [
        n["id"] for n in gold["negatives"] if set(n["evidence_turn_ids"]) & sets[_TRAP_TARGET[n["type"]]]
    ]
    row["n_pred"] = {
        "topics": len(output["topics"]),
        "assignments": len(output["verified_assignments"]),
        "decisions": len(output["verified_decisions"]),
        "failed_topics": len(output["failed_topics"]),
    }
    return row


__all__ = ["evidence_overlap", "segmentation_row"]
