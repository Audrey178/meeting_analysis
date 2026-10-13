"""Độ khớp giữa hai lần chấm của cùng các packet (judge-judge, hoặc judge-người ở M1).

    python eval/bench/judge_agreement.py --run bench_v1 --a judge/judgments --b judge/m1_rejudge

So từng quyết định rời rạc chung của hai bên:
    - phía gold: ``match`` / ``partial`` / ``miss`` (negatives: ``avoided`` / ``hit``);
    - phía output: nhãn item gộp về đúng / sai cho precision (``ok``/``extra_valid`` là đúng).
Báo tỷ lệ khớp và Cohen's kappa cho từng nhóm, cộng chênh lệch P/R việc giao và kết luận theo packet.
Tiêu chí M1 (chốt trong plan): kappa >= 0,7 cho judge-người, tự khớp >= 0,9 cho judge-judge.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from report import CORRECT_LABELS, meeting_counts, metrics_from_counts

_REPO_ROOT = Path(__file__).resolve().parents[2]


def gold_side(value: str) -> str:
    """Quyết định phía gold gộp về một từ khoá."""

    for keyword in ("match", "partial", "miss", "avoided", "hit"):
        if value.startswith(keyword):
            return keyword
    return "?"


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa của các cặp nhãn; None nếu không xác định (không cặp nào, hoặc kỳ vọng khớp = 1)."""

    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[k] * right[k] for k in left) / (n * n)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def decision_pairs(a: dict, b: dict) -> dict[str, list[tuple[str, str]]]:
    """Các cặp quyết định chung của hai judgment cùng packet, theo nhóm."""

    groups: dict[str, list[tuple[str, str]]] = {}
    for kind in ("assignments", "decisions", "key_points", "negatives"):
        left, right = a["matching"].get(kind, {}), b["matching"].get(kind, {})
        groups[f"gold.{kind}"] = [(gold_side(left[k]), gold_side(right[k])) for k in sorted(set(left) & set(right))]
    for kind in ("assignments", "decisions"):
        left, right = a.get("output_labels", {}).get(kind, {}), b.get("output_labels", {}).get(kind, {})
        groups[f"output.{kind}"] = [
            (str(left[k]["label"] in CORRECT_LABELS), str(right[k]["label"] in CORRECT_LABELS))
            for k in sorted(set(left) & set(right))
        ]
    return groups


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--a", required=True, help="thư mục judgment thứ nhất (tương đối với thư mục run)")
    parser.add_argument("--b", required=True, help="thư mục judgment thứ hai")
    args = parser.parse_args()
    run_dir = _REPO_ROOT / "eval" / "results" / args.run
    dir_a, dir_b = run_dir / args.a, run_dir / args.b
    shared = sorted({p.stem for p in dir_a.glob("*.json")} & {p.stem for p in dir_b.glob("*.json")})
    print(f"{len(shared)} packet chấm cả hai lần: {shared}\n")

    pooled: dict[str, list[tuple[str, str]]] = {}
    print(f"{'packet':<12}{'ΔP_A':>8}{'ΔR_A':>8}{'ΔP_D':>8}{'ΔR_D':>8}")
    for packet_id in shared:
        a, b = (json.loads((d / f"{packet_id}.json").read_text()) for d in (dir_a, dir_b))
        for group, pairs in decision_pairs(a, b).items():
            pooled.setdefault(group, []).extend(pairs)
        ma, mb = metrics_from_counts(meeting_counts(a)), metrics_from_counts(meeting_counts(b))
        diffs = [(ma[k] - mb[k]) if ma[k] is not None and mb[k] is not None else None for k in ("P_A", "R_A", "P_D", "R_D")]
        print(f"{packet_id:<12}" + "".join(f"{d:>+8.3f}" if d is not None else f"{'–':>8}" for d in diffs))

    print(f"\n{'nhóm':<22}{'n':>5}{'khớp':>8}{'kappa':>8}")
    all_pairs = []
    for group, pairs in pooled.items():
        all_pairs.extend(pairs)
        agree = sum(x == y for x, y in pairs) / len(pairs) if pairs else None
        kappa = cohen_kappa(pairs)
        print(f"{group:<22}{len(pairs):>5}{agree if agree is None else round(agree, 3):>8}"
              f"{'–' if kappa is None else round(kappa, 3):>8}")
    agree = sum(x == y for x, y in all_pairs) / len(all_pairs) if all_pairs else 0.0
    print(f"{'TỔNG':<22}{len(all_pairs):>5}{round(agree, 3):>8}{round(cohen_kappa(all_pairs) or 0.0, 3):>8}")


if __name__ == "__main__":
    main()
