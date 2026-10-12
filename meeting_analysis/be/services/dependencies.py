"""Các hàm cung cấp dependency cho FastAPI: embedding, bộ cắt chủ đề, analyzer và cache v3."""

from __future__ import annotations

import os
import threading
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

from fastapi import HTTPException, Request

from src.utils.ports import EmbeddingAdapter


def build_embedding_adapter() -> EmbeddingAdapter:
    """Dựng adapter embedding theo cấu hình môi trường (gọi một lần lúc khởi động).

    Import trì hoãn để không bắt buộc cài thư viện của backend embedding không dùng.

    Đầu ra: EmbeddingAdapter.
    """

    from src.utils.embedding_backend import build_embedding_adapter as build

    return build()


def get_embedding_adapter(request: Request) -> EmbeddingAdapter:
    """Lấy adapter embedding dùng chung đã dựng lúc khởi động (``app.state``).

    Đầu vào: request - request hiện tại của FastAPI.
    Đầu ra: EmbeddingAdapter dùng chung cho mọi request.
    """

    return request.app.state.embedding_adapter


def build_topic_segmenter():
    """Dựng bộ cắt chủ đề theo biến môi trường (gọi một lần lúc khởi động).

    ``TOPIC_SEGMENTER``:
        - ``dialstart`` (mặc định) nạp checkpoint DialSTART;
        - ``treeseg`` trả về None để pipeline dùng TreeSeg + adapter embedding.
    ``DIALSTART_CHECKPOINT`` ghi đè đường dẫn checkpoint (mặc định
    ``experiments/dialstart/model_vn3/best.pt``). Import trì hoãn để không bắt buộc cài
    torch/transformers khi dùng TreeSeg.

    Đầu ra: ``DialStartSegmenter`` hoặc None.
    """

    choice = os.environ.get("TOPIC_SEGMENTER", "dialstart").strip().lower()
    if choice == "treeseg":
        return None
    if choice != "dialstart":
        raise ValueError(f"TOPIC_SEGMENTER không hợp lệ: {choice!r} (dialstart | treeseg)")

    from experiments.dialstart import DEFAULT_CHECKPOINT_PATH, DialStartSegmenter

    return DialStartSegmenter(os.environ.get("DIALSTART_CHECKPOINT") or DEFAULT_CHECKPOINT_PATH)


def get_topic_segmenter(request: Request):
    """Lấy bộ cắt chủ đề dùng chung đã dựng lúc khởi động (``app.state``).

    Đầu vào: request - request hiện tại của FastAPI.
    Đầu ra: ``DialStartSegmenter``, hoặc None (dùng TreeSeg) nếu chưa dựng.
    """

    return getattr(request.app.state, "topic_segmenter", None)


def get_analyzer_v3(request: Request):
    """Analyzer v3 dùng chung của ứng dụng, dựng lười ở request v3 đầu tiên.

    Dùng chung (không tạo mỗi request) vì checkpointer của nó giữ các luồng đang chờ
    người duyệt giữa request ``analyze`` và request ``review``. Test ghi đè dependency
    này bằng analyzer dùng LLM giả.

    Đầu vào: request - lấy ``app.state``.
    Đầu ra: ``MeetingAnalyzerV3``.
    """

    from services.pipeline_v3 import build_analyzer_v3

    state = request.app.state
    with _ANALYZER_V3_LOCK:
        if getattr(state, "analyzer_v3", None) is None:
            state.analyzer_v3 = build_analyzer_v3()
    return state.analyzer_v3


def get_analysis_cache_v3(request: Request):
    """Cache kết quả v3 dùng chung của ứng dụng, dựng lười ở request v3 đầu tiên.

    Dùng chung để mọi request thấy cùng chỗ chạy-một-lần và version (xem
    ``services/analysis_cache.py``). Test ghi đè dependency này bằng cache trong bộ nhớ hoặc
    Redis giả. Dựng lỗi (vd. Redis chưa chạy) thì trả 503 và request sau thử dựng lại.

    Đầu vào: request - lấy ``app.state``.
    Đầu ra: ``AnalysisCache``.
    Lỗi HTTP: 503 nếu không dùng được nơi lưu cache.
    """

    from services.analysis_cache import CacheUnavailableError
    from services.pipeline_v3 import build_analysis_cache_v3

    state = request.app.state
    with _ANALYSIS_CACHE_V3_LOCK:
        if getattr(state, "analysis_cache_v3", None) is None:
            try:
                state.analysis_cache_v3 = build_analysis_cache_v3()
            except CacheUnavailableError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
    return state.analysis_cache_v3


_ANALYZER_V3_LOCK = threading.Lock()
_ANALYSIS_CACHE_V3_LOCK = threading.Lock()
