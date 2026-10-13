"""Chạy pipeline ``be/`` trên bộ test tổng hợp và chấm phần tự động.

    python eval/run_pipeline_eval.py [--run NAME] [synth_XXX ...]

Ghi vào ``eval/results/<run>/``:
    outputs/<id>.json     output API + ``_segments`` (ranh giới dự đoán, chỉ số lượt)
    segmentation.json     Pk / WD / F1@2k / F1@5k / K / dK theo metric của 007
    evidence_overlap.json proxy tự động cho output cuối: gold item được coi là "chạm" nếu
                          có item output cùng chủ đề trích dẫn ít nhất một turn gold
Phần chấm Likert do LLM judge làm riêng trên ``outputs/``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BE_DIR = _REPO_ROOT / "be"
for _dir in (_BE_DIR, _REPO_ROOT, _REPO_ROOT / "experiments" / "007_dialtreeseg"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT.parent / ".env")
load_dotenv(_REPO_ROOT / ".env")

from metrics import evaluate  # noqa: E402  (experiments/007_dialtreeseg/metrics.py)
from services import pipeline  # noqa: E402
from services.dependencies import (  # noqa: E402
    build_embedding_adapter,
    build_topic_segmenter,
    get_downstream_llm_adapters,
    get_topic_label_adapter,
)

SYNTH_DIR = _REPO_ROOT / "eval" / "synthetic"


def run_one(meeting_id: str, components: dict) -> tuple[dict, list[int], list[int]]:
    """Chạy pipeline cho một transcript, trả (output, ranh giới dự đoán, item_chars)."""

    payload = json.loads((SYNTH_DIR / "transcripts" / f"{meeting_id}.json").read_text())
    captured: dict = {}
    original_label_topics = pipeline.label_topics

    def capturing_label_topics(segments, **kwargs):
        captured["segments"] = list(segments)
        return original_label_topics(segments, **kwargs)

    pipeline.label_topics = capturing_label_topics
    try:
        output = pipeline.run_meeting_analysis_pipeline(
            payload,
            embedding_adapter=components["embedding"],
            topic_label_adapter=get_topic_label_adapter(),
            downstream_llm_adapters=get_downstream_llm_adapters(),
            topic_segmenter=components["segmenter"],
        )
    finally:
        pipeline.label_topics = original_label_topics

    segments = captured["segments"]
    boundaries = [int(seg.start_ms) for seg in segments[1:]]
    item_chars = [len(f"{t['speaker']}: {t['text']}") + 1 for t in output["turns"]]
    return output, boundaries, item_chars


def evidence_overlap(output: dict, gold: dict, pred_boundaries: list[int]) -> dict:
    """Proxy tự động: gold item có được output trích dẫn tới turn của nó không."""

    def cited(items: list[dict]) -> set[str]:
        return {tid for item in items for tid in item.get("evidence_ids", [])}

    point_turns = {tid for topic in output["topics"] for pt in topic["discussion_points"] for tid in pt["evidence_ids"]}
    sets = {
        "assignments": cited(output["verified_assignments"]),
        "decisions": cited(output["verified_decisions"]),
        "key_points": point_turns,
    }
    row: dict = {}
    for kind, turn_set in sets.items():
        gold_items = gold[kind]
        hits = [g["id"] for g in gold_items if set(g["evidence_turn_ids"]) & turn_set]
        row[kind] = {"gold": len(gold_items), "touched": len(hits), "touched_ids": hits}
    # Bẫy: chạm turn bẫy trong danh sách tương ứng là dấu hiệu (không phải kết luận) có lỗi.
    trap_target = {"hedged_proposal": "decisions", "superseded_decision": "decisions",
                   "rejected_task": "assignments", "unassigned_task": "assignments"}
    row["negatives_touched"] = [
        n["id"] for n in gold["negatives"] if set(n["evidence_turn_ids"]) & sets[trap_target[n["type"]]]
    ]
    row["n_pred"] = {
        "topics": len(output["topics"]),
        "assignments": len(output["verified_assignments"]),
        "decisions": len(output["verified_decisions"]),
        "failed_topics": len(output["failed_topics"]),
    }
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--run", default=time.strftime("run_%Y%m%d_%H%M"))
    args = parser.parse_args()

    ids = args.ids or sorted(p.stem for p in (SYNTH_DIR / "gold").glob("*.json"))
    out_dir = _REPO_ROOT / "eval" / "results" / args.run
    (out_dir / "outputs").mkdir(parents=True, exist_ok=True)

    components = {"embedding": build_embedding_adapter(), "segmenter": build_topic_segmenter()}
    seg_path, ev_path = out_dir / "segmentation.json", out_dir / "evidence_overlap.json"
    seg_rows = json.loads(seg_path.read_text()) if seg_path.exists() else {}
    ev_rows = json.loads(ev_path.read_text()) if ev_path.exists() else {}

    for meeting_id in ids:
        out_file = out_dir / "outputs" / f"{meeting_id}.json"
        gold = json.loads((SYNTH_DIR / "gold" / f"{meeting_id}.json").read_text())
        if out_file.exists():
            output = json.loads(out_file.read_text())
            boundaries = output["_segments"]["boundaries"]
            item_chars = [len(f"{t['speaker']}: {t['text']}") + 1 for t in output["turns"]]
            print(f"[{meeting_id}] dùng lại output có sẵn", flush=True)
        else:
            started = time.time()
            output, boundaries, item_chars = run_one(meeting_id, components)
            output["_segments"] = {"boundaries": boundaries, "seconds": round(time.time() - started, 1)}
            out_file.write_text(json.dumps(output, ensure_ascii=False, indent=1))
            print(f"[{meeting_id}] xong sau {output['_segments']['seconds']}s", flush=True)

        char_prefix = np.concatenate([[0], np.cumsum(item_chars)])
        row = evaluate(boundaries, gold["boundaries"], char_prefix)
        row.update({"pred_boundaries": boundaries, "gold_boundaries": gold["boundaries"], "n_turns": len(item_chars)})
        seg_rows[meeting_id] = row
        ev_rows[meeting_id] = evidence_overlap(output, gold, boundaries)
        seg_path.write_text(json.dumps(seg_rows, ensure_ascii=False, indent=1))
        ev_path.write_text(json.dumps(ev_rows, ensure_ascii=False, indent=1))

    keys = ["Pk", "WD", "F1@2k", "F1@5k", "dK"]
    print(f"{'meeting':<11}" + "".join(f"{k:>8}" for k in keys) + "   pred / gold")
    for mid, r in seg_rows.items():
        print(f"{mid:<11}" + "".join(f"{r[k]:>8.3f}" for k in keys) + f"   {r['pred_boundaries']} / {r['gold_boundaries']}")
    print(f"{'MEAN':<11}" + "".join(f"{np.mean([r[k] for r in seg_rows.values()]):>8.3f}" for k in keys))


if __name__ == "__main__":
    main()
