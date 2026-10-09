"""Tóm tắt results/synthetic.jsonl: regex vs Decisions theo nhãn gold."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def prf(pred: list[bool], gold: list[bool]) -> str:
    tp = sum(p and g for p, g in zip(pred, gold))
    fp = sum(p and not g for p, g in zip(pred, gold))
    fn = sum(g and not p for p, g in zip(pred, gold))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return f"P={precision:.3f} R={recall:.3f} F1={f1:.3f} (tp={tp} fp={fp} fn={fn})"


def ece(probs: list[float], gold: list[bool], bins: int = 10) -> float:
    total = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(probs) if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if idx:
            conf = sum(probs[i] for i in idx) / len(idx)
            acc = sum(gold[i] for i in idx) / len(idx)
            total += len(idx) / len(probs) * abs(conf - acc)
    return total


def main() -> None:
    rows = [json.loads(l) for l in (RESULTS / "synthetic.jsonl").open(encoding="utf-8")]
    gold = [r["gold_commit"] for r in rows]
    print(f"n={len(rows)}  dương={sum(gold)}  âm={len(gold) - sum(gold)}")
    print("regex          ", prf([r["regex_commit"] for r in rows], gold))
    for threshold in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        print(f"decisions p>={threshold}", prf([r["p_commit"] >= threshold for r in rows], gold))
    print(f"ECE(p_commit)={ece([r['p_commit'] for r in rows], gold):.3f}")

    print("\nTỷ lệ coi là 'đã chốt' theo loại lượt (regex | decisions p>=0.5):")
    by_kind: dict[str, list[dict]] = {}
    for r in rows:
        by_kind.setdefault("+".join(r["kinds"]), []).append(r)
    for kind, group in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        rx = sum(r["regex_commit"] for r in group) / len(group)
        dc = sum(r["p_commit"] >= 0.5 for r in group) / len(group)
        print(f"  {kind:35s} n={len(group):4d}  regex={rx:.2f}  decisions={dc:.2f}")

    print("\nPhân bố p_commit theo độ tin cậy (vùng giữa = gửi Verifier):")
    for lo, hi in ((0, 0.2), (0.2, 0.8), (0.8, 1.01)):
        group = [r for r in rows if lo <= r["p_commit"] < hi]
        acc = sum(r["gold_commit"] for r in group) / len(group) if group else 0
        print(f"  [{lo},{hi}) n={len(group):4d}  tỷ lệ gold dương={acc:.2f}")

    secs = sorted(r["seconds"] for r in rows)
    print(f"\nlatency p50={secs[len(secs)//2]:.2f}s p95={secs[int(len(secs)*.95)]:.2f}s")
    print("choice:", Counter(r["choice"] for r in rows).most_common())

    if "--errors" in sys.argv:
        for r in rows:
            if (r["p_commit"] >= 0.5) != r["gold_commit"]:
                print(f"\n[{r['kinds']}] p={r['p_commit']:.2f} regex={r['regex_commit']} {r['key']}\n  {r['speaker']}: {r['text'][:300]}")


if __name__ == "__main__":
    main()
