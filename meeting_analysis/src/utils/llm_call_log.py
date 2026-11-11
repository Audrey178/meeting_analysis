"""Gắn nhãn cho mỗi lời gọi mô hình (agent nào, chủ đề nào gọi), để khi có cảnh báo lỗi hay thử lại thì
biết lời gọi đó của ai. Cần thiết vì nhiều agent chạy song song, nên chỉ nhìn thứ tự dòng log thì
không phân biệt được. Mỗi nhánh chạy song song giữ nhãn riêng, không lẫn sang nhau.
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
    """Trả nhãn của lời gọi LLM đang chạy trong nhánh hiện tại, hoặc ``"unlabeled"`` nếu chưa gắn."""
    return _current_label.get()


@contextmanager
def llm_call(
    name: str, *, segment_id: str | None = None, prompt_chars: int | None = None
) -> Iterator[None]:
    """Gắn nhãn và đo thời gian cho một lời gọi LLM, dùng với ``with``.

    Trong khối ``with``, nhãn được đặt cho nhánh chạy hiện tại để cảnh báo thử lại của kết nối LLM
    in ra đúng tên agent/chủ đề (qua ``current_llm_label``). Khi khối kết thúc: thành công thì ghi log
    INFO kèm thời gian; có lỗi thì ghi log WARNING rồi ném lại lỗi nguyên vẹn. Nhãn cũ luôn được
    khôi phục.

    Ví dụ nhãn: ``action_agent[TOPIC_SEG_000003] prompt=5120chars``.

    Args:
        name: Tên agent hoặc bước gọi LLM.
        segment_id: Mã đoạn chủ đề đang xử lý; None thì nhãn không kèm mã đoạn.
        prompt_chars: Độ dài prompt (ký tự) để ghi vào nhãn; None thì bỏ qua.

    Yields:
        None. Khối ``with`` chỉ bao quanh lời gọi cần gắn nhãn.
    """

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
