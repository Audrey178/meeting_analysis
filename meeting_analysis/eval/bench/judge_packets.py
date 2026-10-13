"""Packet chấm MÙ cho judge: đóng gói, kiểm judgment, gộp judgment về từng arm.

    python eval/bench/judge_packets.py build    --run bench_v1 --arms v3 b0_single_prompt ... [--likert-arms v3 ...]
    python eval/bench/judge_packets.py validate --run bench_v1
    python eval/bench/judge_packets.py merge    --run bench_v1

Ghi trong ``eval/results/<run>/judge/``:
    key.json                    packet_id -> {arm, repeat, meeting_id, likert}; KHÔNG đưa cho judge
    queue.json                  packet chưa chấm, thứ tự xáo ngẫu nhiên (seed lưu trong key.json)
    packets/<packet_id>.md      transcript + gold + output, không tên arm
    judgments/<packet_id>.json  judge ghi theo ``JUDGE_PROTOCOL.md``
``merge`` chép judgment về ``<arm>/r<k>/judgments/<meeting_id>.json`` để ``eval/aggregate_eval.py`` và
``report.py`` đọc theo arm.

Packet bỏ hai phần của ``build_judge_packet.render`` chỉ v3 mới có (việc bị Verifier loại, chủ đề lỗi), để
judge không nhận ra kiến trúc; output vẫn có thể lộ phong cách, nên mù chỉ là giảm thiên lệch, không triệt tiêu.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import secrets
import sys
from pathlib import Path

_BENCH_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BENCH_DIR.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "eval"))

from build_judge_packet import render  # noqa: E402  (eval/build_judge_packet.py)

SYNTH_DIR = _REPO_ROOT / "eval" / "synthetic"
RESULTS_DIR = _REPO_ROOT / "eval" / "results"
_ARCHITECTURE_SECTIONS = ("\n### failed_topics", "\n### Bị debate loại")
CORRECT_LABELS = {"ok", "extra_valid"}
OUTPUT_LABELS = CORRECT_LABELS | {"duplicate", "trap", "not_assignment", "not_decision", "hallucinated"}
LIKERT_KEYS = ("S1", "S2", "S3", "S4", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")


def render_blind(output: dict, gold: dict, likert: bool) -> str:
    """Packet không lộ arm: bỏ phần chỉ v3 có, thêm dòng yêu cầu Likert."""

    text = render(output, gold)
    cut = min((text.find(marker) for marker in _ARCHITECTURE_SECTIONS if marker in text), default=len(text))
    header = f"LIKERT: {'có' if likert else 'không'}  (giao thức: eval/bench/JUDGE_PROTOCOL.md)\n\n"
    return header + text[:cut].rstrip() + "\n"


def _load_key(judge_dir: Path) -> dict:
    path = judge_dir / "key.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"salt": secrets.token_hex(8), "seed": secrets.randbelow(2**31), "packets": {}}


def build(run_dir: Path, arms: list[str], likert_arms: set[str], refresh: bool = False) -> None:
    """Thêm packet cho mọi output của ``arms`` chưa có packet; viết lại hàng đợi chưa chấm.

    ``refresh`` viết lại cả packet đã có (cùng packet_id) khi cách dựng packet đổi; judgment cũ của chúng
    phải được chuyển đi trước, vì chúng chấm trên nội dung packet cũ.
    """

    judge_dir = run_dir / "judge"
    (judge_dir / "packets").mkdir(parents=True, exist_ok=True)
    (judge_dir / "judgments").mkdir(exist_ok=True)
    key = _load_key(judge_dir)
    added = 0
    for arm in arms:
        for out_file in sorted((run_dir / arm).glob("r*/outputs/*.json")):
            repeat, meeting_id = out_file.parent.parent.name, out_file.stem
            packet_id = hashlib.sha256(f"{key['salt']}:{arm}:{repeat}:{meeting_id}".encode()).hexdigest()[:10]
            if packet_id in key["packets"] and not refresh:
                continue
            output = json.loads(out_file.read_text())
            gold = json.loads((SYNTH_DIR / "gold" / f"{meeting_id}.json").read_text())
            likert = arm in likert_arms
            (judge_dir / "packets" / f"{packet_id}.md").write_text(render_blind(output, gold, likert))
            key["packets"][packet_id] = {"arm": arm, "repeat": repeat, "meeting_id": meeting_id, "likert": likert}
            added += 1
    (judge_dir / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1))
    pending = sorted(pid for pid in key["packets"] if not (judge_dir / "judgments" / f"{pid}.json").exists())
    random.Random(key["seed"]).shuffle(pending)
    (judge_dir / "queue.json").write_text(json.dumps(pending, indent=1))
    print(f"thêm {added} packet; {len(pending)} packet chưa chấm (queue.json)")


def check_judgment(judgment: dict, gold: dict, output: dict, likert: bool) -> list[str]:
    """Các lỗi định dạng/thiếu của một judgment so với gold và output của packet (rỗng = hợp lệ)."""

    problems = []
    matching, labels = judgment.get("matching", {}), judgment.get("output_labels", {})
    for kind in ("assignments", "decisions", "key_points", "negatives"):
        missing = {g["id"] for g in gold[kind]} - set(matching.get(kind, {}))
        if missing:
            problems.append(f"matching.{kind} thiếu {sorted(missing)}")
    for kind, prefix, items in (("assignments", "a", output["verified_assignments"]),
                                ("decisions", "d", output["verified_decisions"])):
        given = labels.get(kind, {})
        missing = {f"{prefix}{i}" for i in range(len(items))} - set(given)
        if missing:
            problems.append(f"output_labels.{kind} thiếu {sorted(missing)}")
        bad = {k: v.get("label") for k, v in given.items() if v.get("label") not in OUTPUT_LABELS}
        if bad:
            problems.append(f"output_labels.{kind} nhãn lạ {bad}")
    if likert and set(judgment.get("scores", {})) != set(LIKERT_KEYS):
        problems.append("thiếu/thừa điểm Likert")
    return problems


def _packet_inputs(run_dir: Path, info: dict) -> tuple[dict, dict]:
    output = json.loads((run_dir / info["arm"] / info["repeat"] / "outputs" / f"{info['meeting_id']}.json").read_text())
    gold = json.loads((SYNTH_DIR / "gold" / f"{info['meeting_id']}.json").read_text())
    return output, gold


def validate(run_dir: Path) -> bool:
    """In judgment sai định dạng; True nếu mọi judgment đã có đều hợp lệ."""

    key = _load_key(run_dir / "judge")
    ok = True
    for path in sorted((run_dir / "judge" / "judgments").glob("*.json")):
        info = key["packets"][path.stem]
        output, gold = _packet_inputs(run_dir, info)
        problems = check_judgment(json.loads(path.read_text()), gold, output, info["likert"])
        if problems:
            ok = False
            print(f"{path.stem}: " + "; ".join(problems))
    return ok


def merge(run_dir: Path) -> None:
    """Chép judgment hợp lệ về ``<arm>/r<k>/judgments/<meeting_id>.json``."""

    key = _load_key(run_dir / "judge")
    merged = 0
    for path in sorted((run_dir / "judge" / "judgments").glob("*.json")):
        info = key["packets"][path.stem]
        output, gold = _packet_inputs(run_dir, info)
        judgment = json.loads(path.read_text())
        if check_judgment(judgment, gold, output, info["likert"]):
            continue
        target = run_dir / info["arm"] / info["repeat"] / "judgments" / f"{info['meeting_id']}.json"
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps({**judgment, "meeting_id": info["meeting_id"]}, ensure_ascii=False, indent=1))
        merged += 1
    print(f"đã gộp {merged} judgment hợp lệ")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "validate", "merge"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--arms", nargs="*", default=[])
    parser.add_argument("--likert-arms", nargs="*", default=["v3", "b0_single_prompt", "v3_oracle"])
    parser.add_argument("--refresh", action="store_true", help="viết lại cả packet đã có")
    args = parser.parse_args()
    run_dir = RESULTS_DIR / args.run
    if args.command == "build":
        build(run_dir, args.arms, set(args.likert_arms), args.refresh)
    elif args.command == "validate":
        sys.exit(0 if validate(run_dir) else 1)
    else:
        merge(run_dir)


if __name__ == "__main__":
    main()
