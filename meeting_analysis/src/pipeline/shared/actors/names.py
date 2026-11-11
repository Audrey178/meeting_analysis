"""Chuẩn hoá tên người và tên đơn vị để so sánh với nhau, dùng chung ở mọi chỗ cần so tên.

Ngoài ra nhận biết các đại từ trần như "em", "bọn em": chúng không đủ để chỉ ra ai nhận việc. Các
cách gọi chung chung khác ("một thành viên", "nhóm") không bị chặn bằng danh sách từ; nếu không
khớp được ai thì việc đó sẽ được gửi agent kiểm chứng.
"""

from __future__ import annotations

import re
import unicodedata

# Các từ xưng hô đứng đầu tên, bị bỏ khi so khớp ("anh Sơn" -> "sơn", "đ/c Thông" -> "thông").
HONORIFIC_PREFIXES = ("đồng chí", "đ/c", "anh", "chị", "em", "bạn", "cô", "chú", "bác", "ông", "bà")

# Viết tắt hay gặp trong tên đơn vị. Cùng với việc bỏ "nhân dân" sau "ủy ban"/"hội đồng"
# (``_CANONICAL_PEOPLE_COUNCIL``), "UBND TP", "Ủy ban nhân dân Thành phố" và "Ủy ban Thành
# phố" cùng về một khoá "ủy ban thành phố"; HĐND vẫn khác UBND ("hội đồng" ≠ "ủy ban").
_ORGANIZATION_ABBREVIATIONS = {"ubnd": "ủy ban", "hđnd": "hội đồng", "tp": "thành phố"}
_CANONICAL_PEOPLE_COUNCIL = re.compile(r"(?<!\w)(ủy ban|hội đồng) nhân dân(?!\w)")

# Đại từ ngôi thứ nhất/nhị đứng một mình: không phải tên thật nên không được
# coi là người phụ trách trong văn bản báo cáo.
_FIRST_OR_SECOND_PERSON_PRONOUNS = frozenset(
    {
        "em", "anh", "chị", "tôi", "mình", "ta",
        "bọn em", "bọn anh", "bọn chị", "bọn mình", "bọn tôi",
        "chúng em", "chúng anh", "chúng tôi", "chúng mình", "chúng ta",
        "các em", "các anh", "các chị",
    }
)

def name_key(text: str) -> str:
    """Tạo khoá chuẩn hoá của một tên người hoặc tên đơn vị để so khớp.

    Hai cách viết khác nhau của cùng một tên phải cho ra cùng một khoá: khoá đã chuẩn hoá Unicode,
    viết thường, bỏ phần trong ngoặc, thống nhất "uỷ"/"ủy", mở rộng các viết tắt UBND/HĐND/TP, bỏ
    "nhân dân" sau "ủy ban"/"hội đồng", gộp khoảng trắng và bỏ đúng MỘT từ xưng hô đứng đầu.
    Khoá chỉ dùng để so sánh, không dùng để hiển thị.

    Ví dụ: "Đ/c Thông (HNI)" thành "thông"; "anh Phạm Hồng Sơn" thành "phạm hồng sơn";
    "UBND TP", "Ủy ban nhân dân Thành phố" và "Ủy ban Thành phố" đều thành "ủy ban thành phố".

    Args:
        text: Tên người hoặc đơn vị, như trong bản ghi, danh sách tham dự hoặc do mô hình viết.

    Returns:
        Khoá đã chuẩn hoá; chuỗi rỗng nếu tên chỉ gồm khoảng trắng hoặc phần trong ngoặc.
    """

    key = unicodedata.normalize("NFC", text).casefold()
    key = re.sub(r"\([^)]*\)", " ", key).replace("uỷ", "ủy")
    for abbreviation, expansion in _ORGANIZATION_ABBREVIATIONS.items():
        key = re.sub(rf"(?<!\w){abbreviation}(?!\w)", expansion, key)
    key = _CANONICAL_PEOPLE_COUNCIL.sub(r"\1", key)
    key = re.sub(r"\s+", " ", key).strip()
    for prefix in HONORIFIC_PREFIXES:
        if key.startswith(prefix + " "):
            key = key[len(prefix) + 1:].strip()
            break
    return key


def is_bare_personal_pronoun(actor: str) -> bool:
    """Kiểm tra một cách gọi có chỉ là đại từ ngôi thứ nhất/thứ hai đứng một mình hay không.

    Các cách gọi như "em", "bọn em", "chúng tôi" không chỉ ra được ai cụ thể nên không được
    coi là bên nhận việc. Xưng hô kèm tên ("anh Sơn") không bị coi là đại từ trần.

    Args:
        actor: Cách gọi bên nhận việc do mô hình nêu.

    Returns:
        True nếu cách gọi chỉ là đại từ trần và cần loại bỏ.
    """

    return name_key(actor) in _FIRST_OR_SECOND_PERSON_PRONOUNS


__all__ = [
    "HONORIFIC_PREFIXES",
    "is_bare_personal_pronoun",
    "name_key",
]
