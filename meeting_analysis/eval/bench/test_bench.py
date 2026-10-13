"""Test bộ chạy benchmark không gọi LLM: tính giá, sổ ghi lời gọi, khớp lượt nói với gold, chuẩn hoá output."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import run  # eval/bench/run.py (thêm sys.path cho be/, 007, bench khi import)
from normalize import report_to_eval_output
from src.agentic_v3.schemas import ActionItemV3, ActorAssignee, MeetingReport, VerificationRecord
from src.agentic_v3.core.schemas import DecisionCandidate, DiscussionPoint
from src.utils.contracts import SpeakerTurn, TopicLabel
from usage import RecordingClient, RoleUsage, UsageLedger, price_usd


def test_price_free_paid_and_unpriced():
    stats = RoleUsage(calls=2, input_tokens=1_000_000, cached_input_tokens=400_000, output_tokens=100_000)
    assert price_usd("google/gemma-4-26B-A4B-it", stats) == 0.0
    assert price_usd("gpt-4o-mini", stats) == pytest.approx(0.6 * 0.15 + 0.4 * 0.075 + 0.1 * 0.60)
    assert price_usd("gpt-6-luna", stats) is None


def test_estimated_spend_prices_unpriced_calls(tmp_path, monkeypatch):
    ledger = tmp_path / "spend_ledger.jsonl"
    ledger.write_text("\n".join(json.dumps({"usd_known": usd, "unpriced_paid_calls": n}) for usd, n in [(0.5, 10), (0.25, 30)]))
    monkeypatch.setattr(run, "SPEND_LEDGER", ledger)
    assert run.estimated_spent_usd(0.0) == pytest.approx((0.75, 0.75, 40))
    assert run.estimated_spent_usd(0.01) == pytest.approx((1.15, 0.75, 40))

def test_recording_client_counts_calls_errors_and_usage():
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20, prompt_tokens_details=None)
    calls = iter([SimpleNamespace(usage=usage), RuntimeError("timeout")])

    def create(**kwargs):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    inner = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
                            decisions=SimpleNamespace(create=create))
    ledger = UsageLedger()
    client = RecordingClient(inner, ledger, "decisions")
    client.decisions.create(model="gpt-6-luna", input="x")
    with pytest.raises(RuntimeError):
        client.decisions.create(model="gpt-6-luna", input="y")

    summary = ledger.pop_summary()
    (role,) = summary["roles"]
    assert (role["calls"], role["errors"], role["input_tokens"], role["output_tokens"]) == (2, 1, 100, 20)
    assert summary["unpriced_paid_calls"] == 2
    assert ledger.pop_summary()["roles"] == []  # đã xoá sổ


@pytest.mark.parametrize("meeting_id", run.select_meetings([], "all"))
def test_turns_match_gold(meeting_id):
    payload = json.loads((run.SYNTH_DIR / "transcripts" / f"{meeting_id}.json").read_text())
    gold = json.loads((run.SYNTH_DIR / "gold" / f"{meeting_id}.json").read_text())
    _, _, turns, _ = run.build_meeting_turns(payload)
    run.check_turns_match_gold(meeting_id, turns, gold)


def test_report_to_eval_output_uses_resolved_actor_and_drop_verdict():
    turn = SpeakerTurn("TURN_000001", "Nam", "Em làm.", ("i1",), None, None)
    label = TopicLabel("TOPIC_SEG_000000", "Làm API", "tóm tắt", "", ("TURN_000001",), "llm")
    action = ActionItemV3(
        "TOPIC_SEG_000000", "em", "Làm API", ("TURN_000001",), ("Em làm.",), deadline_raw="thứ Sáu",
        assignees=(ActorAssignee(mention="em", role="lead", name="Nam (Backend)", actor_type="person"),),
    )
    report = MeetingReport(
        labels=(label,),
        meeting_development=(DiscussionPoint("TOPIC_SEG_000000", "ý", ("Nam",), ("TURN_000001",), ("Em làm.",)),),
        assignments=(action,),
        decisions=(DecisionCandidate("TOPIC_SEG_000000", "Chốt", ("TURN_000001",), ("Em làm.",)),),
        verification_records=(VerificationRecord("k", "TOPIC_SEG_000000", "decision", "Bỏ", (), (), "drop", ""),),
        failures=(),
    )
    output = report_to_eval_output(report, (turn,))
    assert output["verified_assignments"][0]["actor"] == "Nam (Backend)"
    assert output["verified_assignments"][0]["deadline"] == "thứ Sáu"
    assert output["topics"][0]["discussion_points"][0]["evidence_ids"] == ["TURN_000001"]
    assert output["debate_records"][0]["kept"] is False


def test_shared_segmentation_roundtrip_keeps_labels(tmp_path):
    payload = json.loads((run.SYNTH_DIR / "transcripts" / "synth_028.json").read_text())
    gold = json.loads((run.SYNTH_DIR / "gold" / "synth_028.json").read_text())
    _, _, turns, _ = run.build_meeting_turns(payload)
    labels = tuple(
        TopicLabel(f"TOPIC_SEG_{i:06d}", f"t{i}", "s", "", None if i == 0 else ("TURN_000001",), "llm")
        for i in range(len(gold["boundaries"]) + 1)
    )
    analyzer = SimpleNamespace(label_segments=lambda segments: labels)
    shared = run.SharedSegmentation(tmp_path, "oracle")

    first = shared.get("synth_028", payload, turns, gold, analyzer)
    again = shared.get("synth_028", payload, turns, gold, analyzer=None)  # đọc lại từ file, không gán nhãn

    assert again[1] == first[1] == labels
    assert [s.atom_ids for s in again[0]] == [s.atom_ids for s in first[0]]


def test_quota_error_flags_summary_once():
    class QuotaError(Exception):
        code = "insufficient_quota"

    def create(**kwargs):
        raise QuotaError("You exceeded your current quota")

    inner = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    ledger = UsageLedger()
    with pytest.raises(QuotaError):
        RecordingClient(inner, ledger, "verifier").chat.completions.create(model="gpt-4o-mini")
    assert ledger.pop_summary()["quota_exhausted"] is True
    assert ledger.pop_summary()["quota_exhausted"] is False


def test_single_prompt_maps_topics_and_skips_unknown_ids():
    from baseline_single_prompt import run_single_prompt

    turns = tuple(SpeakerTurn(f"TURN_{i:06d}", None if i == 1 else f"S{i}", f"câu {i}", (), None, None) for i in range(4))
    raw = {
        "topics": [
            {"start_turn_id": "TURN_000000", "title": "A", "summary": "", "discussion_points": [
                {"text": "ý", "evidence_turn_ids": ["TURN_000001", "TURN_000000", "TURN_999999"]}]},
            {"start_turn_id": "TURN_000002", "title": "B", "summary": "", "discussion_points": []},
            {"start_turn_id": "TURN_000001", "title": "lùi lại", "summary": "", "discussion_points": []},
        ],
        "assignments": [{"actor": "S3", "task": "Làm", "deadline": None, "evidence_turn_ids": ["TURN_000003"]}],
        "decisions": [],
    }
    llm = SimpleNamespace(generate_json=lambda **kwargs: raw)
    output, boundaries = run_single_prompt(llm, turns)
    assert boundaries == [2]
    assert [t["title"] for t in output["topics"]] == ["A", "B"]
    assert output["topics"][0]["discussion_points"][0] == {
        "speakers": ["S0"], "text": "ý", "evidence_ids": ["TURN_000001", "TURN_000000"]}
    assert output["verified_assignments"][0]["segment_id"] == "TOPIC_SEG_000001"


def _judgment(a_hits, a_labels, d_hits=("match d0",), d_labels=("ok",), negatives=("avoided",)):
    return {
        "matching": {
            "assignments": {f"A{i}": v for i, v in enumerate(a_hits)},
            "decisions": {f"D{i}": v for i, v in enumerate(d_hits)},
            "key_points": {"K1": "partial"},
            "negatives": {f"N{i}": v for i, v in enumerate(negatives)},
        },
        "output_labels": {
            "assignments": {f"a{i}": {"label": lab, "actor_ok": lab == "ok", "deadline_ok": None} for i, lab in enumerate(a_labels)},
            "decisions": {f"d{i}": {"label": lab} for i, lab in enumerate(d_labels)},
        },
    }


def test_micro_metrics_from_judgment():
    from report import meeting_counts, metrics_from_counts

    m = metrics_from_counts(meeting_counts(_judgment(["match a0", "partial a1", "miss"], ["ok", "ok", "duplicate", "extra_valid"],
                                                     negatives=("avoided", "hit d1"))))
    assert m["R_A"] == pytest.approx(1.5 / 3)
    assert m["P_A"] == pytest.approx(3 / 4)
    assert m["F1_A"] == pytest.approx(2 * 0.75 * 0.5 / 1.25)
    assert m["actor_acc"] == 1.0 and m["deadline_acc"] is None
    assert m["trap_rate"] == 0.5 and m["R_K"] == 0.5


def test_bootstrap_delta_detects_consistent_gap():
    from report import bootstrap_delta, meeting_counts

    good = {f"m{i}": meeting_counts(_judgment(["match a0"] * 4, ["ok"] * 4)) for i in range(12)}
    bad = {f"m{i}": meeting_counts(_judgment(["match a0", "miss", "miss", "miss"], ["ok", "hallucinated"])) for i in range(12)}
    delta, low, high, n = bootstrap_delta(bad, good, "R_A", n=500)
    assert n == 12 and delta == pytest.approx(-0.75) and high < 0


def test_cohen_kappa_bounds():
    from judge_agreement import cohen_kappa

    assert cohen_kappa([("match", "match"), ("miss", "miss")]) == 1.0
    assert cohen_kappa([("match", "miss"), ("miss", "match")]) == -1.0
    assert cohen_kappa([]) is None
