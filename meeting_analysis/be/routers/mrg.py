"""API MA-MRG (``src/agentic_v2``): tạo job chạy nền và hỏi trạng thái / kết quả.

    POST /meetings/mrg/jobs        -> 202 {job_id, status, ...}   (422 nếu transcript không đọc được)
    GET  /meetings/mrg/jobs/{id}   -> trạng thái, stage, tiến độ; ``result`` khi xong
"""

from __future__ import annotations

import sys
from pathlib import Path

# Thiết lập sys.path viết trực tiếp tại đây; lý do xem khối tương tự trong main.py.
_BE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BE_DIR.parent
_TREESEG_DIR = _REPO_ROOT / "experiments" / "treeseg_turn_level"
for _dir in (_BE_DIR, _TREESEG_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from fastapi import APIRouter, Depends, HTTPException

from schemas import MrgJobRequest, MrgJobStatus
from services.dependencies import (
    get_embedding_adapter,
    get_mrg_job_store,
    get_mrg_llm,
    get_topic_label_adapter,
    get_topic_segmenter,
)
from services.mrg import MrgJobStore, run_mrg_analysis
from src.utils.adapters import parse_transcript_payload

router = APIRouter(prefix="/meetings/mrg")


@router.post("/jobs", response_model=MrgJobStatus, status_code=202)
def create_mrg_job(
    request: MrgJobRequest,
    store: MrgJobStore = Depends(get_mrg_job_store),
    llm=Depends(get_mrg_llm),
    embedding_adapter=Depends(get_embedding_adapter),
    topic_label_adapter=Depends(get_topic_label_adapter),
    topic_segmenter=Depends(get_topic_segmenter),
) -> dict:
    """Tạo job MA-MRG; transcript được đọc thử ngay để báo 422 sớm thay vì để job thất bại sau.

    Đầu vào: ``MrgJobRequest``; các adapter dựng sẵn được tiêm qua ``Depends`` và chuyển nguyên cho job.
    Đầu ra: ``MrgJobStatus`` (status "queued").
    """

    from mrg.pipeline import PipelineConfig

    payload = request.model_dump(include={"meeting_id", "revision_id", "items"})
    try:
        parse_transcript_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    options = request.options
    config = PipelineConfig(exchange=options.exchange, reviewer=options.reviewer, realizer_llm=options.realizer,
                            acceptance_policy=options.acceptance_policy)
    job = store.submit(lambda job, job_store: run_mrg_analysis(
        job, job_store, payload=payload, meeting_date=request.meeting_date.isoformat(), chair=request.chair,
        participants=request.participants, config=config, llm=llm, embedding_adapter=embedding_adapter,
        topic_label_adapter=topic_label_adapter, topic_segmenter=topic_segmenter))
    return job.snapshot(include_result=False)


@router.get("/jobs/{job_id}", response_model=MrgJobStatus)
def get_mrg_job(job_id: str, store: MrgJobStore = Depends(get_mrg_job_store)) -> dict:
    """Trạng thái một job; 404 nếu không có (job chỉ sống trong bộ nhớ tiến trình)."""

    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Không có job {job_id} (server có thể đã khởi động lại)")
    return job.snapshot()
