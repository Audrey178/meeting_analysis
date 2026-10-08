"""Trạng thái LangGraph cho các agent phía sau (downstream) -- xem ``graph.py``.

Các chủ đề được xử lý TUẦN TỰ, từng chủ đề một (không chạy song song tất cả).
``next_segment_index``/``known_names``/``known_assignments`` phục vụ việc đó:
BA nhánh của mỗi chủ đề (Content, Action, Decision) vẫn chạy song song với
nhau qua ``Send``, nhưng chủ đề N+1 chỉ được gửi đi sau khi CẢ BA nhánh của
chủ đề N xong, VÀ mọi candidate uncertain của chủ đề N đã qua debate+judge --
``known_names``/``known_assignments`` mang theo chỉ tên/việc giao ĐÃ KIỂM
CHỨNG (không phải candidate thô), nhờ đó các cách xưng hô "em"/"anh"/"bọn
em" ở chủ đề sau quy được về tên thật đã xuất hiện ở chủ đề trước với độ tin
cậy cao hơn so với dùng candidate chưa kiểm chứng.

Luồng một chủ đề (xem ``graph.py`` cho wiring đầy đủ):

    content_agent/action_agent/decision_agent (Send, song song)
        -> check_topic_evidence (rule, tách CLEAR/UNCERTAIN)
        -> debate_and_judge_agent (Send, chỉ cho candidate UNCERTAIN)
        -> advance_topic (chuyển sang chủ đề kế)

``MeetingState`` sau khi ``graph.invoke()`` xong CHÍNH LÀ kết quả cuối --
không có node/agent nào "dựng báo cáo" sau đó (bỏ ``group_task_assignments``/
``conclusion_agent``/``assemble_report_structure`` của bản M5, xem "M6" trong
be/DESIGN.md). Ba trường ``meeting_development``/``verified_assignments``/
``verified_decisions`` chính là ba phần output (Diễn biến họp / Giao việc /
Kết luận họp) của sơ đồ gốc -- người gọi (API, script) đọc thẳng ba trường
này, không qua bước "assemble" nào nữa. Việc gộp theo người phụ trách (nếu
cần cho một định dạng hiển thị cụ thể) hay viết đoạn văn kết luận hành chính
(nếu cần) là việc của TẦNG TRÌNH BÀY bên ngoài graph (vd. ``be/services/``),
không phải việc của agent pipeline này.

Các trường dùng reducer ``operator.add`` (``meeting_development``,
``action_item_candidates_raw``/``decision_candidates_raw``,
``verified_assignments``/``verified_decisions``, ``debate_records``): kết
quả của chủ đề mới phải CỘNG DỒN vào kết quả các chủ đề trước, không được
ghi đè.

``action_item_candidates_raw``/``decision_candidates_raw`` là candidate
CHƯA kiểm chứng (tương ứng hai ô ``ActionCandidate``/``DecisionCandidate``
trong sơ đồ), do ``action_agent``/``decision_agent`` sinh ra trực tiếp từ
LLM -- không xuất hiện trong sơ đồ như một "output" mà chỉ là bước trung
gian nội bộ trước Evidence-Check. ``verified_assignments``/
``verified_decisions`` là kết quả ĐÃ kiểm chứng (qua ``check_topic_evidence``
nếu CLEAR, hoặc qua ``debate_and_judge_agent`` nếu UNCERTAIN và được giữ).

``pending_debate_tasks`` CỐ Ý không dùng reducer cộng dồn (ghi đè hoàn toàn
mỗi khi ``check_topic_evidence`` chạy): nó chỉ mang candidate uncertain của
ĐÚNG chủ đề hiện tại để cạnh có điều kiện ``graph._dispatch_debate_or_advance``
đọc ngay sau đó. Dùng ``operator.add`` ở đây sẽ khiến nó phình ra qua từng
chủ đề và làm cạnh điều kiện gửi lại debate của các chủ đề ĐÃ XONG một lần nữa.

``completed_content_topics``/``completed_action_topics``/
``completed_decision_topics`` là dấu hiệu rõ ràng "nhánh này của chủ đề này
đã xong thật", mà ``check_topic_evidence``/``advance_topic`` kiểm tra trước
khi chạy tiếp. ``completed_debate_items`` (khóa theo ``DebateTask.item_key``)
đóng vai trò tương tự ở cấp CANDIDATE cho debate. KHÔNG suy ra từ việc danh
sách kết quả có thêm phần tử hay không, vì một chủ đề hoàn toàn có thể cho
ra 0 quyết định (hoặc 0 luận điểm, hoặc 0 candidate uncertain) mà vẫn xong;
kiểm tra kiểu đó sẽ lặp vô hạn ở trường hợp ấy.

``topic_failures`` gom mọi lời gọi LLM theo chủ đề bị lỗi trong vòng lặp
chính (content/action/decision agent). ``retry_failed_topics`` chạy lại các
lời gọi đó một lần và ghi phần VẪN còn thiếu vào ``unrecovered_failures``
(danh sách lỗi duy nhất mà API báo ra; ``topic_failures`` chỉ tăng chứ
không giảm vì là danh sách ``operator.add``). Debate/Judge KHÔNG nằm trong
cơ chế retry này (giới hạn đã biết, xem ``nodes/debate_judge_agent.py``).
"""

from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict

from ..utils.contracts import SpeakerTurn, TopicLabel, TopicSegment
from .schemas import (
    ActionItemCandidate,
    DebateRecord,
    DebateTask,
    DecisionCandidate,
    SpeakerSection,
    TopicFailure,
)


class MeetingState(TypedDict):
    """Trạng thái chung của graph xử lý một cuộc họp.

    Nhóm đầu vào (đặt sẵn trước khi chạy): ``segments``, ``labels_by_segment``,
    ``turns_by_id``, ``meeting_date`` (tùy chọn).
    Nhóm điều khiển vòng lặp chủ đề: ``next_segment_index``, ``known_names``,
    ``known_assignments``, ``completed_content_topics``,
    ``completed_action_topics``, ``completed_decision_topics``.
    Nhóm candidate CHƯA kiểm chứng (nội bộ, không phải output):
    ``action_item_candidates_raw``, ``decision_candidates_raw``.
    Nhóm evidence-check + debate: ``pending_debate_tasks``,
    ``completed_debate_items``, ``debate_records``.
    Nhóm lỗi: ``topic_failures``, ``unrecovered_failures``.
    Nhóm OUTPUT cuối cùng (đúng 3 ô của sơ đồ gốc, đọc thẳng sau
    ``graph.invoke()``, không qua node "assemble" nào): ``meeting_development``
    (Diễn biến họp), ``verified_assignments`` (Giao việc),
    ``verified_decisions`` (Kết luận họp).
    """
    # input cố định 
    segments: tuple[TopicSegment, ...]  # các đoạn chủ đề, từ TreeSeg
    labels_by_segment: dict[str, TopicLabel] # segment_id -> title/summary, từ stage07
    turns_by_id: dict[str, SpeakerTurn] # turn_id -> lượt nói, của CẢ cuộc họp
    meeting_date: NotRequired[str | None]  # ngày họp ISO, neo chuẩn hoá hạn chót
    # control vòng lặp 
    next_segment_index: int # "con trỏ" chính: đang/sắp xử lý topic thứ mấy
    known_names: tuple[str, ...]  # tên thật đã biết từ các topic ĐÃ XONG
    known_assignments: tuple[str, ...]  # dòng "người: việc" đã giao ở các topic ĐÃ XONG
    # Các quyết định đã qua check đã đủ trong 1 topic hay chưa
    completed_content_topics: Annotated[tuple[str, ...], operator.add]
    completed_action_topics: Annotated[tuple[str, ...], operator.add]
    completed_decision_topics: Annotated[tuple[str, ...], operator.add]
    # các quyết định raw
    action_item_candidates_raw: Annotated[list[ActionItemCandidate], operator.add]
    decision_candidates_raw: Annotated[list[DecisionCandidate], operator.add]
    # Các task cần debate check 
    pending_debate_tasks: tuple[DebateTask, ...]
    # Các task đã debate xog
    completed_debate_items: Annotated[tuple[str, ...], operator.add]
    debate_records: Annotated[tuple[DebateRecord, ...], operator.add]
    
    # Topic bị lỗi 
    topic_failures: Annotated[tuple[TopicFailure, ...], operator.add]
    unrecovered_failures: tuple[TopicFailure, ...]
    
    # output cuối cùng
    meeting_development: Annotated[list[SpeakerSection], operator.add]
    verified_assignments: Annotated[list[ActionItemCandidate], operator.add]
    verified_decisions: Annotated[list[DecisionCandidate], operator.add]


__all__ = ["MeetingState"]
