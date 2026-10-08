"""Wiring test cho API MA-MRG (routers/mrg.py + services/mrg.py): transcript thật -> stage01-03 -> TreeSeg ->
stage07 -> MA-MRG (4 role agent, Stage 2–4) -> job -> JSON, mọi LLM/embedding đều giả (không gọi mạng)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app
from services.dependencies import (
    get_embedding_adapter,
    get_mrg_job_store,
    get_mrg_llm,
    get_topic_label_adapter,
)
from services.mrg import MrgJobStore
from test_api import _FakeEmbeddingAdapter, _FakeTopicLabelAdapter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "agentic_v2"))
from mrg.llm.cache import CachedLLM  # noqa: E402
from mrg.llm.client import ScriptedLLM  # noqa: E402

_SAMPLE = Path(__file__).resolve().parent.parent / "inputs" / "sample_transcript.json"
_SEG = "TOPIC_SEG_000000"
_REQUEST = ("Tôi giao Sở Giao thông chủ trì hoàn thiện báo cáo đánh giá tác động môi trường trước ngày 30 tháng 9 "
            "năm 2026")
_SCRIPT = {
    f"stage1.task:{_SEG}": {"tasks": [{"ref": "t1", "label": "Hoàn thiện báo cáo ĐTM"}], "acts": [
        {"id": "a1", "act_type": "REQUEST", "turn_id": "TURN_000005", "quote": _REQUEST, "speaker": "Phạm An",
         "task_ref": "t1", "slots": {"task_text": "Hoàn thiện báo cáo đánh giá tác động môi trường",
                                     "deadline_raw": "trước ngày 30 tháng 9 năm 2026", "directive": True,
                                     "addressees": [{"mention": "Sở Giao thông", "person": "Sở Giao thông",
                                                     "role": "lead"}]}}]},
    "stage1.deliberation:*": {"issues": [{"ref": "i1", "label": "Huy động vốn tư nhân"}], "constraints": [], "acts": [
        {"id": "p1", "act_type": "PROPOSE", "turn_id": "TURN_000004", "issue_ref": "i1",
         "quote": "Tôi đề nghị bổ sung phương án huy động vốn tư nhân", "slots": {"option_text": "Huy động vốn tư nhân"}}]},
    "stage1.participant:*": {"persons": [], "speakers": [], "mentions": [], "turn_flags": []},
    "stage1.discourse:*": {"pairs": [], "threads": []},
    "stage2.exchange:*": {"messages": []},
    "realizer.dien_bien:*": {"narrative": "Thành viên trao đổi."},
    "realizer.thong_bao:*": {"text": "THÔNG BÁO KẾT LUẬN"},
}


@pytest.fixture
def client(tmp_path):
    store = MrgJobStore()
    llm = CachedLLM(ScriptedLLM(_SCRIPT), "fake", tmp_path / "cache", tmp_path / "log.jsonl")
    app.dependency_overrides[get_embedding_adapter] = _FakeEmbeddingAdapter
    app.dependency_overrides[get_topic_label_adapter] = _FakeTopicLabelAdapter
    app.dependency_overrides[get_mrg_llm] = lambda: llm
    app.dependency_overrides[get_mrg_job_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _wait(client: TestClient, job_id: str, timeout_s: float = 30) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = client.get(f"/meetings/mrg/jobs/{job_id}").json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError("job không xong kịp")


def test_mrg_job_end_to_end(client) -> None:
    payload = json.loads(_SAMPLE.read_text(encoding="utf-8"))
    created = client.post("/meetings/mrg/jobs", json={**payload, "meeting_date": "2026-09-21", "chair": "Phạm An"})
    assert created.status_code == 202, created.text
    assert created.json()["status"] in ("queued", "running")      # executor có thể đã nhận job

    body = _wait(client, created.json()["job_id"])
    assert body["status"] == "succeeded", body["error"]
    result = body["result"]
    assert result["meeting_id"] == payload["meeting_id"] and result["meeting_date"] == "2026-09-21"
    assert [t["turn_id"] for t in result["turns"]][:2] == ["TURN_000001", "TURN_000002"]
    assert result["segments"][0]["title"].startswith("Chủ đề đoạn")

    person = next(p for p in result["giao_viec"]["people"] if p["person"] == "Sở Giao thông")
    task = person["tasks"][0]
    assert (task["assignment_status"], task["assigned_by"], task["deadline_norm"]) == \
        ("unconfirmed", "Phạm An", "2026-09-30")
    assert task["fold_trace"]["assignee"][0]["turn_id"] == "TURN_000005"
    assert result["ket_luan"]["open"][0]["alternatives"] == [] and result["thong_bao"] == "THÔNG BÁO KẾT LUẬN"
    assert result["report"]["consistency_violations"] == []
    assert body["stage"] == "done" and body["progress"]["segments"] == 1


def test_mrg_job_requires_meeting_date(client) -> None:
    payload = json.loads(_SAMPLE.read_text(encoding="utf-8"))
    assert client.post("/meetings/mrg/jobs", json=payload).status_code == 422


def test_mrg_job_rejects_unreadable_transcript_early(client) -> None:
    response = client.post("/meetings/mrg/jobs", json={"items": [{"foo": 1}], "meeting_date": "2026-09-21"})
    assert response.status_code == 422


def test_unknown_job_is_404(client) -> None:
    assert client.get("/meetings/mrg/jobs/khongco").status_code == 404


def test_failed_job_reports_error(client, tmp_path) -> None:
    class Boom:
        def complete_json(self, *args, **kwargs):
            raise RuntimeError("gateway sập")

    app.dependency_overrides[get_mrg_llm] = lambda: CachedLLM(Boom(), "x", tmp_path / "c2", tmp_path / "l2")
    payload = json.loads(_SAMPLE.read_text(encoding="utf-8"))
    created = client.post("/meetings/mrg/jobs", json={**payload, "meeting_date": "2026-09-21"})
    body = _wait(client, created.json()["job_id"])
    assert body["status"] == "failed" and "gateway sập" in body["error"]
