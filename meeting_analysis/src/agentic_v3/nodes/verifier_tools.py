"""Tool CHỈ ĐỌC cho Verifier ReAct (luật, 0 token): tra bản ghi của CẢ cuộc họp.

Tool không có tác động phụ nên Verifier được gọi tự do (trong giới hạn số bước).
Lỗi tool (turn_id không tồn tại, tool lạ, tham số rỗng) được trả lại thành chuỗi
observation để Verifier tự sửa ở bước sau, không raise ra ngoài.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...agentic._shared import match_claimed_name_to_real_speaker
from ...stages._shared import VN_STOPWORDS, word_tokens
from ...utils.contracts import SpeakerTurn
from ..schemas import SpeakerRegistry

# Cắt mỗi lượt nói trong observation để prompt của Verifier không phình theo số bước.
_MAX_TURN_CHARS = 600

TOOL_DESCRIPTIONS = """
- get_turn(argument = turn_id): nguyên văn MỘT lượt nói bất kỳ trong cả cuộc họp.
- search_meeting(argument = vài từ khoá): các lượt nói khớp nhất trong CẢ cuộc họp (kể
  cả chủ đề khác), để tìm lượt giao/nhận/chốt việc nằm ngoài đoạn hiện tại.
- lookup_speaker(argument = tên hoặc cách gọi, vd "Sơn", "anh Phong"): người nói thật
  trong danh bạ cuộc họp mà cách gọi đó chỉ tới.
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
        registry: danh bạ người nói.
        search_top_k: số lượt nói tối đa ``search_meeting`` trả về.
    """

    def __init__(
        self,
        meeting_turns: Sequence[SpeakerTurn],
        registry: SpeakerRegistry,
        *,
        search_top_k: int = 5,
    ) -> None:
        self._turns = tuple(meeting_turns)
        self._by_id = {turn.turn_id: turn for turn in self._turns}
        self._registry = registry
        self._top_k = search_top_k
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

    def lookup_speaker(self, alias: str) -> str:
        """Quy một cách gọi về người nói thật trong danh bạ.

        Đầu vào: alias - tên/cách gọi.
        Đầu ra: tên người nói, danh sách ứng viên nếu mơ hồ, hoặc thông báo không tìm thấy.
        """

        matched = match_claimed_name_to_real_speaker(alias, self._turns)
        if matched is not None and matched in self._registry.names:
            return f"'{alias}' là người nói: {matched}"
        alias_tokens = set(word_tokens(alias))
        candidates = [
            name for name in self._registry.names if alias_tokens & set(word_tokens(name))
        ]
        if candidates:
            return f"'{alias}' mơ hồ, có thể là: {', '.join(candidates)}"
        return (
            f"Không có người nói nào khớp '{alias}'. Danh bạ: {', '.join(self._registry.names) or '(rỗng)'}"
        )


__all__ = ["MeetingTools", "TOOL_DESCRIPTIONS", "TOOL_NAMES", "format_turn_line"]
