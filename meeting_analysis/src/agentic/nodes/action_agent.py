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
    validate_evidence_by_turn_ids,
)
from ..deadline import UNKNOWN_DEADLINE, NormalizedDeadline, normalize_deadline
from ..schemas import ActionItemCandidate, SegmentTask, TopicFailure
from ...utils.llm_call_log import llm_call
from ...utils.ports import LLMAdapter, LLMUpstreamError

logger = logging.getLogger(__name__)

ACTION_SYSTEM_PROMPT = """
Bạn trích các VIỆC ĐƯỢC GIAO/NHẬN trong MỘT đoạn chủ đề của cuộc họp: ai
(actor) làm việc gì (text), thời hạn nếu có (deadline, deadline_date, deadline_kind).

CHỈ lấy khi có một trong hai:
- người chủ trì/cấp có thẩm quyền GIAO việc cho một người/đơn vị cụ thể;
- một người/đơn vị TỰ NHẬN việc và không bị ai phản đối -- kể cả khi họ nêu
  việc cụ thể đơn vị mình SẼ làm ("Sở sẽ trình kế hoạch trước 31/3", "bên em
  sẽ cấp giống đợt 2"): đó là cam kết, không phải báo cáo.
KHÔNG lấy: đề xuất/kiến nghị/yêu cầu của thành viên mà chưa ai chấp nhận;
việc ĐÃ làm xong hoặc ĐANG làm chỉ được báo cáo tiến độ; lời mời/điều phối buổi họp ("mời
anh X trình bày"); quy định chung không gắn người thực hiện; phát biểu chốt
phương án mà không có người thực hiện (thuộc agent khác).

Với mỗi việc, khai trung thực:
- status: "assigned" (được giao), "self_committed" (tự nhận), "proposed"
  (mới là đề xuất/yêu cầu chưa ai chấp nhận), "reported" (báo cáo việc đã/đang
  làm). Việc người/đơn vị tự nói SẼ làm là "self_committed". Không chắc thì chọn "proposed" -- việc sẽ được kiểm lại, không bị mất.
- confirm_turn_id: turn_id của lượt nói GIAO hoặc NHẬN việc (lượt mà nếu bỏ đi
  thì không còn ai được giao). Phải là một trong evidence_turn_ids.
- deadline: thời hạn đúng như bản ghi nói ("trước 25/11", "trong tuần này"),
  null nếu không nêu. Chép NGUYÊN CẢ CỤM, giữ các từ "trước", "chậm nhất",
  "cuối", "trong", "khoảng" ("trước ngày 15 tháng 11", không phải "15 tháng 11").
  KHÔNG bịa thời hạn mà bản ghi không nói.
- deadline_date, deadline_kind: quy deadline về ngày theo QUY TẮC CHUẨN HOÁ HẠN
  bên dưới. deadline null thì deadline_date null và deadline_kind "unknown".

QUY TẮC CHUẨN HOÁ HẠN (neo theo "Ngày họp" trong user prompt):
- deadline_date là ngày "YYYY-MM-DD"; deadline_kind là một trong:
  "exact" (ngày cụ thể: "ngày 15/11", "15-11-2026"),
  "before" (hạn chót tới một ngày cụ thể: "trước ngày 15 tháng 11", "chậm nhất thứ Sáu"),
  "end_of_period" (cuối một kỳ nêu rõ: "cuối tháng", "cuối quý", "quý IV", "cuối tuần", "trong tháng 12"),
  "relative" (tính lệch từ ngày họp: "tuần sau", "sang tuần", "tháng sau", "trong tuần này",
  "khoảng 3 tuần", "10 ngày nữa"),
  "unknown" (không quy được ra ngày: "sau POC", "khi có số liệu", ngày không tồn tại như 31/2).
- Ngày/tháng viết số luôn theo thứ tự NGÀY/THÁNG. Thiếu năm thì lấy năm của ngày họp;
  nếu ngày đó đã qua so với ngày họp thì lấy năm sau (quý/tháng đã qua cũng vậy).
- Tuần kết thúc vào CHỦ NHẬT: "tuần sau"/"sang tuần"/"tuần tới" = Chủ nhật tuần kế;
  "trong tuần này"/"cuối tuần" = Chủ nhật tuần này; "đầu tuần" = thứ Hai, "giữa tuần" = thứ Tư.
- "tháng sau"/"sang tháng" = ngày cuối tháng kế; "cuối tháng" = ngày cuối tháng họp;
  "đầu tháng sau" = ngày 10, "giữa tháng sau" = ngày 20 của tháng kế.
- "cuối quý" = ngày cuối quý hiện tại; "quý I..IV" = ngày cuối quý đó (31/3, 30/6, 30/9, 31/12);
  "cuối năm" = 31/12.
- Khoảng thời gian ("khoảng 3 tuần", "trong 10 ngày", "2 tháng nữa") = ngày họp cộng khoảng đó.
- "thứ X" = thứ X gần nhất từ ngày họp trở đi; "thứ X tuần sau" = thứ X của tuần kế.
- "A hoặc B", "từ A đến B" = lấy mốc MUỘN hơn.
- Không có ngày họp, hoặc mốc gắn với sự kiện chứ không với lịch: deadline_date null
  (vẫn khai deadline_kind nếu xác định được). KHÔNG đoán khi không chắc.

text: chỉ là NỘI DUNG CÔNG VIỆC, bắt đầu bằng động từ (vd. "Map lại nhãn sang
12 lĩnh vực và train lại mô hình phân loại"). TUYỆT ĐỐI KHÔNG mở đầu bằng
"giao", "phân công", tên người phụ trách hay "X sẽ" -- người đã nằm ở actor;
KHÔNG lặp thời hạn trong text -- thời hạn nằm ở deadline.

Mỗi việc chỉ xuất hiện MỘT lần: nếu cùng một việc được nhắc nhiều lần trong
đoạn (bàn rồi chốt lại), gộp thành một mục với mọi turn_id liên quan. Việc đã
có trong "Việc đã được giao ở các chủ đề trước" thì KHÔNG lấy lại, trừ khi đoạn
này giao thêm phần việc mới.

Mỗi phần tử PHẢI kèm evidence_turn_ids: danh sách các turn_id của những turn
chứa phát biểu đó. Chọn evidence_turn_ids TRƯỚC khi viết text -- không viết
trước rồi mới tìm bằng chứng khớp. KHÔNG chép lại nội dung turn.

turn_id CHỈ LÀ phần đứng TRƯỚC dấu "|" bên trong ngoặc vuông đầu mỗi dòng
bản ghi -- KHÔNG bao gồm dấu ngoặc vuông, KHÔNG bao gồm tên người nói,
KHÔNG bao gồm dấu "|". Ví dụ dòng bản ghi "[TURN_000020|Phạm Hồng Sơn] Nội
dung..." thì turn_id là "TURN_000020" -- TUYỆT ĐỐI KHÔNG phải
"[TURN_000020|Phạm Hồng Sơn]" hay "TURN_000020|Phạm Hồng Sơn".

NGÔI THỨ BA -- áp dụng cho actor: KHÔNG BAO GIỜ dùng đại từ ngôi thứ nhất/nhị
trần trụi ("tôi", "em", "anh", "chị", "mình", "bọn em", "chúng tôi", ...) để
chỉ một người cụ thể. Nếu bản ghi nêu tên thật, dùng ĐÚNG NGUYÊN VĂN tên đó
-- không tự thêm họ/chức danh, không tự sửa tên. Nếu bản ghi chỉ gọi bằng
đại từ, xác định người đó dựa vào "Người nói trong đoạn này" và "Bối cảnh từ
các chủ đề trước" (ai đang nói với ai, ai đã được nhắc tên, ai đã được giao
việc). Nếu không đủ căn cứ để chắc chắn đó là ai, để actor là null -- KHÔNG
được để actor là chính đại từ đó hay một cụm chung chung ("một thành viên",
"nhóm"), và KHÔNG được đoán bừa một cái tên không có căn cứ.
""".strip()

ACTION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_turn_ids": {"type": "array", "items": {"type": "string"}},
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
                    "evidence_turn_ids", "confirm_turn_id", "status", "actor", "text",
                    "deadline", "deadline_date", "deadline_kind",
                ],
            },
        },
    },
    "required": ["action_items"],
}

_ACTION_STATUSES = frozenset({"assigned", "self_committed", "proposed", "reported"})
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
    """Lấy deadline_date/deadline_kind LLM đã quy theo QUY TẮC CHUẨN HOÁ HẠN của prompt.

    LLM trả ngày không phải ISO hợp lệ, hoặc kind lạ/"unknown" mà luật vẫn quy được, thì
    dùng luật ``normalize_deadline`` làm lưới an toàn. Không có ``deadline_raw`` thì
    luôn là ``unknown``.

    Đầu vào: item - một phần tử ``action_items`` LLM trả; deadline_raw - hạn nguyên văn
        đã làm sạch; meeting_date - ngày họp ISO hoặc None.
    Đầu ra: NormalizedDeadline.
    """

    if not deadline_raw:
        return UNKNOWN_DEADLINE
    fallback = normalize_deadline(deadline_raw, meeting_date)
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
    if llm_date is None and fallback.deadline_date:
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
        f"Bối cảnh từ các chủ đề trước: {task['previous_context']}\n\n"
        f"Người nói trong đoạn này: {speakers}\n\n"
        f"Tiêu đề đoạn: {task['title']}\n"
        f"Tóm tắt đoạn: {task['summary']}\n\n"
        f"Bản ghi:\n{format_turns_as_transcript(task['turns'])}"
    )


def make_action_agent(llm: LLMAdapter):
    """Tạo node ``action_agent`` gắn với một LLM cụ thể.

    Đầu vào: llm - adapter LLM có ``generate_json``.
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
        LLM tự quy hạn nguyên văn (``deadline_raw``) về ``deadline_date``/``deadline_kind``
        theo QUY TẮC CHUẨN HOÁ HẠN trong prompt, neo theo ngày họp; kết quả sai định dạng
        thì dùng luật ``..deadline.normalize_deadline`` (``_resolve_deadline``).
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
                    system_prompt=ACTION_SYSTEM_PROMPT,
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
            claimed_ids = read_list_or_empty(item.get("evidence_turn_ids")) + [confirm_turn_id]
            evidence_ids, quotes = validate_evidence_by_turn_ids(task["turns"], claimed_ids)
            if not text or not evidence_ids:
                dropped += 1
                continue
            actor = read_stripped_text(item.get("actor")) or None
            if actor is not None and is_bare_personal_pronoun(actor):
                actor = None
            status = item.get("status")
            deadline_raw = read_stripped_text(item.get("deadline")) or None
            deadline = _resolve_deadline(item, deadline_raw, task.get("meeting_date"))
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


__all__ = ["ACTION_SYSTEM_PROMPT", "ACTION_SCHEMA", "make_action_agent"]
