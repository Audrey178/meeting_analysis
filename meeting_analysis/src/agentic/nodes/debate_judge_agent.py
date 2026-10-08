"""Node Debate + Judge: kiểm chứng lại MỘT candidate (action/decision) bị
Evidence-Check gắn cờ UNCERTAIN, bằng 3 lời gọi LLM có vai trò riêng biệt
(Agent A ủng hộ / Agent B phản biện / Judge phân xử) -- xem sơ đồ gốc và
mục "Debate/Judge" trong ``be/DESIGN.md``.

Vì sao gộp cả 3 vai trò vào MỘT node LangGraph (không phải 3 node riêng
Agent-A/Agent-B/Judge như tranh vẽ gốc): Debate+Judge chạy cho từng
candidate uncertain RIÊNG LẺ, số lượng động (0..N mỗi chủ đề). Tách 3 node
LangGraph thật cần một cơ chế khớp lại đúng cặp lập luận A/B của ĐÚNG
candidate đó trước khi Judge chạy -- lặp lại kiểu bookkeeping mà
``graph.advance_topic`` đang làm ở cấp CHỦ ĐỀ, nhưng giờ ở cấp ITEM, lồng
bên trong một cấp fan-out/fan-in đã có. Gộp vào 1 node giữ đúng 3 lời gọi/3
vai trò/3 system prompt riêng biệt (không giảm chất lượng tranh luận), chỉ
khác cách nối dây: LangGraph chỉ cần ``Send`` node này một lần mỗi candidate
uncertain, dùng lại đúng cơ chế fan-out/fan-in đã kiểm chứng cho 3 agent
chính (xem ``..graph``).

Judge trả ``verdict`` ba mức thay vì ``kept`` true/false: ``keep``, ``revise``
(việc giao có thật nhưng sai/thiếu người phụ trách -- judge sửa ``actor``
theo bản ghi, thay vì phải chọn giữa giữ một actor vô nghĩa và bỏ một việc
thật) và ``drop``. Judge PHẢI chỉ ra ``deciding_turn_id`` -- lượt nói giao/chốt
-- khi giữ; giữ mà không chỉ ra được lượt nào thuộc đoạn thì bị hạ thành
``drop`` bằng luật (bản trước judge giữ 16/17 candidate, nhiều lần chỉ vì
"nội dung có căn cứ" dù đó là đề xuất chưa ai chấp nhận). Rubric riêng cho
từng loại (``_RUBRICS``) liệt kê đúng các lỗi judge eval đã bắt được.

An toàn khi LLM lỗi: GIỮ candidate (kept=True) kèm ghi chú lỗi, không lùi về
"bỏ" -- một candidate uncertain vẫn có evidence_ids hợp lệ (chỉ là bị nghi
ngờ), nên mất nó vì lỗi hạ tầng tạm thời còn tệ hơn giữ nhầm; nhất quán với
triết lý "lỗi LLM không được xoá nội dung đã trích" xuyên suốt package này.
Đây LÀ một giới hạn đã biết: khác các agent trích xuất chính, debate KHÔNG
có lượt retry riêng ở cuối cuộc họp (chỉ thử 1 lần, không nằm trong
``graph.retry_failed_topics``) -- chấp nhận để không thêm một vòng lặp retry
lồng nữa trong bản đầu; nên thêm sau nếu lỗi debate xảy ra thường trong thực tế.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from .._shared import (
    format_turns_as_transcript,
    is_non_identifying_actor,
    read_confirm_turn_id,
    read_stripped_text,
)
from ..schemas import ActionItemCandidate, DebateRecord, DebateTask, DecisionCandidate, JudgeVerdict
from ...utils.llm_call_log import llm_call
from ...utils.ports import LLMAdapter, LLMUpstreamError

logger = logging.getLogger(__name__)

_KIND_LABELS = {"action": "việc giao (action item)", "decision": "quyết định (decision)"}

# Tiêu chí giữ/bỏ theo loại -- dùng chung cho cả hai bên tranh luận và judge
# để ba vai trò tranh luận trên CÙNG một thước đo. Danh sách "BỎ" lấy từ các
# lỗi judge eval đã gắn cờ trên 30 cuộc họp (eval/results/dialtreeseg_v1).
_RUBRICS = {
    "action": """
GIỮ (keep): có lượt nói trong đoạn mà người chủ trì/cấp có thẩm quyền GIAO việc
này cho đúng người/đơn vị trong candidate, hoặc người/đơn vị đó TỰ NHẬN việc và
không ai phản đối. Người/đơn vị tự nêu việc cụ thể mình SẼ làm (kế hoạch sắp tới,
thường kèm mốc thời gian) là TỰ NHẬN việc -- không phải "báo cáo".
SỬA (revise): việc giao có thật nhưng người phụ trách trong candidate sai, thiếu
hoặc chung chung ("một thành viên", "nhóm") trong khi bản ghi cho thấy rõ ai
nhận việc -- trả revised_actor là tên/đơn vị ĐÚNG NGUYÊN VĂN bản ghi.
BỎ (drop): đề xuất/kiến nghị/yêu cầu của một thành viên chưa được ai chấp nhận;
báo cáo việc ĐÃ làm xong/ĐANG làm; câu thăm dò chưa thành cam kết ("để xem có
làm được không"); lời mời/điều phối buổi họp ("mời anh X trình
bày"); quy định/hướng dẫn chung không gắn người thực hiện; việc bị gạt đi hoặc
hoãn; nội dung không có trong bản ghi.
""".strip(),
    "decision": """
GIỮ (keep): có lượt nói trong đoạn mà người chủ trì KẾT LUẬN hoặc các bên THỐNG
NHẤT đúng nội dung này, và sau đó không bị thay bằng phương án khác.
BỎ (drop): báo cáo tình hình/số liệu/việc đã làm; ước tính, dự báo, nhận định
cá nhân; đề xuất chưa được xác nhận hoặc bị gạt đi/hoãn lại; câu mở đầu, thủ
tục, khẩu hiệu; kế hoạch/văn bản đã có từ trước chỉ được nhắc lại; phương án
đã bị thay thế bởi phương án khác ở sau; nội dung không có trong bản ghi.
(Quyết định không có "revise" -- chỉ keep hoặc drop.)
""".strip(),
}

DEBATE_SUPPORT_SYSTEM_PROMPT = """
Bạn là bên ỦNG HỘ trong một cuộc tranh luận nội bộ để kiểm chứng lại một
candidate {kind_label} đã được trích ra từ MỘT đoạn chủ đề của cuộc họp,
nhưng bị bước kiểm tra bằng luật đánh dấu CHƯA CHẮC CHẮN.

Tiêu chí:
{rubric}

Nhiệm vụ: chỉ ra lượt nói CỤ THỂ (nêu turn_id) cho thấy candidate thoả tiêu
chí GIỮ (hoặc SỬA, nếu chỉ sai người phụ trách). Nếu không tìm được, thừa
nhận thẳng thắn -- TUYỆT ĐỐI KHÔNG bịa nội dung không có trong bản ghi.

Trả JSON: {{"argument": "<lập luận ủng hộ, 2-4 câu, có turn_id>"}}
""".strip()

DEBATE_OPPOSE_SYSTEM_PROMPT = """
Bạn là bên PHẢN BIỆN trong một cuộc tranh luận nội bộ để kiểm chứng lại một
candidate {kind_label} đã được trích ra từ MỘT đoạn chủ đề của cuộc họp,
nhưng bị bước kiểm tra bằng luật đánh dấu CHƯA CHẮC CHẮN, với lý do:
{reasons}

Tiêu chí:
{rubric}

Nhiệm vụ: kiểm candidate theo TỪNG mục trong danh sách BỎ và chỉ ra mục nào
nó vi phạm, kèm turn_id làm căn cứ. TUYỆT ĐỐI KHÔNG bịa nội dung không có
trong bản ghi; nếu thực ra không vi phạm mục nào, thừa nhận thẳng thắn.

Trả JSON: {{"argument": "<lập luận phản biện, 2-4 câu, có turn_id>"}}
""".strip()

JUDGE_SYSTEM_PROMPT = """
Bạn là TRỌNG TÀI, phân xử một candidate {kind_label} đang bị tranh chấp,
dựa trên lập luận của hai bên (ủng hộ/phản biện) và bản ghi gốc.

Tiêu chí:
{rubric}

Chỉ dựa vào bằng chứng có thật trong bản ghi -- không thiên vị bên nào chỉ vì
lập luận "nghe thuyết phục hơn". "Nội dung có nhắc trong bản ghi" CHƯA đủ để
giữ: phải có lượt nói GIAO/NHẬN việc hoặc KẾT LUẬN/THỐNG NHẤT. Khi giữ hoặc
sửa, deciding_turn_id BẮT BUỘC là turn_id của chính lượt nói đó; không chỉ ra
được thì phải bỏ.

Trả JSON: {{"verdict": "keep" | "revise" | "drop",
"deciding_turn_id": "<turn_id hoặc null>",
"revised_actor": "<tên đúng theo bản ghi, chỉ khi verdict=revise, ngược lại null>",
"reasoning": "<1-2 câu giải thích>"}}
""".strip()

DEBATE_ARGUMENT_SCHEMA: dict = {
    "type": "object",
    "properties": {"argument": {"type": "string"}},
    "required": ["argument"],
}

JUDGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["keep", "revise", "drop"]},
        "deciding_turn_id": {"type": ["string", "null"]},
        "revised_actor": {"type": ["string", "null"]},
        "reasoning": {"type": "string"},
    },
    "required": ["verdict", "deciding_turn_id", "revised_actor", "reasoning"],
}


def _candidate_text(candidate: ActionItemCandidate | DecisionCandidate, kind: str) -> str:
    """Lấy nội dung hiển thị của candidate để đưa vào prompt debate/judge và bản ghi audit.

    Đầu vào: candidate - ActionItemCandidate hoặc DecisionCandidate; kind - "action"/"decision".
    Đầu ra: str - "actor: text (hạn: ...)" cho action, hoặc "text" cho decision.
    """

    if kind == "action":
        actor = candidate.actor or "(chưa rõ người phụ trách)"
        deadline = f" (hạn: {candidate.deadline_raw})" if candidate.deadline_raw else ""
        return f"{actor}: {candidate.text}{deadline}"
    return candidate.text


def _build_debate_user_prompt(task: DebateTask, candidate_text: str) -> str:
    """Dựng user prompt chung cho cả Agent A và Agent B: candidate, lý do nghi ngờ, bản ghi.

    Đầu vào: task - DebateTask; candidate_text - nội dung candidate để hiển thị.
    Đầu ra: str - user prompt.
    """

    candidate = task["candidate"]
    reasons = "; ".join(task["reasons"]) or "(không có lý do cụ thể)"
    return (
        f"Candidate: {candidate_text}\n"
        f"Agent trích xuất tự khai: trạng thái '{candidate.status}', "
        f"lượt chốt {candidate.confirm_turn_id or '(không nêu)'}, "
        f"bằng chứng {', '.join(candidate.evidence_ids)}\n"
        f"Lý do bị đánh dấu chưa chắc chắn: {reasons}\n\n"
        f"Bản ghi của đoạn:\n{format_turns_as_transcript(task['turns'])}"
    )


def _kept_result(kind: str, candidate: ActionItemCandidate | DecisionCandidate) -> dict:
    """Gói candidate đã được giữ vào đúng danh sách kết quả theo loại.

    Đầu vào: kind - "action" hoặc "decision"; candidate - candidate (đã gắn ``verification``).
    Đầu ra: dict với đúng MỘT khóa (``verified_assignments`` hoặc
        ``verified_decisions``), giá trị là list 1 phần tử.
    """

    if kind == "action":
        return {"verified_assignments": [candidate]}
    return {"verified_decisions": [candidate]}


def _resolve_verdict(
    task: DebateTask, judge_result: dict
) -> tuple[JudgeVerdict, str | None, ActionItemCandidate | DecisionCandidate]:
    """Áp luật lên kết quả judge: chuẩn hoá verdict, kiểm lượt quyết định, sửa actor.

    - verdict lạ -> "drop"; "revise" với decision -> "keep".
    - keep/revise mà ``deciding_turn_id`` không thuộc đoạn -> "drop" (xem docstring module).
    - revise: chỉ nhận ``revised_actor`` định danh được; không thì giữ actor cũ
      (verdict thành "keep"). Actor cuối không định danh được -> None, để
      frontend xếp vào "Chưa rõ người phụ trách" thay vì một tên giả.

    Đầu vào: task - DebateTask; judge_result - JSON judge trả về.
    Đầu ra: (verdict cuối, deciding_turn_id hợp lệ hoặc None, candidate cuối).
    """

    kind = task["kind"]
    candidate = task["candidate"]
    verdict = judge_result.get("verdict")
    if verdict not in ("keep", "revise", "drop"):
        verdict = "drop"
    if verdict == "revise" and kind == "decision":
        verdict = "keep"
    deciding_turn_id = read_confirm_turn_id(task["turns"], judge_result.get("deciding_turn_id"))
    if verdict != "drop" and deciding_turn_id is None:
        verdict = "drop"
    if kind == "action" and verdict != "drop":
        actor = candidate.actor
        revised = read_stripped_text(judge_result.get("revised_actor"))
        if verdict == "revise" and revised and not is_non_identifying_actor(revised):
            actor = revised
        else:
            verdict = "keep"
        if actor is not None and is_non_identifying_actor(actor):
            actor = None
        candidate = replace(candidate, actor=actor)
    return verdict, deciding_turn_id, replace(candidate, verification="debate")


def make_debate_and_judge_agent(llm: LLMAdapter):
    """Tạo node ``debate_and_judge_agent`` gắn với một LLM cụ thể.

    Cùng một adapter được dùng cho cả 3 vai trò (Agent A/B/Judge) -- đơn
    giản hoá tham số của ``build_graph`` (không thêm 2 tham số LLM riêng chỉ
    cho node này). Mỗi vai trò vẫn là một lời gọi độc lập với system prompt
    riêng, không giảm số lời gọi/chất lượng tranh luận. Có thể tách thành 3
    adapter riêng sau nếu đo được thiên vị tự đồng ý đáng kể (cùng lý do đã
    nêu ở docstring ``graph.build_graph`` cho 3 agent chính).

    Đầu vào: llm - adapter LLM có ``generate_json``.
    Đầu ra: hàm node ``debate_and_judge_agent(task)`` để đăng ký vào graph
        (được ``Send`` một lần mỗi candidate uncertain).
    """

    def _fallback(task: DebateTask, candidate_text: str, support: str, oppose: str, note: str) -> dict:
        """Giữ candidate theo luật an toàn khi LLM lỗi (xem docstring module)."""

        kind = task["kind"]
        candidate = replace(task["candidate"], verification="fallback")
        return {
            "completed_debate_items": (task["item_key"],),
            **_kept_result(kind, candidate),
            "debate_records": (
                DebateRecord(
                    segment_id=task["segment_id"], kind=kind, candidate_text=candidate_text,
                    reasons=task["reasons"], support_argument=support, oppose_argument=oppose,
                    kept=True, reasoning=note, verdict="keep", final_text=candidate_text,
                ),
            ),
        }

    def debate_and_judge_agent(task: DebateTask) -> dict:
        """Tranh luận rồi phân xử MỘT candidate uncertain.

        Đầu vào: task - DebateTask (candidate, lý do nghi ngờ, bản ghi đoạn).
        Đầu ra: dict cập nhật state:
            - ``completed_debate_items``: dấu hoàn thành (``item_key``), LUÔN trả.
            - ``debate_records``: bản ghi tranh luận để audit, LUÔN trả.
            - ``verified_assignments``/``verified_decisions``: candidate (đã
              sửa actor nếu ``revise``), CHỈ khi được giữ -- bao gồm cả trường
              hợp lỗi LLM (xem docstring module về lựa chọn an toàn này).
        """

        kind = task["kind"]
        segment_id = task["segment_id"]
        item_key = task["item_key"]
        kind_label = _KIND_LABELS[kind]
        rubric = _RUBRICS[kind]
        candidate_text = _candidate_text(task["candidate"], kind)
        reasons_text = "; ".join(task["reasons"]) or "(không có lý do cụ thể)"
        user_prompt = _build_debate_user_prompt(task, candidate_text)

        try:
            with llm_call("debate_support", segment_id=segment_id, prompt_chars=len(user_prompt)):
                support_result = llm.generate_json(
                    system_prompt=DEBATE_SUPPORT_SYSTEM_PROMPT.format(kind_label=kind_label, rubric=rubric),
                    user_prompt=user_prompt,
                    schema=DEBATE_ARGUMENT_SCHEMA,
                )
            with llm_call("debate_oppose", segment_id=segment_id, prompt_chars=len(user_prompt)):
                oppose_result = llm.generate_json(
                    system_prompt=DEBATE_OPPOSE_SYSTEM_PROMPT.format(
                        kind_label=kind_label, reasons=reasons_text, rubric=rubric
                    ),
                    user_prompt=user_prompt,
                    schema=DEBATE_ARGUMENT_SCHEMA,
                )
        except LLMUpstreamError as exc:
            logger.warning(
                "debate_and_judge_agent: lỗi LLM ở vòng tranh luận, giữ candidate %s "
                "theo luật an toàn: %s", item_key, exc,
            )
            return _fallback(
                task, candidate_text, "", "",
                f"(debate lỗi LLM ở vòng tranh luận, giữ nguyên theo luật an toàn: {exc})",
            )

        support_argument = read_stripped_text(support_result.get("argument"))
        oppose_argument = read_stripped_text(oppose_result.get("argument"))
        judge_prompt = (
            f"{user_prompt}\n\n"
            f"Lập luận ỦNG HỘ: {support_argument or '(không có)'}\n"
            f"Lập luận PHẢN BIỆN: {oppose_argument or '(không có)'}"
        )
        try:
            with llm_call("debate_judge", segment_id=segment_id, prompt_chars=len(judge_prompt)):
                judge_result = llm.generate_json(
                    system_prompt=JUDGE_SYSTEM_PROMPT.format(kind_label=kind_label, rubric=rubric),
                    user_prompt=judge_prompt,
                    schema=JUDGE_SCHEMA,
                )
        except LLMUpstreamError as exc:
            logger.warning(
                "debate_and_judge_agent: lỗi LLM ở bước judge, giữ candidate %s theo luật an toàn: %s",
                item_key, exc,
            )
            return _fallback(
                task, candidate_text, support_argument, oppose_argument,
                f"(debate lỗi LLM ở bước judge, giữ nguyên theo luật an toàn: {exc})",
            )

        verdict, deciding_turn_id, final_candidate = _resolve_verdict(task, judge_result)
        reasoning = read_stripped_text(judge_result.get("reasoning"))
        if verdict == "drop" and judge_result.get("verdict") in ("keep", "revise"):
            reasoning = f"(Hạ thành drop: judge không chỉ ra được lượt nói giao/chốt thuộc đoạn.) {reasoning}"
        kept = verdict != "drop"
        record = DebateRecord(
            segment_id=segment_id, kind=kind, candidate_text=candidate_text,
            reasons=task["reasons"], support_argument=support_argument,
            oppose_argument=oppose_argument, kept=kept, reasoning=reasoning,
            verdict=verdict, final_text=_candidate_text(final_candidate, kind) if kept else "",
            deciding_turn_id=deciding_turn_id,
        )
        result: dict = {"completed_debate_items": (item_key,), "debate_records": (record,)}
        if kept:
            result.update(_kept_result(kind, final_candidate))
        return result

    return debate_and_judge_agent


__all__ = [
    "DEBATE_SUPPORT_SYSTEM_PROMPT",
    "DEBATE_OPPOSE_SYSTEM_PROMPT",
    "JUDGE_SYSTEM_PROMPT",
    "DEBATE_ARGUMENT_SCHEMA",
    "JUDGE_SCHEMA",
    "make_debate_and_judge_agent",
]
