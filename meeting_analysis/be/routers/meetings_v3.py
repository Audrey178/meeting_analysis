"""Endpoint của pipeline v3 (``services/pipeline_v3.py``); kết quả được cache theo nội dung request.

    POST /v3/meetings/tasks[?refresh=true&refresh_base=true]      -> TasksDocument: việc giao mới +
                                                                     tiến độ việc cũ (``tasks``)
    POST /v3/meetings/decisions[?...]                             -> DecisionsDocument: kết luận
    POST /v3/meetings/content[?...]                               -> ContentDocument: diễn biến
    GET  /v3/meetings/analyses/{analysis_key}/{document_key}      -> document đã cache, không tính gì

    Ba POST dùng chung nền cắt chủ đề + nhãn của cùng transcript; mỗi document được cache riêng
    và chỉ tính khi chưa có. ``refresh`` tính lại document đó trên nền đã có; ``refresh_base`` tính
    lại cả nền (document khác trên nền cũ được tính lại khi được yêu cầu).
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

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Path as PathParam
from pydantic import Field

from schemas import AnalyzeV3Request
from services.analysis_cache import ANALYSIS_KEY_PATTERN, AnalysisCache, CacheUnavailableError
from services.dependencies import (
    get_analysis_cache_v3,
    get_analyzer_v3,
    get_embedding_adapter,
    get_topic_segmenter,
)
from services.documents import ContentDocument, DecisionsDocument, TasksDocument
from services.pipeline_v3 import (
    DOCUMENT_KEY_PATTERN,
    AnalysisConflictError,
    DocumentKind,
    PartReloadFailedError,
    load_cached_document_v3,
    run_meeting_document_v3,
)
from src.utils.ports import EmbeddingAdapter, LLMUpstreamError

router = APIRouter(prefix="/v3/meetings", tags=["meetings-v3"])

MeetingDocumentOut = Annotated[TasksDocument | DecisionsDocument | ContentDocument, Field(discriminator="document_type")]


def _http_errors(compute: Callable[[], dict]) -> dict:
    """Chạy ``compute`` và đổi lỗi của pipeline thành mã HTTP.

    Lỗi HTTP: 504/502 nếu LLM lỗi (502 cả khi chạy lại một document mà có chủ đề lỗi, bản cũ
    được giữ), 503 nếu không dùng được cache (Redis), 409 nếu bản phân tích đang được chạy lại
    toàn bộ, 422 nếu transcript/danh sách không hợp lệ.
    """

    try:
        return compute()
    except LLMUpstreamError as exc:
        raise HTTPException(status_code=504 if exc.timed_out else 502, detail=str(exc)) from exc
    except PartReloadFailedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except CacheUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AnalysisConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _document_endpoint(document: DocumentKind, response_model: type, summary: str):
    """Tạo endpoint ``POST /v3/meetings/{document}`` trả một document."""

    def endpoint(
        request: AnalyzeV3Request,
        refresh: bool = False,
        refresh_base: bool = False,
        analyzer=Depends(get_analyzer_v3),
        embedding_adapter: EmbeddingAdapter = Depends(get_embedding_adapter),
        topic_segmenter=Depends(get_topic_segmenter),
        cache: AnalysisCache = Depends(get_analysis_cache_v3),
    ) -> dict:
        return _http_errors(
            lambda: run_meeting_document_v3(
                request.model_dump(),
                document,
                analyzer=analyzer,
                embedding_adapter=embedding_adapter,
                topic_segmenter=topic_segmenter,
                cache=cache,
                refresh=refresh,
                refresh_base=refresh_base,
            )
        )

    endpoint.__name__ = f"analyze_meeting_{document}_v3"
    endpoint.__doc__ = (
        f"{summary}\n\nĐầu vào: request - transcript (+ người chủ trì, danh sách tham dự, danh sách việc, "
        "nguồn); refresh - tính lại document này; refresh_base - tính lại cả cắt chủ đề + nhãn."
    )
    router.post(f"/{document}", response_model=response_model)(endpoint)


_document_endpoint("tasks", TasksDocument, "Việc giao mới và tiến độ việc cũ (``tasks`` của request).")
_document_endpoint("decisions", DecisionsDocument, "Kết luận cuộc họp kèm thông tin biên bản.")
_document_endpoint("content", ContentDocument, "Diễn biến cuộc họp theo chủ đề.")


@router.get("/analyses/{analysis_key}/{document_key}", response_model=MeetingDocumentOut)
def get_meeting_document_v3(
    analysis_key: str = PathParam(pattern=ANALYSIS_KEY_PATTERN),
    document_key: str = PathParam(pattern=DOCUMENT_KEY_PATTERN),
    cache: AnalysisCache = Depends(get_analysis_cache_v3),
) -> dict:
    """Document đã cache (``extensions.input_fingerprint``/``extensions.document_key`` của response
    trước), không gọi LLM.

    Lỗi HTTP: 404 nếu cache không còn (hết hạn, đổi mã nguồn/model, hoặc nền đã được tính lại);
        503 nếu không dùng được cache (Redis).
    """

    document = _http_errors(lambda: load_cached_document_v3(analysis_key, document_key, cache))
    if document is None:
        raise HTTPException(status_code=404, detail="Không còn kết quả đã lưu cho document này; hãy chạy lại.")
    return document
