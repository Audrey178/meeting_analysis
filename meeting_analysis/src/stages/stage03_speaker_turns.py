"""Stage 3: gộp các dòng bằng chứng liên tiếp thành lượt nói (speaker turn).

Việc gộp cố ý thận trọng: hai dòng chỉ được gộp khi cùng người nói và khoảng cách
giữa chúng nhỏ hơn ``max_gap_ms``. Người nói không xác định hoặc thiếu mốc thời
gian không được gộp trừ khi cấu hình cho phép, vì gộp sai sẽ âm thầm gán lời của
người này cho người khác.
"""

from __future__ import annotations

from ..utils.config import TurnBuilderConfig
from ..utils.contracts import EvidenceItem, SpeakerTurn
from ._shared import known_max, known_min


def _should_merge_into_same_turn(
    previous: EvidenceItem,
    current: EvidenceItem,
    config: TurnBuilderConfig,
) -> bool:
    """Quyết định dòng ``current`` có được gộp vào cùng lượt nói với dòng ``previous`` không.

    Chỉ gộp khi: cùng người nói (theo track), cùng vai trò, không thuộc hai
    ``point_id``/``ref_ids`` khác nhau, người nói không phải "không xác định" (trừ
    khi cấu hình cho phép), và khoảng cách thời gian không quá ``max_gap_ms``
    (thiếu mốc thời gian thì theo ``merge_when_timestamp_missing``).

    Đầu vào:
        previous: dòng bằng chứng liền trước (cuối lượt nói đang xét).
        current: dòng bằng chứng đang xét.
        config: cấu hình dựng lượt nói.

    Đầu ra: bool - True nếu nên gộp.
    """

    previous_track = previous.speaker_track or previous.speaker
    current_track = current.speaker_track or current.speaker
    if previous_track != current_track:
        return False
    if previous.speaker_role != current.speaker_role:
        return False
    if (
        previous.point_id is not None
        and current.point_id is not None
        and previous.point_id != current.point_id
    ):
        return False
    if previous.ref_ids and current.ref_ids and previous.ref_ids[0] != current.ref_ids[0]:
        return False
    if previous_track is None and not config.merge_unknown_speakers:
        return False
    if previous.end_ms is None or current.start_ms is None:
        return config.merge_when_timestamp_missing
    return current.start_ms - previous.end_ms <= config.max_gap_ms


TURN_ITEM_SEPARATOR = " "
"""Chuỗi ``build_speaker_turns`` chèn giữa hai dòng bằng chứng liên tiếp trong cùng một
lượt nói. Stage 4 tính lại vị trí (offset) từng dòng dựa vào chuỗi này, nên hai nơi
không bao giờ được lệch nhau: hãy import hằng này, không gõ lại chuỗi."""


def build_speaker_turns(
    evidence: tuple[EvidenceItem, ...],
    config: TurnBuilderConfig,
) -> tuple[SpeakerTurn, ...]:
    """Gộp các dòng bằng chứng liền kề của cùng một người nói thành các lượt nói.

    Dùng một máy trạng thái nhỏ, tất định: duyệt tuần tự, dòng nào ``_should_merge_into_same_turn``
    với dòng liền trước thì nối vào lượt hiện tại, ngược lại mở lượt mới. Dòng
    trống bị bỏ qua. Mã lượt nói có dạng ``TURN_000001`` tăng dần.

    Đầu vào:
        evidence: các dòng bằng chứng theo thứ tự thời gian.
        config: cấu hình dựng lượt nói (khoảng cách tối đa, có gộp người lạ không...).

    Đầu ra: tuple ``SpeakerTurn``; tuple rỗng nếu không có dòng nào có nội dung.
    """


    evidence = tuple(item for item in evidence if item.text.strip())
    if not evidence:
        return ()

    groups: list[list[EvidenceItem]] = [[evidence[0]]]
    for item in evidence[1:]:
        if _should_merge_into_same_turn(groups[-1][-1], item, config):
            groups[-1].append(item)
        else:
            groups.append([item])

    turns: list[SpeakerTurn] = []
    for index, group in enumerate(groups, start=1):
        turns.append(
            SpeakerTurn(
                turn_id=f"TURN_{index:06d}",
                speaker=group[0].speaker,
                text_exact=TURN_ITEM_SEPARATOR.join(
                    item.text_exact if item.text_exact is not None else item.text
                    for item in group
                ),
                evidence_ids=tuple(item.evidence_id for item in group),
                start_ms=known_min([item.start_ms for item in group]),
                end_ms=known_max([item.end_ms for item in group]),
                speaker_role=group[0].speaker_role,
                speaker_track=group[0].speaker_track,
            )
        )
    return tuple(turns)



__all__ = [
    "TURN_ITEM_SEPARATOR",
    "build_speaker_turns",
]
