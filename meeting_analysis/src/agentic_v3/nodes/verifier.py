"""Node Verifier (ReAct, có giới hạn bước) + vòng đồng thuận với agent trích xuất.

Thay Debate+Judge 3 vai của v1 (support -> oppose -> judge, 3 lời gọi NỐI TIẾP chỉ
đọc lại đúng đoạn hiện tại). Verifier tự tra bằng chứng trong CẢ cuộc họp qua tool
chỉ đọc (``tools.MeetingTools``), thường kết luận sau 1-2 lời gọi; tối đa
``verifier_max_tool_calls + 1`` lời gọi mỗi vòng.

ReAct dựng trên ``LLMAdapter.generate_json`` (một lượt hỏi-đáp JSON), không cần
provider hỗ trợ tool calling: mỗi lượt model trả ``{thought, action, argument, ...}``,
code chạy tool rồi đưa observation vào prompt lượt sau. Lượt cuối bắt buộc
``action="final"``.

Kết luận đi qua đúng luật hậu kiểm của v1 (``_resolve_verdict``): giữ/sửa mà không
chỉ ra được lượt nói giao/chốt thì hạ thành bỏ. Khác v1: lượt đó được phép nằm ở
chủ đề khác của cùng cuộc họp, vì tool cho Verifier thấy cả cuộc họp.

Vòng đồng thuận (thay cho duyệt người): Verifier giữ (keep) thì xong ngay. Mọi kết
luận khác (revise/drop/unresolved) được gửi lại làm feedback cho agent trích xuất
(``action_llm``/``decision_llm``), agent này trả một lập trường:

    accept -> đồng thuận theo Verifier (revise: giữ bản sửa; drop/unresolved: bỏ).
    amend  -> agent sửa candidate theo bản ghi; vòng sau Verifier xét bản đã sửa.
    defend -> agent giữ nguyên, chỉ ra lượt giao/chốt; vòng sau Verifier xét lại
              kèm lập luận đó.

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
from collections.abc import Mapping
from dataclasses import replace

from ...agentic._shared import is_non_identifying_actor, read_confirm_turn_id, read_stripped_text
from ...agentic.nodes.debate_judge_agent import (
    _KIND_LABELS,
    _RUBRICS,
    _build_debate_user_prompt,
    _candidate_text,
    _resolve_verdict,
)
from ...utils.llm_call_log import llm_call
from ...utils.ports import LLMAdapter, LLMUpstreamError
from ..actors.resolution import apply_verifier_actor_choice
from ..config import V3Config
from ..schemas import ConsensusRound, VerificationRecord, VerifierStep, VerifyTask
from .verifier_tools import TOOL_DESCRIPTIONS, TOOL_NAMES, MeetingTools

logger = logging.getLogger(__name__)

VERIFIER_SYSTEM_PROMPT = """
Bạn là KIỂM CHỨNG VIÊN cho một candidate {kind_label} trích từ MỘT đoạn chủ đề
của cuộc họp, bị kiểm tra bằng luật đánh dấu CHƯA CHẮC CHẮN.

Tiêu chí:
{rubric}

Bạn có các tool CHỈ ĐỌC để tra bằng chứng trong CẢ cuộc họp:
{tools}

Mỗi lượt trả về đúng MỘT JSON:
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

reasoning là FEEDBACK gửi lại agent trích xuất khi bạn không giữ: nêu cụ thể điểm
sai/thiếu và lượt nói làm căn cứ, để agent sửa hoặc phản biện. Nếu đã có các vòng
trao đổi trước, xét lập luận của agent trích xuất trên bản ghi, không nhượng bộ chỉ
vì agent phản biện.

Chỉ dựa vào bằng chứng có thật trong bản ghi. "Nội dung có nhắc trong bản ghi" CHƯA
đủ để giữ. Không lặp lại một lần tra đã làm. Tra ít nhất có thể.
""".strip()

VERIFIER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "action": {"type": "string", "enum": [*TOOL_NAMES, "final"]},
        "argument": {"type": ["string", "null"]},
        "verdict": {"type": ["string", "null"], "enum": ["keep", "revise", "drop", "unresolved", None]},
        "deciding_turn_id": {"type": ["string", "null"]},
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

Tiêu chí:
{rubric}

TUYỆT ĐỐI KHÔNG bịa nội dung không có trong bản ghi. Không tìm được lượt giao/nhận/chốt
thì chọn "accept". Trường không dùng để null.

argument: TỐI ĐA 2 câu ngắn (dưới 300 ký tự), dẫn chứng bằng turn_id. KHÔNG trích
nguyên văn lượt nói và KHÔNG dùng dấu nháy kép (") trong bất kỳ trường nào.
""".strip()

# ``argument`` (văn bản tự do) đứng CUỐI: gemma viết xong lập luận thì muốn đóng JSON;
# nếu sau nó còn trường bắt buộc, model sinh khoảng trắng vô tận thay vì dấu phẩy.
PROPOSER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "stance": {"type": "string", "enum": ["accept", "amend", "defend"]},
        "confirm_turn_id": {"type": ["string", "null"]},
        "revised_text": {"type": ["string", "null"]},
        "revised_actor": {"type": ["string", "null"]},
        "argument": {"type": "string"},
    },
    "required": ["stance", "confirm_turn_id", "revised_text", "revised_actor", "argument"],
}

_STANCE_LABELS = {"accept": "đồng ý", "amend": "đã sửa candidate", "defend": "giữ nguyên, phản biện"}


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
    """Các bước tra cứu dạng ``Bước i: action(argument)`` kèm kết quả."""

    return "\n\n".join(
        f"Bước {i}: {step.action}({step.argument})\nKết quả:\n{step.observation}"
        for i, step in enumerate(steps, 1)
    )


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
            f"  Agent trích xuất ({_STANCE_LABELS.get(round_.stance, round_.stance)}): {round_.response}"
        )
    return "\n".join(lines)


def _apply_proposal(candidate, kind: str, response: dict, meeting_turns):
    """Áp phần sửa (amend) hoặc lượt chốt (defend) agent trích xuất gửi lại lên candidate.

    Chỉ nhận actor định danh được và ``confirm_turn_id`` là lượt nói thật của cuộc họp.

    Đầu vào: candidate; kind - "action"/"decision"; response - JSON agent trả;
        meeting_turns - lượt nói cả cuộc họp.
    Đầu ra: candidate (có thể không đổi).
    """

    changes: dict = {}
    confirm_turn_id = read_confirm_turn_id(meeting_turns, response.get("confirm_turn_id"))
    if confirm_turn_id:
        changes["confirm_turn_id"] = confirm_turn_id
    if response.get("stance") == "amend":
        text = read_stripped_text(response.get("revised_text"))
        if text:
            changes["text"] = text
        actor = read_stripped_text(response.get("revised_actor"))
        if kind == "action" and actor and not is_non_identifying_actor(actor):
            changes["actor"] = actor
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
            kind_label=_KIND_LABELS[kind], rubric=_RUBRICS[kind], tools=TOOL_DESCRIPTIONS
        )
        base_prompt = _build_debate_user_prompt({**task, "candidate": candidate}, _candidate_text(candidate, kind))
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
                    observation=tools.run(action, argument),
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
        parts = [_build_debate_user_prompt({**task, "candidate": candidate}, _candidate_text(candidate, kind))]
        if rounds:
            parts.append(f"Các vòng trao đổi trước:\n{_format_rounds(rounds)}")
        parts.append(f"Kiểm chứng viên kết luận: {verdict}\nFeedback: {feedback}")
        if steps:
            parts.append(f"Bằng chứng kiểm chứng viên đã tra:\n{_format_steps(steps)}")
        user_prompt = "\n\n".join(parts)
        with llm_call("verifier_feedback", segment_id=task["segment_id"], prompt_chars=len(user_prompt)):
            return dict(
                proposer_llms[kind].generate_json(
                    system_prompt=PROPOSER_SYSTEM_PROMPT.format(kind_label=_KIND_LABELS[kind], rubric=_RUBRICS[kind]),
                    user_prompt=user_prompt,
                    schema=PROPOSER_SCHEMA,
                )
            )

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
            stance = response.get("stance")
            rounds.append(
                ConsensusRound(
                    candidate_text, tuple(steps), verdict, feedback, deciding_turn_id,
                    stance=stance if stance in _STANCE_LABELS else "",
                    response=read_stripped_text(response.get("argument")),
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
