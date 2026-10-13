"""Chấm Bảng 1 (``PLAN.md`` §4, §6): ghép dự đoán với gold, metric theo cuộc họp, bootstrap CI.

Luật ghép (một luật cho mọi phương pháp):
    1. Mục có ``evidence_turn_ids`` rỗng hoặc chứa id không có thật bị loại trước khi chấm.
    2. Một dự đoán là ứng viên của một gold khi có ít nhất một lượt bằng chứng rơi vào khoảng
       lượt của gold nới thêm ``window`` lượt mỗi phía, và độ trùng âm tiết nội dung
       >= ``min_overlap``.
    3. Ghép tham lam một–một theo độ trùng giảm dần.

Số đếm được cộng dồn qua các cuộc họp (micro), nên bootstrap lấy mẫu lại theo cuộc họp rồi
cộng số đếm của mẫu.
"""

from __future__ import annotations

import importlib.util
import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, fields

import numpy as np

from benchmark.data import PROJECT_ROOT, Meeting
from src.agentic_v3.core.deadline import normalize_deadline

DEFAULT_WINDOW = 1
DEFAULT_MIN_OVERLAP = 0.15
# Synthetic không có ngày họp: neo mọi hạn tương đối của gold và dự đoán vào cùng một ngày giả,
# nên "thứ Sáu tuần này" và "chậm nhất thứ Sáu" vẫn quy về cùng một ngày.
PSEUDO_MEETING_DATE = "2026-11-25"

_STOPWORDS = frozenset(
    "và với của cho các những là thì mà để được bị có không này đó kia ở trong trên dưới từ đến tới "
    "về theo khi nếu như cũng đã đang sẽ rồi lại ra vào lên nữa một hai ba hết phải cần nên làm việc "
    "anh chị em ông bà cô chú bác tôi mình chúng ta họ bên phía phần lúc nào gì ạ dạ vâng nhé".split()
)
_HONORIFICS = ("đồng chí", "đ/c", "anh", "chị", "em", "ông", "bà", "cô", "chú", "bác", "thầy", "bạn")
_NON_WORD_RE = re.compile(r"[^\w]+")
_PAREN_RE = re.compile(r"\(.*?\)")


def _load_segmentation_metrics():
    path = PROJECT_ROOT / "experiments" / "007_dialtreeseg" / "metrics.py"
    spec = importlib.util.spec_from_file_location("dialtreeseg_metrics", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SEG_METRICS = _load_segmentation_metrics()


# --------------------------------------------------------------------------- chuẩn hoá chuỗi


def syllables(text: str | None) -> frozenset[str]:
    """Tập âm tiết nội dung (chữ thường, bỏ dấu câu và hư từ)."""

    if not text:
        return frozenset()
    tokens = _NON_WORD_RE.split(unicodedata.normalize("NFC", text).lower())
    return frozenset(t for t in tokens if t and t not in _STOPWORDS)


def overlap(pred_text: str, gold_text: str) -> float:
    """Độ trùng âm tiết kiểu Dice giữa hai chuỗi, trong [0, 1]."""

    a, b = syllables(pred_text), syllables(gold_text)
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def normalize_name(name: str | None) -> str:
    """Tên người/đơn vị đã chuẩn hoá: bỏ phần trong ngoặc, dấu câu, danh xưng đứng đầu."""

    if not name:
        return ""
    text = _PAREN_RE.sub(" ", unicodedata.normalize("NFC", name).lower())
    text = " ".join(_NON_WORD_RE.sub(" ", text.replace("đ/c", "đồng chí")).split())
    changed = True
    while changed:
        changed = False
        for honorific in _HONORIFICS:
            if text.startswith(honorific + " "):
                text, changed = text[len(honorific) + 1 :], True
    return "" if text in _HONORIFICS else text


def actor_matches(pred_actor: str | None, gold_actor: str, aliases: Iterable[str] = ()) -> bool:
    """Người phụ trách dự đoán có khớp gold (tên chính hoặc một bí danh không phải đại từ) không."""

    pred = normalize_name(pred_actor)
    if not pred:
        return False
    candidates = {normalize_name(gold_actor), *(normalize_name(alias) for alias in aliases)} - {""}
    return pred in candidates


def deadline_matches(pred: str | None, gold: str | None, meeting_date: str | None) -> bool:
    """Hạn dự đoán khớp gold: cùng rỗng, cùng quy ra một ngày, hoặc chuỗi gần như trùng khi không quy được."""

    pred = (pred or "").strip() or None
    if pred is None or gold is None:
        return pred is None and gold is None
    anchor = meeting_date or PSEUDO_MEETING_DATE
    pred_date = normalize_deadline(pred, anchor).deadline_date
    gold_date = normalize_deadline(gold, anchor).deadline_date
    if pred_date and gold_date:
        return pred_date == gold_date
    return overlap(pred, gold) >= 0.5


# --------------------------------------------------------------------------- ghép


@dataclass(frozen=True, slots=True)
class Match:
    pred_index: int
    gold_index: int
    score: float


def turn_window(gold_turns: Iterable[int], window: int) -> range:
    turns = list(gold_turns)
    return range(min(turns) - window, max(turns) + window + 1)


def greedy_match(
    preds: Sequence[dict],
    golds: Sequence[dict],
    pred_text: Callable[[dict], str],
    gold_text: Callable[[dict], str],
    window: int,
    min_overlap: float,
) -> list[Match]:
    """Ghép một–một dự đoán với gold theo luật ở docstring module.

    Đầu vào: ``preds``/``golds`` đã có khoá ``_turns`` (chỉ số lượt bằng chứng).
    Đầu ra: danh sách cặp đã ghép.
    """

    candidates = []
    for gi, gold in enumerate(golds):
        span = turn_window(gold["_turns"], window)
        for pi, pred in enumerate(preds):
            if not any(t in span for t in pred["_turns"]):
                continue
            score = overlap(pred_text(pred), gold_text(gold))
            if score >= min_overlap:
                candidates.append(Match(pi, gi, score))
    used_pred, used_gold, matches = set(), set(), []
    for match in sorted(candidates, key=lambda m: (-m.score, m.pred_index, m.gold_index)):
        if match.pred_index in used_pred or match.gold_index in used_gold:
            continue
        used_pred.add(match.pred_index)
        used_gold.add(match.gold_index)
        matches.append(match)
    return matches


# --------------------------------------------------------------------------- chấm một cuộc họp


@dataclass(slots=True)
class Counts:
    """Số đếm của một cuộc họp (cộng được qua nhiều cuộc họp)."""

    assign_pred: int = 0
    assign_gold: int = 0
    assign_tp: int = 0
    assign_actor_tp: int = 0
    deadline_ok: int = 0
    decision_pred: int = 0
    decision_gold: int = 0
    decision_tp: int = 0
    key_points: int = 0
    key_points_covered: int = 0
    trapped: int = 0
    dropped_invalid_evidence: int = 0

    def __add__(self, other: "Counts") -> "Counts":
        return Counts(*(getattr(self, f.name) + getattr(other, f.name) for f in fields(self)))


@dataclass(slots=True)
class MeetingScore:
    """Kết quả chấm một cuộc họp: số đếm, Pk/WD và các cặp/mục để kiểm tay (M0)."""

    meeting_id: str
    counts: Counts
    pk: float | None = None
    wd: float | None = None
    audit: list[dict] = field(default_factory=list)


def _with_turn_indices(items: Sequence[dict], index_of: dict[str, int]) -> tuple[list[dict], int]:
    """Gắn ``_turns`` cho từng mục; loại mục có evidence rỗng hoặc id không có thật."""

    kept, dropped = [], 0
    for item in items or ():
        ids = item.get("evidence_turn_ids") or []
        if not ids or any(turn_id not in index_of for turn_id in ids):
            dropped += 1
            continue
        kept.append({**item, "_turns": sorted(index_of[turn_id] for turn_id in ids)})
    return kept, dropped


def _segmentation(meeting: Meeting, output: dict, index_of: dict[str, int]) -> tuple[float, float]:
    starts = {index_of[t["start_turn"]] for t in output.get("topics") or () if t.get("start_turn") in index_of}
    prefix = np.concatenate([[0], np.cumsum([turn.chars for turn in meeting.turns])])
    row = _SEG_METRICS.evaluate(sorted(starts - {0}), meeting.gold["boundaries"], prefix)
    return row["Pk"], row["WD"]


_TRAP_TYPES = {
    "assignments": {"rejected_task", "unassigned_task", "hedged_proposal"},
    "decisions": {"hedged_proposal", "superseded_decision", "rejected_task"},
}


def _is_trapped(pred: dict, kind: str, negatives: Sequence[dict], text_of: Callable, window: int, min_overlap: float) -> dict | None:
    for negative in negatives:
        if negative["type"] not in _TRAP_TYPES[kind]:
            continue
        if negative["type"] == "unassigned_task" and not normalize_name(pred.get("actor")):
            continue  # việc không ai nhận được phép xuất hiện nếu không gán người
        span = turn_window(negative["_turns"], window)
        if any(t in span for t in pred["_turns"]) and overlap(text_of(pred), negative["text"]) >= min_overlap:
            return negative
    return None


def score_meeting(
    meeting: Meeting,
    output: dict,
    window: int = DEFAULT_WINDOW,
    min_overlap: float = DEFAULT_MIN_OVERLAP,
) -> MeetingScore:
    """Chấm output (schema chung §5) của một phương pháp trên một cuộc họp synthetic."""

    gold = meeting.gold
    index_of = {turn.turn_id: i for i, turn in enumerate(meeting.turns)}
    golds = {k: _with_turn_indices(gold.get(k, []), index_of)[0] for k in ("assignments", "decisions", "key_points", "negatives")}
    assignments, dropped_a = _with_turn_indices(output.get("assignments"), index_of)
    decisions, dropped_d = _with_turn_indices(output.get("decisions"), index_of)
    discussion, dropped_k = _with_turn_indices(output.get("discussion"), index_of)
    counts = Counts(dropped_invalid_evidence=dropped_a + dropped_d + dropped_k)
    audit: list[dict] = []

    # Việc giao
    task_text = lambda item: item.get("task") or ""  # noqa: E731
    a_matches = greedy_match(assignments, golds["assignments"], task_text, task_text, window, min_overlap)
    counts.assign_pred, counts.assign_gold, counts.assign_tp = len(assignments), len(golds["assignments"]), len(a_matches)
    for m in a_matches:
        pred, ref = assignments[m.pred_index], golds["assignments"][m.gold_index]
        actor_ok = actor_matches(pred.get("actor"), ref["actor"], ref.get("actor_aliases", ()))
        deadline_ok = deadline_matches(pred.get("deadline"), ref.get("deadline"), meeting.meeting_date)
        counts.assign_actor_tp += actor_ok
        counts.deadline_ok += deadline_ok
        audit.append({"kind": "assignment", "status": "matched", "score": round(m.score, 3), "pred": _clean(pred), "gold": _clean(ref), "actor_ok": actor_ok, "deadline_ok": deadline_ok})

    # Kết luận
    decision_text = lambda item: item.get("text") or ""  # noqa: E731
    d_matches = greedy_match(decisions, golds["decisions"], decision_text, decision_text, window, min_overlap)
    counts.decision_pred, counts.decision_gold, counts.decision_tp = len(decisions), len(golds["decisions"]), len(d_matches)
    for m in d_matches:
        audit.append({"kind": "decision", "status": "matched", "score": round(m.score, 3), "pred": _clean(decisions[m.pred_index]), "gold": _clean(golds["decisions"][m.gold_index])})

    # Bẫy: chỉ xét mục không ghép được với gold
    for kind, preds, matched, text_of in (
        ("assignments", assignments, {m.pred_index for m in a_matches}, task_text),
        ("decisions", decisions, {m.pred_index for m in d_matches}, decision_text),
    ):
        for pi, pred in enumerate(preds):
            if pi in matched:
                continue
            trap = _is_trapped(pred, kind, golds["negatives"], text_of, window, min_overlap)
            counts.trapped += trap is not None
            audit.append({"kind": kind.rstrip("s"), "status": "trapped" if trap else "unmatched", "pred": _clean(pred), "gold": _clean(trap) if trap else None})

    # Ý chính: nhiều–một (một ý thảo luận có thể phủ nhiều ý chính)
    counts.key_points = len(golds["key_points"])
    for point in golds["key_points"]:
        span = turn_window(point["_turns"], window)
        counts.key_points_covered += any(
            any(t in span for t in item["_turns"])
            and overlap(item.get("text") or "", point["point"]) >= min_overlap
            and any(actor_matches(speaker, point["speaker"]) for speaker in item.get("speakers") or ())
            for item in discussion
        )

    pk, wd = _segmentation(meeting, output, index_of) if "boundaries" in gold else (None, None)
    return MeetingScore(meeting.meeting_id, counts, pk, wd, audit)


def _clean(item: dict | None) -> dict | None:
    return None if item is None else {k: v for k, v in item.items() if not k.startswith("_")}


# --------------------------------------------------------------------------- tổng hợp và bootstrap


def _ratio(num: float, den: float) -> float | None:
    return num / den if den else None


def _f1(tp: int, n_pred: int, n_gold: int) -> float:
    if n_pred == 0 and n_gold == 0:
        return 1.0
    return 2 * tp / (n_pred + n_gold) if (n_pred + n_gold) else 0.0


def summarize(scores: Sequence[MeetingScore]) -> dict[str, float | None]:
    """Metric Bảng 1 trên một tập cuộc họp (micro theo số đếm; Pk/WD lấy trung bình theo cuộc họp)."""

    c = sum((s.counts for s in scores), Counts())
    n_items = c.assign_pred + c.decision_pred
    trap = _ratio(c.trapped, n_items)
    row = {
        "assign_f1": _f1(c.assign_tp, c.assign_pred, c.assign_gold),
        "assign_actor_f1": _f1(c.assign_actor_tp, c.assign_pred, c.assign_gold),
        "actor_acc": _ratio(c.assign_actor_tp, c.assign_tp),
        "deadline_acc": _ratio(c.deadline_ok, c.assign_tp),
        "decision_f1": _f1(c.decision_tp, c.decision_pred, c.decision_gold),
        "coverage": _ratio(c.key_points_covered, c.key_points),
        "trap_rate": trap,
        "pk": _mean([s.pk for s in scores]),
        "wd": _mean([s.wd for s in scores]),
        "dropped_invalid_evidence": c.dropped_invalid_evidence,
    }
    parts = [row["assign_actor_f1"], row["decision_f1"], row["coverage"], None if trap is None else 1 - trap]
    row["average"] = _mean(parts) if None not in parts else None
    return row


def _mean(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return float(np.mean(present)) if present else None


def bootstrap_ci(
    scores: Sequence[MeetingScore], metric: str, n_resamples: int = 1000, seed: int = 0, alpha: float = 0.05
) -> tuple[float | None, float | None]:
    """95% CI percentile của ``metric``, lấy mẫu lại theo cuộc họp."""

    rng = np.random.default_rng(seed)
    values = []
    for _ in range(n_resamples):
        sample = [scores[i] for i in rng.integers(0, len(scores), len(scores))]
        value = summarize(sample)[metric]
        if value is not None:
            values.append(value)
    if not values:
        return None, None
    return float(np.quantile(values, alpha / 2)), float(np.quantile(values, 1 - alpha / 2))


def paired_bootstrap(
    scores_a: Sequence[MeetingScore],
    scores_b: Sequence[MeetingScore],
    metric: str,
    n_resamples: int = 1000,
    seed: int = 0,
) -> dict[str, float]:
    """Hiệu ``metric(a) − metric(b)`` với cùng các mẫu cuộc họp: hiệu gốc, 95% CI, p hai phía.

    Lỗi: ValueError nếu hai danh sách không cùng thứ tự cuộc họp.
    """

    if [s.meeting_id for s in scores_a] != [s.meeting_id for s in scores_b]:
        raise ValueError("paired bootstrap cần cùng danh sách cuộc họp theo cùng thứ tự")
    rng = np.random.default_rng(seed)
    observed = summarize(scores_a)[metric] - summarize(scores_b)[metric]
    diffs = []
    for _ in range(n_resamples):
        idx = rng.integers(0, len(scores_a), len(scores_a))
        a, b = summarize([scores_a[i] for i in idx])[metric], summarize([scores_b[i] for i in idx])[metric]
        if a is not None and b is not None:
            diffs.append(a - b)
    diffs_arr = np.asarray(diffs)
    p_value = min(1.0, 2 * min(np.mean(diffs_arr <= 0), np.mean(diffs_arr >= 0)))
    return {
        "diff": observed,
        "ci_low": float(np.quantile(diffs_arr, 0.025)),
        "ci_high": float(np.quantile(diffs_arr, 0.975)),
        "p": float(p_value),
    }


def holm(p_values: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    """Hiệu chỉnh Holm–Bonferroni: tên so sánh -> có ý nghĩa hay không."""

    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    result, still_rejecting = {}, True
    for rank, (name, p) in enumerate(ordered):
        still_rejecting = still_rejecting and p <= alpha / (len(ordered) - rank)
        result[name] = still_rejecting
    return result

