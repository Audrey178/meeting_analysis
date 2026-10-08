"""Node Decision Agent: trích các phát biểu KẾT LUẬN/CHỐT PHƯƠNG ÁN trong MỘT đoạn chủ đề.

Tách ra từ agent gộp trước đây (``action_decision_agent``, xem lịch sử ở
``be/DESIGN.md``) theo đúng sơ đồ 3-agent (Content/Action/Decision): giờ là
MỘT lời gọi LLM riêng, không còn sinh chung với action_items trong cùng một
lời gọi. Số lời gọi LLM/chủ đề tăng theo đó (xem ``..graph``).

Output đi vào ``decision_candidates_raw`` (CHƯA kiểm chứng) --
``nodes.evidence_check.check_topic_evidence`` lọc CLEAR/UNCERTAIN trước khi
vào ``decision_candidates`` thật (candidate uncertain phải qua
``debate_and_judge_agent`` trước -- đây chính là câu hỏi "có thực sự được
xác nhận là quyết định?" trong sơ đồ gốc). Cách nối vào graph xem ``..graph``.
"""

from __future__ import annotations

import logging

from .._shared import (
    format_turns_as_transcript,
    read_confirm_turn_id,
    read_list_or_empty,
    read_stripped_text,
    split_dict_entries,
    validate_evidence_by_turn_ids,
)
from ..schemas import DecisionCandidate, SegmentTask, TopicFailure
from ...utils.llm_call_log import llm_call
from ...utils.ports import LLMAdapter, LLMUpstreamError

logger = logging.getLogger(__name__)

DECISION_SYSTEM_PROMPT = """
Bạn trích các KẾT LUẬN/CHỐT PHƯƠNG ÁN trong MỘT đoạn chủ đề của cuộc họp:
một lựa chọn đã được người chủ trì kết luận hoặc cả nhóm THỐNG NHẤT (vd. chọn
phương án A thay vì B, thống nhất cách làm, phạm vi, lịch chung).

KHÔNG lấy (dù câu nghe rất chắc chắn):
- báo cáo tình hình, số liệu, tiến độ, việc đã làm/đang làm;
- ước tính, dự báo, nhận định, ý kiến của một thành viên;
- đề xuất/kiến nghị chưa được ai xác nhận, hoặc bị gạt đi/hoãn lại;
- câu mở đầu, giới thiệu, thủ tục, khẩu hiệu ("giữ vững kỷ cương...");
- kế hoạch/văn bản đã ban hành từ trước chỉ được nhắc lại;
- phương án đã chốt rồi bị THAY THẾ bởi phương án khác ở sau trong đoạn --
  chỉ lấy phương án cuối cùng;
- giao việc cho một người/đơn vị cụ thể (thuộc agent khác).

Với mỗi kết luận, khai trung thực:
- status: "agreed" (đã kết luận/thống nhất), "proposed" (mới là đề xuất),
  "reported" (báo cáo/nhận định). Không chắc thì chọn "proposed" -- mục sẽ
  được kiểm lại, không bị mất.
- confirm_turn_id: turn_id của lượt nói CHỐT (người chủ trì kết luận hoặc lượt
  đồng ý cuối cùng). Phải là một trong evidence_turn_ids.

text: một câu súc tích nêu NỘI DUNG kết luận. Mỗi kết luận chỉ xuất hiện MỘT
lần -- nếu cùng một kết luận được nhắc nhiều lần, gộp thành một mục.

Mỗi phần tử PHẢI kèm evidence_turn_ids: danh sách các turn_id của những turn
chứa phát biểu đó. Chọn evidence_turn_ids TRƯỚC khi viết text -- không viết
trước rồi mới tìm bằng chứng khớp. KHÔNG chép lại nội dung turn.

turn_id CHỈ LÀ phần đứng TRƯỚC dấu "|" bên trong ngoặc vuông đầu mỗi dòng
bản ghi -- KHÔNG bao gồm dấu ngoặc vuông, KHÔNG bao gồm tên người nói,
KHÔNG bao gồm dấu "|". Ví dụ dòng bản ghi "[TURN_000020|Phạm Hồng Sơn] Nội
dung..." thì turn_id là "TURN_000020" -- TUYỆT ĐỐI KHÔNG phải
"[TURN_000020|Phạm Hồng Sơn]" hay "TURN_000020|Phạm Hồng Sơn".

NGÔI THỨ BA: KHÔNG BAO GIỜ dùng đại từ ngôi thứ nhất/nhị trần trụi ("tôi",
"em", "anh", "chị", "mình", "bọn em", "chúng tôi", ...) trong text để chỉ
một người cụ thể -- dùng tên thật nếu bản ghi nêu rõ, hoặc cụm trung tính
("nhóm phụ trách") nếu không đủ căn cứ.
""".strip()

DECISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_turn_ids": {"type": "array", "items": {"type": "string"}},
                    "confirm_turn_id": {"type": ["string", "null"]},
                    "status": {"type": "string", "enum": ["agreed", "proposed", "reported"]},
                    "text": {"type": "string"},
                },
                "required": ["evidence_turn_ids", "confirm_turn_id", "status", "text"],
            },
        },
    },
    "required": ["decisions"],
}

_DECISION_STATUSES = frozenset({"agreed", "proposed", "reported"})


def _build_decision_user_prompt(task: SegmentTask) -> str:
    """Dựng user prompt cho Decision Agent: tiêu đề, tóm tắt và bản ghi của đoạn.

    Không cần ``previous_context``/danh sách người nói: decisions không gắn
    với một người chịu trách nhiệm nên không cần quy "em"/"anh" về tên thật
    (đó là việc của Action Agent).

    Đầu vào: task - gói dữ liệu của một đoạn chủ đề.
    Đầu ra: str - nội dung user prompt.
    """

    return (
        f"Tiêu đề đoạn: {task['title']}\n"
        f"Tóm tắt đoạn: {task['summary']}\n\n"
        f"Bản ghi:\n{format_turns_as_transcript(task['turns'])}"
    )


def make_decision_agent(llm: LLMAdapter):
    """Tạo node ``decision_agent`` gắn với một LLM cụ thể.

    Đầu vào: llm - adapter LLM có ``generate_json``.
    Đầu ra: hàm node ``decision_agent(task)`` để đăng ký vào graph.
    """

    def decision_agent(task: SegmentTask) -> dict:
        """Trích quyết định/chốt phương án (CHƯA kiểm chứng) cho MỘT đoạn chủ đề.

        Mục nào thiếu nội dung hoặc thiếu trích dẫn hợp lệ bị loại (có ghi log); JSON
        sai hình dạng được xử lý như mục xấu chứ không làm sập cả đoạn. Nếu LLM lỗi
        (``LLMUpstreamError``), trả kết quả rỗng kèm ``TopicFailure`` để graph thử lại sau.

        Đầu vào: task - gói dữ liệu của đoạn chủ đề.
        Đầu ra: dict cập nhật state gồm ``decision_candidates_raw``, dấu hoàn
            thành ``completed_decision_topics`` và (khi lỗi) ``topic_failures``.
        """

        segment_id = task["segment_id"]
        # Dấu "nhánh Decision của chủ đề này đã xong", trả cả ở đường lỗi.
        done = {"completed_decision_topics": (segment_id,)}
        user_prompt = _build_decision_user_prompt(task)
        try:
            with llm_call("decision_agent", segment_id=segment_id, prompt_chars=len(user_prompt)):
                result = llm.generate_json(
                    system_prompt=DECISION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema=DECISION_SCHEMA,
                )
        except LLMUpstreamError as exc:
            logger.warning("decision_agent bỏ qua segment %s vì LLM lỗi: %s", segment_id, exc)
            failure = TopicFailure(segment_id, "decision_agent", str(exc))
            return {"decision_candidates_raw": [], "topic_failures": (failure,), **done}

        entries, dropped = split_dict_entries(result.get("decisions"))
        decisions: list[DecisionCandidate] = []
        for item in entries:
            text = read_stripped_text(item.get("text"))
            confirm_turn_id = read_confirm_turn_id(task["turns"], item.get("confirm_turn_id"))
            # Lượt chốt luôn là bằng chứng, kể cả khi model quên liệt kê nó.
            claimed_ids = read_list_or_empty(item.get("evidence_turn_ids")) + [confirm_turn_id]
            evidence_ids, quotes = validate_evidence_by_turn_ids(task["turns"], claimed_ids)
            if not text or not evidence_ids:
                dropped += 1
                continue
            status = item.get("status")
            decisions.append(
                DecisionCandidate(
                    segment_id=segment_id,
                    text=text,
                    evidence_ids=evidence_ids,
                    quotes=quotes,
                    status=status if status in _DECISION_STATUSES else "unknown",
                    confirm_turn_id=confirm_turn_id,
                )
            )
        if dropped:
            logger.warning(
                "decision_agent segment %s: bỏ %d mục không có text/trích dẫn hợp lệ",
                segment_id,
                dropped,
            )
        return {"decision_candidates_raw": decisions, **done}

    return decision_agent


__all__ = ["DECISION_SYSTEM_PROMPT", "DECISION_SCHEMA", "make_decision_agent"]
