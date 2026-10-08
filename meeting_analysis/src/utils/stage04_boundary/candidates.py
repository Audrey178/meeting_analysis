"""Giai đoạn 4a -- CandidateGenerator: liệt kê mọi vị trí cắt hợp lệ.

Lớp này chỉ đề xuất các vị trí (offset), không bao giờ dịch chuyển hay thay
đổi bất kỳ ký tự nào. Nhờ vậy, bất biến "giữ nguyên đoạn văn bản gốc"
(exact-span invariant) của giai đoạn 4 được đảm bảo về mặt cấu trúc: 4a liệt
kê đầy đủ tập hợp các vị trí cắt hợp lệ, còn 4c chỉ được phép chọn trong tập
đó, không được tạo thêm vị trí mới.

Các nguồn phát hiện vị trí cắt bao gồm: dấu câu, từ nối diễn ngôn (discourse
marker), ranh giới mục (item boundary), khoảng lặng (pause) và một
``ClauseBoundaryAdapter`` tùy chọn (mô hình bên ngoài). Mỗi nguồn mang theo
một giá trị "prior" (độ ưu tiên/độ tin cậy mặc định); trong đó chỉ có
``item_boundary`` được cấu hình qua config, các nguồn còn lại là điểm khởi
đầu tạm thời, chờ benchmark T12 đánh giá lại.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from ..contracts import SpeakerTurn
from ..ports import ClauseBoundaryAdapter, ItemSpan


# 4a -- CandidateGenerator (Bộ sinh ứng viên vị trí cắt)
# ---------------------------------------------------------------------------

_NON_BOUNDARY_MARK = "·"
_SENTENCE_END_RE = re.compile(r"[.!?…]+[\"'”’)\]]*", re.UNICODE)
# Comma was tried here (alongside ;/:) in an earlier pass and reverted: it
# fixed word-level breaks but tore apart enumerated lists and multi-word
# entity names that happen to contain an internal comma in ASR output (e.g.
# "Bộ Nông nghiệp, Môi trường" -- one ministry, "Bộ Nông nghiệp và Môi
# trường" -- split at the comma into two fragments). See run_to_stage4.py
# Completion Report. The actual fix for the turns comma was rescuing is the
# continuation penalty in scoring.py's score_candidates(), not this regex --
# do not re-add comma here without re-reading that history.
_WEAK_PUNCT_RE = re.compile(r"[;:]")


_PUNCTUATED_DISCOURSE_MARKER_RE = re.compile(
    r"(?<!\w)(?:tuy\s+nhiên|do\s+đó|vì\s+vậy|mặt\s+khác|ngược\s+lại|"
    r"trong\s+khi|đồng\s+thời|nhưng)(?!\w)",
    re.IGNORECASE,
)

# F3: các từ nối diễn ngôn thường mở đầu một mệnh đề mới một cách đáng tin
# cậy, kể cả khi đầu ra ASR hoàn toàn không có dấu câu (trường hợp "Về
# nguồn vốn" nêu trong brief). Chỉ dùng một danh sách được chọn lọc kỹ,
# độ chính xác cao -- đây là nguồn ứng viên duy nhất không có dấu câu để
# dựa vào, nên một kết quả dương tính giả (false positive) ở đây sẽ tạo ra
# một điểm cắt sai mà không có tín hiệu nào khác xác nhận.
_UNPUNCTUATED_DISCOURSE_MARKER_RE = re.compile(
    r"(?:^|(?<=\s))(?:về\s+phía|về|thứ\s+nhất|thứ\s+hai|thứ\s+ba|"
    r"tiếp\s+theo|đối\s+với|riêng|ngoài\s+ra|bên\s+cạnh\s+đó)(?=\s)",
    re.IGNORECASE,
)

_UNPUNCTUATED_WEAK_MARKER_RE = re.compile(
    r"(?:^|(?<=\s))về(?=\s)", re.IGNORECASE,
)


_PERIOD_ABBREVIATIONS = frozenset(
    {
        "bs", "dr", "e.g", "gs", "i.e", "ks", "mr", "mrs", "p", "pgs",
        "pgs.ts", "prof", "q", "th.s", "ths", "tp", "tp.hcm", "ts", "v.d",
        "v.v",
    }
)
_PREFIX_ABBREVIATIONS = frozenset(
    {
        "bs", "dr", "gs", "ks", "mr", "mrs", "p", "pgs", "pgs.ts", "prof",
        "q", "th.s", "ths", "tp", "ts",
    }
)

_PUNCT_SOURCE_NAMES = frozenset(
    {"turn_edge", "sentence_punct", "weak_punct", "item_boundary", "model"}
)


_SENTENCE_PUNCT_PRIOR = 0.9
_WEAK_PUNCT_PRIOR = 0.5
_DISCOURSE_MARKER_PRIOR = 0.6
_DISCOURSE_MARKER_WEAK_PRIOR = 0.35
_DEFAULT_MODEL_PRIOR = 0.7
_TURN_EDGE_PRIOR = 1.0


@dataclass(frozen=True, slots=True)
class Candidate:
    """Một vị trí (offset) trong ``turn.text_exact`` mà 4c được phép cắt tại đó.

    Thuộc tính:
        pos: Vị trí ký tự (offset) trong văn bản gốc, nơi có thể thực hiện
            cắt.
        source: Tên của mọi nguồn đã đóng góp vào vị trí này, nối với nhau
            bằng ``"+"`` theo thứ tự sắp xếp (theo đúng quy ước
            ``"rule+rule"`` mà ``training/clause_data.py`` đang dùng).
        prior: Giá trị prior lớn nhất trong số các nguồn đóng góp trên.
        model_confidence: Độ tin cậy riêng do mô hình (``ClauseBoundaryAdapter``)
            trả về, được giữ tách biệt với ``prior`` vì đây là giá trị duy
            nhất cần được giữ nguyên (verbatim) khi truyền vào
            ``AnalysisAtom.boundary_confidence`` lúc vị trí này được chọn --
            nếu gộp chung vào giá trị tổng hợp (aggregate) sẽ vô tình làm
            sai lệch ý nghĩa của nó.
    """

    pos: int
    source: str
    prior: float
    punct_prior: float = 0.0
    discourse_prior: float = 0.0
    model_confidence: float | None = None


def _previous_dotted_word(text: str, period_index: int) -> str:
    start = period_index
    while start > 0 and (text[start - 1].isalpha() or text[start - 1] == "."):
        start -= 1
    return text[start:period_index].casefold()


def _period_is_internal(text: str, index: int) -> bool:
    """Nhận diện các dấu chấm (.) không thể là ranh giới mệnh đề/câu (ví dụ:
    dấu phân cách hàng nghìn, số thập phân, ngày tháng, từ viết tắt). Xem
    lịch sử của structure.py -- đây chính là logic kiểm tra từng nằm ở đó,
    được chuyển sang đây vì việc phát hiện ranh giới câu nay thuộc trách
    nhiệm của 4a.

    Tham số:
        text: Toàn bộ văn bản đang xét.
        index: Vị trí (index) của dấu chấm cần kiểm tra trong ``text``.

    Trả về:
        ``True`` nếu dấu chấm tại ``index`` là dấu chấm "nội bộ" (không phải
        ranh giới câu), ``False`` nếu ngược lại.
    """

    if index <= 0:
        return False

    previous = text[index - 1]
    following = text[index + 1] if index + 1 < len(text) else ""
    if previous.isalnum() and following.isalnum():
        return True

    if previous.isdigit():
        next_non_space = index + 1
        while next_non_space < len(text) and text[next_non_space].isspace():
            next_non_space += 1
        if next_non_space < len(text) and text[next_non_space].isdigit():
            return True

    if index + 1 < len(text):
        abbreviation = _previous_dotted_word(text, index)
        next_non_space = index + 1
        while next_non_space < len(text) and text[next_non_space].isspace():
            next_non_space += 1
        if abbreviation in _PREFIX_ABBREVIATIONS and next_non_space < len(text):
            return True
        if abbreviation in _PERIOD_ABBREVIATIONS and next_non_space < len(text):
            continuation = text[next_non_space]
            if (
                continuation.islower()
                or continuation.isdigit()
                or continuation == ","
            ):
                return True
    return False


def _sentence_boundary_view(text: str) -> str:
    characters = list(text)
    for index, character in enumerate(characters):
        if character == "." and _period_is_internal(text, index):
            characters[index] = _NON_BOUNDARY_MARK
    return "".join(characters)


def _consume_whitespace(text: str, offset: int) -> int:
    while offset < len(text) and text[offset].isspace():
        offset += 1
    return offset


def _add(candidates: dict[int, dict[str, float]], pos: int, source: str, prior: float) -> None:
    bucket = candidates.setdefault(pos, {})
    bucket[source] = max(bucket.get(source, 0.0), prior)


def trimmed_end(text: str, start: int, end: int) -> int:
    """Trả về vị trí kết thúc phần nội dung (content end) cho một đoạn thô
    ``start:end``.

    Vị trí các candidate trỏ vào ký tự đầu tiên của atom tiếp theo, do đó
    khoảng trắng phân cách (separator whitespace) thuộc về đoạn thô bên
    trái, và cần được loại bỏ khỏi phạm vi nội dung có bằng chứng (evidence-
    backed content span) của đoạn đó. Các ràng buộc về độ dài phải được kiểm
    tra dựa trên phạm vi đã cắt bỏ khoảng trắng này -- việc tính luôn khoảng
    trắng phân cách chính là lý do khiến bản triển khai 4c đầu tiên có thể
    "khai" một atom dài 40 ký tự trong khi thực tế chỉ xuất ra 39 ký tự.

    Tham số:
        text: Văn bản gốc.
        start: Vị trí bắt đầu của đoạn thô.
        end: Vị trí kết thúc của đoạn thô (trước khi cắt khoảng trắng).

    Trả về:
        Vị trí kết thúc sau khi đã loại bỏ khoảng trắng ở cuối đoạn.
    """

    while end > start and text[end - 1].isspace():
        end -= 1
    return end


def generate_candidates(
    turn: SpeakerTurn,
    sources: frozenset[str],
    clause_adapter: ClauseBoundaryAdapter | None = None,
    item_spans: tuple[ItemSpan, ...] | None = None,
    item_boundary_prior: float = 0.3,
) -> tuple[Candidate, ...]:
    """4a: liệt kê mọi vị trí cắt hợp lệ trong ``text`` (toàn bộ một
    SpeakerTurn).

    Luôn bao gồm hai vị trí biên (sentinel) là ``0`` và ``len(text)``.
    Không bao giờ thay đổi ``text``; mọi vị trí trả về hoặc là sentinel,
    hoặc đã được "tiêu thụ" hết khoảng trắng phía trước (trỏ vào ký tự
    không phải khoảng trắng đầu tiên của atom tiếp theo), nhờ đó 4c không
    bao giờ cần thực hiện thêm một lượt cắt khoảng trắng nữa.

    Không còn lưới dự phòng (whitespace-grid fallback): nếu không nguồn nào
    ở trên cho đủ vị trí cắt an toàn, 4c (``pack_atoms``) sẽ tự giữ nguyên
    đoạn dài thay vì băm đại vào giữa một từ/cụm từ -- xem
    ``stage04_boundary/packing.py``.

    Tham số:
        turn: Lượt nói (SpeakerTurn) cần liệt kê vị trí cắt; văn bản gốc
            được lấy từ ``turn.text_exact``.
        sources: Tập hợp tên các nguồn phát hiện vị trí cắt cần bật, ví dụ
            ``"sentence_punct"``, ``"weak_punct"``, ``"discourse_marker"``,
            ``"item_boundary"``, ``"model"``. Chỉ những nguồn có mặt trong
            tập này mới được xét.
        clause_adapter: ``ClauseBoundaryAdapter`` tùy chọn -- một mô hình
            ngoài đề xuất thêm vị trí cắt kèm độ tin cậy; chỉ được dùng khi
            ``"model"`` có trong ``sources``.
        item_spans: Ranh giới ký tự (start, end) của từng ``EvidenceItem``
            gốc bên trong ``turn.text_exact`` -- ranh giới thật giữa các
            item này chính là điểm ngừng của người nói trong ASR gốc; chỉ
            được dùng khi ``"item_boundary"`` có trong ``sources``.
        item_boundary_prior: Giá trị prior gán cho mỗi vị trí ranh giới
            item (``AtomBuilderConfig.item_boundary_prior``).

    Trả về:
        Một tuple các ``Candidate``, sắp xếp theo vị trí tăng dần, đại diện
        cho toàn bộ tập vị trí cắt hợp lệ mà giai đoạn 4c được phép lựa
        chọn.
    """

    text = turn.text_exact
    n = len(text)
    candidates: dict[int, dict[str, float]] = {0: {"turn_edge": _TURN_EDGE_PRIOR}}
    if n > 0:
        candidates.setdefault(n, {})["turn_edge"] = _TURN_EDGE_PRIOR

    if n == 0:
        return (Candidate(pos=0, source="turn_edge", prior=_TURN_EDGE_PRIOR),)

    if "sentence_punct" in sources:
        view = _sentence_boundary_view(text)
        for match in _SENTENCE_END_RE.finditer(view):
            pos = _consume_whitespace(text, match.end())
            if 0 < pos < n:
                _add(candidates, pos, "sentence_punct", _SENTENCE_PUNCT_PRIOR)

    if "weak_punct" in sources:
        for match in _WEAK_PUNCT_RE.finditer(text):
            pos = _consume_whitespace(text, match.end())
            if 0 < pos < n:
                _add(candidates, pos, "weak_punct", _WEAK_PUNCT_PRIOR)

    if "item_boundary" in sources and item_spans:
        for span_start, _span_end in item_spans[1:]:
            pos = _consume_whitespace(text, span_start)
            if 0 < pos < n:
                _add(candidates, pos, "item_boundary", item_boundary_prior)

    if "discourse_marker" in sources:
        for match in _PUNCTUATED_DISCOURSE_MARKER_RE.finditer(text):
            prefix = text[: match.start()].rstrip()
            if prefix.endswith((",", ";", "-", "–", "—")):
                pos = match.start()
                if 0 < pos < n:
                    _add(candidates, pos, "discourse_marker", _DISCOURSE_MARKER_PRIOR)
        for match in _UNPUNCTUATED_DISCOURSE_MARKER_RE.finditer(text):
            pos = match.start()
            if 0 < pos < n:
                _add(candidates, pos, "discourse_marker", _DISCOURSE_MARKER_PRIOR)
        for match in _UNPUNCTUATED_WEAK_MARKER_RE.finditer(text):
            pos = match.start()
            if 0 < pos < n:
                _add(candidates, pos, "discourse_marker", _DISCOURSE_MARKER_WEAK_PRIOR)

    if "model" in sources and clause_adapter is not None:
        raw = clause_adapter.propose_boundaries(text)
        if not isinstance(raw, tuple):
            raise TypeError(
                "ClauseBoundaryAdapter.propose_boundaries() must return a tuple"
            )
        previous_raw_pos = -1
        for entry in raw:
            if (
                not isinstance(entry, tuple)
                or len(entry) != 2
                or isinstance(entry[0], bool)
                or not isinstance(entry[0], int)
            ):
                raise ValueError(
                    "boundary candidates must be (position, confidence) tuples"
                )
            raw_pos, confidence = entry
            if confidence is not None and (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0.0 <= float(confidence) <= 1.0
            ):
                raise ValueError("model boundary confidence must be between 0 and 1")
            if not 0 <= raw_pos <= n:
                raise ValueError("model boundary position must be inside text_exact")
            if raw_pos <= previous_raw_pos:
                raise ValueError(
                    "model boundary positions must be strictly increasing and unique"
                )
            previous_raw_pos = raw_pos
            pos = _consume_whitespace(text, raw_pos)
            if 0 < pos < n:
                prior = float(confidence) if confidence is not None else _DEFAULT_MODEL_PRIOR
                bucket = candidates.setdefault(pos, {})
                bucket["model"] = max(bucket.get("model", 0.0), prior)
    result: list[Candidate] = []
    for pos in sorted(candidates):
        bucket = candidates[pos]
        source = "+".join(sorted(bucket))
        prior = max(bucket.values())
        punct_prior = max((v for k, v in bucket.items() if k in _PUNCT_SOURCE_NAMES), default=0.0)
        discourse_prior = bucket.get("discourse_marker", 0.0)
        model_confidence = None
        if "model" in bucket:
            model_confidence = bucket["model"]
        result.append(
            Candidate(pos=pos, source=source, prior=prior, punct_prior=punct_prior, discourse_prior=discourse_prior,  model_confidence=model_confidence)
        )
    return tuple(result)
