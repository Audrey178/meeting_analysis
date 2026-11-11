"""Chuyển hạn chót nói theo kiểu tự nhiên tiếng Việt thành một ngày cụ thể, lấy ngày họp làm mốc
(chỉ bằng luật).

Đây là cách tính hạn chính; chỉ khi luật không ra được ngày mới dùng ngày do mô hình tự tính. Hạn
được xếp vào một trong các loại:

  - ngày cụ thể: "ngày 15/11";
  - trước một ngày: "trước ngày 15 tháng 11", "chậm nhất thứ Sáu";
  - cuối một kỳ: "cuối tháng", "cuối quý", "quý IV", "cuối tuần";
  - tính từ ngày họp: "tuần sau", "tháng sau", "khoảng 3 tuần", "3 ngày tới";
  - không xác định: "sau POC", hoặc ngày không có thật.

Quy ước: tuần kết thúc vào Chủ nhật; "tháng sau" là ngày cuối tháng kế tiếp; thiếu năm thì lấy năm
của ngày họp, nếu mốc đó đã qua thì lấy năm sau; "A hoặc B" thì lấy mốc muộn hơn. Không biết ngày
họp thì chỉ tính được ngày khi câu nói tự đủ ngày, tháng, năm.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from ..shared.llm_output import read_stripped_text

DeadlineKind = Literal["exact", "before", "end_of_period", "relative", "unknown"]


@dataclass(frozen=True, slots=True)
class NormalizedDeadline:
    """Hạn chót đã chuẩn hoá: một ngày cụ thể (nếu quy được) và loại hạn.

    Attributes:
        deadline_date: Ngày ISO "YYYY-MM-DD". None nếu không quy được ra ngày.
        deadline_kind: "exact" (ngày cụ thể), "before" (trước một ngày), "end_of_period" (cuối một
            kỳ), "relative" (tính từ ngày họp) hoặc "unknown" (không xác định).
    """

    deadline_date: str | None
    deadline_kind: DeadlineKind


UNKNOWN_DEADLINE = NormalizedDeadline(None, "unknown")

_WEEKDAYS = {
    "hai": 0, "2": 0, "ba": 1, "3": 1, "tư": 2, "4": 2,
    "năm": 3, "5": 3, "sáu": 4, "6": 4, "bảy": 5, "7": 5,
}
_ROMAN_QUARTERS = {"i": 1, "ii": 2, "iii": 3, "iv": 4}

_SLASH_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[/-]\s*(\d{1,2})(?:\s*[/-]\s*(\d{4}|\d{2}))?(?!\d)")
_DOT_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")  # bắt buộc có năm, tránh "1.5 tỷ"
_WORD_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s+tháng\s+(\d{1,2})(?:\s+năm\s+(\d{4}))?")
_QUARTER_RE = re.compile(r"quý\s+(iv|iii|ii|i|[1-4])\b")
_MONTH_RE = re.compile(r"tháng\s+(1[0-2]|[1-9])\b")
_WEEKDAY_RE = re.compile(r"thứ\s+(hai|ba|tư|năm|sáu|bảy|[2-7])\b|(chủ nhật)")
_NUMBER_WORDS = {
    "một": 1, "hai": 2, "ba": 3, "bốn": 4, "tư": 4, "năm": 5,
    "sáu": 6, "bảy": 7, "tám": 8, "chín": 9, "mười": 10,
}
# "3 tuần", "khoảng 3 tuần", "trong 10 ngày tới", "hai tháng nữa": trong ô hạn chót, một
# khoảng thời gian trơn nghĩa là "trong vòng" khoảng đó kể từ ngày họp.
_COUNT_RE = re.compile(rf"(?<![\w/])(?<!thứ )(\d+|{'|'.join(_NUMBER_WORDS)})\s+(ngày|tuần|tháng)\b(?!\s+\d)")
# Cách nói khác của "tuần sau"/"tháng sau"... -> quy về một dạng trước khi áp luật.
_NEXT_ALIASES = (
    (re.compile(r"\bsang\s+(tuần|tháng|quý|năm)\b(?!\s+(?:sau|tới))"), r"\1 sau"),
    (re.compile(r"\b(tuần|tháng|quý|năm)\s+(?:tiếp theo|tiếp|kế tiếp|kế)\b"), r"\1 sau"),
)
_BEFORE_RE = re.compile(
    r"\b(?:trước|chậm nhất|muộn nhất|không quá|không muộn hơn|hạn chót|hạn cuối|đến hết|đến ngày|tới ngày|hạn)\b"
)
_EITHER_RE = re.compile(r"\s+(?:hoặc|hay là|hay)\s+")


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    """Kiểm tra ``text`` có chứa ít nhất một cụm trong ``phrases`` không."""

    return any(phrase in text for phrase in phrases)


def _safe_date(year: int, month: int, day: int) -> date | None:
    """Tạo ngày từ năm, tháng, ngày; trả về None nếu ngày không có thật (ví dụ 31/2)."""

    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_end(year: int, month: int) -> date:
    """Trả về ngày cuối cùng của tháng."""

    return date(year, month, calendar.monthrange(year, month)[1])


def _next_occurrence(build: Callable[[int], date | None], anchor: date) -> date | None:
    """Tính mốc thiếu năm: lấy năm của ngày họp, nếu mốc đã qua thì lấy năm sau.

    Args:
        build: Hàm nhận một năm, trả về ngày tương ứng hoặc None nếu ngày không có thật.
        anchor: Ngày họp.
    """

    current = build(anchor.year)
    if current is not None and current < anchor:
        return build(anchor.year + 1)
    return current


def _iso(value: date | None) -> str | None:
    """Đổi ngày sang dạng "YYYY-MM-DD"; None giữ nguyên là None."""

    return value.isoformat() if value else None


def _resolve_explicit_dates(text: str, anchor: date | None) -> NormalizedDeadline | None:
    """Áp luật ngày nêu rõ: "15/11", "15.11.2026", "15-11-2026", "ngày 15 tháng 11".

    Nhiều ngày (ví dụ "từ 10/11 đến 15/11") thì lấy ngày muộn nhất. Có từ như "trước", "chậm nhất" thì
    loại hạn là "before", ngược lại là "exact". Không biết ngày họp mà câu thiếu năm thì chỉ trả về loại
    hạn, không có ngày.

    Returns:
        Hạn đã chuẩn hoá; ``UNKNOWN_DEADLINE`` nếu mọi ngày tìm thấy đều không có thật; None nếu câu
        không nêu ngày nào, để luật sau thử tiếp.
    """

    matches = [*_SLASH_DATE_RE.finditer(text), *_DOT_DATE_RE.finditer(text), *_WORD_DATE_RE.finditer(text)]
    if not matches:
        return None
    resolved: list[date] = []
    has_valid_yearless = False
    for match in matches:
        day, month = int(match.group(1)), int(match.group(2))
        year = match.group(3)
        if year:
            value = _safe_date(int(year) + (2000 if len(year) == 2 else 0), month, day)
        elif anchor:
            value = _next_occurrence(lambda y: _safe_date(y, month, day), anchor)
        else:
            # 2024 là năm nhuận: chỉ để kiểm ngày/tháng hợp lệ, kể cả 29/2.
            has_valid_yearless |= _safe_date(2024, month, day) is not None
            continue
        if value:
            resolved.append(value)
    if not resolved and not has_valid_yearless:
        return UNKNOWN_DEADLINE
    kind: DeadlineKind = "before" if _BEFORE_RE.search(text) else "exact"
    return NormalizedDeadline(_iso(max(resolved)) if resolved else None, kind)


def _resolve_quarter(text: str, anchor: date | None) -> NormalizedDeadline | None:
    """Áp luật quý; trả về None nếu câu không nhắc tới quý.

    "quý IV"/"quý 4" là cuối quý đó (đã qua thì năm sau); "quý sau"/"quý tới" là cuối quý kế tiếp; mọi
    cách nói khác có chữ "quý" ("quý này", "cuối quý") là cuối quý chứa ngày họp.
    """

    def quarter_end(year: int, quarter: int) -> date:
        """Ngày cuối quý."""

        return _month_end(year, quarter * 3)

    match = _QUARTER_RE.search(text)
    if match:
        token = match.group(1)
        quarter = _ROMAN_QUARTERS.get(token) or int(token)
        value = _next_occurrence(lambda y: quarter_end(y, quarter), anchor) if anchor else None
        return NormalizedDeadline(_iso(value), "end_of_period")
    if "quý" not in text:
        return None
    current = (anchor.month - 1) // 3 + 1 if anchor else None
    if _has_any(text, ("quý sau", "quý tới")):
        value = None
        if anchor and current:
            year, quarter = (anchor.year + 1, 1) if current == 4 else (anchor.year, current + 1)
            value = quarter_end(year, quarter)
        return NormalizedDeadline(_iso(value), "end_of_period" if "cuối" in text else "relative")
    value = quarter_end(anchor.year, current) if anchor and current else None
    return NormalizedDeadline(_iso(value), "end_of_period")


def _resolve_month(text: str, anchor: date | None) -> NormalizedDeadline | None:
    """Áp luật tháng; trả về None nếu không khớp.

    "tháng 11" là cuối tháng 11 (đã qua thì năm sau); "tháng sau" là cuối tháng kế tiếp, riêng "đầu
    tháng sau"/"giữa tháng sau" là ngày 10/ngày 20 của tháng đó; "cuối tháng", "tháng này", "trong
    tháng" là cuối tháng họp.
    """

    match = _MONTH_RE.search(text)
    if match:
        month = int(match.group(1))
        value = _next_occurrence(lambda y: _month_end(y, month), anchor) if anchor else None
        return NormalizedDeadline(_iso(value), "end_of_period")
    if "tháng" not in text:
        return None
    kind: DeadlineKind = "end_of_period" if "cuối" in text else "relative"
    if _has_any(text, ("tháng sau", "tháng tới")):
        value = None
        if anchor:
            first_of_next = (anchor.replace(day=1) + timedelta(days=32)).replace(day=1)
            value = _month_end(first_of_next.year, first_of_next.month)
            # "đầu tháng" = hết thượng tuần (ngày 10), "giữa tháng" = hết trung tuần (ngày 20).
            if "đầu tháng" in text:
                value = first_of_next.replace(day=10)
            elif "giữa tháng" in text:
                value = first_of_next.replace(day=20)
        return NormalizedDeadline(_iso(value), kind)
    if _has_any(text, ("cuối tháng", "tháng này", "trong tháng")):
        return NormalizedDeadline(_iso(_month_end(anchor.year, anchor.month) if anchor else None), kind)
    return None


def _resolve_weekday(text: str, anchor: date | None) -> NormalizedDeadline | None:
    """Áp luật thứ trong tuần; trả về None nếu câu không nêu thứ.

    "thứ Sáu", "chủ nhật" là ngày đó trong tuần họp, đã qua thì sang tuần kế; có "tuần sau"/"tuần tới"
    thì lấy trong tuần kế. Có từ như "trước", "chậm nhất" thì loại hạn là "before".
    """

    match = _WEEKDAY_RE.search(text)
    if not match:
        return None
    kind: DeadlineKind = "before" if _BEFORE_RE.search(text) else "relative"
    if not anchor:
        return NormalizedDeadline(None, kind)
    weekday = 6 if match.group(2) else _WEEKDAYS[match.group(1)]
    monday = anchor - timedelta(days=anchor.weekday())
    next_week = _has_any(text, ("tuần sau", "tuần tới"))
    target = monday + timedelta(days=weekday + (7 if next_week else 0))
    if not next_week and "tuần này" not in text and target < anchor:
        target += timedelta(days=7)  # "thứ Hai" trơn đã qua -> lần tới gần nhất
    return NormalizedDeadline(target.isoformat(), kind)


def _add_months(anchor: date, months: int) -> date:
    """Cộng ``months`` tháng vào ``anchor``; ngày vượt quá tháng đích thì lấy ngày cuối tháng đó."""

    month_index = anchor.month - 1 + months
    year, month = anchor.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def _resolve_count(text: str, anchor: date | None) -> NormalizedDeadline | None:
    """Áp luật khoảng thời gian; trả về None nếu không khớp.

    "3 tuần", "hai tháng nữa", "10 ngày tới" là ngày họp cộng thêm khoảng đó.
    """

    match = _COUNT_RE.search(text)
    if not match:
        return None
    token, unit = match.group(1), match.group(2)
    amount = int(token) if token.isdigit() else _NUMBER_WORDS[token]
    if not anchor:
        return NormalizedDeadline(None, "relative")
    if unit == "tháng":
        value = _add_months(anchor, amount)
    else:
        value = anchor + timedelta(days=amount * (7 if unit == "tuần" else 1))
    return NormalizedDeadline(value.isoformat(), "relative")


def _resolve_week(text: str, anchor: date | None) -> NormalizedDeadline | None:
    """Áp luật tuần; trả về None nếu không khớp.

    "tuần này", "trong tuần", "cuối tuần" là Chủ nhật của tuần họp; có "tuần sau"/"tuần tới" thì sang
    tuần kế. "đầu tuần" là thứ Hai, "giữa tuần" là thứ Tư; mốc đã qua thì sang tuần kế.
    """

    if "tuần" not in text:
        return None
    kind: DeadlineKind = "end_of_period" if "cuối tuần" in text else "relative"
    offset = 7 if _has_any(text, ("tuần sau", "tuần tới")) else 0
    if not offset and not _has_any(text, ("tuần này", "trong tuần", "cuối tuần", "đầu tuần", "giữa tuần")):
        return None
    if not anchor:
        return NormalizedDeadline(None, kind)
    # Mặc định cuối tuần (Chủ nhật); "đầu tuần" = thứ Hai, "giữa tuần" = thứ Tư.
    weekday = 0 if "đầu tuần" in text else 2 if "giữa tuần" in text else 6
    target = anchor - timedelta(days=anchor.weekday()) + timedelta(days=weekday + offset)
    if target < anchor:
        target += timedelta(days=7)  # "đầu tuần" trơn đã qua -> tuần kế
    return NormalizedDeadline(target.isoformat(), kind)


def _resolve_year(text: str, anchor: date | None) -> NormalizedDeadline | None:
    """Áp luật năm: "năm sau" là 31/12 năm kế; "cuối năm", "năm nay", "trong năm" là 31/12 năm họp."""

    if _has_any(text, ("năm sau", "năm tới")):
        return NormalizedDeadline(_iso(date(anchor.year + 1, 12, 31) if anchor else None), "relative")
    if _has_any(text, ("cuối năm", "năm nay", "trong năm")):
        kind: DeadlineKind = "end_of_period" if "cuối năm" in text else "relative"
        return NormalizedDeadline(_iso(date(anchor.year, 12, 31) if anchor else None), kind)
    return None


def _resolve_day_word(text: str, anchor: date | None) -> NormalizedDeadline | None:
    """Áp luật ngày: "hôm nay", "ngày mai", "ngày kia" là ngày họp cộng 0, 1, 2 ngày."""

    for phrase, days in (("hôm nay", 0), ("ngày mai", 1), ("ngày kia", 2)):
        if phrase in text:
            return NormalizedDeadline(_iso(anchor + timedelta(days=days) if anchor else None), "relative")
    return None


# Thứ tự quan trọng: ngày cụ thể trước mọi kỳ; "thứ năm" phải bắt trước luật năm.
_RESOLVERS = (
    _resolve_explicit_dates,
    _resolve_count,  # trước luật tháng: "3 tháng tới" là khoảng, không phải "tháng tới"
    _resolve_quarter,
    _resolve_month,
    _resolve_weekday,
    _resolve_week,
    _resolve_year,
    _resolve_day_word,
)


def _normalize_one(text: str, anchor: date | None) -> NormalizedDeadline:
    """Áp lần lượt các luật lên một phương án hạn (đã tách khỏi "A hoặc B"); luật khớp đầu tiên thắng."""

    for resolve in _RESOLVERS:
        result = resolve(text, anchor)
        if result is not None:
            return result
    return UNKNOWN_DEADLINE


def normalize_deadline(raw: str | None, meeting_date: str | None) -> NormalizedDeadline:
    """Chuẩn hoá một hạn chót nguyên văn chỉ bằng luật, lấy ngày họp làm mốc.

    Câu được viết thường, gom khoảng trắng, và các cách nói như "sang tuần", "tháng tiếp theo" được đưa
    về "tuần sau", "tháng sau". Câu dạng "A hoặc B" được tính từng phương án rồi lấy ngày muộn hơn;
    không phương án nào ra ngày thì lấy loại hạn của phương án đầu tiên nhận ra được.

    Args:
        raw: Hạn chót nguyên văn trong lời nói, ví dụ "chậm nhất thứ Sáu tuần sau". None hoặc rỗng
            thì trả về ``UNKNOWN_DEADLINE``.
        meeting_date: Ngày họp ISO "YYYY-MM-DD". None nếu không biết; khi đó chỉ ra được ngày khi câu
            nêu đủ ngày, tháng, năm.

    Returns:
        Hạn đã chuẩn hoá; ``UNKNOWN_DEADLINE`` nếu không luật nào khớp.

    Raises:
        ValueError: Khi ``meeting_date`` không phải ngày ISO hợp lệ.
    """

    if not raw:
        return UNKNOWN_DEADLINE
    anchor = date.fromisoformat(meeting_date) if meeting_date else None
    text = " ".join(raw.lower().split()).strip(" .,;:")
    for pattern, replacement in _NEXT_ALIASES:
        text = pattern.sub(replacement, text)
    options = [_normalize_one(part, anchor) for part in _EITHER_RE.split(text) if part]
    dated = [option for option in options if option.deadline_date]
    if dated:
        return max(dated, key=lambda option: option.deadline_date)
    return next((option for option in options if option.deadline_kind != "unknown"), UNKNOWN_DEADLINE)


# ---------------------------------------------------------------------------
# Dùng ở Action agent (việc giao và tiến độ)
# ---------------------------------------------------------------------------

_DEADLINE_KINDS = frozenset({"exact", "before", "end_of_period", "relative", "unknown"})
_WEEKDAY_NAMES = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")


def format_meeting_date(meeting_date: str | None) -> str:
    """Trình bày ngày họp kèm thứ cho prompt.

    Ví dụ "2026-10-08" thành "2026-10-08 (thứ Năm)". None hoặc sai định dạng thành "(unknown)".
    Tên thứ giữ tiếng Việt để khớp cách bản ghi nói hạn ("thứ Sáu tuần sau").
    """

    try:
        parsed = date.fromisoformat(meeting_date) if meeting_date else None
    except ValueError:
        parsed = None
    return f"{parsed.isoformat()} ({_WEEKDAY_NAMES[parsed.weekday()]})" if parsed else "(unknown)"


def resolve_deadline(item: dict, deadline_raw: str | None, meeting_date: str | None) -> NormalizedDeadline:
    """Chọn hạn chót cuối cùng cho một việc giao hoặc một cập nhật tiến độ.

    Ưu tiên ngày do luật tính, vì luật tính lịch chính xác còn mô hình hay lệch ngày dù đúng định dạng.
    Chỉ khi luật không ra ngày (ví dụ "trước Tết") mới dùng ngày và loại hạn mô hình tự quy, nếu chúng
    hợp lệ; mô hình ghi "unknown" mà luật vẫn nhận ra loại hạn thì giữ kết quả của luật.

    Args:
        item: Mục mô hình trả về; đọc các trường ``deadline_date`` và ``deadline_kind``.
        deadline_raw: Hạn chót nguyên văn đã làm sạch. None hoặc rỗng thì luôn là ``UNKNOWN_DEADLINE``.
        meeting_date: Ngày họp ISO "YYYY-MM-DD". None nếu không biết.

    Returns:
        Hạn đã chuẩn hoá.

    Raises:
        ValueError: Khi ``meeting_date`` không phải ngày ISO hợp lệ.
    """

    if not deadline_raw:
        return UNKNOWN_DEADLINE
    fallback = normalize_deadline(deadline_raw, meeting_date)
    if fallback.deadline_date:
        return fallback
    kind = item.get("deadline_kind")
    raw_date = read_stripped_text(item.get("deadline_date"))
    try:
        llm_date = date.fromisoformat(raw_date).isoformat() if raw_date else None
    except ValueError:
        llm_date = None
    if kind not in _DEADLINE_KINDS or (raw_date and llm_date is None):
        return fallback
    if kind == "unknown" and fallback.deadline_kind != "unknown":
        return fallback
    return NormalizedDeadline(llm_date, kind)


__all__ = [
    "DeadlineKind",
    "NormalizedDeadline",
    "UNKNOWN_DEADLINE",
    "format_meeting_date",
    "normalize_deadline",
    "resolve_deadline",
]
