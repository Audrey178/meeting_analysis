"""Planner (Plan-and-Execute, luật, 0 token): chạy MỘT lần trước khi các chủ đề tách song song.

Lập hai thứ:

1. ``SpeakerRegistry`` -- danh bạ người nói của cả cuộc họp. Thay ngữ cảnh
   ``known_names``/``known_assignments`` chạy dồn của v1 (lý do duy nhất khiến v1
   phải xử lý chủ đề tuần tự). Khác v1: danh bạ thấy cả người chỉ xuất hiện ở chủ
   đề SAU; đổi lại không còn tên do agent tự gán (có thể sai) lan sang chủ đề sau.
2. ``TopicPlan`` cho từng chủ đề -- có chạy Action/Decision agent không. Chủ đề
   không có cụm giao/nhận/chốt việc nào thì bỏ agent tương ứng. Cue cố ý RỘNG
   (gồm cả "sẽ", "nhận", "làm") vì bỏ nhầm làm mất kết quả (giảm recall), còn
   chạy thừa chỉ tốn một lời gọi. Content agent không bao giờ bị bỏ.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from ..agentic._shared import get_turns_of_segment, list_distinct_speaker_names
from ..utils.contracts import SpeakerTurn, TopicSegment
from .schemas import SpeakerRegistry, TopicPlan

# Cụm cho thấy CÓ THỂ có việc được giao/nhận trong chủ đề.
ACTION_CUES: tuple[str, ...] = (
    "giao", "phân công", "phụ trách", "đảm nhận", "đảm nhiệm", "chủ trì", "phối hợp",
    "yêu cầu", "chỉ đạo", "đề nghị", "đề xuất", "kiến nghị", "nhờ", "nhận", "sẽ", "làm", "xử lý", "triển khai",
    "hoàn thành", "trình", "báo cáo lại", "gửi", "chuẩn bị", "rà soát", "cập nhật",
    "trước ngày", "thời hạn", "hạn chót", "deadline", "trong tuần", "tuần sau", "tháng sau",
)

# Cụm cho thấy CÓ THỂ có kết luận/thống nhất trong chủ đề.
DECISION_CUES: tuple[str, ...] = (
    "chốt", "thống nhất", "kết luận", "quyết định", "nhất trí", "đồng ý", "phê duyệt",
    "thông qua", "chấp thuận", "đề xuất", "kiến nghị", "chọn", "áp dụng", "giữ nguyên", "dừng", "tạm dừng",
    "không làm", "bỏ", "giao", "triển khai", "theo phương án", "như vậy",
)


def _normalize(text: str) -> str:
    """Chuẩn hoá để so khớp cue: NFC, hạ chữ thường, gộp khoảng trắng.

    Đầu vào: text - chuỗi bất kỳ.
    Đầu ra: str đã chuẩn hoá.
    """

    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).casefold()).strip()


def find_cues(text: str, cues: Sequence[str]) -> tuple[str, ...]:
    """Liệt kê các cụm trong ``cues`` xuất hiện trọn âm tiết trong ``text``.

    Đầu vào: text - chuỗi đã chuẩn hoá (``_normalize``); cues - các cụm cần tìm.
    Đầu ra: tuple cụm đã khớp, theo thứ tự trong ``cues``.
    """

    return tuple(cue for cue in cues if re.search(rf"(?<!\w){re.escape(cue)}(?!\w)", text))


def build_speaker_registry(turns: Sequence[SpeakerTurn]) -> SpeakerRegistry:
    """Dựng danh bạ người nói từ toàn bộ lượt nói của cuộc họp.

    Đầu vào: turns - mọi lượt nói, theo thứ tự.
    Đầu ra: SpeakerRegistry.
    """

    return SpeakerRegistry(names=list_distinct_speaker_names(tuple(turns)))


def plan_topic(
    segment_id: str, turns: Sequence[SpeakerTurn], *, skip_without_cues: bool = True
) -> TopicPlan:
    """Lập kế hoạch agent cho MỘT chủ đề theo cue trong nguyên văn lượt nói.

    Đầu vào:
        segment_id: mã chủ đề.
        turns: lượt nói của chủ đề.
        skip_without_cues: False thì luôn chạy đủ ba agent (ablation/tắt tính năng).
    Đầu ra: TopicPlan.
    """

    text = _normalize(" ".join(turn.text_exact for turn in turns))
    action_cues = find_cues(text, ACTION_CUES)
    decision_cues = find_cues(text, DECISION_CUES)
    return TopicPlan(
        segment_id=segment_id,
        run_action=bool(action_cues) or not skip_without_cues,
        run_decision=bool(decision_cues) or not skip_without_cues,
        action_cues=action_cues,
        decision_cues=decision_cues,
    )


def plan_meeting(
    segments: Sequence[TopicSegment],
    turns_by_id: dict[str, SpeakerTurn],
    *,
    skip_without_cues: bool = True,
) -> tuple[SpeakerRegistry, dict[str, TopicPlan]]:
    """Lập danh bạ người nói và kế hoạch agent cho mọi chủ đề.

    Đầu vào:
        segments: các chủ đề theo thứ tự.
        turns_by_id: turn_id -> SpeakerTurn của cả cuộc họp.
        skip_without_cues: xem ``plan_topic``.
    Đầu ra: (SpeakerRegistry, segment_id -> TopicPlan).
    """

    registry = build_speaker_registry(tuple(turns_by_id.values()))
    plans = {
        segment.segment_id: plan_topic(
            segment.segment_id,
            get_turns_of_segment(segment, turns_by_id),
            skip_without_cues=skip_without_cues,
        )
        for segment in segments
    }
    return registry, plans


def format_registry_context(registry: SpeakerRegistry) -> str:
    """Biến danh bạ thành khối ngữ cảnh cho prompt Action agent (ô ``previous_context`` của v1).

    Đầu vào: registry - danh bạ người nói.
    Đầu ra: str cho prompt.
    """

    if not registry.names:
        return "(Không có danh sách người nói.)"
    return "Người nói trong cả cuộc họp: " + ", ".join(registry.names) + "."


__all__ = [
    "ACTION_CUES",
    "DECISION_CUES",
    "build_speaker_registry",
    "find_cues",
    "format_registry_context",
    "plan_meeting",
    "plan_topic",
]
