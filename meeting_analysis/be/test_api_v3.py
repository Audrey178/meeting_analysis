"""Wiring test cho endpoint v3 (``routers/meetings_v3.py``): transcript mẫu đi qua stage01-03
-> TreeSeg -> ``MeetingAnalyzerV3`` -> HTTP, mọi adapter là đồ giả (không gọi mạng).

Kiểm luồng không có candidate nghi ngờ, và luồng Verifier gửi feedback -> agent trích xuất
sửa -> Verifier đồng ý, tất cả trong MỘT request.
"""

from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from main import app
from services.dependencies import get_analyzer_v3, get_embedding_adapter
from src.agentic_v3 import MeetingAnalyzerV3, V3Config
from test_api import (
    _CONFIRMING_TURN_PATTERN,
    _SAMPLE_TRANSCRIPT,
    _FakeEmbeddingAdapter,
    _FakeTopicLabelAdapter,
)


class _RoleLLM:
    """LLM giả cho cả bốn vai trò, nhận vai qua khoá đầu tiên của schema.

    Đầu vào khi tạo: action_status - status agent Action tự khai ("assigned" -> CLEAR,
        "proposed" -> UNCERTAIN, đi Verifier). Verifier lần đầu chưa kết luận, agent trích
        xuất sửa actor theo feedback, Verifier lần sau giữ.
    """

    def __init__(self, action_status: str = "assigned") -> None:
        self.action_status = action_status
        self.verifier_calls = 0

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema: dict) -> dict:
        role = next(iter(schema["properties"]))
        turns = re.findall(r"^\[(TURN_\w+)\|[^\]]*\] (.*)$", user_prompt, re.MULTILINE)
        confirming = [tid for tid, text in turns if re.search(_CONFIRMING_TURN_PATTERN, text)]
        turn_id = (confirming or [tid for tid, _ in turns] or [None])[0]
        if role == "speakers":
            return {"speakers": [{"full_name": "Nguyễn Cường", "points": [{"evidence_turn_ids": [turn_id], "text": "Trình bày tờ trình."}]}]}
        if role == "action_items":
            return {"action_items": [{
                "evidence_turn_ids": [turn_id], "confirm_turn_id": turn_id, "status": self.action_status,
                "actor": "Nguyễn Cường", "text": "Hoàn thiện tờ trình.", "deadline": None,
            }]}
        if role == "decisions":
            return {"decisions": [{"evidence_turn_ids": [turn_id], "confirm_turn_id": turn_id, "status": "agreed", "text": "Chốt phương án."}]}
        if role == "stance":
            return {"stance": "amend", "argument": "sửa theo feedback", "confirm_turn_id": turn_id,
                    "revised_text": None, "revised_actor": "Phòng Tổng hợp"}
        self.verifier_calls += 1
        verdict = "unresolved" if self.verifier_calls == 1 else "keep"
        return {"thought": "", "action": "final", "argument": None, "verdict": verdict,
                "deciding_turn_id": turn_id, "revised_actor": None, "reasoning": "chưa rõ người nhận"}


def _client_with(llm: _RoleLLM) -> TestClient:
    analyzer = MeetingAnalyzerV3(
        content_llm=llm, action_llm=llm, decision_llm=llm, verifier_llm=llm,
        labeler=_FakeTopicLabelAdapter(), config=V3Config(skip_agents_without_cues=False),
    )
    app.dependency_overrides[get_embedding_adapter] = _FakeEmbeddingAdapter
    app.dependency_overrides[get_analyzer_v3] = lambda: analyzer
    return TestClient(app)


def _payload() -> dict:
    return json.loads(_SAMPLE_TRANSCRIPT.read_text(encoding="utf-8"))


def test_v3_analyze_without_uncertain_candidates() -> None:
    try:
        client = _client_with(_RoleLLM(action_status="assigned"))
        payload = {**_payload(), "meeting_date": "2026-10-08"}

        response = client.post("/v3/meetings/analyze", json=payload)

        assert response.status_code == 200, response.text
        result = response.json()
        assert result["meeting_id"] == payload["meeting_id"]
        assert result["revision_id"] == payload["revision_id"]
        assert result["topics"][0]["title"].startswith("Chủ đề đoạn")
        assert [a["actor"] for a in result["verified_assignments"]] == ["Nguyễn Cường"]
        (assignment,) = result["verified_assignments"]
        assert (assignment["deadline_raw"], assignment["deadline_date"], assignment["deadline_kind"]) == (
            None, None, "unknown",
        )
        assert [d["text"] for d in result["verified_decisions"]] == ["Chốt phương án."]
        assert result["failed_topics"] == []
    finally:
        app.dependency_overrides.clear()


def test_v3_verifier_feedback_reaches_consensus() -> None:
    try:
        client = _client_with(_RoleLLM(action_status="proposed"))

        response = client.post("/v3/meetings/analyze", json=_payload())

        assert response.status_code == 200, response.text
        result = response.json()
        (assignment,) = result["verified_assignments"]
        assert assignment["actor"] == "Phòng Tổng hợp"
        assert assignment["verification"] == "consensus"
        (record,) = result["verification_records"]
        assert record["decided_by"] == "consensus"
        assert [(r["verdict"], r["stance"]) for r in record["rounds"]] == [("unresolved", "amend"), ("keep", "")]
        assert client.get("/v3/meetings/threads/x/review").status_code == 404
    finally:
        app.dependency_overrides.clear()
