"""Pipeline agentic v3: mọi chủ đề chạy song song (subgraph + ``Send``), Planner bỏ agent
không cần thiết, Verifier ReAct thay Debate+Judge và gửi feedback lại cho agent trích
xuất tới khi đồng thuận (không có bước duyệt người).

Hình dạng graph xem ``graph.py``/``topic_graph.py``; điểm vào cho tầng dịch vụ là
``MeetingAnalyzerV3`` (``runner.py``). Package dùng lại các agent trích xuất, rubric và
luật của ``src.agentic`` (v1), không sửa gì ở đó.
"""

from .config import V3Config
from .graph.meeting import build_graph_v3
from .nodes.planner import build_speaker_registry, plan_meeting, plan_topic
from .runner import MeetingAnalyzerV3
from .schemas import (
    ConsensusRound,
    MeetingReport,
    SkippedAgent,
    SpeakerRegistry,
    TopicPlan,
    VerificationRecord,
    VerifierStep,
)
from .infra.throttle import LLMConcurrencyGate

__all__ = [
    "ConsensusRound",
    "LLMConcurrencyGate",
    "MeetingAnalyzerV3",
    "MeetingReport",
    "SkippedAgent",
    "SpeakerRegistry",
    "TopicPlan",
    "V3Config",
    "VerificationRecord",
    "VerifierStep",
    "build_graph_v3",
    "build_speaker_registry",
    "plan_meeting",
    "plan_topic",
]
