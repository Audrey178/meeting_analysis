"""Chooses the ``EmbeddingAdapter`` implementation from the environment, so
the backend, the scripts and the eval code all switch backend in ONE place.

    EMBEDDING_BACKEND         ``local`` (open-source, sentence-transformers) or
                              ``openai``
    EMBEDDING_MODEL           model id for the chosen backend (default:
                              ``BAAI/bge-m3`` / ``text-embedding-3-small``)
    EMBEDDING_DEVICE          local only: ``cuda`` / ``cpu`` (default: auto)
    EMBEDDING_MAX_SEQ_LENGTH  local only: token cap per input (default 1024)
    EMBEDDING_TEXT_PREFIX     local only: prepended to every text (E5 models
                              need ``query: ``)

Imports are lazy so choosing one backend never requires the other's
dependencies (``openai`` vs ``torch``/``sentence-transformers``).
"""

from __future__ import annotations

import os

from .ports import EmbeddingAdapter

DEFAULT_BACKEND = "local"
_OPENAI_DEFAULT_MODEL = "text-embedding-3-small"


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def build_embedding_adapter() -> EmbeddingAdapter:
    backend = (os.environ.get("EMBEDDING_BACKEND") or DEFAULT_BACKEND).strip().lower()
    model = (os.environ.get("EMBEDDING_MODEL") or "").strip()
    if backend == "local":
        from .local_embeddings import (
            DEFAULT_LOCAL_MODEL,
            DEFAULT_MAX_SEQ_LENGTH,
            SentenceTransformerEmbeddingClient,
        )

        return SentenceTransformerEmbeddingClient(
            model=model or DEFAULT_LOCAL_MODEL,
            device=(os.environ.get("EMBEDDING_DEVICE") or "").strip() or None,
            max_seq_length=_positive_int_env("EMBEDDING_MAX_SEQ_LENGTH", DEFAULT_MAX_SEQ_LENGTH),
            prefix=os.environ.get("EMBEDDING_TEXT_PREFIX", ""),
        )
    if backend == "openai":
        from .openai_adapters import OpenAIEmbeddingClient

        return OpenAIEmbeddingClient(model=model or _OPENAI_DEFAULT_MODEL)
    raise ValueError(f"EMBEDDING_BACKEND must be 'local' or 'openai', got {backend!r}")


__all__ = ["DEFAULT_BACKEND", "build_embedding_adapter"]
