"""Labels each LLM call with the agent/segment that made it, so retry
warnings from ``OpenAIChatJSONAdapter`` (which only knows "a call failed")
can be attributed. Needed because Speaker-Opinion and Action-Item run
concurrently, so log line order alone cannot say which one is slow.

Dependency-free; uses a ``ContextVar`` so concurrent branches don't see each
other's label.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

logger = logging.getLogger(__name__)

_current_label: ContextVar[str] = ContextVar("llm_call_label", default="unlabeled")


def current_llm_label() -> str:
    return _current_label.get()


@contextmanager
def llm_call(
    name: str, *, segment_id: str | None = None, prompt_chars: int | None = None
) -> Iterator[None]:
    """Wrap one ``generate_json`` call. Logs its duration at INFO on success
    and WARNING on failure (then re-raises), and exposes the label to the
    adapter's retry warnings via :func:`current_llm_label`."""

    label = name if segment_id is None else f"{name}[{segment_id}]"
    if prompt_chars is not None:
        label = f"{label} prompt={prompt_chars}chars"
    token = _current_label.set(label)
    started = time.monotonic()
    try:
        yield
    except BaseException:
        logger.warning("LLM call FAILED %s after %.1fs", label, time.monotonic() - started)
        raise
    else:
        logger.info("LLM call done %s in %.1fs", label, time.monotonic() - started)
    finally:
        _current_label.reset(token)


__all__ = ["current_llm_label", "llm_call"]
