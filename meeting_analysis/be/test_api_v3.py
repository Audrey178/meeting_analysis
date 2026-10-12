"""Wiring test cho endpoint v3 (``routers/meetings_v3.py``): transcript mẫu đi qua stage01-03
-> TreeSeg -> ``MeetingAnalyzerV3`` -> HTTP, mọi adapter là đồ giả (không gọi mạng).

Kiểm hình dạng ba document (Giao việc kèm tiến độ việc cũ, Kết luận kèm thông tin biên bản,
Diễn biến kèm lượt nói; trích dẫn bằng mã item gốc), luồng Verifier gửi feedback -> agent trích
xuất sửa -> Verifier đồng ý trong MỘT request, danh sách tham dự/danh sách việc (tên gọi tắt quy
về đúng đơn vị; sai dạng thì 422), và cache: ba document dùng chung một nền, khoá của document
chỉ theo trường nó phụ thuộc, tính lại riêng một document trên cùng chủ đề và nhãn, tính lại lỗi
thì giữ bản cũ, request trùng chờ chung một lần tính."""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from services.analysis_cache import AnalysisCache, InMemoryAnalysisStore, LocalAnalysisBackend
from services.dependencies import get_analysis_cache_v3, get_analyzer_v3, get_embedding_adapter
from src.agentic_v3 import MeetingAnalyzerV3
from src.utils.contracts import TopicLabel
from src.utils.ports import LLMUpstreamError

_SAMPLE_TRANSCRIPT = Path(__file__).resolve().parent.parent / "inputs" / "sample_transcript.json"

# Lượt nói có từ giao/chốt trong transcript mẫu (vd. "...chủ trì hoàn thiện
# báo cáo... trước ngày 30 tháng 9...").
_CONFIRMING_TURN_PATTERN = r"trước ngày|thống nhất|giao"


class _FakeEmbeddingAdapter:
    """Embedding giả, tất định theo nội dung, không gọi mạng. Transcript mẫu quá ngắn để
    TreeSeg tách (dưới ngưỡng ``2*min_size`` lượt) nên luôn ra đúng một chủ đề: test này kiểm
    nối dây HTTP, không kiểm chất lượng phân cụm."""

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
        if role == "discussion_points":
            return {"discussion_points": [{"evidence_segment_ids": [turn_id], "text": "Trình bày tờ trình."}]}
        if role == "action_items":
            return {"action_items": [{
                "evidence_segment_ids": [turn_id], "confirm_turn_id": turn_id, "status": self.action_status,
                "actor": self.actor, "text": "Hoàn thiện tờ trình.", "deadline": None, "task_id": self.task_id,
            }]}
        if role == "updates":
            return {"updates": [{
                "task_id": "T1", "status": "returned", "status_turn_id": turn_id, "evidence_segment_ids": [turn_id],
                "deadline": None, "deadline_date": None, "deadline_kind": "unknown", "deadline_removed": True,
                "summary": "Tờ trình phải làm lại.", "blockers": [], "directive": "Chuẩn bị lại tờ trình.",
            }]}
        if role == "decisions":
            return {"decisions": [{"evidence_segment_ids": [turn_id], "confirm_turn_id": turn_id, "status": "agreed", "text": "Chốt phương án."}]}
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


def test_health() -> None:
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_v3_accepts_stt_export_payload_without_meeting_id() -> None:
    """Danh sách item xuất thẳng từ STT (trường ``segment``/``speaker_name``, như
    ``inputs/recording_old.json``) không có ``meeting_id``/``revision_id``:
    ``parse_transcript_payload`` tự dùng giá trị mặc định, nên request không được bị 422 vì
    thiếu hai trường này (từng xảy ra khi ``AnalyzeRequest`` bắt buộc chúng)."""

    try:
        client = _client_with(_RoleLLM())
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

        response = client.post("/v3/meetings/content", json=payload)

        assert response.status_code == 200, response.text
        assert response.json()["meeting_id"] == "stt-export"
    finally:
        app.dependency_overrides.clear()


def _analyze_with_failing_embedding(*, timed_out: bool):
    """Gọi ``/v3/meetings/content`` khi embedding (TreeSeg, không có dự phòng) lỗi."""

    class _FailingEmbedding:
        def embed(self, text: str):
            raise LLMUpstreamError("embedding gateway down", timed_out=timed_out)

    try:
        client = _client_with(_RoleLLM())
        app.dependency_overrides[get_embedding_adapter] = _FailingEmbedding
        return client.post("/v3/meetings/content", json=_payload())
    finally:
        app.dependency_overrides.clear()


def test_v3_upstream_timeout_is_504_not_422() -> None:
    response = _analyze_with_failing_embedding(timed_out=True)
    assert response.status_code == 504, response.text


def test_v3_upstream_failure_is_502_not_422() -> None:
    response = _analyze_with_failing_embedding(timed_out=False)
    assert response.status_code == 502, response.text


def _primary_name(task: dict) -> str | None:
    primary = task["extracted"]["assignment"]["primary"] or {}
    return primary.get("unit_name") or primary.get("person_name") or primary.get("name")


def test_v3_tasks_without_uncertain_candidates() -> None:
    try:
        client = _client_with(_RoleLLM(action_status="assigned"))
        payload = {**_payload(), "meeting_date": "2026-10-08"}

        response = client.post("/v3/meetings/tasks", json=payload)

        assert response.status_code == 200, response.text
        document = response.json()
        assert document["meeting_id"] == payload["meeting_id"]
        (task,) = document["data"]["tasks"]
        assert _primary_name(task) == "Nguyễn Cường"
        assert task["extracted"]["due"] is None
        assert (task["extensions"]["verification"], task["extensions"]["relation"]) == ("rule", None)
        assert document["extensions"]["audit"]["verification_records"] == []
    finally:
        app.dependency_overrides.clear()


def test_v3_verifier_feedback_reaches_consensus() -> None:
    try:
        client = _client_with(_RoleLLM(action_status="proposed"))

        response = client.post("/v3/meetings/tasks", json=_payload())

        assert response.status_code == 200, response.text
        document = response.json()
        (task,) = document["data"]["tasks"]
        assert _primary_name(task) == "Phòng Tổng hợp"
        assert task["extensions"]["verification"] == "consensus"
        assert task["extracted"]["detection"]["review_hints"] == ["verifier_consensus"]
        (record,) = document["extensions"]["audit"]["verification_records"]
        assert record["decided_by"] == "consensus"
        assert [(r["verdict"], r["stance"]) for r in record["rounds"]] == [("unresolved", "amend"), ("keep", "")]
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

        response = client.post("/v3/meetings/tasks", json={**_payload(), "attendees": _ATTENDEES})

        assert response.status_code == 200, response.text
        (task,) = response.json()["data"]["tasks"]
        primary = task["extracted"]["assignment"]["primary"]
        assert (primary["target_type"], primary["unit_id"], primary["unit_name"]) == ("unit", "O2", "Đảng ủy UBND Thành phố")
        resolution = primary["extensions"]["resolution"]
        assert (resolution["mention"], resolution["flag"]) == ("Đảng ủy ban", None)
        assert "tên gọi tắt" in resolution["reason"]
    finally:
        app.dependency_overrides.clear()


def test_v3_malformed_attendees_is_rejected() -> None:
    try:
        client = _client_with(_RoleLLM())
        bad = {"organizations": [{"id": "O2", "name": "Đảng ủy UBND Thành phố", "aliases": "Đảng ủy ban"}]}

        for document in ("content", "decisions", "tasks"):
            response = client.post(f"/v3/meetings/{document}", json={**_payload(), "attendees": bad})
            assert response.status_code == 422, document
    finally:
        app.dependency_overrides.clear()


_TASKS = {
    "tasks": [
        {"id": "T1", "title": "Trình Ban Thường vụ tờ trình đề án", "owner": "O2", "due": "2026-01-31",
         "last_status": "in_progress"},
        {"id": "T2", "title": "Lập báo cáo đánh giá môi trường chiến lược", "owner": "P1", "due": "2026-01-10"},
    ]
}


def test_v3_malformed_tasks_is_rejected() -> None:
    try:
        client = _client_with(_RoleLLM())
        bad = {"tasks": [{"id": "T1", "title": "Trình tờ trình", "owner": "O9"}]}

        response = client.post("/v3/meetings/tasks", json={**_payload(), "attendees": _ATTENDEES, "tasks": bad})

        assert response.status_code == 422
        assert "O9" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ----- Ba document: Giao việc, Kết luận, Diễn biến -----

_SOURCE = {"transcript_version_id": "v7", "transcript_uri": "s3://bucket/transcript.json", "document_uris": ["s3://bucket/to-trinh.json"]}


def test_v3_tasks_document_merges_new_tasks_and_backlog_progress() -> None:
    try:
        client = _client_with(_RoleLLM(action_status="assigned", actor="Đảng ủy ban", task_id="T1"))
        payload = {**_payload(), "meeting_date": "2026-01-15", "attendees": _ATTENDEES, "tasks": _TASKS, "source": _SOURCE}

        response = client.post("/v3/meetings/tasks", json=payload)

        assert response.status_code == 200, response.text
        document = response.json()
        assert (document["schema_version"], document["document_type"], document["meeting_id"]) == (
            "1.0", "meeting_tasks", payload["meeting_id"],
        )
        assert (document["artifact_revision"], document["source"]) == (1, _SOURCE)
        generation = document["generation"]
        assert (generation["status"], generation["warnings"]) == ("complete", [])
        assert generation["coverage"] == {"is_complete": True, "processed_segment_count": 6, "total_segment_count": 6}
        extensions = document["extensions"]
        assert extensions["citation_namespace"] == "transcript_item_id"
        assert extensions["task_identity_strategy"] == "confirm_turn_assignee_v1"
        assert extensions["document_key"].startswith("tasks@")

        new, t1, t2 = document["data"]["tasks"]
        # Việc giao mới tiếp nối T1: việc riêng, phụ thuộc T1.
        assert new["task_id"].startswith("task_") and len(new["task_id"]) == len("task_") + 16
        assert new["workflow"]["dependency_task_ids"] == ["T1"]
        assert new["extensions"]["relation"] == "follow_up"
        primary = new["extracted"]["assignment"]["primary"]
        assert (primary["target_type"], primary["unit_id"], primary["unit_name"]) == ("unit", "O2", "Đảng ủy UBND Thành phố")
        assert primary["extensions"]["resolution"]["mention"] == "Đảng ủy ban"
        references = new["extracted"]["references"]
        assert references["segment_ids"] == ["i004"]  # lượt chứa "trước ngày" chỉ có một item
        assert [ref["segment_id"] for ref in references["extensions"]["source_segment_refs"]] == ["i004"]
        assert new["extracted"]["detection"] == {
            "mode": "explicit", "clarity": "clear", "review_hints": [],
            "confidence": {"overall": None, "content": None, "assignment": None, "due": None},
        }
        # Việc cũ: tiến độ nằm trong ``extracted.progress``.
        assert (t1["task_id"], t1["workflow"]["source_presence"], t1["extracted"]["due"]) == ("T1", "present", None)
        progress = t1["extracted"]["progress"]
        assert (progress["previous_status"], progress["status"], progress["deadline_removed"]) == ("in_progress", "returned", True)
        (update,) = progress["updates"]
        assert update["segment_ids"] == ["i004"] and update["turn_ids"] == references["extensions"]["evidence_ids"]
        assert update["deciding"]
        assert t1["extracted"]["assignment"]["primary"]["unit_id"] == "O2"
        assert (t2["task_id"], t2["workflow"]["source_presence"]) == ("T2", "absent")
        assert t2["extracted"]["progress"]["status"] == "not_reported"
        assert set(t2["extracted"]["detection"]["review_hints"]) == {"overdue", "not_reported"}
        assert t2["extracted"]["due"] == {"raw": None, "date": "2026-01-10", "kind": "exact"}
        assert t2["extracted"]["assignment"]["primary"] == {
            "target_type": "person", "person_id": "P1", "person_name": "Nguyễn Cường", "extensions": {"resolution": None},
        }
    finally:
        app.dependency_overrides.clear()


def test_v3_decisions_document_has_minutes_header_and_numbered_items() -> None:
    try:
        client = _client_with(_RoleLLM())
        payload = {**_payload(), "meeting_date": "2026-01-15", "chair": "Phạm An", "attendees": _ATTENDEES}

        response = client.post("/v3/meetings/decisions", json=payload)

        assert response.status_code == 200, response.text
        document = response.json()
        assert document["document_type"] == "meeting_decisions"
        header = document["data"]["header"]
        assert (header["ngay_hop"], header["chu_tri"], header["so_nguoi_tham_gia"]) == ("15/01/2026", "Phạm An", 1)
        assert header["thanh_phan"] == "Nguyễn Cường (Chánh Văn phòng, Đảng ủy UBND Thành phố)"
        (item,) = document["data"]["items"]
        assert (item["so_thu_tu"], item["noi_dung"], item["segment_ids"]) == (1, "Chốt phương án.", ["i004"])
        assert item["original_segment_ids"] == item["segment_ids"]
        assert item["turn_ids"] == [item["extensions"]["confirm_turn_id"]]
        assert item["extensions"]["decision_id"].startswith("decision_")
        assert document["extensions"]["task_identity_strategy"] is None
    finally:
        app.dependency_overrides.clear()


def test_v3_content_document_has_topic_spans_and_transcript_turns() -> None:
    try:
        client = _client_with(_RoleLLM())

        response = client.post("/v3/meetings/content", json=_payload())

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        (topic,) = data["topics"]
        assert (topic["order"], topic["extracted"]["content"]["title"]) == (1, f"Chủ đề đoạn {topic['topic_id']}")
        span = topic["extracted"]["span"]
        assert span["segment_ids"] == ["i001", "i006"]
        assert span["turn_ids"] == [data["turns"][0]["turn_id"], data["turns"][-1]["turn_id"]]
        (point,) = topic["extracted"]["discussion_points"]
        assert (point["point_id"], point["segment_ids"], point["speakers"]) == (
            f"{topic['topic_id']}:1", ["i004"], ["Nguyễn Cường"],
        )
        assert data["turns"][0]["segment_ids"] == ["i001", "i002"]
    finally:
        app.dependency_overrides.clear()


def test_v3_stt_export_cites_original_integer_ids_and_speaker_id() -> None:
    try:
        client = _client_with(_RoleLLM())
        speaker = {"speaker_id": "spk-1", "speaker_name": "Phạm Hồng Sơn"}
        payload = {
            "items": [
                {"id": 7, "segment": "Tôi giao anh Cường hoàn thiện tờ trình.", **speaker},
                {"id": 8, "segment": "Trước ngày 30 nhé.", **speaker},
            ]
        }

        tasks = client.post("/v3/meetings/tasks", json=payload).json()

        (task,) = tasks["data"]["tasks"]
        assert task["extracted"]["references"]["segment_ids"] == [7]  # số, như id gốc của STT
        assert task["extracted"]["assignment"]["assigned_by_speaker_id"] == "spk-1"
    finally:
        app.dependency_overrides.clear()


def test_v3_stt_export_uses_ref_id_as_speaker_id() -> None:
    try:
        client = _client_with(_RoleLLM())
        speaker = {"speaker_name": "Phạm Hồng Sơn", "ref_id": ["spk-ref-1"]}
        payload = {
            "items": [
                {"id": 7, "segment": "Tôi giao anh Cường hoàn thiện tờ trình.", **speaker},
                {"id": 8, "segment": "Trước ngày 30 nhé.", **speaker},
            ]
        }

        tasks = client.post("/v3/meetings/tasks", json=payload).json()
        content = client.post("/v3/meetings/content", json=payload).json()

        (task,) = tasks["data"]["tasks"]
        assert task["extracted"]["assignment"]["assigned_by_speaker_id"] == "spk-ref-1"
        assert {ref["speaker_id"] for ref in task["extensions"]["source_segment_refs"]} == {"spk-ref-1"}
        assert {turn["speaker_id"] for turn in content["data"]["turns"]} == {"spk-ref-1"}
        points = [point for topic in content["data"]["topics"] for point in topic["extracted"]["discussion_points"]]
        assert points and all(point["speaker_ids"] == ["spk-ref-1"] for point in points)
    finally:
        app.dependency_overrides.clear()


# ----- Cache: nền chung, mỗi document một mục -----


def _roles_since(llm: _RoleLLM, calls: int) -> set[str]:
    return set(llm.roles[calls:])


def test_v3_documents_share_one_base_and_are_cached_separately(analysis_cache: AnalysisCache) -> None:
    try:
        llm, labeler = _RoleLLM(), _CountingLabeler()
        client = _client_with(llm, labeler, cache=analysis_cache)
        content = client.post("/v3/meetings/content", json=_payload()).json()
        labels = labeler.calls
        assert _roles_since(llm, 0) == {"discussion_points"}

        calls = len(llm.roles)
        decisions = client.post("/v3/meetings/decisions", json=_payload()).json()

        assert _roles_since(llm, calls) == {"decisions"}
        assert labeler.calls == labels  # nền (chủ đề + nhãn) dùng lại
        assert decisions["extensions"]["input_fingerprint"] == content["extensions"]["input_fingerprint"]
        assert decisions["extensions"]["artifact_version_id"] > content["extensions"]["artifact_version_id"]

        calls = len(llm.roles)
        again = client.post("/v3/meetings/content", json=_payload()).json()
        assert len(llm.roles) == calls
        assert again == content
    finally:
        app.dependency_overrides.clear()


def test_v3_document_key_follows_only_the_inputs_it_depends_on(analysis_cache: AnalysisCache) -> None:
    try:
        llm = _RoleLLM(action_status="assigned", actor="Đảng ủy ban", task_id="T1")
        client = _client_with(llm, cache=analysis_cache)
        payload = {**_payload(), "attendees": _ATTENDEES}
        decisions = client.post("/v3/meetings/decisions", json=payload).json()
        tasks = client.post("/v3/meetings/tasks", json=payload).json()
        calls = len(llm.roles)

        # ``tasks`` và ``source`` không ảnh hưởng Kết luận: dùng lại bản đã có.
        with_tasks = {**payload, "tasks": _TASKS, "source": _SOURCE}
        decisions_again = client.post("/v3/meetings/decisions", json=with_tasks).json()
        assert len(llm.roles) == calls
        assert decisions_again["extensions"]["document_key"] == decisions["extensions"]["document_key"]
        assert decisions_again["source"] == _SOURCE  # response mang nguồn của chính request

        # ``tasks`` đổi thì Giao việc là document khác, tính trên cùng nền.
        tasks_again = client.post("/v3/meetings/tasks", json=with_tasks).json()
        assert _roles_since(llm, calls) == {"action_items", "updates"}
        assert tasks_again["extensions"]["document_key"] != tasks["extensions"]["document_key"]
        assert tasks_again["extensions"]["input_fingerprint"] == tasks["extensions"]["input_fingerprint"]

        # Transcript khác là bản phân tích khác.
        other = client.post("/v3/meetings/decisions", json={**payload, "items": payload["items"][:5]}).json()
        assert other["extensions"]["input_fingerprint"] != decisions["extensions"]["input_fingerprint"]
    finally:
        app.dependency_overrides.clear()


def test_v3_refresh_recomputes_only_that_document_on_same_topics(analysis_cache: AnalysisCache) -> None:
    try:
        llm, labeler = _RoleLLM(), _CountingLabeler()
        client = _client_with(llm, labeler, cache=analysis_cache)
        first = {kind: client.post(f"/v3/meetings/{kind}", json=_payload()).json() for kind in ("content", "tasks", "decisions")}
        calls, labels = len(llm.roles), labeler.calls

        response = client.post("/v3/meetings/decisions?refresh=true", json=_payload())

        assert response.status_code == 200, response.text
        assert _roles_since(llm, calls) == {"decisions"}
        assert labeler.calls == labels  # giữ nguyên chủ đề và nhãn
        refreshed = response.json()
        assert refreshed["artifact_revision"] == 2
        assert refreshed["extensions"]["artifact_version_id"] > first["decisions"]["extensions"]["artifact_version_id"]
        calls = len(llm.roles)
        for kind in ("content", "tasks"):  # document khác lấy từ cache, không đổi
            assert client.post(f"/v3/meetings/{kind}", json=_payload()).json() == first[kind]
        assert len(llm.roles) == calls
    finally:
        app.dependency_overrides.clear()


def test_v3_refresh_base_recomputes_topics_and_retires_other_documents(analysis_cache: AnalysisCache) -> None:
    try:
        llm, labeler = _RoleLLM(), _CountingLabeler()
        client = _client_with(llm, labeler, cache=analysis_cache)
        decisions = client.post("/v3/meetings/decisions", json=_payload()).json()
        client.post("/v3/meetings/content", json=_payload())
        labels = labeler.calls

        client.post("/v3/meetings/content?refresh_base=true", json=_payload())

        assert labeler.calls == 2 * labels
        key, name = decisions["extensions"]["input_fingerprint"], decisions["extensions"]["document_key"]
        assert client.get(f"/v3/meetings/analyses/{key}/{name}").status_code == 404  # tính trên nền cũ
        calls = len(llm.roles)
        recomputed = client.post("/v3/meetings/decisions", json=_payload()).json()
        assert _roles_since(llm, calls) == {"decisions"}
        assert recomputed["artifact_revision"] == 2
    finally:
        app.dependency_overrides.clear()


def test_v3_failed_refresh_keeps_previous_document(analysis_cache: AnalysisCache) -> None:
    try:
        llm = _RoleLLM()
        client = _client_with(llm, cache=analysis_cache)
        first = client.post("/v3/meetings/tasks", json=_payload()).json()

        llm.fail_roles = {"action_items"}
        response = client.post("/v3/meetings/tasks?refresh=true", json=_payload())

        assert response.status_code == 502
        assert "giữ nguyên kết quả trước" in response.json()["detail"]
        key, name = first["extensions"]["input_fingerprint"], first["extensions"]["document_key"]
        cached = client.get(f"/v3/meetings/analyses/{key}/{name}").json()
        assert cached["data"] == first["data"]
        assert cached["artifact_revision"] == 1
    finally:
        app.dependency_overrides.clear()


def test_v3_incomplete_document_is_reported_and_recomputed_next_time(analysis_cache: AnalysisCache) -> None:
    try:
        llm = _RoleLLM()
        llm.fail_roles = {"decisions"}
        client = _client_with(llm, cache=analysis_cache)
        first = client.post("/v3/meetings/decisions", json=_payload()).json()
        generation = first["generation"]
        assert (generation["status"], generation["coverage"]["is_complete"]) == ("partial", False)
        assert generation["coverage"]["processed_segment_count"] == 0
        assert [warning["agent"] for warning in generation["warnings"]] == ["decision_agent"]

        llm.fail_roles = set()
        second = client.post("/v3/meetings/decisions", json=_payload()).json()

        assert (second["generation"]["status"], second["artifact_revision"]) == ("complete", 2)
        assert [item["noi_dung"] for item in second["data"]["items"]] == ["Chốt phương án."]
    finally:
        app.dependency_overrides.clear()


def test_v3_cached_document_lookup(analysis_cache: AnalysisCache) -> None:
    try:
        client = _client_with(_RoleLLM(), cache=analysis_cache)
        first = client.post("/v3/meetings/content", json={**_payload(), "source": _SOURCE}).json()
        key, name = first["extensions"]["input_fingerprint"], first["extensions"]["document_key"]

        cached = client.get(f"/v3/meetings/analyses/{key}/{name}")

        assert cached.status_code == 200
        assert cached.json() == first  # nguồn lưu cùng document
        assert client.get(f"/v3/meetings/analyses/{key}/decisions@{'0' * 16}").status_code == 404
        assert client.get(f"/v3/meetings/analyses/{'0' * 32}/{name}").status_code == 404
        assert client.get(f"/v3/meetings/analyses/{key}/summary@{'0' * 16}").status_code == 422
        assert client.post("/v3/meetings/analyze", json=_payload()).status_code == 404  # endpoint cũ đã bỏ
    finally:
        app.dependency_overrides.clear()


def test_v3_concurrent_refreshes_of_a_document_share_one_computation(analysis_cache: AnalysisCache) -> None:
    try:
        llm = _RoleLLM()
        client = _client_with(llm, cache=analysis_cache)
        client.post("/v3/meetings/decisions", json=_payload())
        per_run = llm.roles.count("decisions")
        llm.delay = 0.3

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda _: TestClient(app).post("/v3/meetings/decisions?refresh=true", json=_payload()), range(2)
                )
            )

        assert [response.status_code for response in responses] == [200, 200]
        assert llm.roles.count("decisions") == 2 * per_run  # một lần tính lại cho cả hai request
        assert {response.json()["artifact_revision"] for response in responses} == {2}
    finally:
        app.dependency_overrides.clear()


def test_v3_refresh_rebuilt_on_new_base_when_topics_are_replaced_midway(analysis_cache: AnalysisCache) -> None:
    try:
        llm = _RoleLLM()
        cache = analysis_cache
        client = _client_with(llm, cache=cache)
        first = client.post("/v3/meetings/decisions", json=_payload()).json()
        key = first["extensions"]["input_fingerprint"]
        replaced = threading.Event()

        def replace_base_once(role: str) -> None:
            # Giả một request "tính lại nền" ghi nền mới đúng lúc Kết luận đang tính lại.
            if role == "decisions" and not replaced.is_set():
                replaced.set()
                cache.save(key, "base", cache.load(key, "base"))

        llm.on_call = replace_base_once
        response = client.post("/v3/meetings/decisions?refresh=true", json=_payload())

        assert response.status_code == 200, response.text
        result = response.json()
        assert replaced.is_set()
        # Kết quả tính trên nền cũ bị bỏ; document được tính lại trên nền mới.
        assert llm.roles.count("decisions") == 3
        name = result["extensions"]["document_key"]
        assert client.get(f"/v3/meetings/analyses/{key}/{name}").json() == result
    finally:
        app.dependency_overrides.clear()
