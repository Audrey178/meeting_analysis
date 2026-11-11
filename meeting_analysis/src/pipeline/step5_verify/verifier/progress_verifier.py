"""Agent kiểm chứng cho các cập nhật tiến độ bị nghi ngờ: tự tra cứu bản ghi rồi trao đổi với agent
giao việc (nơi đã ghi tiến độ) cho tới khi hai bên thống nhất.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from ....utils.llm_call_log import llm_call
from ....utils.ports import LLMAdapter
from ...config import AnalysisConfig
from ...shared.actors.assignees import format_actor, read_assignee_mentions
from ...shared.llm_output import read_stripped_text, read_turn_id
from ...shared.prompts import CHAIR_HINT, JSON_ONE_LINE_RULE, VERIFY_RUBRICS, VIETNAMESE_VALUE, format_chair_line
from ...shared.schemas import (
    ConsensusRound,
    ProgressUpdate,
    Response,
    Review,
    VerificationRecord,
    VerifierStep,
    VerifyTask,
)
from ...shared.transcript import format_turns_as_transcript
from .consensus import evidence_with_turn, read_stance, run_consensus
from .react import format_rounds, format_steps, run_react
from .tools import TOOL_DESCRIPTIONS, TOOL_NAMES, MeetingTools, content_syllables, format_turn_line
from .verdict import suggested_assignees
from .verifier import PROPOSER_SCHEMA, VERIFIER_SCHEMA

logger = logging.getLogger(__name__)

# Trạng thái Verifier/Action agent được chọn.
CLAIM_STATUSES = ("done", "in_progress", "cancelled")

STATUS_LABELS = {
    "done": "đã hoàn thành",
    "in_progress": "đang thực hiện",
    "cancelled": "huỷ",
    "mentioned": "chỉ được nhắc tới",
}

PROGRESS_VERIFIER_SYSTEM_PROMPT = """
You are the VERIFIER for a PROGRESS UPDATE of an old task (a task in the list to report on),
extracted from ONE topic segment of a meeting and flagged as UNCERTAIN by the automatic filter.

Criteria:
{rubric}
{chair_hint}

You have READ-ONLY tools to look up evidence in the WHOLE meeting:
{tools}

Each step returns exactly ONE JSON, with the fields in this order:
- thought: 1-2 sentences: what you know, what is missing, why you look further or why you have
  enough grounds.
- To look further: action is the tool name, argument is its parameter; the conclusion fields are null.
  The argument of search_meeting is ONE Vietnamese phrase of 3-8 words about the task content (e.g.
  giải trình ý kiến Bộ Xây dựng): do not list synonyms or status names, do not repeat words.
- Enough grounds: action = "final", argument = null, then fill:
  reasoning (1-2 sentences, written BEFORE the verdict): which turn says what about this very task,
  and therefore what the task's correct status is,
  deciding_turn_id (REQUIRED for keep/revise: turn_id of the turn that STATES THE STATUS of or GIVES A
  DIRECTIVE on this very task, or the turn where the chair ACCEPTS a member's proposal; possibly in
  another topic),
  verdict EXACTLY per the reasoning: "keep" (the status in the reasoning equals the status of the update
  under review) | "revise" (the task's status is stated but it is a different status, fill
  revised_status; or the new assignee is wrong, fill revised_assignees) | "drop" (no turn states the
  status of this very task, or the proposal was not accepted) | "unresolved" (only when the evidence is
  truly contradictory),
  revised_status (only when changing the status, otherwise null).

When the update REASSIGNS the task to another party (the "bên nhận việc mới" part), the assignee may be
a PERSON or a UNIT. When the assignee is only a form of address, may match someone else, or is doubtful:
call lookup_speaker("<form of address> @<turn_id of the assigning turn>") and then SUGGEST:
  revised_assignees: ONE element {{name, role, type}} PER assignee; name is EXACTLY the name of a
  candidate returned by the tool (do not write another name); role "lead" (leads) | "support" (cooperates) |
  "joint" (does it together, nobody leads); type "person" | "organization".
  actor_reason: why that candidate (who said what in which turn).
If no candidate is clear, set type = "unknown" for each party. If the assignee does not need changing,
or the task is not reassigned, revised_assignees = [] and actor_reason = null.

revised_status and revised_assignees are only SUGGESTIONS: you do not edit the update yourself; the
extractor agent edits it accordingly.

The "Points to check" are questions sent by the automatic filter (which is often wrong): answer them
from the transcript; they are NOT evidence for or against the update. The real status turn may differ
from the turn the agent gave. The "Evidence excerpts" are the parts of the turns the agent pointed to
that are closest to the task (long turns are cut around them): read them before concluding whether
that turn is about the task.

reasoning is the FEEDBACK sent back to the extractor agent when you do not keep: state precisely what
is wrong and the grounding turn. Rely only on evidence actually in the transcript. Look up as little
as possible.

Write thought, reasoning and actor_reason in VIETNAMESE, the language of the transcript. Do NOT use
double quotes (") in thought, reasoning, actor_reason: cite turns by turn_id. {json_rule}
""".strip()

PROGRESS_VERIFIER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "thought": {"type": "string", "description": VIETNAMESE_VALUE},
        "action": {"type": "string", "enum": [*TOOL_NAMES, "final"]},
        "argument": {"type": ["string", "null"]},
        "reasoning": {"type": ["string", "null"], "description": VIETNAMESE_VALUE},
        "deciding_turn_id": {"type": ["string", "null"]},
        "verdict": {"type": ["string", "null"], "enum": ["keep", "revise", "drop", "unresolved", None]},
        "revised_status": {"type": ["string", "null"], "enum": [*CLAIM_STATUSES, None]},
        "revised_assignees": VERIFIER_SCHEMA["properties"]["revised_assignees"],
        "actor_reason": {"type": ["string", "null"], "description": VIETNAMESE_VALUE},
    },
    "required": [
        "thought", "action", "argument", "reasoning", "deciding_turn_id", "verdict", "revised_status",
        "revised_assignees", "actor_reason",
    ],
}

PROGRESS_PROPOSER_SYSTEM_PROMPT = """
You are the EXTRACTOR AGENT that wrote the PROGRESS UPDATE below for an old task. The VERIFIER has just
responded: a verdict and its reason (feedback). Check the feedback against the transcript, then choose
exactly ONE stance:
- "accept": agree with the verifier. If they suggest a different status or assignee, YOU write that
  suggestion into revised_status/revised_assignees (the verifier does not edit for you); if they find
  no turn stating the task's status, the update is dropped.
- "amend": fix the update to match the transcript: revised_status (a different status) and/or
  revised_assignees (the new assignee when the task is reassigned: one element {{name, role, type}} per
  party with role "lead" | "support" | "joint", type "person" | "organization"; name exactly as in the
  transcript), together with confirm_turn_id, the turn stating that status/reassignment. If the assignee
  does not change, revised_assignees = [].
- "defend": keep the update as is and point to the confirm_turn_id the verifier missed.

Fill confirm_turn_id BEFORE choosing the stance: the turn stating the status of/giving a directive on
this very task (or the turn where the chair accepts a proposal), null if there is none. If you can point
to that turn, the stance is "amend" or "defend".

Criteria:
{rubric}
{chair_hint}

NEVER invent content that is not in the transcript. If you cannot find a turn stating the status,
choose "accept". Unused fields are null. argument: AT MOST 2 short sentences in VIETNAMESE, citing turns
by turn_id, WITHOUT double quotes ("). {json_rule}
""".strip()

# ``argument`` (văn bản tự do) đứng CUỐI, như ``verifier.PROPOSER_SCHEMA``.
PROGRESS_PROPOSER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "confirm_turn_id": {"type": ["string", "null"]},
        "stance": {"type": "string", "enum": ["accept", "amend", "defend"]},
        "revised_status": {"type": ["string", "null"], "enum": [*CLAIM_STATUSES, None]},
        "revised_assignees": PROPOSER_SCHEMA["properties"]["revised_assignees"],
        "argument": {"type": "string", "description": VIETNAMESE_VALUE},
    },
    "required": ["confirm_turn_id", "stance", "revised_status", "revised_assignees", "argument"],
}

_STANCE_LABELS = {"accept": "agreed", "amend": "amended the update", "defend": "kept it, rebutted"}


def describe_progress(update: ProgressUpdate, title: str) -> str:
    """Dựng một dòng mô tả cập nhật tiến độ cho prompt và bản ghi kiểm chứng.

    Args:
        update: Cập nhật tiến độ.
        title: Tên việc trong danh sách tồn đọng.

    Returns:
        Chuỗi gồm mã và tên việc, trạng thái, tóm tắt (nếu có) và bên nhận việc mới (nếu giao lại).
    """

    status = update.status
    detail = f" ({update.summary})" if update.summary else ""
    reassign = f"; bên nhận việc mới: {format_actor(update.mentions)}" if update.mentions else ""
    return f"{update.task_id} {title}: {STATUS_LABELS.get(status, status)} [{status}]{detail}{reassign}"


class ProgressVerifier:
    """Kiểm chứng một cập nhật tiến độ UNCERTAIN qua trao đổi giữa Verifier và agent trích xuất việc giao.

    Cài đặt hợp đồng ``ConsensusParty`` cho các yêu cầu kiểm chứng có loại "progress". Verifier có thể
    đề xuất đổi trạng thái hoặc bên nhận việc mới; chỉ agent trích xuất mới áp các đề xuất đó.

    Args:
        llm: Mô hình của Verifier.
        proposer_llm: Mô hình của agent trích xuất việc giao (nơi đã ghi cập nhật tiến độ).
        config: Cấu hình pipeline (số bước tra cứu, số vòng trao đổi, số kết quả tìm kiếm).
    """

    def __init__(self, llm: LLMAdapter, proposer_llm: LLMAdapter, config: AnalysisConfig) -> None:
        self.llm = llm
        self.proposer_llm = proposer_llm
        self.config = config

    # ---- prompt ----

    @staticmethod
    def _title(task: VerifyTask) -> str:
        """Lấy tên việc của cập nhật; dùng mã việc nếu không tìm thấy trong danh sách tồn đọng."""

        agenda_task = task["registry"].agenda.find(task["candidate"].task_id)
        return agenda_task.title if agenda_task else task["candidate"].task_id

    def _evidence_snippets(self, task: VerifyTask, claim: ProgressUpdate) -> str:
        """Trích các lượt bằng chứng agent chỉ ra; lượt dài chỉ lấy đoạn gần nội dung việc nhất.

        Một lượt nói có thể dài vài nghìn ký tự; nếu chỉ đưa mã lượt thì cả hai agent dễ đọc sót câu nêu
        trạng thái nằm giữa lượt, nên đoạn liên quan được đưa thẳng vào prompt.

        Args:
            task: Yêu cầu kiểm chứng.
            claim: Cập nhật tiến độ đang xét.

        Returns:
            Mỗi lượt bằng chứng một dòng; bỏ qua mã lượt không có trong cuộc họp.
        """

        focus = content_syllables(f"{self._title(task)} {claim.summary} {claim.directive}")
        by_id = {turn.turn_id: turn for turn in task["meeting_turns"]}
        return "\n".join(
            format_turn_line(by_id[turn_id], focus_terms=focus)
            for turn_id in claim.evidence_turn_ids if turn_id in by_id
        )

    def _base_prompt(self, task: VerifyTask, claim: ProgressUpdate, rounds: list[ConsensusRound]) -> str:
        """Dựng phần prompt dùng chung cho Verifier và agent trích xuất.

        Gồm: người chủ trì, việc và cập nhật đang xét, lượt agent tự khai, đoạn bằng chứng, các điểm cần
        kiểm (ghi rõ không phải bằng chứng), bản ghi của chủ đề và các vòng trao đổi trước (nếu có).
        """

        reasons = "; ".join(task["reasons"]) or "(no specific reason)"
        request = f"proposing turn {claim.request_turn_id}, " if claim.request_turn_id else ""
        prompt = (
            f"{format_chair_line(task['registry'].chair)}\n"
            f"Old task: {claim.task_id} - {self._title(task)}\n"
            f"Update under review: {describe_progress(claim, self._title(task))}\n"
            f"Extractor agent's own claim: {request}status turn {claim.status_turn_id or '(not given)'}, "
            f"evidence {', '.join(claim.evidence_turn_ids)}\n"
            f"Evidence excerpts:\n{self._evidence_snippets(task, claim)}\n"
            f"Points to check (questions from the automatic filter, NOT evidence): {reasons}\n\n"
            f"Segment transcript:\n{format_turns_as_transcript(task['turns'])}"
        )
        if rounds:
            prompt += f"\n\nPrevious rounds:\n{format_rounds(rounds, 'update', _STANCE_LABELS)}"
        return prompt

    def describe(self, task: VerifyTask, claim: ProgressUpdate) -> str:
        """Trả một dòng mô tả cập nhật cho bản ghi các vòng trao đổi."""

        return describe_progress(claim, self._title(task))

    # ---- một vòng ----

    def _run_react(self, task: VerifyTask, base_prompt: str) -> tuple[dict, list[VerifierStep]]:
        """Chạy một vòng tra cứu từng bước của Verifier.

        Args:
            task: Yêu cầu kiểm chứng.
            base_prompt: Phần cố định của user prompt.

        Returns:
            Cặp (JSON lượt kết luận, hoặc dict rỗng nếu hết lượt mà chưa kết luận; các bước tra cứu).

        Raises:
            LLMUpstreamError: Khi lời gọi mô hình lỗi.
        """

        tools = MeetingTools(
            task["meeting_turns"], task["registry"], search_top_k=self.config.search_top_k, task_text=self._title(task)
        )
        system_prompt = PROGRESS_VERIFIER_SYSTEM_PROMPT.format(
            rubric=VERIFY_RUBRICS["progress"], chair_hint=CHAIR_HINT, tools=TOOL_DESCRIPTIONS,
            json_rule=JSON_ONE_LINE_RULE,
        )
        return run_react(
            self.llm, tools, system_prompt=system_prompt, schema=PROGRESS_VERIFIER_SCHEMA, base_prompt=base_prompt,
            max_calls=self.config.verifier_max_tool_calls + 1, log_name="progress_verifier",
            segment_id=task["segment_id"],
        )

    def review(self, task: VerifyTask, claim: ProgressUpdate, rounds: list[ConsensusRound]) -> Review:
        """Cho Verifier xét cập nhật: một vòng tra cứu rồi áp luật hậu kiểm; không sửa cập nhật.

        Luật hậu kiểm: hết lượt hoặc kết luận lạ thì "unresolved"; bỏ, hoặc không chỉ ra được lượt nêu
        trạng thái có thật, thì "drop". Ngoài ra kết luận là "revise" khi Verifier đề xuất trạng thái khác
        hoặc bên nhận việc khác với hiện tại, ngược lại là "keep" (dù Verifier đã chọn gì).

        Args:
            task: Yêu cầu kiểm chứng.
            claim: Cập nhật đang xét.
            rounds: Các vòng trước.

        Returns:
            Nhận xét của Verifier; đề xuất (chỉ để agent trích xuất đọc) nằm ở ``suggestion`` và
            ``suggestion_reason``.

        Raises:
            LLMUpstreamError: Khi lời gọi mô hình lỗi.
        """

        result, steps = self._run_react(task, self._base_prompt(task, claim, rounds))
        reasoning = read_stripped_text(result.get("reasoning"))
        raw_verdict = result.get("verdict")
        if not result:
            return Review("unresolved", None, "(Verifier hết số bước mà chưa kết luận.)", tuple(steps))
        if raw_verdict not in ("keep", "revise", "drop"):
            return Review("unresolved", None, reasoning or "(Verifier không đủ căn cứ để kết luận.)", tuple(steps))
        turn_id = read_turn_id(task["meeting_turns"], result.get("deciding_turn_id"))
        if raw_verdict == "drop" or turn_id is None:
            if raw_verdict != "drop":
                reasoning = f"(Hạ thành drop: không chỉ ra được lượt nêu trạng thái.) {reasoning}".strip()
            return Review("drop", turn_id, reasoning, tuple(steps))
        status = result.get("revised_status")
        status = status if status in CLAIM_STATUSES and status != claim.status else ""
        assignees = suggested_assignees("progress", result)
        if assignees and format_actor(assignees) == format_actor(claim.mentions):
            assignees = ()
        suggestion = "; ".join([
            *([f"trạng thái {status}"] if status else []),
            *([f"bên nhận việc mới {'; '.join(f'{m.name} ({m.role}, {m.actor_type})' for m in assignees)}"]
              if assignees else []),
        ])
        return Review(
            "revise" if suggestion else "keep", turn_id, reasoning, tuple(steps),
            suggestion=suggestion,
            suggestion_reason=read_stripped_text(result.get("actor_reason")) if assignees else "",
        )

    def respond(self, task: VerifyTask, claim: ProgressUpdate, review: Review,
                rounds: list[ConsensusRound]) -> Response:
        """Cho agent trích xuất trả lời nhận xét và đề xuất của Verifier; agent tự sửa cập nhật nếu cần.

        Lượt nêu trạng thái agent chỉ ra (hợp lệ) luôn được ghi vào cập nhật và thêm vào bằng chứng nếu
        còn thiếu. Khi lập trường là "amend" hoặc "accept", trạng thái mới và bên nhận việc mới cũng được áp.

        Args:
            task: Yêu cầu kiểm chứng.
            claim: Cập nhật Verifier vừa xét.
            review: Nhận xét của Verifier ở vòng này.
            rounds: Các vòng trước.

        Returns:
            Câu trả lời gồm lập trường, lượt nêu trạng thái, lập luận và cập nhật đã sửa; ``edit_reason``
            chỉ có khi bên nhận việc thay đổi.

        Raises:
            LLMUpstreamError: Khi lời gọi mô hình lỗi.
        """

        parts = [self._base_prompt(task, claim, rounds),
                 f"Verifier verdict: {review.verdict}\nFeedback: {review.feedback}"]
        if review.suggestion:
            reason = f"\nReason: {review.suggestion_reason}" if review.suggestion_reason else ""
            parts.append(f"Verifier suggests: {review.suggestion}{reason}")
        if review.steps:
            parts.append(f"Evidence the verifier looked up:\n{format_steps(review.steps)}")
        user_prompt = "\n\n".join(parts)
        with llm_call("progress_verifier_feedback", segment_id=task["segment_id"], prompt_chars=len(user_prompt)):
            response = dict(self.proposer_llm.generate_json(
                system_prompt=PROGRESS_PROPOSER_SYSTEM_PROMPT.format(
                    rubric=VERIFY_RUBRICS["progress"], chair_hint=CHAIR_HINT, json_rule=JSON_ONE_LINE_RULE
                ),
                user_prompt=user_prompt,
                schema=PROGRESS_PROPOSER_SCHEMA,
            ))
        stance, confirm_turn_id, argument = read_stance(response, review.verdict, task["meeting_turns"])
        changes: dict = {}
        if confirm_turn_id:
            changes["status_turn_id"] = confirm_turn_id
            if confirm_turn_id not in claim.evidence_turn_ids:
                changes.update(evidence_with_turn(claim, confirm_turn_id, task["meeting_turns"]))
        if stance in ("amend", "accept"):
            status = response.get("revised_status")
            if status in CLAIM_STATUSES:
                changes["status"] = status
            mentions = read_assignee_mentions(response.get("revised_assignees"))
            if mentions:
                changes["mentions"] = mentions
        revised = replace(claim, **changes) if changes else claim
        changed_actor = revised.mentions != claim.mentions
        return Response(stance, confirm_turn_id, argument, revised,
                        edit_reason=(review.suggestion_reason or argument) if changed_actor else "")

    # ---- kết quả ----

    def settle(self, task: VerifyTask, claim: ProgressUpdate, rounds: list[ConsensusRound], *, verdict: str,
               reasoning: str, deciding_turn_id: str | None, decided_by: str, edit_reason: str = "") -> dict:
        """Đóng gói kết quả cuối của một cập nhật thành phần cập nhật trạng thái của pipeline.

        Cập nhật được giữ khi kết luận khác "drop" (kể cả "unresolved"); lý do kết luận được ghi vào
        cập nhật.

        Args:
            task: Yêu cầu kiểm chứng gốc.
            claim: Bản cập nhật cuối cùng.
            rounds: Toàn bộ các vòng trao đổi.
            verdict: Kết luận cuối.
            reasoning: Lý do của kết luận cuối.
            deciding_turn_id: Lượt nói làm căn cứ, None nếu không có.
            decided_by: "consensus", "verifier" hoặc "fallback".
            edit_reason: Không dùng với cập nhật tiến độ; có để khớp hợp đồng chung.

        Returns:
            Dict có ``verification_records`` (luôn một bản ghi) và ``progress_updates`` nếu giữ.
        """

        kept = verdict != "drop"
        title = self._title(task)
        verification = {"consensus": "consensus", "verifier": "verifier"}.get(decided_by, "fallback")
        claim = replace(claim, verification=verification, reason=reasoning)
        record = VerificationRecord(
            item_key=task["item_key"], segment_id=task["segment_id"], kind="progress",
            candidate_text=describe_progress(task["candidate"], title), reasons=task["reasons"],
            steps=tuple(step for round_ in rounds for step in round_.steps),
            verdict=verdict, reasoning=reasoning,
            final_text=describe_progress(claim, title) if kept else "",
            deciding_turn_id=deciding_turn_id, decided_by=decided_by, rounds=tuple(rounds),
        )
        update: dict = {"verification_records": [record]}
        if kept:
            update["progress_updates"] = [claim]
        return update

    def run(self, task: VerifyTask) -> dict:
        """Kiểm chứng một cập nhật tiến độ qua các vòng trao đổi giữa Verifier và agent trích xuất.

        Args:
            task: Yêu cầu kiểm chứng có loại "progress".

        Returns:
            Dict cập nhật trạng thái: ``verification_records`` (một bản ghi) và ``progress_updates`` nếu
            cập nhật được giữ.
        """

        return run_consensus(self, task, self.config.consensus_max_rounds)


__all__ = [
    "CLAIM_STATUSES",
    "PROGRESS_PROPOSER_SCHEMA",
    "PROGRESS_VERIFIER_SCHEMA",
    "ProgressVerifier",
]
