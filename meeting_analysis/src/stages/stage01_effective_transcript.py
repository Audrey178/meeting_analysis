"""Stage 1: chuyển các dòng transcript thô thành dạng "hiệu lực" (effective).

Các chỉnh sửa theo từng trường (text, người nói) do người duyệt được chồng lên
bản gốc tại đây và ghi lại bằng ``FieldProvenance``, để mọi đoạn phía sau đều
truy được nó đến từ kết quả ASR gốc hay từ bản sửa của con người. Sau stage này
không còn bước nào đọc lại các dòng thô nữa.
"""

from __future__ import annotations

import re
import unicodedata

from ..utils.contracts import (
    EffectiveTranscriptItem,
    FieldProvenance,
    Provenance,
    RawTranscriptItem,
)
from ._shared import SPACE_RE

_UNKNOWN_SPEAKER_RE = re.compile(
    r"^(?:người nói (?:không|chưa) xác định|(?:unknown|unidentified) speaker|speaker unknown)(?: \d+)?$",
    re.IGNORECASE,
)


def _get_first_nonempty_metadata_text(item: RawTranscriptItem, *keys: str) -> str | None:
    """Lấy giá trị chuỗi không rỗng đầu tiên trong metadata của dòng, theo thứ tự các khóa.

    Đầu vào:
        item: dòng transcript thô.
        keys: các khóa metadata cần thử, theo thứ tự ưu tiên.

    Đầu ra: chuỗi đã bỏ khoảng trắng hai đầu của khóa đầu tiên có giá trị chuỗi
        không rỗng, hoặc None nếu không khóa nào có.
    """

    metadata = dict(item.metadata)
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_speaker_role(value: str | None) -> str | None:
    """Chuẩn hóa vai trò người nói về tên chuẩn ("chair", "presenter", "delegate").

    Nhận cả tên tiếng Việt có dấu/không dấu ("chủ trì", "chu tri"...). Vai trò
    không nằm trong bảng thì giữ lại dạng đã chuẩn hóa (NFC, chữ thường).

    Đầu vào: value - vai trò gốc, có thể None.
    Đầu ra: vai trò chuẩn, hoặc None nếu đầu vào None/rỗng.
    """

    if value is None:
        return None
    normalized = SPACE_RE.sub(
        " ", unicodedata.normalize("NFC", value).strip().lower()
    )
    aliases = {
        "chair": "chair",
        "chủ trì": "chair",
        "chu tri": "chair",
        "presenter": "presenter",
        "báo cáo viên": "presenter",
        "bao cao vien": "presenter",
        "delegate": "delegate",
        "đại biểu": "delegate",
        "dai bieu": "delegate",
    }
    return aliases.get(normalized, normalized or None)


def _clean_speaker_name(value: str | None) -> str | None:
    """Làm sạch tên người nói và loại các nhãn "người nói không xác định".

    Đầu vào: value - tên người nói gốc, có thể None.
    Đầu ra: tên đã chuẩn hóa NFC và gộp khoảng trắng; None nếu rỗng hoặc là nhãn
        kiểu "Người nói không xác định 01", "Unknown speaker".
    """

    if value is None:
        return None
    normalized = SPACE_RE.sub(
        " ", unicodedata.normalize("NFC", value).strip()
    )
    if not normalized or _UNKNOWN_SPEAKER_RE.fullmatch(normalized):
        return None
    return normalized


def resolve_effective_transcript(
    raw_items: tuple[RawTranscriptItem, ...],
) -> tuple[EffectiveTranscriptItem, ...]:
    """Dựng danh sách dòng "hiệu lực" từ các dòng thô, không sửa dữ liệu thô.

    Với mỗi dòng, text và người nói được chồng bản người duyệt lên TÁCH RỜI nhau:
    có ``reviewed_text`` thì dùng nó thay ``text``, có ``reviewed_speaker`` thì
    dùng nó thay ``speaker``. Nguồn gốc của từng trường (ASR gốc, người duyệt,
    mô hình nhận diện người nói...) được ghi vào ``FieldProvenance``.

    Đầu vào: raw_items - các dòng transcript thô, theo thứ tự.
    Đầu ra: tuple ``EffectiveTranscriptItem``, cùng số lượng và thứ tự với đầu vào.
    """


    resolved: list[EffectiveTranscriptItem] = []
    for item in raw_items:
        source_schema = _get_first_nonempty_metadata_text(item, "source_schema")
        imported_effective = source_schema == "stt_export"
        source_provenance = (
            Provenance.SOURCE_EXPORT_EFFECTIVE
            if imported_effective
            else Provenance.RAW_STT
        )
        text_is_reviewed = item.reviewed_text is not None
        speaker_is_reviewed = item.reviewed_speaker is not None
        text = item.reviewed_text if text_is_reviewed else item.text
        speaker_raw = item.reviewed_speaker if speaker_is_reviewed else item.speaker
        speaker = _clean_speaker_name(speaker_raw)
        explicit_track = _get_first_nonempty_metadata_text(item, "speaker_track")
        speaker_track = explicit_track or (
            SPACE_RE.sub(
                " ", unicodedata.normalize("NFC", speaker_raw).strip()
            )
            if isinstance(speaker_raw, str) and speaker_raw.strip()
            else speaker
        )
        if speaker_track is not None:
            speaker_track = unicodedata.normalize("NFC", speaker_track)
        role = _normalize_speaker_role(
            _get_first_nonempty_metadata_text(item, "speaker_role", "role_inferred")
        )

        resolved.append(
            EffectiveTranscriptItem(
                item_id=item.item_id,
                text=text,
                speaker=speaker,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                point_id=item.point_id,
                ref_id=item.ref_id,
                provenance=FieldProvenance(
                    text=(
                        Provenance.HUMAN_REVIEW
                        if text_is_reviewed
                        else source_provenance
                    ),
                    speaker=(
                        Provenance.HUMAN_REVIEW
                        if speaker_is_reviewed
                        else (
                            source_provenance
                            if imported_effective
                            else (
                                Provenance.SPEAKER_MODEL
                                if speaker is not None
                                else Provenance.UNKNOWN
                            )
                        )
                    ),
                    start_ms=(
                        source_provenance
                        if item.start_ms is not None
                        else Provenance.UNKNOWN
                    ),
                    end_ms=(
                        source_provenance
                        if item.end_ms is not None
                        else Provenance.UNKNOWN
                    ),
                ),
                source=item,
                revision=item.revision,
                speaker_role=role,
                speaker_track=speaker_track,
                ref_ids=item.ref_ids,
            )
        )
    return tuple(resolved)



__all__ = [
    "resolve_effective_transcript",
]
