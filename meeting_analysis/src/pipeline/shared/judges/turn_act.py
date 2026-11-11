"""Phân loại theo nghĩa các lượt nói quan trọng:

  - Lượt được coi là "lượt chốt" có thật sự là giao việc, nhận việc hay chốt kết luận không.
  - Nội dung lượt chốt có đúng là việc/kết luận mà agent đã ghi không.
  - Một lượt phản hồi đồng ý, sửa đổi hay bác bỏ một đề xuất nêu trước đó.
  - Hai kết luận (hoặc hai việc giao) có nói về cùng một vấn đề không, và cái sau thay thế hay bổ
    sung cái trước.

Lượt nói quá dài được chia nhỏ để xét từng phần; kết quả được nhớ lại để không hỏi lặp.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from ....utils.contracts import SpeakerTurn

COMMIT_CLEAR_MIN = 0.8
CLAIM_SUPPORT_CLEAR_MIN = 0.8
CLAIM_SUPPORT_REFERENCE_MIN = 0.6

COMMIT_LABELS = ("assignment", "conclusion")
DEFAULT_MODEL = "typesafe/jev-1.13"
CONTEXT_TURNS = 2
MAX_TURN_CHARS = 2500

TURN_ACT_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "turn_act",
    "instructions": (
        "The input is an excerpt of a Vietnamese meeting: a few context turns, then the TURN TO JUDGE. "
        "Classify only the TURN TO JUDGE, using the context to understand it. Judge by meaning, not keywords: "
        "colloquial phrasing like 'nhá', 'cứ làm đi', 'coi như xong', 'giúp anh' can still be an assignment/settlement; "
        "'đề nghị' naming who must act and what must be done is usually an assignment, 'đề nghị' asking others "
        "to review or consider is usually a recommendation. Do not infer from the speaker's role."
    ),
    "choices": [
        {"value": "assignment", "description": "Assigns a task to a specific person/unit, or someone takes on/commits to a task."},
        {"value": "conclusion", "description": "Settles, concludes or agrees on a decision."},
        {"value": "proposal", "description": "Only an opinion, proposal, recommendation or acknowledgement; nobody has settled or taken it on yet."},
        {"value": "rejection", "description": "Dismisses, reverses or cancels an earlier proposal/decision/task."},
        {"value": "discussion", "description": "Presentation, report, Q&A; no assignment, no settlement."},
        {"value": "other", "description": "None of the above."},
    ],
}

CLAIM_SUPPORT_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "claim_support",
    "instructions": (
        "The input has the CLAIM TO CHECK, the RELATED EVIDENCE TURNS and the "
        "CONFIRMING TURN. Only ask whether the CONFIRMING TURN really assigns/takes on or accepts "
        "exactly the content of that claim. The earlier evidence only helps resolve references such as "
        "'như anh X nói', 'tiếp thu các ý kiến'; it does not by itself turn a proposal into "
        "an assigned task. Do not infer from the speaker's role or from the turn being a directive "
        "in general. Content with a different output, scope or object does not match."
    ),
    "choices": [
        {
            "value": "direct",
            "description": "The confirming turn directly states/assigns/takes on exactly the claimed content.",
        },
        {
            "value": "accepted_reference",
            "description": (
                "The confirming turn clearly refers to and accepts the specific opinion, or the whole group of "
                "opinions, that contains exactly this claim, without excluding it."
            ),
        },
        {
            "value": "unsupported",
            "description": "The confirming turn states/assigns/accepts something else, or does not accept this claim.",
        },
        {
            "value": "ambiguous",
            "description": "Not enough grounds to tell whether the confirming turn covers exactly this claim.",
        },
    ],
}

PROPOSAL_RESPONSE_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "proposal_response",
    "instructions": (
        "The input is an excerpt of a Vietnamese meeting: the RAISING TURN, the CONTENT TO JUDGE (one point of "
        "that turn), then the RESPONSE TURN spoken later. Only ask: how does the RESPONSE TURN treat that CONTENT. "
        "Judge by meaning, not keywords. Thanks, inviting others to speak, or changing the subject is not "
        "acceptance. Do not infer from the speaker's role."
    ),
    "choices": [
        {"value": "direct_acceptance", "description": "Repeats, agrees with or cites exactly this content (e.g. 'như anh X nói ...' about that very point)."},
        {"value": "general_acceptance", "description": "Generally accepts the earlier opinions (lưu ý, tiếp thu các ý kiến) without dismissing or excluding this content."},
        {"value": "modification", "description": "Accepts it but changes the content, scope or method."},
        {"value": "rejection", "description": "Dismisses, objects, withdraws, says it is not needed or not to be done yet."},
        {"value": "no_response", "description": "Says nothing about this content: only thanks, invites other opinions, or talks about something else."},
    ],
}
# Ngưỡng của ``PROPOSAL_RESPONSE_QUESTION`` (từ prototype, chưa đo lại trên dữ liệu khác Cái Mép) và trần
# ký tự mỗi đoạn của lượt phản hồi: lời tổng kết tiếp nhận từng ý ở một câu riêng, câu đó chìm khi hỏi cả lượt.
RESPONSE_ACCEPT_MIN = 0.6
RESPONSE_REJECT_MIN = 0.5
RESPONSE_MODIFY_MIN = 0.5
RESPONSE_WINDOW_CHARS = 700


DECISION_RELATION_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "decision_relation",
    "instructions": (
        "The input is two CONCLUSIONS of the same Vietnamese meeting; the LATER CONCLUSION was settled later. Ask: are "
        "the two conclusions the SAME decision (same specific object and same thing decided), and if so, does the later "
        "conclusion change the earlier one. All conclusions of a meeting are about the same proposal/document: that does "
        "NOT make them the same decision. Two different requirements about the same proposal (e.g. clarify responsibility / "
        "assess impact / deadline / submission authority) are different matters. Judge by meaning, not keywords."
    ),
    "choices": [
        {
            "value": "changed",
            "description": (
                "Same matter, and the later conclusion reverses, cancels, replaces or modifies the content, scope, "
                "method or deadline of the earlier conclusion."
            ),
        },
        {
            "value": "unchanged",
            "description": "Same matter; the later conclusion repeats, confirms or only adds details that do not contradict the earlier one.",
        },
        {"value": "different_matter", "description": "Two different decisions, even when both are about the same proposal or document."},
    ],
}

ASSIGNMENT_RELATION_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "assignment_relation",
    "instructions": (
        "The input is two ASSIGNED TASKS for the same assignee in a Vietnamese meeting; the LATER TASK was assigned "
        "later. Ask: are the two the SAME task (same product/result to deliver), and if so, does the later assignment "
        "change the earlier one. All tasks of a meeting revolve around the same proposal/document: "
        "that does NOT make them the same task. Two different requests about the same proposal (e.g. redo the submission / "
        "re-assess impact / add mechanisms / review the name) are two different tasks. Judge by meaning, not keywords."
    ),
    "choices": [
        {
            "value": "changed",
            "description": (
                "Same task, and the later assignment cancels, replaces or modifies the content, scope, method or "
                "deadline of the earlier assignment."
            ),
        },
        {
            "value": "unchanged",
            "description": "Same task; the later assignment repeats, confirms or only adds details that do not contradict the earlier one.",
        },
        {"value": "different_matter", "description": "Two different tasks, even when both are about the same proposal or document."},
    ],
}

# Ngưỡng đo trên 8 cặp kết luận; việc giao dùng chung, CHƯA đo lại riêng.
RELATION_SAME_MIN = 0.5
RELATION_CHANGE_MIN = 0.3


@dataclass(frozen=True, slots=True)
class TurnActJudgement:
    """Kết quả phân loại hành vi của một lượt nói (giao việc, chốt, đề xuất, bác bỏ...).

    Attributes:
        label: Lựa chọn có xác suất cao nhất.
        probabilities: Xác suất của từng lựa chọn.
    """

    label: str
    probabilities: Mapping[str, float]

    @property
    def p_commit(self) -> float:
        """Xác suất lượt nói là giao/nhận việc hoặc chốt kết luận (tổng hai lựa chọn tương ứng)."""

        return sum(self.probabilities.get(label, 0.0) for label in COMMIT_LABELS)

    def describe(self) -> str:
        """Trả phân bố xác suất dạng ngắn cho lý do gửi Verifier, ví dụ "assignment 0.27, proposal 0.24"."""

        ranked = sorted(self.probabilities.items(), key=lambda kv: -kv[1])
        return ", ".join(f"{label} {p:.2f}" for label, p in ranked if p >= 0.05)


@dataclass(frozen=True, slots=True)
class ClaimSupportJudgement:
    """Kết quả kiểm lượt chốt có thật sự giao/nhận đúng NỘI DUNG mà candidate ghi hay không.

    Khác với phân loại hành vi: một lượt có thể đúng là giao việc nhưng giao một việc khác với việc
    agent đã ghi.

    Attributes:
        label: Lựa chọn có xác suất cao nhất.
        probabilities: Xác suất của từng lựa chọn.
    """

    label: str
    probabilities: Mapping[str, float]

    @property
    def p_support(self) -> float:
        """Xác suất lượt chốt ủng hộ candidate, trực tiếp hoặc qua tham chiếu đã tiếp nhận."""

        return self.probabilities.get("direct", 0.0) + self.probabilities.get("accepted_reference", 0.0)

    def describe(self) -> str:
        """Trả phân bố xác suất dạng ngắn để ghi vào cờ và nhật ký kiểm chứng."""

        ranked = sorted(self.probabilities.items(), key=lambda kv: -kv[1])
        return ", ".join(f"{label} {p:.2f}" for label, p in ranked if p >= 0.05)


def claim_support_is_clear(judgement: ClaimSupportJudgement) -> bool:
    """Kiểm tra kết quả có đủ chắc để tự động giữ candidate mà không cần Verifier phân xử hay không.

    Đủ chắc khi tổng xác suất ủng hộ đạt ngưỡng rõ ràng, hoặc riêng lựa chọn "tiếp nhận qua tham
    chiếu" đạt ngưỡng thấp hơn dành cho nó.

    Args:
        judgement: Kết quả kiểm nội dung lượt chốt.

    Returns:
        True nếu có thể giữ candidate ngay.
    """

    return (
        judgement.p_support >= CLAIM_SUPPORT_CLEAR_MIN
        or judgement.probabilities.get("accepted_reference", 0.0) >= CLAIM_SUPPORT_REFERENCE_MIN
    )


@dataclass(frozen=True, slots=True)
class ProposalResponseJudgement:
    """Kết quả phân loại cách một lượt phản hồi đối xử với một nội dung nêu ở lượt trước.

    Attributes:
        label: Lựa chọn có xác suất cao nhất.
        probabilities: Xác suất của từng lựa chọn.
    """

    label: str
    probabilities: Mapping[str, float]

    @property
    def p_accept(self) -> float:
        """Xác suất lượt phản hồi tiếp nhận nội dung, trực tiếp hoặc tiếp nhận chung các ý kiến."""

        return self.probabilities.get("direct_acceptance", 0.0) + self.probabilities.get("general_acceptance", 0.0)

    @property
    def p_reject(self) -> float:
        """Xác suất lượt phản hồi gạt đi hoặc phản đối nội dung."""

        return self.probabilities.get("rejection", 0.0)

    @property
    def p_modify(self) -> float:
        """Xác suất lượt phản hồi chấp nhận nhưng đổi nội dung, phạm vi hoặc cách làm."""

        return self.probabilities.get("modification", 0.0)

    def describe(self) -> str:
        """Trả phân bố xác suất dạng ngắn, giảm dần, bỏ các lựa chọn dưới 0.05."""

        ranked = sorted(self.probabilities.items(), key=lambda kv: -kv[1])
        return ", ".join(f"{label} {p:.2f}" for label, p in ranked if p >= 0.05)


@dataclass(frozen=True, slots=True)
class DecisionRelationJudgement:
    """Kết quả so hai kết luận (hoặc hai việc giao) của cùng cuộc họp: cùng vấn đề không, có đổi không.

    Dùng chung cho kết luận và việc giao vì hai câu hỏi có cùng ba lựa chọn: cùng vấn đề và đã đổi,
    cùng vấn đề và giữ nguyên, hoặc khác vấn đề.

    Attributes:
        label: Lựa chọn có xác suất cao nhất.
        probabilities: Xác suất của từng lựa chọn.
    """

    label: str
    probabilities: Mapping[str, float]

    @property
    def p_same(self) -> float:
        """Xác suất hai mục nói về cùng một vấn đề (tổng của "đã đổi" và "giữ nguyên")."""

        return self.probabilities.get("changed", 0.0) + self.probabilities.get("unchanged", 0.0)

    @property
    def p_change(self) -> float:
        """Xác suất mục sau cùng vấn đề và thay đổi mục trước."""

        return self.probabilities.get("changed", 0.0)

    @property
    def p_keep(self) -> float:
        """Xác suất mục sau cùng vấn đề và giữ nguyên mục trước."""

        return self.probabilities.get("unchanged", 0.0)

    def describe(self) -> str:
        """Trả phân bố xác suất dạng ngắn, giảm dần, bỏ các lựa chọn dưới 0.05."""

        ranked = sorted(self.probabilities.items(), key=lambda kv: -kv[1])
        return ", ".join(f"{label} {p:.2f}" for label, p in ranked if p >= 0.05)


class TurnActJudge(Protocol):
    """Hợp đồng của bộ phân loại hành vi lượt nói.

    Bên cài đặt nhận lượt cần xét và các lượt đứng trước làm ngữ cảnh, trả về một
    ``TurnActJudgement``. Khi không phân loại được thì ném exception; nơi gọi gắn cờ để Verifier
    xét. Bên cài đặt có thể có thêm các phương thức kiểm nội dung lượt chốt và phân loại lượt phản
    hồi; các hàm tiện ích trong module tự kiểm xem chúng có hay không.
    """

    def judge(self, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> TurnActJudgement: ...


def render_turn_act_input(turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> str:
    """Ghép ngữ cảnh và lượt cần xét thành input gửi Decisions API.

    Args:
        turn: Lượt cần xét.
        context: Các lượt ngay trước, theo thứ tự; chỉ vài lượt cuối được dùng.

    Returns:
        Văn bản input, mỗi lượt một dòng dạng "người nói: nội dung".
    """

    def line(item: SpeakerTurn) -> str:
        return f"{item.speaker or 'Unknown'}: {item.text_exact}"

    previous = list(context)[-CONTEXT_TURNS:] if CONTEXT_TURNS else []
    parts = ["CONTEXT:\n" + "\n".join(line(t) for t in previous)] if previous else []
    parts.append("TURN TO JUDGE:\n" + line(turn))
    return "\n\n".join(parts)


def render_claim_support_input(claim: str, turn: SpeakerTurn, evidence: Sequence[SpeakerTurn]) -> str:
    """Ghép candidate, các lượt bằng chứng liên quan và lượt chốt thành input câu hỏi kiểm nội dung.

    Lượt chốt không bị lặp lại trong phần bằng chứng.

    Args:
        claim: Nội dung việc/kết luận mà candidate ghi.
        turn: Lượt chốt.
        evidence: Các lượt bằng chứng candidate trích dẫn (có thể gồm cả lượt chốt).

    Returns:
        Văn bản input.
    """

    def line(item: SpeakerTurn) -> str:
        return f"[{item.turn_id}|{item.speaker or 'Unknown'}] {item.text_exact}"

    related = [item for item in evidence if item.turn_id != turn.turn_id]
    parts = [f"CLAIM TO CHECK:\n{claim}"]
    if related:
        parts.append("RELATED EVIDENCE TURNS:\n" + "\n".join(line(item) for item in related))
    parts.append("CONFIRMING TURN:\n" + line(turn))
    return "\n\n".join(parts)


def render_proposal_response_input(claim: str, proposal: SpeakerTurn, response: SpeakerTurn) -> str:
    """Ghép lượt nêu nội dung, nội dung cần xét và lượt phản hồi thành input câu hỏi phản hồi đề xuất."""

    def line(item: SpeakerTurn) -> str:
        return f"[{item.speaker or 'Unknown'}] {item.text_exact}"

    return f"RAISING TURN:\n{line(proposal)}\n\nCONTENT TO JUDGE:\n{claim}\n\nRESPONSE TURN:\n{line(response)}"


def render_decision_relation_input(earlier: str, later: str) -> str:
    """Ghép hai kết luận (trước, sau) thành input câu hỏi quan hệ kết luận; không gửi kèm lượt chốt."""

    return f"EARLIER CONCLUSION:\n{earlier}\n\nLATER CONCLUSION:\n{later}"


def render_assignment_relation_input(earlier: str, later: str) -> str:
    """Ghép hai việc giao (trước, sau; đã kèm bên nhận việc và thời hạn) thành input câu hỏi quan hệ."""

    return f"EARLIER TASK:\n{earlier}\n\nLATER TASK:\n{later}"


_SENTENCE_BREAK = re.compile(r"(?<=[.!?…])\s+")


def split_turn_text(text: str, max_chars: int = MAX_TURN_CHARS) -> tuple[str, ...]:
    """Cắt nội dung một lượt nói thành các đoạn liền nhau, mỗi đoạn không quá ``max_chars`` ký tự.

    Ưu tiên cắt ở ranh giới câu; câu quá dài thì cắt ở khoảng trắng gần nhất, không có khoảng
    trắng thì cắt cứng. Các câu ngắn liền nhau được gộp lại cho tới khi chạm trần.

    Args:
        text: Nội dung lượt nói.
        max_chars: Số ký tự tối đa của mỗi đoạn.

    Returns:
        Các đoạn theo thứ tự; một phần tử (chính ``text``) nếu lượt đủ ngắn.
    """

    if len(text) <= max_chars:
        return (text,)
    pieces: list[str] = []
    for sentence in _SENTENCE_BREAK.split(text):
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            pieces.append(sentence[:cut])
            sentence = sentence[cut:].lstrip()
        if sentence:
            pieces.append(sentence)
    windows: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) > max_chars:
            windows.append(current)
            current = piece
        else:
            current = f"{current} {piece}" if current else piece
    if current:
        windows.append(current)
    return tuple(windows)


def turn_windows(
    turn: SpeakerTurn, context: Sequence[SpeakerTurn]
) -> tuple[tuple[SpeakerTurn, tuple[SpeakerTurn, ...]], ...]:
    """Cắt một lượt quá dài thành các đoạn để hỏi riêng, kèm ngữ cảnh của từng đoạn.

    Mỗi đoạn là một lượt nói giữ nguyên mã lượt, chỉ thay nội dung. Đoạn sau nhận các đoạn trước làm
    ngữ cảnh, nên khi xét đoạn giữa mô hình vẫn thấy phần vừa nói ngay trước đó. Các lượt ngữ cảnh
    được giữ nguyên văn, không rút gọn.

    Args:
        turn: Lượt cần xét.
        context: Các lượt đứng trước, theo thứ tự.

    Returns:
        Các cặp (đoạn, ngữ cảnh của đoạn) theo thứ tự trong lượt; một cặp nếu lượt đủ ngắn.
    """

    previous = tuple(list(context)[-CONTEXT_TURNS:])
    windows = []
    for text in split_turn_text(turn.text_exact):
        part = turn if text == turn.text_exact else replace(turn, text_exact=text)
        windows.append((part, previous))
        previous = (*previous, part)
    return tuple(windows)


def judge_turn(judge: TurnActJudge, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> TurnActJudgement:
    """Phân loại hành vi của cả một lượt nói, kể cả lượt quá dài.

    Lượt dài được hỏi theo từng đoạn; chỉ cần một đoạn là giao việc/chốt thì cả lượt được coi như
    vậy, nên kết quả lấy theo đoạn có xác suất giao/chốt cao nhất.

    Args:
        judge: Bộ phân loại hành vi lượt nói.
        turn: Lượt cần xét.
        context: Các lượt đứng trước, theo thứ tự.

    Returns:
        Kết quả của đoạn có xác suất giao/chốt cao nhất.

    Raises:
        Exception: Lỗi của ``judge`` được ném tiếp.
    """

    judgements = [judge.judge(part, previous) for part, previous in turn_windows(turn, context)]
    return max(judgements, key=lambda judgement: judgement.p_commit)


def judge_claim_support(
    judge: TurnActJudge | None,
    claim: str,
    turn: SpeakerTurn,
    evidence: Sequence[SpeakerTurn],
) -> ClaimSupportJudgement | None:
    """Kiểm lượt chốt có thật sự giao/nhận đúng nội dung ``claim`` hay không.

    Lượt dài được cắt đoạn như ``judge_turn`` và lấy đoạn có xác suất ủng hộ cao nhất.

    Args:
        judge: Bộ phân loại; None hoặc bộ không hỗ trợ kiểm nội dung thì bỏ qua.
        claim: Nội dung việc/kết luận mà candidate ghi.
        turn: Lượt chốt.
        evidence: Các lượt bằng chứng candidate trích dẫn.

    Returns:
        Kết quả của đoạn ủng hộ mạnh nhất; None nếu ``judge`` không hỗ trợ.

    Raises:
        Exception: Lỗi của Decisions API được ném tiếp để nơi gọi tự quyết cách xử lý.
    """

    method = getattr(judge, "judge_claim", None) if judge is not None else None
    if not callable(method):
        return None
    judgements = [method(claim, part, evidence) for part, _ in turn_windows(turn, ())]
    return max(judgements, key=lambda judgement: judgement.p_support)


def judge_proposal_response(
    judge: TurnActJudge | None, claim: str, proposal: SpeakerTurn, response: SpeakerTurn
) -> tuple[str, ProposalResponseJudgement] | None:
    """Xác định lượt phản hồi bác, sửa hay chấp nhận một nội dung đã được nêu ở lượt trước.

    Ví dụ: một thành viên đề xuất "bổ sung đánh giá tác động", rồi lượt tổng kết sau đó nói "tiếp thu các ý
    kiến". Hàm hỏi cả lượt phản hồi và từng đoạn ngắn của nó, vì lời tiếp nhận từng ý thường nằm ở
    một câu riêng và dễ chìm khi hỏi cả lượt. Đây là chỗ DUY NHẤT áp các ngưỡng phản hồi: một đoạn
    bác (xét trước) hoặc sửa đủ mạnh và mạnh hơn đoạn chấp nhận mạnh nhất thì thắng; nếu không thì là
    chấp nhận khi đoạn chấp nhận mạnh nhất đạt ngưỡng.

    Args:
        judge: Bộ phân loại; None hoặc bộ không hỗ trợ câu hỏi phản hồi thì bỏ qua.
        claim: Nội dung đang xét (một ý trong lượt nêu).
        proposal: Lượt nêu nội dung.
        response: Lượt phản hồi, nói sau lượt nêu.

    Returns:
        Cặp (nhãn "reject" / "modify" / "accept", kết quả của đoạn quyết định nhãn đó); None nếu
        ``judge`` không hỗ trợ hoặc lượt không phản hồi rõ.

    Raises:
        Exception: Lỗi của ``judge`` được ném tiếp.
    """

    method = getattr(judge, "judge_response", None) if judge is not None else None
    if not callable(method):
        return None
    parts = dict.fromkeys((response.text_exact, *split_turn_text(response.text_exact, RESPONSE_WINDOW_CHARS)))
    judgements = [method(claim, proposal, replace(response, text_exact=part)) for part in parts]
    best = max(judgements, key=lambda judgement: judgement.p_accept)
    rejecting = max(judgements, key=lambda judgement: judgement.p_reject)
    if rejecting.p_reject >= RESPONSE_REJECT_MIN and rejecting.p_reject > best.p_accept:
        return "reject", rejecting
    modifying = max(judgements, key=lambda judgement: judgement.p_modify)
    if modifying.p_modify >= RESPONSE_MODIFY_MIN and modifying.p_modify > best.p_accept:
        return "modify", modifying
    if best.p_accept >= RESPONSE_ACCEPT_MIN:
        return "accept", best
    return None


class DecisionsApiTurnActJudge:
    """Bộ phân loại lượt nói gọi JEV qua Decisions API, nhớ kết quả theo nội dung input.

    Hỗ trợ đủ các câu hỏi: hành vi lượt nói, kiểm nội dung lượt chốt, phản hồi đề xuất và quan hệ
    giữa hai kết luận/hai việc giao. Mỗi loại câu hỏi có bộ nhớ đệm riêng, được khoá nên dùng được
    từ nhiều luồng.

    Args:
        client: Đối tượng có ``.decisions.create`` để gọi Decisions API.
        model: Tên mô hình Decisions API.
    """

    def __init__(self, client: Any, model: str = DEFAULT_MODEL) -> None:
        self._client = client
        self.model = model
        self._cache: dict[str, TurnActJudgement] = {}
        self._claim_cache: dict[str, ClaimSupportJudgement] = {}
        self._response_cache: dict[str, ProposalResponseJudgement] = {}
        self._relation_cache: dict[str, DecisionRelationJudgement] = {}
        self._lock = threading.Lock()

    def judge(self, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> TurnActJudgement:
        """Phân loại hành vi của một lượt nói (một lời gọi, có bộ nhớ đệm).

        Args:
            turn: Lượt cần xét.
            context: Các lượt đứng trước, theo thứ tự.

        Returns:
            Kết quả phân loại hành vi.

        Raises:
            ValueError: Khi Decisions API không trả lời dạng lựa chọn.
        """

        text = render_turn_act_input(turn, context)
        with self._lock:
            cached = self._cache.get(text)
        if cached is not None:
            return cached
        response = self._client.decisions.create(model=self.model, input=text, questions=[TURN_ACT_QUESTION])
        answer = response.answers[0]
        if getattr(answer, "type", None) != "choice":
            raise ValueError(f"Decisions API không trả lời câu hỏi turn_act (type={getattr(answer, 'type', None)!r})")
        judgement = TurnActJudgement(
            label=answer.choice,
            probabilities={p.value: p.probability for p in answer.probabilities},
        )
        with self._lock:
            self._cache[text] = judgement
        return judgement

    def judge_claim(
        self, claim: str, turn: SpeakerTurn, evidence: Sequence[SpeakerTurn]
    ) -> ClaimSupportJudgement:
        """Hỏi Decisions API lượt ``turn`` có giao/tiếp nhận đúng ``claim`` hay không (có bộ nhớ đệm).

        Raises:
            ValueError: Khi Decisions API không trả lời dạng lựa chọn.
        """

        text = render_claim_support_input(claim, turn, evidence)
        with self._lock:
            cached = self._claim_cache.get(text)
        if cached is not None:
            return cached
        response = self._client.decisions.create(model=self.model, input=text, questions=[CLAIM_SUPPORT_QUESTION])
        answer = response.answers[0]
        if getattr(answer, "type", None) != "choice":
            raise ValueError(
                f"Decisions API không trả lời câu hỏi claim_support (type={getattr(answer, 'type', None)!r})"
            )
        judgement = ClaimSupportJudgement(
            label=answer.choice,
            probabilities={p.value: p.probability for p in answer.probabilities},
        )
        with self._lock:
            self._claim_cache[text] = judgement
        return judgement

    def judge_response(
        self, claim: str, proposal: SpeakerTurn, response: SpeakerTurn
    ) -> ProposalResponseJudgement:
        """Hỏi Decisions API lượt ``response`` đối xử thế nào với ``claim`` nêu ở ``proposal``, có bộ nhớ đệm.

        Raises:
            ValueError: Khi Decisions API không trả lời dạng lựa chọn.
        """

        text = render_proposal_response_input(claim, proposal, response)
        with self._lock:
            cached = self._response_cache.get(text)
        if cached is not None:
            return cached
        answer = self._client.decisions.create(
            model=self.model, input=text, questions=[PROPOSAL_RESPONSE_QUESTION]
        ).answers[0]
        if getattr(answer, "type", None) != "choice":
            raise ValueError(
                f"Decisions API không trả lời câu hỏi proposal_response (type={getattr(answer, 'type', None)!r})"
            )
        judgement = ProposalResponseJudgement(
            label=answer.choice,
            probabilities={p.value: p.probability for p in answer.probabilities},
        )
        with self._lock:
            self._response_cache[text] = judgement
        return judgement

    def judge_relation(self, earlier: str, later: str) -> DecisionRelationJudgement:
        """Hỏi Decisions API kết luận ``later`` có cùng quyết định và có đổi kết luận ``earlier`` không.

        Raises:
            ValueError: Khi Decisions API không trả lời dạng lựa chọn.
        """

        return self._relation(render_decision_relation_input(earlier, later), DECISION_RELATION_QUESTION)

    def judge_assignment_relation(self, earlier: str, later: str) -> DecisionRelationJudgement:
        """Hỏi Decisions API việc giao ``later`` có cùng việc và có đổi việc giao ``earlier`` không.

        Raises:
            ValueError: Khi Decisions API không trả lời dạng lựa chọn.
        """

        return self._relation(render_assignment_relation_input(earlier, later), ASSIGNMENT_RELATION_QUESTION)

    def _relation(self, text: str, question: dict[str, Any]) -> DecisionRelationJudgement:
        """Gọi một câu hỏi quan hệ (kết luận hoặc việc giao) với input đã ghép sẵn, có bộ nhớ đệm."""

        with self._lock:
            cached = self._relation_cache.get(text)
        if cached is not None:
            return cached
        answer = self._client.decisions.create(model=self.model, input=text, questions=[question]).answers[0]
        if getattr(answer, "type", None) != "choice":
            raise ValueError(
                f"Decisions API không trả lời câu hỏi {question['name']} (type={getattr(answer, 'type', None)!r})"
            )
        judgement = DecisionRelationJudgement(
            label=answer.choice,
            probabilities={p.value: p.probability for p in answer.probabilities},
        )
        with self._lock:
            self._relation_cache[text] = judgement
        return judgement


__all__ = [
    "ASSIGNMENT_RELATION_QUESTION",
    "CLAIM_SUPPORT_CLEAR_MIN",
    "CLAIM_SUPPORT_QUESTION",
    "CLAIM_SUPPORT_REFERENCE_MIN",
    "COMMIT_CLEAR_MIN",
    "DECISION_RELATION_QUESTION",
    "PROPOSAL_RESPONSE_QUESTION",
    "RELATION_CHANGE_MIN",
    "RELATION_SAME_MIN",
    "RESPONSE_ACCEPT_MIN",
    "RESPONSE_MODIFY_MIN",
    "RESPONSE_REJECT_MIN",
    "RESPONSE_WINDOW_CHARS",
    "TURN_ACT_QUESTION",
    "ClaimSupportJudgement",
    "DecisionRelationJudgement",
    "DecisionsApiTurnActJudge",
    "ProposalResponseJudgement",
    "TurnActJudge",
    "TurnActJudgement",
    "claim_support_is_clear",
    "judge_claim_support",
    "judge_proposal_response",
    "judge_turn",
    "render_assignment_relation_input",
    "render_claim_support_input",
    "render_decision_relation_input",
    "render_proposal_response_input",
    "render_turn_act_input",
    "split_turn_text",
    "turn_windows",
]
