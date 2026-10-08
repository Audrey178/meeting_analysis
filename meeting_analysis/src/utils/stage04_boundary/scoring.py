"""Giai đoạn 4b -- BoundaryScorer: chỉ tính một con số cho mỗi candidate,
không làm gì khác.

Bộ tính điểm (scorer) kết hợp giá trị prior của từng tín hiệu (cue) với độ
mạch lạc về từ vựng (lexical coherence) xung quanh vị trí cắt được đề xuất.
Nó chỉ trả về một điểm số cho mỗi candidate, không bao giờ chọn, sắp xếp
lại hay chỉnh sửa các đoạn văn bản -- việc lựa chọn thuộc về giai đoạn 4c.
4b: Hai bên của một điểm cắt có tiềm năng không?
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .candidates import Candidate
import numpy as np


# ---------------------------------------------------------------------------
# 4b -- BoundaryScorer (Bộ tính điểm ranh giới)
# ---------------------------------------------------------------------------

# semantic_change dominates the mix on purpose: atoms are meant to be
# semantic units, not clause units. sentence_boundary/discourse_cue alone
# reward cutting at every period or connective even when the two sides are
# still the same idea, which fragmented atoms below the intended semantic
# granularity. Weighted this way, a punctuation/discourse cue only wins the
# cut in pack_atoms() (gain = split_score) when it also coincides with an
# actual meaning shift.
_W_SENTENCE  = 0.25
_W_SEMANTIC  = 0.60
_W_DISCOURSE = 0.15
_W_LENGTH    = 0.20
_CONTEXT_CHARS = 80
# NOTE (bug fix, see run_to_stage4.py Completion Report): tiebreak.py already
# imported these two names, but they were never defined here, so the module
# could not be imported at all -- unconditionally, even with
# atom_builder.llm_tiebreak left at its default False. tau/delta only affect
# behavior on the (currently off-by-default) LLM tiebreak path: tau is the
# split_score midpoint treated as "ambiguous", delta the half-width of that
# band. 0.5/0.1 are placeholders that unblock import; calibrate against real
# split_score distributions before turning llm_tiebreak on.
_TIEBREAK_TAU = 0.5
_TIEBREAK_DELTA = 0.1

# Continuation penalty (run_to_stage4.py Completion Report, Vấn đề 2): a
# weak_punct/item_boundary candidate is a topology-only signal -- it says
# nothing about whether the text that follows actually starts a new clause.
# When the right-context starts lowercase or with one of these connectives,
# it's almost always still the *same* clause continuing (Vietnamese doesn't
# reliably capitalize after a comma or a mid-turn pause). sentence_punct and
# discourse_marker are exempt -- a real period or a genuine discourse marker
# is trusted even when followed by a lowercase word (normal, correct
# Vietnamese), so this only applies when EVERY source contributing to a
# position is weak_punct/item_boundary.
#
# This is deliberately just a 0/1 flag here, NOT pre-weighted: an earlier
# version subtracted a weight straight into static_score's [0, 1] clamp,
# but that only removes the *reward* term (`gain` floors at 0, same as any
# merely-mediocre candidate) -- it can't outweigh len_penalty's pull toward
# target_chars for a candidate that happens to land near it (verified: a
# candidate 255 chars from the previous cut, i.e. close to target_chars=280,
# still won an 0.208-vs-0.383 cost comparison against skipping to the next
# real boundary 444 chars away, even fully zeroed out). Making this an
# actual additive DP cost in pack_atoms() (see `_LAMBDA_CONTINUATION` there)
# is what actually gives it teeth.
_CONTINUATION_CUE_RE = re.compile(r"^(?:rồi|và|thì|về|để)\b", re.IGNORECASE)
_CONTINUATION_ONLY_SOURCES = frozenset({"weak_punct", "item_boundary"})


class SemanticCoherenceScorer:
    """Sentence-embedding cosine similarity, Vietnamese-native model.

    Model choice matters more here than for most NLP tasks: a multilingual
    model (LaBSE, multilingual-e5) trained mostly on English/Chinese/etc
    with Vietnamese as a small slice tends to under-separate Vietnamese
    sentences -- everything clusters toward a mediocre-similarity band
    because the model's Vietnamese subspace is undertrained. A Vietnamese-
    native encoder (PhoBERT-based SimCSE, or a Vietnamese SBERT variant)
    gives sharper separation for the same input, which is what a threshold
    like `_MERGE_THRESHOLD` in 4c actually needs -- a scorer that hugs
    0.5 for everything is useless for a hard cutoff.

    Default here targets `VoVanPhuc/sup-SimCSE-VietNamese-phobert-base`
    (supervised SimCSE fine-tuned on PhoBERT, trained specifically for
    Vietnamese sentence similarity) -- swap the `model_name` if T12
    benchmarking finds a better fit, e.g. a Vietnamese SBERT variant.
    """
    def __init__(self,
        model_name: str = "VoVanPhuc/sup-SimCSE-VietNamese-phobert-base",
        *,
        device: str = "cpu",
        cache_size: int = 4096,
        ) -> None:
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name, device=device)
        self._cache_size = cache_size
        self._cache: dict[str, tuple[float, ...]] = {}

    def warm_cache(self, texts) -> None:
        """Batch-encode every text in ``texts`` not already cached, in ONE
        ``model.encode()`` call instead of one per text.

        ``score_candidates`` below calls this once per turn with every
        candidate's left/right context window before scoring -- without it,
        ``coherence()`` was doing one full PhoBERT forward pass per text
        (measured: ~236ms/candidate on CPU, unbatched), which made a single
        long turn (dozens of candidates) take over a minute and a 16-turn
        session time out past 5 minutes. Batching the same work into a
        handful of ``encode()`` calls is the actual fix -- the model and
        text volume don't change, only how many forward passes it takes.
        """
        uniq = [t for t in dict.fromkeys(texts) if t and t not in self._cache]
        if not uniq:
            return
        vectors = self._model.encode(uniq, normalize_embeddings=True, batch_size=64)
        for text, vec in zip(uniq, vectors):
            self._cache[text] = tuple(vec.tolist())
        # Simple bound so a very long session can't grow this unboundedly;
        # not LRU-precise, just prevents unbounded memory growth.
        if len(self._cache) > self._cache_size:
            for key in list(self._cache)[: len(self._cache) - self._cache_size]:
                del self._cache[key]

    def coherence(self, left_text: str, right_text: str) -> float:
        if not left_text.strip() or not right_text.strip():
            return 0.0
        left_vec = self._embed(left_text)
        right_vec = self._embed(right_text)
        cosine = float(np.dot(left_vec, right_vec))
        return max(0.0, min(1.0, (cosine + 1.0) / 2.0))  # normalize to [0, 1]

    def _embed(self, text: str) -> tuple[float, ...]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        # Fallback for a text warm_cache() didn't see (shouldn't happen on
        # the score_candidates path, but coherence() must still work
        # standalone) -- one unbatched call, same as before this fix.
        vec = self._model.encode(text, normalize_embeddings=True)
        result = tuple(vec.tolist())
        self._cache[text] = result
        return result

class HybridCoherenceScorer:
    """Semantic when available and worth the cost, lexical fallback
    otherwise -- avoids a hard dependency on model availability/latency
    for a pipeline stage that must keep running."""

    def __init__(self, semantic: SemanticCoherenceScorer, lexical = None) -> None:
        self._semantic = semantic
        self._lexical = lexical

    def warm_cache(self, texts) -> None:
        """Delegates to the semantic scorer's batched pre-embedding (see
        ``SemanticCoherenceScorer.warm_cache``); a no-op if the semantic
        scorer is unavailable, matching this class's "semantic when
        available, lexical fallback otherwise" contract."""
        try:
            self._semantic.warm_cache(texts)
        except Exception:
            pass

    def coherence(self, left_text: str, right_text: str) -> float:
        try:
            return self._semantic.coherence(left_text, right_text)
        except Exception:
            return self._lexical.coherence(left_text, right_text)

@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    pos: int
    source: str
    model_confidence: float | None
    sentence_boundary: float
    semantic_change: float
    discourse_cue: float
    continuation_penalty: float
    split_score: float


def candidate_windows(text: str, candidates: tuple[Candidate, ...]) -> list[str]:
    """Every left/right context window ``score_candidates`` will need to
    embed for this turn's candidates -- factored out so a caller processing
    many turns (``build_analysis_atoms``) can pool windows across ALL turns
    into one ``coherence_scorer.warm_cache()`` call instead of one per turn,
    for better batch-encode utilization than per-turn warming alone gives."""
    n = len(text)
    windows: list[str] = []
    for candidate in candidates:
        if 0 < candidate.pos < n:
            windows.append(text[max(0, candidate.pos - _CONTEXT_CHARS): candidate.pos])
            windows.append(text[candidate.pos: candidate.pos + _CONTEXT_CHARS])
    return windows


def score_candidates(
    text: str,
    candidates: tuple[Candidate, ...],
    *,
    coherence_scorer: HybridCoherenceScorer,
) -> tuple[ScoredCandidate, ...]:
    """4b: ``split_score = w_cue * cue_prior + w_coh * (1 - coherence(L, R))``.

    Tham số:
        text: Văn bản gốc của lượt nói (turn), dùng để lấy ngữ cảnh trái/phải
            quanh mỗi vị trí candidate.
        candidates: Tập hợp các vị trí cắt hợp lệ do 4a sinh ra.
        coherence_scorer: Bộ tính độ mạch lạc từ vựng dùng để so sánh đoạn
            văn bản bên trái và bên phải của mỗi vị trí cắt.

    Trả về:
        Một điểm số cho mỗi candidate đầu vào; không bao giờ sắp xếp lại
        hay loại bỏ candidate nào -- làm vậy sẽ âm thầm thu hẹp tập vị trí
        cắt hợp lệ mà 4c được phép chọn.
    """

    n = len(text)

    # Pre-warm the scorer's embedding cache with every left/right context
    # window this turn will need, in one (or a few) batched encode() calls
    # instead of one per candidate -- see SemanticCoherenceScorer.warm_cache.
    # A no-op for anything a caller already warmed (e.g. build_analysis_atoms
    # pooling windows across the whole session before this per-turn loop).
    coherence_scorer.warm_cache(candidate_windows(text, candidates))

    scored: list[ScoredCandidate] = []
    for candidate in candidates:
        continuation_penalty = 0.0
        if candidate.pos <= 0 or candidate.pos >= n:
            sentence_boundary = 1.0
            semantic_change = 0.0
            entity_change = 0.0
            discourse_cue = 0.0
        else:
            left = text[max(0, candidate.pos - _CONTEXT_CHARS): candidate.pos]
            right = text[candidate.pos: candidate.pos + _CONTEXT_CHARS]

            sentence_boundary = candidate.punct_prior
            discourse_cue = candidate.discourse_prior
            semantic_change = 1.0 - coherence_scorer.coherence(left, right)
            if set(candidate.source.split("+")) <= _CONTINUATION_ONLY_SOURCES and (
                right[:1].islower() or _CONTINUATION_CUE_RE.match(right)
            ):
                continuation_penalty = 1.0
        # continuation_penalty is NOT folded in here -- see the module-level
        # note above; pack_atoms() applies it directly as a DP cost instead.
        static_score = max(0.0, min(1.0,
            _W_SENTENCE * sentence_boundary
            + _W_SEMANTIC * semantic_change
            + _W_DISCOURSE * discourse_cue
        ))
        scored.append(
            ScoredCandidate(
                pos=candidate.pos,
                source=candidate.source,
                model_confidence=candidate.model_confidence,
                sentence_boundary=sentence_boundary,
                semantic_change=semantic_change,
                discourse_cue=discourse_cue,
                continuation_penalty=continuation_penalty,
                split_score=static_score,
            )
        )
    return tuple(scored)


def combine(scored: ScoredCandidate, length_pressure: float) -> float:
    """Cộng thêm length_pressure vào static_score để ra split_score cuối
    cùng. Không thể tính length_pressure ngay trong score_candidates() vì
    nó phụ thuộc điểm cắt liền trước MÀ 4C ĐÃ CHỌN trong path đang xét --
    thông tin đó chưa tồn tại ở thời điểm 4b chạy.

    Trọng số _W_LENGTH khai báo cùng chỗ với w_sentence..w_discourse ở
    đầu module, để mọi trọng số nằm một nơi dù length_pressure được tính
    ở tầng khác (4c, theo từng path trong DP).

    Gọi hàm này một lần cho mỗi cặp (candidate, path) trong lúc 4c tìm
    kiếm -- không gọi ở đây vì "path" chưa tồn tại lúc chấm điểm.
    """
    return max(0.0, min(1.0, scored.static_score + _W_LENGTH * length_pressure))
