"""Pipeline MA-MRG (``src/agentic_v2``) phơi qua API dưới dạng job chạy nền có tiến độ.

    transcript ──prepare_meeting──> lượt nói + đoạn chủ đề + nhãn  (dùng chung với pipeline cũ)
               ──build_meeting_input──> MeetingInput (SPEC MA-MRG mục 3)
               ──MeetingPipeline.run──> Giao việc / Kết luận / Diễn biến / Thông báo + report (có fold_trace)

MA-MRG gọi LLM nhiều lần (4 role agent × số đoạn, tối đa 3 vòng trao đổi, Reviewer, realizer), thường mất
vài phút, nên API không chạy đồng bộ: ``POST`` tạo job, ``GET`` hỏi trạng thái + tiến độ theo stage.
Job lưu trong bộ nhớ tiến trình (mất khi khởi động lại) — đủ cho một máy chủ đơn; triển khai nhiều worker
cần chuyển sang hàng đợi ngoài.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Thiết lập sys.path viết trực tiếp tại đây; lý do xem khối tương tự trong main.py.
_BE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BE_DIR.parent
_AGENTIC_V2_DIR = _REPO_ROOT / "src" / "agentic_v2"
for _dir in (_BE_DIR, _REPO_ROOT, _AGENTIC_V2_DIR):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from mrg.llm.cache import CachedLLM  # noqa: E402
from mrg.pipeline import MeetingPipeline, PipelineConfig  # noqa: E402
from mrg.state0.context import InputSegment, InputTurn, MeetingInput, MeetingMeta  # noqa: E402

from services.pipeline import PreparedMeeting, prepare_meeting  # noqa: E402

logger = logging.getLogger(__name__)

STAGE_LABELS = {
    "queued": "Đang chờ",
    "prepare": "Dựng lượt nói, cắt và gán nhãn chủ đề",
    "stage1": "Stage 1 — 4 role agent trích Act",
    "stage2": "Stage 2 — trao đổi giữa các agent",
    "stage3": "Stage 3 — Reviewer phân xử",
    "stage4": "Stage 4 — fold và chiếu 3 output",
    "done": "Hoàn tất",
}


# ----- Dữ liệu vào MA-MRG -----

def _segment_turn_ids(segment, turns: tuple) -> list[str]:
    """turn_id của một đoạn: ``atom_ids`` (bộ cắt chạy trên lượt nói) hoặc khoảng chỉ số ``start_ms:end_ms``."""
    known = {turn.turn_id for turn in turns}
    if segment.atom_ids and all(atom in known for atom in segment.atom_ids):
        return list(segment.atom_ids)
    if segment.start_ms is not None and segment.end_ms is not None:
        return [turn.turn_id for turn in turns[segment.start_ms:segment.end_ms]]
    raise ValueError(f"Không xác định được lượt nói của đoạn {segment.segment_id}")


def build_meeting_input(prepared: PreparedMeeting, meeting_date: str, chair: str | None = None,
                        participants: list[str] | None = None) -> MeetingInput:
    """
    Chức năng: ghép kết quả ``prepare_meeting`` thành hợp đồng đầu vào của MA-MRG (SPEC mục 3).
    Đầu vào: prepared; meeting_date "YYYY-MM-DD" (bắt buộc cho chuẩn hóa hạn); chair; participants
             (rỗng = lấy các người nói ASR).
    Đầu ra: MeetingInput (input_validator của MA-MRG kiểm M0 khi chạy).
    """
    turns = [InputTurn(turn_id=turn.turn_id, order=index, speaker_asr=turn.speaker, text=turn.text_exact,
                       t_start=turn.start_ms / 1000 if turn.start_ms is not None else None,
                       t_end=turn.end_ms / 1000 if turn.end_ms is not None else None)
             for index, turn in enumerate(prepared.turns, start=1)]
    segments = [InputSegment(segment_id=segment.segment_id, turn_ids=_segment_turn_ids(segment, prepared.turns))
                for segment in prepared.segments]
    labels = [{"segment_id": sid, "title": label.title or "", "summary": label.summary or ""}
              for sid, label in prepared.labels_by_segment.items() if label is not None]
    meta = MeetingMeta(meeting_id=prepared.meeting_id, meeting_date=meeting_date, chair=chair or None,
                       participants=list(participants or []))
    return MeetingInput(meeting_meta=meta, turns=turns, segments=segments, topic_labels=labels)


def serialize_result(prepared: PreparedMeeting, state: dict) -> dict:
    """
    Chức năng: state cuối của MeetingPipeline -> JSON cho API (theo ``MrgResult`` trong schemas.py).
    Đầu vào: prepared; state.
    Đầu ra: dict gồm transcript (kèm segment_id, merged_suspect), mục lục đoạn, 3 output, thông báo, cảnh báo, report.
    """
    context = state["context"]
    store = state["stage2"].store
    return {
        "meeting_id": prepared.meeting_id,
        "revision_id": prepared.revision_id,
        "meeting_date": context.meta.get("meeting_date"),
        "chair": context.meta.get("chair"),
        "turns": [{"turn_id": tid, "speaker": turn.speaker, "text": turn.text, "segment_id": turn.segment_id,
                   "merged_suspect": store.turns.get(tid, turn).merged_suspect}
                  for tid, turn in ((tid, context.turns[tid]) for tid in context.turn_order)],
        "segments": [{"segment_id": seg.segment_id, "order": seg.order, "title": seg.title, "summary": seg.summary}
                     for seg in context.segments.values()],
        "giao_viec": state["outputs"]["giao_viec"],
        "ket_luan": state["outputs"]["ket_luan"],
        "dien_bien": state["outputs"]["dien_bien"],
        "thong_bao": state["outputs"].get("thong_bao"),
        "warnings": state["warnings"],
        "report": state["report"],
    }


# ----- Job -----

@dataclass
class MrgJob:
    """Một lần chạy MA-MRG: trạng thái, stage hiện tại, tiến độ, lỗi, kết quả."""

    job_id: str
    status: str = "queued"                  # queued | running | succeeded | failed
    stage: str = "queued"
    progress: dict = field(default_factory=dict)
    error: str | None = None
    result: dict | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    def snapshot(self, include_result: bool = True) -> dict:
        now = self.finished_at or time.time()
        return {
            "job_id": self.job_id, "status": self.status, "stage": self.stage,
            "stage_label": STAGE_LABELS.get(self.stage, self.stage), "progress": dict(self.progress),
            "error": self.error, "elapsed_s": round(now - (self.started_at or self.created_at), 1),
            "result": self.result if include_result else None,
        }


class MrgJobStore:
    """
    Chức năng: kho job trong bộ nhớ + executor chạy nền (mặc định 1 job một lúc để không dồn tải gateway LLM).
    Đầu vào (khởi tạo): max_workers; max_jobs — số job giữ lại (cũ nhất bị xóa).
    Đầu ra: submit(fn) -> job; get(job_id).
    """

    def __init__(self, max_workers: int = 1, max_jobs: int = 50):
        self._jobs: dict[str, MrgJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mrg-job")
        self._max_jobs = max_jobs

    def get(self, job_id: str) -> MrgJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: MrgJob, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(job, key, value)

    def submit(self, work) -> MrgJob:
        """
        Chức năng: tạo job và chạy ``work(job, store)`` trong nền; ngoại lệ được ghi vào job (không làm sập server).
        Đầu vào: work — hàm nhận (job, store) và trả kết quả dict.
        Đầu ra: job vừa tạo (trạng thái queued).
        """
        job = MrgJob(job_id=uuid.uuid4().hex[:12])
        with self._lock:
            self._jobs[job.job_id] = job
            while len(self._jobs) > self._max_jobs:
                self._jobs.pop(next(iter(self._jobs)))

        def run() -> None:
            self.update(job, status="running", started_at=time.time())
            try:
                result = work(job, self)
                self.update(job, status="succeeded", stage="done", result=result, finished_at=time.time())
            except Exception as exc:                        # noqa: BLE001 — mọi lỗi phải về trạng thái job
                logger.error("MA-MRG job %s lỗi: %s\n%s", job.job_id, exc, traceback.format_exc())
                self.update(job, status="failed", error=f"{type(exc).__name__}: {exc}", finished_at=time.time())

        self._executor.submit(run)
        return job


def run_mrg_analysis(job: MrgJob, store: MrgJobStore, *, payload: dict, meeting_date: str, chair: str | None,
                     participants: list[str] | None, config: PipelineConfig, llm: CachedLLM,
                     embedding_adapter, topic_label_adapter, topic_segmenter) -> dict:
    """
    Chức năng: thân một job MA-MRG: prepare_meeting -> MeetingInput -> MeetingPipeline (báo tiến độ) -> JSON.
    Đầu vào: job, store; payload transcript; meeting_date; chair; participants; config; llm; các adapter dựng sẵn.
    Đầu ra: dict theo ``MrgResult``.
    """
    store.update(job, stage="prepare", progress={})
    prepared = prepare_meeting(payload, embedding_adapter=embedding_adapter,
                               topic_label_adapter=topic_label_adapter, topic_segmenter=topic_segmenter)
    store.update(job, progress={"turns": len(prepared.turns), "segments": len(prepared.segments)})
    meeting = build_meeting_input(prepared, meeting_date, chair, participants)

    def on_progress(stage: str, info: dict) -> None:
        store.update(job, stage=stage, progress={"turns": len(prepared.turns),
                                                 "segments": len(prepared.segments), **info})

    pipeline = MeetingPipeline(llm, config, progress=on_progress)
    state = pipeline.run(meeting)
    return serialize_result(prepared, state)


def build_mrg_llm() -> CachedLLM:
    """
    Chức năng: LLM cho MA-MRG — gateway OpenAI-compatible (MODEL_NAME, OPENAI_BASE_URL, OPENAI_API_KEY) bọc cache
               đĩa theo nội dung (chạy lại cùng transcript không tốn lời gọi). ``MRG_CACHE_DIR`` ghi đè thư mục cache.
    Đầu ra: CachedLLM.
    """
    from mrg.llm.client import OpenAIChatBackend

    backend = OpenAIChatBackend()
    cache_dir = Path(os.environ.get("MRG_CACHE_DIR") or _REPO_ROOT / "outputs" / "mrg_cache")
    return CachedLLM(backend, backend.model, cache_dir / "llm", cache_dir / "llm_calls.jsonl")
