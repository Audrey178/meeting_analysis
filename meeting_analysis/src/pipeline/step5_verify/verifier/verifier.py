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
    VIETNAMESE_VALUE,
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
You are the VERIFIER for a {kind_label} candidate extracted from ONE topic segment of a meeting
and flagged as UNCERTAIN by the automatic filter.

Criteria:
{rubric}
{chair_hint}

You have READ-ONLY tools to look up evidence in the WHOLE meeting:
{tools}

Each step returns exactly ONE JSON, with the fields in this order:
- thought: 1-2 sentences: what you know from the transcript and the previous steps, what is
  missing, why you look further or why you have enough grounds.
- To look further: action is the tool name, argument is its parameter; the conclusion fields are null.
- Enough grounds: action = "final", argument = null, and fill verdict:
  "keep" | "revise" | "drop" | "unresolved" (only when the evidence is truly contradictory
  or missing), deciding_turn_id (REQUIRED for keep/revise: turn_id of the turn that
  ASSIGNS/TAKES ON the task or CONCLUDES/AGREES, possibly in another topic), reasoning (1-2 sentences).

For an ASSIGNED TASK, the assignee may be a PERSON or a UNIT ("giao Sở Tài chính chủ trì" is valid).
When the assignee is only a form of address, may match someone else, or is doubtful: call
lookup_speaker("<form of address> @<turn_id of the confirming turn>") and then SUGGEST (you do not edit the
candidate yourself; the extractor agent edits it per your suggestion, so to change the assignee use
verdict = "revise"):
  revised_assignees: ONE element {{name, role, type}} PER assignee; name is EXACTLY the name of a
  candidate returned by the tool (do not write another name); role "lead" (leads) | "support" (cooperates) |
  "joint" (does it together, nobody leads); type "person" | "organization".
  actor_reason: why that candidate (who said what in which turn; rely on position/unit only
  when the transcript cannot tell).
If no candidate is clear, set type = "unknown" for each party (name keeps the transcript's form of address;
the assigned task is still kept). If the assignee does not need changing, revised_assignees = [].
For decisions, leave these two fields empty/null.

The "Automatic filter flags" only tell why the candidate was sent for checking: the filter only
scores ONE turn that the extractor agent gave and is often wrong, so those flags are NOT evidence
and must NOT be used as a reason to drop. The real ASSIGNING/SETTLING turn may differ from the turn
the agent gave. Before concluding drop/unresolved, read the settling and accepting words in the segment
(with a chair: the chair's turns), especially the last turns of the segment (summing-up, "đề nghị các đồng chí
...", "giao ...", "chuẩn bị lại ..."); if you find an assigning/settling turn with the candidate's content,
keep/revise with deciding_turn_id set to that turn.

You MUST compare CONTENT: deciding_turn_id must not merely be an assigning/settling turn in
general; that very turn must state the candidate's task or clearly refer to/accept the specific
request in the evidence turn. Do not use a summing-up turn about task A as grounds for task B just
because it is a settling turn. A turn of the person who raised the point is not an acceptance of
that point.

reasoning is the FEEDBACK sent back to the extractor agent when you do not keep: state precisely what
is wrong/missing and the grounding turn, so the agent can fix or rebut it. If there are earlier rounds,
weigh the agent's argument against the transcript; do not concede just because the agent objects.

Rely only on evidence actually in the transcript. "The content is mentioned in the transcript" is NOT
enough to keep. Look up as little as possible.

Write thought, reasoning and actor_reason in VIETNAMESE, the language of the transcript. Do NOT use
double quotes (") in thought, reasoning, actor_reason: cite turns by turn_id, do not quote verbatim.
{json_rule}
""".strip()


VERIFIER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "thought": {"type": "string", "description": VIETNAMESE_VALUE},
        "action": {"type": "string", "enum": [*TOOL_NAMES, "final"]},
        "argument": {"type": ["string", "null"]},
        "deciding_turn_id": {"type": ["string", "null"]},
        "verdict": {"type": ["string", "null"], "enum": ["keep", "revise", "drop", "unresolved", None]},
        "revised_assignees": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": VIETNAMESE_VALUE},
                    "role": {"type": "string", "enum": list(ASSIGNEE_ROLES)},
                    "type": {"type": "string", "enum": [*ASSIGNEE_TYPES, "unknown"]},
                },
                "required": ["name", "role", "type"],
            },
        },
        "actor_reason": {"type": ["string", "null"], "description": VIETNAMESE_VALUE},
        "reasoning": {"type": ["string", "null"], "description": VIETNAMESE_VALUE},
    },
    "required": [
        "thought", "action", "argument", "verdict", "deciding_turn_id", "revised_assignees",
        "actor_reason", "reasoning",
    ],
}

PROPOSER_SYSTEM_PROMPT = """
You are the EXTRACTOR AGENT that proposed the {kind_label} candidate below from ONE topic segment
of a meeting. The VERIFIER has just responded: a verdict and its reason (feedback). Check the
feedback against the transcript, then choose exactly ONE stance:
- "accept": agree with the verifier. If they ask for a revision (revise), YOU write the revision per
  their suggestion into revised_text/revised_assignees (the verifier does not edit for you); if they
  ask to drop / find no grounds, the candidate is dropped.
- "amend": fix the candidate to match the transcript: revised_text (new content, starting with a
  verb, without the assignee's name or the deadline) and/or revised_assignees (assigned tasks only:
  one element {{name, role, type}} per assigned person/unit with role "lead" |
  "support" | "joint", type "person" | "organization"; name exactly as in the transcript), together with
  confirm_turn_id, the turn that ASSIGNS/TAKES ON the task or CONCLUDES/AGREES. If the assignee does not
  change, revised_assignees = [].
- "defend": keep the candidate as is and point to the confirm_turn_id the verifier missed.

Fill confirm_turn_id BEFORE choosing the stance: the turn in the transcript that ASSIGNS/TAKES ON the
task or CONCLUDES/AGREES and grounds the candidate, null if there is none. If you can point to that
turn, the stance is "amend" or "defend", NOT "accept"; argument must agree with the chosen stance.

Criteria:
{rubric}
{chair_hint}

NEVER invent content that is not in the transcript. If you cannot find an assigning/taking-on/settling
turn, choose "accept". Unused fields are null.

argument: AT MOST 2 short sentences (under 300 characters), citing turns by turn_id. Write argument and
revised_text in VIETNAMESE, the language of the transcript. Do NOT quote turns verbatim and do NOT use
double quotes (") in any field. {json_rule}
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
                    "name": {"type": "string", "description": VIETNAMESE_VALUE},
                    "role": {"type": "string", "enum": list(ASSIGNEE_ROLES)},
                    "type": {"type": "string", "enum": list(ASSIGNEE_TYPES)},
                },
                "required": ["name", "role", "type"],
            },
        },
        "revised_text": {"type": ["string", "null"], "description": VIETNAMESE_VALUE},
        "argument": {"type": "string", "description": VIETNAMESE_VALUE},
    },
    "required": ["confirm_turn_id", "stance", "revised_assignees", "revised_text", "argument"],
}

_STANCE_LABELS = {"accept": "agreed", "amend": "amended the candidate", "defend": "kept it, rebutted"}


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

    reasons = "; ".join(task["reasons"]) or "(no specific reason)"
    return (
        f"{format_chair_line(task['registry'].chair)}\n"
        f"Candidate: {describe_candidate(candidate, task['kind'])}\n"
        f"Extractor agent's own claim: status '{candidate.status}', "
        f"confirming turn {candidate.confirm_turn_id or '(not given)'}, "
        f"evidence {', '.join(candidate.evidence_turn_ids)}\n"
        f"Automatic filter flags (only hints, may be wrong, NOT evidence): {reasons}\n\n"
        f"Segment transcript:\n{format_turns_as_transcript(task['turns'])}"
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
            base_prompt += f"\n\nPrevious rounds:\n{format_rounds(rounds, 'candidate', _STANCE_LABELS)}"
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
            parts.append(f"Previous rounds:\n{format_rounds(rounds, 'candidate', _STANCE_LABELS)}")
        parts.append(f"Verifier verdict: {review.verdict}\nFeedback: {review.feedback}")
        if review.suggestion:
            reason = f"\nReason: {review.suggestion_reason}" if review.suggestion_reason else ""
            parts.append(f"Verifier suggests assignees: {review.suggestion}{reason}")
        if review.steps:
            parts.append(f"Evidence the verifier looked up:\n{format_steps(review.steps)}")
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
