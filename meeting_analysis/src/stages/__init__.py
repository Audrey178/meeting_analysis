"""Các stage xác định (deterministic) tích hợp sẵn, mỗi module là một stage.

Backend (``be/services/segmentation.py``, ``be/services/pipeline_v3.py``) dùng:
    stage01 -> stage02 -> stage03 -> cắt chủ đề (DialSTART | TreeSeg) -> stage07

Module không phải stage: ``_shared`` chứa hàm dùng chung cho nhiều stage.
"""

from __future__ import annotations

from ._shared import LexicalCosineSimilarity
from .stage01_effective_transcript import resolve_effective_transcript
from .stage02_evidence import build_evidence_items
from .stage03_speaker_turns import build_speaker_turns
from .stage07_topic_labeling import StructuredLLMTopicLabeler, label_topics

__all__ = [
    "LexicalCosineSimilarity",
    "StructuredLLMTopicLabeler",
    "build_evidence_items",
    "build_speaker_turns",
    "label_topics",
    "resolve_effective_transcript",
]
