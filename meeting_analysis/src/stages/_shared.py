"""Helpers shared by more than one stage module.

Only things genuinely used by several stages live here. Near-duplicates stay
where they are, because the differences are load-bearing:

- ``_normalized`` exists in three stages. Stages 11/12 and 15-19 fold with
  ``str.lower``; stage 10 folds with ``str.casefold``, which differs outside
  ASCII and is the correct choice there. They are not the same function and
  must not be merged.
- Stage 5 keeps its own word pattern. It preserves intra-word hyphens and
  apostrophes (``[^\\W_]+(?:[-'][^\\W_]+)*``) for entity and keyphrase
  extraction, where stages 6-8 want bare ``\\w+`` runs. Sharing one pattern
  would silently change both.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
import math
import re
import unicodedata

from ..utils.contracts import AnalysisAtom

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


def join_atoms(atoms: tuple[AnalysisAtom, ...]) -> str:
    """Exact atom text joined by newlines -- never re-wrapped or re-spaced,
    because every downstream offset is measured against this string."""

    return "\n".join(atom.text_exact for atom in atoms)


class LexicalCosineSimilarity:
    """Auditable offline fallback, explicitly not an MPNet replacement.

    Used by stage 6 (segmentation) and stage 8 (recurrence) so that both have
    the same deterministic behaviour when no embedding adapter is injected.
    """

    model_name = "lexical-cosine-fallback-v1"

    def similarity(self, left_text: str, right_text: str) -> float:
        left = Counter(word_tokens(left_text))
        right = Counter(word_tokens(right_text))
        if not left or not right:
            return 0.0
        numerator = sum(value * right.get(token, 0) for token, value in left.items())
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        return numerator / (left_norm * right_norm)


__all__ = [
    "LexicalCosineSimilarity",
    "SPACE_RE",
    "VN_STOPWORDS",
    "WORD_RE",
    "join_atoms",
    "known_max",
    "known_min",
    "word_tokens",
]
