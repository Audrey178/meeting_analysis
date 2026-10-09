"""So luật từ khoá (_COMMIT_CUES/_HEDGE_CUES) với OpenAI Decisions API trên từng lượt nói.

Câu hỏi đo: lượt nói này có thực sự GIAO/NHẬN việc hoặc CHỐT kết luận không. Đây là điều
``_confirm_turn_reasons`` đang quyết định bằng từ khoá.

Hai nguồn lượt nói:
- ``synthetic``: 30 transcript trong ``eval/synthetic``, nhãn lấy từ gold
  (lượt bằng chứng của assignments/decisions -> dương; của negatives -> âm; thêm mẫu lượt
  thường -> âm).
- ``real``: một transcript thật, không có nhãn; chỉ ghi lại để xem chỗ hai bên lệch nhau.

Kết quả ghi theo dòng vào ``results/<source>.jsonl``; chạy lại sẽ bỏ qua lượt đã có.

Cách chạy:
    python experiments/009_decisions_api/run_turn_act.py synthetic
    python experiments/009_decisions_api/run_turn_act.py real inputs/recording_old.json
"""

from __future__ import annotations

import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from src.agentic._shared import _confirm_turn_reasons  # noqa: E402
from src.stages.stage01_effective_transcript import resolve_effective_transcript  # noqa: E402
from src.stages.stage02_evidence import build_evidence_items  # noqa: E402
from src.stages.stage03_speaker_turns import build_speaker_turns  # noqa: E402
from src.utils.adapters import parse_transcript_payload  # noqa: E402
from src.utils.config import load_config  # noqa: E402
from src.utils.contracts import SpeakerTurn  # noqa: E402

ENV_PATH = _REPO_ROOT.parent / ".env"
CONFIG_PATH = _REPO_ROOT / "configs" / "default.json"
SYNTH_DIR = _REPO_ROOT / "eval" / "synthetic"
RESULTS_DIR = _HERE / "results"

MODEL = "gpt-6-luna"
CONTEXT_TURNS = 2
MAX_TURN_CHARS = 2500
OTHER_TURNS_PER_MEETING = 8
CONCURRENCY = 8
COMMIT_CHOICES = ("giao_viec", "ket_luan")
NEGATIVE_TYPES = ("hedged_proposal", "superseded_decision", "rejected_task", "unassigned_task")

TURN_ACT_QUESTION = {
    "type": "choice",
    "name": "turn_act",
    "instructions": (
        "Input là trích đoạn cuộc họp tiếng Việt: vài lượt ngữ cảnh rồi LƯỢT CẦN XÉT. "
        "Chỉ phân loại LƯỢT CẦN XÉT, dùng ngữ cảnh để hiểu nó. Xét theo nghĩa, không theo từ khoá: "
        "khẩu ngữ như 'nhá', 'cứ làm đi', 'coi như xong', 'giúp anh' vẫn có thể là giao/chốt; "
        "'đề nghị' của người chủ trì thường là chỉ đạo, của đại biểu thường là kiến nghị."
    ),
    "choices": [
        {"value": "giao_viec", "description": "Giao việc cho người/đơn vị cụ thể, hoặc một người nhận/cam kết làm việc."},
        {"value": "ket_luan", "description": "Chốt, kết luận hoặc thống nhất một quyết định."},
        {"value": "de_xuat", "description": "Mới là ý kiến, đề xuất, kiến nghị, ghi nhận; chưa ai chốt hay nhận."},
        {"value": "bac_bo", "description": "Gạt đi, đảo lại hoặc huỷ một đề xuất/quyết định/việc trước đó."},
        {"value": "thao_luan", "description": "Trình bày, báo cáo, hỏi đáp; không giao, không chốt."},
        {"value": "khac", "description": "Không thuộc các loại trên."},
    ],
}


def _api_key() -> str:
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("VERIFIER_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"Không thấy VERIFIER_API_KEY trong {ENV_PATH}")


def build_turns(payload: dict) -> list[SpeakerTurn]:
    """Chạy stage01-03 như pipeline để ra ``SpeakerTurn`` cùng id với output thật."""

    meeting_id, _revision, raw_items = parse_transcript_payload(payload)
    config = load_config(str(CONFIG_PATH))
    evidence = build_evidence_items(meeting_id, resolve_effective_transcript(raw_items))
    return list(build_speaker_turns(evidence, config.turn_builder))


def render_input(turns: list[SpeakerTurn], index: int) -> str:
    """Ghép ngữ cảnh + lượt cần xét thành input cho Decisions."""

    def line(turn: SpeakerTurn) -> str:
        return f"{turn.speaker or 'Không rõ'}: {turn.text_exact[:MAX_TURN_CHARS]}"

    context = [line(t) for t in turns[max(0, index - CONTEXT_TURNS):index]]
    parts = ["NGỮ CẢNH:\n" + "\n".join(context)] if context else []
    parts.append("LƯỢT CẦN XÉT:\n" + line(turns[index]))
    return "\n\n".join(parts)


def regex_is_commit(turn: SpeakerTurn) -> bool:
    return not _confirm_turn_reasons(turn)


def synthetic_samples(rng: random.Random) -> list[dict]:
    samples = []
    for gold_path in sorted((SYNTH_DIR / "gold").glob("*.json")):
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        payload = json.loads((SYNTH_DIR / "transcripts" / gold_path.name).read_text(encoding="utf-8"))
        turns = build_turns(payload)
        index_of = {t.turn_id: i for i, t in enumerate(turns)}
        labels: dict[str, set[str]] = {}
        for kind, entries in (("assignment", gold["assignments"]), ("decision", gold["decisions"])):
            for entry in entries:
                for turn_id in entry["evidence_turn_ids"]:
                    labels.setdefault(turn_id, set()).add(kind)
        for entry in gold["negatives"]:
            for turn_id in entry["evidence_turn_ids"]:
                labels.setdefault(turn_id, set()).add(entry["type"])
        others = [t.turn_id for t in turns if t.turn_id not in labels]
        for turn_id in rng.sample(others, min(OTHER_TURNS_PER_MEETING, len(others))):
            labels[turn_id] = {"other"}
        for turn_id, kinds in labels.items():
            is_pos = bool(kinds & {"assignment", "decision"})
            is_neg = bool(kinds - {"assignment", "decision"})
            if is_pos and is_neg:  # vừa là bằng chứng vừa là bẫy -> nhãn mơ hồ, bỏ
                continue
            index = index_of[turn_id]
            samples.append({
                "key": f"{gold['meeting_id']}/{turn_id}",
                "kinds": sorted(kinds),
                "gold_commit": is_pos,
                "turn": turns[index],
                "input": render_input(turns, index),
            })
    return samples


def real_samples(path: Path) -> list[dict]:
    turns = build_turns(json.loads(path.read_text(encoding="utf-8")))
    return [
        {"key": f"{path.stem}/{t.turn_id}", "kinds": [], "gold_commit": None, "turn": t,
         "input": render_input(turns, i)}
        for i, t in enumerate(turns)
        if len(t.text_exact.split()) >= 4  # bỏ lượt "dạ", "vâng" ...
    ]


def ask_decisions(client: httpx.Client, text: str) -> tuple[dict, float]:
    body = {"model": MODEL, "input": text, "questions": [TURN_ACT_QUESTION]}
    for attempt in range(5):
        started = time.monotonic()
        try:
            response = client.post("https://api.openai.com/v1/decisions", json=body)
        except httpx.TransportError:
            time.sleep(2 * (attempt + 1))
            continue
        if response.status_code in (429, 500, 502, 503):
            time.sleep(2 * (attempt + 1))
            continue
        response.raise_for_status()
        return response.json()["answers"][0], time.monotonic() - started
    raise RuntimeError("Decisions API lỗi sau 5 lần thử")


def run(samples: list[dict], out_path: Path) -> None:
    done = set()
    if out_path.exists():
        done = {json.loads(line)["key"] for line in out_path.open(encoding="utf-8")}
    todo = [s for s in samples if s["key"] not in done]
    print(f"{len(samples)} lượt, đã có {len(done)}, cần gọi {len(todo)}", flush=True)
    client = httpx.Client(headers={"Authorization": f"Bearer {_api_key()}"}, timeout=30)

    def one(sample: dict) -> dict:
        answer, seconds = ask_decisions(client, sample["input"])
        probs = {p["value"]: p["probability"] for p in answer.get("probabilities", [])}
        turn = sample["turn"]
        return {
            "key": sample["key"],
            "kinds": sample["kinds"],
            "gold_commit": sample["gold_commit"],
            "speaker": turn.speaker,
            "text": turn.text_exact,
            "regex_commit": regex_is_commit(turn),
            "regex_reasons": _confirm_turn_reasons(turn),
            "choice": answer.get("choice"),
            "confidence": answer.get("confidence"),
            "probs": probs,
            "p_commit": sum(probs.get(c, 0.0) for c in COMMIT_CHOICES),
            "seconds": round(seconds, 3),
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as out, ThreadPoolExecutor(CONCURRENCY) as pool:
        for n, record in enumerate(pool.map(one, todo), 1):
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            if n % 50 == 0:
                print(f"  {n}/{len(todo)}", flush=True)


def main(argv: list[str]) -> None:
    source = argv[0]
    if source == "synthetic":
        run(synthetic_samples(random.Random(0)), RESULTS_DIR / "synthetic.jsonl")
    elif source == "real":
        path = Path(argv[1])
        run(real_samples(path), RESULTS_DIR / f"real_{path.stem}.jsonl")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
