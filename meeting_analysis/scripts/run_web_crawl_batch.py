"""Batch driver: (raw .doc, groundtruth .docx) pairs under
``web_crawl/{downloads,outputs}`` -> legacy transcript JSON ->
``scripts/run_to_TreeSeg.py``, one run per session.

Reuses ``experiments/treeseg_turn_level/gt_parser.py``'s
``parse_turns``/``read_doc_text`` (the parser already validated against all
47 sessions by ``turn_purity.py``) instead of inventing a new ``.doc``
parser.

Usage:
    python scripts/run_web_crawl_batch.py --llm --embed --atoms
    python scripts/run_web_crawl_batch.py --limit 1 --llm --embed --atoms
    python scripts/run_web_crawl_batch.py --dry-run   # only build the JSON, skip the pipeline
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

_MEETING_ANALYSIS = Path(__file__).resolve().parent.parent
_WEB_CRAWL = _MEETING_ANALYSIS.parent / "web_crawl"
_DOWNLOADS = _WEB_CRAWL / "downloads"
_OUTPUTS = _WEB_CRAWL / "outputs"

sys.path.insert(0, str(_MEETING_ANALYSIS / "experiments" / "treeseg_turn_level"))
from gt_parser import parse_turns, read_doc_text  # noqa: E402

_JSON_DIR = _MEETING_ANALYSIS / "inputs" / "web_crawl_testset"
_JSON_DIR.mkdir(parents=True, exist_ok=True)


def find_session_pairs() -> list[tuple[Path, Path]]:
    """Every ``outputs/**/*_groundtruth.docx`` matched to its raw ``.doc``
    in ``downloads/`` at the same relative path -- ``downloads/`` has more
    raw transcripts than ``outputs/`` has groundtruth for; only pairs with
    both sides are used here (same matching as ``turn_purity.py``)."""
    pairs = []
    for gt_path in sorted(_OUTPUTS.rglob("*_groundtruth.docx")):
        rel = gt_path.relative_to(_OUTPUTS)
        raw_name = rel.name.removesuffix("_groundtruth.docx") + ".doc"
        raw_path = _DOWNLOADS / rel.parent / raw_name
        if raw_path.exists():
            pairs.append((raw_path, gt_path))
        else:
            print(f"SKIP (no raw .doc match): {rel}")
    return pairs


def build_transcript_json(raw_path: Path, out_path: Path) -> int:
    """Parse one raw ``.doc`` into the legacy ``{meeting, turns}`` schema
    ``load_transcript`` reads (``src/utils/adapters.py``), write it to
    ``out_path``, return the turn count."""
    turns = parse_turns(read_doc_text(raw_path))
    payload = {
        "meeting": {"session_number": raw_path.stem},
        "turns": [
            {
                "id": f"t{i + 1:04d}",
                "speaker_raw": f"{t.speaker} - {t.role}" if t.role else t.speaker,
                "text": t.text,
            }
            for i, t in enumerate(turns)
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(turns)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N session pairs")
    parser.add_argument("--llm", action="store_true", help="Forwarded to run_to_TreeSeg.py")
    parser.add_argument("--embed", action="store_true", help="Forwarded to run_to_TreeSeg.py")
    parser.add_argument(
        "--atoms",
        action="store_true",
        help="Forwarded to run_to_TreeSeg.py -- run TreeSeg over stage 4 atoms instead of raw turns",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only build the transcript JSON, don't run the pipeline")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    pairs = find_session_pairs()
    if args.limit:
        pairs = pairs[: args.limit]
    print(f"{len(pairs)} session(s) to process.\n")

    ok: list[str] = []
    failed: list[tuple[str, str]] = []
    for i, (raw_path, gt_path) in enumerate(pairs, 1):
        rel = gt_path.relative_to(_OUTPUTS)
        stem = rel.name.removesuffix("_groundtruth.docx")
        json_path = _JSON_DIR / rel.parent / f"{stem}.json"
        out_path = _OUTPUTS / rel.parent / f"{stem}_treeseg.json"

        print(f"[{i}/{len(pairs)}] {rel.parent / stem}")
        try:
            n_turns = build_transcript_json(raw_path, json_path)
            print(f"   parsed {n_turns} turns -> {json_path}")
        except Exception as exc:  # noqa: BLE001 -- report and keep going
            print(f"   FAILED (parse): {exc!r}")
            failed.append((str(rel), f"parse: {exc!r}"))
            continue

        if args.dry_run:
            continue

        cmd = [sys.executable, "scripts/run_to_TreeSeg.py", "-i", str(json_path), "-o", str(out_path)]
        if args.llm:
            cmd.append("--llm")
        if args.embed:
            cmd.append("--embed")
        if args.atoms:
            cmd.append("--atoms")

        t0 = time.time()
        result = subprocess.run(cmd, cwd=str(_MEETING_ANALYSIS), capture_output=True, text=True)
        dt = time.time() - t0
        if result.returncode == 0:
            print(f"   OK ({dt:.1f}s) -> {out_path}")
            ok.append(str(rel))
        else:
            print(f"   FAILED (pipeline, {dt:.1f}s), rc={result.returncode}")
            print("   ---- stderr tail ----")
            print("\n".join(result.stderr.splitlines()[-20:]))
            failed.append((str(rel), result.stderr.splitlines()[-1] if result.stderr else "unknown"))

    print("\n==== SUMMARY ====")
    print(f"OK: {len(ok)}  FAILED: {len(failed)}  TOTAL: {len(pairs)}")
    if failed:
        print("Failed sessions:")
        for name, err in failed:
            print(f"  - {name}: {err}")


if __name__ == "__main__":
    main()
