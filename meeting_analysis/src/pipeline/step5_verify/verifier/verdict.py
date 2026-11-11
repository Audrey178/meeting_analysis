"""Kiểm lại kết luận của agent kiểm chứng bằng luật trước khi dùng: kết luận không hợp lệ thì coi là bỏ,
lượt nói được dẫn làm căn cứ phải có thật. Các bên nhận việc mà agent kiểm chứng đề xuất chỉ được
chuyển cho agent trích xuất làm gợi ý, không tự áp vào mục.
"""

from __future__ import annotations

from ...shared.actors.assignees import (
    declares_unknown_assignees,
    format_actor,
    read_assignee_mentions,
)
from ...shared.llm_output import read_turn_id
from ...shared.schemas import (
    ActionItemCandidate,
    VerdictInput,
    DecisionCandidate,
    JudgeVerdict,
)

KIND_LABELS = {
    "action": "việc giao (action item)",
    "decision": "quyết định (decision)",
    "progress": "cập nhật tiến độ (progress update)",
}


def describe_candidate(candidate: ActionItemCandidate | DecisionCandidate, kind: str) -> str:
    """Dựng chuỗi mô tả một candidate để đưa vào prompt Verifier và bản ghi kiểm chứng.

    Args:
        candidate: Việc giao hoặc kết luận.
        kind: "action" cho việc giao, "decision" cho kết luận.

    Returns:
        Với việc giao: "bên nhận: nội dung (hạn: ...)"; với kết luận: chỉ nội dung.
    """

    if kind == "action":
        actor = candidate.actor or "(chưa rõ người phụ trách)"
        deadline = f" (hạn: {candidate.deadline_raw})" if candidate.deadline_raw else ""
        return f"{actor}: {candidate.text}{deadline}"
    return candidate.text


def suggested_assignees(kind: str, judge_result: dict):
    """Đọc các bên nhận việc Verifier đề xuất; đây chỉ là gợi ý cho agent trích xuất, không áp vào mục.

    Args:
        kind: Loại mục: "action", "decision" hoặc "progress". Với "decision" luôn trả rỗng.
        judge_result: JSON ở lượt cuối của Verifier.

    Returns:
        Tuple các bên nhận việc được đề xuất; rỗng nếu là kết luận, Verifier không đề xuất, hoặc Verifier
        khai không xác định được ("unknown").
    """

    if kind != "action" or declares_unknown_assignees(judge_result.get("revised_assignees")):
        return ()
    return read_assignee_mentions(judge_result.get("revised_assignees"))


def resolve_verdict(verdict_input: VerdictInput, judge_result: dict) -> tuple[JudgeVerdict, str | None]:
    """Áp luật hậu kiểm lên kết luận của Verifier cho một việc giao hoặc kết luận.

    Các luật: kết luận lạ thành "drop"; kết luận không có "revise" nên "revise" thành "keep"; giữ hay sửa
    mà không chỉ ra được lượt nói có thật làm căn cứ thì thành "drop". Với việc giao còn giữ, kết luận là
    "revise" khi và chỉ khi Verifier đề xuất bên nhận việc khác bên hiện tại, ngược lại là "keep".

    Args:
        verdict_input: Loại mục, mục đang xét và các lượt nói dùng để kiểm lượt căn cứ.
        judge_result: JSON ở lượt cuối của Verifier.

    Returns:
        Cặp (kết luận cuối, mã lượt căn cứ hợp lệ hoặc None).
    """

    kind = verdict_input["kind"]
    candidate = verdict_input["candidate"]
    verdict = judge_result.get("verdict")
    if verdict not in ("keep", "revise", "drop"):
        verdict = "drop"
    if verdict == "revise" and kind == "decision":
        verdict = "keep"
    deciding_turn_id = read_turn_id(verdict_input["turns"], judge_result.get("deciding_turn_id"))
    if verdict != "drop" and deciding_turn_id is None:
        verdict = "drop"
    if kind == "action" and verdict != "drop":
        suggested = suggested_assignees(kind, judge_result)
        changes_actor = bool(suggested) and format_actor(suggested) != candidate.actor
        verdict = "revise" if changes_actor else "keep"
    return verdict, deciding_turn_id


__all__ = [
    "KIND_LABELS",
    "describe_candidate",
    "resolve_verdict",
    "suggested_assignees",
]
