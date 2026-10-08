"""Phase 1, M3 (Plan Bước 3): đo trên TOÀN BỘ corpus GT thật (47 session,
Kỳ họp thứ ba + thứ tư, khoá XIII) xem turn-level segmentation mất bao nhiêu
thông tin so với ranh giới topic thật -- thay cho việc chỉ viết "limitation"
suông trong luận văn.

Phương pháp (chặn dưới bảo thủ theo nguyên lý pigeonhole, xem docstring của
``gt_parser.py``): với mỗi speaker trong một session, nếu số topic (Heading 3)
khác nhau mà GT gán bullet cho họ > số turn thực tế của họ trong transcript
thô, thì ít nhất (topic_count - turn_count) lần "chuyển topic" đã xảy ra BÊN
TRONG một turn -- không thể là turn-level segmentation nào bắt được, bất kể
thuật toán tốt đến đâu. Đây là NGƯỠNG TRÊN cho hiệu năng turn-level (một
loại "oracle gap"), không phải bản thân hiệu năng của TreeSeg.

Chạy: python3 turn_purity.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gt_parser import parse_groundtruth, parse_turns, read_doc_text

_WEB_CRAWL_ROOT = Path(__file__).resolve().parents[3] / "web_crawl"
_DOWNLOADS = _WEB_CRAWL_ROOT / "downloads"
_OUTPUTS = _WEB_CRAWL_ROOT / "outputs"


_CHAIR_ROLE_MARKERS = ("Chủ tịch Quốc hội", "Phó Chủ tịch")


def _is_chair_role(role: str) -> bool:
    """True for presiding-chair roles (role field is a title, e.g. 'Phó
    Chủ tịch Quốc hội'), False for a regular đại biểu (role field is their
    electoral province/city, e.g. 'TP Cần Thơ'). Chairs structurally speak
    under many topics via short procedural framing/handoff remarks -- a
    different, less interesting kind of "multi-topic turn" than a đại biểu
    covering several substantive points in one speech. Reported separately
    so the headline number is not dominated by an artifact of session
    structure."""

    return any(marker in role for marker in _CHAIR_ROLE_MARKERS)


@dataclass
class SessionResult:
    session: str
    n_turns: int
    n_topics: int
    n_speakers: int
    n_speakers_multi_topic: int  # speakers with topic_count > turn_count
    extra_topic_transitions: int  # sum of max(0, topic_count - turn_count)
    n_speakers_multi_topic_non_chair: int
    extra_topic_transitions_non_chair: int


def find_session_pairs() -> list[tuple[Path, Path]]:
    """Match every ``outputs/**/*_groundtruth.docx`` to its raw ``.doc`` in
    ``downloads/`` at the same relative path (README: "downloads/ has more
    raw transcript than outputs/ has groundtruth for" -- only pairs with
    both sides are used here)."""

    pairs: list[tuple[Path, Path]] = []
    for gt_path in sorted(_OUTPUTS.rglob("*_groundtruth.docx")):
        rel = gt_path.relative_to(_OUTPUTS)
        raw_name = rel.name.removesuffix("_groundtruth.docx") + ".doc"
        raw_path = _DOWNLOADS / rel.parent / raw_name
        if raw_path.exists():
            pairs.append((raw_path, gt_path))
        else:
            print(f"SKIP (no raw .doc match): {rel}")
    return pairs


def analyze_session(raw_path: Path, gt_path: Path) -> SessionResult:
    turns = parse_turns(read_doc_text(raw_path))
    topics = parse_groundtruth(gt_path)

    turn_count: dict[str, int] = {}
    role_of: dict[str, str] = {}
    for turn in turns:
        turn_count[turn.speaker] = turn_count.get(turn.speaker, 0) + 1
        role_of.setdefault(turn.speaker, turn.role)

    topic_count: dict[str, int] = {}
    for topic in topics:
        for speaker in topic.speakers:
            topic_count[speaker] = topic_count.get(speaker, 0) + 1

    all_speakers = set(turn_count) | set(topic_count)
    n_multi = 0
    extra = 0
    n_multi_non_chair = 0
    extra_non_chair = 0
    for speaker in all_speakers:
        gap = topic_count.get(speaker, 0) - turn_count.get(speaker, 0)
        if gap > 0:
            n_multi += 1
            extra += gap
            if not _is_chair_role(role_of.get(speaker, "")):
                n_multi_non_chair += 1
                extra_non_chair += gap

    return SessionResult(
        session=raw_path.stem,
        n_turns=len(turns),
        n_topics=len(topics),
        n_speakers=len(all_speakers),
        n_speakers_multi_topic=n_multi,
        extra_topic_transitions=extra,
        n_speakers_multi_topic_non_chair=n_multi_non_chair,
        extra_topic_transitions_non_chair=extra_non_chair,
    )


def main() -> None:
    pairs = find_session_pairs()
    print(f"{len(pairs)} session(s) with both raw + groundtruth found.\n")

    results: list[SessionResult] = []
    for raw_path, gt_path in pairs:
        try:
            results.append(analyze_session(raw_path, gt_path))
        except Exception as exc:  # noqa: BLE001 -- report and keep going
            print(f"FAILED: {raw_path.name}: {exc!r}")

    total_turns = sum(r.n_turns for r in results)
    total_speakers = sum(r.n_speakers for r in results)
    total_multi = sum(r.n_speakers_multi_topic for r in results)
    total_extra = sum(r.extra_topic_transitions for r in results)
    total_multi_nc = sum(r.n_speakers_multi_topic_non_chair for r in results)
    total_extra_nc = sum(r.extra_topic_transitions_non_chair for r in results)
    sessions_with_evidence = sum(1 for r in results if r.n_speakers_multi_topic > 0)
    sessions_with_evidence_nc = sum(1 for r in results if r.n_speakers_multi_topic_non_chair > 0)

    print(f"Sessions analyzed:              {len(results)}")
    print(f"Sessions with >=1 multi-topic turn (lower bound, ALL roles): {sessions_with_evidence} "
          f"({sessions_with_evidence / len(results):.1%})")
    print(f"Sessions with >=1 multi-topic turn (lower bound, non-chair only): {sessions_with_evidence_nc} "
          f"({sessions_with_evidence_nc / len(results):.1%})")
    print(f"Total turns:                    {total_turns}")
    print(f"Total (speaker, session) pairs: {total_speakers}")
    print(f"...multi-topic, ALL roles (lower bound): {total_multi} ({total_multi / total_speakers:.1%})")
    print(f"...multi-topic, non-chair only (lower bound): {total_multi_nc} ({total_multi_nc / total_speakers:.1%})")
    print(f"Extra topic-transitions inside turns, ALL roles: {total_extra}")
    print(f"Extra topic-transitions inside turns, non-chair only: {total_extra_nc}")

    _write_report(results)


def _write_report(results: list[SessionResult]) -> None:
    lines = [
        "# Turn purity — Phase 1, M3",
        "",
        "**Chặn dưới bảo thủ (pigeonhole), không phải con số tuyệt đối** — xem "
        "docstring `turn_purity.py`. Đo trên corpus GT thật (không phải dataset "
        "tổng hợp): mọi session ở `web_crawl/outputs/Quốc hội khoá XIII/` có cả "
        "raw `.doc` khớp trong `downloads/`.",
        "",
    ]
    total_turns = sum(r.n_turns for r in results)
    total_speakers = sum(r.n_speakers for r in results)
    total_multi = sum(r.n_speakers_multi_topic for r in results)
    total_extra = sum(r.extra_topic_transitions for r in results)
    total_multi_nc = sum(r.n_speakers_multi_topic_non_chair for r in results)
    total_extra_nc = sum(r.extra_topic_transitions_non_chair for r in results)
    sessions_with_evidence = sum(1 for r in results if r.n_speakers_multi_topic > 0)
    sessions_with_evidence_nc = sum(1 for r in results if r.n_speakers_multi_topic_non_chair > 0)

    lines += [
        "**Quan trọng: tách riêng chủ tọa (Chủ tịch/Phó Chủ tịch Quốc hội) khỏi "
        "đại biểu thường.** Chủ tọa xuất hiện dưới nhiều topic một cách CẤU TRÚC "
        "(câu dẫn dắt/chuyển mục ngắn ở đầu mỗi topic), khác về bản chất so với "
        "một đại biểu trình bày nhiều điểm thực chất trong 1 lượt phát biểu. Cột "
        "'non-chair' mới là con số đáng tin cho câu hỏi \"đại biểu có thực sự nói "
        "nhiều vấn đề trong 1 turn không\".",
        "",
        f"- Số session phân tích được: {len(results)}",
        f"- Session có bằng chứng >=1 turn đa-topic — TẤT CẢ vai trò: "
        f"{sessions_with_evidence} ({sessions_with_evidence / len(results):.1%}) — "
        f"CHỈ đại biểu (bỏ chủ tọa): {sessions_with_evidence_nc} "
        f"({sessions_with_evidence_nc / len(results):.1%})",
        f"- Tổng số turn: {total_turns}, tổng số cặp (speaker, session): {total_speakers}",
        f"- Đa-topic (chặn dưới) — TẤT CẢ vai trò: {total_multi} "
        f"({total_multi / total_speakers:.1%}) — CHỈ đại biểu: {total_multi_nc} "
        f"({total_multi_nc / total_speakers:.1%})",
        f"- Số lần chuyển topic bị 'nuốt' trong turn (chặn dưới) — TẤT CẢ vai trò: "
        f"{total_extra} — CHỈ đại biểu: {total_extra_nc}",
        "",
        "## Theo từng session",
        "",
        "| Session | #turn | #topic | #speaker | đa-topic (tất cả) | đa-topic (chỉ đại biểu) | extra transitions (chỉ đại biểu) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in sorted(results, key=lambda r: -r.extra_topic_transitions_non_chair):
        lines.append(
            f"| {r.session} | {r.n_turns} | {r.n_topics} | {r.n_speakers} | "
            f"{r.n_speakers_multi_topic} | {r.n_speakers_multi_topic_non_chair} | "
            f"{r.extra_topic_transitions_non_chair} |"
        )

    out_path = Path(__file__).parent / "turn_purity_results.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
