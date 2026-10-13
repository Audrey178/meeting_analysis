"""Baseline B0: MỘT lời gọi LLM cho cả cuộc họp sinh mọi phần của biên bản.

Cùng model chính (gemma) và cùng các quy tắc nghiệp vụ với agent v3 (``CHAIR_ASSIGNMENT_RULE``,
``CHAIR_CONCLUSION_RULE``, ``THIRD_PERSON_RULE`` lấy thẳng từ ``nodes/prompts.py``), để chênh lệch
với v3 đo đúng phần kiến trúc (cắt chủ đề, agent riêng, evidence-check, Verifier) chứ không đo
chênh lệch prompt. Model tự chia chủ đề, nên B0 cũng có ranh giới để chấm như các arm khác.
Không có Decisions/Verifier: chi phí OpenAI = 0.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.agentic_v3.nodes.prompts import CHAIR_ASSIGNMENT_RULE, CHAIR_CONCLUSION_RULE, THIRD_PERSON_RULE
from src.utils.contracts import SpeakerTurn
from src.utils.ports import LLMAdapter

SYSTEM_PROMPT = f"""
Bạn là thư ký lập biên bản cuộc họp. Đọc toàn bộ bản ghi và trả về MỘT đối tượng JSON gồm:

1. "topics": các chủ đề theo thứ tự thời gian, liền mạch, phủ kín bản ghi. Ranh giới đặt ở chỗ nội
   dung thực sự chuyển (đổi hạng mục/module, hoặc đổi giai đoạn trình bày → góp ý → kết luận); chen
   ngang ngắn không phải ranh giới. Mỗi chủ đề: "start_turn_id" (lượt nói đầu tiên của chủ đề),
   "title" (động từ + hạng mục đầy đủ), "summary" (1-2 câu, nêu kết quả chính), "discussion_points"
   (các ý thảo luận: "text" tóm tắt vấn đề và quan điểm các bên, "evidence_turn_ids").
2. "assignments": việc được GIAO/NHẬN. Mỗi việc: "actor" (người/đơn vị nhận), "task" (bắt đầu
   bằng động từ, không lặp tên người nhận hay thời hạn), "deadline" (nguyên văn, null nếu không nêu),
   "evidence_turn_ids". Chỉ tính việc có người nhận hoặc được chỉ định rõ; đề xuất bị gạt đi, việc
   không ai nhận thì không đưa vào (việc cần làm mà không ai nhận: actor = null).
3. "decisions": điều đã CHỐT. Mỗi mục: "text", "evidence_turn_ids". Đề xuất chưa được chấp nhận
   không phải kết luận; kết luận bị đảo lại sau đó thì chỉ lấy bản cuối.

{CHAIR_ASSIGNMENT_RULE}

{CHAIR_CONCLUSION_RULE}

{THIRD_PERSON_RULE}

turn_id là phần trong ngoặc vuông đầu mỗi dòng (vd. "TURN_000012"). Mọi evidence_turn_ids phải là
turn_id có thật trong bản ghi.
""".strip()

_EVIDENCE = {"type": "array", "items": {"type": "string"}}
SCHEMA: dict = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_turn_id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "discussion_points": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}, "evidence_turn_ids": _EVIDENCE},
                            "required": ["text", "evidence_turn_ids"],
                        },
                    },
                },
                "required": ["start_turn_id", "title", "summary", "discussion_points"],
            },
        },
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "actor": {"type": ["string", "null"]},
                    "task": {"type": "string"},
                    "deadline": {"type": ["string", "null"]},
                    "evidence_turn_ids": _EVIDENCE,
                },
                "required": ["actor", "task", "deadline", "evidence_turn_ids"],
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "evidence_turn_ids": _EVIDENCE},
                "required": ["text", "evidence_turn_ids"],
            },
        },
    },
    "required": ["topics", "assignments", "decisions"],
}


def render_transcript(turns: Sequence[SpeakerTurn]) -> str:
    """Bản ghi một dòng mỗi lượt: ``[TURN_xxxxxx] người nói: nội dung``."""

    return "\n".join(f"[{turn.turn_id}] {turn.speaker}: {turn.text_exact}" for turn in turns)


def _speakers(turns: Sequence[SpeakerTurn], indices: list[int]) -> list[str]:
    """Người nói của các lượt trích dẫn, theo thứ tự lên tiếng, bỏ lượt không có tên người nói."""

    names: list[str] = []
    for index in sorted(indices):
        speaker = turns[index].speaker
        if speaker and speaker not in names:
            names.append(speaker)
    return names


def run_single_prompt(llm: LLMAdapter, turns: Sequence[SpeakerTurn]) -> tuple[dict, list[int]]:
    """Chạy B0 cho một cuộc họp.

    Đầu vào: llm - adapter model chính; turns - lượt nói theo thứ tự.
    Đầu ra: (output theo schema chung của ``normalize.py``, ranh giới dự đoán theo chỉ số lượt).
        turn_id không có thật trong bản ghi bị bỏ khỏi evidence; chủ đề có ``start_turn_id`` không
        có thật hoặc không tăng dần bị gộp vào chủ đề trước.
    Lỗi: ``LLMUpstreamError`` nếu lời gọi lỗi sau mọi lượt thử.
    """

    raw = llm.generate_json(system_prompt=SYSTEM_PROMPT, user_prompt=render_transcript(turns), schema=SCHEMA)
    index_of = {turn.turn_id: i for i, turn in enumerate(turns)}

    def evidence(item: dict) -> list[str]:
        return [tid for tid in item.get("evidence_turn_ids") or [] if tid in index_of]

    topics, boundaries = [], []
    for topic in raw.get("topics") or []:
        start = index_of.get(topic.get("start_turn_id"))
        new_topic = not topics or (start is not None and start > (boundaries[-1] if boundaries else 0))
        points = [{"speakers": _speakers(turns, [index_of[t] for t in evidence(p)]), "text": p.get("text", ""),
                   "evidence_ids": evidence(p)} for p in topic.get("discussion_points") or []]
        if new_topic:
            if topics:
                boundaries.append(start)
            topics.append({"segment_id": f"TOPIC_SEG_{len(topics):06d}", "title": topic.get("title", ""),
                           "summary": topic.get("summary", ""), "discussion_points": points})
        else:
            topics[-1]["discussion_points"].extend(points)

    def topic_of(evidence_ids: list[str]) -> str | None:
        if not evidence_ids:
            return None
        first = min(index_of[t] for t in evidence_ids)
        return f"TOPIC_SEG_{sum(b <= first for b in boundaries):06d}"

    output = {
        "turns": [{"turn_id": t.turn_id, "speaker": t.speaker, "text": t.text_exact} for t in turns],
        "topics": topics,
        "verified_assignments": [
            {"segment_id": topic_of(evidence(a)), "actor": a.get("actor"), "actor_raw": a.get("actor"),
             "text": a.get("task", ""), "deadline": a.get("deadline"), "evidence_ids": evidence(a),
             "verification": "none"}
            for a in raw.get("assignments") or []
        ],
        "verified_decisions": [
            {"segment_id": topic_of(evidence(d)), "text": d.get("text", ""), "evidence_ids": evidence(d),
             "verification": "none"}
            for d in raw.get("decisions") or []
        ],
        "failed_topics": [],
        "debate_records": [],
    }
    return output, boundaries


__all__ = ["SYSTEM_PROMPT", "run_single_prompt"]
