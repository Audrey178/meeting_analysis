"""Xử lý chữ tiếng Việt dùng chung (chỉ bằng luật): gộp khoảng trắng, tách từ, bỏ các từ chức năng
không mang nghĩa, và chuẩn hoá chữ để so khớp hoặc so trùng nội dung.
"""

from __future__ import annotations

import re
import unicodedata

SPACE_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"\w+", re.UNICODE)

# Từ chức năng tiếng Việt (kiểm tiêu đề nhãn chủ đề, so tên người).
VN_STOPWORDS = frozenset(
    {
        "và", "là", "của", "có", "không", "được", "cho", "này", "đó", "các",
        "một", "những", "để", "với", "trong", "về", "đã", "sẽ", "thì", "mà",
        "nhưng", "cũng", "khi", "nếu", "như", "hay", "hoặc", "tại", "theo",
        "từ", "đến", "sau", "trước", "vì", "nên", "rằng", "vẫn", "còn", "lại",
    }
)


def word_tokens(text: str) -> tuple[str, ...]:
    """Tách chữ thành các từ viết thường, sau khi chuẩn hoá Unicode.

    Nhờ chuẩn hoá trước, cùng một từ dù gõ dấu dựng sẵn hay dấu tổ hợp vẫn so bằng nhau.

    Args:
        text: Chuỗi bất kỳ.

    Returns:
        Các từ theo thứ tự xuất hiện, giữ cả từ lặp.
    """

    return tuple(WORD_RE.findall(unicodedata.normalize("NFC", text).lower()))


def _collapse_whitespace(text: str) -> str:
    """Gộp mọi chuỗi khoảng trắng/xuống dòng liên tiếp thành một dấu cách và bỏ khoảng trắng hai đầu."""

    return " ".join(text.split())


# Từ chức năng bỏ khi so trùng nội dung (chỉ để so khớp, không đổi text hiển thị).
_SIMILARITY_STOPWORDS = frozenset(
    "và của cho các những một được để là thì sẽ đã với trong theo về từ khi này "
    "đó lại ra vào cũng như nhằm việc thực hiện giao thống nhất".split()
)


def normalize_for_match(text: str) -> str:
    """Chuẩn hoá chữ để so khớp cụm từ: chuẩn hoá Unicode, viết thường, gộp khoảng trắng.

    Args:
        text: Chuỗi bất kỳ.

    Returns:
        Chuỗi đã chuẩn hoá, chỉ dùng để so sánh, không dùng để hiển thị.
    """

    return _collapse_whitespace(unicodedata.normalize("NFC", text).casefold())


def content_tokens(text: str, drop: frozenset[str] = frozenset()) -> frozenset[str]:
    """Lấy tập âm tiết mang nội dung của một chuỗi để so trùng nội dung.

    Bỏ âm tiết một ký tự, các từ chức năng và các từ nhạt nghĩa hay lặp trong câu giao việc
    ("thực hiện", "giao", "thống nhất"...), cùng các từ nơi gọi muốn bỏ thêm.

    Args:
        text: Chuỗi bất kỳ.
        drop: Các từ bỏ thêm, viết thường.

    Returns:
        Tập âm tiết nội dung.
    """

    words = re.findall(r"\w+", normalize_for_match(text))
    return frozenset(w for w in words if len(w) > 1 and w not in _SIMILARITY_STOPWORDS and w not in drop)


__all__ = [
    "SPACE_RE",
    "VN_STOPWORDS",
    "WORD_RE",
    "content_tokens",
    "normalize_for_match",
    "word_tokens",
]
