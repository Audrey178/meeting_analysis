"""Các kiểu dữ liệu không sửa được, dùng chung cho cả pipeline: dòng bản ghi, lượt nói, đoạn chủ đề và
tên chủ đề.

Có ba cấp: mỗi dòng bản ghi (đơn vị nhỏ nhất, dùng để trích dẫn) thuộc một lượt nói (các dòng liền
nhau của cùng một người), mỗi lượt nói thuộc một đoạn chủ đề. Thời gian tính bằng mili-giây.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias


Scalar: TypeAlias = str | int | float | bool | None
Metadata: TypeAlias = tuple[tuple[str, Scalar], ...]


class Provenance(StrEnum):
    """Nguồn gốc giá trị của một trường trong dòng hiệu lực (``EffectiveTranscriptItem``).

    Attributes:
        RAW_STT: Lấy nguyên từ bản chuyển giọng nói thành chữ.
        SPEAKER_MODEL: Nhãn người nói có sẵn trong đầu vào, do hệ thống nhận diện người nói gán.
        HUMAN_REVIEW: Do người duyệt sửa.
        SOURCE_EXPORT_EFFECTIVE: Lấy từ file xuất của hệ thống chuyển giọng nói, vốn đã là bản hiệu lực.
        UNKNOWN: Không rõ nguồn.
    """

    RAW_STT = "raw_stt"
    SPEAKER_MODEL = "speaker_model"
    HUMAN_REVIEW = "human_review"
    SOURCE_EXPORT_EFFECTIVE = "source_export_effective"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FieldProvenance:
    """Nguồn gốc của từng trường trong một dòng hiệu lực.

    Attributes:
        text: Nguồn của nội dung lời nói.
        speaker: Nguồn của nhãn người nói.
        start_ms: Nguồn của mốc bắt đầu; mặc định là bản ghi thô.
        end_ms: Nguồn của mốc kết thúc; mặc định là bản ghi thô.
    """

    text: Provenance
    speaker: Provenance
    start_ms: Provenance = Provenance.RAW_STT
    end_ms: Provenance = Provenance.RAW_STT


@dataclass(frozen=True, slots=True)
class RawTranscriptItem:
    """Một dòng bản ghi thô đúng như file đầu vào, kèm bản người duyệt sửa (nếu có).

    Chưa áp bản sửa: việc chồng bản người duyệt lên dòng thô làm ở bước dựng dòng hiệu lực.

    Attributes:
        item_id: Mã dòng trong đầu vào, giữ nguyên để trích dẫn.
        text: Nội dung nguyên văn.
        speaker: Nhãn người nói trong đầu vào; None nếu không có.
        start_ms: Mốc bắt đầu (mili-giây); None nếu không biết.
        end_ms: Mốc kết thúc (mili-giây); None nếu không biết.
        ref_id: Mã người nói chính, bằng ``ref_ids[0]``; None nếu không có.
        reviewed_text: Nội dung do người duyệt sửa; None thì dùng ``text``.
        reviewed_speaker: Nhãn người nói do người duyệt sửa; None thì dùng ``speaker``.
        revision: Số lần sửa của dòng, 0 nếu chưa sửa.
        metadata: Các trường lạ (giá trị vô hướng) của đầu vào, giữ lại để bước sau đọc nếu cần.
        ref_ids: Mọi mã người nói của dòng, đã bỏ trùng, giữ thứ tự (xem
            ``EffectiveTranscriptItem.speaker_id``).
    """

    item_id: str
    text: str
    speaker: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    ref_id: str | None = None
    reviewed_text: str | None = None
    reviewed_speaker: str | None = None
    revision: int = 0
    metadata: Metadata = ()
    ref_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EffectiveTranscriptItem:
    """Một dòng "hiệu lực": dòng thô đã được chồng bản sửa của người duyệt lên.

    Đây là dữ liệu mà các bước sau đọc. Dòng thô vẫn được giữ trong ``source`` để đối chiếu.

    Attributes:
        item_id: Mã dòng, giống dòng thô.
        text: Nội dung sau khi áp bản sửa.
        speaker: Nhãn người nói sau khi áp bản sửa; None nếu không biết.
        start_ms: Mốc bắt đầu (mili-giây); None nếu không biết.
        end_ms: Mốc kết thúc (mili-giây); None nếu không biết.
        ref_id: Mã người nói chính lấy từ dòng thô.
        provenance: Mỗi trường lấy từ nguồn nào.
        source: Dòng thô gốc.
        revision: Số lần sửa.
        speaker_role: Vai trò người nói nếu biết; None nếu không.
        ref_ids: Mọi mã người nói của dòng.
        speaker_id: Mã người nói, cố định theo người trong suốt cuộc họp; None nếu đầu vào không có mã.
    """

    item_id: str
    text: str
    speaker: str | None
    start_ms: int | None
    end_ms: int | None
    ref_id: str | None
    provenance: FieldProvenance
    source: RawTranscriptItem
    revision: int = 0
    speaker_role: str | None = None
    ref_ids: tuple[str, ...] = ()
    # Mã người nói (cố định theo người trong cuộc họp): ``ref_ids[0]``, thiếu thì ``speaker_id`` của dòng.
    # Cùng hệ mã với ``AttendeePerson.person_id`` và ``MeetingChair.person_id``.
    speaker_id: str | None = None


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    """Một lượt nói (turn): các dòng hiệu lực liền nhau của cùng một người.

    Attributes:
        turn_id: Mã lượt nói, dạng ``TURN_000001``.
        speaker: Nhãn người nói đã làm sạch; thêm hậu tố " #2", " #3"... nếu trùng nhãn với người khác.
        text_exact: Nguyên văn các dòng trong lượt, nối bằng dấu cách.
        start_ms: Mốc bắt đầu (mili-giây); None nếu không biết.
        end_ms: Mốc kết thúc (mili-giây); None nếu không biết.
        speaker_role: Vai trò người nói nếu biết; None nếu không.
        speaker_id: Mã người nói của lượt (xem ``EffectiveTranscriptItem.speaker_id``).
        source_items: Các cặp (item_id, nguyên văn) của từng dòng trong lượt, theo thứ tự; dùng để
            trích dẫn về đúng dòng gốc.
    """

    turn_id: str
    speaker: str | None
    text_exact: str
    start_ms: int | None
    end_ms: int | None
    speaker_role: str | None = None
    # Mã người nói của lượt (xem ``EffectiveTranscriptItem.speaker_id``). Hai người khác mã mà cùng
    # nhãn thì ``speaker`` của người xuất hiện sau được thêm hậu tố " #2", " #3"... để nhãn là duy nhất.
    speaker_id: str | None = None
    source_items: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class TopicSegment:
    """Một đoạn chủ đề (topic): dãy lượt nói liền nhau, cắt ở bước 2, chưa đặt tên.

    Attributes:
        segment_id: Mã đoạn, dạng ``TOPIC_SEG_000000``.
        turn_ids: Mã các lượt nói trong đoạn, theo thứ tự.
        text: Nội dung đoạn, mỗi dòng dạng "người nói: nội dung".
        start_turn: Chỉ số lượt nói đầu tiên (tính từ 0, thuộc đoạn).
        end_turn: Chỉ số ngay sau lượt cuối, tức đoạn là ``[start_turn, end_turn)``.
        token_count: Chưa bước nào điền, luôn None.
        segmentation_method: Chưa bước nào điền, luôn None; API vẫn trả trường này trong
            ``extensions``.
        boundary_score: Chưa bước nào điền, luôn None; API vẫn trả trường này trong ``extensions``.
    """

    segment_id: str
    turn_ids: tuple[str, ...] | None = None
    text: str | None = None
    start_turn: int | None = None
    end_turn: int | None = None
    token_count: int | None = None
    segmentation_method: str | None = None
    boundary_score: float | None = None


@dataclass(frozen=True, slots=True)
class TopicLabel:
    """Tên của một đoạn chủ đề (bước 3): tiêu đề và tóm tắt, thường do LLM sinh.

    Attributes:
        segment_id: Mã đoạn chủ đề được đặt tên.
        title: Tiêu đề ngắn.
        summary: Tóm tắt nội dung đoạn.
        text: Văn bản của đoạn đã đưa cho bộ đặt tên.
        evidence_turn_ids: Chưa dùng, luôn None.
        method: Cách sinh tên: ``"llm_structured"``, hoặc ``"keyword_fallback_after_guard_failure"``
            khi phải dùng tên dự phòng.
        model_name: Mô hình đã sinh tên; None nếu là tên dự phòng.
    """

    segment_id: str
    title: str
    summary: str
    text: str
    evidence_turn_ids: tuple[str, ...] | None
    method: str
    model_name: str | None = None


__all__ = [
    "EffectiveTranscriptItem",
    "FieldProvenance",
    "Provenance",
    "RawTranscriptItem",
    "Scalar",
    "SpeakerTurn",
    "TopicLabel",
    "TopicSegment",
]
