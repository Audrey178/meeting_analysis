"""TẤT CẢ CÁC MODE CỦA STAGE 6, chia theo ba nhóm.

    baseline    no_split, split_per_turn, split_uniform, split_random
    sequential  pack_by_length, greedy_adjacent_cosine, greedy_chunk_cosine,
                greedy_hybrid, texttiling
    dp          dp_optimal, dp_optimal_elbow, dp_optimal_fixed_k,
                greedy_on_gram, dp_turn_aligned

Tên mode cũ được đăng ký làm ``legacy_names``, nên config đang chạy vẫn ra
đúng kết quả cũ.

ĐỌC TRƯỚC KHI SO SÁNH HAI NHÓM
------------------------------
``greedy_hybrid`` và ``dp_optimal`` khác nhau BỐN điểm cùng lúc:

    1. Cách tìm kiếm      — tham lam  vs  quy hoạch động
    2. Độ phủ BM25        — top-k của Stage 5  vs  toàn bộ từ vựng
    3. Tính đối xứng      — bất đối xứng (doc/query)  vs  hợp nhất ở mức vector
    4. Làm mượt           — không có  vs  cộng láng giềng ±w

Vì vậy ``dp_optimal`` thắng ``greedy_hybrid`` KHÔNG nói lên điều gì về riêng
DP. Mode ``greedy_on_gram`` bên dưới là đối chứng để tách bạch: cùng biểu
diễn, nhưng tìm kiếm tham lam.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import math
import random
import statistics
from typing import Protocol

from ..utils.config import SegmentationConfig
from ..utils.contracts import AnalysisAtom, AtomFeatures
from ..utils.ports import CosineSimilarityAdapter
from . import segmentation as dp_engine
from ._shared import LexicalCosineSimilarity, join_atoms
from .stage06_topic_segmentation import (
    FORCED_BOUNDARY_SUFFIX,
    SegmentationContext,
    SegmentPlan,
    Span,
    build_plan_from_cuts,
    count_tokens,
    count_tokens_of_atoms,
    register_mode,
)
import logging


# ===========================================================================
# PHẦN 1. ĐƠN VỊ PHÂN TÍCH (chỉ nhóm sequential dùng; nhóm DP chạy trên atom)
# ===========================================================================


class AnalysisUnit:
    """Một cụm atom được coi là không thể tách trong lúc chia tham lam.

    Mặc định một đơn vị = một lượt nói trọn vẹn, vì trong họp hành chính biên
    chủ đề gần như luôn trùng biên lượt nói.

    Thuộc tính:
        indices: các chỉ số atom thuộc đơn vị này, liên tục và tăng dần.
        forced_boundary_before: True khi đơn vị này là phần đầu sau một lần
            xé lượt nói quá dài — dùng để không cho phần đuôi lưng chừng nuốt
            luôn lượt nói kế tiếp.
    """

    __slots__ = ("indices", "forced_boundary_before")

    def __init__(self, indices: tuple[int, ...], forced_boundary_before: bool = False) -> None:
        self.indices = indices
        self.forced_boundary_before = forced_boundary_before

    @property
    def start(self) -> int:
        """Chỉ số atom đầu tiên của đơn vị."""

        return self.indices[0]


def build_analysis_units(
    atoms: Sequence[AnalysisAtom], *, respect_turn_boundaries: bool, max_tokens: int
) -> tuple[AnalysisUnit, ...]:
    """Gom atom thành các đơn vị phân tích, tôn trọng lượt nói và ngân sách token.

    Đầu vào:
        atoms: chuỗi atom của cuộc họp.
        respect_turn_boundaries: True thì gom theo ``turn_id``; False thì mỗi
            atom là một đơn vị riêng.
        max_tokens: số token tối đa cho một đơn vị.

    Đầu ra:
        Tuple AnalysisUnit phủ hết chuỗi atom, đúng thứ tự.

    Lỗi:
        ValueError nếu một atom đơn lẻ đã dài hơn ``max_tokens``.
    """

    if not respect_turn_boundaries:
        return tuple(AnalysisUnit((i,)) for i in range(len(atoms)))

    # Bước 1: gom atom theo turn_id.
    turns: list[list[int]] = []
    for index, atom in enumerate(atoms):
        if turns and atom.turn_id == atoms[turns[-1][-1]].turn_id:
            turns[-1].append(index)
        else:
            turns.append([index])

    # Bước 2: lượt nào vượt ngân sách thì xé nhỏ theo biên atom.
    units: list[AnalysisUnit] = []
    force_next = False
    for turn in turns:
        if count_tokens_of_atoms(atoms, turn) <= max_tokens:
            units.append(AnalysisUnit(tuple(turn), force_next))
            force_next = False
            continue
        units.extend(_split_oversized_turn(atoms, turn, max_tokens, force_next))
        force_next = True
    return tuple(units)


def _split_oversized_turn(
    atoms: Sequence[AnalysisAtom],
    turn: Sequence[int],
    max_tokens: int,
    force_first: bool,
) -> list[AnalysisUnit]:
    """Xé một lượt nói quá dài thành nhiều mảnh, cắt ở biên atom.

    Đầu vào:
        atoms: chuỗi atom gốc.
        turn: các chỉ số atom của lượt nói cần xé.
        max_tokens: ngân sách token cho mỗi mảnh.
        force_first: True thì mảnh đầu tiên mang cờ ``forced_boundary_before``.

    Đầu ra:
        Danh sách AnalysisUnit, mỗi cái vừa ngân sách.

    Lỗi:
        ValueError nếu một atom đơn lẻ đã dài hơn ``max_tokens``. Đây là cầu
        dao cố ý, không nới lỏng: ``soft_cap_chars`` của Stage 4 chỉ là mục
        tiêu mềm nên không có biên nào ngắn hơn để lùi về; mà ``max_tokens``
        lại đang là thứ duy nhất bảo vệ prompt không cắt bớt của
        stage07/08/12.
    """

    pieces: list[AnalysisUnit] = []
    current: list[int] = []
    current_tokens = 0
    is_first_piece = True

    for index in turn:
        atom_tokens = count_tokens(atoms[index].text_exact)
        if atom_tokens > max_tokens:
            raise ValueError(
                f"atom {atoms[index].atom_id!r} không có biên nội bộ nào đủ ngắn "
                "cho topic_segmenter.max_tokens; kiểm tra dấu câu / dấu đầu mục "
                "bị thiếu trong nguồn, hoặc nâng topic_segmenter.max_tokens"
            )
        if current and current_tokens + atom_tokens > max_tokens:
            pieces.append(AnalysisUnit(tuple(current), force_first and is_first_piece))
            is_first_piece = False
            current, current_tokens = [], 0
        current.append(index)
        current_tokens += atom_tokens

    if current:
        pieces.append(AnalysisUnit(tuple(current), force_first and is_first_piece))
    return pieces


def find_speaker_change_cuts(atoms: Sequence[AnalysisAtom]) -> tuple[int, ...]:
    """Tìm các vị trí atom mà người nói thay đổi.

    Đầu vào:
        atoms: chuỗi atom của cuộc họp.

    Đầu ra:
        Tuple chỉ số atom bắt đầu một lượt nói mới (không tính vị trí 0).
    """

    return tuple(
        index for index in range(1, len(atoms)) if atoms[index].turn_id != atoms[index - 1].turn_id
    )


# ===========================================================================
# PHẦN 2. BỘ CHẤM ĐIỂM ĐỘ GIỐNG NHAU
# ===========================================================================


class PairScorer(Protocol):
    """Giao diện chung: chấm độ giống nhau giữa hai nhóm atom."""

    def score(self, left: Sequence[int], right: Sequence[int]) -> float: ...


def _validate_cosine(value: float) -> float:
    """Đảm bảo giá trị cosine hữu hạn và nằm trong [-1, 1]."""

    if not math.isfinite(value) or not -1.0 <= value <= 1.0:
        raise ValueError("độ giống nhau phải hữu hạn và nằm trong khoảng [-1, 1]")
    return value


class CosineScorer:
    """Chấm điểm bằng cosine thuần trên phần văn bản ghép của hai nhóm atom.

    Thuộc tính:
        atoms: chuỗi atom gốc.
        adapter: bộ đo được inject; None thì dùng LexicalCosineSimilarity.
    """

    def __init__(
        self,
        atoms: Sequence[AnalysisAtom],
        *,
        similarity_adapter: CosineSimilarityAdapter | None = None,
    ) -> None:
        self._atoms = atoms
        self._adapter = similarity_adapter or LexicalCosineSimilarity()

    def _text_of(self, indices: Sequence[int]) -> str:
        """Ghép văn bản của các atom theo chỉ số."""

        return join_atoms(tuple(self._atoms[i] for i in indices))

    def score(self, left: Sequence[int], right: Sequence[int]) -> float:
        """Chấm độ giống nhau giữa hai nhóm atom.

        Đầu vào:
            left: chỉ số các atom bên trái.
            right: chỉ số các atom bên phải.

        Đầu ra:
            Cosine trong khoảng [-1, 1].
        """

        return _validate_cosine(
            float(self._adapter.similarity(self._text_of(left), self._text_of(right)))
        )


class HybridBM25CosineScorer:
    """Chấm điểm lai: ``keyword_weight * bm25_norm + semantic_weight * cosine``.

    Phần BM25 tiêu thụ trực tiếp trọng số ``lex_syllable`` của Stage 5; Stage 6
    không bao giờ ước lượng lại IDF (ràng buộc F8). Hàm mũ chỉ để bóp điểm
    BM25 vô hạn về khoảng [0, 1) cho cùng thang với cosine.

    LƯU Ý — BẤT ĐỐI XỨNG, cố ý và giữ nguyên: nhóm bên trái đóng vai document,
    nhóm bên phải cung cấp query term. Đảo thứ tự sẽ ra điểm khác. Chấp nhận
    được vì nhóm tham lam luôn chấm trái-rồi-phải theo thứ tự đọc — và đây
    chính là thứ mà cách hợp nhất ở mức vector của nhóm DP tránh được.

    Đường chấm điểm theo chuỗi văn bản thô của bản cũ (``_bm25_from_text`` /
    ``_atoms_by_text`` / ``_fallback_term_weights``) đã BỊ XÓA: nó chỉ phục vụ
    caller truyền string, và với cùng đầu vào nó cho ra số khác đường atom.
    """

    # Hằng số làm bão hòa điểm BM25. Là điểm khởi đầu để benchmark, không
    # phải hằng số đã tinh chỉnh cho production.
    BM25_SATURATION_SCALE = 2.0

    def __init__(
        self,
        atoms: Sequence[AnalysisAtom],
        atom_features: Sequence[AtomFeatures],
        *,
        similarity_adapter: CosineSimilarityAdapter | None = None,
        keyword_weight: float = 0.5,
        semantic_weight: float = 0.5,
    ) -> None:
        self._cosine = CosineScorer(atoms, similarity_adapter=similarity_adapter)
        self.keyword_weight = keyword_weight
        self.semantic_weight = semantic_weight
        self._weights = extract_keyword_weights(atoms, atom_features)

    def score(self, left: Sequence[int], right: Sequence[int]) -> float:
        """Chấm điểm lai giữa hai nhóm atom.

        Đầu vào:
            left: chỉ số các atom bên trái, đóng vai document.
            right: chỉ số các atom bên phải, cung cấp query term.

        Đầu ra:
            Điểm lai; càng cao càng nên gộp hai nhóm vào một đoạn.
        """

        document: dict[str, float] = {}
        for index in left:
            for term, weight in self._weights[index].items():
                document[term] = document.get(term, 0.0) + weight

        query_terms = {term for index in right for term in self._weights[index]}
        bm25_raw = sum(document.get(term, 0.0) for term in query_terms)
        bm25_norm = 1.0 - math.exp(-bm25_raw / self.BM25_SATURATION_SCALE)

        return self.keyword_weight * bm25_norm + self.semantic_weight * self._cosine.score(
            left, right
        )


def extract_keyword_weights(
    atoms: Sequence[AnalysisAtom], atom_features: Sequence[AtomFeatures]
) -> tuple[dict[str, float], ...]:
    """Kiểm tra và sắp lại trọng số từ khóa của Stage 5 theo vị trí atom.

    Sắp theo vị trí (thay vì tra theo atom_id) để vòng lặp chấm điểm chỉ phải
    truy cập list, không phải dict lồng dict.

    Đầu vào:
        atoms: chuỗi atom gốc.
        atom_features: đặc trưng Stage 5, thứ tự tùy ý.

    Đầu ra:
        Tuple dict {từ khóa: trọng số}, phần tử thứ i ứng với atoms[i].

    Lỗi:
        ValueError nếu atom_id trùng, không khớp một-một với atoms, hoặc
        trọng số không phải số hữu hạn không âm.
    """

    features_by_id: dict[str, AtomFeatures] = {}
    for feature in atom_features:
        if feature.atom_id in features_by_id:
            raise ValueError("atom_features có atom_id trùng nhau")
        features_by_id[feature.atom_id] = feature

    expected_ids = {atom.atom_id for atom in atoms}
    if set(features_by_id) != expected_ids:
        details = []
        if missing := sorted(expected_ids - set(features_by_id)):
            details.append("thiếu=" + ",".join(missing))
        if extra := sorted(set(features_by_id) - expected_ids):
            details.append("thừa=" + ",".join(extra))
        raise ValueError(
            "atom_features phải khớp một-một với atoms"
            + (": " + "; ".join(details) if details else "")
        )

    aligned: list[dict[str, float]] = []
    for atom in atoms:
        weights: dict[str, float] = {}
        for term, weight in features_by_id[atom.atom_id].lex_syllable:
            if not isinstance(term, str) or not term:
                raise ValueError("lex_syllable: từ khóa phải là chuỗi khác rỗng")
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise ValueError("lex_syllable: trọng số phải là số")
            value = float(weight)
            if not math.isfinite(value) or value < 0.0:
                raise ValueError("lex_syllable: trọng số phải hữu hạn và không âm")
            weights[term] = value
        aligned.append(weights)
    return tuple(aligned)


# ===========================================================================
# PHẦN 3. NHÓM BASELINE — không dùng tín hiệu nội dung
# ===========================================================================
#
# Ba mode dưới đây không phải để lấp chỗ trống. Một segmenter không vượt được
# split_uniform trên Pk thì chưa chứng minh được gì, và người phản biện sẽ hỏi.


def resolve_segment_count(context: SegmentationContext) -> int:
    """Xác định số đoạn K cho các baseline cần biết trước số đoạn.

    Thứ tự ưu tiên:
        extra["k"] -> extra["atoms_per_segment"] -> segmentation_config.k_fixed
        -> trung điểm của [min_len, max_len]

    Nên suy K từ độ dài đoạn trong đáp án của tập train rồi truyền vào. Nhánh
    trung điểm chỉ là tiện lợi, không phải một lựa chọn thí nghiệm chặt chẽ.

    Đầu vào:
        context: bối cảnh của lần chạy.

    Đầu ra:
        Số đoạn K, luôn nằm trong khoảng [1, tổng số atom].
    """

    explicit_k = context.extra.get("k")
    if explicit_k is not None:
        return max(1, min(int(explicit_k), context.atom_count))

    atoms_per_segment = context.extra.get("atoms_per_segment")
    if atoms_per_segment is not None:
        return max(1, min(round(context.atom_count / float(atoms_per_segment)), context.atom_count))

    if context.segmentation_config.k_fixed is not None:
        return max(1, min(int(context.segmentation_config.k_fixed), context.atom_count))

    midpoint = (context.segmentation_config.min_len + context.segmentation_config.max_len) / 2.0
    return max(1, min(round(context.atom_count / midpoint), context.atom_count))


@register_mode("single", family="baseline", legacy_names=("k1",))
def no_split(context: SegmentationContext) -> SegmentPlan:
    """Không cắt gì cả — cả cuộc họp là một đoạn.

    Cận dưới tầm thường về độ mịn. Nếu model không thắng nổi mode này thì tín
    hiệu nội dung chưa đóng góp gì.

    Đầu vào:
        context: bối cảnh của lần chạy.

    Đầu ra:
        Kế hoạch gồm đúng một đoạn phủ toàn bộ chuỗi atom.
    """

    return build_plan_from_cuts((), context.atom_count)


@register_mode("per_turn", family="baseline")
def split_per_turn(context: SegmentationContext) -> SegmentPlan:
    """Cắt tại mọi chỗ đổi người nói — mỗi lượt nói là một đoạn.

    Cận trên tầm thường về số đoạn. Bỏ qua ``max_tokens``, nên đây là baseline
    để đo đạc chứ không phải cấu hình chạy thật.

    Đầu vào:
        context: bối cảnh của lần chạy.

    Đầu ra:
        Kế hoạch với một đoạn cho mỗi lượt nói.
    """

    return build_plan_from_cuts(find_speaker_change_cuts(context.atoms), context.atom_count)


@register_mode("uniform", family="baseline", legacy_names=("uniform_k",))
def split_uniform(context: SegmentationContext) -> SegmentPlan:
    """Chia đều thành K đoạn bằng nhau, không nhìn nội dung.

    Mạnh bất ngờ khi cuộc họp có nhịp agenda đều, vốn đúng với phần lớn phiên
    họp Quốc hội. Đây là con số thực sự phải vượt qua.

    Đầu vào:
        context: bối cảnh; K lấy qua ``resolve_segment_count``.

    Đầu ra:
        Kế hoạch với K đoạn dài xấp xỉ bằng nhau.
    """

    k = resolve_segment_count(context)
    cut_points = [round(i * context.atom_count / k) for i in range(1, k)]
    return build_plan_from_cuts(cut_points, context.atom_count)


@register_mode("random", family="baseline", legacy_names=("random_k",))
def split_random(context: SegmentationContext) -> SegmentPlan:
    """Cắt ngẫu nhiên K đoạn, vẫn tôn trọng ``min_len``.

    Có seed nên tái lập được. Hãy chạy nhiều seed và lấy trung bình trước khi
    đưa một con số vào bảng kết quả.

    Đầu vào:
        context: bối cảnh; ``context.seed`` là hạt ngẫu nhiên.

    Đầu ra:
        Kế hoạch với tối đa K đoạn, mỗi đoạn dài ít nhất ``min_len`` atom.
    """

    k = resolve_segment_count(context)
    min_len = max(1, context.segmentation_config.min_len)
    rng = random.Random(context.seed)

    candidates = list(range(min_len, max(min_len, context.atom_count - min_len) + 1))
    rng.shuffle(candidates)

    chosen: list[int] = []
    for candidate in candidates:
        if len(chosen) >= k - 1:
            break
        if all(abs(candidate - existing) >= min_len for existing in chosen):
            chosen.append(candidate)
    return build_plan_from_cuts(chosen, context.atom_count)


# ===========================================================================
# PHẦN 4. NHÓM SEQUENTIAL — tham lam, quét trái sang phải
# ===========================================================================
#
# Bốn chiến lược cũ vốn là cùng một vòng lặp với hai công tắc: có tra ngưỡng
# độ giống nhau hay không, và vế trái của phép so là gì. Giờ chúng dùng chung
# đúng một hàm.
#
# Hạn chế chung, nói một lần: quyết định tại đơn vị thứ i là CUỐI CÙNG. Một
# biên sai không thể sửa lại. Đó chính là lý do nhóm DP tồn tại.


def run_greedy_split(
    context: SegmentationContext, *, scorer: PairScorer | None, left_window: str
) -> SegmentPlan:
    """Quét trái sang phải, gộp đơn vị vào đoạn đang mở cho tới khi phải cắt.

    Đầu vào:
        context: bối cảnh của lần chạy.
        scorer: bộ chấm điểm. None nghĩa là chỉ đóng gói theo ngân sách token,
            không nhìn nội dung.
        left_window: "prev_unit" thì vế trái là đơn vị liền trước;
            "open_chunk" thì vế trái là toàn bộ đoạn đang mở.

    Đầu ra:
        Kế hoạch chia phủ hết chuỗi atom.
    """

    units = build_analysis_units(
        context.atoms,
        respect_turn_boundaries=context.topic_config.respect_turn_boundaries,
        max_tokens=context.topic_config.max_tokens,
    )
    if not units:
        return ()

    threshold = context.topic_config.similarity_threshold
    max_tokens = context.topic_config.max_tokens

    spans: list[Span] = []
    current: list[int] = list(units[0].indices)
    pending_score: float | None = None
    pending_note = ""

    for position in range(1, len(units)):
        unit = units[position]
        within_budget = count_tokens_of_atoms(context.atoms, [*current, *unit.indices]) <= max_tokens

        similarity: float | None = None
        is_forced = False

        if scorer is None:
            # Chỉ đóng gói theo độ dài; cờ ép biên do xé lượt nói quá dài.
            is_forced = unit.forced_boundary_before
            should_append = within_budget and not is_forced
        else:
            left = units[position - 1].indices if left_window == "prev_unit" else tuple(current)
            similarity = scorer.score(left, unit.indices)
            should_append = within_budget and similarity > threshold

        if should_append:
            current.extend(unit.indices)
            continue

        # Đóng đoạn hiện tại, mở đoạn mới bắt đầu từ đơn vị này.
        spans.append(Span(current[0], current[-1] + 1, pending_score, pending_note))
        current = list(unit.indices)
        pending_score = similarity
        pending_note = FORCED_BOUNDARY_SUFFIX if is_forced else ""

    spans.append(Span(current[0], current[-1] + 1, pending_score, pending_note))
    return tuple(spans)


@register_mode("linear", family="sequential", legacy_names=("paper_chunked_linear",))
def pack_by_length(context: SegmentationContext) -> SegmentPlan:
    """Đóng gói theo ngân sách token, hoàn toàn không nhìn nội dung.

    Thực chất là một baseline, chỉ khác ở chỗ nó tôn trọng lượt nói và ngưỡng
    token.

    Đầu vào:
        context: bối cảnh của lần chạy.

    Đầu ra:
        Kế hoạch chia, mỗi đoạn vừa ngân sách token.
    """

    return run_greedy_split(context, scorer=None, left_window="open_chunk")


@register_mode("cosine_adjacent", family="sequential", legacy_names=("paper_simple_cosine",))
def greedy_adjacent_cosine(context: SegmentationContext) -> SegmentPlan:
    """Tham lam, so đơn vị LIỀN TRƯỚC với đơn vị hiện tại.

    Đầu vào:
        context: bối cảnh của lần chạy.

    Đầu ra:
        Kế hoạch chia.
    """

    return run_greedy_split(
        context,
        scorer=CosineScorer(context.atoms, similarity_adapter=context.similarity_adapter),
        left_window="prev_unit",
    )


@register_mode("cosine_chunk", family="sequential", legacy_names=("paper_complex_cosine",))
def greedy_chunk_cosine(context: SegmentationContext) -> SegmentPlan:
    """Tham lam, so TOÀN BỘ ĐOẠN ĐANG MỞ với đơn vị hiện tại.

    Nhiều ngữ cảnh hơn, nhưng đoạn càng dài thì văn bản ghép càng kéo tụt độ
    giống nhau — một thiên lệch độ dài không cố ý, khiến đoạn dài dễ bị cắt.

    Đầu vào:
        context: bối cảnh của lần chạy.

    Đầu ra:
        Kế hoạch chia.
    """

    return run_greedy_split(
        context,
        scorer=CosineScorer(context.atoms, similarity_adapter=context.similarity_adapter),
        left_window="open_chunk",
    )


@register_mode("hybrid_sequential", family="sequential", legacy_names=("hybrid_bm25_semantic",))
def greedy_hybrid(context: SegmentationContext) -> SegmentPlan:
    """Tham lam, dùng bộ chấm điểm lai BM25 + cosine.

    Đầu vào:
        context: bối cảnh; trọng số lấy từ ``topic_config``.

    Đầu ra:
        Kế hoạch chia.
    """

    return run_greedy_split(
        context,
        scorer=HybridBM25CosineScorer(
            context.atoms,
            context.atom_features,
            similarity_adapter=context.similarity_adapter,
            keyword_weight=context.topic_config.keyword_weight,
            semantic_weight=context.topic_config.semantic_weight,
        ),
        left_window="open_chunk",
    )


@register_mode("texttiling", family="sequential")
def texttiling(context: SegmentationContext) -> SegmentPlan:
    """TextTiling (Hearst 1997): cắt tại các "chỗ trũng" của đường độ giống nhau.

    Vì sao đáng có ngoài chuyện trích dẫn: các mode trên đều tra ngưỡng TUYỆT
    ĐỐI ``similarity > similarity_threshold``. Thang cosine lại trôi theo từng
    cuộc họp — họp chuyên đề hẹp thì mọi cặp đều cao, họp nhiều nội dung thì
    mọi cặp đều thấp — nên ngưỡng tinh chỉnh trên vài cuộc họp không chuyển
    được sang cuộc họp khác.

    Depth score thì TƯƠNG ĐỐI so với ngữ cảnh cục bộ:

        depth[i] = (đỉnh gần nhất bên trái - sim[i])
                 + (đỉnh gần nhất bên phải - sim[i])

    và cắt ở nơi ``depth[i] > mean(depth) - std(depth)/2``. Không thêm hằng số
    cần tinh chỉnh nào ngoài kích thước khối.

    Đầu vào:
        context: bối cảnh; ``extra["block_units"]`` đặt số đơn vị mỗi bên khi
            tính độ giống nhau (mặc định 3).

    Đầu ra:
        Kế hoạch chia. Nếu tín hiệu quá phẳng thì trả về một đoạn duy nhất.
    """

    block_size = int(context.option("block_units", 3))

    scorer: PairScorer = (
        HybridBM25CosineScorer(
            context.atoms,
            context.atom_features,
            similarity_adapter=context.similarity_adapter,
            keyword_weight=context.topic_config.keyword_weight,
            semantic_weight=context.topic_config.semantic_weight,
        )
        if getattr(context.topic_config, "keyword_weight", 0.0)
        else CosineScorer(context.atoms, similarity_adapter=context.similarity_adapter)
    )

    units = build_analysis_units(
        context.atoms,
        respect_turn_boundaries=context.topic_config.respect_turn_boundaries,
        max_tokens=context.topic_config.max_tokens,
    )
    if len(units) < 3:
        return build_plan_from_cuts((), context.atom_count)

    # Với mỗi khe giữa hai đơn vị, so khối bên trái với khối bên phải.
    similarities: list[float] = []
    for gap in range(len(units) - 1):
        left = [i for u in units[max(0, gap - block_size + 1) : gap + 1] for i in u.indices]
        right = [i for u in units[gap + 1 : gap + 1 + block_size] for i in u.indices]
        similarities.append(scorer.score(left, right))

    depths = compute_depth_scores(similarities)
    positive_depths = [value for value in depths if value > 0.0]
    if len(positive_depths) < 2:
        return build_plan_from_cuts((), context.atom_count)
    cutoff = statistics.mean(positive_depths) - statistics.stdev(positive_depths) / 2.0

    cut_points: list[int] = []
    scores: dict[int, float] = {}
    for gap, depth in enumerate(depths):
        if depth > cutoff and is_local_minimum(similarities, gap):
            start = units[gap + 1].start
            cut_points.append(start)
            scores[start] = similarities[gap]
    return build_plan_from_cuts(cut_points, context.atom_count, scores=scores)


def is_local_minimum(values: Sequence[float], index: int) -> bool:
    """Kiểm tra ``values[index]`` có phải cực tiểu cục bộ không.

    Đầu vào:
        values: dãy giá trị độ giống nhau theo từng khe.
        index: vị trí cần kiểm tra.

    Đầu ra:
        True nếu hai bên đều lớn hơn hoặc bằng giá trị tại ``index``.
    """

    left_ok = index == 0 or values[index - 1] >= values[index]
    right_ok = index == len(values) - 1 or values[index + 1] >= values[index]
    return left_ok and right_ok


def compute_depth_scores(values: Sequence[float]) -> list[float]:
    """Tính độ sâu của từng chỗ trũng trên đường độ giống nhau.

    Đầu vào:
        values: dãy độ giống nhau theo từng khe giữa hai đơn vị.

    Đầu ra:
        List cùng độ dài; phần tử thứ i là tổng độ chênh từ giá trị tại i lên
        đỉnh gần nhất ở hai phía. Trũng càng sâu thì số càng lớn.
    """

    depths: list[float] = []
    for index, value in enumerate(values):
        left_peak, cursor = value, index
        while cursor > 0 and values[cursor - 1] >= values[cursor]:
            cursor -= 1
            left_peak = max(left_peak, values[cursor])

        right_peak, cursor = value, index
        while cursor < len(values) - 1 and values[cursor + 1] >= values[cursor]:
            cursor += 1
            right_peak = max(right_peak, values[cursor])

        depths.append((left_peak - value) + (right_peak - value))
    return depths


# ===========================================================================
# PHẦN 5. NHÓM DP — tối ưu toàn cục
# ===========================================================================
#
# segmentation.py được BỌC LẠI, không bị sửa. Điểm thay đổi là ba giá trị
# k_mode của nó trở thành ba mode gọi được riêng: trước đây chọn elbow phải
# sửa SegmentationConfig.k_mode ở một chỗ KHÁC với tên strategy — hai núm để
# diễn đạt một lựa chọn.
#
# Engine bỏ qua hoàn toàn respect_turn_boundaries và max_tokens;
# min_len/max_len đếm theo ATOM. Ngân sách token được chốt ở bước sau, trong
# stage06_topic_segmentation.check_token_budget.


def run_dp_engine(context: SegmentationContext, k_mode: str) -> SegmentPlan:
    """Gọi engine DP trong segmentation.py và đổi kết quả sang danh sách Span.

    Đầu vào:
        context: bối cảnh của lần chạy.
        k_mode: "penalty" | "elbow" | "fixed".

    Đầu ra:
        Kế hoạch chia; ``score`` của mỗi đoạn là cue score tại biên, ``note``
        ghi lại chi phí của đoạn để tiện chẩn đoán.

    Lỗi:
        ValueError nếu ``beta_dense > 0`` mà không có embedding_adapter, hoặc
        cấu hình K không khả thi.
    """

    config: SegmentationConfig = context.segmentation_config
    if config.k_mode != k_mode:
        config = replace(config, k_mode=k_mode)
    logging.info(f"Running DP engine with config: {config}")
    result = dp_engine.segment(
        context.atoms,
        context.atom_features,
        config,
        embedding_adapter=context.embedding_adapter,
    )
    return tuple(
        Span(s.start_index, s.end_index, s.boundary_cue_score, note=f"cost={s.cost:.4f}")
        for s in result.segments
    )


@register_mode("dp_penalty", family="dp", legacy_names=("hybrid_bm25_semantic_v2", "dp"))
def dp_optimal(context: SegmentationContext) -> SegmentPlan:
    """Quy hoạch động, số đoạn K tự do, điều khiển bằng ``gamma``.

    Đây là mode chính của nhóm DP. Số đoạn không cần biết trước: gamma đóng
    vai "phí mỗi lần cắt", gamma càng lớn thì càng ít đoạn.

    Đầu vào:
        context: bối cảnh của lần chạy.

    Đầu ra:
        Kế hoạch chia tối ưu toàn cục theo hàm chi phí + phạt biên.
    """

    return run_dp_engine(context, "penalty")


@register_mode("dp_elbow", family="dp")
def dp_optimal_elbow(context: SegmentationContext) -> SegmentPlan:
    """Quy hoạch động, tự chọn K bằng phương pháp khuỷu tay.

    Chạy DP cố định K cho MỌI K khả thi rồi chọn điểm khuỷu, nên đắt hơn
    ``dp_optimal`` một bậc theo ``k_max``. Nên để dành cho phần ablation.

    Đầu vào:
        context: bối cảnh của lần chạy.

    Đầu ra:
        Kế hoạch chia ứng với K tại điểm khuỷu.
    """

    return run_dp_engine(context, "elbow")


@register_mode("dp_fixed", family="dp")
def dp_optimal_fixed_k(context: SegmentationContext) -> SegmentPlan:
    """Quy hoạch động với đúng ``k_fixed`` đoạn.

    Dùng cho thí nghiệm K-oracle: nếu kết quả không hơn ``dp_elbow`` bao nhiêu
    thì cách chọn K đang ổn; hơn nhiều thì vấn đề nằm ở khâu chọn K chứ không
    phải ở ma trận độ giống nhau.

    Đầu vào:
        context: bối cảnh; ``segmentation_config.k_fixed`` là số đoạn cần.

    Đầu ra:
        Kế hoạch chia gồm đúng K đoạn.

    Lỗi:
        ValueError nếu K không khả thi với min_len/max_len hiện tại.
    """

    return run_dp_engine(context, "fixed")


def make_cost_function(context: SegmentationContext):
    """Dựng hàm ``cost(a, b)`` từ bảng prefix mà engine DP xuất ra.

    Đường chéo được khôi phục bằng cách lấy tổng khối 1x1, nên hàm này chỉ cần
    API công khai ``build_segment_gram`` — segmentation.py không phải sửa gì.

    Đầu vào:
        context: bối cảnh của lần chạy.

    Đầu ra:
        Hàm ``cost(a, b) -> float``: chi phí của đoạn atom ``[a, b)``. Càng
        thấp nghĩa là các atom trong đoạn càng gắn kết với nhau.

    Lỗi:
        ValueError nếu ``beta_dense > 0`` mà không có embedding_adapter.
    """

    gram = dp_engine.build_segment_gram(
        context.atoms,
        context.segmentation_config,
        embedding_adapter=context.embedding_adapter,
    )
    prefix = gram.prefix

    def block_sum(row_from: int, row_to: int, col_from: int, col_to: int) -> float:
        """Tổng của khối chữ nhật trong ma trận Gram, lấy qua prefix 2 chiều."""

        return (
            prefix[row_to][col_to]
            - prefix[row_from][col_to]
            - prefix[row_to][col_from]
            + prefix[row_from][col_from]
        )

    diagonal = [0.0]
    for index in range(context.atom_count):
        diagonal.append(diagonal[-1] + block_sum(index, index + 1, index, index + 1))

    def cost(a: int, b: int) -> float:
        return diagonal[b] - diagonal[a] - block_sum(a, b, a, b) / (b - a)

    return cost


@register_mode("gram_greedy", family="dp")
def greedy_on_gram(context: SegmentationContext) -> SegmentPlan:
    """ĐỐI CHỨNG: cùng biểu diễn với ``dp_optimal``, nhưng tìm kiếm tham lam.

    Mở rộng đoạn hiện tại chừng nào việc đó không làm chi phí tăng quá
    ``gamma``; vượt thì cắt.

    Mode này tồn tại để tách bạch hai hiệu ứng đang bị trộn lẫn:

        dp_optimal    - greedy_on_gram    = đóng góp của TÌM KIẾM TOÀN CỤC
        greedy_on_gram - greedy_hybrid    = đóng góp của BIỂU DIỄN
                                            (BM25 đầy đủ + kênh ký tự
                                             + làm mượt + tính đối xứng)

    Không có mode này thì hai hiệu ứng đó không tách được, và cả hai con số
    đều không nói lên điều gì.

    Đầu vào:
        context: bối cảnh của lần chạy.

    Đầu ra:
        Kế hoạch chia.
    """

    cost = make_cost_function(context)
    config = context.segmentation_config
    min_len, max_len, gamma = config.min_len, config.max_len, config.gamma

    cut_points: list[int] = []
    start = 0
    for end in range(1, context.atom_count):
        length = end - start
        if length < min_len:
            continue
        if length >= max_len or cost(start, end + 1) - cost(start, end) > gamma:
            cut_points.append(end)
            start = end
    return build_plan_from_cuts(cut_points, context.atom_count)


@register_mode("dp_turn_aligned", family="dp")
def dp_turn_aligned(context: SegmentationContext) -> SegmentPlan:
    """Quy hoạch động, nhưng CHỈ được cắt tại chỗ đổi người nói.

    Lý do: trong họp hành chính do chủ tọa điều hành, biên chủ đề gần như luôn
    trùng với chỗ đổi người nói. Engine DP mức atom có thể cắt giữa lượt nói —
    ``cues.speaker_change`` chỉ GIẢM PHẠT cho biên kiểu đó chứ không BẮT BUỘC.
    Mode này biến ưu tiên mềm đó thành ràng buộc cứng.

    Lợi ích kèm theo: tập ứng viên co từ n atom xuống m lượt nói, nên đệ quy
    O(n²) thành O(m²). Một phiên họp ~3000 atom trong ~300 lượt nói giảm được
    khoảng 100 lần.

    ``min_len``/``max_len`` vẫn áp dụng, vẫn đếm theo atom.

    Đầu vào:
        context: bối cảnh của lần chạy.

    Đầu ra:
        Kế hoạch chia, mọi biên đều nằm tại chỗ đổi người nói.

    Lỗi:
        ValueError nếu không có cách chia nào vừa hợp lệ vừa thỏa min_len và
        max_len.
    """

    cost = make_cost_function(context)
    config = context.segmentation_config
    gamma, lam = config.gamma, config.lam
    min_len, max_len = config.min_len, config.max_len

    # Tập điểm cắt ứng viên: đầu cuộc họp, các chỗ đổi người nói, và điểm cuối.
    candidates = [0, *find_speaker_change_cuts(context.atoms), context.atom_count]
    cue_scores = compute_cue_scores(context)
    candidate_count = len(candidates) - 1

    # best[j] = tổng chi phí nhỏ nhất để phủ từ đầu tới candidates[j].
    best = [math.inf] * (candidate_count + 1)
    backtrack = [0] * (candidate_count + 1)
    best[0] = 0.0

    for j in range(1, candidate_count + 1):
        end = candidates[j]
        for i in range(j):
            start = candidates[i]
            if best[i] == math.inf or not (min_len <= end - start <= max_len):
                continue
            # Vị trí 0 là đầu chuỗi, không phải biên thật nên không bị phạt.
            penalty = 0.0 if start == 0 else gamma * (1.0 - lam * cue_scores[start])
            total = best[i] + cost(start, end) + penalty
            if total < best[j]:
                best[j], backtrack[j] = total, i

    if best[candidate_count] == math.inf:
        raise ValueError(
            "dp_turn_aligned: không có cách chia khả thi — các chỗ đổi người nói "
            f"không tương thích với min_len={min_len}/max_len={max_len}"
        )

    cut_points: list[int] = []
    j = candidate_count
    while j > 0:
        i = backtrack[j]
        if candidates[i] > 0:
            cut_points.append(candidates[i])
        j = i
    return build_plan_from_cuts(
        cut_points, context.atom_count, scores={cut: cue_scores[cut] for cut in cut_points}
    )


def compute_cue_scores(context: SegmentationContext) -> list[float]:
    """Tính điểm dấu hiệu chuyển ý cho từng atom.

    Dùng đúng bộ trọng số của ``segmentation._cue_scores`` để hai nhóm mode
    chấm cue trên cùng một thang.

    Đầu vào:
        context: bối cảnh; đọc ``atom_features[*].cues``.

    Đầu ra:
        List số thực trong khoảng [0, 1], cùng độ dài với chuỗi atom. Càng cao
        nghĩa là càng có bằng chứng ngôn ngữ cho một biên tại đó.
    """

    features_by_id = {feature.atom_id: feature for feature in context.atom_features}
    scores: list[float] = []
    for atom in context.atoms:
        cues = features_by_id[atom.atom_id].cues
        raw = (
            0.45 * float(cues.transition_cue)
            + 0.25 * float(cues.enumeration_cue)
            + 0.20 * float(cues.closing_cue)
            + 0.25 * float(cues.speaker_change)
        )
        scores.append(min(1.0, max(0.0, raw)))
    return scores


__all__ = [
    "AnalysisUnit",
    "CosineScorer",
    "HybridBM25CosineScorer",
    "PairScorer",
    "build_analysis_units",
    "compute_cue_scores",
    "compute_depth_scores",
    "extract_keyword_weights",
    "find_speaker_change_cuts",
    "make_cost_function",
    "resolve_segment_count",
    "run_dp_engine",
    "run_greedy_split",
]