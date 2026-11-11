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
from ...shared.prompts import CHAIR_HINT, JSON_ONE_LINE_RULE, VERIFY_RUBRICS, format_chair_line
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
Bạn là KIỂM CHỨNG VIÊN cho một CẬP NHẬT TIẾN ĐỘ của một việc cũ (việc trong danh sách cần báo
cáo), trích từ MỘT đoạn chủ đề của cuộc họp, bị bộ lọc tự động đánh dấu CHƯA CHẮC CHẮN.

Tiêu chí:
{rubric}
{chair_hint}

Bạn có các tool CHỈ ĐỌC để tra bằng chứng trong CẢ cuộc họp:
{tools}

Mỗi lượt trả về đúng MỘT JSON, các trường theo thứ tự:
- thought: 1-2 câu: đã biết gì, còn thiếu gì, vì sao tra tiếp hoặc vì sao đã đủ căn cứ.
- Muốn tra thêm: action là tên tool, argument là tham số; các trường kết luận để null. argument của
  search_meeting là MỘT cụm 3-8 từ về nội dung việc (vd. giải trình ý kiến Bộ Xây dựng): không liệt
  kê từ đồng nghĩa, tên trạng thái hay lặp lại từ.
- Đủ căn cứ: action = "final", argument = null, rồi điền:
  reasoning (1-2 câu, viết TRƯỚC kết luận): lượt nào nói gì về chính việc này, và vì vậy trạng thái
  đúng của việc là gì,
  deciding_turn_id (BẮT BUỘC khi keep/revise: turn_id của lượt nói NÊU TÌNH TRẠNG hoặc CHỈ ĐẠO về
  chính việc này, hoặc lượt người chủ trì CHẤP NHẬN đề xuất của thành viên; có thể ở chủ đề khác),
  verdict theo ĐÚNG reasoning: "keep" (trạng thái trong reasoning trùng trạng thái cập nhật đang xét)
  | "revise" (việc được nêu tình trạng nhưng là trạng thái khác, điền revised_status; hoặc bên nhận
  việc mới sai, điền revised_assignees) | "drop" (không lượt nào nêu tình trạng của chính việc này,
  hoặc đề xuất không được chấp nhận) | "unresolved" (chỉ khi bằng chứng thật sự mâu thuẫn),
  revised_status (chỉ khi đổi trạng thái, không thì null).

Khi cập nhật có GIAO LẠI việc cho bên khác (dòng "bên nhận việc mới"), bên nhận việc có thể là NGƯỜI
hoặc ĐƠN VỊ. Khi bên nhận việc chỉ là tên gọi, có thể trùng người khác, hoặc bị nghi ngờ: gọi
lookup_speaker("<cách gọi> @<turn_id lượt giao>") rồi ĐỀ XUẤT:
  revised_assignees: MỖI bên nhận việc một phần tử {{name, role, type}}; name là ĐÚNG tên một
  ứng viên tool trả về (không tự viết tên khác); role "lead" (chủ trì) | "support" (phối hợp) |
  "joint" (cùng thực hiện, không ai chủ trì); type "person" | "organization".
  actor_reason: vì sao chọn ứng viên đó (ai nói gì ở lượt nào).
Không có ứng viên nào rõ ràng thì để mỗi bên type = "unknown". Không cần sửa bên nhận việc, hoặc việc
không được giao lại, thì revised_assignees = [] và actor_reason = null.

revised_status và revised_assignees chỉ là ĐỀ XUẤT: bạn không tự sửa cập nhật, agent trích xuất sẽ
sửa theo.

"Điểm cần kiểm" là câu hỏi bộ lọc tự động gửi sang (bộ lọc hay sai): trả lời nó bằng bản ghi, nó
KHÔNG phải bằng chứng cho hay chống cập nhật. Lượt nêu trạng thái thật có thể khác lượt agent khai. "Đoạn bằng chứng" là
phần trong các lượt agent chỉ ra có nội dung gần với việc nhất (lượt dài bị cắt quanh đó): đọc nó
trước khi kết luận lượt đó có nói về việc hay không.

reasoning là FEEDBACK gửi lại agent trích xuất khi bạn không giữ: nêu cụ thể điểm sai và lượt
nói làm căn cứ. Chỉ dựa vào bằng chứng có thật trong bản ghi. Tra ít nhất có thể.

KHÔNG dùng dấu nháy kép (") trong thought, reasoning, actor_reason: dẫn lượt nói bằng turn_id. {json_rule}
""".strip()

PROGRESS_VERIFIER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "action": {"type": "string", "enum": [*TOOL_NAMES, "final"]},
        "argument": {"type": ["string", "null"]},
        "reasoning": {"type": ["string", "null"]},
        "deciding_turn_id": {"type": ["string", "null"]},
        "verdict": {"type": ["string", "null"], "enum": ["keep", "revise", "drop", "unresolved", None]},
        "revised_status": {"type": ["string", "null"], "enum": [*CLAIM_STATUSES, None]},
        "revised_assignees": VERIFIER_SCHEMA["properties"]["revised_assignees"],
        "actor_reason": {"type": ["string", "null"]},
    },
    "required": [
        "thought", "action", "argument", "reasoning", "deciding_turn_id", "verdict", "revised_status",
        "revised_assignees", "actor_reason",
    ],
}

PROGRESS_PROPOSER_SYSTEM_PROMPT = """
Bạn là AGENT TRÍCH XUẤT đã ghi CẬP NHẬT TIẾN ĐỘ dưới đây cho một việc cũ. KIỂM CHỨNG VIÊN vừa
phản hồi: kết luận và lý do (feedback). Đối chiếu feedback với bản ghi rồi chọn đúng MỘT lập trường:
- "accept": đồng ý với kiểm chứng viên. Họ đề xuất trạng thái hay bên nhận việc khác thì CHÍNH BẠN
  ghi đề xuất đó vào revised_status/revised_assignees (kiểm chứng viên không sửa hộ); họ cho rằng
  không lượt nào nêu tình trạng của việc thì cập nhật bị bỏ.
- "amend": sửa cập nhật cho đúng bản ghi: revised_status (trạng thái khác) và/hoặc revised_assignees
  (bên nhận việc mới khi việc được giao lại: mỗi bên một phần tử {{name, role, type}} với role
  "lead" | "support" | "joint", type "person" | "organization"; name đúng nguyên văn bản ghi), kèm
  confirm_turn_id là lượt nói nêu trạng thái/giao lại đó. Không sửa bên nhận việc thì
  revised_assignees = [].
- "defend": giữ nguyên cập nhật, chỉ ra confirm_turn_id mà kiểm chứng viên bỏ sót.

Điền confirm_turn_id TRƯỚC khi chọn lập trường: lượt nói nêu tình trạng/chỉ đạo về chính việc
này (hoặc lượt người chủ trì chấp nhận đề xuất), null nếu không có. Đã chỉ ra được lượt đó thì lập
trường là "amend" hoặc "defend".

Tiêu chí:
{rubric}
{chair_hint}

TUYỆT ĐỐI KHÔNG bịa nội dung không có trong bản ghi. Không tìm được lượt nêu trạng thái thì chọn
"accept". Trường không dùng để null. argument: TỐI ĐA 2 câu ngắn, dẫn chứng bằng turn_id, KHÔNG
dùng dấu nháy kép ("). {json_rule}
""".strip()

# ``argument`` (văn bản tự do) đứng CUỐI, như ``verifier.PROPOSER_SCHEMA``.
PROGRESS_PROPOSER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "confirm_turn_id": {"type": ["string", "null"]},
        "stance": {"type": "string", "enum": ["accept", "amend", "defend"]},
        "revised_status": {"type": ["string", "null"], "enum": [*CLAIM_STATUSES, None]},
        "revised_assignees": PROPOSER_SCHEMA["properties"]["revised_assignees"],
        "argument": {"type": "string"},
    },
    "required": ["confirm_turn_id", "stance", "revised_status", "revised_assignees", "argument"],
}

_STANCE_LABELS = {"accept": "đồng ý", "amend": "đã sửa cập nhật", "defend": "giữ nguyên, phản biện"}


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

        reasons = "; ".join(task["reasons"]) or "(không có lý do cụ thể)"
        request = f"lượt đề xuất {claim.request_turn_id}, " if claim.request_turn_id else ""
        prompt = (
            f"{format_chair_line(task['registry'].chair)}\n"
            f"Việc cũ: {claim.task_id} - {self._title(task)}\n"
            f"Cập nhật đang xét: {describe_progress(claim, self._title(task))}\n"
            f"Agent trích xuất tự khai: {request}lượt nêu trạng thái {claim.status_turn_id or '(không nêu)'}, "
            f"bằng chứng {', '.join(claim.evidence_turn_ids)}\n"
            f"Đoạn bằng chứng:\n{self._evidence_snippets(task, claim)}\n"
            f"Điểm cần kiểm (câu hỏi của bộ lọc tự động, KHÔNG phải bằng chứng): {reasons}\n\n"
            f"Bản ghi của đoạn:\n{format_turns_as_transcript(task['turns'])}"
        )
        if rounds:
            prompt += f"\n\nCác vòng trao đổi trước:\n{format_rounds(rounds, 'cập nhật', _STANCE_LABELS)}"
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
                 f"Kiểm chứng viên kết luận: {review.verdict}\nFeedback: {review.feedback}"]
        if review.suggestion:
            reason = f"\nLý do: {review.suggestion_reason}" if review.suggestion_reason else ""
            parts.append(f"Kiểm chứng viên đề xuất: {review.suggestion}{reason}")
        if review.steps:
            parts.append(f"Bằng chứng kiểm chứng viên đã tra:\n{format_steps(review.steps)}")
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
