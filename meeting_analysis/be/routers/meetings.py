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

from schemas import AnalyzeRequest, AnalyzeResponse
from services.dependencies import (
    get_downstream_llm_adapters,
    get_embedding_adapter,
    get_topic_label_adapter,
    get_topic_segmenter,
)
from services.pipeline import run_meeting_analysis_pipeline
from src.utils.ports import EmbeddingAdapter, LLMAdapter, LLMUpstreamError, TopicLabelAdapter

router = APIRouter()


@router.post("/meetings/analyze", response_model=AnalyzeResponse)
def analyze_meeting(
    request: AnalyzeRequest,
    embedding_adapter: EmbeddingAdapter = Depends(get_embedding_adapter),
    topic_label_adapter: TopicLabelAdapter = Depends(get_topic_label_adapter),
    downstream_llm_adapters: tuple[LLMAdapter, LLMAdapter, LLMAdapter, LLMAdapter] = Depends(
        get_downstream_llm_adapters
    ),
    topic_segmenter=Depends(get_topic_segmenter),
) -> dict:
    """Endpoint phân tích một cuộc họp: nhận transcript, trả về chủ đề, phân công và kết luận.

    Đầu vào:
        request: transcript cuộc họp (``AnalyzeRequest``).
        embedding_adapter, topic_label_adapter, downstream_llm_adapters, topic_segmenter:
            các adapter được FastAPI tiêm vào qua ``Depends`` (``topic_segmenter`` None thì
            pipeline cắt chủ đề bằng TreeSeg).

    Đầu ra: dict theo ``AnalyzeResponse``.

    Lỗi HTTP: 504 nếu LLM hết thời gian chờ, 502 nếu LLM lỗi khác, 422 nếu transcript
    không hợp lệ (``ValueError``).
    """

    try:
        return run_meeting_analysis_pipeline(
            request.model_dump(),
            embedding_adapter=embedding_adapter,
            topic_label_adapter=topic_label_adapter,
            downstream_llm_adapters=downstream_llm_adapters,
            topic_segmenter=topic_segmenter,
        )
    except LLMUpstreamError as exc:
        raise HTTPException(status_code=504 if exc.timed_out else 502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
