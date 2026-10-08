"""Cue patterns for meeting-boundary signals (transition/enumeration/closing).

Kept in one module, versioned, so nothing hardcodes these patterns elsewhere
(plan.md §2.4). In administrative meetings the chair almost always signals an
agenda-item change with one of a small set of fixed phrases -- a stronger
boundary signal than any lexical/semantic similarity, which is exactly why
this module exists as a standalone, dependency-free feature source.

Deliberately no import from ``stages/`` (or anywhere else in this project):
this stays a leaf module usable by Stage 5, Stage 6, or a test in isolation,
with no risk of an ``utils`` -> ``stages`` -> ``utils`` import cycle.
"""

from __future__ import annotations

import re
import unicodedata

CUE_PATTERNS_VERSION = "v1"

_PREFIX_CHAR_LIMIT = 40

# Ordinal words used in "thứ <ordinal>" (1st..10th). Vietnamese grammar uses
# "tư", not "bốn", for the ordinal "fourth" -- see _CARDINAL_WORDS below for
# the (different) cardinal form used in "<cardinal> là".  Stops at "mười"
# (10th): administrative agendas rarely enumerate past ten items, and this
# is a heuristic feature, not an exhaustive parser.
_ORDINAL_WORDS = ("nhất", "hai", "ba", "tư", "năm", "sáu", "bảy", "tám", "chín", "mười")

# Cardinal words used in "<cardinal> là" (one is.., two is.., i.e. "firstly",
# "secondly", ...), 1..10, same stopping point as _ORDINAL_WORDS above.
_CARDINAL_WORDS = ("một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín", "mười")

_TRANSITION_LITERALS = (
    "tiếp theo",
    "chuyển sang",
    "sang nội dung",
    "về vấn đề",
    "về nội dung",
    "bây giờ",
    "tiếp đến",
)

# These two have a variable-length name/title between the anchor phrases
# ("mời đồng chí <ai đó> phát biểu" / "đề nghị đồng chí <ai đó> báo cáo") --
# bounded to a small character gap; the ~40-char prefix window this module
# always searches within is a much tighter bound in practice.
_TRANSITION_WILDCARD_PATTERNS = (
    r"\bmời\s+đồng\s+chí\b.{0,30}?\bphát\s+biểu\b",
    r"\bđề\s+nghị\s+đồng\s+chí\b.{0,30}?\bbáo\s+cáo\b",
)

_ENUMERATION_LITERALS = (
    *(f"thứ {word}" for word in _ORDINAL_WORDS),
    *(f"{word} là" for word in _CARDINAL_WORDS),
    "nội dung thứ",
    "vấn đề thứ",
)

_CLOSING_LITERALS = (
    "như vậy là",
    "tôi kết luận",
    "kết luận như sau",
    "thống nhất như sau",
    "tóm lại",
    "xin hết",
)


def _normalize_prefix(text: str, *, limit: int = _PREFIX_CHAR_LIMIT) -> str:
    """NFC + casefold, whitespace-collapsed, then cut to the first ``limit``
    characters -- cue matching only ever looks at the start of an atom, never
    scans the whole text (plan.md §2.4)."""

    normalized = " ".join(unicodedata.normalize("NFC", text).casefold().split())
    return normalized[:limit]


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Compile a literal multi-word cue phrase into a flexible-boundary regex.

    ``\\b`` on both ends accepts any punctuation (or nothing) immediately
    before/after the phrase -- "Thứ nhất," and "Thứ nhất:" both match --
    without requiring a specific trailing character. Internal whitespace is
    ``\\s+`` so multiple spaces still match; the input is already
    whitespace-collapsed by ``_normalize_prefix`` before this is applied.
    """

    escaped = r"\s+".join(re.escape(word) for word in phrase.split())
    return re.compile(rf"\b{escaped}\b")


_TRANSITION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    _phrase_pattern(phrase) for phrase in _TRANSITION_LITERALS
) + tuple(re.compile(pattern) for pattern in _TRANSITION_WILDCARD_PATTERNS)

_ENUMERATION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    _phrase_pattern(phrase) for phrase in _ENUMERATION_LITERALS
)

_CLOSING_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    _phrase_pattern(phrase) for phrase in _CLOSING_LITERALS
)


def _matches_any(patterns: tuple[re.Pattern[str], ...], prefix: str) -> bool:
    return any(pattern.search(prefix) for pattern in patterns)


def has_transition_cue(text: str) -> bool:
    """True when ``text`` opens with an agenda-transition phrase."""

    return _matches_any(_TRANSITION_PATTERNS, _normalize_prefix(text))


def has_enumeration_cue(text: str) -> bool:
    """True when ``text`` opens with an ordinal/cardinal enumeration phrase."""

    return _matches_any(_ENUMERATION_PATTERNS, _normalize_prefix(text))


def has_closing_cue(text: str) -> bool:
    """True when ``text`` opens with a meeting-closing/summary phrase."""

    return _matches_any(_CLOSING_PATTERNS, _normalize_prefix(text))


__all__ = [
    "CUE_PATTERNS_VERSION",
    "has_closing_cue",
    "has_enumeration_cue",
    "has_transition_cue",
]
