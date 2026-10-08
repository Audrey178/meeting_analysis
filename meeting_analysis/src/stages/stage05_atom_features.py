"""Stage 5: deterministic representations for locked analysis atoms.

Features produced here are metadata, never evidence.  In particular, this
module neither edits ``AnalysisAtom.text_exact`` nor changes atom boundaries.
Dense vectors remain in the shared in-memory embedding cache; the serializable
artifact contains only a model identifier, dimension, and content-addressed
reference.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
import bisect
import math
import re
import unicodedata

from ..utils.config import FeatureBuilderConfig
from ..utils.contracts import (
    AnalysisAtom,
    AtomFeatures,
    AtomMeta,
    CueFlags,
    EntityMention,
    LexicalStats,
)
from ..utils.cues import has_closing_cue, has_enumeration_cue, has_transition_cue
from ..utils.embeddings import EmbeddingCache, content_ref
from ..utils.ports import EmbeddingAdapter


_WORD_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])",
    re.UNICODE,
)
_URL_RE = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s<>()\[\]{}\"']*"
    r"[^\s<>()\[\]{}\"',.!?;:]"
)
_DATE_RE = re.compile(
    r"(?<!\d)(?:0?[1-9]|[12]\d|3[01])[/.-]"
    r"(?:0?[1-9]|1[0-2])[/.-](?:\d{2}|\d{4})(?!\d)"
)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[ .-]*\d){8,10}(?!\d)")
_MONEY_RE = re.compile(
    # "đồng" is excluded when followed by "chí" ("đồng chí" = comrade, an
    # address before a PERSON name, not a currency unit) -- TIP-001 fix (b).
    # The other currency spellings never carry that ambiguity.
    r"(?<!\w)\d+(?:[.,]\d+)*(?:\s*)(?:₫|đồng(?!\s*chí\b)|VNĐ|VND|USD)(?!\w)",
    re.IGNORECASE,
)
_ACRONYM_RE = re.compile(r"(?<!\w)[A-ZĐ]{2,}(?:[.-][A-ZĐ]{2,})*(?!\w)")

_CAPITAL_WORD = r"[A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠ-Ỹ][^\W\d_]*"
_PERSON_RE = re.compile(
    # The honorific itself ("đồng chí", "tiến sĩ", ...) is matched
    # case-insensitively via a scoped inline flag -- mid-sentence Vietnamese
    # normally lowercases it (see the TIP-001 regression case: "... 5 đồng
    # chí Nguyễn Văn A"). _CAPITAL_WORD is deliberately left outside that
    # scope: the name itself must still be genuinely capitalized, or this
    # would match ordinary lowercase words as a "person".
    rf"(?<!\w)(?i:Ông|Bà|Đồng\s+chí|Tiến\s+sĩ|Thạc\s+sĩ|TS\.?|PGS\.?\s*TS\.?)"
    rf"\s+{_CAPITAL_WORD}(?:\s+{_CAPITAL_WORD}){{1,4}}",
    re.UNICODE,
)
_ORG_PREFIX_RE = re.compile(
    r"(?<!\w)(?:Ủy ban(?:\s+Nhân dân)?|Đảng ủy|Công ty(?:\s+Cổ phần|\s+TNHH)?|"
    r"Tập đoàn|Bộ|Sở|Ban|Phòng|Viện|Trường|UBND|HĐND|MTTQ)(?!\w)"
)

# These words normally begin the predicate following an organisation name.
# They keep the deliberately lightweight organisation rule from swallowing a
# whole clause.  Dictionary matches take precedence whenever available.
_ORG_TAIL_BREAKS = frozenset(
    {
        "báo",
        "cần",
        "chịu",
        "chỉ",
        "cho",
        "đã",
        "đang",
        "đề",
        "giao",
        "khẩn",
        "phải",
        "phối",
        "rà",
        "sẽ",
        "thực",
        "và",
        "về",
        "yêu",
    }
)

# A compact Vietnamese/English stop-list is enough for the RAKE-lite fallback.
# It deliberately avoids domain nouns so project-specific phrases survive.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "và",
        "hoặc",
        "của",
        "cho",
        "với",
        "từ",
        "trong",
        "ngoài",
        "trên",
        "dưới",
        "tại",
        "về",
        "là",
        "có",
        "được",
        "bị",
        "đã",
        "đang",
        "sẽ",
        "này",
        "đó",
        "các",
        "những",
        "một",
        "thì",
        "mà",
        "như",
        "để",
        "do",
        "vì",
        "nên",
        "cũng",
        "rất",
    }
)

_SCORE_DIGITS = 12

# LexicalStats.tokenizer_id per channel (TIP-002 §2.3/§2.5) -- version tags,
# bumped whenever the tokenization rule for that channel changes.
_SYLLABLE_TOKENIZER_ID = "syl-uni-bi-v1"
_CHAR_TOKENIZER_ID = "char-3-5gram-v1"


@dataclass(frozen=True, slots=True)
class _EntityCandidate:
    start: int
    end: int
    entity_type: str
    canonical: str | None
    priority: int


def _normalized_text(text: str) -> str:
    """NFC/casefold text for lexical features, never for source offsets."""

    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _words(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _WORD_RE.finditer(_normalized_text(text)))


def _syllable_terms(text: str, *, use_bigrams: bool = True) -> Counter[str]:
    """Unigram + bigram âm tiết liền kề. Bigram nối bằng '_'.

    Bigrams never cross an atom boundary: ``_words`` already operates on one
    atom's ``text_exact``, so the zip below only ever pairs syllables within
    that single atom.
    """

    syllables = _words(text)
    terms: Counter[str] = Counter(syllables)
    if use_bigrams:
        terms.update(f"{left}_{right}" for left, right in zip(syllables, syllables[1:]))
    return terms


def _char_ngrams(text: str, ngram_range: range = range(3, 6)) -> Counter[str]:
    normalized = _normalized_text(text)
    grams: Counter[str] = Counter()
    for size in ngram_range:
        for start in range(max(0, len(normalized) - size + 1)):
            gram = normalized[start : start + size]
            if any(character.isalnum() for character in gram):
                grams[gram] += 1
    return grams


def _bm25_weights(
    documents: tuple[Counter[str], ...],
    *,
    tokenizer_id: str,
    k1: float,
    b: float,
) -> tuple[tuple[dict[str, float], LexicalStats], ...]:
    """Trả về trọng số ĐẦY ĐỦ cho mọi term. Không cắt.

    `df` tính trong phạm vi một cuộc họp là chủ ý, không phải thiếu sót. Nó
    làm nổi các từ đặc trưng theo mục nghị sự -- đúng cái Stage 6 cần. Trọng
    số ở đây không so sánh được giữa các cuộc họp; nếu cần retrieval
    cross-document, tính một bộ trọng số riêng với df đóng băng từ corpus
    tham chiếu.

    Cutting to top-k is `_top_k`'s job, applied by the caller only when
    serializing onto ``AtomFeatures``. Keyphrase scoring (``_keyphrases``)
    uses this full table directly (TIP-001 fix (a)): scoring against a
    top-k-cut table assigns a false weight of 0 to every term outside the
    cut, which both under-scores real candidates built from those terms and
    lets zero-score candidates survive when too few positive-score
    candidates exist to fill top_k.
    """

    document_count = len(documents)
    if document_count == 0:
        return ()
    document_frequency: Counter[str] = Counter()
    lengths = tuple(sum(document.values()) for document in documents)
    for document in documents:
        document_frequency.update(document.keys())
    average_length = (sum(lengths) / document_count) or 1.0
    stats = LexicalStats(
        tokenizer_id=tokenizer_id,
        doc_count=document_count,
        avg_length=average_length,
        k1=k1,
        b=b,
    )

    results: list[tuple[dict[str, float], LexicalStats]] = []
    for document, length in zip(documents, lengths, strict=True):
        document_weights: dict[str, float] = {}
        for term, frequency in document.items():
            frequency_in_documents = document_frequency[term]
            inverse_document_frequency = math.log(
                1.0
                + (document_count - frequency_in_documents + 0.5)
                / (frequency_in_documents + 0.5)
            )
            denominator = frequency + k1 * (1.0 - b + b * length / average_length)
            document_weights[term] = inverse_document_frequency * (
                frequency * (k1 + 1.0) / denominator
            )
        results.append((document_weights, stats))
    return tuple(results)


def _top_k(weights: dict[str, float], top_k: int) -> tuple[tuple[str, float], ...]:
    ordered = sorted(weights.items(), key=lambda item: (-item[1], item[0]))[:top_k]
    return tuple((term, round(score, _SCORE_DIGITS)) for term, score in ordered)


def _dictionary_entries(
    entity_aliases: Mapping[str, object] | None,
) -> tuple[tuple[str, str], ...]:
    if entity_aliases is None:
        return ()
    # Accept both a flat alias map and the JSON file's decoded
    # ``{"aliases": {...}}`` shape, which keeps the public API convenient.
    nested = entity_aliases.get("aliases")
    aliases: Mapping[object, object]
    if isinstance(nested, Mapping):
        aliases = nested
    else:
        aliases = entity_aliases

    deduplicated: dict[str, tuple[str, str]] = {}
    for raw_alias, raw_canonical in aliases.items():
        if not isinstance(raw_alias, str) or not raw_alias.strip():
            raise ValueError("entity alias keys must be non-empty strings")
        if not isinstance(raw_canonical, str) or not raw_canonical.strip():
            raise ValueError("entity canonical names must be non-empty strings")
        alias = raw_alias.strip()
        canonical = raw_canonical.strip()
        folded = alias.casefold()
        previous = deduplicated.get(folded)
        if previous is not None and previous[1] != canonical:
            raise ValueError(f"conflicting canonical names for entity alias {alias!r}")
        deduplicated[folded] = (alias, canonical)
        # A canonical spelling is itself a dictionary entity/link target.
        deduplicated.setdefault(canonical.casefold(), (canonical, canonical))
    return tuple(
        sorted(
            deduplicated.values(),
            key=lambda item: (-len(item[0]), item[0].casefold()),
        )
    )


def _infer_entity_type(text: str) -> str:
    folded = text.casefold()
    if any(
        marker in folded
        for marker in (
            "ủy ban",
            "ubnd",
            "hđnd",
            "mttq",
            "đảng ủy",
            "công ty",
            "tập đoàn",
            "bộ ",
            "sở ",
            "ban ",
            "phòng ",
            "viện ",
            "trường ",
        )
    ):
        return "ORG"
    if re.match(r"(?i)^(?:ông|bà|đồng chí|tiến sĩ|thạc sĩ|ts\.?|pgs\.?)\b", text):
        return "PERSON"
    return "ENTITY"


def _dictionary_candidates(
    text: str, entries: tuple[tuple[str, str], ...]
) -> list[_EntityCandidate]:
    candidates: list[_EntityCandidate] = []
    for alias, canonical in entries:
        prefix = r"(?<!\w)" if alias[0].isalnum() else ""
        suffix = r"(?!\w)" if alias[-1].isalnum() else ""
        pattern = re.compile(prefix + re.escape(alias) + suffix, re.IGNORECASE)
        for match in pattern.finditer(text):
            candidates.append(
                _EntityCandidate(
                    match.start(),
                    match.end(),
                    _infer_entity_type(canonical),
                    canonical,
                    100,
                )
            )
    return candidates


def _organization_candidates(text: str) -> list[_EntityCandidate]:
    candidates: list[_EntityCandidate] = []
    words = tuple(_WORD_RE.finditer(text))
    starts = [word_match.start() for word_match in words]
    for prefix in _ORG_PREFIX_RE.finditer(text):
        end = prefix.end()
        tail_count = 0
        # Jump straight to the first word at/after prefix.end() instead of
        # rescanning every earlier word for each prefix -- TIP-001 fix (c),
        # O(n^2) -> O(n log n) overall.
        index = bisect.bisect_left(starts, prefix.end())
        for word_match in words[index:]:
            between = text[end : word_match.start()]
            if tail_count >= 6 or not between.isspace():
                break
            word = word_match.group(0)
            if word.casefold() in _ORG_TAIL_BREAKS:
                break
            # From the second tail word onward the tail must stay capitalized
            # (TIP-001 fix (c)): otherwise an ordinary lowercase predicate
            # ("phát biểu") gets swallowed into the span. _ORG_TAIL_BREAKS
            # remains a second line of defence for predicate words not
            # covered by this rule (e.g. the very first tail word).
            if tail_count >= 1 and not re.fullmatch(_CAPITAL_WORD, word):
                break
            end = word_match.end()
            tail_count += 1
        # Acronym prefixes are useful entities by themselves; lexical prefixes
        # such as "Ban" require a name tail to avoid ordinary-noun false hits.
        prefix_text = prefix.group(0)
        if tail_count or prefix_text.isupper():
            candidates.append(_EntityCandidate(prefix.start(), end, "ORG", None, 50))
    return candidates


def _regex_candidates(text: str) -> list[_EntityCandidate]:
    candidates: list[_EntityCandidate] = []
    patterns = (
        (_EMAIL_RE, "EMAIL", 80),
        (_URL_RE, "URL", 80),
        (_PHONE_RE, "PHONE", 70),
        (_DATE_RE, "DATE", 60),
        (_MONEY_RE, "MONEY", 60),
        (_PERSON_RE, "PERSON", 55),
        (_ACRONYM_RE, "ORG", 45),
    )
    for pattern, entity_type, priority in patterns:
        candidates.extend(
            _EntityCandidate(match.start(), match.end(), entity_type, None, priority)
            for match in pattern.finditer(text)
        )
    candidates.extend(_organization_candidates(text))
    return candidates


def extract_entities(
    text: str,
    entity_aliases: Mapping[str, object] | None = None,
) -> tuple[EntityMention, ...]:
    """Extract non-overlapping, exact-span regex/dictionary entities.

    Dictionary aliases win over heuristic regexes, and longer matches win at
    the same position.  Canonicalization never rewrites the source text.
    """

    entries = _dictionary_entries(entity_aliases)
    candidates = _dictionary_candidates(text, entries) + _regex_candidates(text)
    candidates.sort(
        key=lambda candidate: (
            -candidate.priority,
            candidate.start,
            -(candidate.end - candidate.start),
            candidate.entity_type,
        )
    )

    accepted: list[_EntityCandidate] = []
    for candidate in candidates:
        if candidate.start == candidate.end:
            continue
        if any(
            candidate.start < existing.end and existing.start < candidate.end
            for existing in accepted
        ):
            continue
        accepted.append(candidate)
    accepted.sort(key=lambda candidate: (candidate.start, candidate.end))
    return tuple(
        EntityMention(
            text=text[candidate.start : candidate.end],
            start_char=candidate.start,
            end_char=candidate.end,
            entity_type=candidate.entity_type,
            canonical=candidate.canonical,
        )
        for candidate in accepted
    )


def _keyphrases(
    words: tuple[str, ...],
    weights: Mapping[str, float],
    top_k: int,
) -> tuple[str, ...]:
    """Score 1-3 word phrase candidates against a FULL (uncut) weight table.

    ``weights`` must be the atom's full-support syllable BM25 weights (see
    ``_bm25_weights``), never a top-k-cut table -- TIP-001 fix (a).
    """

    if not words:
        return ()
    candidates: dict[str, float] = {}
    # RAKE-lite: stopwords delimit phrases; score all 1-3 word windows inside
    # each content run with a small length gain.  This works without a
    # Vietnamese word segmenter while remaining deterministic/offline.
    run: list[str] = []

    def score_run() -> None:
        for start in range(len(run)):
            for size in range(1, min(3, len(run) - start) + 1):
                terms = run[start : start + size]
                phrase = " ".join(terms)
                score = sum(weights.get(term, 0.0) for term in terms) * (
                    1.0 + 0.15 * (size - 1)
                )
                if score <= 0.0:
                    # A zero (or, degenerately, negative) score means every
                    # term in this window is absent from the atom's own
                    # weight table -- never a real candidate, and must not
                    # survive to pad out top_k (TIP-001 fix (a)).
                    continue
                candidates[phrase] = max(candidates.get(phrase, 0.0), score)

    for word in words:
        if word in _STOPWORDS:
            score_run()
            run = []
        else:
            run.append(word)
    score_run()

    ordered = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))
    selected: list[str] = []
    for phrase, _score in ordered:
        phrase_terms = tuple(phrase.split())
        # Avoid filling top-k entirely with nested variants of one phrase.
        if any(_phrase_is_inside(phrase_terms, existing) for existing in selected):
            continue
        selected.append(phrase)
        if len(selected) == top_k:
            break
    return tuple(selected)


def _phrase_is_inside(phrase_terms: tuple[str, ...], existing: str) -> bool:
    existing_terms = tuple(existing.split())
    if len(phrase_terms) >= len(existing_terms):
        return False
    return any(
        phrase_terms == existing_terms[offset : offset + len(phrase_terms)]
        for offset in range(len(existing_terms) - len(phrase_terms) + 1)
    )


def _embedding_cache(
    embedding_adapter: EmbeddingAdapter | EmbeddingCache,
) -> EmbeddingCache:
    if isinstance(embedding_adapter, EmbeddingCache):
        return embedding_adapter
    return EmbeddingCache(
        embedding_adapter,
        model_id=getattr(embedding_adapter, "model_id", None),
    )


def _resolved_speaker(
    atom: AnalysisAtom, atom_meta: Mapping[str, AtomMeta] | None
) -> str | None:
    """``AnalysisAtom.speaker`` wins when present; ``AtomMeta.speaker_id`` is
    only a fallback for atoms whose own ``speaker`` is unknown (TIP-003
    plan.md §2.4: "thiếu metadata thì speaker_change=False" only means no
    signal was available from *either* source, not "ignore atom.speaker
    whenever atom_meta is absent")."""

    if atom.speaker is not None:
        return atom.speaker
    if atom_meta is not None:
        meta = atom_meta.get(atom.atom_id)
        if meta is not None:
            return meta.speaker_id
    return None


def _silence_gap_ms(
    atom: AnalysisAtom,
    previous_atom: AnalysisAtom | None,
    atom_meta: Mapping[str, AtomMeta] | None,
) -> int | None:
    """``current.start_ms - previous.end_ms`` when both are known via
    ``atom_meta``; ``None`` for the first atom, whenever ``atom_meta`` is
    missing/incomplete for either atom, or when the computed gap is
    negative. A negative gap most often means the two atoms share one source
    ``EvidenceItem`` (unreliable relative timing -- see ``AnalysisAtom``'s
    own docstring) or some other data inconsistency; this is treated as
    "unknown" rather than raised, since ``silence_gap_ms`` is an auxiliary
    feature, not a hard invariant.
    """

    if previous_atom is None or atom_meta is None:
        return None
    current_meta = atom_meta.get(atom.atom_id)
    previous_meta = atom_meta.get(previous_atom.atom_id)
    if current_meta is None or previous_meta is None:
        return None
    if current_meta.start_ms is None or previous_meta.end_ms is None:
        return None
    gap = current_meta.start_ms - previous_meta.end_ms
    return gap if gap >= 0 else None


def _cue_flags(
    atom: AnalysisAtom,
    previous_atom: AnalysisAtom | None,
    atom_meta: Mapping[str, AtomMeta] | None,
) -> CueFlags:
    """Build one atom's ``CueFlags``, using only ``atom``/``previous_atom``
    (by input order, not ``turn_id`` -- see TIP-003) and the optional
    ``atom_meta`` lookup. Every flag stays computable with ``atom_meta is
    None``, except ``silence_gap_ms`` which always needs it.
    """

    speaker_change = False
    if previous_atom is not None:
        current_speaker = _resolved_speaker(atom, atom_meta)
        previous_speaker = _resolved_speaker(previous_atom, atom_meta)
        speaker_change = (
            current_speaker is not None
            and previous_speaker is not None
            and current_speaker != previous_speaker
        )
    return CueFlags(
        speaker_change=speaker_change,
        transition_cue=has_transition_cue(atom.text_exact),
        enumeration_cue=has_enumeration_cue(atom.text_exact),
        closing_cue=has_closing_cue(atom.text_exact),
    )


def build_atom_features(
    atoms: tuple[AnalysisAtom, ...],
    config: FeatureBuilderConfig,
    *,
    embedding_adapter: EmbeddingAdapter | EmbeddingCache | None = None,
    entity_aliases: Mapping[str, object] | None = None,
    atom_meta: Mapping[str, AtomMeta] | None = None,
) -> tuple[AtomFeatures, ...]:
    """"""

    atom_ids = tuple(atom.atom_id for atom in atoms)
    if len(atom_ids) != len(set(atom_ids)):
        raise ValueError("atom feature building requires unique atom IDs")
    if not atoms:
        return ()

    char_ngram_range = range(config.char_ngram_range[0], config.char_ngram_range[1])
    character_documents = tuple(
        _char_ngrams(atom.text_exact, char_ngram_range) for atom in atoms
    )
    word_sequences = tuple(_words(atom.text_exact) for atom in atoms)
    syllable_documents = tuple(
        _syllable_terms(atom.text_exact, use_bigrams=config.use_syllable_bigrams)
        for atom in atoms
    )

    syllable_weight_stats = _bm25_weights(
        syllable_documents,
        tokenizer_id=_SYLLABLE_TOKENIZER_ID,
        k1=config.bm25_k1,
        b=config.bm25_b,
    )
    char_weight_stats = _bm25_weights(
        character_documents,
        tokenizer_id=_CHAR_TOKENIZER_ID,
        k1=config.bm25_k1,
        b=config.bm25_b,
    )

    cache = (
        _embedding_cache(embedding_adapter)
        if embedding_adapter is not None
        else None
    )
    vectors_by_atom = (
        cache.embed_batch(atom.text_exact for atom in atoms) if cache is not None else None
    )

    expected_embedding_dim: int | None = None
    features: list[AtomFeatures] = []
    for index, (atom, words, (syllable_weights, _syl_stats), (char_weights, _char_stats)) in enumerate(
        zip(
            atoms,
            word_sequences,
            syllable_weight_stats,
            char_weight_stats,
            strict=True,
        )
    ):
        embedding_model_id: str | None = None
        embedding_dim: int | None = None
        embedding_vector_ref: str | None = None
        if cache is not None:
            assert vectors_by_atom is not None  # cache is not None implies this was computed
            vector = vectors_by_atom[index]
            if not vector or any(not math.isfinite(float(value)) for value in vector):
                raise ValueError(
                    "EmbeddingAdapter.embed() must return a non-empty finite vector"
                )
            embedding_dim = len(vector)
            if expected_embedding_dim is None:
                expected_embedding_dim = embedding_dim
            elif embedding_dim != expected_embedding_dim:
                raise ValueError("EmbeddingAdapter returned inconsistent vector dimensions")
            embedding_model_id = cache.model_id
            embedding_vector_ref = content_ref(cache.model_id, atom.text_exact)

        previous_atom = atoms[index - 1] if index > 0 else None
        features.append(
            AtomFeatures(
                atom_id=atom.atom_id,
                lex_syllable=_top_k(syllable_weights, config.emit_top_k_terms),
                lex_char=_top_k(char_weights, config.emit_top_k_terms),
                entities=extract_entities(atom.text_exact, entity_aliases),
                keyphrases=_keyphrases(words, syllable_weights, config.top_k_keyphrases),
                cues=_cue_flags(atom, previous_atom, atom_meta),
                embedding_model_id=embedding_model_id,
                embedding_dim=embedding_dim,
                embedding_vector_ref=embedding_vector_ref,
            )
        )
    return tuple(features)


def build_full_lexical_weights(
    atoms: tuple[AnalysisAtom, ...],
    config: FeatureBuilderConfig,
) -> tuple[tuple[dict[str, float], dict[str, float]], ...]:

    if not atoms:
        return ()

    char_ngram_range = range(config.char_ngram_range[0], config.char_ngram_range[1])
    character_documents = tuple(
        _char_ngrams(atom.text_exact, char_ngram_range) for atom in atoms
    )
    syllable_documents = tuple(
        _syllable_terms(atom.text_exact, use_bigrams=config.use_syllable_bigrams)
        for atom in atoms
    )
    syllable_weight_stats = _bm25_weights(
        syllable_documents,
        tokenizer_id=_SYLLABLE_TOKENIZER_ID,
        k1=config.bm25_k1,
        b=config.bm25_b,
    )
    char_weight_stats = _bm25_weights(
        character_documents,
        tokenizer_id=_CHAR_TOKENIZER_ID,
        k1=config.bm25_k1,
        b=config.bm25_b,
    )
    return tuple(
        (syllable_weights, char_weights)
        for (syllable_weights, _syl_stats), (char_weights, _char_stats) in zip(
            syllable_weight_stats, char_weight_stats, strict=True
        )
    )


__all__ = ["build_atom_features", "build_full_lexical_weights", "extract_entities"]
