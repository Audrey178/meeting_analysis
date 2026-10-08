"""Các stage xác định (deterministic) tích hợp sẵn, mỗi module là một stage.

Đường chạy chính hiện tại (backend, ``be/services/pipeline.py``) chỉ dùng:
    stage01 -> stage02 -> stage03 -> TreeSeg -> stage07
Các tên này được import sẵn (eager) ngay khi import package.

Nhánh atoms (stage04, stage05, stage06, stage08 và ``segmentation``) hiện KHÔNG nằm trên
đường chạy chính; chỉ ``scripts/run_to_stage8.py``, cờ ``--atoms`` của
``scripts/run_to_TreeSeg.py``, ``eval/`` và ``experiments/`` còn dùng. Các tên của nhánh này
được nạp TRỄ (lazy): chỉ nạp module tương ứng khi có người truy cập tên đó. Nhờ vậy import một
stage của đường chính không kéo theo hàng nghìn dòng code không dùng, và lỗi trong nhánh cũ
không làm hỏng việc khởi động backend.

Ba module không phải stage: ``_shared`` và ``_speech_acts`` chứa hàm dùng chung cho nhiều
stage, ``review_markers`` chứa các phép chiếu phục vụ kiểm toán của cả lần chạy.
"""

from __future__ import annotations

import importlib
from typing import Any

from ._shared import LexicalCosineSimilarity
from .review_markers import (
    evidence_integrity_review_markers,
    model_stage_review_markers,
)
from .stage01_effective_transcript import resolve_effective_transcript
from .stage02_evidence import build_evidence_items
from .stage03_speaker_turns import build_speaker_turns
from .stage07_topic_labeling import StructuredLLMTopicLabeler, label_topics

# Tên công khai của nhánh atoms -> (module, tên thật trong module đó). Nạp trễ, xem ``__getattr__``.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "build_analysis_atoms": (".stage04_analysis_atoms", "build_analysis_atoms"),
    "build_atom_features": (".stage05_atom_features", "build_atom_features"),
    "build_full_lexical_weights": (".stage05_atom_features", "build_full_lexical_weights"),
    "extract_entities": (".stage05_atom_features", "extract_entities"),
    "HybridBM25CosineScorer": (".stage06_modes", "HybridBM25CosineScorer"),
    "segment_topics": (".stage06_topic_segmentation", "segment_topics"),
    "hybrid_segment": (".segmentation", "segment"),
    "StructuredLLMTopicRecurrenceChecker": (".stage08_topic_recurrence", "StructuredLLMTopicRecurrenceChecker"),
    "resolve_topic_recurrence": (".stage08_topic_recurrence", "resolve_topic_recurrence"),
}


def __getattr__(name: str) -> Any:
    """Nạp trễ các tên của nhánh atoms (PEP 562): chỉ import module khi tên được truy cập.

    Đầu vào: name - tên thuộc tính được truy cập trên package ``src.stages``.
    Đầu ra: đối tượng tương ứng; kết quả được lưu vào namespace nên các lần sau không vào lại hàm này.
    Lỗi: AttributeError nếu ``name`` không phải tên nạp trễ (hành vi chuẩn của Python).
    """

    try:
        module_name, attribute = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(importlib.import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Liệt kê cả tên nạp trễ để ``dir()``/tự hoàn thành thấy đầy đủ."""

    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = [
    # Đường chạy chính (import sẵn)
    "LexicalCosineSimilarity",
    "StructuredLLMTopicLabeler",
    "build_evidence_items",
    "build_speaker_turns",
    "evidence_integrity_review_markers",
    "label_topics",
    "model_stage_review_markers",
    "resolve_effective_transcript",
    # Nhánh atoms (nạp trễ)
    *_LAZY_EXPORTS,
]
