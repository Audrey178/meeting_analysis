"""Dữ liệu được truyền qua lại trong luồng chạy bước 4-6: phần chung của cả cuộc họp và phần riêng
của từng chủ đề.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from ...utils.contracts import SpeakerTurn, TopicLabel, TopicSegment
from ..shared.meeting_inputs.agenda import TaskAgenda
from ..shared.meeting_inputs.attendees import AttendeeRoster, MeetingChair
from ..shared.schemas import (
    ActionItemCandidate,
    AnalysisPart,
    DecisionCandidate,
    DiscussionPoint,
    MeetingReport,
    ProgressUpdate,
    ExtractorInput,
    SpeakerRegistry,
    TopicFailure,
    VerificationRecord,
    VerifyTask,
)


class TopicInput(TypedDict):
    """Gói dữ liệu gửi vào luồng con của một chủ đề.

    Attributes:
        segment: Đoạn chủ đề đang xử lý.
        turns: Lượt nói thuộc chủ đề, theo thứ tự.
        meeting_turns: Lượt nói của cả cuộc họp, để Verifier tra bằng chứng nằm ở chủ đề khác.
        registry: Danh bạ người nói của cả cuộc họp.
        meeting_date: Ngày họp dạng "YYYY-MM-DD", mốc để quy hạn chót về ngày; None nếu không biết.
        parts: Các phần kết quả cần tính, quyết định agent trích xuất nào được chạy.
        label: Nhãn của chủ đề từ bước 3.
    """

    segment: TopicSegment
    turns: tuple[SpeakerTurn, ...]  # lượt nói của chủ đề
    meeting_turns: tuple[SpeakerTurn, ...]  # lượt nói của cả cuộc họp (cho tool Verifier)
    registry: SpeakerRegistry
    meeting_date: str | None  # ngày họp ISO, neo chuẩn hoá hạn chót của Action agent
    parts: frozenset[AnalysisPart]  # phần kết quả cần tính: chọn agent trích xuất nào được chạy
    label: TopicLabel  # nhãn chủ đề (bước 3, ``step3_label``)


class TopicOutput(TypedDict):
    """Các kết quả luồng con trả về luồng cha.

    Tên khoá và cách cộng dồn trùng với trạng thái cuộc họp, nên kết quả của mọi chủ đề được nối
    vào cùng danh sách. Thứ tự giữa các chủ đề chưa đúng thứ tự cuộc họp; bước tổng hợp sẽ sắp lại.

    Attributes:
        labels: Nhãn của chủ đề (mỗi chủ đề góp một nhãn).
        discussion_points: Các ý thảo luận.
        verified_assignments: Việc giao đã được giữ, qua luật hoặc qua Verifier.
        verified_decisions: Kết luận đã được giữ, qua luật hoặc qua Verifier.
        verification_records: Bản ghi của mỗi lần Verifier xét một candidate.
        topic_failures: Các lần agent trích xuất vẫn lỗi sau mọi lượt thử.
        progress_updates: Cập nhật tiến độ đã được giữ, qua luật hoặc qua Verifier.
    """

    labels: Annotated[list[TopicLabel], operator.add]
    discussion_points: Annotated[list[DiscussionPoint], operator.add]
    verified_assignments: Annotated[list[ActionItemCandidate], operator.add]
    verified_decisions: Annotated[list[DecisionCandidate], operator.add]
    verification_records: Annotated[list[VerificationRecord], operator.add]
    topic_failures: Annotated[list[TopicFailure], operator.add]
    progress_updates: Annotated[list[ProgressUpdate], operator.add]  # đã kiểm (evidence_check)


class TopicState(TopicInput, TopicOutput):
    """Trạng thái nội bộ của luồng con một chủ đề, gồm đầu vào, đầu ra và các kết quả trung gian.

    Attributes:
        extractor_input: Gói dữ liệu đưa cho các agent trích xuất.
        action_candidates_raw: Việc giao agent trích ra, chưa kiểm.
        decision_candidates_raw: Kết luận agent trích ra, chưa kiểm.
        progress_updates_raw: Cập nhật tiến độ agent trích ra, chưa kiểm.
        pending_verify: Các candidate UNCERTAIN đang chờ gửi Verifier.
    """

    extractor_input: ExtractorInput
    action_candidates_raw: Annotated[list[ActionItemCandidate], operator.add]
    decision_candidates_raw: Annotated[list[DecisionCandidate], operator.add]
    progress_updates_raw: Annotated[list[ProgressUpdate], operator.add]
    pending_verify: tuple[VerifyTask, ...]


class MeetingState(TopicOutput):
    """Trạng thái của luồng chạy cả cuộc họp, gồm đầu vào và kết quả cộng dồn của mọi chủ đề.

    Attributes:
        meeting_id: Mã cuộc họp.
        meeting_date: Ngày họp dạng "YYYY-MM-DD"; None nếu không biết.
        chair: Người chủ trì do phiên họp cung cấp, None nếu không có; được đưa vào danh bạ.
        segments: Các đoạn chủ đề theo thứ tự.
        turns_by_id: Lượt nói của cả cuộc họp, tra theo mã lượt, giữ thứ tự cuộc họp.
        attendee_roster: Danh sách người và đơn vị tham dự; None nếu không có.
        task_agenda: Danh sách việc cần báo cáo tiến độ; None nếu không có.
        parts: Các phần kết quả cần tính.
        topic_labels: Nhãn từ bước 3, tra theo mã đoạn chủ đề.
        registry: Danh bạ người nói, có sau bước dựng danh bạ.
        report: Báo cáo cuối, có sau bước tổng hợp; None trước đó.
    """

    meeting_id: str
    meeting_date: str | None
    chair: MeetingChair | None  # người chủ trì phiên họp cung cấp; ``build_registry`` đưa vào ``registry``
    segments: tuple[TopicSegment, ...]
    turns_by_id: dict[str, SpeakerTurn]
    attendee_roster: AttendeeRoster | None
    task_agenda: TaskAgenda | None
    parts: frozenset[AnalysisPart]
    topic_labels: dict[str, TopicLabel]
    registry: SpeakerRegistry
    report: MeetingReport | None


__all__ = [
    "MeetingState",
    "TopicInput",
    "TopicOutput",
    "TopicState",
]
