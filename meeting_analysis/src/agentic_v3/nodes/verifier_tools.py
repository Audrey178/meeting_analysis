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


def format_turn_line(turn: SpeakerTurn) -> str:
    """Dựng một dòng ``[turn_id|người nói] nội dung`` (cắt bớt nếu quá dài).

    Đầu vào: turn - lượt nói.
    Đầu ra: str.
    """

    text = turn.text_exact
    if len(text) > _MAX_TURN_CHARS:
        text = text[:_MAX_TURN_CHARS] + "…"
    return f"[{turn.turn_id}|{turn.speaker or 'unknown'}] {text}"


def _content_terms(text: str) -> tuple[set[str], set[tuple[str, str]]]:
    """Âm tiết nội dung (bỏ hư từ) và các cặp âm tiết liền nhau của ``text``.

    Cặp âm tiết bắt được từ ghép tiếng Việt ("kế hoạch", "nhãn dữ liệu") mà âm
    tiết đơn lẻ không phân biệt được.

    Đầu vào: text - chuỗi bất kỳ.
    Đầu ra: (tập âm tiết, tập cặp âm tiết).
    """

    tokens = word_tokens(text)
    unigrams = {token for token in tokens if token not in VN_STOPWORDS}
    bigrams = set(zip(tokens, tokens[1:]))
    return unigrams, bigrams


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
        return format_turn_line(turn)

    def search_meeting(self, query: str) -> str:
        """Tìm các lượt nói khớp từ khoá nhất trong cả cuộc họp.

        Điểm = số âm tiết nội dung trùng + 2 x số cặp âm tiết trùng; hoà điểm thì giữ
        thứ tự thời gian.

        Đầu vào: query - từ khoá.
        Đầu ra: các dòng lượt nói (tối đa ``search_top_k``) hoặc thông báo không có kết quả.
        """

        query_unigrams, query_bigrams = _content_terms(query)
        if not query_unigrams and not query_bigrams:
            return "LỖI: từ khoá chỉ gồm hư từ, hãy dùng từ khoá cụ thể hơn."
        scored = []
        for index, (unigrams, bigrams) in enumerate(self._terms):
            score = len(query_unigrams & unigrams) + 2 * len(query_bigrams & bigrams)
            if score:
                scored.append((-score, index))
        if not scored:
            return "Không có lượt nói nào khớp."
        best = sorted(scored)[: self._top_k]
        return "\n".join(format_turn_line(self._turns[index]) for _, index in sorted(best, key=lambda x: x[1]))

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
