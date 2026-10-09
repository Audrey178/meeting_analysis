"""Điểm vào của v3 cho tầng dịch vụ: dựng graph một lần, chạy từng cuộc họp một mạch.

Một ``MeetingAnalyzerV3`` giữ:
- ``LLMConcurrencyGate`` dùng chung cho mọi cuộc họp chạy qua nó (giới hạn tổng số lời
  gọi LLM đồng thời của tiến trình);
- graph đã compile (không cần checkpointer: không còn bước dừng chờ người duyệt, các
  candidate chưa chắc chắn được Verifier và agent trích xuất trao đổi tới khi đồng thuận).
"""

from __future__ import annotations

from collections.abc import Sequence

from ..utils.config import TopicLabelerConfig
from ..utils.contracts import SpeakerTurn, TopicSegment
from ..utils.ports import LLMAdapter, TopicLabelAdapter
from .config import V3Config
from .graph.meeting import build_graph_v3
from .infra.throttle import DEFAULT_LLM_CONCURRENCY, LLMConcurrencyGate
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
        Đầu ra: MeetingReport.
        """

        state = {
            "meeting_id": meeting_id,
            "revision_id": revision_id,
            "meeting_date": meeting_date,
            "chair": chair,
            "segments": tuple(segments),
            "turns_by_id": {turn.turn_id: turn for turn in turns},
            "labels": [],
            "meeting_development": [],
            "verified_assignments": [],
            "verified_decisions": [],
            "verification_records": [],
            "topic_failures": [],
            "skipped_agents": [],
            "report": None,
        }
        output = self.graph.invoke(state, {"max_concurrency": self.config.max_concurrency})
        return output["report"]


__all__ = ["MeetingAnalyzerV3"]
