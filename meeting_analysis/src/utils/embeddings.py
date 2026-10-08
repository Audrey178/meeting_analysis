"""Shared embedding cache (stage4-5-plan.md section 2, point 2).

Not owned by any one stage: 4b (coherence scoring), Stage 5 (features), and
Stage 6 (semantic segmentation) all need vectors from the same adapter. One
shared cache instance means text embedded once by any of them is never
re-embedded by the others. Caching key is ``sha256(text)``, matching the
content-addressed ``AtomFeatures.embedding_vector_ref`` (D5): the vector
itself never appears in output JSON or ``run_hash``, only this reference.
"""

from __future__ import annotations

from collections.abc import Iterable
import hashlib

from .ports import EmbeddingAdapter

# Separates model_id from text before hashing (TIP-001 fix (d)): two models
# embedding the same text must not collide on the same content_ref, or a
# downstream reader of AtomFeatures.embedding_vector_ref cannot tell which
# model produced it. NUL cannot appear in a well-formed model_id string in
# practice, so it is a safe, simple delimiter.
_MODEL_TEXT_DELIMITER = "\x00"


def content_ref(model_id: str, text: str) -> str:
    """Deterministic, content-addressed cache key for one (model, text) pair."""

    return hashlib.sha256(
        f"{model_id}{_MODEL_TEXT_DELIMITER}{text}".encode("utf-8")
    ).hexdigest()


class EmbeddingCache:
    """Wraps one ``EmbeddingAdapter``, memoizing vectors by content.

    Each instance is bound to exactly one adapter/model (``self.model_id`` is
    fixed for the instance's lifetime), so the internal memoization key only
    needs to vary by text, not by model -- unlike the ``embedding_vector_ref``
    this class hands out in ``AtomFeatures``, which is compared *across*
    models/adapters and therefore must fold ``model_id`` into the hash (see
    ``content_ref``).
    """

    def __init__(self, adapter: EmbeddingAdapter, *, model_id: str | None = None) -> None:
        self._adapter = adapter
        self.model_id = model_id or getattr(
            adapter, "model", getattr(adapter, "model_name", type(adapter).__name__)
        )
        self._vectors: dict[str, tuple[float, ...]] = {}

    def _cache_key(self, text: str) -> str:
        # Internal memoization only -- keyed by text alone is correct here
        # because one EmbeddingCache instance always wraps one adapter/model.
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_vector(vector: object) -> tuple[float, ...]:
        if not isinstance(vector, tuple) or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in vector
        ):
            raise TypeError("EmbeddingAdapter.embed() must return a tuple of floats")
        return vector

    def embed(self, text: str) -> tuple[float, ...]:
        key = self._cache_key(text)
        cached = self._vectors.get(key)
        if cached is not None:
            return cached
        vector = self._validate_vector(self._adapter.embed(text))
        self._vectors[key] = vector
        return vector

    def embed_batch(self, texts: Iterable[str]) -> tuple[tuple[float, ...], ...]:
        """Embed many texts, calling the adapter's batch API at most once.

        Returns vectors in the same order as ``texts`` (duplicates included).
        Uses ``self._vectors`` for anything already cached. For the rest, a
        batch method on the underlying adapter (``embed_many`` or
        ``embed_batch``, checked in that order) is called exactly once with
        the deduplicated missing texts when present; otherwise this falls
        back to calling ``embed`` once per missing text, which is guaranteed
        to produce the exact same result as calling ``self.embed(text)``
        sequentially for each text.
        """

        ordered_texts = tuple(texts)
        results: list[tuple[float, ...] | None] = []
        missing_texts: list[str] = []
        seen_missing: dict[str, None] = {}
        for text in ordered_texts:
            key = self._cache_key(text)
            cached = self._vectors.get(key)
            results.append(cached)
            if cached is None and text not in seen_missing:
                seen_missing[text] = None
                missing_texts.append(text)

        if missing_texts:
            batch_method = getattr(self._adapter, "embed_many", None) or getattr(
                self._adapter, "embed_batch", None
            )
            vector_by_text: dict[str, tuple[float, ...]] = {}
            if batch_method is not None:
                batch_vectors = tuple(batch_method(tuple(missing_texts)))
                if len(batch_vectors) != len(missing_texts):
                    raise ValueError(
                        "EmbeddingAdapter batch method must return exactly one "
                        "vector per input text"
                    )
                for text, vector in zip(missing_texts, batch_vectors, strict=True):
                    vector_by_text[text] = self._validate_vector(vector)
            else:
                for text in missing_texts:
                    vector_by_text[text] = self._validate_vector(self._adapter.embed(text))
            for text, vector in vector_by_text.items():
                self._vectors[self._cache_key(text)] = vector

        final: list[tuple[float, ...]] = []
        for text, cached in zip(ordered_texts, results, strict=True):
            final.append(cached if cached is not None else self._vectors[self._cache_key(text)])
        return tuple(final)

    def dim(self, sample_text: str) -> int:
        return len(self.embed(sample_text))


__all__ = ["EmbeddingCache", "content_ref"]
