"""Phiếu gán nhãn của người cho M1 (đo judge khớp người), xuất ra CSV và đọc lại thành judgment.

    python eval/bench/m1_human_sheet.py export --run bench_v1 [--n 100] [--seed 0]
    python eval/bench/m1_human_sheet.py import --run bench_v1
    python eval/bench/judge_agreement.py --run bench_v1 --a judge/m1_judgeA --b judge/m1_human

``export`` lấy ngẫu nhiên ``n`` quyết định của judge A (``judge/m1_judgeA``) trên các packet M1 (``judge/m1_packets.json``) và ghi
``judge/m1_human.csv``: mỗi dòng có nội dung gold/output, kết luận của judge và cột ``human`` để trống.
Người điền ``human`` (đọc transcript trong packet nếu cần):
    dòng ``gold.*``      : match | partial | miss          (negatives: avoided | hit)
    dòng ``output.*``    : dung | sai                       (item output có đúng là việc giao/kết luận thật không)
``import`` đọc các dòng đã điền thành ``judge/m1_human/<packet_id>.json`` (chỉ gồm quyết định đã điền), để
``judge_agreement.py`` so với judge trên đúng những quyết định đó.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = _REPO_ROOT / "eval" / "results"
SYNTH_DIR = _REPO_ROOT / "eval" / "synthetic"
FIELDS = ["packet_id", "group", "item_id", "gold_text", "output_text", "judge", "human", "note"]


def _gold_texts(gold: dict) -> dict[str, str]:
    texts = {}
    for kind in ("assignments", "decisions", "key_points", "negatives"):
        for g in gold[kind]:
            extra = f"[{g['actor']}] " if g.get("actor") else ""
            texts[g["id"]] = extra + (g.get("task") or g.get("text") or g.get("point") or "")
    return texts


def _output_texts(output: dict) -> dict[str, str]:
    texts = {f"a{i}": f"[{a['actor']}] {a['text']}" for i, a in enumerate(output["verified_assignments"])}
    texts.update({f"d{i}": d["text"] for i, d in enumerate(output["verified_decisions"])})
    return texts


def export(run_dir: Path, n: int, seed: int) -> None:
    """Ghi ``judge/m1_human.csv`` với ``n`` quyết định ngẫu nhiên của judge trên các packet M1."""

    judge_dir = run_dir / "judge"
    key = json.loads((judge_dir / "key.json").read_text())["packets"]
    rows = []
    for packet_id in json.loads((judge_dir / "m1_packets.json").read_text()):
        info = key[packet_id]
        judgment = json.loads((judge_dir / "m1_judgeA" / f"{packet_id}.json").read_text())
        output = json.loads((run_dir / info["arm"] / info["repeat"] / "outputs" / f"{info['meeting_id']}.json").read_text())
        gold_texts = _gold_texts(json.loads((SYNTH_DIR / "gold" / f"{info['meeting_id']}.json").read_text()))
        out_texts = _output_texts(output)
        for kind, decisions in judgment["matching"].items():
            for gold_id, verdict in decisions.items():
                ref = re.search(r"\b([ad]\d+)\b", verdict)
                rows.append({"packet_id": packet_id, "group": f"gold.{kind}", "item_id": gold_id,
                             "gold_text": gold_texts.get(gold_id, ""),
                             "output_text": out_texts.get(ref.group(1), "") if ref else "",
                             "judge": verdict, "human": "", "note": ""})
        for kind, labels in judgment.get("output_labels", {}).items():
            for item_id, label in labels.items():
                rows.append({"packet_id": packet_id, "group": f"output.{kind}", "item_id": item_id, "gold_text": "",
                             "output_text": out_texts.get(item_id, ""), "judge": f"{label['label']} {label.get('note', '')}".strip(),
                             "human": "", "note": ""})
    random.Random(seed).shuffle(rows)
    sample = sorted(rows[:n], key=lambda r: (r["packet_id"], r["group"], r["item_id"]))
    path = judge_dir / "m1_human.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig để Excel đọc đúng tiếng Việt
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sample)
    print(f"ghi {len(sample)}/{len(rows)} quyết định vào {path}")


def import_sheet(run_dir: Path) -> None:
    """Đọc dòng đã điền ``human`` thành judgment rút gọn ``judge/m1_human/<packet_id>.json``."""

    judge_dir = run_dir / "judge"
    with (judge_dir / "m1_human.csv").open(encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["human"].strip()]
    judgments: dict[str, dict] = {}
    for row in rows:
        j = judgments.setdefault(row["packet_id"], {"judge": "human", "matching": {}, "output_labels": {}})
        side, kind = row["group"].split(".", 1)
        value = row["human"].strip().lower()
        if side == "gold":
            j["matching"].setdefault(kind, {})[row["item_id"]] = value
        else:
            label = "ok" if value in ("dung", "đúng", "ok") else "hallucinated"
            j["output_labels"].setdefault(kind, {})[row["item_id"]] = {"label": label}
    out_dir = judge_dir / "m1_human"
    out_dir.mkdir(exist_ok=True)
    for packet_id, judgment in judgments.items():
        (out_dir / f"{packet_id}.json").write_text(json.dumps(judgment, ensure_ascii=False, indent=1))
    print(f"đọc {len(rows)} dòng đã điền của {len(judgments)} packet vào {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("export", "import"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    run_dir = RESULTS_DIR / args.run
    if args.command == "export":
        export(run_dir, args.n, args.seed)
    else:
        import_sheet(run_dir)


if __name__ == "__main__":
    main()
