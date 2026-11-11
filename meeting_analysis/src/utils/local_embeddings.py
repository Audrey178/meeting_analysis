"""Tạo vector biểu diễn câu bằng mô hình mã nguồn mở chạy ngay trên máy: không gọi mạng và không tốn
phí sau lần tải mô hình đầu tiên. Dùng cho phần tra cứu kho tri thức. Được tách riêng để các phần khác
không phải nạp thư viện học sâu nặng.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_MODEL = "BAAI/bge-m3"
# bge-m3 advertises 8192 tokens, but attention memory grows with length: on a
# 4 GB GPU 1024 tokens is comfortably safe (measured ~1.1 GB peak at fp16).
DEFAULT_MAX_SEQ_LENGTH = 1024
DEFAULT_BATCH_SIZE = 16


class SentenceTransformerEmbeddingClient:
    """Tạo vector biểu diễn cho văn bản bằng mô hình ``sentence-transformers`` chạy trên máy.

    Mô hình chỉ được nạp ở lần mã hoá đầu tiên (nạp lười), nên tạo đối tượng rất nhẹ. Vector được
    chuẩn hoá về độ dài 1 và lưu bộ nhớ đệm theo nội dung, nên mã hoá lại cùng một câu không tốn thêm.
    Văn bản dài hơn giới hạn bị cắt bớt ở phía ĐẦU (giữ phần cuối). An toàn khi gọi từ nhiều luồng:
    việc nạp và chạy mô hình được khoá.

    Args:
        model: Tên mô hình trên Hugging Face, mặc định ``BAAI/bge-m3``.
        device: Thiết bị chạy, ví dụ ``"cuda"`` hoặc ``"cpu"``; None thì tự chọn GPU nếu có.
        max_seq_length: Số token tối đa mỗi văn bản; giữ nhỏ để không tràn bộ nhớ GPU.
        batch_size: Số văn bản mã hoá mỗi lô.
        prefix: Chuỗi gắn vào đầu mọi văn bản trước khi mã hoá (một số mô hình cần, ví dụ
            ``"query: "``); rỗng thì không gắn.
        loader: Hàm nạp mô hình ``(tên, thiết bị) -> encoder``, dùng thay thế trong test; None thì
            dùng ``sentence-transformers``.

    Attributes:
        model: Tên mô hình đang dùng.
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
        """Tên hiển thị của mô hình, dạng ``local-embedding:<tên mô hình>``."""
        return f"local-embedding:{self.model}"

    def _ensure_encoder(self) -> Any:
        """Nạp mô hình ở lần gọi đầu và trả lại encoder; bên gọi phải giữ khoá."""
        if self._encoder is None:
            device = self._device or _default_device()
            logger.info("loading embedding model %s on %s", self.model, device)
            encoder = self._loader(self.model, device)
            encoder.max_seq_length = self._max_seq_length
            encoder.tokenizer.truncation_side = "left"
            self._encoder = encoder
        return self._encoder

    def embed(self, text: str) -> tuple[float, ...]:
        """Trả vector (đã chuẩn hoá) của một văn bản."""
        return self.embed_many((text,))[0]

    def embed_many(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Trả vector cho nhiều văn bản, đúng thứ tự đầu vào.

        Văn bản trùng nhau hoặc đã gặp trước đó lấy từ bộ nhớ đệm; chỉ văn bản mới được đưa vào mô
        hình, theo lô. Văn bản rỗng hoặc toàn khoảng trắng được thay bằng một dấu cách để vẫn có
        vector.

        Args:
            texts: Các văn bản cần mã hoá; có thể trùng nhau.

        Returns:
            Tuple vector, mỗi vector là tuple số thực đã chuẩn hoá độ dài 1, cùng số lượng và thứ tự
            với ``texts``.
        """

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


def _default_device() -> str:
    """Chọn ``"cuda"`` nếu có GPU, ngược lại ``"cpu"``."""
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def _load_sentence_transformer(model: str, device: str) -> Any:
    """Nạp mô hình ``sentence-transformers`` lên thiết bị chỉ định.

    Trên GPU dùng fp16 (giảm nửa bộ nhớ, chất lượng tra cứu không đổi đáng kể); trên CPU giữ fp32 vì
    fp16 chạy chậm.
    """

    import torch
    from sentence_transformers import SentenceTransformer

    model_kwargs = {"torch_dtype": torch.float16} if device.startswith("cuda") else {}
    return SentenceTransformer(model, device=device, model_kwargs=model_kwargs)


__all__ = [
    "DEFAULT_LOCAL_MODEL",
    "DEFAULT_MAX_SEQ_LENGTH",
    "SentenceTransformerEmbeddingClient",
]
