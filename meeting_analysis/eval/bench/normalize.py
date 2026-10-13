"""Đưa ``MeetingReport`` (hoặc output của baseline) về một schema chung để chấm.

Schema giữ đúng các khoá mà ``eval/build_judge_packet.py`` và ``eval/aggregate_eval.py`` đang đọc
(``turns``, ``topics``, ``verified_assignments``, ``verified_decisions``, ``failed_topics``,
``debate_records``), nên mọi arm dùng chung một bộ chấm. Mọi ``evidence_ids`` là turn_id
(``TURN_xxxxxx``), cùng hệ với ``evidence_turn_ids`` của gold.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.agentic_v3.schemas import MeetingReport
from src.utils.contracts import SpeakerTurn, TopicSegment


def _actor_name(item) -> str | None:
    """Tên bên nhận việc sau khi định danh (``ActionItemV3.assignees``), không có thì ``actor`` thô."""

    names = [assignee.name or assignee.mention for assignee in getattr(item, "assignees", ())]
    return ", ".join(names) if names else item.actor


def segment_boundaries(segments: Sequence[TopicSegment]) -> list[int]:
    """Chỉ số lượt nói bắt đầu mỗi chủ đề, trừ chủ đề đầu (``start_ms`` của segment là chỉ số lượt)."""

    return [int(segment.start_ms) for segment in segments[1:]]


def report_to_eval_output(report: MeetingReport, turns: Sequence[SpeakerTurn]) -> dict:
    """Chuyển kết quả v3 sang schema chấm chung.

    Đầu vào: report - kết quả ``MeetingAnalyzerV3.analyze``; turns - lượt nói của cuộc họp.
    Đầu ra: dict theo schema chung (chưa có ``_segments``/``_cost``, do ``run.py`` thêm).
    """

    points_by_topic: dict[str, list[dict]] = {}
    for point in report.meeting_development:
        points_by_topic.setdefault(point.segment_id, []).append(
            {"speakers": list(point.speakers), "text": point.text, "evidence_ids": list(point.evidence_ids)}
        )
    return {
        "turns": [{"turn_id": t.turn_id, "speaker": t.speaker, "text": t.text_exact} for t in turns],
        "topics": [
            {
                "segment_id": label.segment_id,
                "title": label.title,
                "summary": label.summary,
                "discussion_points": points_by_topic.get(label.segment_id, []),
            }
            for label in report.labels
        ],
        "verified_assignments": [
            {
                "segment_id": item.segment_id,
                "actor": _actor_name(item),
                "actor_raw": item.actor,
                "text": item.text,
                "deadline": item.deadline_raw,
                "evidence_ids": list(item.evidence_ids),
                "verification": item.verification,
            }
            for item in report.assignments
        ],
        "verified_decisions": [
            {
                "segment_id": item.segment_id,
                "text": item.text,
                "evidence_ids": list(item.evidence_ids),
                "verification": item.verification,
            }
            for item in report.decisions
        ],
        "failed_topics": [
            {"segment_id": f.segment_id, "agent": f.agent, "error": f.error} for f in report.failures
        ],
        "debate_records": [
            {
                "kind": record.kind,
                "candidate_text": record.candidate_text,
                "verdict": record.verdict,
                "decided_by": record.decided_by,
                "kept": record.verdict != "drop",
            }
            for record in report.verification_records
        ],
    }


__all__ = ["report_to_eval_output", "segment_boundaries"]
