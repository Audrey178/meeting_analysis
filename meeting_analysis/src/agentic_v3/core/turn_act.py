"""Phân loại hành động lời nói của lượt chốt (giao việc / kết luận / đề xuất ...) theo NGHĨA.

Thay cho so khớp ``_COMMIT_CUES``/``_HEDGE_CUES`` trong ``_shared._confirm_turn_reasons``
khi có judge. Luật từ khoá bỏ sót khẩu ngữ ("cứ làm cái này nhá", "để Sơn nghiên cứu giúp
anh") và gắn cờ nhầm theo cụm ("hay là" trong "bản hay là cái gì cũng được"). Đo trên 869
lượt có gold của ``eval/synthetic`` (``experiments/009_decisions_api``): regex P=0.77
R=0.61; Decisions API p_commit>=0.5 P=0.86 R=0.93, ECE 0.04. Chia ba vùng:
p_commit >= ``COMMIT_CLEAR_MIN`` thì 92% đúng là chốt, < ``COMMIT_REJECT_MAX`` thì chỉ 4%.

``DecisionsTurnActJudge`` gọi OpenAI Decisions API (``client.decisions.create``), cùng
schema câu hỏi đã đo trong thí nghiệm trên.

``render_turn_act_input`` chỉ giữ ``MAX_TURN_CHARS`` ký tự đầu mỗi lượt. Lượt dài (câu chốt có
thể nằm sau mốc đó) được cắt thành nhiều đoạn bằng ``turn_windows`` và hỏi từng đoạn, nên input
mỗi lời gọi vẫn ngắn như lúc đo; ``judge_turn`` làm việc đó cho nơi cần MỘT kết quả mỗi lượt.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from ...utils.contracts import SpeakerTurn

# Ngưỡng ba vùng của p_commit, chọn trên eval/synthetic (xem docstring module).
COMMIT_CLEAR_MIN = 0.8
COMMIT_REJECT_MAX = 0.2

COMMIT_LABELS = ("giao_viec", "ket_luan")
DEFAULT_MODEL = "gpt-6-luna"
# Số lượt đứng trước gửi kèm làm ngữ cảnh, và trần ký tự mỗi lượt (lượt ASR có thể rất dài).
CONTEXT_TURNS = 2
MAX_TURN_CHARS = 2500

TURN_ACT_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "turn_act",
    "instructions": (
        "Input là trích đoạn cuộc họp tiếng Việt: vài lượt ngữ cảnh rồi LƯỢT CẦN XÉT. "
        "Chỉ phân loại LƯỢT CẦN XÉT, dùng ngữ cảnh để hiểu nó. Xét theo nghĩa, không theo từ khoá: "
        "khẩu ngữ như 'nhá', 'cứ làm đi', 'coi như xong', 'giúp anh' vẫn có thể là giao/chốt; "
        "'đề nghị' của người chủ trì thường là chỉ đạo, của đại biểu thường là kiến nghị."
    ),
    "choices": [
        {"value": "giao_viec", "description": "Giao việc cho người/đơn vị cụ thể, hoặc một người nhận/cam kết làm việc."},
        {"value": "ket_luan", "description": "Chốt, kết luận hoặc thống nhất một quyết định."},
        {"value": "de_xuat", "description": "Mới là ý kiến, đề xuất, kiến nghị, ghi nhận; chưa ai chốt hay nhận."},
        {"value": "bac_bo", "description": "Gạt đi, đảo lại hoặc huỷ một đề xuất/quyết định/việc trước đó."},
        {"value": "thao_luan", "description": "Trình bày, báo cáo, hỏi đáp; không giao, không chốt."},
        {"value": "khac", "description": "Không thuộc các loại trên."},
    ],
}


@dataclass(frozen=True, slots=True)
class TurnActJudgement:
    """Kết quả phân loại một lượt nói.

    Các trường:
        label: lựa chọn có xác suất cao nhất (một ``value`` trong ``TURN_ACT_QUESTION``).
        probabilities: xác suất từng lựa chọn.
    """

    label: str
    probabilities: Mapping[str, float]

    @property
    def p_commit(self) -> float:
        """Xác suất lượt nói là giao/nhận việc hoặc chốt kết luận."""

        return sum(self.probabilities.get(label, 0.0) for label in COMMIT_LABELS)

    def describe(self) -> str:
        """Phân bố xác suất dạng ngắn cho lý do gửi Verifier, vd. "giao_viec 0.27, de_xuat 0.24"."""

        ranked = sorted(self.probabilities.items(), key=lambda kv: -kv[1])
        return ", ".join(f"{label} {p:.2f}" for label, p in ranked if p >= 0.05)


class TurnActJudge(Protocol):
    """Phân loại ``turn`` khi biết các lượt đứng trước nó (``context``).

    Lỗi: ném exception khi không phân loại được; nơi gọi tự quay về luật từ khoá.
    """

    def judge(self, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> TurnActJudgement: ...


def render_turn_act_input(turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> str:
    """Ghép ngữ cảnh + lượt cần xét thành input cho Decisions.

    Đầu vào: turn - lượt cần xét; context - các lượt ngay trước (lấy ``CONTEXT_TURNS`` lượt cuối).
    Đầu ra: str.
    """

    def line(item: SpeakerTurn) -> str:
        return f"{item.speaker or 'Không rõ'}: {item.text_exact[:MAX_TURN_CHARS]}"

    previous = list(context)[-CONTEXT_TURNS:] if CONTEXT_TURNS else []
    parts = ["NGỮ CẢNH:\n" + "\n".join(line(t) for t in previous)] if previous else []
    parts.append("LƯỢT CẦN XÉT:\n" + line(turn))
    return "\n\n".join(parts)


_SENTENCE_BREAK = re.compile(r"(?<=[.!?…])\s+")


def split_turn_text(text: str, max_chars: int = MAX_TURN_CHARS) -> tuple[str, ...]:
    """Cắt nội dung một lượt thành các đoạn liền nhau, mỗi đoạn tối đa ``max_chars`` ký tự.

    Cắt theo ranh giới câu; câu dài hơn ``max_chars`` thì cắt ở khoảng trắng.

    Đầu vào: text - nội dung lượt; max_chars - trần ký tự mỗi đoạn.
    Đầu ra: tuple các đoạn theo thứ tự (một phần tử nếu lượt đủ ngắn).
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


def tail_turn(turn: SpeakerTurn, max_chars: int = MAX_TURN_CHARS) -> SpeakerTurn:
    """Lượt ngữ cảnh chỉ giữ ``max_chars`` ký tự CUỐI (phần sát lượt cần xét), cắt ở khoảng trắng."""

    text = turn.text_exact
    if len(text) <= max_chars:
        return turn
    tail = text[-max_chars:]
    space = tail.find(" ")
    return replace(turn, text_exact=tail[space + 1:] if space >= 0 else tail)


def turn_windows(
    turn: SpeakerTurn, context: Sequence[SpeakerTurn]
) -> tuple[tuple[SpeakerTurn, tuple[SpeakerTurn, ...]], ...]:
    """Cắt lượt dài hơn ``MAX_TURN_CHARS`` thành các đoạn để hỏi riêng, kèm ngữ cảnh của từng đoạn.

    Mỗi đoạn là một ``SpeakerTurn`` cùng ``turn_id``. Đoạn sau nhận đoạn trước làm ngữ cảnh;
    lượt ngữ cảnh dài chỉ giữ phần cuối, sát lượt cần xét.

    Đầu vào: turn - lượt cần xét; context - các lượt đứng trước, theo thứ tự.
    Đầu ra: tuple (đoạn, ngữ cảnh của đoạn) theo thứ tự trong lượt; một phần tử nếu lượt đủ ngắn.
    """

    previous = tuple(tail_turn(item) for item in list(context)[-CONTEXT_TURNS:])
    windows = []
    for text in split_turn_text(turn.text_exact):
        part = turn if text == turn.text_exact else replace(turn, text_exact=text)
        windows.append((part, previous))
        previous = (*previous, part)
    return tuple(windows)


def judge_turn(judge: TurnActJudge, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> TurnActJudgement:
    """Phân loại cả lượt, kể cả lượt dài hơn ``MAX_TURN_CHARS``: hỏi từng đoạn (``turn_windows``).

    Lượt có câu chốt ở một đoạn bất kỳ là lượt chốt, nên lấy kết quả của đoạn có p_commit cao
    nhất. Lượt ngắn chỉ có một đoạn: đúng một lời gọi, input như ``judge.judge(turn, context)``.

    Đầu vào: judge - TurnActJudge; turn - lượt cần xét; context - các lượt đứng trước, theo thứ tự.
    Đầu ra: TurnActJudgement của đoạn có p_commit cao nhất.
    Lỗi: exception của judge được ném tiếp.
    """

    judgements = [judge.judge(part, previous) for part, previous in turn_windows(turn, context)]
    return max(judgements, key=lambda judgement: judgement.p_commit)


class DecisionsTurnActJudge:
    """``TurnActJudge`` gọi OpenAI Decisions API, nhớ kết quả theo nội dung input.

    Nhiều candidate của cùng một chủ đề hay trỏ chung một lượt chốt nên cache tránh gọi lặp.

    Đầu vào khi tạo:
        client: ``openai.OpenAI`` (hoặc vật có ``.decisions.create`` cùng chữ ký).
        model: model Decisions.
    """

    def __init__(self, client: Any, model: str = DEFAULT_MODEL) -> None:
        self._client = client
        self.model = model
        self._cache: dict[str, TurnActJudgement] = {}
        self._lock = threading.Lock()

    def judge(self, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> TurnActJudgement:
        text = render_turn_act_input(turn, context)
        with self._lock:
            cached = self._cache.get(text)
        if cached is not None:
            return cached
        response = self._client.decisions.create(model=self.model, input=text, questions=[TURN_ACT_QUESTION])
        answer = response.answers[0]
        if getattr(answer, "type", None) != "choice":
            raise ValueError(f"Decisions không trả lời câu hỏi turn_act (type={getattr(answer, 'type', None)!r})")
        judgement = TurnActJudgement(
            label=answer.choice,
            probabilities={p.value: p.probability for p in answer.probabilities},
        )
        with self._lock:
            self._cache[text] = judgement
        return judgement


__all__ = [
    "COMMIT_CLEAR_MIN",
    "COMMIT_REJECT_MAX",
    "DecisionsTurnActJudge",
    "TURN_ACT_QUESTION",
    "TurnActJudge",
    "TurnActJudgement",
    "judge_turn",
    "render_turn_act_input",
    "split_turn_text",
    "tail_turn",
    "turn_windows",
]
