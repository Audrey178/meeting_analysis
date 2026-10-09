"""Quy trình từ transcript đến đầu ra cuộc họp (được API gọi qua ``run_meeting_analysis_pipeline``):

    stage01 resolve_effective_transcript   (dòng thô -> dòng hiệu lực)
    stage02 build_evidence_items           (dòng hiệu lực -> bằng chứng có mã ổn định)
    stage03 build_speaker_turns            (bằng chứng -> lượt nói)
    cắt chủ đề trên các lượt nói, một trong ba bộ:
        - DialSTART (experiments/006_dialstart, checkpoint model_vn3/best.pt) nếu
          ``topic_segmenter`` là ``DialStartSegmenter`` -- mặc định khi chạy API
          (``TOPIC_SEGMENTER=dialstart``)
        - DialTreeSeg (experiments/007_dialtreeseg) nếu ``topic_segmenter`` là
          ``DialTreeSegSegmenter`` (``TOPIC_SEGMENTER=dialtreeseg``): phương pháp chọn trong
          ``experiments/007_dialtreeseg/config.json`` (``backend.method``)
        - TreeSeg (experiments/treeseg_turn_level/treeseg.py) nếu ``topic_segmenter`` là None
    stage07 label_topics                   (đặt tiêu đề + tóm tắt cho từng chủ đề)
    Các agent LangGraph hướng-C (graph.py: Content / Action / Decision /
        Evidence-Check / Debate+Judge) -- xem ../DESIGN.md ("M6")
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

from src.agentic import (
    ActionItemCandidate,
    DebateRecord,
    DecisionCandidate,
    MeetingState,
    SpeakerSection,
    build_graph,
    merge_duplicate_assignments,
    merge_duplicate_decisions,
)
from src.stages.stage01_effective_transcript import resolve_effective_transcript
from src.stages.stage02_evidence import build_evidence_items
from src.stages.stage03_speaker_turns import build_speaker_turns
from src.stages.stage07_topic_labeling import label_topics
from src.utils.adapters import parse_transcript_payload
from src.utils.config import load_config
from src.utils.ports import EmbeddingAdapter, LLMAdapter, TopicLabelAdapter


from experiments.dialstart import DialStartSegmenter

_DEFAULT_CONFIG_PATH = _REPO_ROOT / "configs" / "default.json"

# Ngưỡng gain càng nhỏ cut càng vụn (ngược lại cut càng thô)
_TREESEG_MIN_RELATIVE_GAIN = 0.022

# Tách thô nếu đoạn vượt quá số ký tự cho phép.
_TREESEG_MAX_SEGMENT_CHARS = 35000

# Cắt DialSTART (xem ``select_boundaries`` trong experiments/006_dialstart/dialstart_segmenter.py).
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


def _serialize_speaker_section(section: SpeakerSection) -> dict:
    """Chuyển một ``SpeakerSection`` thành dict JSON cho phản hồi API.

    Đầu vào: section - các luận điểm của một người nói trong một chủ đề.
    Đầu ra: dict gồm ``initials``, ``full_name`` và ``points`` (mỗi điểm có text,
        evidence_ids, quotes, citation_count).
    """

    return {
        "initials": section.initials,
        "full_name": section.full_name,
        "points": [
            {
                "text": point.text,
                "evidence_ids": list(point.evidence_ids),
                "quotes": list(point.quotes),
                "citation_count": point.citation_count,
            }
            for point in section.points
        ],
    }


def read_meeting_date(payload: dict) -> str | None:
    """Lấy ngày họp ISO "YYYY-MM-DD" từ payload (``AnalyzeRequest.model_dump()`` cho ra ``date``).

    Đầu vào: payload - transcript dạng dict.
    Đầu ra: chuỗi ISO, hoặc None nếu payload không có ngày họp.
    """

    value = payload.get("meeting_date")
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _serialize_action_item(item: ActionItemCandidate) -> dict:
    """Chuyển một ``ActionItemCandidate`` (đã kiểm chứng) thành dict JSON cho phản hồi API.

    Đầu vào: item - một việc được giao, đã qua Evidence-Check (+ Debate/Judge
        nếu uncertain).
    Đầu ra: dict gồm ``segment_id``, ``actor``, ``text``, ``deadline_raw``/``deadline_date``/
        ``deadline_kind``, ``evidence_ids``,
        ``quotes``, ``citation_count``. Không gộp theo người (xem docstring
        module) -- ``actor`` đi kèm TỪNG item thay vì nằm ở một object cha.
    """

    return {
        "segment_id": item.segment_id,
        "actor": item.actor,
        "text": item.text,
        "deadline_raw": item.deadline_raw,
        "deadline_date": item.deadline_date,
        "deadline_kind": item.deadline_kind,
        "status": item.status,
        "confirm_turn_id": item.confirm_turn_id,
        "verification": item.verification,
        "evidence_ids": list(item.evidence_ids),
        "quotes": list(item.quotes),
        "citation_count": len(item.evidence_ids),
    }


def _serialize_decision(item: DecisionCandidate) -> dict:
    """Chuyển một ``DecisionCandidate`` (đã kiểm chứng) thành dict JSON cho phản hồi API.

    Đầu vào: item - một quyết định/chốt phương án, đã qua Evidence-Check (+
        Debate/Judge nếu uncertain).
    Đầu ra: dict gồm ``segment_id``, ``text``, ``evidence_ids``, ``quotes``,
        ``citation_count``.
    """

    return {
        "segment_id": item.segment_id,
        "text": item.text,
        "status": item.status,
        "confirm_turn_id": item.confirm_turn_id,
        "verification": item.verification,
        "evidence_ids": list(item.evidence_ids),
        "quotes": list(item.quotes),
        "citation_count": len(item.evidence_ids),
    }


def _serialize_debate_record(record: DebateRecord) -> dict:
    """Chuyển một ``DebateRecord`` thành dict JSON để API báo minh bạch việc kiểm chứng.

    Đầu vào: record - bản ghi debate+judge của một candidate uncertain.
    Đầu ra: dict theo đúng các trường của ``DebateRecord``.
    """

    return {
        "segment_id": record.segment_id,
        "kind": record.kind,
        "candidate_text": record.candidate_text,
        "reasons": list(record.reasons),
        "support_argument": record.support_argument,
        "oppose_argument": record.oppose_argument,
        "kept": record.kept,
        "reasoning": record.reasoning,
        "verdict": record.verdict,
        "final_text": record.final_text,
        "deciding_turn_id": record.deciding_turn_id,
    }


def _group_meeting_development_by_topic(
    segments, labels_by_segment: dict, meeting_development: list[SpeakerSection]
) -> list[dict]:
    """Ghép ``meeting_development`` (danh sách phẳng) với tiêu đề/tóm tắt chủ đề để trả JSON.
    Đầu vào:
        segments: các đoạn chủ đề của cuộc họp, theo đúng thứ tự.
        labels_by_segment: bảng tra segment_id -> TopicLabel (từ stage07).
        meeting_development: ``final_state["meeting_development"]`` (phẳng,
            mọi chủ đề trộn chung).
    Đầu ra: list[dict], mỗi phần tử một chủ đề, theo đúng thứ tự ``segments``.
    """

    sections_by_segment: dict[str, list[SpeakerSection]] = {}
    for section in meeting_development:
        sections_by_segment.setdefault(section.segment_id, []).append(section)

    return [
        {
            "segment_id": segment.segment_id,
            "title": label.title if label else "",
            "summary": label.summary if label else "",
            "speakers": [
                _serialize_speaker_section(section)
                for section in sections_by_segment.get(segment.segment_id, [])
            ],
        }
        for segment in segments
        for label in [labels_by_segment.get(segment.segment_id)]
    ]


@dataclass
class PreparedMeeting:
    """Phần chung của mọi pipeline phía sau: transcript đã dựng lượt nói, cắt chủ đề và gán nhãn.

    Các trường:
        meeting_id, revision_id: mã cuộc họp / phiên bản transcript.
        turns: ``SpeakerTurn`` của stage03, theo thứ tự.
        segments: ``TopicSegment`` phủ kín ``turns``.
        labels_by_segment: segment_id -> ``TopicLabel`` (stage07).
    """

    meeting_id: str
    revision_id: str
    turns: tuple
    segments: list
    labels_by_segment: dict


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


def segment_meeting(
    payload: dict,
    *,
    embedding_adapter: EmbeddingAdapter,
    topic_segmenter=None,
) -> SegmentedMeeting:
    """Đọc transcript -> stage01-03 dựng lượt nói -> cắt chủ đề (chưa gán nhãn).

    Dùng chung cho ``prepare_meeting`` (v1) và pipeline v3
    (``services/pipeline_v3.py``, gán nhãn trong từng chủ đề) để mọi pipeline nhận
    CÙNG lượt nói và cùng ranh giới chủ đề.

    Đầu vào: như ``run_meeting_analysis_pipeline`` (không cần adapter gán nhãn).
    Đầu ra: ``SegmentedMeeting``.
    Lỗi: ``LLMUpstreamError`` nếu bước embedding lỗi; ``ValueError`` nếu transcript không hợp lệ.
    """

    meeting_id, revision_id, raw_items = parse_transcript_payload(payload)
    config = load_pipeline_config()

    effective = resolve_effective_transcript(raw_items)
    evidence = build_evidence_items(meeting_id, effective)
    turns = build_speaker_turns(evidence, config.turn_builder)

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
    elif topic_segmenter is not None:
        # DialTreeSeg: tham số cắt nằm trong experiments/007_dialtreeseg/config.json, chỉ cần
        # adapter embedding (bge) và độ dài từng lượt.
        boundaries = topic_segmenter.predict_boundaries(
            texts, embedding_adapter=embedding_adapter, item_chars=item_chars
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


def prepare_meeting(
    payload: dict,
    *,
    embedding_adapter: EmbeddingAdapter,
    topic_label_adapter: TopicLabelAdapter,
    topic_segmenter=None,
) -> PreparedMeeting:
    """Đọc transcript -> stage01-03 dựng lượt nói -> cắt chủ đề -> stage07 gán nhãn.

    Dùng cho pipeline agentic cũ (``run_meeting_analysis_pipeline``).

    Đầu vào: như ``run_meeting_analysis_pipeline``.
    Đầu ra: ``PreparedMeeting``.
    Lỗi: ``LLMUpstreamError`` nếu bước embedding lỗi; ``ValueError`` nếu transcript không hợp lệ.
    """

    meeting = segment_meeting(
        payload, embedding_adapter=embedding_adapter, topic_segmenter=topic_segmenter
    )
    labels = label_topics(
        meeting.segments, config=meeting.config.topic_labeler, adapter=topic_label_adapter
    )
    labels_by_segment = {label.segment_id: label for label in labels}
    return PreparedMeeting(
        meeting.meeting_id, meeting.revision_id, meeting.turns, meeting.segments, labels_by_segment
    )


def run_meeting_analysis_pipeline(
    payload: dict,
    *,
    embedding_adapter: EmbeddingAdapter,
    topic_label_adapter: TopicLabelAdapter,
    downstream_llm_adapters: tuple[LLMAdapter, LLMAdapter, LLMAdapter, LLMAdapter],
    topic_segmenter=None,
) -> dict:
    """Chạy toàn bộ quy trình phân tích một cuộc họp, từ transcript đến kết quả JSON

    Đầu vào:
        payload: transcript dạng dict (``AnalyzeRequest.model_dump()``).
        embedding_adapter: adapter embedding cho TreeSeg và DialTreeSeg (không dùng với
            DialSTART).
        topic_label_adapter: bộ gán nhãn chủ đề (stage07).
        downstream_llm_adapters: bốn LLM cho (content, action, decision, debate_judge).
        topic_segmenter: ``DialStartSegmenter`` hoặc ``DialTreeSegSegmenter`` đã nạp checkpoint;
            None thì dùng TreeSeg.

    Đầu ra: dict với ``meeting_id``, ``revision_id``, ``topics`` (Diễn biến họp,
        theo chủ đề), ``verified_assignments`` (Giao việc, phẳng), ``verified_decisions``
        (Kết luận họp, phẳng), ``turns``, ``failed_topics``, ``debate_records``.

    Lỗi: ``LLMUpstreamError`` nếu bước embedding của TreeSeg/DialTreeSeg lỗi (bước duy nhất không có
        dự phòng; stage07 và các agent đã tự xử lý lỗi LLM); ``ValueError`` nếu transcript
        không hợp lệ. Router (``routers/meetings.py``) chuyển hai lỗi này thành mã HTTP.
    """

    prepared = prepare_meeting(
        payload,
        embedding_adapter=embedding_adapter,
        topic_label_adapter=topic_label_adapter,
        topic_segmenter=topic_segmenter,
    )
    meeting_id, revision_id = prepared.meeting_id, prepared.revision_id
    turns, segments, labels_by_segment = prepared.turns, prepared.segments, prepared.labels_by_segment
    turns_by_id = {turn.turn_id: turn for turn in turns}

    content_llm, action_llm, decision_llm, debate_judge_llm = downstream_llm_adapters
    graph = build_graph(content_llm, action_llm, decision_llm, debate_judge_llm)
    state: MeetingState = {
        "segments": tuple(segments),
        "labels_by_segment": labels_by_segment,
        "turns_by_id": turns_by_id,
        "meeting_date": read_meeting_date(payload),
        "next_segment_index": 0,
        "known_names": (),
        "known_assignments": (),
        "completed_content_topics": (),
        "completed_action_topics": (),
        "completed_decision_topics": (),
        "action_item_candidates_raw": [],
        "decision_candidates_raw": [],
        "pending_debate_tasks": (),
        "completed_debate_items": (),
        "debate_records": (),
        "topic_failures": (),
        "unrecovered_failures": (),
        "meeting_development": [],
        "verified_assignments": [],
        "verified_decisions": [],
    }
    final_state = graph.invoke(state)

    return {
        "meeting_id": meeting_id,
        "revision_id": revision_id,
        "topics": _group_meeting_development_by_topic(
            segments, labels_by_segment, final_state["meeting_development"]
        ),
        # Gộp mục trùng (luật, 0 token) ở đây vì reducer của graph chỉ cộng dồn,
        # không thay được mục của chủ đề trước khi chủ đề sau nhắc lại cùng việc.
        "verified_assignments": [
            _serialize_action_item(item)
            for item in merge_duplicate_assignments(final_state["verified_assignments"])
        ],
        "verified_decisions": [
            _serialize_decision(item)
            for item in merge_duplicate_decisions(final_state["verified_decisions"])
        ],
        "turns": [
            {"turn_id": turn.turn_id, "speaker": turn.speaker, "text": turn.text_exact}
            for turn in turns
        ],
        "failed_topics": [
            {"segment_id": f.segment_id, "agent": f.agent, "error": f.error}
            for f in final_state["unrecovered_failures"]
        ],
        "debate_records": [
            _serialize_debate_record(record) for record in final_state.get("debate_records", ())
        ],
    }
