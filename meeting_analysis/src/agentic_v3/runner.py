"""Điểm vào của v3 cho tầng dịch vụ: dựng graph một lần, chạy từng cuộc họp một mạch.

Một ``MeetingAnalyzerV3`` giữ:
- ``LLMConcurrencyGate`` dùng chung cho mọi cuộc họp chạy qua nó (giới hạn tổng số lời
  gọi LLM đồng thời của tiến trình);
- graph đã compile (không cần checkpointer: không còn bước dừng chờ người duyệt, các
  candidate chưa chắc chắn được Verifier và agent trích xuất trao đổi tới khi đồng thuận).
"""

from __future__ import annotations

from collections.abc import Sequence

from .core.turn_act import TurnActJudge
from ..utils.config import TopicLabelerConfig
from ..utils.contracts import SpeakerTurn, TopicSegment
from ..utils.ports import LLMAdapter, TopicLabelAdapter
from .actors.agenda import TaskAgenda
from .actors.attendees import AttendeeRoster
from .config import V3Config
from .graph.meeting import build_graph_v3
from .infra.throttle import DEFAULT_LLM_CONCURRENCY, LLMConcurrencyGate
from .nodes.progress_act import ProgressActJudge
from .schemas import MeetingReport


class MeetingAnalyzerV3:
    """Chạy pipeline v3 (sau khi đã có lượt nói và ranh giới chủ đề).

    Đầu vào khi tạo:
        content_llm, action_llm, decision_llm, verifier_llm: adapter LLM thô (runner tự
            bọc qua gate). ``action_llm``/``decision_llm`` cũng trả lời feedback của Verifier.
        labeler: adapter gán nhãn chủ đề (stage07).
        labeler_config: cấu hình stage07.
        config: cấu hình v3.
        llm_concurrency: số lời gọi LLM đồng thời tối đa.
        verifier_llm_concurrency: None thì Verifier dùng chung gate trên; đặt số thì
            Verifier có gate riêng (dùng khi ``verifier_llm`` trỏ tới backend khác).
        turn_judge: bộ phân loại lượt chốt theo nghĩa cho evidence-check; None thì
            dùng luật từ khoá (``_COMMIT_CUES``/``_HEDGE_CUES``).
        progress_llm: adapter LLM thô của agent tiến độ; None thì dùng ``action_llm``.
        progress_judge: Decisions cho lượt nêu trạng thái tiến độ; None thì giữ trạng thái
            agent khai (``verification="unchecked"``).
    """

    def __init__(
        self,
        *,
        content_llm: LLMAdapter,
        action_llm: LLMAdapter,
        decision_llm: LLMAdapter,
        verifier_llm: LLMAdapter,
        labeler: TopicLabelAdapter,
        labeler_config: TopicLabelerConfig | None = None,
        config: V3Config | None = None,
        llm_concurrency: int = DEFAULT_LLM_CONCURRENCY,
        verifier_llm_concurrency: int | None = None,
        turn_judge: TurnActJudge | None = None,
        progress_llm: LLMAdapter | None = None,
        progress_judge: ProgressActJudge | None = None,
    ) -> None:
        self.config = config or V3Config()
        self.gate = LLMConcurrencyGate(llm_concurrency)
        verifier_gate = self.gate if verifier_llm_concurrency is None else LLMConcurrencyGate(verifier_llm_concurrency)
        self.graph = build_graph_v3(
            self.gate.wrap_llm(content_llm),
            self.gate.wrap_llm(action_llm),
            self.gate.wrap_llm(decision_llm),
            verifier_gate.wrap_llm(verifier_llm),
            self.gate.wrap_topic_labeler(labeler),
            labeler_config or TopicLabelerConfig(),
            self.config,
            turn_judge=turn_judge,
            progress_llm=self.gate.wrap_llm(progress_llm) if progress_llm is not None else None,
            progress_judge=progress_judge,
        )

    def analyze(
        self,
        *,
        meeting_id: str,
        revision_id: str = "",
        meeting_date: str | None = None,
        chair: str | None = None,
        turns: Sequence[SpeakerTurn],
        segments: Sequence[TopicSegment],
        attendee_roster: AttendeeRoster | None = None,
        task_agenda: TaskAgenda | None = None,
    ) -> MeetingReport:
        """Chạy pipeline cho một cuộc họp tới khi có kết quả cuối.

        Đầu vào:
            meeting_id: mã cuộc họp.
            revision_id: mã phiên bản transcript.
            meeting_date: ngày họp ISO "YYYY-MM-DD" (tùy chọn) để quy hạn chót ("tuần sau")
                về ngày; None thì việc giao vẫn có ``deadline_kind`` nhưng ít khi có ``deadline_date``.
            chair: tên người chủ trì (tùy chọn). Agent trích xuất và Verifier dựa vào đây để
                nhận ra lời giao việc/kết luận; None thì model tự suy ra từ bản ghi.
            turns: lượt nói (stage03), theo thứ tự.
            segments: ranh giới chủ đề phủ kín ``turns`` (CHƯA cần nhãn).
            attendee_roster: danh sách người/đơn vị tham dự (``attendees.load_attendee_roster``
                theo quy ước đặt tên); None thì actor chỉ quy về người nói trong bản ghi.
            task_agenda: danh sách việc cần báo cáo tiến độ (``agenda.load_task_agenda``);
                None thì không chạy agent tiến độ và ``task_progress`` rỗng.
        Đầu ra: MeetingReport.
        """

        state = {
            "meeting_id": meeting_id,
            "revision_id": revision_id,
            "meeting_date": meeting_date,
            "chair": chair,
            "segments": tuple(segments),
            "turns_by_id": {turn.turn_id: turn for turn in turns},
            "attendee_roster": attendee_roster,
            "task_agenda": task_agenda,
            "labels": [],
            "meeting_development": [],
            "verified_assignments": [],
            "verified_decisions": [],
            "verification_records": [],
            "topic_failures": [],
            "skipped_agents": [],
            "progress_updates": [],
            "report": None,
        }
        output = self.graph.invoke(state, {"max_concurrency": self.config.max_concurrency})
        return output["report"]


__all__ = ["MeetingAnalyzerV3"]
