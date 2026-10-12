"""Pipeline agentic v3: mọi chủ đề chạy song song (subgraph + ``Send``) trên danh bạ người
nói do Planner dựng trước, Planner hỏi Decisions để bỏ agent không cần thiết, Verifier ReAct
thay Debate+Judge và gửi feedback lại cho agent trích xuất tới khi đồng thuận (không có bước
duyệt người).

Hình dạng graph xem ``graph/meeting.py``/``graph/topic.py``; điểm vào cho tầng dịch vụ là
``MeetingAnalyzerV3`` (``runner.py``). Các agent trích xuất và
luật gốc của v1 (``src.agentic``, nay đã xóa) nằm ở ``core/``.
"""

from .actors.agenda import AgendaTask, TaskAgenda, load_task_agenda, parse_task_agenda, task_path_for
from .actors.attendees import AttendeeRoster, attendee_path_for, load_attendee_roster
from .config import V3Config
from .graph import build_graph_v3
from .nodes.planner import build_speaker_registry
from .runner import MeetingAnalyzerV3
from .schemas import (
    AGENT_OF_PART,
    ANALYSIS_PARTS,
    ActionItemV3,
    ActorCandidate,
    AnalysisPart,
    ConsensusRound,
    MeetingReport,
    ProgressUpdate,
    SkippedAgent,
    SpeakerRegistry,
    TaskProgress,
    VerificationRecord,
    VerifierStep,
)
from .infra.throttle import LLMConcurrencyGate

__all__ = [
    "AGENT_OF_PART",
    "ANALYSIS_PARTS",
    "ActionItemV3",
    "AgendaTask",
    "ActorCandidate",
    "AnalysisPart",
    "AttendeeRoster",
    "ConsensusRound",
    "LLMConcurrencyGate",
    "MeetingAnalyzerV3",
    "MeetingReport",
    "ProgressUpdate",
    "SkippedAgent",
    "SpeakerRegistry",
    "TaskAgenda",
    "TaskProgress",
    "V3Config",
    "VerificationRecord",
    "VerifierStep",
    "attendee_path_for",
    "build_graph_v3",
    "build_speaker_registry",
    "load_attendee_roster",
    "load_task_agenda",
    "parse_task_agenda",
    "task_path_for",
]
