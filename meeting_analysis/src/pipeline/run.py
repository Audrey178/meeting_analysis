"""Điểm vào của pipeline: chạy đủ sáu bước cho một cuộc họp.

Việc chạy chia làm hai giai đoạn. Giai đoạn chuẩn bị (bước 1-3) đọc bản ghi, tách lượt nói, chia
chủ đề và đặt tên chủ đề; kết quả này có thể được lưu lại để dùng nhiều lần. Giai đoạn phân tích
(bước 4-6) trích xuất, kiểm chứng và tổng hợp báo cáo trên nền đó, và có thể chỉ tính một phần kết
quả.

Bộ phân tích được dựng một lần cho cả chương trình và dùng chung cho mọi cuộc họp; nó giữ giới hạn
chung về số lời gọi mô hình chạy cùng lúc.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..utils.config import TopicLabelerConfig
from ..utils.contracts import SpeakerTurn, TopicLabel, TopicSegment
from ..utils.ports import LLMAdapter, TopicLabelAdapter
from .config import AnalysisConfig
from .deps import GraphDeps
from .graph.meeting import build_meeting_graph
from .shared.meeting_inputs.agenda import TaskAgenda
from .shared.meeting_inputs.attendees import AttendeeRoster, MeetingChair
from .shared.schemas import ANALYSIS_PARTS, AnalysisPart, MeetingReport
from .shared.throttle import DEFAULT_LLM_CONCURRENCY, LLMConcurrencyGate
from .step1_turns import build_meeting_turns
from .step2_segment import segment_turns
from .step3_label import label_topics
from .shared.judges.progress_act import ProgressActJudge
from .shared.judges.turn_act import TurnActJudge

if TYPE_CHECKING:
    from .step2_segment.dialstart import DialStartSegmenter


@dataclass(frozen=True)
class PreparedMeeting:
    """Lưu "nền" của một cuộc họp sau bước 1-3 để chạy bước 4-6 nhiều lần trên cùng dữ liệu.

    Attributes:
        meeting_id: Mã cuộc họp lấy từ bản ghi.
        turns: Các lượt nói theo thứ tự thời gian.
        segments: Các đoạn chủ đề liên tiếp, phủ kín ``turns``.
        labels: Nhãn (tiêu đề, tóm tắt) của từng đoạn, cùng thứ tự với ``segments``.
    """

    meeting_id: str
    turns: tuple[SpeakerTurn, ...]
    segments: tuple[TopicSegment, ...]
    labels: tuple[TopicLabel, ...]


class MeetingAnalyzer:
    """Chạy pipeline phân tích cho từng cuộc họp, dùng chung mô hình và giới hạn đồng thời.

    Nên tạo một lần cho cả chương trình rồi gọi lại cho mọi cuộc họp: bộ giới hạn số lời gọi LLM
    đồng thời nằm trong đối tượng này, tạo nhiều đối tượng thì giới hạn không còn là giới hạn chung.
    Thường gọi ``prepare`` để dựng nền (bước 1-3), rồi ``analyze`` để trích xuất và tổng hợp (bước 4-6).

    Args:
        content_llm: Mô hình cho agent tóm tắt ý thảo luận. Truyền bản thô; lớp này tự bọc qua bộ
            giới hạn đồng thời (cùng với ba mô hình dưới).
        action_llm: Mô hình cho agent trích việc giao và tiến độ; cũng trả lời nhận xét của Verifier.
        decision_llm: Mô hình cho agent trích kết luận; cũng trả lời nhận xét của Verifier.
        verifier_llm: Mô hình cho Verifier.
        labeler: Bộ gán nhãn chủ đề của bước 3.
        labeler_config: Cấu hình gán nhãn; None thì dùng mặc định.
        config: Thông số bước 4-6; None thì dùng mặc định.
        llm_concurrency: Số lời gọi LLM đồng thời tối đa, dùng chung cho mọi cuộc họp.
        verifier_llm_concurrency: None thì Verifier dùng chung giới hạn trên. Đặt số thì Verifier có
            giới hạn riêng, hữu ích khi ``verifier_llm`` trỏ tới dịch vụ khác.
        turn_judge: Bộ phân loại lượt nói qua Decisions API. None thì không xét được lượt chốt, nên
            mọi candidate có lượt chốt đều phải qua Verifier, và kết quả các chủ đề chỉ được gộp
            trùng theo chữ.
        progress_judge: Bộ phân loại lượt nêu trạng thái tiến độ qua Decisions API. None thì mọi cập
            nhật tiến độ đều phải qua Verifier.

    Attributes:
        config: Thông số bước 4-6 đang dùng.
        gate: Bộ giới hạn số lời gọi LLM đồng thời dùng chung.
        deps: Phụ thuộc truyền cho luồng chạy bước 4-6 (các mô hình đã bọc qua giới hạn).
        graph: Luồng chạy bước 4-6 đã dựng sẵn.
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
        config: AnalysisConfig | None = None,
        llm_concurrency: int = DEFAULT_LLM_CONCURRENCY,
        verifier_llm_concurrency: int | None = None,
        turn_judge: TurnActJudge | None = None,
        progress_judge: ProgressActJudge | None = None,
    ) -> None:
        self.config = config or AnalysisConfig()
        self.gate = LLMConcurrencyGate(llm_concurrency)
        verifier_gate = self.gate if verifier_llm_concurrency is None else LLMConcurrencyGate(verifier_llm_concurrency)
        self._labeler = self.gate.wrap_topic_labeler(labeler)
        self._labeler_config = labeler_config or TopicLabelerConfig()
        self.deps = GraphDeps(
            content_llm=self.gate.wrap_llm(content_llm),
            action_llm=self.gate.wrap_llm(action_llm),
            decision_llm=self.gate.wrap_llm(decision_llm),
            verifier_llm=verifier_gate.wrap_llm(verifier_llm),
            config=self.config,
            turn_judge=turn_judge,
            progress_judge=progress_judge,
        )
        self.graph = build_meeting_graph()

    def prepare(self, payload: dict, *, segmenter: DialStartSegmenter) -> PreparedMeeting:
        """Chạy bước 1-3: tách lượt nói, chia chủ đề và gán nhãn cho một bản ghi.

        Args:
            payload: Bản ghi cuộc họp dạng dict, theo khuôn của request phân tích.
            segmenter: Bộ chia đoạn chủ đề đã nạp checkpoint; nên tạo một lần rồi dùng lại.

        Returns:
            Nền của cuộc họp, dùng làm đầu vào cho ``analyze``.

        Raises:
            ValueError: Khi bản ghi không đúng khuôn dạng được hỗ trợ.
            LLMUpstreamError: Khi mô hình gán nhãn gặp lỗi không thể thử lại. Lỗi khác chỉ làm đoạn đó
                nhận nhãn dự phòng trích từ chính lời nói.
        """

        meeting_id, turns = build_meeting_turns(payload)
        segments = tuple(segment_turns(turns, segmenter))
        labels = self.label_segments(segments)
        return PreparedMeeting(meeting_id, turns, segments, labels)

    def label_segments(self, segments: Sequence[TopicSegment]) -> tuple[TopicLabel, ...]:
        """Chạy bước 3: gán nhãn mọi đoạn chủ đề, các đoạn được gọi song song.

        Args:
            segments: Các đoạn chủ đề theo thứ tự.

        Returns:
            Nhãn của từng đoạn, cùng số lượng và thứ tự với ``segments``.
        """

        return label_topics(tuple(segments), config=self._labeler_config, adapter=self._labeler)

    def analyze(
        self,
        *,
        meeting_id: str,
        meeting_date: str | None = None,
        chair: MeetingChair | None = None,
        turns: Sequence[SpeakerTurn],
        segments: Sequence[TopicSegment],
        attendee_roster: AttendeeRoster | None = None,
        task_agenda: TaskAgenda | None = None,
        parts: Collection[AnalysisPart] | None = None,
        labels: Sequence[TopicLabel] | None = None,
    ) -> MeetingReport:
        """Chạy bước 4-6: trích xuất, kiểm chứng và tổng hợp báo cáo cho một cuộc họp.

        Có thể chỉ tính một phần kết quả qua ``parts``; các phần không được yêu cầu để rỗng trong
        báo cáo, nhưng nhãn chủ đề thì luôn đủ.

        Args:
            meeting_id: Mã cuộc họp.
            meeting_date: Ngày họp dạng "YYYY-MM-DD", dùng làm mốc để quy hạn chót như "tuần sau" về
                ngày cụ thể. None thì việc giao vẫn có loại hạn nhưng thường không có ngày.
            chair: Người chủ trì do phiên họp cung cấp. Tên được lấy theo mã trong ``attendee_roster``,
                không khớp thì dùng tên đi kèm. Agent trích xuất và Verifier dựa vào người này để nhận ra
                lời giao việc, lời chốt kết luận. None thì pipeline không đoán ai là người chủ trì.
            turns: Các lượt nói của cả cuộc họp, theo thứ tự.
            segments: Các đoạn chủ đề phủ kín ``turns``.
            attendee_roster: Danh sách người và đơn vị tham dự. None thì bên nhận việc chỉ được xác định
                trong số người đã phát biểu.
            task_agenda: Danh sách việc cần báo cáo tiến độ. None thì không trích tiến độ và phần tiến độ
                của báo cáo rỗng.
            parts: Các phần kết quả cần tính, lấy trong ``ANALYSIS_PARTS``. None thì tính mọi phần.
            labels: Nhãn của từng đoạn, cùng thứ tự ``segments``. None thì gán nhãn lại trước khi chạy.

        Returns:
            Báo cáo cuộc họp đã sắp theo thứ tự chủ đề và gộp mục trùng.

        Raises:
            ValueError: Khi ``parts`` chứa phần không tồn tại.
        """

        selected = frozenset(ANALYSIS_PARTS if parts is None else parts)
        unknown = selected.difference(ANALYSIS_PARTS)
        if unknown:
            raise ValueError(f"phần kết quả không hợp lệ: {sorted(unknown)} (hợp lệ: {list(ANALYSIS_PARTS)})")
        if labels is None:
            labels = self.label_segments(segments)
        state = {
            "meeting_id": meeting_id,
            "meeting_date": meeting_date,
            "chair": chair.with_roster_name(attendee_roster) if chair else None,
            "segments": tuple(segments),
            "turns_by_id": {turn.turn_id: turn for turn in turns},
            "attendee_roster": attendee_roster,
            "task_agenda": task_agenda,
            "parts": selected,
            "topic_labels": {label.segment_id: label for label in labels},
            "labels": [],
            "discussion_points": [],
            "verified_assignments": [],
            "verified_decisions": [],
            "verification_records": [],
            "topic_failures": [],
            "progress_updates": [],
            "report": None,
        }
        output = self.graph.invoke(state, {"max_concurrency": self.config.max_concurrency}, context=self.deps)
        return output["report"]


__all__ = [
    "MeetingAnalyzer",
    "PreparedMeeting",
]
