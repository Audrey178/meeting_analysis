"""Node Action Agent: trích các phát biểu GIAO VIỆC/PHÂN CÔNG trong MỘT đoạn chủ đề.

Tách ra từ agent gộp trước đây (``action_decision_agent``, xem lịch sử ở
``be/DESIGN.md``) theo đúng sơ đồ 3-agent (Content/Action/Decision): giờ là
MỘT lời gọi LLM riêng, không còn sinh chung với decisions trong cùng một
lời gọi. Số lời gọi LLM/chủ đề tăng theo đó (xem ``..graph``).

Output đi vào ``action_item_candidates_raw`` (CHƯA kiểm chứng) --
``nodes.evidence_check.check_topic_evidence`` lọc CLEAR/UNCERTAIN trước khi
vào ``action_item_candidates`` thật (candidate uncertain phải qua
``debate_and_judge_agent`` trước). Cách nối vào graph xem ``..graph``.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from .._shared import (
    is_bare_personal_pronoun,
    list_distinct_speaker_names,
    format_turns_as_transcript,
    read_list_or_empty,
    read_confirm_turn_id,
    read_stripped_text,
    split_dict_entries,
    strip_assignment_prefix,
    validate_evidence_by_segment_ids,
)
from ..deadline import UNKNOWN_DEADLINE, NormalizedDeadline, normalize_deadline
from ..schemas import ActionItemCandidate, SegmentTask, TopicFailure
from ....utils.llm_call_log import llm_call
from ....utils.ports import LLMAdapter, LLMUpstreamError

logger = logging.getLogger(__name__)

ACTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
                    "confirm_turn_id": {"type": ["string", "null"]},
                    "status": {
                        "type": "string",
                        "enum": ["assigned", "self_committed", "proposed", "reported"],
                    },
                    "actor": {"type": ["string", "null"]},
                    "text": {"type": "string"},
                    "deadline": {"type": ["string", "null"]},
                    "deadline_date": {"type": ["string", "null"]},
                    "deadline_kind": {
                        "type": "string",
                        "enum": ["exact", "before", "end_of_period", "relative", "unknown"],
                    },
                },
                "required": [
                    "evidence_segment_ids", "confirm_turn_id", "status", "actor", "text",
                    "deadline", "deadline_date", "deadline_kind",
                ],
            },
        },
    },
    "required": ["action_items"],
}

_ACTION_STATUSES = frozenset({"assigned", "self_committed", "proposed", "reported"})
# Giá trị ``task_id`` cho việc giao mới. v3 chỉ thêm trường task_id (enum mã việc + giá trị
# này) vào schema khi phiên họp có danh sách việc (``agentic_v3/nodes/extractors.py``).
NEW_TASK_ID = "new"
_DEADLINE_KINDS = frozenset({"exact", "before", "end_of_period", "relative", "unknown"})
_WEEKDAY_NAMES = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")

# "(hạn: khoảng 3 tuần)" / ", hạn: ..." ở CUỐI text: model lặp thời hạn dù prompt đã cấm.
_DEADLINE_ECHO_RE = re.compile(
    r"\s*(?:\(\s*(?:thời\s+)?hạn(?:\s*:|\s+(?!chế))[^)]*\)|[,;]\s*(?:thời\s+)?hạn\s*:[^,;()]*)\s*\.?$",
    re.IGNORECASE,
)


def _strip_deadline_echo(text: str, deadline_raw: str | None) -> str:
    """Bỏ phần lặp thời hạn ở cuối ``text`` khi hạn đã nằm ở ``deadline_raw``.

    Đầu vào: text - nội dung việc; deadline_raw - hạn nguyên văn (None thì giữ nguyên text).
    Đầu ra: text đã bỏ đuôi "(hạn: ...)"; nếu bỏ xong rỗng thì trả text gốc.
    """

    if not deadline_raw:
        return text
    stripped = _DEADLINE_ECHO_RE.sub("", text).strip()
    return stripped or text


def _format_meeting_date(meeting_date: str | None) -> str:
    """"2026-10-08" -> "2026-10-08 (thứ Năm)"; None/sai định dạng -> "(không rõ)"."""

    try:
        parsed = date.fromisoformat(meeting_date) if meeting_date else None
    except ValueError:
        parsed = None
    return f"{parsed.isoformat()} ({_WEEKDAY_NAMES[parsed.weekday()]})" if parsed else "(không rõ)"


def _resolve_deadline(item: dict, deadline_raw: str | None, meeting_date: str | None) -> NormalizedDeadline:
    """Quy ``deadline_raw`` về deadline_date/deadline_kind: luật trước, LLM dự phòng.

    Luật ``normalize_deadline`` cài đúng QUY TẮC CHUẨN HOÁ HẠN của prompt và tính lịch tất
    định, nên khi luật ra được ngày thì dùng luật (LLM hay tính lệch ngày dù đúng định dạng).
    Luật không ra ngày ("trước Tết", cách nói lạ) thì dùng kết quả LLM nếu hợp lệ. Không có
    ``deadline_raw`` thì luôn là ``unknown``.

    Đầu vào: item - một phần tử ``action_items`` LLM trả; deadline_raw - hạn nguyên văn
        đã làm sạch; meeting_date - ngày họp ISO hoặc None.
    Đầu ra: NormalizedDeadline.
    """

    if not deadline_raw:
        return UNKNOWN_DEADLINE
    fallback = normalize_deadline(deadline_raw, meeting_date)
    if fallback.deadline_date:
        return fallback
    kind = item.get("deadline_kind")
    raw_date = read_stripped_text(item.get("deadline_date"))
    try:
        llm_date = date.fromisoformat(raw_date).isoformat() if raw_date else None
    except ValueError:
        llm_date = None
    if kind not in _DEADLINE_KINDS or (raw_date and llm_date is None):
        return fallback
    if kind == "unknown" and fallback.deadline_kind != "unknown":
        return fallback
    return NormalizedDeadline(llm_date, kind)


def _build_action_user_prompt(task: SegmentTask) -> str:
    """Dựng user prompt cho Action Agent.

    Gồm: ngày họp (neo cho QUY TẮC CHUẨN HOÁ HẠN), ngữ cảnh từ các chủ đề trước,
    danh sách người nói của đoạn (để quy "em"/"anh" về tên thật), tiêu đề, tóm tắt
    và bản ghi của đoạn.

    Đầu vào: task - gói dữ liệu của một đoạn chủ đề.
    Đầu ra: str - nội dung user prompt.
    """

    speakers = ", ".join(list_distinct_speaker_names(task["turns"])) or "(không rõ)"
    return (
        f"Ngày họp: {_format_meeting_date(task.get('meeting_date'))}\n\n"
        f"Bối cảnh cuộc họp:\n{task['previous_context']}\n\n"
        f"Người nói trong đoạn này: {speakers}\n\n"
        f"Tiêu đề đoạn: {task['title']}\n"
        f"Tóm tắt đoạn: {task['summary']}\n\n"
        f"Bản ghi:\n{format_turns_as_transcript(task['turns'])}"
    )


def make_action_agent(llm: LLMAdapter, system_prompt: str):
    """Tạo node ``action_agent`` gắn với một LLM và system prompt cụ thể.

    Đầu vào: llm - adapter LLM có ``generate_json``; system_prompt - system prompt của agent
        (bản v3 ở ``agentic_v3/nodes/prompts.py``).
    Đầu ra: hàm node ``action_agent(task)`` để đăng ký vào graph.
    """

    def action_agent(task: SegmentTask) -> dict:
        """Trích việc được giao (CHƯA kiểm chứng) cho MỘT đoạn chủ đề.

        Mục nào thiếu nội dung hoặc thiếu trích dẫn hợp lệ bị loại (có ghi log); JSON
        sai hình dạng (``null``, phần tử không phải dict, ``text`` không phải chuỗi...)
        được xử lý như mục xấu chứ không làm sập cả đoạn. Actor là đại từ trần
        ("em", "anh"...) hoặc không phải chuỗi được đặt thành None thay vì giữ nguyên.
        ``text`` được bỏ tiền tố lặp "giao <actor>" (``strip_assignment_prefix``);
        ``status`` lạ thành "unknown" và ``confirm_turn_id`` không thuộc đoạn
        thành None -- cả hai đều khiến Evidence-Check gửi candidate đi debate.
        Hạn nguyên văn (``deadline_raw``) được quy về ``deadline_date``/``deadline_kind`` bằng
        luật ``..deadline.normalize_deadline``, neo theo ngày họp; luật không ra ngày thì dùng
        kết quả LLM quy theo QUY TẮC CHUẨN HOÁ HẠN trong prompt (``_resolve_deadline``).
        Nếu LLM lỗi (``LLMUpstreamError``), trả kết quả rỗng kèm ``TopicFailure`` để
        graph thử lại sau.

        Đầu vào: task - gói dữ liệu của đoạn chủ đề.
        Đầu ra: dict cập nhật state gồm ``action_item_candidates_raw``, dấu
            hoàn thành ``completed_action_topics`` và (khi lỗi) ``topic_failures``.
        """

        segment_id = task["segment_id"]
        # Dấu "nhánh Action của chủ đề này đã xong", trả cả ở đường lỗi.
        done = {"completed_action_topics": (segment_id,)}
        user_prompt = _build_action_user_prompt(task)
        try:
            with llm_call("action_agent", segment_id=segment_id, prompt_chars=len(user_prompt)):
                result = llm.generate_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema=ACTION_SCHEMA,
                )
        except LLMUpstreamError as exc:
            logger.warning("action_agent bỏ qua segment %s vì LLM lỗi: %s", segment_id, exc)
            failure = TopicFailure(segment_id, "action_agent", str(exc))
            return {"action_item_candidates_raw": [], "topic_failures": (failure,), **done}

        entries, dropped = split_dict_entries(result.get("action_items"))
        actions: list[ActionItemCandidate] = []
        for item in entries:
            text = read_stripped_text(item.get("text"))
            confirm_turn_id = read_confirm_turn_id(task["turns"], item.get("confirm_turn_id"))
            # Lượt chốt luôn là bằng chứng, kể cả khi model quên liệt kê nó.
            evidence_ids, quotes, segment_ids = validate_evidence_by_segment_ids(
                task["turns"], read_list_or_empty(item.get("evidence_segment_ids")), [confirm_turn_id]
            )
            if not text or not evidence_ids:
                dropped += 1
                continue
            actor = read_stripped_text(item.get("actor")) or None
            if actor is not None and is_bare_personal_pronoun(actor):
                actor = None
            status = item.get("status")
            deadline_raw = read_stripped_text(item.get("deadline")) or None
            deadline = _resolve_deadline(item, deadline_raw, task.get("meeting_date"))
            # Mã việc cũ (chỉ có khi phiên họp có danh sách việc); mã có trong danh sách hay
            # không được kiểm ở ``finalize``.
            task_id = read_stripped_text(item.get("task_id"))
            actions.append(
                ActionItemCandidate(
                    segment_id=segment_id,
                    actor=actor,
                    text=_strip_deadline_echo(strip_assignment_prefix(text, actor), deadline_raw),
                    evidence_ids=evidence_ids,
                    quotes=quotes,
                    deadline_raw=deadline_raw,
                    deadline_date=deadline.deadline_date,
                    deadline_kind=deadline.deadline_kind,
                    status=status if status in _ACTION_STATUSES else "unknown",
                    confirm_turn_id=confirm_turn_id,
                    segment_ids=segment_ids,
                    task_id=task_id if task_id and task_id != NEW_TASK_ID else None,
                )
            )
        if dropped:
            logger.warning(
                "action_agent segment %s: bỏ %d mục không có text/trích dẫn hợp lệ",
                segment_id,
                dropped,
            )
        return {"action_item_candidates_raw": actions, **done}

    return action_agent


__all__ = ["ACTION_SCHEMA", "NEW_TASK_ID", "make_action_agent"]
