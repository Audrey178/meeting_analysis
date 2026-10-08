"""Wiring test for the FastAPI backend (main.py + routers/ + services/): a
real transcript through stage01-03 -> TreeSeg (over turns) -> stage07 ->
the hướng-C LangGraph -> HTTP response, with every adapter dependency
overridden by a fake (no network, no billed API calls). Checks the endpoint
is wired correctly end-to-end, not that any real model's output is good --
that's separate work once a real adapter is chosen (see DESIGN.md).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from services.dependencies import (
    get_downstream_llm_adapters,
    get_embedding_adapter,
    get_topic_label_adapter,
)

# Must match stage07_topic_labeling.py's OWN import of TopicLabel
# (`from ..utils.contracts import TopicLabel`, i.e. nested under `src`) --
# see the long comment in services/pipeline.py's imports for why the bare
# `utils.contracts` flavor is a different class and would fail
# `_validate_label_structure`'s `isinstance(label, TopicLabel)` check.
from src.utils.contracts import TopicLabel
from src.utils.ports import LLMUpstreamError

_SAMPLE_TRANSCRIPT = (
    Path(__file__).resolve().parent.parent / "inputs" / "sample_transcript.json"
)


class _FakeEmbeddingAdapter:
    """Deterministic, content-based -- no network. Doesn't need to produce
    meaningful clusters: a tiny sample transcript never reaches TreeSeg's
    ``2*min_size`` split threshold anyway (see ``run_to_TreeSeg.py``'s own
    ``min_size=25``), so it always comes back as exactly one segment --
    this test is about the HTTP wiring, not about TreeSeg's clustering
    quality."""

    def embed(self, text: str) -> tuple[float, ...]:
        digest = sum(ord(char) for char in text)
        return (float(digest % 97), float(digest % 53))


class _FakeTopicLabelAdapter:
    def label_topic(self, segment, prev_segment, prev_topic, turns, evidence, *, prior_issues=()):
        del prev_segment, prev_topic, turns, evidence, prior_issues
        text = segment.text or ""
        return TopicLabel(
            segment_id=segment.segment_id,
            title=f"Chủ đề đoạn {segment.segment_id}",
            summary=text[:200],
            text=text,
            evidence_ids=(),
            method="fake_for_test",
        )


class _UnusedLLM:
    """Fails loudly if ever called -- documents that the fixture's action/decision
    candidates are all unambiguous (actor resolved, no hedge words), so
    Evidence-Check must never route anything to Debate+Judge."""

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema: dict) -> dict:
        raise AssertionError("debate_and_judge_agent should not run for this fixture")


# Lượt nói có từ giao/chốt trong transcript mẫu (vd. "...chủ trì hoàn thiện
# báo cáo... trước ngày 30 tháng 9...").
_CONFIRMING_TURN_PATTERN = r"trước ngày|thống nhất|giao"


class _DroppingJudgeLLM:
    """Debate+Judge giả: hai bên trả lập luận rỗng, judge luôn ``drop``."""

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema: dict) -> dict:
        del system_prompt, user_prompt
        if "verdict" in schema["properties"]:
            return {"verdict": "drop", "deciding_turn_id": None, "revised_actor": None, "reasoning": ""}
        return {"argument": ""}


class _CitingLLM:
    """A fake LLM whose response is built from the prompt so it can cite a
    REAL turn of the segment (items without a valid citation are dropped by
    the agents)."""

    def __init__(self, build, prefer_turn_pattern: str | None = None) -> None:
        self._build = build
        self._prefer = re.compile(prefer_turn_pattern) if prefer_turn_pattern else None
        self.calls = 0

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema: dict) -> dict:
        del system_prompt, schema
        self.calls += 1
        turns = re.findall(r"^\[(TURN_\w+)\|[^\]]*\] (.*)$", user_prompt, re.MULTILINE)
        # Cite the segment's confirming turn when asked (Evidence-Check reads the
        # cited confirm turn verbatim), else its first turn.
        preferred = [tid for tid, text in turns if self._prefer and self._prefer.search(text)]
        return self._build(preferred[0] if preferred else turns[0][0])


def _override_downstream_llm_adapters():
    content_llm = _CitingLLM(
        lambda turn_id: {
            "speakers": [
                {
                    "full_name": "Nguyễn Cường",
                    "points": [
                        {
                            "evidence_turn_ids": [turn_id],
                            "text": "Trình bày tờ trình.",
                        }
                    ],
                }
            ]
        }
    )
    action_llm = _CitingLLM(
        lambda turn_id: {
            "action_items": [
                {
                    "evidence_turn_ids": [turn_id],
                    "confirm_turn_id": turn_id,
                    "status": "assigned",
                    "actor": "Nguyễn Cường",
                    "text": "Hoàn thiện tờ trình.",
                    "deadline": None,
                }
            ],
        },
        prefer_turn_pattern=_CONFIRMING_TURN_PATTERN,
    )
    decision_llm = _CitingLLM(
        lambda turn_id: {
            "decisions": [
                {
                    "evidence_turn_ids": [turn_id],
                    "confirm_turn_id": turn_id,
                    "status": "agreed",
                    "text": "Chốt phương án.",
                }
            ]
        },
        prefer_turn_pattern=_CONFIRMING_TURN_PATTERN,
    )
    # Actor is resolved and grounded, both candidates self-report a confirmed
    # status with a valid confirm turn, and nothing is hedged, so Evidence-Check
    # marks both CLEAR: debate_judge_llm must never be called.
    debate_judge_llm = _UnusedLLM()
    return content_llm, action_llm, decision_llm, debate_judge_llm


def test_analyze_meeting_end_to_end_with_fake_adapters() -> None:
    app.dependency_overrides[get_embedding_adapter] = _FakeEmbeddingAdapter
    app.dependency_overrides[get_topic_label_adapter] = _FakeTopicLabelAdapter
    app.dependency_overrides[get_downstream_llm_adapters] = _override_downstream_llm_adapters
    try:
        client = TestClient(app)
        payload = json.loads(_SAMPLE_TRANSCRIPT.read_text(encoding="utf-8"))

        response = client.post("/meetings/analyze", json=payload)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["meeting_id"] == payload["meeting_id"]
        assert body["revision_id"] == payload["revision_id"]
        assert len(body["topics"]) >= 1
        first_topic = body["topics"][0]
        assert first_topic["title"].startswith("Chủ đề đoạn")
        assert first_topic["speakers"][0]["full_name"] == "Nguyễn Cường"
        assert len(body["verified_decisions"]) == 1
        assert body["verified_decisions"][0]["text"] == "Chốt phương án."
        assert len(body["verified_assignments"]) == 1
        assert body["verified_assignments"][0]["actor"] == "Nguyễn Cường"
        assert body["verified_assignments"][0]["text"] == "Hoàn thiện tờ trình."
        assert len(body["turns"]) >= 1
        first_turn = body["turns"][0]
        assert set(first_turn) == {"turn_id", "speaker", "text"}
        assert body["failed_topics"] == []
    finally:
        app.dependency_overrides.clear()


def test_analyze_meeting_accepts_stt_export_payload_without_meeting_id() -> None:
    """Regression test: a raw STT-export item list (``segment``/
    ``speaker_name`` fields, e.g. the real shape of
    ``inputs/recording_old.json``) has no top-level ``meeting_id``/
    ``revision_id`` at all -- ``parse_transcript_payload`` is explicitly
    written to fall back to defaults for exactly this shape
    (``_is_stt_export``), but ``AnalyzeRequest`` briefly required both
    fields unconditionally and rejected this exact payload with a 422
    before ``parse_transcript_payload`` ever ran. Must keep working."""

    app.dependency_overrides[get_embedding_adapter] = _FakeEmbeddingAdapter
    app.dependency_overrides[get_topic_label_adapter] = _FakeTopicLabelAdapter
    # The fixture's fake actor is not in this one-line STT transcript, so
    # Evidence-Check (correctly) sends it to Debate+Judge; this test is only
    # about payload acceptance, so a judge that drops it is enough.
    app.dependency_overrides[get_downstream_llm_adapters] = lambda: (
        *_override_downstream_llm_adapters()[:3],
        _DroppingJudgeLLM(),
    )
    try:
        client = TestClient(app)
        payload = {
            "items": [
                {
                    "id": 3,
                    "segment": "Với cả anh Việt thì sang tuần này sẽ",
                    "speaker_id": "7eeb6971-97a2-46fb-983f-53ac7753a5c2",
                    "speaker_name": "Phạm Hồng Sơn",
                    "start_time": 5.80221875,
                    "end_time": 8.77221875,
                    "ref_id": ["dd99e490-7385-4bbf-ba75-26859c7280e9"],
                }
            ]
        }

        response = client.post("/meetings/analyze", json=payload)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["meeting_id"] == "stt-export"
        assert body["revision_id"] == "export-0"
    finally:
        app.dependency_overrides.clear()


def test_health() -> None:
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}


def _analyze_with_failing_downstream_llm(*, timed_out: bool):
    class _Failing:
        def generate_json(self, *, system_prompt: str, user_prompt: str, schema: dict) -> dict:
            raise LLMUpstreamError("gateway down", timed_out=timed_out)

    # Agents and stage 7 now degrade on an LLM outage, so the embedding step
    # (used by TreeSeg, no fallback) is where an upstream failure must surface
    # as 502/504 instead of a 422.
    class _FailingEmbedding:
        def embed(self, text: str):
            raise LLMUpstreamError("embedding gateway down", timed_out=timed_out)

    app.dependency_overrides[get_embedding_adapter] = _FailingEmbedding
    app.dependency_overrides[get_topic_label_adapter] = _FakeTopicLabelAdapter
    app.dependency_overrides[get_downstream_llm_adapters] = lambda: (_Failing(),) * 4
    try:
        payload = json.loads(_SAMPLE_TRANSCRIPT.read_text(encoding="utf-8"))
        return TestClient(app).post("/meetings/analyze", json=payload)
    finally:
        app.dependency_overrides.clear()


def test_upstream_llm_timeout_is_504_not_422() -> None:
    response = _analyze_with_failing_downstream_llm(timed_out=True)
    assert response.status_code == 504, response.text


def test_upstream_llm_failure_is_502_not_422() -> None:
    response = _analyze_with_failing_downstream_llm(timed_out=False)
    assert response.status_code == 502, response.text
