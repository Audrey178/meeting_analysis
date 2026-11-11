"""Bước 3: dùng mô hình ngôn ngữ đặt tên ngắn cho từng đoạn chủ đề."""

from __future__ import annotations

from .topic_labeling import StructuredLLMTopicLabeler, label_topics

__all__ = [
    "StructuredLLMTopicLabeler",
    "label_topics",
]
