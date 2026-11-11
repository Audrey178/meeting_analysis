"""Các công cụ CHỈ ĐỌC để agent kiểm chứng tra bản ghi của cả cuộc họp: xem nguyên văn một lượt nói,
tìm các lượt nói liên quan theo từ khoá, và tra người/đơn vị trong danh bạ.

Kết quả tìm kiếm được xếp theo mức độ khớp, và những lượt nói dài chỉ hiện phần chứa nhiều từ khớp
nhất.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Collection, Sequence

from ....utils.contracts import SpeakerTurn
from ...shared.actors.resolution import is_clear_choice, rank_actor_candidates
from ...shared.schemas import ActorCandidate, SpeakerRegistry
from ...shared.text import VN_STOPWORDS, WORD_RE, word_tokens


_MAX_TURN_CHARS = 600
_MAX_GET_TURN_CHARS = 3000

_SNIPPET_LEAD_CHARS = 120

_BM25_K1 = 1.2
_BM25_B = 0.75
_BIGRAM_WEIGHT = 2.0

TOOL_DESCRIPTIONS = """
- get_turn(argument = turn_id): the verbatim text of ANY ONE turn in the whole meeting.
- search_meeting(argument = a few Vietnamese keywords): the best-matching turns in the WHOLE meeting
  (including other topics), to find assigning/taking-on/settling turns outside the current segment.
- lookup_speaker(argument = how the actor is called, optionally with "@turn_id" of the confirming
  turn, e.g. "Sơn @T12", "anh Phong", "Sở Tài chính"): candidate PEOPLE or UNITS (speakers,
  attendee list) with score and reason, by decreasing score. The context around the confirming turn
  is considered first; functions/units in the list are only considered when the context cannot tell.
""".strip()

TOOL_NAMES = ("get_turn", "search_meeting", "lookup_speaker")


def format_turn_line(
    turn: SpeakerTurn, *, max_chars: int = _MAX_TURN_CHARS, focus_terms: Collection[str] = ()
) -> str:
    """Dựng một dòng ``[mã lượt|người nói] nội dung`` cho một lượt nói, cắt bớt nếu quá dài.

    Khi phải cắt, đoạn được giữ là cửa sổ chứa nhiều từ khớp ``focus_terms`` nhất; chỗ bị cắt được đánh
    dấu bằng "…".

    Args:
        turn: Lượt nói.
        max_chars: Số ký tự tối đa của phần nội dung.
        focus_terms: Các âm tiết chữ thường cần ưu tiên giữ; rỗng thì lấy phần đầu lượt nói.

    Returns:
        Dòng hiển thị lượt nói.
    """

    text = turn.text_exact
    if len(text) > max_chars:
        start = _snippet_start(text, focus_terms, max_chars)
        end = start + max_chars
        text = f"{'…' if start else ''}{text[start:end]}{'…' if end < len(text) else ''}"
    return f"[{turn.turn_id}|{turn.speaker or 'unknown'}] {text}"


def _snippet_start(text: str, focus_terms: Collection[str], max_chars: int) -> int:
    """Tìm vị trí bắt đầu của cửa sổ ``max_chars`` ký tự chứa nhiều từ khớp ``focus_terms`` nhất.

    Mỗi cửa sổ thử đặt bắt đầu sớm hơn một từ khớp một đoạn ngắn, để giữ ngữ cảnh phía trước.

    Args:
        text: Nguyên văn lượt nói.
        focus_terms: Các âm tiết chữ thường cần ưu tiên giữ.
        max_chars: Độ dài cửa sổ.

    Returns:
        Vị trí ký tự bắt đầu; 0 nếu không có từ nào khớp (lấy phần đầu lượt nói).
    """

    if not focus_terms:
        return 0
    offsets = [
        match.start()
        for match in WORD_RE.finditer(text)
        if unicodedata.normalize("NFC", match.group()).lower() in focus_terms
    ]
    best_start, best_hits = 0, 0
    for offset in offsets:
        start = max(0, min(offset - _SNIPPET_LEAD_CHARS, len(text) - max_chars))
        hits = sum(start <= other < start + max_chars for other in offsets)
        if hits > best_hits:
            best_start, best_hits = start, hits
    return best_start


def _content_terms(text: str) -> Counter:
    """Đếm các âm tiết nội dung (bỏ hư từ) và các cặp âm tiết liền nhau trong ``text``.

    Cặp âm tiết chỉ bị bỏ khi cả hai âm tiết đều là hư từ.

    Returns:
        Bộ đếm có khoá là âm tiết (chuỗi) hoặc cặp âm tiết (tuple), giá trị là số lần xuất hiện.
    """

    tokens = word_tokens(text)
    terms: Counter = Counter(token for token in tokens if token not in VN_STOPWORDS)
    terms.update(pair for pair in zip(tokens, tokens[1:]) if not set(pair) <= VN_STOPWORDS)
    return terms


def content_syllables(text: str) -> set[str]:
    """Lấy tập âm tiết nội dung (bỏ hư từ) của ``text``, dùng làm ``focus_terms`` khi trích lượt nói."""

    return {term for term in _content_terms(text) if isinstance(term, str)}


def _term_length(terms: Counter) -> int:
    """Tính độ dài lượt nói theo số âm tiết nội dung, dùng để chuẩn hoá điểm BM25."""

    return sum(count for term, count in terms.items() if isinstance(term, str))


class MeetingTools:
    """Bộ công cụ chỉ đọc của Verifier, gắn với bản ghi và danh bạ của một cuộc họp.

    Gồm ba công cụ: xem nguyên văn một lượt nói, tìm lượt nói theo từ khoá (xếp hạng BM25 trên âm tiết
    và cặp âm tiết), và tra ứng viên người/đơn vị cho một cách gọi. Mọi lỗi được trả về dưới dạng văn bản
    để mô hình đọc và tự sửa, không ném ngoại lệ.

    Args:
        meeting_turns: Mọi lượt nói của cuộc họp, theo thứ tự.
        registry: Danh bạ người nói kèm danh sách tham dự.
        search_top_k: Số lượt nói tối đa mà công cụ tìm kiếm trả về.
        task_text: Nội dung việc đang kiểm, dùng làm ngữ cảnh khi tra người/đơn vị.
        is_self_committed: True nếu việc đang kiểm được ghi là tự nhận việc.
    """

    def __init__(
        self,
        meeting_turns: Sequence[SpeakerTurn],
        registry: SpeakerRegistry,
        *,
        search_top_k: int = 5,
        task_text: str = "",
        is_self_committed: bool = False,
    ) -> None:
        self._turns = tuple(meeting_turns)
        self._by_id = {turn.turn_id: turn for turn in self._turns}
        self._by_number = _index_by_number(self._turns)
        self._registry = registry
        self._top_k = search_top_k
        self._task_text = task_text
        self._is_self_committed = is_self_committed
        self._terms = [_content_terms(turn.text_exact) for turn in self._turns]
        self._lengths = [_term_length(terms) for terms in self._terms]
        self._avg_length = (sum(self._lengths) / len(self._lengths) or 1.0) if self._lengths else 1.0
        self._doc_freq: Counter = Counter(term for terms in self._terms for term in terms)

    def run(self, action: str, argument: str) -> str:
        """Gọi một công cụ theo tên; tên lạ hoặc tham số rỗng được trả thành thông báo lỗi.

        Args:
            action: Tên công cụ.
            argument: Tham số dạng chuỗi; None được coi như rỗng.

        Returns:
            Kết quả tra cứu đưa lại cho Verifier.
        """

        argument = (argument or "").strip()
        if action not in TOOL_NAMES:
            return f"ERROR: no tool '{action}'. Only use: {', '.join(TOOL_NAMES)} or final."
        if not argument:
            return f"ERROR: tool {action} needs a non-empty argument."
        if action == "get_turn":
            return self.get_turn(argument)
        if action == "search_meeting":
            return self.search_meeting(argument)
        return self.lookup_speaker(argument)

    def get_turn(self, turn_id: str) -> str:
        """Trả nguyên văn một lượt nói (cắt ở mức dài hơn so với kết quả tìm kiếm).

        Args:
            turn_id: Mã lượt nói; chấp nhận cả dạng "[T1|Tên]" hoặc chỉ số thứ tự ở cuối mã.

        Returns:
            Dòng lượt nói, hoặc thông báo lỗi nếu không có lượt đó.
        """

        bare = self._resolve_turn_id(turn_id)
        turn = self._by_id.get(bare)
        if turn is None:
            return f"ERROR: no turn '{bare}' in the meeting."
        return format_turn_line(turn, max_chars=_MAX_GET_TURN_CHARS)

    def _resolve_turn_id(self, raw: str) -> str:
        """Chuẩn hoá cách Verifier gọi một lượt nói về mã lượt thật của cuộc họp.

        Bỏ ngoặc vuông và phần tên người nói; nếu vẫn không khớp thì thử khớp theo số thứ tự ở cuối mã
        (ví dụ "T30" khớp "TURN_000030"), miễn số đó không trùng giữa nhiều lượt.

        Args:
            raw: Chuỗi Verifier đưa vào.

        Returns:
            Mã lượt thật nếu tìm được; ngược lại là chuỗi đã bỏ ngoặc, để dùng trong thông báo lỗi.
        """

        bare = raw.strip().lstrip("[").split("|", 1)[0].rstrip("]").strip()
        if bare in self._by_id:
            return bare
        number = _trailing_number(bare)
        return self._by_number.get(number, bare) if number is not None else bare

    def search_meeting(self, query: str) -> str:
        """Tìm các lượt nói khớp từ khoá nhất trong cả cuộc họp, kể cả ở chủ đề khác.

        Lấy những lượt điểm cao nhất rồi hiển thị theo thứ tự thời gian trong cuộc họp.

        Args:
            query: Vài từ khoá.

        Returns:
            Các dòng lượt nói (tối đa ``search_top_k``); hoặc thông báo nếu từ khoá chỉ gồm hư từ hay
            không có lượt nào khớp.
        """

        query_terms = set(_content_terms(query))
        if not query_terms:
            return "ERROR: the keywords are only function words; use more specific keywords."
        scored = []
        for index, terms in enumerate(self._terms):
            score = self._bm25(query_terms, terms, self._lengths[index])
            if score > 0:
                scored.append((-score, index))
        if not scored:
            return "No matching turn."
        best = sorted(scored)[: self._top_k]
        focus = content_syllables(query)
        return "\n".join(
            format_turn_line(self._turns[index], focus_terms=focus) for _, index in sorted(best, key=lambda x: x[1])
        )

    def _bm25(self, query_terms: set, terms: Counter, length: int) -> float:
        """Tính điểm BM25 của một lượt nói với tập từ khoá; cặp âm tiết khớp được nhân trọng số cao hơn.

        Args:
            query_terms: Âm tiết và cặp âm tiết của từ khoá.
            terms: Bộ đếm âm tiết và cặp âm tiết của lượt nói.
            length: Số âm tiết nội dung của lượt nói.

        Returns:
            Điểm khớp; 0 nếu không trùng từ nào.
        """

        total = len(self._turns)
        norm = _BM25_K1 * (1 - _BM25_B + _BM25_B * length / self._avg_length)
        score = 0.0
        for term in query_terms:
            tf = terms.get(term, 0)
            if not tf:
                continue
            df = self._doc_freq[term]
            idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
            weight = _BIGRAM_WEIGHT if isinstance(term, tuple) else 1.0
            score += weight * idf * tf * (_BM25_K1 + 1) / (tf + norm)
        return score

    def lookup_speaker(self, argument: str) -> str:
        """Liệt kê các ứng viên người hoặc đơn vị cho một cách gọi bên nhận việc, kèm điểm và lý do.

        Nếu có kèm lượt chốt, ngữ cảnh quanh lượt đó được dùng để phân định ứng viên.

        Args:
            argument: Cách gọi, tuỳ chọn kèm "@mã lượt chốt", ví dụ "Sơn @T12" hoặc "Sở Tài chính".

        Returns:
            Các dòng ``mã | tên | loại | điểm | lý do`` và một dòng kết luận CLEAR hoặc AMBIGUOUS; hoặc thông
            báo lỗi / không có ứng viên (kèm danh sách người nói đã biết).
        """

        alias, _, turn_part = argument.partition("@")
        alias = alias.strip()
        context_turn_id = self._resolve_turn_id(turn_part) or None
        if not alias:
            return "ERROR: missing the actor's form of address before '@'."
        if context_turn_id and context_turn_id not in self._by_id:
            return f"ERROR: no turn '{context_turn_id}' in the meeting."
        candidates = rank_actor_candidates(
            alias,
            self._registry,
            meeting_turns=self._turns,
            context_turn_id=context_turn_id,
            task_text=self._task_text,
            is_self_committed=self._is_self_committed,
            declared_type="unknown",
        )
        if not candidates:
            known = ", ".join(self._registry.names) or "(empty)"
            return f"No person/unit matches '{alias}'. Speakers: {known}"
        lines = [_format_candidate(candidate) for candidate in candidates]
        if is_clear_choice(candidates):
            lines.append(f"CLEAR: '{alias}' is {candidates[0].name} ({candidates[0].actor_type}).")
        else:
            lines.append(f"AMBIGUOUS: no candidate is clear enough for '{alias}'; choose by the evidence or leave unknown.")
        return "\n".join(lines)


def _trailing_number(turn_id: str) -> int | None:
    """Lấy số thứ tự ở cuối một mã lượt ("TURN_000030" ra 30, "T5" ra 5); None nếu không có."""

    match = re.search(r"(\d+)\s*$", turn_id)
    return int(match.group(1)) if match else None


def _index_by_number(turns: Sequence[SpeakerTurn]) -> dict[int, str]:
    """Lập bảng tra số thứ tự sang mã lượt; bỏ những số trùng giữa nhiều lượt để không đoán sai."""

    index: dict[int, str] = {}
    duplicated: set[int] = set()
    for turn in turns:
        number = _trailing_number(turn.turn_id)
        if number is None:
            continue
        if number in index:
            duplicated.add(number)
        index[number] = turn.turn_id
    return {number: turn_id for number, turn_id in index.items() if number not in duplicated}


def _format_candidate(candidate: ActorCandidate) -> str:
    """Dựng một dòng mô tả ứng viên trong kết quả tra người/đơn vị."""

    return (
        f"{candidate.ref_id or '-'} | {candidate.name} | {candidate.actor_type} | "
        f"{candidate.score:.2f} | {candidate.reason}"
    )


__all__ = [
    "MeetingTools",
    "TOOL_DESCRIPTIONS",
    "TOOL_NAMES",
    "format_turn_line",
]
