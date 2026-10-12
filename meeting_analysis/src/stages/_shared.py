"""Helpers shared by more than one stage module (stage03 timestamps, stage07 words)."""

from __future__ import annotations

from collections.abc import Iterable
import re
import unicodedata

SPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"\w+", re.UNICODE)

# Vietnamese function-word stoplist, shared by Stage 7 (title-blacklist
# subset check) and formerly duplicated verbatim in Stage 8 (dead code,
# removed -- TIP-008, plan_stage_7_8.md §2.5). One list, one place.
VN_STOPWORDS = frozenset(
    {
        "và", "là", "của", "có", "không", "được", "cho", "này", "đó", "các",
        "một", "những", "để", "với", "trong", "về", "đã", "sẽ", "thì", "mà",
        "nhưng", "cũng", "khi", "nếu", "như", "hay", "hoặc", "tại", "theo",
        "từ", "đến", "sau", "trước", "vì", "nên", "rằng", "vẫn", "còn", "lại",
    }
)


def known_min(values: Iterable[int | None]) -> int | None:
    """Smallest non-``None`` value, or ``None`` when every value is unknown.

    Timestamps are optional throughout the contracts, so a turn or atom may
    legitimately have no bound at all; that is different from a bound of 0.
    """

    known = [value for value in values if value is not None]
    return min(known) if known else None


def known_max(values: Iterable[int | None]) -> int | None:
    """Largest non-``None`` value, or ``None`` when every value is unknown."""

    known = [value for value in values if value is not None]
    return max(known) if known else None


def word_tokens(text: str) -> tuple[str, ...]:
    """Lowercased ``\\w+`` runs, NFC-normalised first so that the same
    Vietnamese word written with composed and decomposed diacritics compares
    equal."""

    return tuple(WORD_RE.findall(unicodedata.normalize("NFC", text).lower()))


__all__ = [
    "SPACE_RE",
    "VN_STOPWORDS",
    "WORD_RE",
    "known_max",
    "known_min",
    "word_tokens",
]
