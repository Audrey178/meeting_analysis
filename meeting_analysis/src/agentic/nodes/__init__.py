"""Mỗi module là một node (hoặc hàm tạo node) của graph -- cách nối xem ``..graph``.

Không có node "assemble báo cáo" nào ở đây -- ``MeetingState`` sau khi
``graph.invoke()`` xong CHÍNH LÀ kết quả cuối (``meeting_development``/
``verified_assignments``/``verified_decisions``), xem ``..state`` và "M6"
trong ``be/DESIGN.md``.
"""

from .action_agent import make_action_agent
from .content_agent import make_content_agent
from .debate_judge_agent import make_debate_and_judge_agent
from .decision_agent import make_decision_agent
from .evidence_check import check_topic_evidence

__all__ = [
    "make_content_agent",
    "make_action_agent",
    "make_decision_agent",
    "check_topic_evidence",
    "make_debate_and_judge_agent",
]
