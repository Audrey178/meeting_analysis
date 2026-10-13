"""Bảng kết quả benchmark từ judgment đã gộp (``judge_packets.py merge``) và output của các arm.

    python eval/bench/report.py --run bench_v1 [--ref v3] [--split dev|heldout|all]

Ghi ``eval/results/<run>/REPORT.md`` và ``report.json``. Mỗi arm:
    P/R/F1 việc giao và kết luận (micro: cộng đếm trên mọi cuộc họp), độ đúng người nhận/hạn chót trên việc
    giao khớp gold, tỷ lệ dính bẫy, recall ý chính (partial = 0,5), metric ranh giới, chi phí.
Arm có nhiều lần chạy (r1, r2, ...) báo trung bình ± độ lệch chuẩn giữa các lần chạy.
Chênh lệch so với ``--ref`` dùng bootstrap ghép cặp theo cuộc họp (10k lần, 95% CI) trên các cuộc họp hai arm
cùng có judgment; arm nhiều lần chạy thì lấy lần r1.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = _REPO_ROOT / "eval" / "results"
MANIFEST = _REPO_ROOT / "eval" / "synthetic" / "manifest.json"
CORRECT_LABELS = {"ok", "extra_valid"}
SEG_KEYS = ("Pk", "WD", "F1@2k")
# Metric chính và hướng tốt (+1 cao là tốt, -1 thấp là tốt).
MAIN_METRICS = {"F1_A": 1, "F1_D": 1, "P_A": 1, "R_A": 1, "P_D": 1, "R_D": 1, "actor_acc": 1,
                "deadline_acc": 1, "trap_rate": -1, "R_K": 1}


def _credit(value: str) -> float:
    return 1.0 if value.startswith("match") else 0.5 if value.startswith("partial") else 0.0


def meeting_counts(judgment: dict) -> Counter:
    """Các đếm cộng được của một cuộc họp (để tính micro và bootstrap)."""

    # .get: judgment rút gọn của người (M1) chỉ có những quyết định đã điền.
    matching, labels = judgment["matching"], judgment.get("output_labels", {})
    c: Counter = Counter()
    for kind, short in (("assignments", "A"), ("decisions", "D")):
        c[f"gold_{short}"] += len(matching.get(kind, {}))
        c[f"hit_{short}"] += sum(_credit(v) for v in matching.get(kind, {}).values())
        items = labels.get(kind, {}).values()
        c[f"pred_{short}"] += len(items)
        c[f"correct_{short}"] += sum(item["label"] in CORRECT_LABELS for item in items)
    for item in labels.get("assignments", {}).values():
        if item["label"] == "ok":
            for field in ("actor_ok", "deadline_ok"):
                if item.get(field) is not None:
                    c[f"{field}_n"] += 1
                    c[f"{field}_true"] += bool(item[field])
    c["gold_K"] += len(matching.get("key_points", {}))
    c["hit_K"] += sum(_credit(v) for v in matching.get("key_points", {}).values())
    c["traps"] += len(matching.get("negatives", {}))
    c["traps_hit"] += sum(v.startswith("hit") for v in matching.get("negatives", {}).values())
    return c


def metrics_from_counts(c: Counter) -> dict[str, float | None]:
    """Metric micro từ đếm cộng dồn."""

    def ratio(a: str, b: str) -> float | None:
        return c[a] / c[b] if c[b] else None

    out: dict[str, float | None] = {}
    for short in ("A", "D"):
        p, r = ratio(f"correct_{short}", f"pred_{short}"), ratio(f"hit_{short}", f"gold_{short}")
        out[f"P_{short}"], out[f"R_{short}"] = p, r
        out[f"F1_{short}"] = 2 * p * r / (p + r) if p is not None and r is not None and p + r else None
    out["actor_acc"] = ratio("actor_ok_true", "actor_ok_n")
    out["deadline_acc"] = ratio("deadline_ok_true", "deadline_ok_n")
    out["trap_rate"] = ratio("traps_hit", "traps")
    out["R_K"] = ratio("hit_K", "gold_K")
    return out


def load_repeat(repeat_dir: Path, meeting_ids: set[str]) -> dict:
    """Judgment, metric ranh giới và chi phí của một lần chạy, chỉ trên ``meeting_ids``."""

    judgments = {p.stem: json.loads(p.read_text()) for p in sorted((repeat_dir / "judgments").glob("*.json"))
                 if p.stem in meeting_ids}
    seg_path = repeat_dir / "segmentation.json"
    seg = {k: v for k, v in (json.loads(seg_path.read_text()) if seg_path.exists() else {}).items() if k in meeting_ids}
    costs = []
    for out_file in sorted((repeat_dir / "outputs").glob("*.json")):
        if out_file.stem in meeting_ids:
            output = json.loads(out_file.read_text())
            cost = output.get("_cost", {})
            paid = sum(r["calls"] for r in cost.get("roles", []) if r.get("usd") != 0.0)
            costs.append((cost.get("usd_known", 0.0), paid, output["_segments"]["seconds"]))
    return {"counts": {m: meeting_counts(j) for m, j in judgments.items()}, "seg": seg, "costs": costs}


def bootstrap_delta(arm: dict[str, Counter], ref: dict[str, Counter], metric: str,
                    n: int = 10_000, seed: int = 0) -> tuple[float, float, float, int] | None:
    """(Δ, CI thấp, CI cao, số cuộc họp) của ``metric`` arm − ref, bootstrap ghép cặp theo cuộc họp."""

    shared = sorted(set(arm) & set(ref))
    if not shared:
        return None
    rng = np.random.default_rng(seed)

    def value(counts: dict[str, Counter], ids) -> float | None:
        total: Counter = Counter()
        for m in ids:
            total.update(counts[m])
        return metrics_from_counts(total)[metric]

    point_a, point_r = value(arm, shared), value(ref, shared)
    if point_a is None or point_r is None:
        return None
    deltas = []
    for _ in range(n):
        sample = [shared[i] for i in rng.integers(0, len(shared), len(shared))]
        a, r = value(arm, sample), value(ref, sample)
        if a is not None and r is not None:
            deltas.append(a - r)
    low, high = np.percentile(deltas, [2.5, 97.5])
    return point_a - point_r, float(low), float(high), len(shared)


def _fmt(value: float | None, digits: int = 3) -> str:
    return "–" if value is None else f"{value:.{digits}f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--ref", default="v3")
    parser.add_argument("--split", choices=("dev", "heldout", "all"), default="all")
    args = parser.parse_args()
    run_dir = RESULTS_DIR / args.run
    manifest = json.loads(MANIFEST.read_text())
    meeting_ids = {m["meeting_id"] for m in manifest if args.split == "all" or m.get("split", "dev") == args.split}

    arms: dict[str, list[dict]] = {}
    for arm_dir in sorted(p for p in run_dir.iterdir() if p.is_dir() and not p.name.startswith(("_", "judge"))):
        repeats = [load_repeat(r, meeting_ids) for r in sorted(arm_dir.glob("r*"))]
        if any(rep["counts"] for rep in repeats):
            arms[arm_dir.name] = repeats

    rows, report = [], {"split": args.split, "ref": args.ref, "arms": {}}
    for name, repeats in arms.items():
        per_repeat = []
        for rep in repeats:
            total: Counter = Counter()
            for c in rep["counts"].values():
                total.update(c)
            per_repeat.append(metrics_from_counts(total))
        summary = {}
        for key in MAIN_METRICS:
            values = [m[key] for m in per_repeat if m[key] is not None]
            summary[key] = (float(np.mean(values)), float(np.std(values)) if len(values) > 1 else None) if values else (None, None)
        first = repeats[0]
        seg = {k: float(np.mean([r[k] for r in first["seg"].values()])) if first["seg"] else None for k in SEG_KEYS}
        costs = np.array(first["costs"]) if first["costs"] else np.zeros((0, 3))
        cost = {"usd_total": float(costs[:, 0].sum()) if len(costs) else 0.0,
                "paid_calls_per_meeting": float(costs[:, 1].mean()) if len(costs) else 0.0,
                "seconds_per_meeting": float(costs[:, 2].mean()) if len(costs) else 0.0}
        n_meetings = len(first["counts"])
        report["arms"][name] = {"n_meetings": n_meetings, "n_repeats": len(repeats), "metrics": summary,
                                "segmentation": seg, "cost": cost}
        rows.append((name, n_meetings, len(repeats), summary, seg, cost))

    lines = [f"# Kết quả `{args.run}` (split = {args.split})", "",
             "Micro trên các cuộc họp đã chấm; `±` = độ lệch chuẩn giữa các lần chạy. Recall tính partial = 0,5.", "",
             "| Arm | n | lần | F1 giao | P giao | R giao | F1 kết luận | P kết luận | R kết luận | Đúng người | Đúng hạn | Dính bẫy | R ý chính | Pk | $ | Lời gọi trả tiền/họp | Giây/họp |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, n, reps, summary, seg, cost in rows:
        def cell(key: str) -> str:
            mean, std = summary[key]
            return _fmt(mean) + (f" ± {std:.3f}" if std is not None else "")
        lines.append(f"| {name} | {n} | {reps} | " + " | ".join(cell(k) for k in
                     ("F1_A", "P_A", "R_A", "F1_D", "P_D", "R_D", "actor_acc", "deadline_acc", "trap_rate", "R_K"))
                     + f" | {_fmt(seg['Pk'])} | {cost['usd_total']:.3f} | {cost['paid_calls_per_meeting']:.1f}"
                     + f" | {cost['seconds_per_meeting']:.0f} |")

    if args.ref in arms:
        ref_counts = arms[args.ref][0]["counts"]
        lines += ["", f"## Chênh lệch so với `{args.ref}` (bootstrap ghép cặp, 95% CI)", "",
                  "| Arm | n chung | " + " | ".join(f"Δ {k}" for k in MAIN_METRICS) + " |",
                  "|---|---|" + "---|" * len(MAIN_METRICS)]
        report["deltas"] = {}
        for name, repeats in arms.items():
            if name == args.ref:
                continue
            cells, deltas, n_shared = [], {}, 0
            for key, direction in MAIN_METRICS.items():
                result = bootstrap_delta(repeats[0]["counts"], ref_counts, key)
                if result is None:
                    cells.append("–")
                    continue
                delta, low, high, n_shared = result
                significant = low > 0 or high < 0
                better = (delta > 0) == (direction > 0)
                mark = (" ▲" if better else " ▼") if significant else ""
                cells.append(f"{delta:+.3f} [{low:+.3f}, {high:+.3f}]{mark}")
                deltas[key] = {"delta": delta, "ci": [low, high], "significant": significant}
            report["deltas"][name] = deltas
            lines.append(f"| {name} | {n_shared} | " + " | ".join(cells) + " |")
        lines += ["", "▲/▼: CI không chứa 0 và arm tốt hơn/kém hơn `ref` theo hướng của metric (dính bẫy: thấp là tốt)."]

    (run_dir / "REPORT.md").write_text("\n".join(lines) + "\n")
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
