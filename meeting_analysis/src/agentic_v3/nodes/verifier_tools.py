"""Tool CHỈ ĐỌC cho Verifier ReAct (luật, 0 token): tra bản ghi của CẢ cuộc họp.

Tool không có tác động phụ nên Verifier được gọi tự do (trong giới hạn số bước).
Lỗi tool (turn_id không tồn tại, tool lạ, tham số rỗng) được trả lại thành chuỗi
observation để Verifier tự sửa ở bước sau, không raise ra ngoài.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...stages._shared import VN_STOPWORDS, word_tokens
from ...utils.contracts import SpeakerTurn
from ..actors.resolution import is_clear_choice, rank_actor_candidates
from ..schemas import ActorCandidate, SpeakerRegistry

# Cắt mỗi lượt nói trong observation để prompt của Verifier không phình theo số bước.
_MAX_TURN_CHARS = 600
_MAX_GET_TURN_CHARS = 3000
# Đoạn trích của search_meeting bắt đầu trước từ khớp đầu tiên chừng này ký tự.
_SNIPPET_LEAD_CHARS = 120

# Tham số BM25. Điểm thô (đếm số từ trùng) làm các lượt nói dài luôn đứng đầu và đẩy
# các lượt ngắn như lời chốt của chủ trì ra khỏi top-k; BM25 chuẩn hoá theo độ dài
# lượt nói và hạ trọng số từ xuất hiện ở hầu hết các lượt ("đề án", "cái").
_BM25_K1 = 1.2
_BM25_B = 0.75
_BIGRAM_WEIGHT = 2.0

TOOL_DESCRIPTIONS = """
- get_turn(argument = turn_id): nguyên văn MỘT lượt nói bất kỳ trong cả cuộc họp.
- search_meeting(argument = vài từ khoá): các lượt nói khớp nhất trong CẢ cuộc họp (kể
  cả chủ đề khác), để tìm lượt giao/nhận/chốt việc nằm ngoài đoạn hiện tại.
- lookup_speaker(argument = cách gọi actor, tuỳ chọn kèm "@turn_id" của lượt chốt, vd
  "Sơn @T12", "anh Phong", "Sở Tài chính"): các ứng viên NGƯỜI hoặc ĐƠN VỊ (người nói,
  danh sách tham dự) kèm điểm và lý do, điểm giảm dần. Ngữ cảnh quanh lượt chốt được
  xét trước, chức năng/đơn vị trong danh sách chỉ xét khi ngữ cảnh chưa phân định được.
""".strip()

TOOL_NAMES = ("get_turn", "search_meeting", "lookup_speaker")


def format_turn_line(
    turn: SpeakerTurn, *, max_chars: int = _MAX_TURN_CHARS, focus_terms: Collection[str] = ()
) -> str:
    """Dựng một dòng ``[turn_id|người nói] nội dung`` (cắt bớt nếu quá dài).

    Lượt nói dài được cắt quanh chỗ có nhiều từ khớp ``focus_terms`` nhất thay vì lấy
    phần đầu, vì câu giao/chốt thường nằm cuối một lượt nói dài.

    Đầu vào: turn - lượt nói; max_chars - độ dài tối đa phần nội dung;
        focus_terms - âm tiết (chữ thường) cần giữ trong đoạn trích.
    Đầu ra: str.
    """

    text = turn.text_exact
    if len(text) > max_chars:
        start = _snippet_start(text, focus_terms, max_chars)
        end = start + max_chars
        text = f"{'…' if start else ''}{text[start:end]}{'…' if end < len(text) else ''}"
    return f"[{turn.turn_id}|{turn.speaker or 'unknown'}] {text}"


def _snippet_start(text: str, focus_terms: Collection[str], max_chars: int) -> int:
    """Vị trí bắt đầu cửa sổ ``max_chars`` ký tự chứa nhiều từ khớp ``focus_terms`` nhất.

    Đầu vào: text - nguyên văn lượt nói; focus_terms - âm tiết chữ thường; max_chars.
    Đầu ra: int - 0 nếu không có từ nào khớp (lấy phần đầu như cũ).
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
    """Đếm âm tiết nội dung (bỏ hư từ) và cặp âm tiết liền nhau của ``text``.

    Cặp âm tiết bắt được từ ghép tiếng Việt ("kế hoạch", "nhãn dữ liệu") mà âm
    tiết đơn lẻ không phân biệt được; cặp chỉ gồm hư từ bị bỏ.

    Đầu vào: text - chuỗi bất kỳ.
    Đầu ra: Counter - khoá là âm tiết (str) hoặc cặp âm tiết (tuple), giá trị là số lần.
    """

    tokens = word_tokens(text)
    terms: Counter = Counter(token for token in tokens if token not in VN_STOPWORDS)
    terms.update(pair for pair in zip(tokens, tokens[1:]) if not set(pair) <= VN_STOPWORDS)
    return terms


def _term_length(terms: Counter) -> int:
    """Độ dài lượt nói theo số âm tiết nội dung (dùng cho chuẩn hoá BM25)."""

    return sum(count for term, count in terms.items() if isinstance(term, str))


class MeetingTools:
    """Bộ tool của Verifier, gắn với bản ghi và danh bạ của một cuộc họp.

    Đầu vào khi tạo:
        meeting_turns: mọi lượt nói của cuộc họp, theo thứ tự.
        registry: danh bạ người nói + danh sách tham dự.
        search_top_k: số lượt nói tối đa ``search_meeting`` trả về.
        task_text: nội dung việc đang kiểm (tín hiệu chức năng của ``lookup_speaker``).
        is_self_committed: việc đang kiểm là tự nhận.
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
        self._registry = registry
        self._top_k = search_top_k
        self._task_text = task_text
        self._is_self_committed = is_self_committed
        self._terms = [_content_terms(turn.text_exact) for turn in self._turns]
        self._lengths = [_term_length(terms) for terms in self._terms]
        self._avg_length = (sum(self._lengths) / len(self._lengths) or 1.0) if self._lengths else 1.0
        self._doc_freq: Counter = Counter(term for terms in self._terms for term in terms)

    def run(self, action: str, argument: str) -> str:
        """Gọi tool theo tên; mọi lỗi được trả thành observation.

        Đầu vào: action - tên tool; argument - tham số dạng chuỗi.
        Đầu ra: str - observation đưa lại cho Verifier.
        """

        argument = (argument or "").strip()
        if action not in TOOL_NAMES:
            return f"LỖI: không có tool '{action}'. Chỉ dùng: {', '.join(TOOL_NAMES)} hoặc final."
        if not argument:
            return f"LỖI: tool {action} cần argument không rỗng."
        if action == "get_turn":
            return self.get_turn(argument)
        if action == "search_meeting":
            return self.search_meeting(argument)
        return self.lookup_speaker(argument)

    def get_turn(self, turn_id: str) -> str:
        """Nguyên văn một lượt nói.

        Đầu vào: turn_id - mã lượt nói (chấp nhận cả dạng "[T1|Tên]").
        Đầu ra: dòng lượt nói, hoặc thông báo lỗi.
        """

        bare = turn_id.strip().lstrip("[").split("|", 1)[0].rstrip("]").strip()
        turn = self._by_id.get(bare)
        if turn is None:
            return f"LỖI: không có lượt nói '{bare}' trong cuộc họp."
        return format_turn_line(turn, max_chars=_MAX_GET_TURN_CHARS)

    def search_meeting(self, query: str) -> str:
        """Tìm các lượt nói khớp từ khoá nhất trong cả cuộc họp.

        Điểm BM25 trên âm tiết nội dung và cặp âm tiết (cặp nặng gấp ``_BIGRAM_WEIGHT``);
        hoà điểm thì giữ thứ tự thời gian. Kết quả in theo thứ tự thời gian, mỗi lượt
        cắt quanh chỗ khớp từ khoá.

        Đầu vào: query - từ khoá.
        Đầu ra: các dòng lượt nói (tối đa ``search_top_k``) hoặc thông báo không có kết quả.
        """

        query_terms = set(_content_terms(query))
        if not query_terms:
            return "LỖI: từ khoá chỉ gồm hư từ, hãy dùng từ khoá cụ thể hơn."
        scored = []
        for index, terms in enumerate(self._terms):
            score = self._bm25(query_terms, terms, self._lengths[index])
            if score > 0:
                scored.append((-score, index))
        if not scored:
            return "Không có lượt nói nào khớp."
        best = sorted(scored)[: self._top_k]
        focus = {term for term in query_terms if isinstance(term, str)}
        return "\n".join(
            format_turn_line(self._turns[index], focus_terms=focus) for _, index in sorted(best, key=lambda x: x[1])
        )

    def _bm25(self, query_terms: set, terms: Counter, length: int) -> float:
        """Điểm BM25 của một lượt nói với tập từ khoá.

        Đầu vào: query_terms - âm tiết/cặp âm tiết của từ khoá; terms - Counter của lượt
            nói; length - số âm tiết nội dung của lượt nói.
        Đầu ra: float (0 nếu không trùng từ nào).
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
        """Liệt kê ứng viên (người/đơn vị) cho một cách gọi actor, kèm điểm và lý do.

        Đầu vào: argument - cách gọi, tuỳ chọn kèm "@turn_id" của lượt chốt ("Sơn @T12").
        Đầu ra: các dòng ``mã | tên | loại | điểm | lý do`` và dòng kết luận RÕ RÀNG/MƠ HỒ,
            hoặc thông báo không có ứng viên.
        """

        alias, _, turn_part = argument.partition("@")
        alias = alias.strip()
        context_turn_id = turn_part.strip().lstrip("[").split("|", 1)[0].rstrip("]").strip() or None
        if not alias:
            return "LỖI: thiếu cách gọi actor trước '@'."
        if context_turn_id and context_turn_id not in self._by_id:
            return f"LỖI: không có lượt nói '{context_turn_id}' trong cuộc họp."
        candidates = rank_actor_candidates(
            alias,
            self._registry,
            meeting_turns=self._turns,
            context_turn_id=context_turn_id,
            task_text=self._task_text,
            is_self_committed=self._is_self_committed,
        )
        if not candidates:
            known = ", ".join(self._registry.names) or "(rỗng)"
            return f"Không có người/đơn vị nào khớp '{alias}'. Người nói: {known}"
        lines = [_format_candidate(candidate) for candidate in candidates]
        if is_clear_choice(candidates):
            lines.append(f"RÕ RÀNG: '{alias}' là {candidates[0].name} ({candidates[0].actor_type}).")
        else:
            lines.append(f"MƠ HỒ: chưa ứng viên nào đủ rõ cho '{alias}'; chọn theo bằng chứng hoặc để unknown.")
        return "\n".join(lines)


def _format_candidate(candidate: ActorCandidate) -> str:
    """Một dòng ứng viên trong observation của ``lookup_speaker``."""

    return (
        f"{candidate.ref_id or '-'} | {candidate.name} | {candidate.actor_type} | "
        f"{candidate.score:.2f} | {candidate.reason}"
    )


__all__ = ["MeetingTools", "TOOL_DESCRIPTIONS", "TOOL_NAMES", "format_turn_line"]
