"""Endpoint của pipeline v3 (``services/pipeline_v3.py``); kết quả được cache theo nội dung request.

    POST /v3/meetings/tasks[?refresh=true&refresh_base=true]      -> TasksDocument: việc giao mới +
                                                                     tiến độ việc cũ (``tasks``)
    POST /v3/meetings/decisions[?...]                             -> DecisionsDocument: kết luận
    POST /v3/meetings/content[?...]                               -> ContentDocument: diễn biến; sau response
                                                                     tính sẵn tasks + decisions vào cache
    GET  /v3/meetings/tasks|decisions|content/{meeting_id}         -> document theo request ``POST /content``
                                                                     gần nhất của cuộc họp (lấy từ cache)

    Ba POST dùng chung nền cắt chủ đề + nhãn của cùng transcript; mỗi document được cache riêng
    và chỉ tính khi chưa có. ``refresh`` tính lại document đó trên nền đã có; ``refresh_base`` tính
    lại cả nền (document khác trên nền cũ được tính lại khi được yêu cầu).

``POST /content`` là bước đầu của luồng: trả Diễn biến ngay, rồi chạy nền Giao việc + Kết luận
với cùng request và lưu cache, để ``POST /tasks``/``/decisions`` gửi cùng request sau đó lấy từ cache
(tới khi đang tính thì chờ chung lần tính đó). Request sau phải gửi cùng ``chair``/``meeting_date``/
``attendees``/``tasks`` thì mới trùng mục cache (xem ``document_entry_name``). Gọn hơn: ``GET
/tasks|decisions/{meeting_id}`` dùng lại đúng request ``POST /content`` gần nhất của cuộc họp.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Thiết lập sys.path viết trực tiếp tại đây; lý do không đưa vào module dùng chung xem
# khối tương tự trong main.py.
_BE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BE_DIR.parent
for _dir in (_BE_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from schemas import AnalyzeV3Request
from services.analysis_cache import AnalysisCache, CacheUnavailableError
from services.dependencies import (
    get_analysis_cache_v3,
    get_analyzer_v3,
    get_topic_segmenter,
)
from services.documents import ContentDocument, DecisionsDocument, TasksDocument
from services.pipeline_v3 import (
    AnalysisConflictError,
    DocumentKind,
    PartReloadFailedError,
    prefetch_meeting_documents_v3,
    remember_meeting_request_v3,
    run_meeting_document_by_id_v3,
    run_meeting_document_v3,
)

from src.utils.ports import LLMUpstreamError

router = APIRouter(prefix="/v3/meetings", tags=["meetings-v3"])

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


def _document_endpoint(
    document: DocumentKind, response_model: type, summary: str, prefetch: tuple[DocumentKind, ...] = ()
):
    """Tạo endpoint ``POST /v3/meetings/{document}`` trả một document; ``prefetch`` là các document
    được tính sẵn vào cache sau response (chạy nền, lỗi chỉ ghi log), khi đó request cũng được lưu
    làm request gần nhất của cuộc họp (``GET /{document}/{meeting_id}``)."""

    def endpoint(
        request: AnalyzeV3Request,
        background_tasks: BackgroundTasks,
        refresh: bool = False,
        refresh_base: bool = False,
        analyzer=Depends(get_analyzer_v3),
        topic_segmenter=Depends(get_topic_segmenter),
        cache: AnalysisCache = Depends(get_analysis_cache_v3),
    ) -> dict:
        payload = request.model_dump()
        result = _http_errors(
            lambda: run_meeting_document_v3(
                payload,
                document,
                analyzer=analyzer,
                segmenter=topic_segmenter,
                cache=cache,
                refresh=refresh,
                refresh_base=refresh_base,
            )
        )
        if prefetch:
            _http_errors(lambda: remember_meeting_request_v3(result["meeting_id"], payload, cache))
            background_tasks.add_task(
                prefetch_meeting_documents_v3,
                payload,
                prefetch,
                analyzer=analyzer,
                segmenter=topic_segmenter,
                cache=cache,
            )
        return result

    endpoint.__name__ = f"analyze_meeting_{document}_v3"
    endpoint.__doc__ = (
        f"{summary}\n\nĐầu vào: request - transcript (+ người chủ trì, danh sách tham dự, danh sách việc, "
        "nguồn); refresh - tính lại document này; refresh_base - tính lại cả cắt chủ đề + nhãn."
    )
    router.post(f"/{document}", response_model=response_model)(endpoint)


_document_endpoint("tasks", TasksDocument, "Việc giao mới và tiến độ việc cũ (``tasks`` của request).")
_document_endpoint("decisions", DecisionsDocument, "Kết luận cuộc họp.")
_document_endpoint(
    "content",
    ContentDocument,
    "Diễn biến cuộc họp theo chủ đề; sau response tính sẵn Giao việc + Kết luận vào cache.",
    prefetch=("tasks", "decisions"),
)


def _meeting_document_endpoint(document: DocumentKind, response_model: type, summary: str):
    """Tạo endpoint ``GET /v3/meetings/{document}/{meeting_id}``."""

    def endpoint(
        meeting_id: str,
        analyzer=Depends(get_analyzer_v3),
        topic_segmenter=Depends(get_topic_segmenter),
        cache: AnalysisCache = Depends(get_analysis_cache_v3),
    ) -> dict:
        result = _http_errors(
            lambda: run_meeting_document_by_id_v3(
                meeting_id,
                document,
                analyzer=analyzer,
                segmenter=topic_segmenter,
                cache=cache,
            )
        )
        if result is None:
            raise HTTPException(
                status_code=404, detail="Chưa có kết quả của cuộc họp này; hãy gọi POST /v3/meetings/content trước."
            )
        return result

    endpoint.__name__ = f"get_meeting_{document}_by_id_v3"
    endpoint.__doc__ = (
        f"{summary}\n\nTheo request ``POST /v3/meetings/content`` gần nhất của ``meeting_id``: lấy từ cache "
        "(đang tính nền thì chờ; chưa có thì tính).\n\nLỗi HTTP: 404 nếu cuộc họp chưa gọi POST /content "
        "(hoặc đã hết hạn); còn lại như POST."
    )
    router.get(f"/{document}/{{meeting_id}}", response_model=response_model)(endpoint)


_meeting_document_endpoint("tasks", TasksDocument, "Việc giao mới và tiến độ việc cũ của cuộc họp.")
_meeting_document_endpoint("decisions", DecisionsDocument, "Kết luận cuộc họp.")
_meeting_document_endpoint("content", ContentDocument, "Diễn biến cuộc họp theo chủ đề.")
