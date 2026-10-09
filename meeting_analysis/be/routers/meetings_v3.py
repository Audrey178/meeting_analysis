"""Endpoint của pipeline v3 (``services/pipeline_v3.py``).

    POST /v3/meetings/analyze  -> AnalyzeV3Result (chạy một mạch, không có bước duyệt người)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Thiết lập sys.path viết trực tiếp tại đây; lý do không đưa vào module dùng chung xem
# khối tương tự trong main.py.
_BE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BE_DIR.parent
_TREESEG_DIR = _REPO_ROOT / "experiments" / "treeseg_turn_level"
for _dir in (_BE_DIR, _TREESEG_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from fastapi import APIRouter, Depends, HTTPException

from schemas import AnalyzeV3Request, AnalyzeV3Result
from services.dependencies import get_analyzer_v3, get_embedding_adapter, get_topic_segmenter
from services.pipeline_v3 import start_meeting_analysis_v3
from src.utils.ports import EmbeddingAdapter, LLMUpstreamError

router = APIRouter(prefix="/v3/meetings", tags=["meetings-v3"])


@router.post("/analyze", response_model=AnalyzeV3Result)
def analyze_meeting_v3(
    request: AnalyzeV3Request,
    analyzer=Depends(get_analyzer_v3),
    embedding_adapter: EmbeddingAdapter = Depends(get_embedding_adapter),
    topic_segmenter=Depends(get_topic_segmenter),
) -> dict:
    """Phân tích một cuộc họp bằng v3 (mọi chủ đề song song).

    Đầu vào: request - transcript (+ người chủ trì nếu có); các adapter được tiêm qua ``Depends``.
    Đầu ra: ``AnalyzeV3Result``.
    Lỗi HTTP: 504/502 nếu bước embedding lỗi LLM, 422 nếu transcript không hợp lệ.
    """

    try:
        return start_meeting_analysis_v3(
            request.model_dump(),
            analyzer=analyzer,
            embedding_adapter=embedding_adapter,
            topic_segmenter=topic_segmenter,
        )
    except LLMUpstreamError as exc:
        raise HTTPException(status_code=504 if exc.timed_out else 502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
