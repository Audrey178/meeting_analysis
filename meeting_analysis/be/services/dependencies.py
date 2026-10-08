"""Các hàm cung cấp adapter (dependency) cho FastAPI: embedding, gán nhãn chủ đề và LLM."""

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
_DIALSTART_DIR = _REPO_ROOT / "experiments" / "006_dialstart"
_DIALTREESEG_DIR = _REPO_ROOT / "experiments" / "007_dialtreeseg"
for _dir in (_BE_DIR, _TREESEG_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from fastapi import Request

from src.stages.stage07_topic_labeling import StructuredLLMTopicLabeler
from src.utils.ports import EmbeddingAdapter, LLMAdapter, TopicLabelAdapter


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
        - ``dialtreeseg`` bọc DialSTART (điểm khe, depth) trong ``DialTreeSegSegmenter``, ghép với
          cây TreeSeg trên adapter embedding của backend; phương pháp và tham số lấy từ
          ``experiments/007_dialtreeseg/config.json``;
        - ``treeseg`` trả về None để pipeline dùng TreeSeg + adapter embedding.
    ``DIALSTART_CHECKPOINT`` ghi đè đường dẫn checkpoint (mặc định
    ``experiments/006_dialstart/model_vn3/best.pt``). Import trì hoãn để không bắt buộc cài
    torch/transformers khi dùng TreeSeg.

    Đầu ra: ``DialStartSegmenter``, ``DialTreeSegSegmenter`` hoặc None.
    """

    choice = os.environ.get("TOPIC_SEGMENTER", "dialstart").strip().lower()
    if choice == "treeseg":
        return None
    if choice not in ("dialstart", "dialtreeseg"):
        raise ValueError(
            f"TOPIC_SEGMENTER không hợp lệ: {choice!r} (dialstart | dialtreeseg | treeseg)"
        )

    for _dir in (_DIALSTART_DIR, _DIALTREESEG_DIR):
        if str(_dir) not in sys.path:
            sys.path.insert(0, str(_dir))
    from dialstart_segmenter import DEFAULT_CHECKPOINT_PATH, DialStartSegmenter

    dialstart = DialStartSegmenter(os.environ.get("DIALSTART_CHECKPOINT") or DEFAULT_CHECKPOINT_PATH)
    if choice == "dialstart":
        return dialstart

    from dialtreeseg_segmenter import DialTreeSegSegmenter

    return DialTreeSegSegmenter(dialstart)


def get_topic_segmenter(request: Request):
    """Lấy bộ cắt chủ đề dùng chung đã dựng lúc khởi động (``app.state``).

    Đầu vào: request - request hiện tại của FastAPI.
    Đầu ra: ``DialStartSegmenter`` / ``DialTreeSegSegmenter``, hoặc None (dùng TreeSeg) nếu chưa dựng.
    """

    return getattr(request.app.state, "topic_segmenter", None)


def get_topic_label_adapter() -> TopicLabelAdapter:
    """Dựng bộ gán nhãn chủ đề dùng LLM cho một request (tạo mới mỗi request).

    Đầu ra: ``StructuredLLMTopicLabeler`` bọc một ``OpenAIChatJSONAdapter``.
    """

    from src.utils.openai_adapters import OpenAIChatJSONAdapter

    llm = OpenAIChatJSONAdapter()
    return StructuredLLMTopicLabeler(llm, model_name=getattr(llm, "model_name", "openai"))


def get_downstream_llm_adapters() -> tuple[LLMAdapter, LLMAdapter, LLMAdapter, LLMAdapter]:
    """Dựng LLM cho bốn agent phía sau (Content, Action, Decision, Debate+Judge).

    Hiện cả bốn dùng CHUNG một instance (tạo mới mỗi request), tức là chấp nhận đánh đổi
    nêu ở docstring ``build_graph`` (không tách model trích xuất khỏi model kiểm chứng).

    Đầu ra: tuple bốn LLMAdapter theo thứ tự (content, action, decision, debate_judge).
    """

    from src.utils.openai_adapters import OpenAIChatJSONAdapter

    llm = OpenAIChatJSONAdapter()
    return llm, llm, llm, llm


def get_mrg_llm():
    """LLM cho MA-MRG (gateway OpenAI-compatible + cache đĩa); test ghi đè bằng ScriptedLLM.

    Đầu ra: ``mrg.llm.cache.CachedLLM``.
    """

    from services.mrg import build_mrg_llm

    return build_mrg_llm()


def get_mrg_job_store(request: Request):
    """Kho job MA-MRG dùng chung (dựng lúc khởi động, ``app.state.mrg_jobs``)."""

    return request.app.state.mrg_jobs


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


_ANALYZER_V3_LOCK = threading.Lock()
