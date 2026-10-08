"""Node Content Agent: trích luận điểm của từng người nói trong MỘT đoạn chủ đề.

Đổi tên từ ``speaker_opinion_agent`` (xem lịch sử ở ``be/DESIGN.md``) theo
đúng sơ đồ 3-agent (Content/Action/Decision) -- logic không đổi. Cách nối
vào graph xem ``..graph``. Node chạy một lần cho mỗi đoạn chủ đề (được gửi
qua ``Send``), không bao giờ thấy cả cuộc họp, chỉ thấy các lượt nói của
đúng đoạn của nó (``..schemas.SegmentTask``).

Khác với Action/Decision Agent: output của Content Agent đi THẲNG vào
``meeting_development`` (không qua evidence-check/debate) -- sơ đồ gốc không
vẽ Evidence Check cho Content, vì "diễn biến họp" là tường thuật lại luận
điểm đã nói, không phải một khẳng định cần xác nhận đúng/sai như action/decision.
"""

from __future__ import annotations

import logging

from .._shared import (
    is_assignment_point,
    validate_evidence_by_turn_ids,
    make_speaker_initials,
    match_claimed_name_to_real_speaker,
    format_turns_as_transcript,
    read_list_or_empty,
    read_stripped_text,
    split_dict_entries,
)
from ..schemas import SegmentTask, SpeakerPoint, SpeakerSection, TopicFailure
from ...utils.llm_call_log import llm_call
from ...utils.ports import LLMAdapter, LLMUpstreamError

logger = logging.getLogger(__name__)

CONTENT_SYSTEM_PROMPT = """
Bạn trích luận điểm thảo luận của từng người nói trong MỘT đoạn chủ đề của
cuộc họp. Chỉ dùng nội dung được cung cấp, không suy diễn thêm.

BẮT BUỘC viết ở NGÔI THỨ BA: text của mỗi luận điểm không được chứa đại từ
ngôi thứ nhất/nhị ("tôi", "em", "anh", "chị", "mình", "bọn em", "chúng
tôi", ...) để chỉ MỘT NGƯỜI CỤ THỂ khác với người nói chính của luận điểm
đó. Nếu luận điểm có nhắc đến người khác bằng đại từ như vậy, dùng tên thật
của người đó khi bản ghi của đoạn này nêu rõ ai là ai; nếu không đủ căn cứ
để xác định, dùng cụm trung tính như "một thành viên khác" thay vì giữ
nguyên đại từ hay tự đoán một cái tên. 

Với mỗi người nói xuất hiện trong đoạn, liệt kê các luận điểm (points) họ
đã nêu, CÔ ĐỌNG theo các quy tắc sau:
- Với mỗi người nói xuất hiện trong đoạn, xác định các Ý CHÍNH mà người đó đưa ra và thực hiện SEMANTIC CONSOLIDATION (HỢP NHẤT THEO NGỮ NGHĨA)
- CHỈ ĐƯỢC Tối đa 5 luận điểm cho mỗi người nói trong đoạn này. Chỉ giữ ý chính phục
  vụ chủ đề của đoạn (đề xuất, nhận định, lý do, băn khoăn, phản đối); bỏ
  chào hỏi, xác nhận qua loa ("vâng", "ok"), lặp lại câu người khác, ý phụ.
- Mỗi luận điểm là MỘT Ý CHÍNH đã được hợp nhất theo ngữ nghĩa CỦA MỘT NGƯỜI
  NÓI, viết thành MỘT CÂU SÚC TÍCH. Không nhồi nhiều ý khác nhau vào một câu
  bằng dấu phẩy, "và", "đồng thời".
- Nếu người nói nêu nhiều lần cùng một ý, hoặc nhiều ý cùng hướng/cùng phục vụ
  một mục đích, GỘP thành một luận điểm và đưa TẤT CẢ turn_id của các lượt đó
  vào evidence_turn_ids của luận điểm ấy (không tách thành nhiều luận điểm).
- Người nói không có ý nào đáng giữ thì không liệt kê người đó.
- KHÔNG ghi lại câu GIAO VIỆC/PHÂN CÔNG ("Giao Hiếu...", "Giao nhiệm vụ
  cho...") hay câu tự nhận việc -- chúng đã nằm ở phần Giao việc của báo
  cáo, ghi lại ở đây là lặp. Với người chủ trì, chỉ ghi lập luận/định hướng
  của họ (vì sao chọn phương án, lưu ý gì), không liệt kê lại từng việc đã giao.

Mỗi luận điểm PHẢI kèm evidence_turn_ids: danh sách các turn_id của
những turn chứa luận điểm đó (một luận điểm gộp thì trích nhiều turn_id).
KHÔNG chép lại nội dung/câu trích của turn.

turn_id CHỈ LÀ phần đứng TRƯỚC dấu "|" bên trong ngoặc vuông đầu mỗi dòng
bản ghi -- KHÔNG bao gồm dấu ngoặc vuông, KHÔNG bao gồm tên người nói,
KHÔNG bao gồm dấu "|". Ví dụ dòng bản ghi "[TURN_000020|Phạm Hồng Sơn] Nội
dung..." thì turn_id là "TURN_000020" -- TUYỆT ĐỐI KHÔNG phải
"[TURN_000020|Phạm Hồng Sơn]" hay "TURN_000020|Phạm Hồng Sơn".

Chọn evidence_turn_ids TRƯỚC khi viết text của luận điểm -- không được viết
luận điểm rồi mới đi tìm bằng chứng khớp với nó.

full_name PHẢI xuất hiện đúng nguyên văn trong bản ghi, kể cả khi có vẻ
sai chính tả -- không tự sửa/hoàn thiện tên.
""".strip()

CONTENT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "speakers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "full_name": {"type": "string"},
                    "points": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "evidence_turn_ids": {"type": "array", "items": {"type": "string"}},
                                "text": {"type": "string"},
                            },
                            "required": ["evidence_turn_ids", "text"],
                        },
                    },
                },
                "required": ["full_name", "points"],
            },
        }
    },
    "required": ["speakers"],
}


def _build_content_user_prompt(task: SegmentTask) -> str:
    """Dựng phần user prompt cho Content Agent: tiêu đề, tóm tắt và bản ghi của đoạn.

    Đầu vào: task - gói dữ liệu của một đoạn chủ đề.
    Đầu ra: str - nội dung user prompt.
    """

    return (
        f"Tiêu đề đoạn: {task['title']}\n"
        f"Tóm tắt đoạn: {task['summary']}\n\n"
        f"Bản ghi:\n{format_turns_as_transcript(task['turns'])}"
    )


def _build_speaker_sections_from_llm_result(task: SegmentTask, result: dict) -> tuple[list[SpeakerSection], int]:
    """Chuyển JSON của model thành các ``SpeakerSection`` đã kiểm chứng, kèm số luận điểm bị loại.

    Một luận điểm chỉ được giữ nếu: có nội dung, có ít nhất một trích dẫn hợp lệ
    (luận điểm không trích dẫn thì không kiểm chứng được), người nói của nó
    quy được về một người nói thật của đoạn này
    (``match_claimed_name_to_real_speaker``), và nó không chỉ là câu giao việc
    (``is_assignment_point`` -- đã có ở Giao việc, không đếm vào ``dropped``). Các luận điểm của cùng một người
    được gộp thành một section, theo thứ tự gặp đầu tiên.

    Chịu được JSON sai hình dạng (``null``, sai kiểu phần tử, ``text`` không phải chuỗi...):
    mục xấu chỉ bị loại và tính vào ``dropped``, không làm sập cả đoạn.

    Đầu vào:
        task: gói dữ liệu của đoạn chủ đề (lấy các lượt nói để đối chiếu).
        result: JSON do model trả về theo ``CONTENT_SCHEMA``.

    Đầu ra: tuple ``(sections, dropped)``, gồm danh sách SpeakerSection và số
        luận điểm đã bị loại.
    """

    turns = task["turns"]
    points_by_speaker: dict[str, list[SpeakerPoint]] = {}
    speakers, dropped = split_dict_entries(result.get("speakers"))
    for speaker in speakers:
        claimed_name = read_stripped_text(speaker.get("full_name"))
        points, invalid_point_count = split_dict_entries(speaker.get("points"))
        dropped += invalid_point_count
        for point in points:
            text = read_stripped_text(point.get("text"))
            evidence_ids, quotes = validate_evidence_by_turn_ids(
                turns, read_list_or_empty(point.get("evidence_turn_ids"))
            )
            full_name = match_claimed_name_to_real_speaker(claimed_name, turns, evidence_ids)
            if not text or not evidence_ids or full_name is None:
                dropped += 1
                continue
            if is_assignment_point(text):
                # Đã có ở Giao việc (Action Agent); không tính là luận điểm lỗi.
                continue
            points_by_speaker.setdefault(full_name, []).append(
                SpeakerPoint(text=text, evidence_ids=evidence_ids, quotes=quotes)
            )
    sections = [
        SpeakerSection(
            segment_id=task["segment_id"],
            initials=make_speaker_initials(full_name),
            full_name=full_name,
            points=tuple(points),
        )
        for full_name, points in points_by_speaker.items()
    ]
    return sections, dropped


def make_content_agent(llm: LLMAdapter):
    """Tạo node ``content_agent`` gắn với một LLM cụ thể.

    Đầu vào: llm - adapter LLM có ``generate_json``.
    Đầu ra: hàm node ``content_agent(task)`` để đăng ký vào graph.
    """

    def content_agent(task: SegmentTask) -> dict:
        """Trích luận điểm theo người nói cho MỘT đoạn chủ đề.

        Nếu LLM lỗi (``LLMUpstreamError``), trả kết quả rỗng kèm ``TopicFailure``
        để graph thử lại sau, thay vì làm hỏng cả cuộc họp.

        Đầu vào: task - gói dữ liệu của đoạn chủ đề.
        Đầu ra: dict cập nhật state gồm ``meeting_development``, dấu hoàn
            thành ``completed_content_topics`` và (khi lỗi) ``topic_failures``.
        """

        segment_id = task["segment_id"]
        # Dấu rõ ràng "nhánh Content của chủ đề này đã xong"
        # (xem ``..graph.advance_topic``); trả cả ở đường lỗi.
        done = {"completed_content_topics": (segment_id,)}
        user_prompt = _build_content_user_prompt(task)
        try:
            with llm_call("content_agent", segment_id=segment_id, prompt_chars=len(user_prompt)):
                result = llm.generate_json(
                    system_prompt=CONTENT_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    schema=CONTENT_SCHEMA,
                )
        except LLMUpstreamError as exc:
            logger.warning(
                "content_agent bỏ qua segment %s vì LLM lỗi: %s", segment_id, exc
            )
            failure = TopicFailure(segment_id, "content_agent", str(exc))
            return {"meeting_development": [], "topic_failures": (failure,), **done}
        sections, dropped = _build_speaker_sections_from_llm_result(task, result)
        if dropped:
            logger.warning(
                "content_agent segment %s: bỏ %d luận điểm không có text/trích dẫn "
                "hợp lệ hoặc không xác định được người nói",
                segment_id,
                dropped,
            )
        return {"meeting_development": sections, **done}

    return content_agent


__all__ = [
    "CONTENT_SYSTEM_PROMPT",
    "CONTENT_SCHEMA",
    "make_content_agent",
]
