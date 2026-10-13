"""Phần còn lại của node Debate + Judge (v1) mà Verifier v3 (``nodes/verifier.py``) dùng lại.

Gồm nhãn loại (``_KIND_LABELS``), cách hiển thị một candidate (``_candidate_text``) và luật
hậu kiểm verdict (``_resolve_verdict``). Verdict có ba mức: ``keep``, ``revise`` (việc giao có thật nhưng
sai/thiếu người phụ trách -- sửa ``actor`` theo bản ghi) và ``drop``; giữ mà không chỉ ra được
lượt giao/chốt (``deciding_turn_id``) thuộc đoạn thì bị hạ thành ``drop`` bằng luật. Rubric giữ/bỏ
nạp vào prompt Verifier nằm ở ``agentic_v3/nodes/prompts.py`` (``VERIFY_RUBRICS``).
"""

from __future__ import annotations

from dataclasses import replace

from .._shared import is_non_identifying_actor, read_confirm_turn_id, read_stripped_text
from ..schemas import ActionItemCandidate, DebateTask, DecisionCandidate, JudgeVerdict

_KIND_LABELS = {"action": "việc giao (action item)", "decision": "quyết định (decision)"}


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
