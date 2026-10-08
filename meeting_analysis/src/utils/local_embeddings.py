"""Local, open-source embedding backend (``sentence-transformers``).

Drop-in for ``OpenAIEmbeddingClient`` wherever an ``EmbeddingAdapter``
(``ports.py``) is expected: same ``embed``/``cosine``/``model`` surface, plus
``embed_many`` (which ``embeddings.EmbeddingCache.embed_batch`` picks up).
No network call and no per-token cost after the one-time weight download.

Kept out of ``openai_adapters.py`` so importing that module never pulls in
torch, and this one never needs the ``openai`` package.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable, Sequence
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_MODEL = "BAAI/bge-m3"
# bge-m3 advertises 8192 tokens, but TreeSeg's ``embed_items_with_preceding_context`` joins up to
# ``width`` turns into one string, and attention memory grows with length: on
# a 4 GB GPU 1024 tokens is comfortably safe (measured ~1.1 GB peak at fp16).
DEFAULT_MAX_SEQ_LENGTH = 1024
DEFAULT_BATCH_SIZE = 16


class SentenceTransformerEmbeddingClient:
    """Embeds text with a local ``sentence-transformers`` model.
    """

    def __init__(
        self,
        *,
        model: str = DEFAULT_LOCAL_MODEL,
        device: str | None = None,
        max_seq_length: int = DEFAULT_MAX_SEQ_LENGTH,
        batch_size: int = DEFAULT_BATCH_SIZE,
        prefix: str = "",
        loader: Callable[[str, str], Any] | None = None,
    ) -> None:
        self.model = model
        self._device = device
        self._max_seq_length = max_seq_length
        self._batch_size = batch_size
        self._prefix = prefix
        self._loader = loader or _load_sentence_transformer
        self._encoder: Any | None = None
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[float, ...]] = {}

    @property
    def model_name(self) -> str:
        return f"local-embedding:{self.model}"

    def _ensure_encoder(self) -> Any:
        if self._encoder is None:
            device = self._device or _default_device()
            logger.info("loading embedding model %s on %s", self.model, device)
            encoder = self._loader(self.model, device)
            encoder.max_seq_length = self._max_seq_length
            encoder.tokenizer.truncation_side = "left"
            self._encoder = encoder
        return self._encoder

    def embed(self, text: str) -> tuple[float, ...]:
        return self.embed_many((text,))[0]

    def embed_many(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Vectors for ``texts`` in the same order (duplicates included);
        texts already seen are served from the cache and only the rest are
        encoded, in batches."""

        bodies = [self._prefix + (text if text.strip() else " ") for text in texts]
        missing = list(dict.fromkeys(body for body in bodies if body not in self._cache))
        if missing:
            with self._lock:
                encoder = self._ensure_encoder()
                vectors = encoder.encode(
                    missing,
                    batch_size=self._batch_size,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
            for body, vector in zip(missing, vectors, strict=True):
                self._cache[body] = tuple(float(value) for value in vector)
        return tuple(self._cache[body] for body in bodies)

    def cosine(self, left_text: str, right_text: str) -> float:
        left, right = self.embed_many((left_text, right_text))
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        # Guard float drift so a caller's [-1, 1] range check never trips.
        return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _default_device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _load_sentence_transformer(model: str, device: str) -> Any:
    """Loads ``model``; fp16 on CUDA (halves VRAM, no measurable quality
    change for retrieval-style encoders), fp32 on CPU where fp16 is slow."""

    import torch
    from sentence_transformers import SentenceTransformer

    model_kwargs = {"torch_dtype": torch.float16} if device.startswith("cuda") else {}
    return SentenceTransformer(model, device=device, model_kwargs=model_kwargs)


__all__ = [
    "DEFAULT_LOCAL_MODEL",
    "DEFAULT_MAX_SEQ_LENGTH",
    "SentenceTransformerEmbeddingClient",
]
