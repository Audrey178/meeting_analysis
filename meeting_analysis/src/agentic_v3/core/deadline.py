"""Chuẩn hoá hạn chót nói tự nhiên tiếng Việt về ngày ISO, neo theo ngày họp (luật, 0 token).

Action Agent tự quy hạn theo QUY TẮC CHUẨN HOÁ HẠN trong prompt (cùng các quy ước dưới đây);
module này là LUẬT DỰ PHÒNG khi LLM trả ngày sai định dạng hoặc bỏ trống: quy hạn nguyên văn
(``deadline_raw``, vd. "trước ngày 15 tháng 11") về ``deadline_date`` ("2026-11-15") và ``deadline_kind``:

- ``exact``: ngày cụ thể ("ngày 15/11", "15-11-2026").
- ``before``: hạn chót tới một ngày cụ thể ("trước ngày 15 tháng 11", "chậm nhất thứ Sáu").
- ``end_of_period``: cuối một kỳ nêu rõ ("cuối tháng", "cuối quý", "quý IV", "cuối tuần").
- ``relative``: tính lệch từ ngày họp ("tuần sau", "sang tuần", "tháng sau", "trong tuần này",
  "khoảng 3 tuần", "3 ngày tới").
- ``unknown``: không quy được ("sau POC", "31/2"); khi đó ``deadline_date`` là None.

Quy ước mặc định: tuần kết thúc Chủ nhật ("tuần sau" = Chủ nhật tuần kế), "tháng sau" =
ngày cuối tháng kế. Thiếu năm thì lấy năm của ngày họp; mốc đó đã qua so với ngày họp
thì lấy năm sau. Không có ngày họp thì vẫn trả ``deadline_kind`` nhưng chỉ có
``deadline_date`` khi chuỗi tự đủ ngày/tháng/năm. "A hoặc B" lấy mốc muộn hơn.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

DeadlineKind = Literal["exact", "before", "end_of_period", "relative", "unknown"]


@dataclass(frozen=True, slots=True)
class NormalizedDeadline:
    """Hạn chót đã chuẩn hoá.

    Các trường:
        deadline_date: ngày ISO "YYYY-MM-DD", None nếu không quy được.
        deadline_kind: loại hạn (xem docstring module).
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

_NEXT = ("sau", "tới")


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _next_occurrence(build: Callable[[int], date | None], anchor: date) -> date | None:
    """Mốc thiếu năm: lấy năm của ngày họp, đã qua thì lấy năm sau."""

    current = build(anchor.year)
    if current is not None and current < anchor:
        return build(anchor.year + 1)
    return current


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _resolve_explicit_dates(text: str, anchor: date | None) -> NormalizedDeadline | None:
    """Ngày nêu rõ ngày/tháng ("15/11", "15-11-2026", "ngày 15 tháng 11"); None nếu không có.

    Nhiều ngày (khoảng "từ 10/11 đến 15/11") thì lấy ngày muộn nhất.
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
    def quarter_end(year: int, quarter: int) -> date:
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
    month_index = anchor.month - 1 + months
    year, month = anchor.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(anchor.day, calendar.monthrange(year, month)[1]))


def _resolve_count(text: str, anchor: date | None) -> NormalizedDeadline | None:
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
    if _has_any(text, ("năm sau", "năm tới")):
        return NormalizedDeadline(_iso(date(anchor.year + 1, 12, 31) if anchor else None), "relative")
    if _has_any(text, ("cuối năm", "năm nay", "trong năm")):
        kind: DeadlineKind = "end_of_period" if "cuối năm" in text else "relative"
        return NormalizedDeadline(_iso(date(anchor.year, 12, 31) if anchor else None), kind)
    return None


def _resolve_day_word(text: str, anchor: date | None) -> NormalizedDeadline | None:
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
    for resolve in _RESOLVERS:
        result = resolve(text, anchor)
        if result is not None:
            return result
    return UNKNOWN_DEADLINE


def normalize_deadline(raw: str | None, meeting_date: str | None) -> NormalizedDeadline:
    """Chuẩn hoá một hạn chót nguyên văn theo luật; không khớp mẫu nào thì ``unknown``.

    Đầu vào:
        raw: hạn nguyên văn theo bản ghi (có thể None).
        meeting_date: ngày họp ISO "YYYY-MM-DD" (có thể None).
    Đầu ra: NormalizedDeadline.
    Lỗi: ValueError nếu ``meeting_date`` không phải ngày ISO hợp lệ.
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


__all__ = ["DeadlineKind", "NormalizedDeadline", "UNKNOWN_DEADLINE", "normalize_deadline"]
