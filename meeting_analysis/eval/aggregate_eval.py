"""Gộp metric ranh giới, proxy trích dẫn và điểm Likert của judge thành bảng tổng.

    python eval/aggregate_eval.py --run NAME

Đọc ``eval/results/<run>/{segmentation,evidence_overlap}.json`` và ``judgments/*.json``,
ghi ``summary.json`` và in bảng.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
SEG_KEYS = ["Pk", "WD", "F1@2k", "F1@5k", "dK"]
LIKERT_KEYS = ["S1", "S2", "S3", "S4", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8"]


def match_recall(matching: dict[str, str]) -> float | None:
    """Recall với match = 1, partial = 0.5."""

    if not matching:
        return None
    score = sum(1.0 if v.startswith("match") else 0.5 if v.startswith("partial") else 0.0 for v in matching.values())
    return score / len(matching)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    run_dir = _REPO_ROOT / "eval" / "results" / args.run
    seg = json.loads((run_dir / "segmentation.json").read_text())
    judgments = {p.stem: json.loads(p.read_text()) for p in sorted((run_dir / "judgments").glob("*.json"))}
    manifest = {m["meeting_id"]: m for m in json.loads((_REPO_ROOT / "eval/synthetic/manifest.json").read_text())}

    rows = {}
    for mid in sorted(seg):
        row = {k: seg[mid][k] for k in SEG_KEYS}
        row["bucket"] = manifest.get(mid, {}).get("length_bucket")
        if mid in judgments:
            j = judgments[mid]
            row.update({k: j["scores"][k]["score"] for k in LIKERT_KEYS})
            for kind in ("assignments", "decisions", "key_points"):
                row[f"recall_{kind}"] = match_recall(j["matching"][kind])
            negs = j["matching"]["negatives"]
            row["traps_hit"] = sum(not v.startswith("avoided") for v in negs.values())
            row["traps_total"] = len(negs)
        rows[mid] = row

    def mean(key: str) -> float | None:
        vals = [r[key] for r in rows.values() if r.get(key) is not None]
        return float(np.mean(vals)) if vals else None

    cols = SEG_KEYS + LIKERT_KEYS + ["recall_assignments", "recall_decisions", "recall_key_points"]
    summary = {"per_meeting": rows, "mean": {k: mean(k) for k in cols},
               "traps": [sum(r.get("traps_hit", 0) for r in rows.values()), sum(r.get("traps_total", 0) for r in rows.values())]}
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))

    short = {"recall_assignments": "R_A", "recall_decisions": "R_D", "recall_key_points": "R_K"}
    print(f"{'meeting':<11}{'b':>2}" + "".join(f"{short.get(k, k):>7}" for k in cols))
    for mid, r in rows.items():
        cells = "".join(f"{r[k]:>7.2f}" if isinstance(r.get(k), float) else f"{r.get(k, '-')!s:>7}" for k in cols)
        print(f"{mid:<11}{r['bucket'] or '':>2}{cells}")
    print(f"{'MEAN':<13}" + "".join(f"{v:>7.2f}" if v is not None else f"{'-':>7}" for v in summary["mean"].values()))
    print(f"traps hit: {summary['traps'][0]}/{summary['traps'][1]}")


if __name__ == "__main__":
    main()
