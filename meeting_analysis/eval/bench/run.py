"""Chạy một arm của benchmark trên bộ test tổng hợp và chấm phần tự động.

    python eval/bench/run.py --run bench_v1 --arm v3 --budget-usd 2.38 [--repeat 1]
                             [--split dev|heldout|all] [synth_XXX ...]

Ghi vào ``eval/results/<run>/``:
    _shared/<segmenter>/<id>.json      ranh giới + nhãn chủ đề, tính MỘT lần cho mỗi bộ cắt; mọi arm
                                       cùng bộ cắt dùng lại, nên các arm chỉ khác nhau ở thành phần
                                       đang thử (và nhiễu của bộ gán nhãn không lẫn vào)
    <arm>/r<k>/manifest.json           git sha, cấu hình arm, V3Config, model, fingerprint mã nguồn
    <arm>/r<k>/outputs/<id>.json       output theo schema chung (``normalize.py``) + ``_segments`` + ``_cost``
    <arm>/r<k>/segmentation.json       Pk / WD / F1@2k / F1@5k / dK
    <arm>/r<k>/evidence_overlap.json   proxy trích dẫn
và cộng chi phí từng cuộc họp vào ``eval/results/spend_ledger.jsonl``, dùng chung mọi run để chặn
tổng ngân sách OpenAI của cả nghiên cứu (``--budget-usd``).

Arm định nghĩa trong ``arms.json``; khoá thiếu lấy theo ``DEFAULT_ARM`` (= production). Gọi thẳng
``MeetingAnalyzerV3``, không qua cache của API.

Chấm judge: ``eval/build_judge_packet.py --run <run>/<arm>/r<k>`` rồi ``eval/aggregate_eval.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, replace
from pathlib import Path

_BENCH_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BENCH_DIR.parent.parent
# treeseg_turn_level: gói ``experiments.treeseg_turn_level`` import ``treeseg`` như module gốc
# (``services/dependencies.py`` cũng thêm thư mục này).
_EXPERIMENTS = _REPO_ROOT / "experiments"
for _dir in (_REPO_ROOT / "be", _REPO_ROOT, _EXPERIMENTS / "treeseg_turn_level", _EXPERIMENTS / "007_dialtreeseg", _BENCH_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT.parent / ".env")
load_dotenv(_REPO_ROOT / ".env")

import numpy as np  # noqa: E402

from auto_metrics import evidence_overlap, segmentation_row  # noqa: E402
from baseline_single_prompt import run_single_prompt  # noqa: E402
from experiments.treeseg_turn_level import boundaries_to_topic_segments  # noqa: E402
from normalize import report_to_eval_output, segment_boundaries  # noqa: E402
from services.analysis_cache import fingerprint_pipeline  # noqa: E402
from services.pipeline_v3 import (  # noqa: E402
    _FINGERPRINT_ENV,
    _FINGERPRINT_SOURCES,
    _build_decisions_client,
    _build_progress_judge,
    _build_turn_judge,
    _build_verifier_llm,
    build_v3_config_from_env,
)
from services.segmentation import build_meeting_turns, load_pipeline_config, segment_meeting  # noqa: E402
from src.agentic_v3 import MeetingAnalyzerV3  # noqa: E402
from src.stages.stage07_topic_labeling import StructuredLLMTopicLabeler  # noqa: E402
from src.utils.contracts import TopicLabel  # noqa: E402
from src.utils.openai_adapters import OpenAIChatJSONAdapter  # noqa: E402
from usage import RecordingClient, UsageLedger, record_adapter_calls  # noqa: E402

SYNTH_DIR = _REPO_ROOT / "eval" / "synthetic"
RESULTS_DIR = _REPO_ROOT / "eval" / "results"
SPEND_LEDGER = RESULTS_DIR / "spend_ledger.jsonl"

DEFAULT_ARM = {
    "segmenter": "dialstart",  # dialstart | treeseg | oracle (ranh giới gold) | none (một chủ đề)
    "config": {},  # ghi đè trường của V3Config (lấy từ biến môi trường V3_*)
    "turn_judge": True,  # Decisions API cho evidence-check và kiểm tiến độ
    "verifier": "separate",  # separate (VERIFIER_MODEL_NAME) | main (model chính)
    "baseline": None,  # "single_prompt" = B0 (baseline_single_prompt.py), bỏ qua mọi khoá trên
}


def load_arm(name: str) -> dict:
    """Cấu hình đầy đủ của một arm (``arms.json`` đè lên ``DEFAULT_ARM``).

    Lỗi: KeyError nếu arm không có trong ``arms.json``.
    """

    arms = json.loads((_BENCH_DIR / "arms.json").read_text())
    if name not in arms:
        raise KeyError(f"arm {name!r} không có trong arms.json (có: {sorted(arms)})")
    return {**DEFAULT_ARM, **arms[name]}


def build_analyzer(arm: dict, ledger: UsageLedger) -> MeetingAnalyzerV3:
    """Dựng analyzer v3 như ``build_analyzer_v3`` của production, khác ở hai điểm: mỗi vai trò
    một adapter riêng có ghi lời gọi vào ``ledger``, và các thành phần bật/tắt theo ``arm``.

    Đầu vào: arm - cấu hình arm; ledger - sổ ghi lời gọi.
    Đầu ra: MeetingAnalyzerV3.
    Lỗi: ValueError nếu arm cần Verifier riêng/Decisions mà biến môi trường chưa đặt.
    """

    def main_llm(role: str) -> OpenAIChatJSONAdapter:
        return record_adapter_calls(OpenAIChatJSONAdapter(), ledger, role)

    if arm["verifier"] == "separate":
        verifier_llm, verifier_concurrency = _build_verifier_llm(None)
        if verifier_llm is None:
            raise ValueError("arm cần Verifier riêng nhưng VERIFIER_MODEL_NAME chưa đặt")
        record_adapter_calls(verifier_llm, ledger, "verifier")
    else:
        verifier_llm, verifier_concurrency = main_llm("verifier"), None

    decisions = None
    if arm["turn_judge"]:
        decisions = _build_decisions_client()
        if decisions is None:
            raise ValueError("arm cần Decisions API nhưng TURN_ACT_MODEL chưa đặt")
        client, model = decisions
        decisions = (RecordingClient(client, ledger, "decisions"), model)

    label_llm = main_llm("labeler")
    return MeetingAnalyzerV3(
        content_llm=main_llm("content"),
        action_llm=main_llm("action"),
        decision_llm=main_llm("decision"),
        verifier_llm=verifier_llm,
        labeler=StructuredLLMTopicLabeler(label_llm, model_name=label_llm.model_name),
        labeler_config=load_pipeline_config().topic_labeler,
        config=replace(build_v3_config_from_env(), **arm["config"]),
        llm_concurrency=int(os.environ.get("V3_LLM_CONCURRENCY", "8")),
        verifier_llm_concurrency=verifier_concurrency,
        turn_judge=_build_turn_judge(decisions),
        progress_judge=_build_progress_judge(decisions),
    )


class SharedSegmentation:
    """Ranh giới + nhãn chủ đề của một bộ cắt, tính một lần mỗi cuộc họp và dùng chung mọi arm."""

    def __init__(self, run_dir: Path, segmenter: str) -> None:
        self.segmenter = segmenter
        self.dir = run_dir / "_shared" / segmenter
        self.dir.mkdir(parents=True, exist_ok=True)
        self._dialstart = None
        self._embedding = None

    def _predict_boundaries(self, payload: dict, gold: dict) -> list[int]:
        """Ranh giới (chỉ số lượt) theo bộ cắt; mô hình chỉ được nạp khi cần."""

        if self.segmenter == "oracle":
            return list(gold["boundaries"])
        if self.segmenter == "none":
            return []
        if self.segmenter == "dialstart":
            if self._dialstart is None:
                from services.dependencies import build_topic_segmenter

                self._dialstart = build_topic_segmenter()
            return segment_boundaries(segment_meeting(payload, embedding_adapter=None, topic_segmenter=self._dialstart).segments)
        if self.segmenter == "treeseg":
            if self._embedding is None:
                from services.dependencies import build_embedding_adapter

                self._embedding = build_embedding_adapter()
            return segment_boundaries(segment_meeting(payload, embedding_adapter=self._embedding).segments)
        raise ValueError(f"segmenter không hợp lệ: {self.segmenter!r}")

    def get(self, meeting_id: str, payload: dict, turns: tuple, gold: dict, analyzer: MeetingAnalyzerV3):
        """(segments, labels) của cuộc họp; lần đầu thì cắt + gán nhãn rồi lưu.

        Đầu vào: meeting_id; payload - transcript; turns - lượt nói; gold - để lấy ranh giới oracle;
            analyzer - để gán nhãn (``label_segments``).
        Đầu ra: (list TopicSegment, tuple TopicLabel).
        """

        path = self.dir / f"{meeting_id}.json"
        if path.exists():
            data = json.loads(path.read_text())
            segments = boundaries_to_topic_segments(turns, data["boundaries"])
            # JSON biến tuple thành list; ``evidence_ids`` có thể là None (nhãn fallback) thì giữ None.
            labels = tuple(
                TopicLabel(**{k: tuple(v) if isinstance(v, list) else v for k, v in d.items()}) for d in data["labels"]
            )
            return segments, labels
        boundaries = self._predict_boundaries(payload, gold)
        segments = boundaries_to_topic_segments(turns, boundaries)
        labels = analyzer.label_segments(segments)
        data = {"boundaries": boundaries, "labels": [asdict(label) for label in labels]}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        return segments, labels


def check_turns_match_gold(meeting_id: str, turns: tuple, gold: dict) -> None:
    """Gold đánh chỉ số theo lượt nói lúc ``build.py`` dựng; lượt nói lần này phải trùng khớp.

    Lỗi: ValueError nếu số lượt khác hoặc gold trích turn_id không tồn tại.
    """

    if len(turns) != gold["n_turns"]:
        raise ValueError(f"{meeting_id}: {len(turns)} lượt nói, gold có {gold['n_turns']} -- stage03 đã đổi?")
    turn_ids = {turn.turn_id for turn in turns}
    cited = {tid for kind in ("assignments", "decisions", "negatives", "key_points") for g in gold[kind]
             for tid in g["evidence_turn_ids"]}
    missing = sorted(cited - turn_ids)
    if missing:
        raise ValueError(f"{meeting_id}: gold trích turn không tồn tại: {missing[:5]}")


def total_spent_usd() -> tuple[float, int]:
    """(USD đã biết giá, số lời gọi trả tiền chưa có giá) cộng trên mọi run đã ghi."""

    if not SPEND_LEDGER.exists():
        return 0.0, 0
    rows = [json.loads(line) for line in SPEND_LEDGER.read_text().splitlines() if line.strip()]
    return sum(r["usd_known"] for r in rows), sum(r["unpriced_paid_calls"] for r in rows)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=_REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def write_or_check_manifest(arm_dir: Path, arm_name: str, arm: dict, analyzer: MeetingAnalyzerV3 | None) -> None:
    """Ghi manifest lần đầu; lần sau (chạy tiếp) thì đòi mã nguồn và cấu hình không đổi.

    Lỗi: RuntimeError nếu fingerprint khác manifest đã có (code/prompt/model đã đổi: dùng ``--run`` mới).
    """

    fingerprint = fingerprint_pipeline(
        [_REPO_ROOT / s for s in _FINGERPRINT_SOURCES], _FINGERPRINT_ENV, root=_REPO_ROOT
    )
    path = arm_dir / "manifest.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if previous["fingerprint"] != fingerprint:
            raise RuntimeError(f"{path}: mã nguồn hoặc cấu hình đã đổi so với lúc bắt đầu run; dùng --run mới")
        return
    manifest = {
        "arm": arm_name,
        "arm_config": arm,
        "v3_config": asdict(analyzer.config) if analyzer is not None else None,
        "fingerprint": fingerprint,
        "git_sha": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--", "src", "be", "configs", "experiments/dialstart")),
        "models": {name: os.environ.get(name) for name in ("MODEL_NAME", "VERIFIER_MODEL_NAME", "TURN_ACT_MODEL")},
        "temperature": 0.0,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))


def select_meetings(ids: list[str], split: str) -> list[str]:
    """Các cuộc họp cần chạy: ``ids`` nếu có, không thì mọi cuộc họp thuộc ``split`` của manifest."""

    if ids:
        return ids
    manifest = json.loads((SYNTH_DIR / "manifest.json").read_text())
    return sorted(m["meeting_id"] for m in manifest if split == "all" or m.get("split", "dev") == split)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--run", required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--split", choices=("dev", "heldout", "all"), default="dev")
    parser.add_argument("--budget-usd", type=float, required=True,
                        help="trần tổng chi OpenAI của CẢ nghiên cứu (cộng mọi run trong spend_ledger.jsonl)")
    args = parser.parse_args()

    arm = load_arm(args.arm)
    run_dir = RESULTS_DIR / args.run
    arm_dir = run_dir / args.arm / f"r{args.repeat}"
    (arm_dir / "outputs").mkdir(parents=True, exist_ok=True)

    ledger = UsageLedger()
    if arm["baseline"] == "single_prompt":
        analyzer, shared = None, None
        baseline_llm = record_adapter_calls(OpenAIChatJSONAdapter(), ledger, "baseline")
    elif arm["baseline"] is None:
        analyzer = build_analyzer(arm, ledger)
        shared = SharedSegmentation(run_dir, arm["segmenter"])
    else:
        raise ValueError(f"baseline không hợp lệ: {arm['baseline']!r}")
    write_or_check_manifest(arm_dir, args.arm, arm, analyzer)

    seg_path, ev_path = arm_dir / "segmentation.json", arm_dir / "evidence_overlap.json"
    seg_rows = json.loads(seg_path.read_text()) if seg_path.exists() else {}
    ev_rows = json.loads(ev_path.read_text()) if ev_path.exists() else {}
    failed: list[str] = []
    stop_reason: str | None = None

    for meeting_id in select_meetings(args.ids, args.split):
        out_file = arm_dir / "outputs" / f"{meeting_id}.json"
        gold = json.loads((SYNTH_DIR / "gold" / f"{meeting_id}.json").read_text())
        if out_file.exists():
            output = json.loads(out_file.read_text())
            print(f"[{meeting_id}] dùng lại output có sẵn", flush=True)
        else:
            spent, unpriced = total_spent_usd()
            if spent >= args.budget_usd:
                print(f"DỪNG: đã chi ${spent:.4f} >= trần ${args.budget_usd} (chưa tính {unpriced} lời gọi chưa có giá)")
                break
            payload = json.loads((SYNTH_DIR / "transcripts" / f"{meeting_id}.json").read_text())
            _, revision_id, turns, _ = build_meeting_turns(payload)
            check_turns_match_gold(meeting_id, turns, gold)
            started = time.time()
            try:
                if analyzer is None:
                    output, boundaries = run_single_prompt(baseline_llm, turns)
                else:
                    segments, labels = shared.get(meeting_id, payload, turns, gold, analyzer)
                    report = analyzer.analyze(
                        meeting_id=meeting_id, revision_id=revision_id, turns=turns, segments=segments,
                        labels=labels, meeting_date=payload.get("meeting_date"), chair=payload.get("chair"),
                    )
                    output, boundaries = report_to_eval_output(report, turns), segment_boundaries(segments)
            except Exception as exc:  # một cuộc họp lỗi không được làm mất cả run
                cost = ledger.pop_summary()
                print(f"[{meeting_id}] LỖI {type(exc).__name__}: {exc}", flush=True)
                traceback.print_exc()
                failed.append(meeting_id)
            else:
                cost = ledger.pop_summary()
                if cost["quota_exhausted"]:
                    print(f"[{meeting_id}] DỪNG: tài khoản OpenAI hết tiền (insufficient_quota); KHÔNG lưu "
                          "output này, nạp tiền rồi chạy lại đúng lệnh để chạy tiếp.", flush=True)
                    stop_reason = "quota"
            if stop_reason is None and meeting_id not in failed:
                output["_segments"] = {"boundaries": boundaries, "segmenter": arm["baseline"] or arm["segmenter"],
                                       "seconds": round(time.time() - started, 1)}
                output["_cost"] = cost
                out_file.write_text(json.dumps(output, ensure_ascii=False, indent=1))
                print(f"[{meeting_id}] xong sau {output['_segments']['seconds']}s, ${cost['usd_known']:.4f}"
                      + (f" (+{cost['unpriced_paid_calls']} lời gọi chưa có giá)" if cost["unpriced_paid_calls"] else ""),
                      flush=True)
            with SPEND_LEDGER.open("a") as ledger_file:
                ledger_file.write(json.dumps({
                    "run": args.run, "arm": args.arm, "repeat": args.repeat, "meeting_id": meeting_id,
                    "usd_known": cost["usd_known"], "unpriced_paid_calls": cost["unpriced_paid_calls"],
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }) + "\n")
            if stop_reason is not None:
                break
            if meeting_id in failed:
                continue

        seg_rows[meeting_id] = segmentation_row(output, gold)
        ev_rows[meeting_id] = evidence_overlap(output, gold)
        seg_path.write_text(json.dumps(seg_rows, ensure_ascii=False, indent=1))
        ev_path.write_text(json.dumps(ev_rows, ensure_ascii=False, indent=1))

    keys = ["Pk", "WD", "F1@2k", "F1@5k", "dK"]
    print(f"\n{'meeting':<11}" + "".join(f"{k:>8}" for k in keys) + "   A_touch  D_touch  traps")
    for mid in sorted(seg_rows):
        r, e = seg_rows[mid], ev_rows[mid]
        touch = lambda kind: f"{e[kind]['touched']}/{e[kind]['gold']}"  # noqa: E731
        print(f"{mid:<11}" + "".join(f"{r[k]:>8.3f}" for k in keys)
              + f"   {touch('assignments'):>7}  {touch('decisions'):>7}  {len(e['negatives_touched']):>5}")
    if seg_rows:
        print(f"{'MEAN':<11}" + "".join(f"{np.mean([r[k] for r in seg_rows.values()]):>8.3f}" for k in keys))
    spent, unpriced = total_spent_usd()
    print(f"\nTổng chi OpenAI mọi run: ${spent:.4f} / ${args.budget_usd}"
          + (f" + {unpriced} lời gọi chưa có giá (đối chiếu dashboard)" if unpriced else ""))
    if failed:
        print(f"Lỗi: {failed}")


if __name__ == "__main__":
    main()
