"""Gói transcript + gold + output thành một file text gọn cho LLM judge đọc.

    python eval/build_judge_packet.py --run NAME [synth_XXX ...]

Ghi ``eval/results/<run>/packets/<id>.md``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
SYNTH_DIR = _REPO_ROOT / "eval" / "synthetic"


def render(output: dict, gold: dict) -> str:
    turns = output["turns"]
    gold_starts = set(gold["boundaries"])
    pred_starts = set(output["_segments"]["boundaries"])
    lines = [f"# {gold['meeting_id']}  tags={gold['tags']}", "", "## Transcript",
             "(`G>` = ranh giới gold bắt đầu tại lượt này, `P>` = ranh giới dự đoán)", ""]
    for i, t in enumerate(turns):
        mark = ("G>" if i in gold_starts else "  ") + ("P>" if i in pred_starts else "  ")
        lines.append(f"{mark} [{i}] {t['turn_id']} {t['speaker']}: {t['text']}")

    lines += ["", "## Gold", "### Chủ đề"]
    for tp in gold["topics"]:
        lines.append(f"- [{tp['turn_range'][0]}–{tp['turn_range'][1]}) {tp['title']} — {tp['summary']}")
    for kind in ("assignments", "decisions", "negatives", "key_points"):
        lines.append(f"### {kind}")
        for g in gold[kind]:
            extra = {k: g[k] for k in ("actor", "deadline", "type", "speaker") if k in g}
            text = g.get("task") or g.get("text") or g.get("point")
            lines.append(f"- {g['id']} (topic {g['topic_index']}) {extra} {text}  ev={g['evidence_turn_ids']}")

    lines += ["", "## Output", "### Chủ đề + Diễn biến họp"]
    for tp in output["topics"]:
        lines.append(f"#### {tp['segment_id']}: {tp['title']}\n_{tp['summary']}_")
        for pt in tp["discussion_points"]:
            lines.append(f"- [{', '.join(pt['speakers'])}] {pt['text']}  ev={pt['evidence_ids']}")
    lines.append("### Giao việc")
    for i, a in enumerate(output["verified_assignments"]):
        lines.append(f"- a{i} ({a['segment_id']}) actor={a['actor']!r} deadline={a.get('deadline')!r}: {a['text']}"
                     f"  ev={a['evidence_ids']}")
    lines.append("### Kết luận")
    for i, d in enumerate(output["verified_decisions"]):
        lines.append(f"- d{i} ({d['segment_id']}) {d['text']}  ev={d['evidence_ids']}")
    if output["failed_topics"]:
        lines.append(f"### failed_topics\n{output['failed_topics']}")
    dropped = [r for r in output["debate_records"] if not r["kept"]]
    if dropped:
        lines.append("### Bị debate loại")
        lines += [f"- ({r['kind']}) {r['candidate_text']}" for r in dropped]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    run_dir = _REPO_ROOT / "eval" / "results" / args.run
    (run_dir / "packets").mkdir(exist_ok=True)
    ids = args.ids or sorted(p.stem for p in (run_dir / "outputs").glob("*.json"))
    for meeting_id in ids:
        output = json.loads((run_dir / "outputs" / f"{meeting_id}.json").read_text())
        gold = json.loads((SYNTH_DIR / "gold" / f"{meeting_id}.json").read_text())
        (run_dir / "packets" / f"{meeting_id}.md").write_text(render(output, gold))


if __name__ == "__main__":
    main()
