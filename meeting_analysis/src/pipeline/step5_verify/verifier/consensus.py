"""Vòng trao đổi giữa agent kiểm chứng và agent trích xuất cho MỘT mục bị nghi ngờ, dùng chung cho mọi
loại mục.

Mỗi vòng, agent kiểm chứng nhận xét: giữ, sửa hay bỏ. Nếu giữ thì xong. Nếu không, agent trích xuất
trả lời bằng một trong ba cách: đồng ý, sửa lại mục, hoặc bảo vệ mục của mình kèm lượt nói làm bằng
chứng. Hai bên cùng đồng ý thì dừng.

Hết số vòng mà chưa thống nhất thì: agent kiểm chứng vẫn muốn bỏ thì bỏ, còn lại giữ bản cuối của
agent trích xuất. Nếu việc gọi mô hình bị lỗi giữa chừng thì giữ nguyên mục gốc.
"""

from __future__ import annotations

import logging
from typing import Protocol

from ....utils.ports import LLMUpstreamError
from ...shared.llm_output import read_stripped_text, read_turn_id
from ...shared.schemas import Claim, ConsensusRound, Response, Review, VerifyTask

logger = logging.getLogger(__name__)

# Lập trường agent trích xuất được chọn khi trả lời Verifier.
STANCES = ("accept", "amend", "defend")


class ConsensusParty(Protocol):
    """Hợp đồng cho phần riêng theo loại mục (việc giao/kết luận hoặc tiến độ) của vòng đồng thuận.

    Vòng đồng thuận chỉ điều phối thứ tự gọi; mọi việc gọi mô hình, dựng prompt và đóng gói kết quả do
    bên cài đặt hợp đồng này đảm nhận. ``review`` và ``respond`` báo lỗi mô hình bằng
    ``LLMUpstreamError``; lỗi không ``fatal`` được vòng đồng thuận xử lý bằng cách giữ nguyên mục gốc.
    """

    def describe(self, task: VerifyTask, claim: Claim) -> str:
        """Trả một dòng mô tả mục, dùng trong bản ghi các vòng trao đổi."""

    def review(self, task: VerifyTask, claim: Claim, rounds: list[ConsensusRound]) -> Review:
        """Cho Verifier xét mục ở vòng hiện tại và trả nhận xét đã qua luật hậu kiểm.

        Args:
            task: Yêu cầu kiểm chứng gốc.
            claim: Bản mục đang xét (có thể đã được agent trích xuất sửa ở vòng trước).
            rounds: Các vòng đã xong, để Verifier xét lại lập luận của agent trích xuất.

        Returns:
            Nhận xét của Verifier; không được sửa mục.

        Raises:
            LLMUpstreamError: Khi lời gọi mô hình lỗi.
        """

    def respond(self, task: VerifyTask, claim: Claim, review: Review, rounds: list[ConsensusRound]) -> Response:
        """Cho agent trích xuất trả lời nhận xét của Verifier.

        Args:
            task: Yêu cầu kiểm chứng gốc.
            claim: Bản mục Verifier vừa xét.
            review: Nhận xét của Verifier ở vòng này.
            rounds: Các vòng đã xong.

        Returns:
            Câu trả lời gồm lập trường, lập luận và bản mục sau khi agent tự sửa (nếu có sửa).

        Raises:
            LLMUpstreamError: Khi lời gọi mô hình lỗi.
        """

    def settle(self, task: VerifyTask, claim: Claim, rounds: list[ConsensusRound], *, verdict: str,
               reasoning: str, deciding_turn_id: str | None, decided_by: str, edit_reason: str = "") -> dict:
        """Đóng gói kết quả cuối của một mục thành phần cập nhật trạng thái của pipeline.

        Args:
            task: Yêu cầu kiểm chứng gốc.
            claim: Bản mục cuối cùng.
            rounds: Toàn bộ các vòng trao đổi.
            verdict: Kết luận cuối: "keep", "revise", "drop" hoặc "unresolved"; mọi kết luận khác "drop"
                đều giữ mục.
            reasoning: Lý do của kết luận cuối.
            deciding_turn_id: Lượt nói làm căn cứ, None nếu không có.
            decided_by: Ai quyết: "consensus" (hai bên thống nhất), "verifier" (hết vòng, theo Verifier)
                hoặc "fallback" (lỗi mô hình hoặc chưa kết luận được).
            edit_reason: Lý do agent trích xuất đổi bên nhận việc, rỗng nếu không đổi.

        Returns:
            Dict luôn có bản ghi kiểm chứng; có thêm mục cuối nếu mục được giữ.
        """


def evidence_with_turn(candidate, turn_id: str, meeting_turns) -> dict:
    """Bổ sung một lượt chốt mới (chưa nằm trong bằng chứng) vào các trường bằng chứng của mục.

    Dùng khi agent trích xuất chỉ ra một lượt chốt ở chỗ khác, kể cả ở chủ đề khác. Các lượt bằng chứng
    được sắp lại theo thứ tự trong cuộc họp; mã item trích dẫn chỉ thêm các item của lượt mới.

    Args:
        candidate: Mục đang xét (việc giao, kết luận hoặc cập nhật tiến độ).
        turn_id: Mã lượt chốt mới, đã kiểm là lượt có thật trong cuộc họp.
        meeting_turns: Toàn bộ lượt nói của cuộc họp.

    Returns:
        Dict gồm ``evidence_turn_ids``, ``quotes`` và ``item_ids`` mới, để thay vào mục.
    """

    kept = set(candidate.evidence_turn_ids) | {turn_id}
    ordered = [turn for turn in meeting_turns if turn.turn_id in kept]
    cited = set(candidate.item_ids) | {item_id for turn in ordered if turn.turn_id == turn_id for item_id, _ in turn.source_items}
    return {
        "evidence_turn_ids": tuple(turn.turn_id for turn in ordered),
        "quotes": tuple(turn.text_exact for turn in ordered),
        "item_ids": tuple(item_id for turn in ordered for item_id, _ in turn.source_items if item_id in cited),
    }


def read_stance(response: dict, verdict: str, meeting_turns) -> tuple[str, str | None, str]:
    """Đọc lập trường của agent trích xuất từ câu trả lời của mô hình, sửa trường hợp tự mâu thuẫn.

    Agent chọn "accept" (đồng ý bỏ mục) nhưng lại chỉ ra được một lượt chốt thì thực chất là đang bảo vệ
    mục, nên lập trường được đổi thành "defend". Không đổi khi Verifier đề nghị sửa, vì khi đó "accept"
    nghĩa là đồng ý sửa.

    Args:
        response: JSON agent trích xuất trả về.
        verdict: Kết luận của Verifier ở vòng này.
        meeting_turns: Toàn bộ lượt nói của cuộc họp, để kiểm lượt chốt có thật.

    Returns:
        Bộ ba (lập trường hợp lệ hoặc chuỗi rỗng, mã lượt chốt hợp lệ hoặc None, lập luận).
    """

    stance = response.get("stance")
    stance = stance if stance in STANCES else ""
    confirm_turn_id = read_turn_id(meeting_turns, response.get("confirm_turn_id"))
    argument = read_stripped_text(response.get("argument"))
    if stance == "accept" and verdict != "revise" and confirm_turn_id:
        stance = "defend"
        argument = f"(Đổi accept thành defend vì agent chỉ ra lượt {confirm_turn_id}.) {argument}".strip()
    return stance, confirm_turn_id, argument


def run_consensus(party: ConsensusParty, task: VerifyTask, max_rounds: int) -> dict:
    """Chạy các vòng trao đổi giữa Verifier và agent trích xuất cho một mục tới khi thống nhất.

    Mỗi vòng: Verifier "keep" thì giữ ngay; nếu không, agent trích xuất trả lời. Agent "accept" một đề
    nghị bỏ thì mục bị bỏ; "accept" một đề nghị sửa thì giữ bản đã sửa; "amend"/"defend" thì sang vòng
    sau với bản mới. Hết vòng mà chưa thống nhất: Verifier vẫn muốn bỏ thì bỏ, còn lại giữ bản cuối của
    agent trích xuất. Lỗi mô hình không nghiêm trọng thì giữ nguyên mục gốc với kết luận "unresolved".

    Args:
        party: Phần riêng theo loại mục (xem ``ConsensusParty``).
        task: Yêu cầu kiểm chứng của một mục nghi ngờ.
        max_rounds: Số vòng tối đa; phải ít nhất 1.

    Returns:
        Dict cập nhật trạng thái do ``party.settle`` trả về.

    Raises:
        LLMUpstreamError: Khi lỗi mô hình được đánh dấu ``fatal``.
    """

    original = task["candidate"]
    claim = original
    rounds: list[ConsensusRound] = []
    last: Review | None = None
    edit_reason = ""

    def fallback(note: str, exc: LLMUpstreamError) -> dict:
        if exc.fatal:
            raise exc
        logger.warning("consensus: %s ở %s: %s", note, task["item_key"], exc)
        return party.settle(task, original, rounds, verdict="unresolved", reasoning=f"({note}: {exc})",
                            deciding_turn_id=None, decided_by="fallback")

    for _ in range(max_rounds):
        try:
            review = party.review(task, claim, rounds)
        except LLMUpstreamError as exc:
            return fallback("Verifier lỗi LLM", exc)
        last = review
        claim_text = party.describe(task, claim)
        if review.verdict == "keep":
            rounds.append(ConsensusRound(claim_text, review.steps, "keep", review.feedback, review.deciding_turn_id))
            return party.settle(task, claim, rounds, verdict="keep", reasoning=review.feedback,
                                deciding_turn_id=review.deciding_turn_id, decided_by="consensus",
                                edit_reason=edit_reason)
        try:
            response = party.respond(task, claim, review, rounds)
        except LLMUpstreamError as exc:
            return fallback("Agent trích xuất lỗi LLM khi trả lời feedback", exc)
        rounds.append(ConsensusRound(
            claim_text, review.steps, review.verdict, review.feedback, review.deciding_turn_id,
            stance=response.stance, response=response.argument, confirm_turn_id=response.confirm_turn_id,
        ))
        if response.stance == "accept" and review.verdict != "revise":
            return party.settle(task, claim, rounds, verdict="drop", reasoning=review.feedback,
                                deciding_turn_id=review.deciding_turn_id, decided_by="consensus")
        claim = response.claim
        edit_reason = response.edit_reason or edit_reason
        if response.stance == "accept":
            return party.settle(task, claim, rounds, verdict="revise", reasoning=review.feedback,
                                deciding_turn_id=review.deciding_turn_id, decided_by="consensus",
                                edit_reason=edit_reason)

    note = f"(Chưa đồng thuận sau {len(rounds)} vòng"
    if last.verdict == "drop":
        return party.settle(task, claim, rounds, verdict="drop", reasoning=f"{note}, Verifier bỏ.) {last.feedback}",
                            deciding_turn_id=last.deciding_turn_id, decided_by="verifier")
    return party.settle(task, claim, rounds, verdict=last.verdict,
                        reasoning=f"{note}, giữ bản cuối của agent trích xuất.) {last.feedback}",
                        deciding_turn_id=last.deciding_turn_id,
                        decided_by="fallback" if last.verdict == "unresolved" else "verifier",
                        edit_reason=edit_reason)


__all__ = [
    "STANCES",
    "ConsensusParty",
    "evidence_with_turn",
    "read_stance",
    "run_consensus",
]
