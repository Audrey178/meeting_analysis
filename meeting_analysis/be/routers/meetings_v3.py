"""Endpoint của pipeline v3 (``services/pipeline_v3.py``); kết quả được cache theo nội dung request.

    POST /v3/meetings/analyze[?refresh=true]   -> AnalyzeV3Result: phần nào đã có trong cache
                                                  thì dùng lại, thiếu mới tính; ``refresh`` tính
                                                  lại tất cả, kể cả cắt chủ đề + nhãn
    POST /v3/meetings/analyze/{part}           -> AnalyzeV3Result sau khi tính lại riêng ``part``
                                                  (development | assignments | decisions |
                                                  progress) trên cùng chủ đề và nhãn
    GET  /v3/meetings/analyses/{analysis_key}  -> AnalyzeV3Result đã cache, không tính gì
                                                  (404 nếu cache không còn đủ)
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
from fastapi import Path as PathParam

from schemas import AnalyzeV3Request, AnalyzeV3Result
from services.analysis_cache import ANALYSIS_KEY_PATTERN, AnalysisCache, CacheUnavailableError
from services.dependencies import (
    get_analysis_cache_v3,
    get_analyzer_v3,
    get_embedding_adapter,
    get_topic_segmenter,
)
from services.pipeline_v3 import (
    AnalysisConflictError,
    PartNotApplicableError,
    PartReloadFailedError,
    load_cached_analysis_v3,
    run_meeting_analysis_v3,
)
from src.agentic_v3 import AnalysisPart
from src.utils.ports import EmbeddingAdapter, LLMUpstreamError

router = APIRouter(prefix="/v3/meetings", tags=["meetings-v3"])


def _run_analysis(request: AnalyzeV3Request, **kwargs) -> dict:
    """Gọi ``run_meeting_analysis_v3`` và đổi lỗi thành mã HTTP.

    Lỗi HTTP: 504/502 nếu LLM lỗi (502 cả khi chạy lại một phần mà có chủ đề lỗi, bản cũ được
    giữ), 503 nếu không dùng được cache (Redis), 409 nếu phần không áp dụng hoặc bản phân tích
    đang được chạy lại toàn bộ, 422 nếu transcript/danh sách không hợp lệ.
    """

    try:
        return run_meeting_analysis_v3(request.model_dump(), **kwargs)
    except LLMUpstreamError as exc:
        raise HTTPException(status_code=504 if exc.timed_out else 502, detail=str(exc)) from exc
    except PartReloadFailedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except CacheUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (PartNotApplicableError, AnalysisConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/analyze", response_model=AnalyzeV3Result)
def analyze_meeting_v3(
    request: AnalyzeV3Request,
    refresh: bool = False,
    analyzer=Depends(get_analyzer_v3),
    embedding_adapter: EmbeddingAdapter = Depends(get_embedding_adapter),
    topic_segmenter=Depends(get_topic_segmenter),
    cache: AnalysisCache = Depends(get_analysis_cache_v3),
) -> dict:
    """Phân tích một cuộc họp bằng v3 (mọi chủ đề song song), dùng lại phần đã cache.

    Đầu vào: request - transcript (+ người chủ trì, danh sách tham dự, danh sách việc nếu có);
        refresh - tính lại tất cả, bỏ qua cache; các adapter và cache được tiêm qua ``Depends``.
    Đầu ra: ``AnalyzeV3Result``.
    """

    return _run_analysis(
        request,
        analyzer=analyzer,
        embedding_adapter=embedding_adapter,
        topic_segmenter=topic_segmenter,
        cache=cache,
        refresh=refresh,
    )


@router.post("/analyze/{part}", response_model=AnalyzeV3Result)
def reload_meeting_part_v3(
    part: AnalysisPart,
    request: AnalyzeV3Request,
    analyzer=Depends(get_analyzer_v3),
    embedding_adapter: EmbeddingAdapter = Depends(get_embedding_adapter),
    topic_segmenter=Depends(get_topic_segmenter),
    cache: AnalysisCache = Depends(get_analysis_cache_v3),
) -> dict:
    """Tính lại riêng phần ``part`` (cùng chủ đề và nhãn), các phần khác lấy từ cache.

    Request phải là đúng payload đã phân tích; khác payload là một bản phân tích khác (tính mọi
    phần còn thiếu, như ``/analyze``).

    Đầu vào: part - development | assignments | decisions | progress; request - như ``/analyze``.
    Đầu ra: ``AnalyzeV3Result`` đủ mọi phần.
    """

    return _run_analysis(
        request,
        analyzer=analyzer,
        embedding_adapter=embedding_adapter,
        topic_segmenter=topic_segmenter,
        cache=cache,
        reload_part=part,
    )


@router.get("/analyses/{analysis_key}", response_model=AnalyzeV3Result)
def get_meeting_analysis_v3(
    analysis_key: str = PathParam(pattern=ANALYSIS_KEY_PATTERN),
    cache: AnalysisCache = Depends(get_analysis_cache_v3),
) -> dict:
    """Kết quả đã cache của một bản phân tích (dùng khi trang web tải lại), không gọi LLM.

    Đầu vào: analysis_key - ``AnalyzeV3Result.analysis_key`` của một response trước.
    Đầu ra: ``AnalyzeV3Result``.
    Lỗi HTTP: 404 nếu cache không còn đủ mọi phần (hết hạn, đổi mã nguồn/model, hoặc chưa chạy
        xong); 503 nếu không dùng được cache (Redis).
    """

    try:
        result = load_cached_analysis_v3(analysis_key, cache)
    except CacheUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Không còn kết quả đã lưu cho bản phân tích này; hãy chạy lại.")
    return result
