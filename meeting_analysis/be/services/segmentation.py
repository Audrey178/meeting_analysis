"""Phần chung đầu pipeline: transcript -> lượt nói -> các đoạn chủ đề (chưa gán nhãn).

    parse_transcript_payload               (payload -> dòng thô)
    stage01 resolve_effective_transcript   (dòng thô -> dòng hiệu lực)
    stage02 build_evidence_items           (dòng hiệu lực -> bằng chứng có mã ổn định)
    stage03 build_speaker_turns            (bằng chứng -> lượt nói)
    cắt chủ đề trên các lượt nói, một trong hai bộ:
        - DialSTART (experiments/dialstart, checkpoint model_vn3/best.pt) nếu
          ``topic_segmenter`` là ``DialStartSegmenter`` -- mặc định khi chạy API
          (``TOPIC_SEGMENTER=dialstart``)
        - TreeSeg (experiments/treeseg_turn_level/treeseg.py) nếu ``topic_segmenter`` là None

``services/pipeline_v3.py`` gọi ``segment_meeting`` rồi gán nhãn và chạy các agent v3.
"""

from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass

_BE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BE_DIR.parent
for _dir in (_BE_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from experiments.treeseg_turn_level import boundaries_to_topic_segments, segment_turns_with_treeseg

from src.stages.stage01_effective_transcript import resolve_effective_transcript
from src.stages.stage02_evidence import build_evidence_items
from src.stages.stage03_speaker_turns import build_speaker_turns
from src.utils.adapters import parse_transcript_payload
from src.utils.config import load_config
from src.utils.ports import EmbeddingAdapter

from experiments.dialstart import DialStartSegmenter

_DEFAULT_CONFIG_PATH = _REPO_ROOT / "configs" / "default.json"

# Ngưỡng gain càng nhỏ cut càng vụn (ngược lại cut càng thô)
_TREESEG_MIN_RELATIVE_GAIN = 0.022

# Tách thô nếu đoạn vượt quá số ký tự cho phép.
_TREESEG_MAX_SEGMENT_CHARS = 35000

# Cắt DialSTART (xem ``select_boundaries`` trong experiments/dialstart/dialstart_segmenter.py).
# Checkpoint chỉ được eval với số ranh giới oracle, nên khi chạy thật tự chọn ranh giới:
#   - làm mượt điểm khe (cửa sổ 5 lúc đo, nay 3): trên 12 cuộc họp Quốc hội có nhãn, bỏ bước này F1
#     segeval giảm 0.418 -> 0.297 -- tác động lớn nhất;
#   - ngưỡng depth mean + k*std, mỗi đoạn >= _DIALSTART_MIN_SIZE lượt;
#   - bỏ đoạn vụn < _dialstart_min_segment_chars ký tự (STT có nhiều lượt rất ngắn; chưa
#     kiểm chứng bằng nhãn vì lượt nói Quốc hội vốn dài);
#   - gộp đoạn liền kề có cosine embedding chủ đề >= _DIALSTART_MERGE_THRESHOLD (Quốc hội:
#     +0.025 F1).
_DIALSTART_SMOOTH_WINDOW = 3
_DIALSTART_THRESHOLD_STD = 1.0
_DIALSTART_MIN_SIZE = 4
# Sàn ký tự mỗi đoạn = tổng ký tự / _DIALSTART_MIN_SEGMENT_FRACTION, kẹp trong
# [_DIALSTART_MIN_SEGMENT_CHARS_FLOOR, _DIALSTART_MIN_SEGMENT_CHARS_CAP]. Cuộc họp dài
# (Quốc hội ~236k) chạm trần 10000 như bộ cũ.
_DIALSTART_MIN_SEGMENT_FRACTION = 15
_DIALSTART_MIN_SEGMENT_CHARS_FLOOR = 1500
_DIALSTART_MIN_SEGMENT_CHARS_CAP = 10000
_DIALSTART_MERGE_THRESHOLD = None


def _dialstart_min_segment_chars(item_chars: list[int]) -> int:
    """Sàn ký tự mỗi đoạn DialSTART, tỉ lệ theo độ dài cuộc họp.

    Đầu vào: item_chars - độ dài (ký tự) từng lượt nói.
    Đầu ra: số ký tự tối thiểu của một đoạn chủ đề.
    """

    scaled = sum(item_chars) // _DIALSTART_MIN_SEGMENT_FRACTION
    return max(_DIALSTART_MIN_SEGMENT_CHARS_FLOOR, min(_DIALSTART_MIN_SEGMENT_CHARS_CAP, scaled))


@dataclass
class SegmentedMeeting:
    """Transcript đã dựng lượt nói và cắt chủ đề, CHƯA gán nhãn.

    Các trường:
        meeting_id, revision_id: mã cuộc họp / phiên bản transcript.
        turns: ``SpeakerTurn`` của stage03, theo thứ tự.
        segments: ``TopicSegment`` phủ kín ``turns``.
        config: cấu hình pipeline đã nạp (``configs/default.json``).
    """

    meeting_id: str
    revision_id: str
    turns: tuple
    segments: list
    config: object


def load_pipeline_config():
    """Nạp cấu hình pipeline từ ``configs/default.json`` (mặc định nếu không có file)."""

    return load_config(str(_DEFAULT_CONFIG_PATH) if _DEFAULT_CONFIG_PATH.is_file() else None)


def build_meeting_turns(payload: dict) -> tuple[str, str, tuple, object]:
    """Đọc transcript -> stage01-03 dựng lượt nói (chưa cắt chủ đề).

    Tách khỏi ``segment_meeting`` để benchmark (``eval/bench/run.py``) dựng đúng cùng dãy lượt
    nói rồi tự cắt chủ đề theo gold hoặc gộp cả cuộc họp thành một chủ đề.

    Đầu vào: payload - transcript dạng dict (``AnalyzeV3Request.model_dump()``).
    Đầu ra: (meeting_id, revision_id, lượt nói theo thứ tự, cấu hình pipeline đã nạp).
    Lỗi: ``ValueError`` nếu transcript không hợp lệ.
    """

    meeting_id, revision_id, raw_items = parse_transcript_payload(payload)
    config = load_pipeline_config()
    effective = resolve_effective_transcript(raw_items)
    evidence = build_evidence_items(meeting_id, effective)
    turns = build_speaker_turns(evidence, config.turn_builder)
    return meeting_id, revision_id, tuple(turns), config


def segment_meeting(
    payload: dict,
    *,
    embedding_adapter: EmbeddingAdapter,
    topic_segmenter=None,
) -> SegmentedMeeting:
    """Đọc transcript -> stage01-03 dựng lượt nói -> cắt chủ đề (chưa gán nhãn).

    Pipeline v3 (``services/pipeline_v3.py``) gọi hàm này rồi gán nhãn trong từng chủ đề.

    Đầu vào:
        payload: transcript dạng dict (``AnalyzeV3Request.model_dump()``).
        embedding_adapter: adapter embedding cho TreeSeg (không dùng với DialSTART).
        topic_segmenter: ``DialStartSegmenter`` đã nạp checkpoint; None thì dùng TreeSeg.
    Đầu ra: ``SegmentedMeeting``.
    Lỗi: ``LLMUpstreamError`` nếu bước embedding lỗi; ``ValueError`` nếu transcript không hợp lệ.
    """

    meeting_id, revision_id, turns, config = build_meeting_turns(payload)

    # Đo trên dòng "người nói: nội dung" giống TreeSeg, vì đó là thứ vào prompt.
    item_chars = [len(f"{turn.speaker}: {turn.text_exact}") + 1 for turn in turns]
    
    texts = [turn.text_exact for turn in turns]
    if isinstance(topic_segmenter, DialStartSegmenter):
        boundaries = topic_segmenter.predict_boundaries(
            texts,
            min_size=_DIALSTART_MIN_SIZE,
            threshold_std=_DIALSTART_THRESHOLD_STD,
            smooth_window=_DIALSTART_SMOOTH_WINDOW,
            min_segment_chars=_dialstart_min_segment_chars(item_chars),
            merge_threshold=_DIALSTART_MERGE_THRESHOLD,
            max_segment_chars=_TREESEG_MAX_SEGMENT_CHARS,
            item_chars=item_chars,
        )
        segments = boundaries_to_topic_segments(turns, boundaries)
    else:
        segments = segment_turns_with_treeseg(
            turns,
            embed_fn=embedding_adapter.embed,
            width=5,
            min_size=4,
            min_relative_gain=_TREESEG_MIN_RELATIVE_GAIN,
            max_segment_chars=_TREESEG_MAX_SEGMENT_CHARS,
        )
    return SegmentedMeeting(meeting_id, revision_id, tuple(turns), list(segments), config)
