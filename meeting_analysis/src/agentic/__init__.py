"""Các agent LangGraph phía sau (Content / Action / Decision / Evidence-Check /
Debate+Judge).

Cách điều phối xem ``graph.py``; lịch sử thiết kế xem ``be/DESIGN.md``.
Không có node "assemble báo cáo" nào -- kết quả của ``build_graph(...).invoke(...)``
CHÍNH LÀ ``MeetingState`` cuối cùng, đọc thẳng ``meeting_development``/
``verified_assignments``/``verified_decisions`` (xem "M6" trong ``be/DESIGN.md``).

Cần thư viện ``langgraph``. Package này chỉ import langgraph khi chính nó được
import; ``src/__init__.py`` không import nó, nên phần pipeline xác định (không
LLM) không phụ thuộc cứng vào langgraph.
"""

from ._shared import merge_duplicate_assignments, merge_duplicate_decisions
from .graph import build_graph
from .state import MeetingState
from .schemas import (
    ActionItemCandidate,
    DebateRecord,
    DecisionCandidate,
    SegmentTask,
    SpeakerPoint,
    SpeakerSection,
)

__all__ = [
    "build_graph",
    "merge_duplicate_assignments",
    "merge_duplicate_decisions",
    "MeetingState",
    "DebateRecord",
    "DecisionCandidate",
    "ActionItemCandidate",
    "SegmentTask",
    "SpeakerPoint",
    "SpeakerSection",
]
