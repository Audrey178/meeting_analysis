"""Vòng tra cứu từng bước của agent kiểm chứng, dùng chung cho mọi loại mục: mỗi bước agent chọn một
công cụ tra bản ghi, đọc kết quả, rồi quyết định tra tiếp hay đưa ra kết luận. Có giới hạn số bước.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ....utils.llm_call_log import llm_call
from ....utils.ports import LLMAdapter
from ...shared.llm_output import read_stripped_text
from ...shared.schemas import ConsensusRound, VerifierStep
from .tools import MeetingTools

_FINAL_TURN_NOTE = "THIS IS THE LAST STEP: action must be \"final\" and verdict must be filled."


def format_steps(steps: Sequence[VerifierStep]) -> str:
    """Trình bày các bước tra cứu đã làm thành văn bản: suy nghĩ, hành động, kết quả.

    Giữ cả phần suy nghĩ để lượt sau của mô hình thấy vì sao bước trước đã tra như vậy.

    Args:
        steps: Các bước tra cứu theo thứ tự.

    Returns:
        Văn bản các bước, đánh số từ 1; rỗng nếu chưa có bước nào.
    """

    return "\n\n".join(
        f"Step {i}\nThought: {step.thought or '(none)'}\n"
        f"Action: {step.action}({step.argument})\nResult:\n{step.observation}"
        for i, step in enumerate(steps, 1)
    )


def format_rounds(rounds: Sequence[ConsensusRound], item_label: str, stance_labels: Mapping[str, str]) -> str:
    """Trình bày các vòng trao đổi trước để mỗi bên xét lại lập luận của bên kia.

    Args:
        rounds: Các vòng đã xong.
        item_label: Tên gọi mục trong prompt, ví dụ "candidate" hoặc "cập nhật".
        stance_labels: Bảng đổi mã lập trường của agent trích xuất sang nhãn hiển thị.

    Returns:
        Văn bản các vòng, đánh số từ 1; rỗng nếu chưa có vòng nào.
    """

    return "\n".join(
        f"Round {index} - {item_label}: {round_.candidate_text}\n"
        f"  Verifier: {round_.verdict}"
        f"{f' (turn {round_.deciding_turn_id})' if round_.deciding_turn_id else ''}: {round_.feedback}\n"
        f"  Extractor agent ({stance_labels.get(round_.stance, 'unknown stance')}"
        f"{f', turn {round_.confirm_turn_id}' if round_.confirm_turn_id else ''}): {round_.response}"
        for index, round_ in enumerate(rounds, 1)
    )


def _build_step_prompt(base_prompt: str, steps: list[VerifierStep], is_last: bool) -> str:
    """Ghép prompt cho một lượt tra cứu: phần cố định, lịch sử tra cứu, yêu cầu kết luận nếu là lượt cuối."""

    parts = [base_prompt]
    if steps:
        parts.append(f"Lookup history:\n{format_steps(steps)}")
    if is_last:
        parts.append(_FINAL_TURN_NOTE)
    return "\n\n".join(parts)


def _repeat_notice(steps: list[VerifierStep], action: str, argument: str) -> str | None:
    """Phát hiện Verifier lặp lại đúng một lần tra đã làm trong vòng này, để khỏi tốn bước vô ích.

    Tham số được so sau khi bỏ khác biệt hoa/thường và khoảng trắng.

    Args:
        steps: Các bước đã làm trong vòng.
        action: Tên công cụ của lần tra mới.
        argument: Tham số của lần tra mới.

    Returns:
        Thông báo lỗi dùng làm kết quả tra cứu nếu bị lặp; None nếu là lần tra mới.
    """

    key = " ".join(argument.casefold().split())
    for index, step in enumerate(steps, 1):
        if step.action == action and " ".join(step.argument.casefold().split()) == key:
            return (
                f"ERROR: already looked up {action}({argument}) in Step {index}, result as above. "
                "Read the segment transcript carefully, look up something else, or conclude."
            )
    return None


def run_react(
    llm: LLMAdapter,
    tools: MeetingTools,
    *,
    system_prompt: str,
    schema: Mapping[str, object],
    base_prompt: str,
    max_calls: int,
    log_name: str,
    segment_id: str,
) -> tuple[dict, list[VerifierStep]]:
    """Chạy một vòng tra cứu từng bước (ReAct) của Verifier cho tới khi có kết luận hoặc hết lượt.

    Mỗi lượt mô hình chọn một công cụ để tra hoặc chọn "final" để kết luận. Ở lượt cuối, prompt yêu cầu
    bắt buộc kết luận; nếu mô hình vẫn không kết luận thì trả JSON rỗng.

    Args:
        llm: Mô hình của Verifier.
        tools: Bộ công cụ chỉ đọc trên bản ghi cuộc họp.
        system_prompt: System prompt đã điền đủ.
        schema: JSON schema cho mỗi lượt trả lời.
        base_prompt: Phần cố định của user prompt (mục đang xét, bản ghi, các vòng trước).
        max_calls: Số lời gọi mô hình tối đa, tính cả lượt kết luận.
        log_name: Tên ghi log lời gọi mô hình.
        segment_id: Mã chủ đề, dùng để ghi log.

    Returns:
        Cặp (JSON của lượt kết luận, hoặc dict rỗng nếu hết lượt mà chưa kết luận; các bước tra cứu).

    Raises:
        LLMUpstreamError: Khi lời gọi mô hình lỗi.
    """

    steps: list[VerifierStep] = []
    for call_index in range(max_calls):
        user_prompt = _build_step_prompt(base_prompt, steps, call_index == max_calls - 1)
        with llm_call(log_name, segment_id=segment_id, prompt_chars=len(user_prompt)):
            result = dict(llm.generate_json(system_prompt=system_prompt, user_prompt=user_prompt, schema=schema))
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


__all__ = [
    "format_rounds",
    "format_steps",
    "run_react",
]
