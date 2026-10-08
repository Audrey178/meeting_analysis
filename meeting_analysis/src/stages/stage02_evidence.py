"""Stage 2: "đóng băng" các dòng effective thành bằng chứng (evidence) có mã ổn định.

Mã của một ``EvidenceItem`` chỉ phụ thuộc định danh của dòng nguồn (meeting_id
và item_id), còn nội dung chuẩn hóa được băm riêng thành ``content_hash``. Nhờ
đó cùng một transcript luôn cho cùng mã qua các lần chạy, và sửa nội dung chỉ đổi
``content_hash`` chứ không đổi mã trích dẫn. Mọi stage sau đều trích dẫn các mã
này; không stage nào được tạo, sửa hay đổi thứ tự bằng chứng.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from urllib.parse import quote

from ..utils.contracts import EffectiveTranscriptItem, EvidenceItem
from ._shared import SPACE_RE


def _normalize_evidence_text(text: str) -> str:
    """Chuẩn hóa văn bản bằng chứng: Unicode NFC, gộp khoảng trắng, bỏ khoảng trắng hai đầu.

    Đầu vào: text - văn bản của dòng.
    Đầu ra: văn bản đã chuẩn hóa (dùng làm ``text``; bản gốc giữ ở ``text_exact``).
    """

    return SPACE_RE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def _make_evidence_id(meeting_id: str, source_item_id: str) -> str:
    """Tạo mã bằng chứng dạng ``<meeting>:TR01:<item>``, có mã hóa URL các thành phần.

    Mã chỉ phụ thuộc định danh nguồn. Người dùng sửa nội dung chỉ làm đổi
    ``content_hash``, không đổi mã trích dẫn/bằng chứng.

    Đầu vào: meeting_id - mã cuộc họp; source_item_id - mã dòng nguồn.
    Đầu ra: str - mã bằng chứng.
    """

    meeting = quote(meeting_id.strip(), safe="-._~")
    source = quote(source_item_id.strip(), safe="-._~")
    return f"{meeting}:TR01:{source}"


def _compute_content_hash(item: EffectiveTranscriptItem, normalized_text: str) -> str:
    """Tính mã băm SHA-256 ổn định của nội dung dòng (text, người nói, mốc thời gian, tham chiếu...).

    Dùng JSON sắp khóa cố định nên cùng nội dung luôn cho cùng mã băm.

    Đầu vào: item - dòng effective; normalized_text - văn bản đã chuẩn hóa.
    Đầu ra: str - mã băm SHA-256 dạng hex.
    """

    payload = {
        "source_item_id": item.item_id,
        "text_exact": item.text,
        "text_normalized": normalized_text,
        "speaker": item.speaker,
        "speaker_role": item.speaker_role,
        "speaker_track": item.speaker_track,
        "start_ms": item.start_ms,
        "end_ms": item.end_ms,
        "point_id": item.point_id,
        "ref_id": item.ref_id,
        "ref_ids": item.ref_ids,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_evidence_items(
    meeting_id: str,
    snapshot: tuple[EffectiveTranscriptItem, ...],
) -> tuple[EvidenceItem, ...]:
    """Tạo danh sách bằng chứng (registry) có mã ổn định, giữ nguyên văn để trích dẫn.

    Đầu vào:
        meeting_id: mã cuộc họp, không được rỗng.
        snapshot: các dòng effective từ stage 1.

    Đầu ra: tuple ``EvidenceItem``, cùng số lượng và thứ tự với ``snapshot``.

    Lỗi:
        ValueError nếu meeting_id rỗng, có item_id trùng, có ``end_ms`` sớm hơn
        ``start_ms``, hoặc hai dòng cho ra cùng mã bằng chứng.
    """


    if not meeting_id.strip():
        raise ValueError("meeting_id must be non-empty")

    seen_source_ids: set[str] = set()
    seen_evidence_ids: set[str] = set()
    evidence: list[EvidenceItem] = []

    for item in snapshot:
        if item.item_id in seen_source_ids:
            raise ValueError(f"duplicate source item id: {item.item_id!r}")
        if (
            item.start_ms is not None
            and item.end_ms is not None
            and item.end_ms < item.start_ms
        ):
            raise ValueError(
                f"item {item.item_id!r} has end_ms earlier than start_ms"
            )

        evidence_id = _make_evidence_id(meeting_id, item.item_id)
        if evidence_id in seen_evidence_ids:
            raise ValueError(f"evidence id collision: {evidence_id!r}")

        normalized_text = _normalize_evidence_text(item.text)
        evidence.append(
            EvidenceItem(
                evidence_id=evidence_id,
                source_item_id=item.item_id,
                text=normalized_text,
                speaker=item.speaker,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                point_id=item.point_id,
                ref_id=item.ref_id,
                provenance=item.provenance,
                revision=item.revision,
                text_exact=item.text,
                content_hash=_compute_content_hash(item, normalized_text),
                speaker_role=item.speaker_role,
                speaker_track=item.speaker_track,
                ref_ids=item.ref_ids,
            )
        )
        seen_source_ids.add(item.item_id)
        seen_evidence_ids.add(evidence_id)

    return tuple(evidence)



__all__ = [
    "build_evidence_items",
]
