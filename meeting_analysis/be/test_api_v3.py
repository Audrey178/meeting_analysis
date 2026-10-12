"""Wiring test cho endpoint v3 (``routers/meetings_v3.py``): transcript mẫu đi qua stage01-03
-> TreeSeg -> ``MeetingAnalyzerV3`` -> HTTP, mọi adapter là đồ giả (không gọi mạng).

Kiểm luồng không có candidate nghi ngờ, luồng Verifier gửi feedback -> agent trích xuất
sửa -> Verifier đồng ý, tất cả trong MỘT request, danh sách tham dự gửi kèm request
(tên gọi tắt của đơn vị quy về đúng đơn vị; danh sách sai dạng thì 422), danh sách việc
cần báo cáo tiến độ (``task_progress``, ``task_id``/``relation`` của việc giao), và cache
kết quả: request lặp lại không gọi LLM, chạy lại riêng một phần trên cùng chủ đề và nhãn,
chạy lại lỗi thì giữ bản cũ, request trùng chờ chung một lần tính.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from main import app
from services.analysis_cache import AnalysisCache, InMemoryAnalysisStore, LocalAnalysisBackend
from services.dependencies import get_analysis_cache_v3, get_analyzer_v3, get_embedding_adapter
from src.agentic_v3 import MeetingAnalyzerV3
from src.utils.ports import LLMUpstreamError
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

    def __init__(self, action_status: str = "assigned", actor: str = "Nguyễn Cường", task_id: str | None = None) -> None:
        self.action_status = action_status
        self.actor = actor
        self.task_id = task_id
        self.verifier_calls = 0
        self.user_prompts: list[str] = []
        self.roles: list[str] = []  # vai của từng lời gọi, theo thứ tự
        self.fail_roles: set[str] = set()  # vai nào raise LLMUpstreamError (giả gateway lỗi)
        self.delay = 0.0  # số giây mỗi lời gọi "chạy"
        self.on_call = None  # hàm gọi trước mỗi lời gọi với vai, để test chen thao tác vào giữa

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema: dict) -> dict:
        # Agent trả lời feedback nhận qua "stance": khoá đầu schema của nó là confirm_turn_id.
        role = "stance" if "stance" in schema["properties"] else next(iter(schema["properties"]))
        self.user_prompts.append(user_prompt)
        self.roles.append(role)
        if self.on_call is not None:
            self.on_call(role)
        time.sleep(self.delay)
        if role in self.fail_roles:
            raise LLMUpstreamError("gateway down")
        turns = re.findall(r"^\[(TURN_\w+)\|[^\]]*\] (.*)$", user_prompt, re.MULTILINE)
        confirming = [tid for tid, text in turns if re.search(_CONFIRMING_TURN_PATTERN, text)]
        turn_id = (confirming or [tid for tid, _ in turns] or [None])[0]
        if role == "speakers":
            return {"speakers": [{"full_name": "Nguyễn Cường", "points": [{"evidence_turn_ids": [turn_id], "text": "Trình bày tờ trình."}]}]}
        if role == "action_items":
            return {"action_items": [{
                "evidence_turn_ids": [turn_id], "confirm_turn_id": turn_id, "status": self.action_status,
                "actor": self.actor, "text": "Hoàn thiện tờ trình.", "deadline": None, "task_id": self.task_id,
            }]}
        if role == "updates":
            return {"updates": [{
                "task_id": "T1", "status": "returned", "status_turn_id": turn_id, "evidence_turn_ids": [turn_id],
                "deadline": None, "deadline_date": None, "deadline_kind": "unknown", "deadline_removed": True,
                "summary": "Tờ trình phải làm lại.", "blockers": [], "directive": "Chuẩn bị lại tờ trình.",
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


class _CountingLabeler(_FakeTopicLabelAdapter):
    """Adapter gán nhãn giả đếm số lần được gọi (gán nhãn chạy song song nên cần khoá)."""

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def label_topic(self, segment, *args, **kwargs):
        with self._lock:
            self.calls += 1
        return super().label_topic(segment, *args, **kwargs)


def _client_with(llm: _RoleLLM, labeler=None, cache: AnalysisCache | None = None) -> TestClient:
    """Client gọi app với LLM/labeler giả; mỗi client một cache trong bộ nhớ (trừ khi truyền vào)."""

    analyzer = MeetingAnalyzerV3(
        content_llm=llm, action_llm=llm, decision_llm=llm, verifier_llm=llm,
        labeler=labeler or _FakeTopicLabelAdapter(),
    )
    cache = cache or AnalysisCache(LocalAnalysisBackend(InMemoryAnalysisStore()))
    app.dependency_overrides[get_embedding_adapter] = _FakeEmbeddingAdapter
    app.dependency_overrides[get_analyzer_v3] = lambda: analyzer
    app.dependency_overrides[get_analysis_cache_v3] = lambda: cache
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


_ATTENDEES = {
    "people": [{"id": "P1", "full_name": "Nguyễn Cường", "position": "Chánh Văn phòng", "org_id": "O2"}],
    "organizations": [
        {"id": "O2", "name": "Đảng ủy UBND Thành phố", "aliases": ["Đảng ủy ban"], "functions": ["xây dựng tờ trình"]},
    ],
}


def test_v3_attendee_alias_resolves_organization_actor() -> None:
    try:
        client = _client_with(_RoleLLM(action_status="assigned", actor="Đảng ủy ban"))

        response = client.post("/v3/meetings/analyze", json={**_payload(), "attendees": _ATTENDEES})

        assert response.status_code == 200, response.text
        (assignment,) = response.json()["verified_assignments"]
        assert (assignment["actor"], assignment["actor_type"], assignment["actor_flag"]) == (
            "Đảng ủy UBND Thành phố", "organization", None,
        )
        (assignee,) = assignment["assignees"]
        assert (assignee["mention"], assignee["ref_id"]) == ("Đảng ủy ban", "O2")
        assert "tên gọi tắt" in assignee["reason"]
    finally:
        app.dependency_overrides.clear()


def test_v3_malformed_attendees_is_rejected() -> None:
    try:
        client = _client_with(_RoleLLM())
        bad = {"organizations": [{"id": "O2", "name": "Đảng ủy UBND Thành phố", "aliases": "Đảng ủy ban"}]}

        response = client.post("/v3/meetings/analyze", json={**_payload(), "attendees": bad})

        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


_TASKS = {
    "tasks": [
        {"id": "T1", "title": "Trình Ban Thường vụ tờ trình đề án", "owner": "O2", "due": "2026-01-31",
         "last_status": "in_progress"},
        {"id": "T2", "title": "Lập báo cáo đánh giá môi trường chiến lược", "owner": "P1", "due": "2026-01-10"},
    ]
}


def test_v3_tasks_produce_progress_and_link_assignments() -> None:
    try:
        client = _client_with(_RoleLLM(action_status="assigned", actor="Đảng ủy ban", task_id="T1"))
        payload = {**_payload(), "meeting_date": "2026-01-15", "attendees": _ATTENDEES, "tasks": _TASKS}

        response = client.post("/v3/meetings/analyze", json=payload)

        assert response.status_code == 200, response.text
        result = response.json()
        t1, t2 = result["task_progress"]
        assert (t1["task_id"], t1["owner"], t1["status"], t1["deadline_removed"]) == (
            "T1", "Đảng ủy UBND Thành phố", "returned", True,
        )
        assert t1["deciding_update"]["verification"] == "unchecked"  # không có Decisions trong test
        assert (t2["status"], t2["overdue"], t2["updates"]) == ("not_reported", True, [])
        (assignment,) = result["verified_assignments"]
        assert (assignment["task_id"], assignment["relation"]) == ("T1", "follow_up")
    finally:
        app.dependency_overrides.clear()


def test_v3_without_tasks_has_no_progress() -> None:
    try:
        client = _client_with(_RoleLLM())

        response = client.post("/v3/meetings/analyze", json=_payload())

        assert response.status_code == 200, response.text
        result = response.json()
        assert result["task_progress"] == []
        assert result["verified_assignments"][0]["relation"] is None
    finally:
        app.dependency_overrides.clear()


def test_v3_malformed_tasks_is_rejected() -> None:
    try:
        client = _client_with(_RoleLLM())
        bad = {"tasks": [{"id": "T1", "title": "Trình tờ trình", "owner": "O9"}]}

        response = client.post("/v3/meetings/analyze", json={**_payload(), "attendees": _ATTENDEES, "tasks": bad})

        assert response.status_code == 422
        assert "O9" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ----- Cache kết quả và chạy lại từng phần -----

_PARTS = {"development", "assignments", "decisions"}


def _without_parts(result: dict) -> dict:
    """Response bỏ ``parts`` (``from_cache`` khác nhau giữa lần tính và lần lấy cache)."""

    return {key: value for key, value in result.items() if key != "parts"}


def test_v3_repeated_request_is_served_from_cache(analysis_cache: AnalysisCache) -> None:
    try:
        llm, labeler = _RoleLLM(), _CountingLabeler()
        client = _client_with(llm, labeler, cache=analysis_cache)
        first = client.post("/v3/meetings/analyze", json=_payload()).json()
        calls, labels = len(llm.roles), labeler.calls

        second = client.post("/v3/meetings/analyze", json=_payload()).json()

        assert (len(llm.roles), labeler.calls) == (calls, labels)  # không gọi LLM thêm lần nào
        assert set(first["parts"]) == _PARTS
        assert not any(meta["from_cache"] for meta in first["parts"].values())
        assert all(meta["from_cache"] for meta in second["parts"].values())
        assert _without_parts(second) == _without_parts(first)
    finally:
        app.dependency_overrides.clear()


def test_v3_reload_part_recomputes_only_that_part_on_same_topics(analysis_cache: AnalysisCache) -> None:
    try:
        llm, labeler = _RoleLLM(), _CountingLabeler()
        client = _client_with(llm, labeler, cache=analysis_cache)
        first = client.post("/v3/meetings/analyze", json=_payload()).json()
        calls, labels = len(llm.roles), labeler.calls

        response = client.post("/v3/meetings/analyze/decisions", json=_payload())

        assert response.status_code == 200, response.text
        reloaded = response.json()
        assert "decisions" in llm.roles[calls:]
        assert not {"speakers", "action_items"} & set(llm.roles[calls:])
        assert labeler.calls == labels  # giữ nguyên chủ đề và nhãn
        assert reloaded["topics"] == first["topics"]
        assert reloaded["verified_assignments"] == first["verified_assignments"]
        assert (reloaded["parts"]["decisions"]["generation"], reloaded["parts"]["decisions"]["from_cache"]) == (2, False)
        assert (reloaded["parts"]["assignments"]["generation"], reloaded["parts"]["assignments"]["from_cache"]) == (1, True)
        assert reloaded["cache_version"] > first["cache_version"]
    finally:
        app.dependency_overrides.clear()


def test_v3_reload_on_empty_cache_computes_every_part_once(analysis_cache: AnalysisCache) -> None:
    try:
        client = _client_with(_RoleLLM(), cache=analysis_cache)

        response = client.post("/v3/meetings/analyze/assignments", json=_payload())

        assert response.status_code == 200, response.text
        result = response.json()
        assert {part: meta["generation"] for part, meta in result["parts"].items()} == dict.fromkeys(_PARTS, 1)
        assert result["topics"] and [a["actor"] for a in result["verified_assignments"]] == ["Nguyễn Cường"]
    finally:
        app.dependency_overrides.clear()


def test_v3_failed_reload_keeps_previous_part(analysis_cache: AnalysisCache) -> None:
    try:
        llm = _RoleLLM()
        client = _client_with(llm, cache=analysis_cache)
        first = client.post("/v3/meetings/analyze", json=_payload()).json()

        llm.fail_roles = {"action_items"}
        response = client.post("/v3/meetings/analyze/assignments", json=_payload())

        assert response.status_code == 502
        assert "giữ nguyên kết quả trước" in response.json()["detail"]
        cached = client.get(f"/v3/meetings/analyses/{first['analysis_key']}").json()
        assert cached["verified_assignments"] == first["verified_assignments"]
        assert cached["parts"]["assignments"]["generation"] == 1
    finally:
        app.dependency_overrides.clear()


def test_v3_incomplete_part_is_recomputed_by_next_analyze(analysis_cache: AnalysisCache) -> None:
    try:
        llm = _RoleLLM()
        llm.fail_roles = {"decisions"}
        client = _client_with(llm, cache=analysis_cache)
        first = client.post("/v3/meetings/analyze", json=_payload()).json()
        assert first["parts"]["decisions"]["status"] == "incomplete"
        assert {failure["agent"] for failure in first["failed_topics"]} == {"decision_agent"}

        llm.fail_roles = set()
        second = client.post("/v3/meetings/analyze", json=_payload()).json()

        decisions = second["parts"]["decisions"]
        assert (decisions["status"], decisions["generation"], decisions["from_cache"]) == ("ok", 2, False)
        assert second["parts"]["assignments"]["from_cache"]
        assert second["failed_topics"] == []
        assert [d["text"] for d in second["verified_decisions"]] == ["Chốt phương án."]
    finally:
        app.dependency_overrides.clear()


def test_v3_refresh_recomputes_topics_and_every_part(analysis_cache: AnalysisCache) -> None:
    try:
        llm, labeler = _RoleLLM(), _CountingLabeler()
        client = _client_with(llm, labeler, cache=analysis_cache)
        first = client.post("/v3/meetings/analyze", json=_payload()).json()
        labels = labeler.calls

        refreshed = client.post("/v3/meetings/analyze?refresh=true", json=_payload()).json()

        assert labeler.calls == 2 * labels
        assert refreshed["analysis_key"] == first["analysis_key"]
        assert {part: meta["generation"] for part, meta in refreshed["parts"].items()} == dict.fromkeys(_PARTS, 2)
    finally:
        app.dependency_overrides.clear()


def test_v3_reload_progress_keeps_assignment_links(analysis_cache: AnalysisCache) -> None:
    try:
        llm = _RoleLLM(action_status="assigned", actor="Đảng ủy ban", task_id="T1")
        client = _client_with(llm, cache=analysis_cache)
        payload = {**_payload(), "meeting_date": "2026-01-15", "attendees": _ATTENDEES, "tasks": _TASKS}
        first = client.post("/v3/meetings/analyze", json=payload).json()
        calls = len(llm.roles)

        reloaded = client.post("/v3/meetings/analyze/progress", json=payload).json()

        assert set(llm.roles[calls:]) == {"updates"}
        assert reloaded["parts"]["progress"]["generation"] == 2
        assert reloaded["task_progress"] == first["task_progress"]
        assert reloaded["verified_assignments"] == first["verified_assignments"]
    finally:
        app.dependency_overrides.clear()


def test_v3_reload_rejects_missing_or_unknown_part(analysis_cache: AnalysisCache) -> None:
    try:
        client = _client_with(_RoleLLM(), cache=analysis_cache)

        assert client.post("/v3/meetings/analyze/progress", json=_payload()).status_code == 409
        assert client.post("/v3/meetings/analyze/summary", json=_payload()).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_v3_cached_analysis_lookup_by_key(analysis_cache: AnalysisCache) -> None:
    try:
        client = _client_with(_RoleLLM(), cache=analysis_cache)
        first = client.post("/v3/meetings/analyze", json=_payload()).json()

        cached = client.get(f"/v3/meetings/analyses/{first['analysis_key']}")

        assert cached.status_code == 200
        assert _without_parts(cached.json()) == _without_parts(first)
        assert client.get(f"/v3/meetings/analyses/{'0' * 32}").status_code == 404
        assert client.get("/v3/meetings/analyses/not-a-key").status_code == 422
        other = client.post("/v3/meetings/analyze", json={**_payload(), "chair": "Nguyễn Cường"}).json()
        assert other["analysis_key"] != first["analysis_key"]
    finally:
        app.dependency_overrides.clear()


def test_v3_concurrent_reloads_of_a_part_share_one_computation(analysis_cache: AnalysisCache) -> None:
    try:
        llm = _RoleLLM()
        client = _client_with(llm, cache=analysis_cache)
        client.post("/v3/meetings/analyze", json=_payload())
        per_run = llm.roles.count("decisions")
        llm.delay = 0.3

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(lambda _: TestClient(app).post("/v3/meetings/analyze/decisions", json=_payload()), range(2))
            )

        assert [response.status_code for response in responses] == [200, 200]
        assert llm.roles.count("decisions") == 2 * per_run  # một lần tính lại cho cả hai request
        assert {response.json()["parts"]["decisions"]["generation"] for response in responses} == {2}
    finally:
        app.dependency_overrides.clear()


def test_v3_reload_rebuilt_on_new_base_when_topics_are_replaced_midway(analysis_cache: AnalysisCache) -> None:
    try:
        llm = _RoleLLM()
        cache = analysis_cache
        client = _client_with(llm, cache=cache)
        first = client.post("/v3/meetings/analyze", json=_payload()).json()
        key = first["analysis_key"]
        replaced = threading.Event()

        def replace_base_once(role: str) -> None:
            # Giả một request "chạy lại toàn bộ" ghi nền mới đúng lúc phần Kết luận đang tính lại.
            if role == "decisions" and not replaced.is_set():
                replaced.set()
                cache.save(key, "base", cache.load(key, "base"))

        llm.on_call = replace_base_once
        response = client.post("/v3/meetings/analyze/decisions", json=_payload())

        assert response.status_code == 200, response.text
        result = response.json()
        assert replaced.is_set()
        # Kết quả tính trên nền cũ bị bỏ; mọi phần được tính lại trên nền mới.
        assert {part: meta["from_cache"] for part, meta in result["parts"].items()} == dict.fromkeys(_PARTS, False)
        assert _without_parts(client.get(f"/v3/meetings/analyses/{key}").json()) == _without_parts(result)
    finally:
        app.dependency_overrides.clear()
