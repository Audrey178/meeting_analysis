"""Quy trình v3 (``src/agentic_v3``) cho API: cắt chủ đề như v1, rồi mọi chủ đề chạy song song
(gán nhãn -> trích xuất -> Evidence-Check -> Verifier ReAct <-> agent trích xuất tới khi
đồng thuận), trả kết quả trong MỘT request (không có bước duyệt người).

    segment_meeting (stage01-03 + cắt chủ đề, dùng chung với v1)
    MeetingAnalyzerV3.analyze -> MeetingReport

``MeetingAnalyzerV3`` sống suốt vòng đời ứng dụng (``app.state.analyzer_v3``) để mọi request
dùng chung một ``LLMConcurrencyGate``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BE_DIR.parent
for _dir in (_BE_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from experiments.dialstart import DialStartSegmenter

from src.agentic_v3 import ActionItemV3, MeetingAnalyzerV3, MeetingReport, V3Config
from src.agentic_v3.actors.attendees import AttendeeRoster, parse_attendee_roster
from src.utils.ports import EmbeddingAdapter

from services.pipeline import (
    _group_meeting_development_by_topic,
    _serialize_action_item,
    _serialize_decision,
    load_pipeline_config,
    read_meeting_date,
    segment_meeting,
)


def _env_flag(name: str, default: bool) -> bool:
    """Đọc biến môi trường dạng cờ ("1/true/yes/on" là bật)."""

    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_v3_config_from_env() -> V3Config:
    """Cấu hình v3 từ biến môi trường ``V3_*`` (giá trị thiếu dùng mặc định của ``V3Config``).

    Đầu ra: V3Config.
    """

    defaults = V3Config()
    return V3Config(
        skip_agents_without_cues=_env_flag("V3_SKIP_AGENTS_WITHOUT_CUES", defaults.skip_agents_without_cues),
        extract_attempts=int(os.environ.get("V3_EXTRACT_ATTEMPTS", defaults.extract_attempts)),
        verifier_max_tool_calls=int(os.environ.get("V3_VERIFIER_MAX_TOOL_CALLS", defaults.verifier_max_tool_calls)),
        consensus_max_rounds=int(os.environ.get("V3_CONSENSUS_MAX_ROUNDS", defaults.consensus_max_rounds)),
        max_concurrency=int(os.environ.get("V3_MAX_CONCURRENCY", defaults.max_concurrency)),
    )


def _build_verifier_llm(default_llm):
    """LLM cho Verifier: backend riêng nếu có ``VERIFIER_MODEL_NAME``, không thì ``default_llm``.

    Biến môi trường (chỉ đọc khi có ``VERIFIER_MODEL_NAME``):
        VERIFIER_BASE_URL, VERIFIER_API_KEY: endpoint OpenAI-compatible (vd DeepSeek).
        VERIFIER_RESPONSE_MODE: ``json_object`` (mặc định, DeepSeek không hỗ trợ
            ``json_schema`` strict) hoặc ``json_schema``.
        VERIFIER_LLM_CONCURRENCY: số lời gọi Verifier đồng thời (gate riêng, mặc định 8).
        VERIFIER_THINKING: ``enabled``/``disabled`` gửi kèm ``{"thinking": {"type": ...}}``
            (DeepSeek V4); để trống thì không gửi. ``deepseek-flash`` bật thinking thì
            hay trả ``content`` toàn khoảng trắng ở chế độ ``json_object``.

    Đầu vào: default_llm - LLM dùng chung của các vai trò khác.
    Đầu ra: (adapter, số lời gọi đồng thời hoặc None nếu dùng chung gate).
    Lỗi: ValueError nếu có ``VERIFIER_MODEL_NAME`` mà thiếu ``VERIFIER_BASE_URL``/``VERIFIER_API_KEY``.
    """

    from src.utils.openai_adapters import OpenAIChatJSONAdapter

    model = os.environ.get("VERIFIER_MODEL_NAME", "").strip()
    if not model:
        return default_llm, None
    base_url = os.environ.get("VERIFIER_BASE_URL", "").strip()
    api_key = os.environ.get("VERIFIER_API_KEY", "").strip()
    if not base_url or not api_key:
        raise ValueError("VERIFIER_MODEL_NAME cần đi kèm VERIFIER_BASE_URL và VERIFIER_API_KEY")
    thinking = os.environ.get("VERIFIER_THINKING", "").strip().lower()
    if thinking not in ("", "enabled", "disabled"):
        raise ValueError(f"VERIFIER_THINKING không hợp lệ: {thinking!r} (enabled | disabled)")
    llm = OpenAIChatJSONAdapter(
        model=model,
        base_url=base_url,
        api_key=api_key,
        response_mode=os.environ.get("VERIFIER_RESPONSE_MODE", "json_object"),
        extra_body={"thinking": {"type": thinking}} if thinking else None,
    )
    return llm, int(os.environ.get("VERIFIER_LLM_CONCURRENCY", "8"))


def _build_turn_judge():
    """Bộ phân loại lượt chốt theo nghĩa (OpenAI Decisions API), hoặc None nếu chưa bật.

    Biến môi trường:
        TURN_ACT_MODEL: model Decisions (vd ``gpt-6-luna``); để trống thì không bật, evidence-check
            dùng luật từ khoá như v1.
        TURN_ACT_API_KEY: key OpenAI; để trống thì dùng ``VERIFIER_API_KEY`` rồi ``OPENAI_API_KEY``.
        TURN_ACT_BASE_URL: mặc định ``https://api.openai.com/v1`` (KHÔNG kế thừa ``OPENAI_BASE_URL``,
            vốn trỏ tới gateway chỉ có chat).
        TURN_ACT_TIMEOUT_SECONDS: timeout mỗi lời gọi (mặc định 10; quá hạn thì quay về luật từ khoá).

    Đầu ra: ``DecisionsTurnActJudge`` hoặc None.
    Lỗi: ValueError nếu có ``TURN_ACT_MODEL`` mà không tìm được API key.
    """

    from openai import OpenAI

    from src.agentic.turn_act import DecisionsTurnActJudge

    model = os.environ.get("TURN_ACT_MODEL", "").strip()
    if not model:
        return None
    api_key = next(
        (value for name in ("TURN_ACT_API_KEY", "VERIFIER_API_KEY", "OPENAI_API_KEY")
         if (value := os.environ.get(name, "").strip())),
        None,
    )
    if api_key is None:
        raise ValueError("TURN_ACT_MODEL cần TURN_ACT_API_KEY (hoặc VERIFIER_API_KEY/OPENAI_API_KEY)")
    client = OpenAI(
        api_key=api_key,
        base_url=os.environ.get("TURN_ACT_BASE_URL", "").strip() or "https://api.openai.com/v1",
        timeout=float(os.environ.get("TURN_ACT_TIMEOUT_SECONDS", "10")),
        max_retries=2,  # đã gặp "Connection reset by peer" lẻ tẻ khi đo; SDK tự thử lại lỗi mạng/429/5xx
    )
    return DecisionsTurnActJudge(client, model=model)


def build_analyzer_v3() -> MeetingAnalyzerV3:
    """Dựng analyzer v3 dùng adapter OpenAI thật (gọi lười, lần đầu có request v3).

    Một instance LLM dùng chung cho gán nhãn + ba agent trích xuất, như
    ``get_downstream_llm_adapters`` của v1; Verifier có thể trỏ sang backend riêng
    (``_build_verifier_llm``). Số lời gọi đồng thời đọc từ ``V3_LLM_CONCURRENCY`` (mặc định 8).
    Lượt chốt được xét theo nghĩa khi có ``TURN_ACT_MODEL`` (``_build_turn_judge``).

    Đầu ra: MeetingAnalyzerV3.
    """

    from src.stages.stage07_topic_labeling import StructuredLLMTopicLabeler
    from src.utils.openai_adapters import OpenAIChatJSONAdapter

    llm = OpenAIChatJSONAdapter()
    verifier_llm, verifier_concurrency = _build_verifier_llm(llm)
    labeler = StructuredLLMTopicLabeler(llm, model_name=getattr(llm, "model_name", "openai"))
    return MeetingAnalyzerV3(
        content_llm=llm,
        action_llm=llm,
        decision_llm=llm,
        verifier_llm=verifier_llm,
        labeler=labeler,
        labeler_config=load_pipeline_config().topic_labeler,
        config=build_v3_config_from_env(),
        llm_concurrency=int(os.environ.get("V3_LLM_CONCURRENCY", "8")),
        verifier_llm_concurrency=verifier_concurrency,
        turn_judge=_build_turn_judge(),
    )


def _serialize_verification_record(record) -> dict:
    """Chuyển ``VerificationRecord`` thành dict JSON."""

    return {
        "item_key": record.item_key,
        "segment_id": record.segment_id,
        "kind": record.kind,
        "candidate_text": record.candidate_text,
        "reasons": list(record.reasons),
        "steps": [
            {"thought": s.thought, "action": s.action, "argument": s.argument, "observation": s.observation}
            for s in record.steps
        ],
        "verdict": record.verdict,
        "reasoning": record.reasoning,
        "final_text": record.final_text,
        "deciding_turn_id": record.deciding_turn_id,
        "decided_by": record.decided_by,
        "rounds": [
            {
                "candidate_text": r.candidate_text,
                "verdict": r.verdict,
                "feedback": r.feedback,
                "deciding_turn_id": r.deciding_turn_id,
                "stance": r.stance,
                "response": r.response,
            }
            for r in record.rounds
        ],
    }


def _serialize_candidate(candidate) -> dict:
    """Một ``ActorCandidate`` thành dict theo ``ActorCandidateOut``."""

    return {
        "name": candidate.name,
        "actor_type": candidate.actor_type,
        "score": candidate.score,
        "reason": candidate.reason,
        "ref_id": candidate.ref_id,
    }


def _serialize_action_item_v3(item) -> dict:
    """Việc giao v3 = dict của v1 cộng phần định danh actor (nếu item là ``ActionItemV3``).

    Đầu vào: item - ActionItemCandidate hoặc ActionItemV3.
    Đầu ra: dict theo ``ActionItemV3Out``.
    """

    serialized = _serialize_action_item(item)
    if isinstance(item, ActionItemV3):
        serialized.update(
            actor_type=item.actor_type,
            actor_flag=item.actor_flag,
            actor_reason=item.actor_reason,
            actor_candidates=[_serialize_candidate(c) for c in item.actor_candidates],
            assignees=[
                {
                    "mention": a.mention,
                    "role": a.role,
                    "name": a.name,
                    "actor_type": a.actor_type,
                    "flag": a.flag,
                    "reason": a.reason,
                    "ref_id": a.ref_id,
                    "candidates": [_serialize_candidate(c) for c in a.candidates],
                }
                for a in item.assignees
            ],
        )
    return serialized


def _build_result(meeting, report: MeetingReport) -> dict:
    """Dựng phản hồi API từ cuộc họp đã cắt chủ đề và kết quả v3.

    Đầu vào: meeting - kết quả ``segment_meeting``; report - MeetingReport.
    Đầu ra: dict theo ``AnalyzeV3Result``.
    """

    labels_by_segment = {label.segment_id: label for label in report.labels}
    return {
        "meeting_id": meeting.meeting_id,
        "revision_id": meeting.revision_id,
        "topics": _group_meeting_development_by_topic(
            meeting.segments, labels_by_segment, list(report.meeting_development)
        ),
        "verified_assignments": [_serialize_action_item_v3(item) for item in report.assignments],
        "verified_decisions": [_serialize_decision(item) for item in report.decisions],
        "turns": [{"turn_id": turn.turn_id, "speaker": turn.speaker, "text": turn.text_exact} for turn in meeting.turns],
        "failed_topics": [
            {"segment_id": f.segment_id, "agent": f.agent, "error": f.error} for f in report.failures
        ],
        "verification_records": [_serialize_verification_record(r) for r in report.verification_records],
        "skipped_agents": [{"segment_id": s.segment_id, "agent": s.agent} for s in report.skipped_agents],
    }


def read_attendee_roster(payload: dict) -> AttendeeRoster | None:
    """Đọc danh sách tham dự (``attendees``) gửi kèm request, None nếu không có.

    Đầu vào: payload - ``AnalyzeRequest.model_dump()``.
    Đầu ra: AttendeeRoster hoặc None.
    Lỗi: ValueError nếu danh sách sai dạng (router trả 422).
    """

    attendees = payload.get("attendees")
    return parse_attendee_roster(attendees) if attendees else None


def start_meeting_analysis_v3(
    payload: dict,
    *,
    analyzer: MeetingAnalyzerV3,
    embedding_adapter: EmbeddingAdapter,
    topic_segmenter: DialStartSegmenter | None = None,
) -> dict:
    """Phân tích một cuộc họp bằng v3, chạy một mạch tới kết quả cuối.

    Đầu vào:
        payload: transcript dạng dict (``AnalyzeV3Request.model_dump()``); ``chair`` (tùy
            chọn) là tên người chủ trì.
        analyzer: ``MeetingAnalyzerV3`` dùng chung của ứng dụng.
        embedding_adapter, topic_segmenter: như v1 (``run_meeting_analysis_pipeline``).
    Đầu ra: dict theo ``AnalyzeV3Result``.
    Lỗi: ``LLMUpstreamError`` nếu bước embedding lỗi; ``ValueError`` nếu transcript không hợp lệ.
    """

    meeting = segment_meeting(payload, embedding_adapter=embedding_adapter, topic_segmenter=topic_segmenter)
    report = analyzer.analyze(
        meeting_id=meeting.meeting_id,
        revision_id=meeting.revision_id,
        meeting_date=read_meeting_date(payload),
        chair=payload.get("chair"),
        turns=meeting.turns,
        segments=meeting.segments,
        attendee_roster=read_attendee_roster(payload),
    )
    return _build_result(meeting, report)


__all__ = [
    "build_analyzer_v3",
    "build_v3_config_from_env",
    "read_attendee_roster",
    "start_meeting_analysis_v3",
]
