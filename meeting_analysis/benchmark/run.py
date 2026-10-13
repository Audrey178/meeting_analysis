"""Chạy một hàng Bảng 1 trên một tập cuộc họp (``PLAN.md`` §8).

    python -m benchmark.run --method zero_shot --model gemma --split dev [--ids synth_005 ...]

Output mỗi cuộc họp ở ``results/<method>__<model>/<meeting_id>.json`` gồm output theo schema chung,
usage và khoá cache (băm prompt + model). Cuộc họp đã có output cùng khoá thì bỏ qua, nên chạy lại
sau khi gateway sập không tốn thêm. Lỗi được ghi ``status: "error"`` và chạy lại lần sau.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv

from benchmark.data import PROJECT_ROOT, SPLITS, load_meeting
from benchmark.llm import BenchLLM, ModelConfig, Usage
from benchmark.methods.common import Method

BENCH_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_DIR / "results"
logger = logging.getLogger("benchmark.run")


def load_method(name: str) -> Method:
    return importlib.import_module(f"benchmark.methods.{name}").METHOD


def cache_key(method: Method, model: ModelConfig) -> str:
    payload = json.dumps([method.name, method.prompt_fingerprint, model.name], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def git_sha() -> str:
    result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=PROJECT_ROOT)
    return result.stdout.strip()


def run_one(meeting_id: str, method: Method, llm: BenchLLM, out_dir: Path, key: str) -> str:
    """Chạy một cuộc họp, ghi file kết quả; trả trạng thái ("cached", "ok", "error")."""

    out_path = out_dir / f"{meeting_id}.json"
    if out_path.exists():
        previous = json.loads(out_path.read_text())
        if previous.get("cache_key") == key and previous.get("status") == "ok":
            return "cached"
    meeting = load_meeting(meeting_id)
    usage = Usage()
    record = {"meeting_id": meeting_id, "method": method.name, "model": llm.config.name, "cache_key": key,
              "git_sha": git_sha(), "finished_at": None}
    try:
        record.update(status="ok", output=method.run(meeting, llm, usage))
    except Exception as exc:  # ghi lỗi theo cuộc họp, không dừng cả run
        logger.exception("%s/%s lỗi", method.name, meeting_id)
        record.update(status="error", error=f"{type(exc).__name__}: {exc}")
    record.update(usage=usage.as_dict(), input_chars=meeting.total_chars,
                  finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    logger.info("%s/%s %s %s", method.name, meeting_id, record["status"], usage.as_dict())
    return record["status"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--method", required=True)
    parser.add_argument("--model", default="gemma")
    parser.add_argument("--split", choices=sorted(SPLITS), default="dev")
    parser.add_argument("--ids", nargs="*", help="chỉ chạy các cuộc họp này")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv(PROJECT_ROOT.parent / ".env")
    config = yaml.safe_load((BENCH_DIR / "config.yaml").read_text())
    model = ModelConfig(**config["models"][args.model])
    method = load_method(args.method)
    llm = BenchLLM(model)
    key = cache_key(method, model)
    out_dir = RESULTS_DIR / f"{method.name}__{args.model}"
    out_dir.mkdir(parents=True, exist_ok=True)

    ids = args.ids or list(SPLITS[args.split])
    with ThreadPoolExecutor(max_workers=config["max_parallel_meetings"]) as pool:
        statuses = list(pool.map(lambda mid: run_one(mid, method, llm, out_dir, key), ids))
    summary = {status: statuses.count(status) for status in set(statuses)}
    logger.info("xong %s: %s", out_dir.name, summary)


if __name__ == "__main__":
    main()
