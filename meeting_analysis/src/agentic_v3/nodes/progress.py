"""Tiến độ các việc cần báo cáo: agent trích xuất, kiểm lượt nêu trạng thái, gộp theo việc.

Chỉ chạy khi phiên họp có danh sách việc (``SpeakerRegistry.agenda``, file ``*.tasks.json``).

1. ``make_progress_agent``: MỘT lời gọi LLM mỗi chủ đề. Agent nhận CẢ danh sách việc và tự
   chọn việc nào chủ đề có nói tới (không lọc trước theo từ khoá), khai trạng thái kèm
   lượt nêu trạng thái (``status_turn_id``).
2. ``check_progress_updates`` (trong ``evidence_check``): hỏi Decisions API (``nodes/progress_act.py``,
   lượt dài thì từng đoạn).
   - Cập nhật có trạng thái: xét lượt nêu trạng thái, rồi các lượt bằng chứng khác. Xác nhận
     -> giữ; Decisions chắc chắn trạng thái khác -> sửa; còn lại -> hạ về "mentioned" (cờ
     ``uncertain``). Riêng câu hỏi chung (việc làm ra sản phẩm) không được đổi qua lại giữa
     các trạng thái báo cáo xong/đang làm/vướng: nó hay chấm tình trạng của đề án/dự án được
     nhắc thay cho tình trạng của việc. Lượt chắc chắn là báo cáo về việc thì giữ trạng thái
     agent khai (cờ ``kept``). Việc chỉ là báo cáo tại cuộc họp được hỏi câu riêng, câu đó được
     sửa cả trạng thái báo cáo.
   - Cập nhật "mentioned": xét các lượt bằng chứng. Mọi lượt đều "không nói về việc này" thì
     bỏ cập nhật (agent gắn nhầm việc); lượt nói về việc mà Decisions chắc chắn là báo cáo
     (xong/đang làm/vướng) thì nâng lên trạng thái đó; là yêu cầu làm lại/hoãn thì chỉ nâng
     khi lượt đó cũng là chỉ đạo/kết luận theo ``turn_judge`` (Decisions chỉ thấy 2 lượt trước,
     không tự biết đề xuất của một thành viên có được người chủ trì chấp nhận hay không).
   Việc trong danh sách không bao giờ bị xoá: việc không còn cập nhật nào là "not_reported".
   Pha 1 không đưa cập nhật tiến độ qua Verifier ReAct.
3. ``summarize_task_progress`` (trong ``finalize``): gộp cập nhật của mỗi việc qua mọi chủ
   đề. Lượt chỉ đạo/kết luận (``turn_judge``) thắng lượt báo cáo; cùng loại thì lượt muộn
   hơn thắng. KHÔNG dựa vào tên người nói, vì nhãn người nói có thể gộp nhiều người.
4. ``link_assignment_to_agenda`` (trong ``finalize``): gán quan hệ việc giao <-> việc cũ
   theo các trường (``task_id``, trạng thái, bên nhận việc, hạn), không so khớp chữ.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date

from ..actors.agenda import AgendaTask, TaskAgenda
from ..actors.resolution import normalize_name_key
from ..core._shared import (
    format_turns_as_transcript,
    list_distinct_speaker_names,
    read_confirm_turn_id,
    read_list_or_empty,
    read_stripped_text,
    split_dict_entries,
    validate_evidence_by_segment_ids,
)
from ..core.nodes.action_agent import _format_meeting_date, _resolve_deadline
from ..core.schemas import SegmentTask, TopicFailure
from ..core.turn_act import COMMIT_CLEAR_MIN, TurnActJudge
from ...utils.contracts import SpeakerTurn
from ...utils.llm_call_log import llm_call
from ...utils.ports import LLMAdapter, LLMUpstreamError
from ..schemas import (
    UPDATE_STATUSES,
    ActionItemV3,
    ProgressUpdate,
    SpeakerRegistry,
    TaskProgress,
)
from .planner import format_registry_context
from .progress_act import STATUS_CLEAR_MIN, ProgressActJudge, ProgressActJudgement, judge_turn_windows
from .prompts import PROGRESS_SYSTEM_PROMPT, format_chair_line

logger = logging.getLogger(__name__)

# Giới hạn độ dài các trường văn bản tự do (model trên gemma từng sinh chuỗi vô tận).
_MAX_SUMMARY_CHARS = 400
_MAX_BLOCKERS = 2
_MAX_BLOCKER_CHARS = 200
# Số cập nhật của MỘT chủ đề được kiểm song song (mỗi cập nhật vài lời gọi Decisions).
_MAX_PARALLEL_CHECKS = 4
# Decisions nâng "mentioned" lên trạng thái báo cáo; lên trạng thái chỉ đạo thì lượt phải là
# chỉ đạo/kết luận theo ``turn_judge`` (``_check_mention``).
_REPORT_STATUSES = ("done", "in_progress", "blocked")
_DIRECTIVE_STATUSES = ("returned", "deferred")

_DEADLINE_KINDS = ["exact", "before", "end_of_period", "relative", "unknown"]


def build_progress_schema(task_ids: Sequence[str]) -> dict:
    """Schema JSON của agent tiến độ; ``task_id`` là enum các mã trong danh sách việc.

    Trường ngắn (mã, enum, turn_id) đứng trước, văn bản tự do đứng cuối.

    Đầu vào: task_ids - mã các việc trong danh sách (không rỗng).
    Đầu ra: dict schema.
    """

    item = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "enum": list(task_ids)},
            "status": {"type": "string", "enum": list(UPDATE_STATUSES)},
            "status_turn_id": {"type": ["string", "null"]},
            "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
            "deadline": {"type": ["string", "null"]},
            "deadline_date": {"type": ["string", "null"]},
            "deadline_kind": {"type": "string", "enum": _DEADLINE_KINDS},
            "deadline_removed": {"type": "boolean"},
            "summary": {"type": "string"},
            "blockers": {"type": "array", "items": {"type": "string"}},
            "directive": {"type": ["string", "null"]},
        },
    }
    item["required"] = list(item["properties"])
    return {
        "type": "object",
        "properties": {"updates": {"type": "array", "items": item}},
        "required": ["updates"],
    }


def _build_user_prompt(task: SegmentTask, registry: SpeakerRegistry) -> str:
    """User prompt: người chủ trì, ngày họp, bối cảnh (danh bạ + danh sách việc), bản ghi đoạn.

    Đầu vào: task - gói dữ liệu đoạn chủ đề; registry - danh bạ cả cuộc họp.
    Đầu ra: str.
    """

    speakers = ", ".join(list_distinct_speaker_names(task["turns"])) or "(không rõ)"
    return (
        f"{format_chair_line(registry.chair)}\n\n"
        f"Ngày họp: {_format_meeting_date(task.get('meeting_date'))}\n\n"
        f"Bối cảnh:\n{format_registry_context(registry)}\n\n"
        f"Người nói trong đoạn này: {speakers}\n\n"
        f"Tiêu đề đoạn: {task['title']}\n"
        f"Tóm tắt đoạn: {task['summary']}\n\n"
        f"Bản ghi:\n{format_turns_as_transcript(task['turns'])}"
    )


def _read_blockers(value: object) -> tuple[str, ...]:
    """Đọc ``blockers``: tối đa ``_MAX_BLOCKERS`` chuỗi khác rỗng, đã cắt độ dài."""

    blockers = [read_stripped_text(entry)[:_MAX_BLOCKER_CHARS] for entry in read_list_or_empty(value)]
    return tuple(blocker for blocker in blockers if blocker)[:_MAX_BLOCKERS]


def _turn_positions(turns: Sequence[SpeakerTurn]) -> dict[str, int]:
    """turn_id -> vị trí trong ``turns``."""

    return {turn.turn_id: index for index, turn in enumerate(turns)}


def _update_position(update: ProgressUpdate, positions: Mapping[str, int]) -> int:
    """Vị trí của cập nhật trong bản ghi: lượt nêu trạng thái, không có thì bằng chứng muộn nhất."""

    if update.status_turn_id in positions:
        return positions[update.status_turn_id]
    return max((positions.get(turn_id, -1) for turn_id in update.evidence_ids), default=-1)


def _merge_same_task(updates: list[ProgressUpdate], turns: Sequence[SpeakerTurn]) -> list[ProgressUpdate]:
    """Gộp các mục cùng ``task_id`` trong MỘT chủ đề (prompt yêu cầu một mục mỗi việc).

    Mục chính là mục có trạng thái rõ (khác "mentioned", có lượt nêu trạng thái); cùng loại
    thì mục nói muộn hơn. Bằng chứng được hợp lại.

    Đầu vào: updates - cập nhật đã đọc, theo thứ tự model trả; turns - lượt nói của chủ đề.
    Đầu ra: list, mỗi ``task_id`` một mục, giữ thứ tự xuất hiện đầu tiên.
    """

    positions = _turn_positions(turns)

    def rank(update: ProgressUpdate) -> tuple[bool, int]:
        informative = update.status != "mentioned" and update.status_turn_id is not None
        return informative, _update_position(update, positions)

    merged: dict[str, ProgressUpdate] = {}
    for update in updates:
        kept = merged.get(update.task_id)
        if kept is None:
            merged[update.task_id] = update
            continue
        base, other = (update, kept) if rank(update) > rank(kept) else (kept, update)
        ids = list(base.evidence_ids)
        quotes = list(base.quotes)
        for turn_id, quote in zip(other.evidence_ids, other.quotes):
            if turn_id not in ids:
                ids.append(turn_id)
                quotes.append(quote)
        segment_ids = list(base.segment_ids)
        segment_ids.extend(item_id for item_id in other.segment_ids if item_id not in segment_ids)
        merged[update.task_id] = replace(
            base, evidence_ids=tuple(ids), quotes=tuple(quotes), segment_ids=tuple(segment_ids)
        )
    return list(merged.values())


def make_progress_agent(llm: LLMAdapter) -> Callable[[SegmentTask, SpeakerRegistry], dict]:
    """Tạo agent tiến độ (cùng chữ ký với ``extractors.make_extractor``).

    Đầu vào: llm - adapter LLM.
    Đầu ra: hàm ``(task, registry) -> dict`` trả ``progress_updates_raw`` và, khi LLM lỗi,
        ``topic_failures``.
    """

    def progress_agent(task: SegmentTask, registry: SpeakerRegistry) -> dict:
        """Trích cập nhật tiến độ (CHƯA kiểm) của các việc được nhắc trong MỘT chủ đề.

        Mục có ``task_id`` ngoài danh sách hoặc không có bằng chứng hợp lệ bị bỏ (ghi log);
        ``status`` lạ thành "mentioned"; ``status_turn_id`` không thuộc đoạn thành None
        (bước kiểm sẽ hạ trạng thái về "mentioned").

        Đầu vào: task - gói dữ liệu đoạn chủ đề; registry - danh bạ (có danh sách việc).
        Đầu ra: dict ``progress_updates_raw`` (+ ``topic_failures`` khi LLM lỗi).
        """

        segment_id = task["segment_id"]
        agenda = registry.agenda
        if not agenda.tasks:
            return {"progress_updates_raw": []}
        user_prompt = _build_user_prompt(task, registry)
        try:
            with llm_call("progress_agent", segment_id=segment_id, prompt_chars=len(user_prompt)):
                result = llm.generate_json(
                    system_prompt=PROGRESS_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema=build_progress_schema(agenda.task_ids),
                )
        except LLMUpstreamError as exc:
            logger.warning("progress_agent bỏ qua segment %s vì LLM lỗi: %s", segment_id, exc)
            return {"progress_updates_raw": [], "topic_failures": (TopicFailure(segment_id, "progress_agent", str(exc)),)}

        entries, dropped = split_dict_entries(result.get("updates"))
        updates: list[ProgressUpdate] = []
        turns = task["turns"]
        for item in entries:
            task_id = read_stripped_text(item.get("task_id"))
            if agenda.find(task_id) is None:
                dropped += 1
                continue
            status_turn_id = read_confirm_turn_id(turns, item.get("status_turn_id"))
            evidence_ids, quotes, segment_ids = validate_evidence_by_segment_ids(
                turns, read_list_or_empty(item.get("evidence_segment_ids")), [status_turn_id]
            )
            if not evidence_ids:
                dropped += 1
                continue
            status = item.get("status")
            deadline_raw = read_stripped_text(item.get("deadline")) or None
            deadline = _resolve_deadline(item, deadline_raw, task.get("meeting_date"))
            updates.append(
                ProgressUpdate(
                    segment_id=segment_id,
                    task_id=task_id,
                    status=status if status in UPDATE_STATUSES else "mentioned",
                    status_turn_id=status_turn_id,
                    evidence_ids=evidence_ids,
                    quotes=quotes,
                    segment_ids=segment_ids,
                    summary=read_stripped_text(item.get("summary"))[:_MAX_SUMMARY_CHARS],
                    blockers=_read_blockers(item.get("blockers")),
                    directive=read_stripped_text(item.get("directive"))[:_MAX_SUMMARY_CHARS],
                    deadline_raw=deadline_raw,
                    deadline_date=deadline.deadline_date,
                    deadline_kind=deadline.deadline_kind,
                    deadline_removed=item.get("deadline_removed") is True and deadline_raw is None,
                )
            )
        if dropped:
            logger.warning("progress_agent segment %s: bỏ %d mục sai mã việc/không có bằng chứng", segment_id, dropped)
        return {"progress_updates_raw": _merge_same_task(updates, turns)}

    return progress_agent


def _downgrade(update: ProgressUpdate, reason: str, **changes) -> ProgressUpdate:
    """Hạ cập nhật về "mentioned" (cờ ``uncertain``), giữ trạng thái agent khai để hiển thị."""

    return replace(
        update, status="mentioned", proposed_status=update.status, status_flag="uncertain", reason=reason, **changes
    )


def _describe(judgements: Sequence[ProgressActJudgement]) -> str:
    """Phân bố xác suất cho lý do; lượt nhiều đoạn thì ghi từng đoạn."""

    if len(judgements) == 1:
        return judgements[0].describe()
    return "; ".join(f"đoạn {number}: {j.describe()}" for number, j in enumerate(judgements, start=1))


def _check_status(
    update: ProgressUpdate,
    task: AgendaTask,
    turns: Sequence[SpeakerTurn],
    progress_judge: ProgressActJudge | None,
) -> ProgressUpdate:
    """Kiểm cập nhật có trạng thái bằng Decisions.

    Xét lượt nêu trạng thái agent chỉ ra trước, rồi các lượt bằng chứng còn lại từ lượt muộn
    nhất: gemma đôi khi để ``status_turn_id`` null, hoặc chọn lượt kết luận chung trong khi
    câu nêu trạng thái nằm ở lượt bằng chứng khác. Lượt dài được xét từng đoạn
    (``judge_turn_windows``). Lượt đầu tiên có một đoạn xác nhận trạng thái agent khai thì giữ
    và ghi lượt đó. Không lượt nào xác nhận: lượt xét đầu tiên chắc chắn nêu trạng thái rõ
    KHÁC thì sửa theo nó; còn lại hạ về "mentioned".

    Ngoại lệ cho câu hỏi chung (``report_task`` False): agent khai một trạng thái báo cáo
    (``_REPORT_STATUSES``) thì Decisions không sửa sang trạng thái báo cáo khác, vì câu hỏi này
    hay chấm tình trạng của đề án/dự án được nhắc thay cho tình trạng của việc. Lượt xét đầu
    tiên chắc chắn là báo cáo về việc (tổng xác suất nhóm báo cáo >= ``STATUS_CLEAR_MIN``) thì
    giữ trạng thái agent khai, cờ ``kept``. Decisions vẫn sửa sang chỉ đạo (làm lại/hoãn).
    """

    positions = _turn_positions(turns)
    first = [positions[update.status_turn_id]] if update.status_turn_id is not None else []
    evidence = sorted({positions[t] for t in update.evidence_ids if t in positions}, reverse=True)
    candidates = first + [index for index in evidence if index not in first]
    if progress_judge is None or not candidates:
        if update.status_turn_id is None:
            return _downgrade(update, "Không chỉ ra được lượt nói nêu trạng thái.")
        return replace(update, verification="unchecked")
    observed: list[tuple[str, tuple[ProgressActJudgement, ...]]] = []
    for index in candidates:
        try:
            judgements = judge_turn_windows(progress_judge, task.title, turns[index], turns[:index])
        except Exception as exc:  # lỗi mạng/API: giữ trạng thái agent khai, không quay về từ khoá
            logger.warning("progress_act lỗi ở %s/%s: %s", update.segment_id, update.task_id, exc)
            return replace(update, verification="unchecked", reason=f"Decisions lỗi: {exc}")
        turn_id = turns[index].turn_id
        support = max(judgements, key=lambda judgement: judgement.p_status(update.status))
        if support.p_status(update.status) >= STATUS_CLEAR_MIN:
            if turn_id == update.status_turn_id:
                reason = ""
            elif update.status_turn_id is None:
                reason = f"Agent không chỉ ra lượt nêu trạng thái; Decisions xác nhận ở lượt {turn_id}."
            else:
                reason = f"Decisions xác nhận ở lượt {turn_id}, không ở lượt agent chỉ ra {update.status_turn_id}."
            return replace(
                update, status_turn_id=turn_id, verification="decisions",
                status_probabilities=support.as_pairs(), reason=reason,
            )
        observed.append((turn_id, judgements))
    described = "; ".join(f"{turn_id}: {_describe(judgements)}" for turn_id, judgements in observed)
    first_turn_id, first_judgements = observed[0]
    held = update.status in _REPORT_STATUSES

    def flips_report(judgement: ProgressActJudgement, best: str) -> bool:
        return held and not judgement.report_task and best in _REPORT_STATUSES

    alternatives = [
        (p_best, judgement, best)
        for judgement in first_judgements
        for best, p_best in (judgement.best_status(),)
        if best not in (None, "mentioned", update.status) and not flips_report(judgement, best)
    ]
    if alternatives:
        p_best, judgement, best = max(alternatives, key=lambda alternative: alternative[0])
        if p_best >= STATUS_CLEAR_MIN:
            return replace(
                update,
                status=best,
                status_turn_id=first_turn_id,
                proposed_status=update.status,
                status_flag="revised",
                status_probabilities=judgement.as_pairs(),
                verification="decisions",
                reason=f"Decisions xếp lượt {first_turn_id} là {best} ({described}).",
            )
    reports = [
        judgement for judgement in first_judgements
        if held and not judgement.report_task and judgement.p_any(_REPORT_STATUSES) >= STATUS_CLEAR_MIN
    ]
    if reports:
        judgement = max(reports, key=lambda judgement: judgement.p_any(_REPORT_STATUSES))
        return replace(
            update,
            status_turn_id=first_turn_id,
            status_flag="kept",
            status_probabilities=judgement.as_pairs(),
            verification="decisions",
            reason=(
                f"Decisions xác nhận lượt {first_turn_id} là báo cáo về việc nhưng không xác nhận "
                f"{update.status} ({described}); giữ trạng thái agent khai."
            ),
        )
    best_support = max(
        (judgement for _, judgements in observed for judgement in judgements),
        key=lambda judgement: judgement.p_status(update.status),
    )
    return _downgrade(
        update,
        f"Decisions không xác nhận {update.status} ({described}).",
        status_probabilities=best_support.as_pairs(),
        verification="decisions",
    )


def _p_commit(turn_judge: TurnActJudge | None, turns: Sequence[SpeakerTurn], index: int) -> float | None:
    """Xác suất lượt ``index`` là chỉ đạo/kết luận (``turn_judge``), None nếu không đo được."""

    if turn_judge is None:
        return None
    try:
        return turn_judge.judge(turns[index], turns[:index]).p_commit
    except Exception as exc:
        logger.warning("turn_act lỗi ở lượt %s: %s", turns[index].turn_id, exc)
        return None


def _raise_mention(
    update: ProgressUpdate, status: str, turn_id: str, judgement: ProgressActJudgement, reason: str
) -> ProgressUpdate:
    """Nâng cập nhật "mentioned" lên ``status`` theo Decisions (cờ ``revised``)."""

    return replace(
        update,
        status=status,
        status_turn_id=turn_id,
        proposed_status="mentioned",
        status_flag="revised",
        status_probabilities=judgement.as_pairs(),
        verification="decisions",
        reason=reason,
    )


def _check_mention(
    update: ProgressUpdate,
    task: AgendaTask,
    turns: Sequence[SpeakerTurn],
    progress_judge: ProgressActJudge | None,
    turn_judge: TurnActJudge | None,
) -> ProgressUpdate | None:
    """Kiểm cập nhật "mentioned": các lượt bằng chứng có thật sự nói về việc này không.

    Xét từ lượt bằng chứng muộn nhất, dừng ở lượt đầu tiên có một đoạn Decisions không xếp là
    "không nói về việc này" (p(khac) < ``STATUS_CLEAR_MIN``):
    - lượt đó chắc chắn là BÁO CÁO (``_REPORT_STATUSES``): nâng lên trạng thái đó, vì báo cáo
      tự đứng được trong một lượt;
    - lượt đó chắc chắn yêu cầu làm lại/hoãn (``_DIRECTIVE_STATUSES``): chỉ nâng khi
      ``turn_judge`` cũng xếp lượt là chỉ đạo/kết luận (p_commit >= ``COMMIT_CLEAR_MIN``). Câu
      hỏi của ``turn_judge`` phân biệt chỉ đạo của người chủ trì với kiến nghị của đại biểu, nên
      đề nghị làm lại của một thành viên không thành "returned";
    - còn lại: giữ "mentioned".
    Mọi lượt đều "không nói về việc này" thì trả None (bỏ cập nhật: agent gắn nhầm việc, vd.
    trùng một từ hay chỉ nhắc chung cả đề án).
    """

    if progress_judge is None:
        return replace(update, verification="unchecked")
    positions = _turn_positions(turns)
    indexes = sorted({positions[turn_id] for turn_id in update.evidence_ids if turn_id in positions}, reverse=True)
    if not indexes:  # parser đã bỏ cập nhật không có bằng chứng trong chủ đề
        return replace(update, verification="unchecked")
    observed = []
    for index in indexes:
        try:
            judgements = judge_turn_windows(progress_judge, task.title, turns[index], turns[:index])
        except Exception as exc:  # lỗi mạng/API: giữ cập nhật, không quay về từ khoá
            logger.warning("progress_act lỗi ở %s/%s: %s", update.segment_id, update.task_id, exc)
            return replace(update, verification="unchecked", reason=f"Decisions lỗi: {exc}")
        closest = min(judgements, key=lambda judgement: judgement.p_unrelated())
        if closest.p_unrelated() >= STATUS_CLEAR_MIN:
            observed.append(f"{turns[index].turn_id} ({_describe(judgements)})")
            continue
        turn_id = turns[index].turn_id
        described = _describe(judgements)
        p_report, report, judgement = max(
            ((j.p_status(status), status, j) for j in judgements for status in _REPORT_STATUSES),
            key=lambda found: found[0],
        )
        if p_report >= STATUS_CLEAR_MIN:
            return _raise_mention(
                update, report, turn_id, judgement,
                f"Agent khai chỉ nhắc tới; Decisions xếp lượt {turn_id} là báo cáo {report} ({described}).",
            )
        p_order, order, judgement = max(
            ((j.p_status(status), status, j) for j in judgements for status in _DIRECTIVE_STATUSES),
            key=lambda found: found[0],
        )
        reason = ""
        if p_order >= STATUS_CLEAR_MIN:
            p_commit = _p_commit(turn_judge, turns, index)
            if p_commit is not None and p_commit >= COMMIT_CLEAR_MIN:
                return _raise_mention(
                    update, order, turn_id, judgement,
                    f"Agent khai chỉ nhắc tới; Decisions xếp lượt {turn_id} là {order} ({described}), "
                    f"lượt chỉ đạo/kết luận (p_commit {p_commit:.2f}).",
                )
            commit = "không đo được" if p_commit is None else f"p_commit {p_commit:.2f}"
            reason = f"Decisions xếp lượt {turn_id} là {order} nhưng lượt không phải chỉ đạo/kết luận ({commit})."
        return replace(update, verification="decisions", status_probabilities=closest.as_pairs(), reason=reason)
    logger.info(
        "progress: bỏ cập nhật %s ở %s vì Decisions xếp mọi lượt bằng chứng là không nói về việc này: %s",
        update.task_id, update.segment_id, "; ".join(observed),
    )
    return None


def _measure_directive(
    update: ProgressUpdate, turns: Sequence[SpeakerTurn], turn_judge: TurnActJudge | None
) -> ProgressUpdate:
    """Ghi ``p_directive``: xác suất lượt nêu trạng thái là chỉ đạo/kết luận (``turn_judge``).

    Chỉ đo cho cập nhật còn giữ trạng thái khác "mentioned" (ứng viên thắng ở ``finalize``).
    """

    if turn_judge is None or update.status == "mentioned" or update.status_turn_id is None:
        return update
    index = _turn_positions(turns)[update.status_turn_id]
    try:
        p_directive = turn_judge.judge(turns[index], turns[:index]).p_commit
    except Exception as exc:
        logger.warning("turn_act lỗi khi đo chỉ đạo ở %s/%s: %s", update.segment_id, update.task_id, exc)
        return update
    return replace(update, p_directive=p_directive)


def check_progress_updates(
    updates: Sequence[ProgressUpdate],
    turns: Sequence[SpeakerTurn],
    agenda: TaskAgenda,
    progress_judge: ProgressActJudge | None = None,
    turn_judge: TurnActJudge | None = None,
) -> list[ProgressUpdate]:
    """Kiểm các cập nhật tiến độ của MỘT chủ đề (gọi trong ``evidence_check``).

    Cập nhật có trạng thái đi ``_check_status`` rồi đo ``p_directive``; cập nhật "mentioned"
    đi ``_check_mention`` (có thể bị bỏ). Các cập nhật được kiểm song song vì mỗi cập nhật
    cần vài lời gọi Decisions.

    Đầu vào: updates - cập nhật thô của chủ đề; turns - lượt nói của chủ đề; agenda - danh
        sách việc; progress_judge - Decisions cho lượt nêu trạng thái (None = không kiểm);
        turn_judge - Decisions cho lượt chỉ đạo/kết luận (None = không đo ``p_directive``).
    Đầu ra: list cập nhật đã kiểm theo thứ tự đầu vào, trừ cập nhật bị bỏ (việc lạ hoặc
        "mentioned" mà mọi lượt bằng chứng đều không nói về việc).
    """

    turns = tuple(turns)

    def check(update: ProgressUpdate) -> ProgressUpdate | None:
        task = agenda.find(update.task_id)
        if task is None:  # parser đã lọc; phòng khi danh sách việc đổi giữa chừng
            return None
        if update.status == "mentioned":
            checked = _check_mention(update, task, turns, progress_judge, turn_judge)
        else:
            checked = _check_status(update, task, turns, progress_judge)
        return None if checked is None else _measure_directive(checked, turns, turn_judge)

    if not updates:
        return []
    with ThreadPoolExecutor(max_workers=min(len(updates), _MAX_PARALLEL_CHECKS)) as pool:
        checked = list(pool.map(check, updates))
    return [update for update in checked if update is not None]


def _is_confirmed(update: ProgressUpdate) -> bool:
    """Cập nhật có trạng thái rõ (không phải "mentioned", không bị hạ vì chưa chắc; ``kept`` vẫn tính)."""

    return update.status != "mentioned" and update.status_flag != "uncertain"


def _is_directive(update: ProgressUpdate) -> bool:
    """Lượt nêu trạng thái là chỉ đạo/kết luận theo ``turn_judge``."""

    return update.p_directive is not None and update.p_directive >= COMMIT_CLEAR_MIN


def _is_overdue(due: str | None, meeting_date: str | None, status: str) -> bool:
    """Hạn cũ đã qua so với ngày họp mà việc chưa xong."""

    if not due or not meeting_date or status == "done":
        return False
    try:
        return date.fromisoformat(due) < date.fromisoformat(meeting_date)
    except ValueError:
        return False


def summarize_task_progress(
    agenda: TaskAgenda,
    updates: Sequence[ProgressUpdate],
    meeting_turns: Sequence[SpeakerTurn],
    meeting_date: str | None,
) -> tuple[TaskProgress, ...]:
    """Gộp cập nhật của mọi chủ đề thành MỘT dòng tiến độ cho mỗi việc trong danh sách.

    Cập nhật thắng: trong các cập nhật có trạng thái rõ, lượt chỉ đạo/kết luận thắng lượt
    báo cáo, cùng loại thì lượt muộn hơn thắng; không có cập nhật rõ thì lấy cập nhật muộn
    nhất (trạng thái "mentioned"). Việc không có cập nhật nào là "not_reported".
    ``status_conflict`` chỉ bật khi có báo cáo "done" đã xác nhận cùng một trạng thái rõ khác
    (vd. báo cáo xong nhưng bị yêu cầu làm lại); "đang làm" rồi bị trả lại hay "vướng" rồi
    "đang làm" là diễn tiến bình thường, không phải mâu thuẫn.

    Đầu vào: agenda - danh sách việc; updates - cập nhật đã kiểm của mọi chủ đề;
        meeting_turns - lượt nói cả cuộc họp theo thứ tự; meeting_date - ngày họp ISO hoặc None.
    Đầu ra: tuple TaskProgress theo thứ tự của danh sách việc.
    """

    positions = _turn_positions(meeting_turns)
    result = []
    for task in agenda.tasks:
        own = sorted(
            (update for update in updates if update.task_id == task.task_id),
            key=lambda update: _update_position(update, positions),
        )
        base = TaskProgress(
            task_id=task.task_id,
            title=task.title,
            owner=task.owner.name,
            previous_status=task.last_status,
            status="not_reported",
            previous_due=task.due,
        )
        if not own:
            result.append(replace(base, overdue=_is_overdue(task.due, meeting_date, "not_reported")))
            continue
        confirmed = [update for update in own if _is_confirmed(update)]
        confirmed_statuses = {update.status for update in confirmed}
        if confirmed:
            winner = max(confirmed, key=lambda u: (_is_directive(u), _update_position(u, positions)))
        else:
            winner = own[-1]
        with_deadline = [u for u in (confirmed or own) if u.deadline_raw or u.deadline_removed]
        deadline_source = winner if (winner.deadline_raw or winner.deadline_removed) else (
            with_deadline[-1] if with_deadline else None
        )
        result.append(
            replace(
                base,
                status=winner.status,
                deadline_raw=deadline_source.deadline_raw if deadline_source else None,
                deadline_date=deadline_source.deadline_date if deadline_source else None,
                deadline_kind=deadline_source.deadline_kind if deadline_source else "unknown",
                deadline_removed=deadline_source.deadline_removed if deadline_source else False,
                status_conflict="done" in confirmed_statuses and len(confirmed_statuses) >= 2,
                uncertain=winner.status_flag == "uncertain",
                overdue=_is_overdue(task.due, meeting_date, winner.status),
                deciding_update=winner,
                updates=tuple(own),
            )
        )
    return tuple(result)


def _party_keys(task: AgendaTask) -> tuple[set[str], set[str]]:
    """Mã và tên đã chuẩn hoá của bên chủ trì + phối hợp."""

    refs = {party.ref_id for party in task.parties if party.ref_id}
    names = {normalize_name_key(party.name) for party in task.parties}
    return refs, names


def link_assignment_to_agenda(item: ActionItemV3, agenda: TaskAgenda) -> ActionItemV3:
    """Gán quan hệ của việc giao với danh sách việc (gọi trong ``finalize``, sau định danh actor).

    - không có danh sách việc: giữ nguyên (``relation`` None);
    - không có ``task_id`` hoặc mã không có trong danh sách: "new" (mã lạ bị xoá);
    - việc do người khác giao (không phải "self_committed"/"reported") mà mọi bên nhận việc
      đã định danh đều ngoài bên chủ trì/phối hợp của việc cũ: "reassign";
    - hạn mới khác hạn cũ: "reschedule";
    - còn lại: "follow_up".
    Bên nhận việc chưa định danh được không tính là giao lại (không đủ căn cứ). Việc một bên
    tự nhận hay báo cáo cũng không phải giao lại, vì không ai giao. Việc qua Verifier giữ
    status agent khai ("proposed"/"unknown") nên vẫn được xét.

    Đầu vào: item - việc giao đã định danh actor; agenda - danh sách việc.
    Đầu ra: ActionItemV3 có ``relation`` (và ``task_id`` đã kiểm).
    """

    if not agenda.tasks:
        return item
    task = agenda.find(item.task_id)
    if task is None:
        return replace(item, task_id=None, relation="new")
    refs, names = _party_keys(task)
    resolved = [assignee for assignee in item.assignees if assignee.name]
    given_by_someone = item.status not in ("self_committed", "reported")
    if given_by_someone and resolved and not any(
        (assignee.ref_id and assignee.ref_id in refs) or normalize_name_key(assignee.name) in names
        for assignee in resolved
    ):
        return replace(item, relation="reassign")
    if item.deadline_date and task.due and item.deadline_date != task.due:
        return replace(item, relation="reschedule")
    return replace(item, relation="follow_up")


__all__ = [
    "build_progress_schema",
    "check_progress_updates",
    "link_assignment_to_agenda",
    "make_progress_agent",
    "summarize_task_progress",
]
