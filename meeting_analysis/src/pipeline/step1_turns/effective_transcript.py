"""Bước 1.1: từ các dòng bản ghi gốc, dựng ra các dòng "hiệu lực" dùng cho các bước sau: lấy nội dung
đã được người duyệt sửa nếu có, làm sạch tên người nói, chuẩn hoá vai trò. Dữ liệu gốc không bị
thay đổi.
"""

from __future__ import annotations

import re
import unicodedata

from ...utils.contracts import (
    EffectiveTranscriptItem,
    FieldProvenance,
    Provenance,
    RawTranscriptItem,
)
from ..shared.text import SPACE_RE

_UNKNOWN_SPEAKER_RE = re.compile(
    r"^(?:người nói (?:không|chưa) xác định|(?:unknown|unidentified) speaker|speaker unknown)(?: \d+)?$",
    re.IGNORECASE,
)


def _get_first_nonempty_metadata_text(item: RawTranscriptItem, *keys: str) -> str | None:
    """Lấy giá trị chuỗi không rỗng đầu tiên trong metadata của dòng, theo thứ tự khóa.

    Args:
        item: Dòng bản ghi thô.
        *keys: Các khóa metadata cần thử, khóa trước được ưu tiên.

    Returns:
        Giá trị đã bỏ khoảng trắng hai đầu của khóa đầu tiên có chuỗi không rỗng; None nếu không
        khóa nào có (giá trị không phải chuỗi cũng bị bỏ qua).
    """

    metadata = dict(item.metadata)
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_speaker_role(value: str | None) -> str | None:
    """Đưa vai trò người nói về một trong các tên chuẩn "chair", "presenter", "delegate".

    Nhận cả tên tiếng Việt có dấu lẫn không dấu (ví dụ "Chủ trì", "chu tri"). Vai trò ngoài
    bảng không bị bỏ mà giữ ở dạng đã chuẩn hóa (NFC, chữ thường, gộp khoảng trắng).

    Args:
        value: Vai trò gốc lấy từ metadata, có thể None.

    Returns:
        Vai trò đã chuẩn hóa; None nếu đầu vào None hoặc chỉ toàn khoảng trắng.
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
    """Làm sạch tên người nói và coi các nhãn kiểu "người nói không xác định" là không có tên.

    Args:
        value: Tên người nói gốc, có thể None.

    Returns:
        Tên đã chuẩn hóa NFC và gộp khoảng trắng; None nếu rỗng hoặc là nhãn giữ chỗ như
        "Người nói không xác định 01", "Unknown speaker".
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
    """Dựng các dòng "hiệu lực" từ các dòng bản ghi thô, giữ nguyên dữ liệu thô.

    Với mỗi dòng: lấy nội dung và tên người nói do người duyệt sửa nếu có, nếu không thì dùng bản
    gốc; làm sạch tên, chuẩn hóa vai trò, xác định mã người nói (ưu tiên mã tham chiếu của dòng,
    sau đó mới tới mã trong metadata). Mỗi trường được ghi kèm nguồn gốc (người duyệt, bản xuất
    đã hiệu lực sẵn, kết quả nhận dạng giọng nói thô, mô hình nhận người nói, hoặc chưa biết) để
    bước sau truy vết.
    Dòng rỗng vẫn được giữ; việc bỏ dòng rỗng do bước gộp lượt nói đảm nhận.

    Args:
        raw_items: Các dòng bản ghi thô theo thứ tự.

    Returns:
        Tuple dòng hiệu lực, cùng số lượng và thứ tự với ``raw_items``; mỗi dòng giữ tham chiếu tới
        dòng thô gốc.
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
        speaker_id = (item.ref_ids[0] if item.ref_ids else item.ref_id) or _get_first_nonempty_metadata_text(
            item, "speaker_id"
        )
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
                ref_ids=item.ref_ids,
                speaker_id=speaker_id,
            )
        )
    return tuple(resolved)



__all__ = [
    "resolve_effective_transcript",
]
