"""Node Verifier (ReAct, có giới hạn bước) + vòng đồng thuận với agent trích xuất.

Thay Debate+Judge 3 vai của v1 (support -> oppose -> judge, 3 lời gọi NỐI TIẾP chỉ
đọc lại đúng đoạn hiện tại). Verifier tự tra bằng chứng trong CẢ cuộc họp qua tool
chỉ đọc (``verifier_tools.MeetingTools``), thường kết luận sau 1-2 lời gọi; tối đa
``verifier_max_tool_calls + 1`` lời gọi mỗi vòng.

ReAct dựng trên ``LLMAdapter.generate_json`` (một lượt hỏi-đáp JSON), không cần
provider hỗ trợ tool calling: mỗi lượt model trả ``{thought, action, argument, ...}``,
code chạy tool rồi đưa cả suy nghĩ, hành động và observation vào prompt lượt sau. Lượt
cuối bắt buộc ``action="final"``.

Tiêu chí của Verifier là rubric v1 cộng câu "chủ trì đề nghị + người/đơn vị + việc là
giao việc" mà Action agent v3 cũng dùng (``prompts.VERIFY_RUBRICS``), để hai bên chấm
cùng một chuẩn.

Kết luận đi qua đúng luật hậu kiểm của v1 (``_resolve_verdict``): giữ/sửa mà không
chỉ ra được lượt nói giao/chốt thì hạ thành bỏ. Khác v1: lượt đó được phép nằm ở
chủ đề khác của cùng cuộc họp, vì tool cho Verifier thấy cả cuộc họp.

Vòng đồng thuận (thay cho duyệt người): Verifier giữ (keep) thì xong ngay. Mọi kết
luận khác (revise/drop/unresolved) được gửi lại làm feedback cho agent trích xuất
(``action_llm``/``decision_llm``), agent này trả một lập trường:

    accept -> đồng thuận theo Verifier (revise: giữ bản sửa; drop/unresolved: bỏ).
    amend  -> agent sửa candidate theo bản ghi; vòng sau Verifier xét bản đã sửa.
    defend -> agent giữ nguyên, chỉ ra lượt giao/chốt; vòng sau Verifier xét lại
              kèm lập luận đó. "accept" mà vẫn chỉ ra lượt giao/chốt (khi Verifier
              không đề nghị sửa) là tự mâu thuẫn và được coi là defend.

Lặp tới khi đồng thuận hoặc hết ``consensus_max_rounds`` vòng. Hết vòng: lấy kết luận
cuối của Verifier (``decided_by="verifier"``); kết luận đó vẫn là "unresolved" thì giữ
theo luật an toàn ``fallback`` như v1. Lỗi LLM ở bất kỳ bước nào cũng giữ ``fallback``
(lỗi hạ tầng không được xoá nội dung đã trích).

Định danh actor (chỉ việc giao): Verifier tra ``lookup_speaker`` rồi điền
``revised_actor`` (đúng tên một ứng viên), ``revised_actor_type`` và ``actor_reason``.
Lựa chọn chỉ được nhận khi tên nằm trong danh sách ứng viên và có lý do; ``unknown``
thì giữ ứng viên và gắn cờ; còn lại dùng luật chấm điểm (``actors/resolution.py``).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import replace

from ..core._shared import (
    _content_tokens,
    format_turns_as_transcript,
    is_non_identifying_actor,
    read_confirm_turn_id,
    read_stripped_text,
    strip_assignment_prefix,
)
from ..core.nodes.debate_judge_agent import (
    _KIND_LABELS,
    _candidate_text,
    _resolve_verdict,
)
from ...utils.llm_call_log import llm_call
from ...utils.ports import LLMAdapter, LLMUpstreamError
from ..actors.resolution import apply_verifier_actor_choice
from ..config import V3Config
from ..schemas import ConsensusRound, VerificationRecord, VerifierStep, VerifyTask
from .prompts import CHAIR_HINT, VERIFY_RUBRICS, format_chair_line
from .verifier_tools import TOOL_DESCRIPTIONS, TOOL_NAMES, MeetingTools

logger = logging.getLogger(__name__)

VERIFIER_SYSTEM_PROMPT = """
Bạn là KIỂM CHỨNG VIÊN cho một candidate {kind_label} trích từ MỘT đoạn chủ đề của cuộc
họp, bị bộ lọc tự động đánh dấu CHƯA CHẮC CHẮN.

Tiêu chí:
{rubric}
{chair_hint}

Bạn có các tool CHỈ ĐỌC để tra bằng chứng trong CẢ cuộc họp:
{tools}

Mỗi lượt trả về đúng MỘT JSON, các trường theo thứ tự:
- thought: 1-2 câu: đã biết gì từ bản ghi và các bước trước, còn thiếu gì, vì sao tra
  tiếp hoặc vì sao đã đủ căn cứ.
- Muốn tra thêm: action là tên tool, argument là tham số; các trường kết luận để null.
- Đủ căn cứ: action = "final", argument = null, và điền verdict:
  "keep" | "revise" | "drop" | "unresolved" (chỉ khi bằng chứng thật sự mâu thuẫn
  hoặc thiếu), deciding_turn_id (BẮT BUỘC khi keep/revise: turn_id của lượt nói
  GIAO/NHẬN việc hoặc KẾT LUẬN/THỐNG NHẤT, có thể ở chủ đề khác), reasoning (1-2 câu).

Với VIỆC GIAO, actor có thể là NGƯỜI hoặc ĐƠN VỊ ("giao Sở Tài chính chủ trì" là hợp lệ).
Khi actor chỉ là tên gọi, có thể trùng người khác, hoặc bị nghi ngờ: gọi
lookup_speaker("<cách gọi> @<turn_id lượt chốt>") rồi điền:
  revised_actor: ĐÚNG tên một ứng viên tool trả về (không tự viết tên khác). Việc giao
  cho nhiều bên thì nối bằng ", " và ghi vai trò trong ngoặc, vd
  "Sở Tài chính (chủ trì), Sở Xây dựng (phối hợp)"; mỗi bên phải là một ứng viên;
  revised_actor_type: "person" | "organization" | "unknown";
  actor_reason: vì sao chọn ứng viên đó (ai nói gì ở lượt nào; chỉ dựa vào chức vị/đơn
  vị khi bản ghi không phân định được).
Không có ứng viên nào rõ ràng thì revised_actor_type = "unknown" (việc giao vẫn giữ).
Với quyết định, ba trường này để null.

"Cờ của bộ lọc tự động" chỉ cho biết vì sao candidate bị gửi kiểm tra: bộ lọc chỉ
chấm MỘT lượt nói mà agent trích xuất khai và hay sai, nên cờ đó KHÔNG phải bằng
chứng và KHÔNG được dùng làm lý do bỏ. Lượt GIAO/CHỐT thật có thể khác lượt agent
khai. Trước khi kết luận drop/unresolved, đọc các lượt nói của người chủ trì/cấp có
thẩm quyền trong đoạn, nhất là các lượt cuối đoạn (tổng kết, "đề nghị các đồng chí
...", "giao ...", "chuẩn bị lại ..."); thấy lượt giao/chốt đúng nội dung candidate
thì keep/revise với deciding_turn_id là lượt đó.

reasoning là FEEDBACK gửi lại agent trích xuất khi bạn không giữ: nêu cụ thể điểm
sai/thiếu và lượt nói làm căn cứ, để agent sửa hoặc phản biện. Đã có các vòng trao đổi
trước thì xét lập luận của agent trên bản ghi, không nhượng bộ chỉ vì agent phản biện.

Chỉ dựa vào bằng chứng có thật trong bản ghi. "Nội dung có nhắc trong bản ghi" CHƯA đủ
để giữ. Tra ít nhất có thể.
""".strip()

# ``deciding_turn_id`` đứng TRƯỚC ``verdict``: model phải chỉ ra lượt giao/chốt trước khi
# chọn kết luận, không chọn "keep"/"drop" rồi mới tìm lượt nói cho khớp.
VERIFIER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "action": {"type": "string", "enum": [*TOOL_NAMES, "final"]},
        "argument": {"type": ["string", "null"]},
        "deciding_turn_id": {"type": ["string", "null"]},
        "verdict": {"type": ["string", "null"], "enum": ["keep", "revise", "drop", "unresolved", None]},
        "revised_actor": {"type": ["string", "null"]},
        "revised_actor_type": {"type": ["string", "null"], "enum": ["person", "organization", "unknown", None]},
        "actor_reason": {"type": ["string", "null"]},
        "reasoning": {"type": ["string", "null"]},
    },
    "required": [
        "thought", "action", "argument", "verdict", "deciding_turn_id", "revised_actor",
        "revised_actor_type", "actor_reason", "reasoning",
    ],
}

_FINAL_TURN_NOTE = "ĐÂY LÀ LƯỢT CUỐI: bắt buộc action = \"final\" và điền verdict."

PROPOSER_SYSTEM_PROMPT = """
Bạn là AGENT TRÍCH XUẤT đã đề xuất candidate {kind_label} dưới đây từ MỘT đoạn chủ đề
của cuộc họp. KIỂM CHỨNG VIÊN vừa phản hồi: kết luận và lý do (feedback). Đối chiếu
feedback với bản ghi rồi chọn đúng MỘT lập trường:
- "accept": đồng ý với kiểm chứng viên (sửa theo đề xuất của họ, hoặc bỏ candidate nếu
  họ đề nghị bỏ / không đủ căn cứ).
- "amend": sửa candidate cho đúng bản ghi: revised_text (nội dung mới, bắt đầu bằng
  động từ) và/hoặc revised_actor (chỉ với việc giao, đúng nguyên văn bản ghi), kèm
  confirm_turn_id là lượt nói GIAO/NHẬN việc hoặc KẾT LUẬN/THỐNG NHẤT.
- "defend": giữ nguyên candidate, chỉ ra confirm_turn_id mà kiểm chứng viên bỏ sót.

Điền confirm_turn_id TRƯỚC khi chọn lập trường: lượt nói GIAO/NHẬN việc hoặc KẾT LUẬN/
THỐNG NHẤT trong bản ghi làm căn cứ cho candidate, null nếu không có. Đã chỉ ra được
lượt đó thì lập trường là "amend" hoặc "defend", KHÔNG phải "accept"; argument phải
cùng chiều với lập trường đã chọn.

Tiêu chí:
{rubric}
{chair_hint}

TUYỆT ĐỐI KHÔNG bịa nội dung không có trong bản ghi. Không tìm được lượt giao/nhận/chốt
thì chọn "accept". Trường không dùng để null.

argument: TỐI ĐA 2 câu ngắn (dưới 300 ký tự), dẫn chứng bằng turn_id. KHÔNG trích
nguyên văn lượt nói và KHÔNG dùng dấu nháy kép (") trong bất kỳ trường nào.
""".strip()

# ``confirm_turn_id`` đứng TRƯỚC ``stance``: model sinh JSON theo thứ tự trường, nếu
# chọn lập trường trước thì sẽ "accept" rồi mới viết lập luận phản biện ngược lại.
# ``argument`` (văn bản tự do) đứng CUỐI: gemma viết xong lập luận thì muốn đóng JSON;
# nếu sau nó còn trường bắt buộc, model sinh khoảng trắng vô tận thay vì dấu phẩy.
PROPOSER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "confirm_turn_id": {"type": ["string", "null"]},
        "stance": {"type": "string", "enum": ["accept", "amend", "defend"]},
        "revised_text": {"type": ["string", "null"]},
        "revised_actor": {"type": ["string", "null"]},
        "argument": {"type": "string"},
    },
    "required": ["confirm_turn_id", "stance", "revised_text", "revised_actor", "argument"],
}

_STANCE_LABELS = {"accept": "đồng ý", "amend": "đã sửa candidate", "defend": "giữ nguyên, phản biện"}

# Kiểm lại "accept" khi lập luận dẫn turn_id mà confirm_turn_id để trống: ``argument`` phải
# đứng cuối PROPOSER_SCHEMA (xem trên) nên model chọn lập trường TRƯỚC khi lập luận, và hay
# "accept" rồi viết "...nhưng thực tế tại TURN_x các bên đã thống nhất". Hỏi lại chiều của
# lập luận bằng một lời gọi ngắn (không gửi bản ghi, chỉ trường enum + turn_id).
STANCE_CHECK_SYSTEM_PROMPT = """
Đọc LẬP LUẬN của một agent về một candidate {kind_label} rút từ cuộc họp. Chỉ xác định
chiều của lập luận, KHÔNG tự đánh giá lại candidate:
- "keep": lập luận cho rằng bản ghi CÓ lượt nói giao/nhận việc hoặc kết luận/thống nhất
  làm căn cứ giữ candidate (kể cả khi nó nói kiểm chứng viên đã bỏ sót lượt đó).
- "drop": lập luận cho rằng KHÔNG có căn cứ (chỉ là ý kiến, thảo luận, đề xuất chưa ai
  chấp nhận...), đồng ý bỏ candidate.
turn_id: lượt mà lập luận dẫn làm căn cứ GIỮ (chọn trong các lượt được dẫn), null nếu "drop".
""".strip()

STANCE_CHECK_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "supports": {"type": "string", "enum": ["keep", "drop"]},
        "turn_id": {"type": ["string", "null"]},
    },
    "required": ["supports", "turn_id"],
}

_TURN_ID_PATTERN = re.compile(r"\b(?:TURN_\d+|T\d+)\b")

# Tỉ lệ âm tiết nội dung trùng giữa candidate gốc và bản ``amend`` (trên bản ngắn hơn,
# xem ``_keeps_original_content``). Đo trên 6 bản amend của cuộc họp Cái Mép - Thị Vải và
# fixture test: 2 bản đổi sang việc khác trùng 0.33-0.36, 5 bản sửa/thu hẹp/mở rộng cùng
# một việc trùng 0.60-1.0.
_AMEND_MIN_RETAINED = 0.5


def _build_candidate_prompt(task: VerifyTask, candidate) -> str:
    """Phần đầu prompt chung cho Verifier và agent trích xuất: người chủ trì, candidate, cờ
    nghi ngờ, bản ghi.

    Khác ``_build_debate_user_prompt`` của v1: lý do bị đánh dấu được ghi rõ là cờ của
    bộ lọc tự động (gợi ý, có thể sai) để model không lấy nó làm căn cứ bỏ candidate.

    Đầu vào: task - VerifyTask; candidate - bản đang xét.
    Đầu ra: str.
    """

    reasons = "; ".join(task["reasons"]) or "(không có lý do cụ thể)"
    return (
        f"{format_chair_line(task['registry'].chair)}\n"
        f"Candidate: {_candidate_text(candidate, task['kind'])}\n"
        f"Agent trích xuất tự khai: trạng thái '{candidate.status}', "
        f"lượt chốt {candidate.confirm_turn_id or '(không nêu)'}, "
        f"bằng chứng {', '.join(candidate.evidence_ids)}\n"
        f"Cờ của bộ lọc tự động (chỉ là gợi ý, có thể sai, KHÔNG phải bằng chứng): {reasons}\n\n"
        f"Bản ghi của đoạn:\n{format_turns_as_transcript(task['turns'])}"
    )


def _build_step_prompt(base_prompt: str, steps: list[VerifierStep], is_last: bool) -> str:
    """Ghép prompt của một lượt ReAct: candidate + bản ghi đoạn + lịch sử tra cứu.

    Đầu vào:
        base_prompt: candidate, lý do nghi ngờ, bản ghi đoạn và các vòng trao đổi trước.
        steps: các bước tra cứu đã làm ở vòng hiện tại.
        is_last: True thì thêm yêu cầu bắt buộc kết luận.
    Đầu ra: str - user prompt.
    """

    parts = [base_prompt]
    if steps:
        parts.append(f"Lịch sử tra cứu:\n{_format_steps(steps)}")
    if is_last:
        parts.append(_FINAL_TURN_NOTE)
    return "\n\n".join(parts)


def _format_steps(steps: list[VerifierStep] | tuple[VerifierStep, ...]) -> str:
    """Các bước tra cứu theo kiểu ReAct: suy nghĩ, hành động ``action(argument)``, kết quả.

    Giữ cả suy nghĩ để lượt sau thấy vì sao bước trước đã tra như vậy.
    """

    return "\n\n".join(
        f"Bước {i}\nSuy nghĩ: {step.thought or '(không ghi)'}\n"
        f"Hành động: {step.action}({step.argument})\nKết quả:\n{step.observation}"
        for i, step in enumerate(steps, 1)
    )


def _repeat_notice(steps: list[VerifierStep], action: str, argument: str) -> str | None:
    """Thông báo khi Verifier tra lại đúng một lần tra đã làm ở vòng này (tốn bước vô ích).

    Đầu vào: steps - các bước đã làm; action, argument - lần tra mới.
    Đầu ra: observation báo lặp, hoặc None nếu là lần tra mới.
    """

    key = " ".join(argument.casefold().split())
    for index, step in enumerate(steps, 1):
        if step.action == action and " ".join(step.argument.casefold().split()) == key:
            return (
                f"LỖI: đã tra {action}({argument}) ở Bước {index}, kết quả như trên. "
                "Đọc kỹ bản ghi của đoạn, tra cách khác hoặc kết luận."
            )
    return None


def _format_rounds(rounds: list[ConsensusRound]) -> str:
    """Các vòng trao đổi trước, để Verifier xét lại lập luận của agent trích xuất.

    Đầu vào: rounds - các vòng đã xong.
    Đầu ra: str (rỗng nếu chưa có vòng nào).
    """

    lines = []
    for index, round_ in enumerate(rounds, 1):
        lines.append(
            f"Vòng {index} - candidate: {round_.candidate_text}\n"
            f"  Kiểm chứng viên: {round_.verdict}"
            f"{f' (lượt {round_.deciding_turn_id})' if round_.deciding_turn_id else ''}: {round_.feedback}\n"
            f"  Agent trích xuất ({_STANCE_LABELS.get(round_.stance, round_.stance)}"
            f"{f', lượt {round_.confirm_turn_id}' if round_.confirm_turn_id else ''}): {round_.response}"
        )
    return "\n".join(lines)


def _read_stance(response: dict, verdict: str, meeting_turns) -> tuple[str, str | None, str]:
    """Đọc lập trường của agent trích xuất, sửa trường hợp "accept" tự mâu thuẫn.

    "accept" khi Verifier không giữ nghĩa là BỎ candidate. Nếu agent vẫn chỉ ra một lượt
    nói thật làm căn cứ thì đó là phản biện chứ không phải đồng ý (model chọn nhãn trước
    rồi viết lập luận ngược lại), nên coi là "defend" để Verifier xét lại lượt đó.
    Với "revise", "accept" kèm lượt nói là đồng ý bản sửa, giữ nguyên.

    Đầu vào: response - JSON agent trả; verdict - kết luận Verifier vòng này;
        meeting_turns - lượt nói cả cuộc họp.
    Đầu ra: (stance hợp lệ hoặc "", confirm_turn_id hợp lệ hoặc None, argument).
    """

    stance = response.get("stance")
    stance = stance if stance in _STANCE_LABELS else ""
    confirm_turn_id = read_confirm_turn_id(meeting_turns, response.get("confirm_turn_id"))
    argument = read_stripped_text(response.get("argument"))
    if stance == "accept" and verdict != "revise" and confirm_turn_id:
        stance = "defend"
        argument = f"(Đổi accept thành defend vì agent chỉ ra lượt {confirm_turn_id}.) {argument}".strip()
    return stance, confirm_turn_id, argument


def _cited_turn_ids(argument: str, meeting_turns) -> list[str]:
    """Các turn_id có thật mà lập luận của agent dẫn ra, theo thứ tự xuất hiện, không lặp.

    Đầu vào: argument - lập luận; meeting_turns - lượt nói cả cuộc họp.
    Đầu ra: list turn_id.
    """

    cited: list[str] = []
    for raw in _TURN_ID_PATTERN.findall(argument or ""):
        turn_id = read_confirm_turn_id(meeting_turns, raw)
        if turn_id and turn_id not in cited:
            cited.append(turn_id)
    return cited


def _strip_repeated_actor(text: str, actor: str | None) -> str:
    """Bỏ mọi tiền tố "<actor>: " lặp ở đầu nội dung việc giao (agent hay chép cả
    "Đảng ủy, Ban: ..." vào ``revised_text``, sửa nhiều vòng thì lặp nhiều lần).

    Đầu vào: text - nội dung agent viết; actor - người/đơn vị phụ trách.
    Đầu ra: str đã bỏ tiền tố (không đổi nếu không có).
    """

    previous = None
    while text != previous:
        previous, text = text, strip_assignment_prefix(text, actor)
    return text


def _keeps_original_content(original: str, revised: str) -> bool:
    """Bản sửa của agent còn giữ nội dung của candidate gốc không.

    ``amend`` là để sửa câu chữ/actor của CÙNG một việc. Hai bản trùng dưới
    ``_AMEND_MIN_RETAINED`` âm tiết nội dung (tính trên bản NGẮN hơn, để bản thu hẹp
    "Nghiên cứu mở lại phản ánh" hay bản mở rộng thêm ý không bị phạt) là agent đã chuyển
    sang việc khác (vd. "nghiên cứu cơ chế ... Luật Đô thị đặc biệt" thành "đánh giá tác
    động của đề án"), làm mất việc gốc và đẻ ra mục trùng với việc khác.

    Đầu vào: original, revised - nội dung việc trước và sau khi sửa.
    Đầu ra: bool.
    """

    original_terms, revised_terms = _content_tokens(original), _content_tokens(revised)
    if not original_terms or not revised_terms:
        return True
    shared = len(original_terms & revised_terms)
    return shared / min(len(original_terms), len(revised_terms)) >= _AMEND_MIN_RETAINED


def _evidence_with_turn(candidate, turn_id: str, meeting_turns) -> dict:
    """Thêm lượt chốt mới (nằm ngoài bằng chứng) vào ``evidence_ids``/``quotes``/``segment_ids``.

    Giữ bất biến "lượt chốt nằm trong bằng chứng" như ``validate_evidence_by_segment_ids``
    khi Verifier dời ``confirm_turn_id`` sang một lượt khác của cuộc họp.

    Đầu vào: candidate; turn_id - lượt chốt mới (đã kiểm là lượt thật);
        meeting_turns - lượt nói cả cuộc họp.
    Đầu ra: dict các trường bằng chứng mới, theo thứ tự bản ghi.
    """

    kept = set(candidate.evidence_ids) | {turn_id}
    ordered = [turn for turn in meeting_turns if turn.turn_id in kept]
    cited = set(candidate.segment_ids) | {item_id for turn in ordered if turn.turn_id == turn_id for item_id, _ in turn.source_items}
    return {
        "evidence_ids": tuple(turn.turn_id for turn in ordered),
        "quotes": tuple(turn.text_exact for turn in ordered),
        "segment_ids": tuple(item_id for turn in ordered for item_id, _ in turn.source_items if item_id in cited),
    }


def _apply_proposal(candidate, kind: str, response: dict, meeting_turns):
    """Áp phần sửa (amend) hoặc lượt chốt (defend) agent trích xuất gửi lại lên candidate.

    Chỉ nhận actor định danh được và ``confirm_turn_id`` là lượt nói thật của cuộc họp.
    Nội dung sửa được bỏ tiền tố actor lặp; bản sửa chuyển sang việc khác
    (``_keeps_original_content``) thì giữ nội dung gốc, chỉ nhận lượt chốt/actor mới.

    Đầu vào: candidate; kind - "action"/"decision"; response - JSON agent trả;
        meeting_turns - lượt nói cả cuộc họp.
    Đầu ra: candidate (có thể không đổi).
    """

    changes: dict = {}
    confirm_turn_id = read_confirm_turn_id(meeting_turns, response.get("confirm_turn_id"))
    if confirm_turn_id:
        changes["confirm_turn_id"] = confirm_turn_id
        if confirm_turn_id not in candidate.evidence_ids:
            changes.update(_evidence_with_turn(candidate, confirm_turn_id, meeting_turns))
    if response.get("stance") == "amend":
        actor = read_stripped_text(response.get("revised_actor"))
        if kind == "action" and actor and not is_non_identifying_actor(actor):
            changes["actor"] = actor
        text = read_stripped_text(response.get("revised_text"))
        if kind == "action" and text:
            for name in {changes.get("actor"), candidate.actor} - {None}:
                text = _strip_repeated_actor(text, name)
        if text and _keeps_original_content(candidate.text, text):
            changes["text"] = text
        elif text:
            logger.info("verifier: bỏ bản sửa đổi sang việc khác: %r -> %r", candidate.text, text)
    return replace(candidate, **changes) if changes else candidate


def make_verifier(llm: LLMAdapter, proposer_llms: Mapping[str, LLMAdapter], config: V3Config):
    """Tạo node ``verifier`` gắn với LLM kiểm chứng, LLM của agent trích xuất và cấu hình.

    Đầu vào:
        llm: adapter của Verifier (có ``generate_json``).
        proposer_llms: kind ("action"/"decision") -> adapter của agent trích xuất đã
            sinh candidate, dùng để trả lời feedback.
        config: cấu hình v3.
    Đầu ra: hàm node ``verifier(task: VerifyTask) -> dict`` (được ``Send`` mỗi candidate).
    """

    def _settle(task, candidate, rounds, *, verdict, reasoning, deciding_turn_id, decided_by,
                actor_choice: dict | None = None) -> dict:
        """Đóng gói kết quả cuối của MỘT candidate thành dict cập nhật state.

        Lỗi LLM/không kết luận được thì ``candidate`` là bản GỐC: bản agent tự sửa mà
        Verifier chưa xét lại không được vào kết quả.

        Đầu vào: task; candidate - bản cuối (bị bỏ nếu ``verdict == "drop"``); rounds -
            các vòng trao đổi; verdict, reasoning, deciding_turn_id, decided_by - cho bản ghi;
            actor_choice - JSON lượt cuối của Verifier (chọn actor), None nếu không có.
        Đầu ra: dict ``verification_records`` (+ ``verified_*`` nếu giữ).
        """

        kind = task["kind"]
        kept = verdict != "drop"
        verification = {"consensus": "consensus", "verifier": "verifier"}.get(decided_by, "fallback")
        candidate = replace(candidate, verification=verification)
        if kind == "action" and kept:
            candidate = apply_verifier_actor_choice(
                candidate, actor_choice or {}, task["registry"], task["meeting_turns"],
                original_actor=task["candidate"].actor,
            )
        record = VerificationRecord(
            item_key=task["item_key"], segment_id=task["segment_id"], kind=kind,
            candidate_text=_candidate_text(task["candidate"], kind), reasons=task["reasons"],
            steps=tuple(step for round_ in rounds for step in round_.steps),
            verdict=verdict, reasoning=reasoning,
            final_text=_candidate_text(candidate, kind) if kept else "",
            deciding_turn_id=deciding_turn_id, decided_by=decided_by, rounds=tuple(rounds),
        )
        update: dict = {"verification_records": [record]}
        if kept:
            key = "verified_assignments" if kind == "action" else "verified_decisions"
            update[key] = [candidate]
        return update

    def _run_react(task: VerifyTask, candidate, rounds: list[ConsensusRound]) -> tuple[dict, list[VerifierStep]]:
        """Một vòng ReAct của Verifier trên ``candidate`` hiện tại.

        Đầu vào: task; candidate - bản đang xét; rounds - các vòng trước (đưa vào prompt).
        Đầu ra: (JSON lượt cuối, hoặc {} nếu hết bước mà chưa ``final``; các bước tra cứu).
        Lỗi: LLMUpstreamError nếu LLM lỗi.
        """

        kind = task["kind"]
        tools = MeetingTools(
            task["meeting_turns"],
            task["registry"],
            search_top_k=config.search_top_k,
            task_text=candidate.text,
            is_self_committed=getattr(candidate, "status", None) == "self_committed",
        )
        system_prompt = VERIFIER_SYSTEM_PROMPT.format(
            kind_label=_KIND_LABELS[kind], rubric=VERIFY_RUBRICS[kind], chair_hint=CHAIR_HINT, tools=TOOL_DESCRIPTIONS
        )
        base_prompt = _build_candidate_prompt(task, candidate)
        if rounds:
            base_prompt += f"\n\nCác vòng trao đổi trước:\n{_format_rounds(rounds)}"
        steps: list[VerifierStep] = []
        max_calls = config.verifier_max_tool_calls + 1
        for call_index in range(max_calls):
            user_prompt = _build_step_prompt(base_prompt, steps, call_index == max_calls - 1)
            with llm_call("verifier", segment_id=task["segment_id"], prompt_chars=len(user_prompt)):
                result = dict(
                    llm.generate_json(system_prompt=system_prompt, user_prompt=user_prompt, schema=VERIFIER_SCHEMA)
                )
            action = read_stripped_text(result.get("action"))
            if action == "final":
                return result, steps
            argument = read_stripped_text(result.get("argument"))
            steps.append(
                VerifierStep(
                    thought=read_stripped_text(result.get("thought")),
                    action=action,
                    argument=argument,
                    observation=_repeat_notice(steps, action, argument) or tools.run(action, argument),
                )
            )
        return {}, steps

    def _judge(task: VerifyTask, candidate, result: dict):
        """Áp luật hậu kiểm lên kết luận của Verifier.

        Đầu vào: task; candidate - bản đang xét; result - JSON lượt cuối ({} nếu hết bước).
        Đầu ra: (verdict, deciding_turn_id, candidate sau khi sửa, feedback).
        """

        reasoning = read_stripped_text(result.get("reasoning"))
        raw_verdict = result.get("verdict")
        if not result:
            return "unresolved", None, candidate, "(Verifier hết số bước mà chưa kết luận.)"
        if raw_verdict not in ("keep", "revise", "drop"):
            return "unresolved", None, candidate, reasoning or "(Verifier không đủ căn cứ để kết luận.)"
        resolve_input = {"kind": task["kind"], "candidate": candidate, "turns": task["meeting_turns"]}
        verdict, deciding_turn_id, resolved = _resolve_verdict(resolve_input, result)
        if verdict == "drop" and raw_verdict in ("keep", "revise"):
            reasoning = f"(Hạ thành drop: không chỉ ra được lượt nói giao/chốt.) {reasoning}"
        return verdict, deciding_turn_id, resolved, reasoning

    def _ask_proposer(task: VerifyTask, candidate, verdict: str, feedback: str, steps, rounds) -> dict:
        """Gửi feedback của Verifier cho agent trích xuất và nhận lập trường của nó.

        Đầu vào: task; candidate - bản Verifier vừa xét; verdict, feedback - kết luận vòng
            này; steps - bằng chứng Verifier đã tra; rounds - các vòng trước.
        Đầu ra: JSON theo ``PROPOSER_SCHEMA``.
        Lỗi: LLMUpstreamError nếu LLM lỗi.
        """

        kind = task["kind"]
        parts = [_build_candidate_prompt(task, candidate)]
        if rounds:
            parts.append(f"Các vòng trao đổi trước:\n{_format_rounds(rounds)}")
        parts.append(f"Kiểm chứng viên kết luận: {verdict}\nFeedback: {feedback}")
        if steps:
            parts.append(f"Bằng chứng kiểm chứng viên đã tra:\n{_format_steps(steps)}")
        user_prompt = "\n\n".join(parts)
        with llm_call("verifier_feedback", segment_id=task["segment_id"], prompt_chars=len(user_prompt)):
            return dict(
                proposer_llms[kind].generate_json(
                    system_prompt=PROPOSER_SYSTEM_PROMPT.format(
                        kind_label=_KIND_LABELS[kind], rubric=VERIFY_RUBRICS[kind], chair_hint=CHAIR_HINT
                    ),
                    user_prompt=user_prompt,
                    schema=PROPOSER_SCHEMA,
                )
            )

    def _recheck_accept(task: VerifyTask, candidate, argument: str) -> str | None:
        """Hỏi lại chiều của lập luận khi agent "accept" việc bỏ nhưng lại dẫn turn_id.

        Chỉ gọi LLM khi lập luận dẫn ít nhất một lượt nói có thật; lỗi LLM thì giữ "accept".

        Đầu vào: task; candidate - bản vừa bị đề nghị bỏ; argument - lập luận của agent.
        Đầu ra: turn_id căn cứ giữ (thuộc các lượt được dẫn) nếu lập luận thực chất là
            phản biện, ngược lại None.
        """

        cited = _cited_turn_ids(argument, task["meeting_turns"])
        if not cited:
            return None
        kind = task["kind"]
        user_prompt = (
            f"Candidate: {_candidate_text(candidate, kind)}\n"
            f"Lập luận của agent: {argument}\nCác lượt được dẫn: {', '.join(cited)}"
        )
        try:
            with llm_call("stance_check", segment_id=task["segment_id"], prompt_chars=len(user_prompt)):
                result = dict(
                    proposer_llms[kind].generate_json(
                        system_prompt=STANCE_CHECK_SYSTEM_PROMPT.format(kind_label=_KIND_LABELS[kind]),
                        user_prompt=user_prompt,
                        schema=STANCE_CHECK_SCHEMA,
                    )
                )
        except LLMUpstreamError as exc:
            logger.warning("verifier: lỗi LLM khi kiểm lại lập trường ở %s: %s", task["item_key"], exc)
            return None
        if result.get("supports") != "keep":
            return None
        turn_id = read_confirm_turn_id(task["meeting_turns"], result.get("turn_id"))
        return turn_id if turn_id in cited else cited[0]

    def verifier(task: VerifyTask) -> dict:
        """Kiểm chứng MỘT candidate qua các vòng Verifier <-> agent trích xuất tới khi đồng thuận.

        Đầu vào: task - VerifyTask.
        Đầu ra: dict cập nhật state:
            - ``verification_records``: LUÔN trả một bản ghi (kèm các vòng trao đổi).
            - ``verified_assignments``/``verified_decisions``: candidate cuối khi giữ/sửa.
        """

        candidate = task["candidate"]
        rounds: list[ConsensusRound] = []
        outcome = None
        last_result: dict = {}
        for _ in range(config.consensus_max_rounds):
            try:
                result, steps = _run_react(task, candidate, rounds)
            except LLMUpstreamError as exc:
                logger.warning("verifier: lỗi LLM ở candidate %s: %s", task["item_key"], exc)
                return _settle(task, task["candidate"], rounds, verdict="unresolved", reasoning=f"(Verifier lỗi LLM: {exc})",
                               deciding_turn_id=None, decided_by="fallback")
            verdict, deciding_turn_id, resolved, feedback = _judge(task, candidate, result)
            outcome = (verdict, deciding_turn_id, resolved, feedback)
            last_result = result
            candidate_text = _candidate_text(candidate, task["kind"])
            if verdict == "keep":
                rounds.append(ConsensusRound(candidate_text, tuple(steps), verdict, feedback, deciding_turn_id))
                return _settle(task, resolved, rounds, verdict="keep", reasoning=feedback,
                               deciding_turn_id=deciding_turn_id, decided_by="consensus", actor_choice=result)
            try:
                response = _ask_proposer(task, candidate, verdict, feedback, steps, rounds)
            except LLMUpstreamError as exc:
                logger.warning("verifier: lỗi LLM khi hỏi lại agent trích xuất ở %s: %s", task["item_key"], exc)
                return _settle(task, task["candidate"], rounds, verdict="unresolved",
                               reasoning=f"(Agent trích xuất lỗi LLM khi trả lời feedback: {exc})",
                               deciding_turn_id=None, decided_by="fallback")
            stance, confirm_turn_id, argument = _read_stance(response, verdict, task["meeting_turns"])
            if stance == "accept" and verdict != "revise":
                defended = _recheck_accept(task, candidate, argument)
                if defended:
                    stance, confirm_turn_id = "defend", defended
                    argument = f"(Đổi accept thành defend vì lập luận dẫn lượt {defended} làm căn cứ giữ.) {argument}"
                    response = {**response, "stance": "defend", "confirm_turn_id": defended}
            rounds.append(
                ConsensusRound(
                    candidate_text, tuple(steps), verdict, feedback, deciding_turn_id,
                    stance=stance, response=argument, confirm_turn_id=confirm_turn_id,
                )
            )
            if stance == "accept":
                final_verdict = "revise" if verdict == "revise" else "drop"
                return _settle(task, resolved, rounds, verdict=final_verdict, reasoning=feedback,
                               deciding_turn_id=deciding_turn_id, decided_by="consensus", actor_choice=result)
            candidate = _apply_proposal(candidate, task["kind"], response, task["meeting_turns"])

        verdict, deciding_turn_id, resolved, feedback = outcome
        if verdict == "unresolved":
            return _settle(task, task["candidate"], rounds, verdict="unresolved",
                           reasoning=f"(Chưa đồng thuận sau {len(rounds)} vòng, giữ theo luật an toàn.) {feedback}",
                           deciding_turn_id=None, decided_by="fallback")
        return _settle(task, resolved, rounds, verdict=verdict,
                       reasoning=f"(Chưa đồng thuận sau {len(rounds)} vòng, theo kết luận của Verifier.) {feedback}",
                       deciding_turn_id=deciding_turn_id, decided_by="verifier", actor_choice=last_result)

    return verifier


__all__ = ["PROPOSER_SCHEMA", "PROPOSER_SYSTEM_PROMPT", "VERIFIER_SCHEMA", "VERIFIER_SYSTEM_PROMPT", "make_verifier"]
