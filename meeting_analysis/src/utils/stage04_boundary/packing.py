"""Giai đoạn 4c -- ConstrainedPacker: chọn điểm cắt dưới ``min_chars`` (cứng)
và ``soft_cap_chars`` (mềm).

Packing tối ưu hóa sự đánh đổi giữa độ dài/nuốt (swallow)/cắt (cut), tuân
theo kích thước atom tối thiểu (``min_chars``, cứng) và một cái đích mềm
(``soft_cap_chars``) mà hàm chi phí tối ưu hóa hướng tới chứ không ép buộc.
Nó chọn trong số các offset mà 4a đã tạo ra và 4b đã chấm điểm; nó không thể
tự tổng hợp một offset mới, đó là điều giữ cho mỗi atom được đóng gói luôn là
một đoạn transcript chính xác -- kể cả khi không có ranh giới an toàn nào
trong ngưỡng mềm và atom kết quả vượt quá nó (xem ``_FORCED_OVERSIZED_SUFFIX``).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ports import ItemSpan
from .candidates import trimmed_end
from .scoring import ScoredCandidate


# ---------------------------------------------------------------------------
# 4c -- ConstrainedPacker
# ---------------------------------------------------------------------------

# Các hằng số hiệu chỉnh cho chi phí (cost) packing bên dưới. Giống như
# ``_BM25_SATURATION_SCALE`` của topics.py, đây là điểm khởi đầu đã được ghi
# lại, không phải giá trị đã tinh chỉnh cho production -- xem
# docs/stage4-5-plan.md D3/T12.
_LAMBDA_LEN = 1.0
_LAMBDA_SWALLOW = 0.5
_LAMBDA_CUT = 0.2
_LAMBDA_GAIN = 0.5
# Additive cost for cutting at a ScoredCandidate.continuation_penalty
# position (see scoring.py's module-level note on why this can't just be
# folded into split_score/gain: gain floors at 0, so a "no bonus" candidate
# still wins whenever it happens to land near target_chars purely on
# len_penalty). This has to be large enough to outweigh that pull -- 1.0,
# same order of magnitude as _LAMBDA_LEN, verified against the reported
# case (a continuation candidate 255 chars out, vs. a real boundary 444
# chars out: without this term the near-target one won 0.208 vs 0.383).
_LAMBDA_CONTINUATION = 1.0

# Appended to PackedAtom.packing_method when no real boundary candidate left
# a span under soft_cap_chars, so the packer kept the whole stretch as one
# atom instead of inventing a mid-word cut. Distinct from stage06's
# ``_FORCED_OVERSIZED_TURN_SUFFIX`` (a different stage, a different
# granularity: that one marks a force-split *turn* boundary, this one marks
# a single *atom* that was never split at all).
_FORCED_OVERSIZED_SUFFIX = "+forced_oversized"


@dataclass(frozen=True, slots=True)
class PackedAtom:
    start: int
    end: int
    partition_end: int
    boundary_source: str
    boundary_confidence: float | None
    packing_method: str



def pack_atoms(
    text: str,
    scored: tuple[ScoredCandidate, ...],
    *,
    min_chars: int,
    target_chars: int,
    soft_cap_chars: int,
) -> tuple[PackedAtom, ...]:
    """4c: quy hoạch động (DP) tất định trên các offset ứng viên -- không bao
    giờ dùng thuật toán tham lam (greedy), vì ``run_hash`` băm
    ``analysis_atoms`` và cách phá vỡ thế hòa (tie-breaking) kiểu tham lam sẽ
    không thể tái lập được giữa các lựa chọn có cùng chi phí theo cách mà một
    lượt quét argmin tường minh có thể.

    ``min_chars`` là ràng buộc cứng, chỉ được nới lỏng cho một turn nguyên
    vẹn ngắn hơn nó (D3). ``soft_cap_chars`` KHÔNG còn là ràng buộc cứng: nó
    chỉ định hình ``len_penalty`` (tăng vô hạn khi lệch xa mục tiêu), nên DP
    vẫn luôn ưu tiên một ranh giới thật ngắn hơn khi có, nhưng khi không
    candidate nào cho một cách chia an toàn, packer giữ nguyên đoạn dài
    (đánh dấu ``packing_method`` bằng ``_FORCED_OVERSIZED_SUFFIX``) thay vì
    băm đại vào giữa từ. Chỉ một cấu hình tĩnh thực sự không tương thích
    (ví dụ ``min_chars`` quá lớn so với văn bản) mới raise lỗi.
    """

    n = len(text)
    if n == 0:
        return ()

    by_pos = {candidate.pos: candidate for candidate in scored}

    def score_at(pos: int) -> float:
        candidate = by_pos.get(pos)
        return candidate.split_score if candidate is not None else 1.0

    def continuation_penalty_at(pos: int) -> float:
        candidate = by_pos.get(pos)
        return candidate.continuation_penalty if candidate is not None else 0.0

    positions = sorted({candidate.pos for candidate in scored} | {0, n})
    turn_content_length = trimmed_end(text, 0, n)
    effective_min = min_chars if turn_content_length >= min_chars else 0
    effective_target = min(target_chars, soft_cap_chars)

    def solve(enforce_min: bool) -> tuple[list[float], list[int]]:
        k = len(positions)
        infinity = float("inf")
        dp = [infinity] * k
        back = [-1] * k
        dp[0] = 0.0
        prefix = [0.0] * k
        for index in range(1, k):
            prefix[index] = prefix[index - 1] + score_at(positions[index])
        for j in range(1, k):
            pos_j = positions[j]
            for i in range(j):
                if dp[i] == infinity:
                    continue
                pos_i = positions[i]
                content_end = trimmed_end(text, pos_i, pos_j)
                length = content_end - pos_i
                # soft_cap_chars is a soft target now, not a hard wall: no
                # `length > soft_cap_chars: continue` prune here anymore.
                # len_penalty below already grows unboundedly past the cap,
                # so a real, shorter split is still always preferred when
                # one exists -- an over-cap span only wins when it's
                # genuinely the cheapest reachable option.
                if enforce_min and effective_min and length < effective_min:
                    continue
                swallow = prefix[j - 1] - prefix[i]
                len_penalty = ((length - effective_target) / effective_target) ** 2
                gain = score_at(pos_j)
                cost = (
                    _LAMBDA_LEN * len_penalty
                    + _LAMBDA_SWALLOW * swallow
                    + _LAMBDA_CUT
                    - _LAMBDA_GAIN * gain
                    + _LAMBDA_CONTINUATION * continuation_penalty_at(pos_j)
                )
                total = dp[i] + cost
                if total < dp[j]:
                    dp[j] = total
                    back[j] = i
        return dp, back

    dp, back = solve(enforce_min=bool(effective_min))
    if dp[-1] == float("inf"):
        raise ValueError(
            "ConstrainedPacker found no packing that satisfies min_chars; "
            "the atom_builder limits are incompatible with this turn"
        )

    spans: list[tuple[int, int]] = []
    index = len(positions) - 1
    while index > 0:
        prev = back[index]
        spans.append((positions[prev], positions[index]))
        index = prev
    spans.reverse()

    packed: list[PackedAtom] = []
    for start, raw_end in spans:
        # Mọi vị trí ứng viên đã được xử lý loại bỏ khoảng trắng ở đầu
        # (START) của nó rồi (việc của 4a); còn END của một atom chỉ đơn
        # giản là vị trí của ứng viên kế tiếp, vốn vẫn còn mang khoảng trắng
        # phân tách giữa chúng. Cắt bỏ nó ở đây -- cùng công việc mà
        # ``_trimmed_span`` từng làm -- để không có text_exact của atom nào
        # kết thúc bằng khoảng trắng.
        end = trimmed_end(text, start, raw_end)
        candidate = by_pos.get(start)
        boundary_source = candidate.source if candidate is not None else "turn_edge"
        boundary_confidence = candidate.model_confidence if candidate is not None else None
        packing_method = (
            "rule_pack_v1" + _FORCED_OVERSIZED_SUFFIX
            if (end - start) > soft_cap_chars
            else "rule_pack_v1"
        )
        packed.append(
            PackedAtom(
                start=start,
                end=end,
                partition_end=raw_end,
                boundary_source=boundary_source,
                boundary_confidence=boundary_confidence,
                packing_method=packing_method,
            )
        )
    return tuple(packed)
