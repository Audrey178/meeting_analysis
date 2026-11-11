"""Đọc danh sách bên nhận việc mà agent khai ra cho một việc giao: tên, vai trò (chủ trì hay phối hợp)
và loại (người hay đơn vị). Chỉ đọc đúng những gì agent khai, không tự đoán thêm từ câu chữ.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from ..llm_output import read_stripped_text, split_dict_entries
from ..schemas import ASSIGNEE_ROLES, ASSIGNEE_TYPES, AssigneeMention
from .names import is_bare_personal_pronoun, name_key

_ROLE_ORDER = {"lead": 0, "joint": 1, "support": 2}

# Schema JSON của trường ``assignees`` (việc giao của Action agent và Verifier, bên nhận mới trong
# cập nhật tiến độ).
ASSIGNEES_SCHEMA: dict = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "id": {"type": ["string", "null"]},
            "role": {"type": "string", "enum": list(ASSIGNEE_ROLES)},
            "type": {"type": "string", "enum": list(ASSIGNEE_TYPES)},
        },
        "required": ["name", "id", "role", "type"],
    },
}


def _read_code(value: object) -> str | None:
    """Đọc mã danh bạ do mô hình khai: bỏ ngoặc bao quanh, viết hoa; rỗng hoặc "null" thành None."""

    code = read_stripped_text(value).strip("[]() ").upper()
    return code if code and code not in ("NULL", "NONE") else None


def read_assignee_mentions(value: object, legacy_actor: object = None) -> tuple[AssigneeMention, ...]:
    """Chuẩn hoá trường bên nhận việc do mô hình trả về thành các ``AssigneeMention``.

    Bỏ các mục không có tên, các mục chỉ là đại từ trần ("em", "chúng tôi") và các mục trùng nhau
    (trùng mã danh bạ nếu có mã, không thì trùng tên đã chuẩn hoá). Vai trò hoặc loại lạ được thay
    bằng giá trị mặc định ("joint" và "unknown"). Nếu có ít nhất một bên chủ trì hoặc phối hợp thì
    mọi bên "joint" được nâng thành chủ trì, vì khi đó việc đã có phân vai rõ ràng.

    Args:
        value: Giá trị trường ``assignees`` trong JSON của mô hình; None nghĩa là mô hình không khai.
        legacy_actor: Trường ``actor`` dạng chuỗi kiểu cũ. Chỉ được đọc khi ``value`` là None, và
            khi đó trở thành MỘT bên chủ trì.

    Returns:
        Các bên nhận việc, xếp theo vai trò chủ trì -> cùng thực hiện -> phối hợp; rỗng nếu không
        có bên nào hợp lệ.
    """

    entries, _invalid = split_dict_entries(value)
    mentions: list[AssigneeMention] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        name = read_stripped_text(entry.get("name"))
        key = name_key(name)
        if not key or is_bare_personal_pronoun(name):
            continue
        code = _read_code(entry.get("id"))
        identity = ("code", code) if code else ("name", key)
        if identity in seen:
            continue
        seen.add(identity)
        role, actor_type = entry.get("role"), entry.get("type")
        mentions.append(
            AssigneeMention(
                name,
                role if role in ASSIGNEE_ROLES else "joint",
                actor_type if actor_type in ASSIGNEE_TYPES else "unknown",
                code,
            )
        )
    if value is None:
        legacy = read_stripped_text(legacy_actor)
        if legacy and not is_bare_personal_pronoun(legacy):
            mentions.append(AssigneeMention(legacy, "lead"))
    if any(mention.role in ("lead", "support") for mention in mentions):
        mentions = [replace(m, role="lead") if m.role == "joint" else m for m in mentions]
    return tuple(sorted(mentions, key=lambda mention: _ROLE_ORDER[mention.role]))


def declares_unknown_assignees(value: object) -> bool:
    """Kiểm tra Verifier có khai MỌI bên nhận việc là "unknown" (không xác định được ai) hay không.

    Đọc thẳng từ JSON gốc, không qua bước chuẩn hoá các bên nhận việc.

    Args:
        value: Giá trị trường bên nhận việc trong JSON của Verifier.

    Returns:
        True khi ``value`` là danh sách không rỗng và mọi phần tử đều là dict có loại "unknown".
    """

    return isinstance(value, list) and bool(value) and all(
        isinstance(entry, dict) and entry.get("type") == "unknown" for entry in value
    )


def format_actor(mentions: Sequence[AssigneeMention]) -> str | None:
    """Ghép tên các bên nhận việc thành chuỗi ``actor``, nối bằng ", "; None nếu không có bên nào."""

    return ", ".join(mention.name for mention in mentions) or None


__all__ = [
    "declares_unknown_assignees",
    "format_actor",
    "read_assignee_mentions",
]
