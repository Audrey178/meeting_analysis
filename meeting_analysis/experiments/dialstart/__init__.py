import sys
from pathlib import Path

# Thư mục này từng là ``experiments/006_dialstart`` và được nạp qua sys.path, nên mã nơi khác
# (be/services/dependencies.py, experiments/007_dialtreeseg) vẫn import trần
# ``dialstart_segmenter``. Đưa chính thư mục này lên sys.path để mọi nơi dùng CHUNG một
# module ``dialstart_segmenter`` (import tương đối sẽ tạo module thứ hai, khác class).
_DIR = str(Path(__file__).resolve().parent)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from dialstart_segmenter import DialStartSegmenter  # noqa: E402

__all__ = ["DialStartSegmenter"]
