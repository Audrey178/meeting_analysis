"""Agent kiểm chứng cho việc giao và kết luận bị nghi ngờ.

Agent tự tra cứu bản ghi rồi nhận xét; agent trích xuất trả lời và có thể sửa mục. Chỉ agent trích
xuất được sửa nội dung mục; agent kiểm chứng chỉ nhận xét và gợi ý. Bản sửa phải còn giữ nội dung
của mục gốc, không được biến thành một việc khác.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace

from ....utils.llm_call_log import llm_call
from ....utils.ports import LLMAdapter
from ...config import AnalysisConfig
from ...shared.actors.assignees import format_actor, read_assignee_mentions
from ...shared.actors.resolution import apply_verifier_actor_choice
from ...shared.llm_output import (
    read_turn_id,
    read_stripped_text,
)
from ...shared.prompts import (
    CHAIR_HINT,
    JSON_ONE_LINE_RULE,
    VERIFY_RUBRICS,
    format_chair_line,
)
from ...shared.schemas import (
    ASSIGNEE_ROLES,
    ASSIGNEE_TYPES,
    ConsensusRound,
    Response,
    Review,
    VerificationRecord,
    VerifierStep,
    VerifyTask,
)
from ...shared.text import content_tokens
from ...shared.transcript import format_turns_as_transcript
from .consensus import evidence_with_turn, read_stance, run_consensus
from .react import format_rounds, format_steps, run_react
from .tools import TOOL_DESCRIPTIONS, TOOL_NAMES, MeetingTools
from .verdict import KIND_LABELS, describe_candidate, resolve_verdict, suggested_assignees

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

Với VIỆC GIAO, bên nhận việc có thể là NGƯỜI hoặc ĐƠN VỊ ("giao Sở Tài chính chủ trì" là hợp lệ).
Khi bên nhận việc chỉ là tên gọi, có thể trùng người khác, hoặc bị nghi ngờ: gọi
lookup_speaker("<cách gọi> @<turn_id lượt chốt>") rồi ĐỀ XUẤT (bạn không tự sửa candidate; agent trích
xuất sẽ sửa theo đề xuất, nên cần đổi bên nhận việc thì verdict = "revise"):
  revised_assignees: MỖI bên nhận việc một phần tử {{name, role, type}}; name là ĐÚNG tên một
  ứng viên tool trả về (không tự viết tên khác); role "lead" (chủ trì) | "support" (phối hợp) |
  "joint" (cùng thực hiện, không ai chủ trì); type "person" | "organization".
  actor_reason: vì sao chọn ứng viên đó (ai nói gì ở lượt nào; chỉ dựa vào chức vị/đơn
  vị khi bản ghi không phân định được).
Không có ứng viên nào rõ ràng thì để mỗi bên type = "unknown" (name giữ cách gọi trong bản ghi;
việc giao vẫn giữ). Không cần sửa bên nhận việc thì revised_assignees = [].
Với quyết định, hai trường này để rỗng/null.

"Cờ của bộ lọc tự động" chỉ cho biết vì sao candidate bị gửi kiểm tra: bộ lọc chỉ
chấm MỘT lượt nói mà agent trích xuất khai và hay sai, nên cờ đó KHÔNG phải bằng
chứng và KHÔNG được dùng làm lý do bỏ. Lượt GIAO/CHỐT thật có thể khác lượt agent
khai. Trước khi kết luận drop/unresolved, đọc các lời chốt và lời tiếp nhận trong đoạn
(có người chủ trì: các lượt của người chủ trì), nhất là các lượt cuối đoạn (tổng kết, "đề nghị các đồng chí
...", "giao ...", "chuẩn bị lại ..."); thấy lượt giao/chốt đúng nội dung candidate
thì keep/revise với deciding_turn_id là lượt đó.

BẮT BUỘC so NỘI DUNG: deciding_turn_id không chỉ phải là một lượt giao/chốt nói
chung, mà chính lượt đó phải nói đúng việc candidate hoặc quy chiếu/tiếp nhận rõ
yêu cầu cụ thể ở lượt evidence. Không được dùng một lượt tổng kết về việc A
làm căn cứ cho việc B chỉ vì lượt đó là lời chốt. Lượt của chính người nêu ý không
phải lời tiếp nhận ý đó.

reasoning là FEEDBACK gửi lại agent trích xuất khi bạn không giữ: nêu cụ thể điểm
sai/thiếu và lượt nói làm căn cứ, để agent sửa hoặc phản biện. Đã có các vòng trao đổi
trước thì xét lập luận của agent trên bản ghi, không nhượng bộ chỉ vì agent phản biện.

Chỉ dựa vào bằng chứng có thật trong bản ghi. "Nội dung có nhắc trong bản ghi" CHƯA đủ
để giữ. Tra ít nhất có thể.

KHÔNG dùng dấu nháy kép (") trong thought, reasoning, actor_reason: dẫn lượt nói bằng
turn_id, không trích nguyên văn. {json_rule}
""".strip()


VERIFIER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "action": {"type": "string", "enum": [*TOOL_NAMES, "final"]},
        "argument": {"type": ["string", "null"]},
        "deciding_turn_id": {"type": ["string", "null"]},
        "verdict": {"type": ["string", "null"], "enum": ["keep", "revise", "drop", "unresolved", None]},
        "revised_assignees": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string", "enum": list(ASSIGNEE_ROLES)},
                    "type": {"type": "string", "enum": [*ASSIGNEE_TYPES, "unknown"]},
                },
                "required": ["name", "role", "type"],
            },
        },
        "actor_reason": {"type": ["string", "null"]},
        "reasoning": {"type": ["string", "null"]},
    },
    "required": [
        "thought", "action", "argument", "verdict", "deciding_turn_id", "revised_assignees",
        "actor_reason", "reasoning",
    ],
}

PROPOSER_SYSTEM_PROMPT = """
Bạn là AGENT TRÍCH XUẤT đã đề xuất candidate {kind_label} dưới đây từ MỘT đoạn chủ đề
của cuộc họp. KIỂM CHỨNG VIÊN vừa phản hồi: kết luận và lý do (feedback). Đối chiếu
feedback với bản ghi rồi chọn đúng MỘT lập trường:
- "accept": đồng ý với kiểm chứng viên. Họ đề nghị sửa (revise) thì CHÍNH BẠN viết bản sửa theo
  đề xuất của họ vào revised_text/revised_assignees (kiểm chứng viên không sửa hộ); họ đề nghị
  bỏ / không đủ căn cứ thì candidate bị bỏ.
- "amend": sửa candidate cho đúng bản ghi: revised_text (nội dung mới, bắt đầu bằng
  động từ, không chứa tên người nhận việc hay thời hạn) và/hoặc revised_assignees (chỉ với
  việc giao: mỗi người/đơn vị nhận việc một phần tử {{name, role, type}} với role "lead" |
  "support" | "joint", type "person" | "organization"; name đúng nguyên văn bản ghi), kèm
  confirm_turn_id là lượt nói GIAO/NHẬN việc hoặc KẾT LUẬN/THỐNG NHẤT. Không sửa bên nhận
  việc thì revised_assignees = [].
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
nguyên văn lượt nói và KHÔNG dùng dấu nháy kép (") trong bất kỳ trường nào. {json_rule}
""".strip()


PROPOSER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "confirm_turn_id": {"type": ["string", "null"]},
        "stance": {"type": "string", "enum": ["accept", "amend", "defend"]},
        "revised_assignees": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string", "enum": list(ASSIGNEE_ROLES)},
                    "type": {"type": "string", "enum": list(ASSIGNEE_TYPES)},
                },
                "required": ["name", "role", "type"],
            },
        },
        "revised_text": {"type": ["string", "null"]},
        "argument": {"type": "string"},
    },
    "required": ["confirm_turn_id", "stance", "revised_assignees", "revised_text", "argument"],
}

_STANCE_LABELS = {"accept": "đồng ý", "amend": "đã sửa candidate", "defend": "giữ nguyên, phản biện"}


_AMEND_MIN_RETAINED = 0.5

_AMEND_MIN_REVISED_COVERAGE = 0.5


def _rubric(task: VerifyTask) -> str:
    """Lấy bộ tiêu chí kiểm chứng ứng với loại mục của yêu cầu."""

    return VERIFY_RUBRICS[task["kind"]]


def _build_candidate_prompt(task: VerifyTask, candidate) -> str:
    """Dựng phần đầu prompt dùng chung cho Verifier và agent trích xuất.

    Gồm: người chủ trì (nếu có), mục đang xét, những gì agent trích xuất tự khai, lý do bị gắn cờ (ghi
    rõ chỉ là gợi ý, không phải bằng chứng) và bản ghi của chủ đề.

    Args:
        task: Yêu cầu kiểm chứng.
        candidate: Bản mục đang xét (có thể đã được sửa ở vòng trước).

    Returns:
        Phần đầu của user prompt.
    """

    reasons = "; ".join(task["reasons"]) or "(không có lý do cụ thể)"
    return (
        f"{format_chair_line(task['registry'].chair)}\n"
        f"Candidate: {describe_candidate(candidate, task['kind'])}\n"
        f"Agent trích xuất tự khai: trạng thái '{candidate.status}', "
        f"lượt chốt {candidate.confirm_turn_id or '(không nêu)'}, "
        f"bằng chứng {', '.join(candidate.evidence_turn_ids)}\n"
        f"Cờ của bộ lọc tự động (chỉ là gợi ý, có thể sai, KHÔNG phải bằng chứng): {reasons}\n\n"
        f"Bản ghi của đoạn:\n{format_turns_as_transcript(task['turns'])}"
    )


def _keeps_original_content(original: str, revised: str) -> bool:
    """Kiểm bản sửa của agent còn nói về cùng việc với mục gốc, không bị biến thành một việc khác.

    So tập từ nội dung của hai câu: phần chung phải chiếm đủ tỉ lệ so với câu ngắn hơn và so với bản sửa.
    Một trong hai câu không có từ nội dung nào thì coi như đạt.

    Args:
        original: Nội dung mục trước khi sửa.
        revised: Nội dung agent đề nghị sửa thành.

    Returns:
        True nếu bản sửa còn giữ nội dung gốc.
    """

    original_terms, revised_terms = content_tokens(original), content_tokens(revised)
    if not original_terms or not revised_terms:
        return True
    shared = len(original_terms & revised_terms)
    retained = shared / min(len(original_terms), len(revised_terms))
    revised_coverage = shared / len(revised_terms)
    return retained >= _AMEND_MIN_RETAINED and revised_coverage >= _AMEND_MIN_REVISED_COVERAGE


def _apply_proposal(candidate, kind: str, response: dict, meeting_turns):
    """Áp phần agent trích xuất tự sửa lên mục.

    Lượt chốt agent chỉ ra (hợp lệ) luôn được ghi vào mục và thêm vào bằng chứng nếu còn thiếu. Khi
    lập trường là "amend" hoặc "accept", bên nhận việc mới (chỉ với việc giao) và nội dung mới cũng được
    áp; nội dung mới bị bỏ qua nếu nó đã biến thành một việc khác.

    Args:
        candidate: Mục đang xét.
        kind: "action" hoặc "decision".
        response: JSON agent trích xuất trả về.
        meeting_turns: Toàn bộ lượt nói của cuộc họp, để kiểm lượt chốt có thật.

    Returns:
        Mục sau khi sửa; chính mục cũ nếu không có gì thay đổi.
    """

    changes: dict = {}
    confirm_turn_id = read_turn_id(meeting_turns, response.get("confirm_turn_id"))
    if confirm_turn_id:
        changes["confirm_turn_id"] = confirm_turn_id
        if confirm_turn_id not in candidate.evidence_turn_ids:
            changes.update(evidence_with_turn(candidate, confirm_turn_id, meeting_turns))
    if response.get("stance") in ("amend", "accept"):
        revised = read_assignee_mentions(response.get("revised_assignees")) if kind == "action" else ()
        if revised:
            changes["actor"], changes["mentions"] = format_actor(revised), revised
        text = read_stripped_text(response.get("revised_text"))
        if text and _keeps_original_content(candidate.text, text):
            changes["text"] = text
        elif text:
            logger.info("verifier: bỏ bản sửa đổi sang việc khác: %r -> %r", candidate.text, text)
    return replace(candidate, **changes) if changes else candidate


class Verifier:
    """Kiểm chứng một việc giao hoặc kết luận UNCERTAIN qua trao đổi giữa Verifier và agent trích xuất.

    Cài đặt hợp đồng ``ConsensusParty``: Verifier tự tra bản ghi rồi nhận xét, agent trích xuất trả lời
    và là bên duy nhất được sửa mục.

    Args:
        llm: Mô hình của Verifier.
        proposer_llms: Mô hình của agent trích xuất theo loại mục, khoá "action" và "decision".
        config: Cấu hình pipeline (số bước tra cứu, số vòng trao đổi, số kết quả tìm kiếm).
    """

    def __init__(
        self,
        llm: LLMAdapter,
        proposer_llms: Mapping[str, LLMAdapter],
        config: AnalysisConfig,
    ) -> None:
        self.llm = llm
        self.proposer_llms = proposer_llms
        self.config = config

    @staticmethod
    def describe(task: VerifyTask, claim) -> str:
        """Trả một dòng mô tả mục cho bản ghi các vòng trao đổi."""

        return describe_candidate(claim, task["kind"])

    def settle(self, task, claim, rounds, *, verdict, reasoning, deciding_turn_id, decided_by,
               edit_reason: str = "") -> dict:
        """Đóng gói kết quả cuối của một mục thành phần cập nhật trạng thái của pipeline.

        Mục được giữ khi kết luận khác "drop" (kể cả "unresolved"). Với việc giao được giữ, lựa chọn bên
        nhận việc được định danh lại theo danh bạ, kèm lý do đổi bên nhận việc (nếu có).

        Args:
            task: Yêu cầu kiểm chứng gốc.
            claim: Bản mục cuối cùng.
            rounds: Toàn bộ các vòng trao đổi.
            verdict: Kết luận cuối.
            reasoning: Lý do của kết luận cuối.
            deciding_turn_id: Lượt nói làm căn cứ, None nếu không có.
            decided_by: "consensus", "verifier" hoặc "fallback".
            edit_reason: Lý do đổi bên nhận việc, rỗng nếu không đổi.

        Returns:
            Dict có ``verification_records`` (luôn một bản ghi) và, nếu giữ, ``verified_assignments``
            hoặc ``verified_decisions``.
        """

        kind = task["kind"]
        kept = verdict != "drop"
        verification = {"consensus": "consensus", "verifier": "verifier"}.get(
            decided_by, "fallback"
        )
        claim = replace(claim, verification=verification)
        if kind == "action" and kept:
            claim = apply_verifier_actor_choice(
                claim, {"actor_reason": edit_reason}, task["registry"], task["meeting_turns"]
            )
        record = VerificationRecord(
            item_key=task["item_key"], segment_id=task["segment_id"], kind=kind,
            candidate_text=describe_candidate(task["candidate"], kind), reasons=task["reasons"],
            steps=tuple(step for round_ in rounds for step in round_.steps),
            verdict=verdict, reasoning=reasoning,
            final_text=describe_candidate(claim, kind) if kept else "",
            deciding_turn_id=deciding_turn_id, decided_by=decided_by, rounds=tuple(rounds),
        )
        update: dict = {"verification_records": [record]}
        if kept:
            key = "verified_assignments" if kind == "action" else "verified_decisions"
            update[key] = [claim]
        return update

    def _run_react(self, task: VerifyTask, candidate, rounds: list[ConsensusRound]) -> tuple[dict, list[VerifierStep]]:
        """Chạy một vòng tra cứu từng bước của Verifier trên bản mục hiện tại.

        Args:
            task: Yêu cầu kiểm chứng.
            candidate: Bản mục đang xét.
            rounds: Các vòng trước, đưa vào prompt.

        Returns:
            Cặp (JSON lượt kết luận, hoặc dict rỗng nếu hết lượt mà chưa kết luận; các bước tra cứu).

        Raises:
            LLMUpstreamError: Khi lời gọi mô hình lỗi.
        """

        kind = task["kind"]
        tools = MeetingTools(
            task["meeting_turns"],
            task["registry"],
            search_top_k=self.config.search_top_k,
            task_text=candidate.text,
            is_self_committed=getattr(candidate, "status", None) == "self_committed",
        )
        system_prompt = VERIFIER_SYSTEM_PROMPT.format(
            kind_label=KIND_LABELS[kind], rubric=_rubric(task), chair_hint=CHAIR_HINT, tools=TOOL_DESCRIPTIONS,
            json_rule=JSON_ONE_LINE_RULE,
        )
        base_prompt = _build_candidate_prompt(task, candidate)
        if rounds:
            base_prompt += f"\n\nCác vòng trao đổi trước:\n{format_rounds(rounds, 'candidate', _STANCE_LABELS)}"
        return run_react(
            self.llm, tools, system_prompt=system_prompt, schema=VERIFIER_SCHEMA, base_prompt=base_prompt,
            max_calls=self.config.verifier_max_tool_calls + 1, log_name="verifier", segment_id=task["segment_id"],
        )

    def review(self, task: VerifyTask, claim, rounds: list[ConsensusRound]) -> Review:
        """Cho Verifier xét mục: một vòng tra cứu rồi áp luật hậu kiểm; không sửa mục.

        Hết lượt mà chưa kết luận, hoặc Verifier tự chọn "unresolved", thì nhận xét là "unresolved". Giữ
        hay sửa mà không chỉ ra được lượt căn cứ có thật thì bị hạ thành "drop", kèm ghi chú trong lý do.

        Args:
            task: Yêu cầu kiểm chứng.
            claim: Bản mục đang xét.
            rounds: Các vòng trước.

        Returns:
            Nhận xét của Verifier; khi kết luận là "revise", bên nhận việc đề xuất nằm ở ``suggestion``.

        Raises:
            LLMUpstreamError: Khi lời gọi mô hình lỗi.
        """

        result, steps = self._run_react(task, claim, rounds)
        reasoning = read_stripped_text(result.get("reasoning"))
        raw_verdict = result.get("verdict")
        if not result:
            return Review("unresolved", None, "(Verifier hết số bước mà chưa kết luận.)", tuple(steps))
        if raw_verdict not in ("keep", "revise", "drop"):
            return Review("unresolved", None, reasoning or "(Verifier không đủ căn cứ để kết luận.)", tuple(steps))
        resolve_input = {"kind": task["kind"], "candidate": claim, "turns": task["meeting_turns"]}
        verdict, deciding_turn_id = resolve_verdict(resolve_input, result)
        if verdict == "drop" and raw_verdict in ("keep", "revise"):
            reasoning = f"(Hạ thành drop: không chỉ ra được lượt nói giao/chốt.) {reasoning}"
        suggested = suggested_assignees(task["kind"], result) if verdict == "revise" else ()
        return Review(
            verdict, deciding_turn_id, reasoning, tuple(steps),
            suggestion="; ".join(f"{m.name} ({m.role}, {m.actor_type})" for m in suggested),
            suggestion_reason=read_stripped_text(result.get("actor_reason")) if suggested else "",
        )

    def respond(self, task: VerifyTask, claim, review: Review, rounds: list[ConsensusRound]) -> Response:
        """Cho agent trích xuất trả lời nhận xét và đề xuất của Verifier; agent tự sửa mục nếu cần.

        Args:
            task: Yêu cầu kiểm chứng.
            claim: Bản mục Verifier vừa xét.
            review: Nhận xét của Verifier ở vòng này.
            rounds: Các vòng trước.

        Returns:
            Câu trả lời gồm lập trường, lượt chốt, lập luận và mục đã áp phần agent sửa; ``edit_reason``
            chỉ có khi agent đổi bên nhận việc.

        Raises:
            LLMUpstreamError: Khi lời gọi mô hình lỗi.
        """

        kind = task["kind"]
        parts = [_build_candidate_prompt(task, claim)]
        if rounds:
            parts.append(f"Các vòng trao đổi trước:\n{format_rounds(rounds, 'candidate', _STANCE_LABELS)}")
        parts.append(f"Kiểm chứng viên kết luận: {review.verdict}\nFeedback: {review.feedback}")
        if review.suggestion:
            reason = f"\nLý do: {review.suggestion_reason}" if review.suggestion_reason else ""
            parts.append(f"Kiểm chứng viên đề xuất bên nhận việc: {review.suggestion}{reason}")
        if review.steps:
            parts.append(f"Bằng chứng kiểm chứng viên đã tra:\n{format_steps(review.steps)}")
        user_prompt = "\n\n".join(parts)
        with llm_call("verifier_feedback", segment_id=task["segment_id"], prompt_chars=len(user_prompt)):
            response = dict(
                self.proposer_llms[kind].generate_json(
                    system_prompt=PROPOSER_SYSTEM_PROMPT.format(
                        kind_label=KIND_LABELS[kind], rubric=_rubric(task), chair_hint=CHAIR_HINT,
                        json_rule=JSON_ONE_LINE_RULE,
                    ),
                    user_prompt=user_prompt,
                    schema=PROPOSER_SCHEMA,
                )
            )
        stance, confirm_turn_id, argument = read_stance(response, review.verdict, task["meeting_turns"])
        revised = _apply_proposal(claim, kind, {**response, "stance": stance}, task["meeting_turns"])
        changed_actor = getattr(revised, "mentions", ()) != getattr(claim, "mentions", ())
        return Response(stance, confirm_turn_id, argument, revised,
                        edit_reason=(review.suggestion_reason or argument) if changed_actor else "")

    def run(self, task: VerifyTask) -> dict:
        """Kiểm chứng một mục qua các vòng trao đổi giữa Verifier và agent trích xuất.

        Args:
            task: Yêu cầu kiểm chứng của một việc giao hoặc kết luận.

        Returns:
            Dict cập nhật trạng thái: ``verification_records`` luôn có một bản ghi (kèm các vòng trao
            đổi); ``verified_assignments`` hoặc ``verified_decisions`` chứa mục cuối nếu mục được giữ.
        """

        return run_consensus(self, task, self.config.consensus_max_rounds)


__all__ = [
    "PROPOSER_SCHEMA",
    "PROPOSER_SYSTEM_PROMPT",
    "VERIFIER_SCHEMA",
    "VERIFIER_SYSTEM_PROMPT",
    "Verifier",
]
