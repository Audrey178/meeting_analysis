"""Tách actor ghép thành từng bên nhận việc kèm vai trò (luật, 0 token).

Họp hành chính hay giao một việc cho nhiều bên::

    "Sở Tài chính chủ trì, phối hợp với Sở Xây dựng"  -> Sở Tài chính (lead), Sở Xây dựng (support)
    "Sở Tài chính (chủ trì), Sở Xây dựng (phối hợp)"  -> như trên
    "anh Sơn và anh Thông"                            -> anh Sơn (joint), anh Thông (joint)
    "Sở Nông nghiệp và Môi trường"                    -> MỘT đơn vị (không cắt ở "và")

Module chỉ TÁCH cách gọi; định danh từng cách gọi nằm ở ``resolution.py``.

Không cắt nhầm tên có chữ "và": tên trong danh sách tham dự được giữ nguyên trước khi
tách; với tên ngoài danh sách, vế sau "và" không phải người/đơn vị nào được ghép lại vào
vế trước nếu vế trước là đơn vị.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..schemas import AssigneeRole

_LEAD_CUE = re.compile(r"(?<!\w)(?:chủ trì|đầu mối|chịu trách nhiệm chính)(?!\w)", re.IGNORECASE)
_SUPPORT_CUE = re.compile(r"(?<!\w)phối hợp(?:\s+với)?(?!\w)", re.IGNORECASE)
_ROLE_IN_PARENTHESES = re.compile(r"\(\s*(chủ trì|phối hợp)\s*\)", re.IGNORECASE)
# Dấu tách giữa các bên; nhóm bắt để biết vế nào được tách bởi "và" (có thể là một tên).
_SEPARATOR = re.compile(r"\s*(,|;|/|(?<!\w)(?:cùng với|cùng|và)(?!\w))\s*", re.IGNORECASE)
_EDGE_FILLER = re.compile(r"^(?:[\s,;:.\-]|(?:thì|là|do)(?!\w))+|(?:[\s,;:.\-]|thì(?!\w))+$", re.IGNORECASE)
_PLACEHOLDER = "§{index}§"
_PLACEHOLDER_PATTERN = re.compile("§(\\d+)§")


@dataclass(frozen=True, slots=True)
class ActorMention:
    """Một cách gọi bên nhận việc tách từ actor ghép.

    Các trường:
        text: cách gọi (đã bỏ từ chỉ vai trò), vd "Sở Xây dựng", "anh Sơn".
        role: "lead" | "support" | "joint".
    """

    text: str
    role: AssigneeRole


def _protect_names(text: str, protected_names: Sequence[str]) -> tuple[str, list[str]]:
    """Thay các tên cần giữ nguyên (tên dài trước) bằng placeholder để không bị tách.

    Đầu vào: text - actor; protected_names - tên người/đơn vị trong danh sách.
    Đầu ra: (chuỗi đã thay, list tên gốc theo chỉ số placeholder).
    """

    originals: list[str] = []
    for name in sorted({n for n in protected_names if n.strip()}, key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE)

        def _swap(match: re.Match) -> str:
            originals.append(match.group(0))
            return _PLACEHOLDER.format(index=len(originals) - 1)

        text = pattern.sub(_swap, text)
    return text, originals


def _restore_names(text: str, originals: list[str]) -> str:
    """Trả các placeholder về tên gốc."""

    return _PLACEHOLDER_PATTERN.sub(lambda match: originals[int(match.group(1))], text)


def _clean_mention(raw: str) -> tuple[str, AssigneeRole | None]:
    """Bỏ từ chỉ vai trò khỏi một vế, đọc vai trò ghi trong ngoặc nếu có.

    Đầu vào: raw - một vế sau khi tách.
    Đầu ra: (cách gọi sạch, vai trò trong ngoặc hoặc None).
    """

    explicit_role: AssigneeRole | None = None
    role_match = _ROLE_IN_PARENTHESES.search(raw)
    if role_match:
        explicit_role = "lead" if role_match.group(1).lower() == "chủ trì" else "support"
        raw = _ROLE_IN_PARENTHESES.sub(" ", raw)
    raw = _LEAD_CUE.sub(" ", raw)
    raw = re.sub(r"\s+", " ", raw)
    return _EDGE_FILLER.sub("", raw).strip(), explicit_role


def _split_side(
    text: str, is_known_entity: Callable[[str], bool], looks_like_organization: Callable[[str], bool]
) -> list[tuple[str, AssigneeRole | None]]:
    """Tách một phía (chủ trì hoặc phối hợp) thành các vế, ghép lại tên đơn vị bị cắt ở "và".

    Đầu vào:
        text: phía cần tách (tên trong danh sách đã thành placeholder).
        is_known_entity: vế có khớp người/đơn vị nào không.
        looks_like_organization: vế có dạng tên đơn vị không.
    Đầu ra: list (cách gọi, vai trò trong ngoặc hoặc None).
    """

    pieces = _SEPARATOR.split(text)
    mentions: list[tuple[str, AssigneeRole | None]] = []
    separator = ""
    for index, piece in enumerate(pieces):
        if index % 2 == 1:
            separator = piece.lower()
            continue
        mention, role = _clean_mention(piece)
        if not mention:
            continue
        if (
            separator == "và"
            and mentions
            and looks_like_organization(mentions[-1][0])
            and not looks_like_organization(mention)
            and not is_known_entity(mention)
        ):
            previous, previous_role = mentions.pop()
            mentions.append((f"{previous} và {mention}", previous_role or role))
            continue
        mentions.append((mention, role))
    return mentions


def split_actor_mentions(
    actor: str,
    *,
    protected_names: Sequence[str] = (),
    is_known_entity: Callable[[str], bool] = lambda _: False,
    looks_like_organization: Callable[[str], bool] = lambda _: False,
) -> tuple[ActorMention, ...]:
    """Tách actor ghép thành các bên nhận việc kèm vai trò.

    Vai trò: vế trước "phối hợp (với)" là chủ trì, vế sau là phối hợp; vai trò ghi trong
    ngoặc ("(chủ trì)", "(phối hợp)") được ưu tiên. Không có từ chỉ vai trò: một bên là
    "lead", nhiều bên là "joint".

    Đầu vào:
        actor: actor do agent/Verifier nêu.
        protected_names: tên không được tách (người/đơn vị trong danh sách tham dự).
        is_known_entity: vế có khớp người/đơn vị nào không (để ghép lại tên bị cắt ở "và").
        looks_like_organization: vế có dạng tên đơn vị không.
    Đầu ra: tuple ActorMention theo thứ tự xuất hiện (rỗng nếu actor rỗng).
    """

    text = unicodedata.normalize("NFC", actor or "").strip()
    if not text:
        return ()
    text, originals = _protect_names(text, protected_names)
    # Che "(chủ trì)"/"(phối hợp)" để chữ "phối hợp" trong ngoặc không bị coi là chỗ chia hai phía.
    masked = _ROLE_IN_PARENTHESES.sub(lambda match: "#" * len(match.group(0)), text)
    support_cue = _SUPPORT_CUE.search(masked)
    lead_text, support_text = (text[: support_cue.start()], text[support_cue.end():]) if support_cue else (text, "")
    has_lead_cue = bool(_LEAD_CUE.search(lead_text)) or bool(support_cue)

    lead_side = _split_side(lead_text, is_known_entity, looks_like_organization)
    support_side = _split_side(support_text, is_known_entity, looks_like_organization)
    default_lead_role: AssigneeRole = "lead" if has_lead_cue or len(lead_side) == 1 else "joint"
    mentions = [
        ActorMention(_restore_names(mention, originals), role or default_lead_role) for mention, role in lead_side
    ]
    mentions.extend(
        ActorMention(_restore_names(mention, originals), role or "support") for mention, role in support_side
    )
    if any(m.role == "lead" for m in mentions):
        mentions = [ActorMention(m.text, "lead") if m.role == "joint" else m for m in mentions]
    return tuple(mentions)


def find_support_names_in_text(task_text: str, entity_names: Sequence[str]) -> tuple[str, ...]:
    """Tìm bên phối hợp nằm trong NỘI DUNG việc ("…, phối hợp với Sở Xây dựng").

    Chỉ nhận tên có trong ``entity_names`` (người/đơn vị trong danh sách tham dự) để
    không biến một cụm bất kỳ thành bên nhận việc.

    Đầu vào: task_text - nội dung việc; entity_names - tên được phép nhận.
    Đầu ra: tuple tên (theo thứ tự xuất hiện sau "phối hợp").
    """

    text = unicodedata.normalize("NFC", task_text or "")
    found: list[tuple[int, str]] = []
    for cue in _SUPPORT_CUE.finditer(text):
        clause_end = re.search(r"[.;]", text[cue.end():])
        clause = text[cue.end(): cue.end() + clause_end.start()] if clause_end else text[cue.end():]
        for name in entity_names:
            match = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", clause, re.IGNORECASE)
            if match and name not in (existing for _, existing in found):
                found.append((cue.end() + match.start(), name))
    return tuple(name for _, name in sorted(found))


__all__ = ["ActorMention", "find_support_names_in_text", "split_actor_mentions"]
