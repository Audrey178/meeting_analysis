"""STAGE 6 — CHIA CHUỖI ATOM THÀNH CÁC ĐOẠN CÙNG CHỦ ĐỀ.

Stage 6 làm đúng một việc: tìm các điểm cắt trong chuỗi atom, sao cho mỗi
đoạn nói về một chủ đề.

    - KHÔNG đặt tên cho đoạn        -> việc của Stage 7
    - KHÔNG gộp các đoạn cách xa    -> việc của Stage 8
    - KHÔNG cắt ở giữa một atom     -> atom là đơn vị nhỏ nhất

Biên được KHÓA tại đây. Stage 7 và Stage 8 chỉ đọc, không được dịch biên.

KIẾN TRÚC
---------
    atom[] -> mode(context) -> Span[] -> build_topic_segments() -> TopicSegment[]
              ^^^^^^^^^^^^^^^^^^^^^^^    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
              khác nhau từng mode        DÙNG CHUNG cho mọi mode

Mỗi mode chỉ trả về danh sách `Span` (khoảng chỉ số atom). Toàn bộ phần lắp
ráp — tra timestamp, đếm token, kiểm tra bất biến — nằm ở đây và chạy giống
hệt nhau cho baseline cắt bừa lẫn cho DP tối ưu. Đó là điều kiện để việc so
sánh giữa chúng có ý nghĩa.

Các mode nằm trong stage06_modes.py. Engine DP nằm trong segmentation.py và
KHÔNG bị sửa đổi.

QUY ƯỚC ĐẶT TÊN
---------------
Tên hàm, tên class, tên biến bằng tiếng Anh; docstring và comment bằng tiếng
Việt. Tên mode trong sổ đăng ký ("dp_penalty", "uniform", ...) giữ nguyên vì
chúng nằm trong config và trong trường `segmentation_method` của từng
segment — đổi là hỏng log và kết quả eval cũ.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import logging
from typing import Any

from ..utils.config import FeatureBuilderConfig, SegmentationConfig, TopicSegmenterConfig
from ..utils.contracts import AnalysisAtom, AtomFeatures, AtomMeta, TopicSegment
from ..utils.embeddings import EmbeddingCache
from ..utils.ports import CosineSimilarityAdapter, EmbeddingAdapter
from ._shared import join_atoms, known_max, known_min, word_tokens

logger = logging.getLogger(__name__)

# Hậu tố gắn vào segmentation_method khi biên bị ép ra bởi một lượt nói quá
# dài, chứ không phải do tín hiệu nội dung.
FORCED_BOUNDARY_SUFFIX = "+forced_oversized_turn_boundary"


# ===========================================================================
# 1. ĐẾM TOKEN
# ===========================================================================


def count_tokens(text: str) -> int:
    """Đếm số token trong một chuỗi văn bản.

    Đây là bản đếm xấp xỉ, không phụ thuộc thư viện ngoài. Khi lên production
    nên thay bằng tokenizer thật của LLM ở hạ nguồn, vì đây chính là đơn vị
    mà ngân sách prompt của stage07/08/12 được đo.

    Đầu vào:
        text: chuỗi cần đếm.

    Đầu ra:
        Số token. Trả 0 nếu chuỗi rỗng hoặc chỉ có khoảng trắng, ngược lại
        trả ít nhất 1.
    """

    return max(1, len(word_tokens(text))) if text.strip() else 0


def count_tokens_of_atoms(atoms: Sequence[AnalysisAtom], indices: Sequence[int]) -> int:
    """Đếm tổng số token của một nhóm atom.

    Đầu vào:
        atoms: toàn bộ danh sách atom của cuộc họp.
        indices: các vị trí atom cần cộng lại, ví dụ [3, 4, 5].

    Đầu ra:
        Tổng số token của phần văn bản ghép từ các atom đó.
    """

    return count_tokens(join_atoms(tuple(atoms[i] for i in indices)))


# ===========================================================================
# 2. KIỂU DỮ LIỆU CHÍNH
# ===========================================================================


@dataclass(frozen=True, slots=True)
class Span:
    """Một đoạn, biểu diễn bằng khoảng chỉ số atom nửa mở ``[start, end)``.

    Các đoạn phải liền nhau, không chồng lấn, và phủ hết chuỗi atom.

    Thuộc tính:
        start: chỉ số atom đầu tiên thuộc đoạn (tính từ 0).
        end: chỉ số atom đầu tiên KHÔNG thuộc đoạn.
        score: điểm của biên tại ``start``. Mỗi mode hiểu điểm này một kiểu
            (cosine với nhóm tham lam, cue score với nhóm DP, None với các
            mode không có khái niệm tương ứng). Chỉ dùng để chẩn đoán —
            không bước nào ở hạ nguồn được rẽ nhánh theo giá trị này.
        note: nhãn phụ, ví dụ đánh dấu biên bị ép ra do lượt nói quá dài.
    """

    start: int
    end: int
    score: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(f"đoạn rỗng hoặc ngược: [{self.start}, {self.end})")

    @property
    def atom_count(self) -> int:
        """Số atom nằm trong đoạn này."""

        return self.end - self.start


# Kết quả của một mode: danh sách các đoạn, xếp theo thứ tự đọc.
SegmentPlan = tuple[Span, ...]


@dataclass(frozen=True, slots=True)
class SegmentationContext:
    """Toàn bộ dữ liệu mà một mode được phép đọc.

    Mode không được lấy dữ liệu từ bất kỳ nguồn nào ngoài object này. Nhờ vậy
    mọi mode chạy trên cùng một đầu vào và so sánh được với nhau.

    Thuộc tính:
        atoms: chuỗi atom của một cuộc họp, đúng thứ tự thời gian.
        atom_features: đặc trưng do Stage 5 sinh ra, một phần tử mỗi atom.
        topic_config: cấu hình Stage 6 (ngưỡng, giới hạn token, ...).
        segmentation_config: cấu hình riêng của engine DP (gamma, lam, ...).
        similarity_adapter: bộ đo độ giống nhau; None thì dùng bản cosine từ
            vựng mặc định.
        embedding_adapter: nguồn vector ngữ nghĩa; bắt buộc khi beta_dense > 0.
        seed: hạt ngẫu nhiên, chỉ dùng cho baseline cắt bừa.
        extra: các tham số lẻ không đáng đưa vào config chung, ví dụ số đoạn
            mục tiêu của baseline hay kích thước khối của TextTiling.
    """

    atoms: tuple[AnalysisAtom, ...]
    atom_features: tuple[AtomFeatures, ...]
    topic_config: TopicSegmenterConfig
    segmentation_config: SegmentationConfig
    similarity_adapter: CosineSimilarityAdapter | None = None
    embedding_adapter: EmbeddingAdapter | EmbeddingCache | None = None
    seed: int = 0
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def atom_count(self) -> int:
        """Tổng số atom của cuộc họp."""

        return len(self.atoms)

    def option(self, name: str, default: Any) -> Any:
        """Lấy một tham số lẻ từ ``extra``, trả ``default`` nếu không có."""

        value = self.extra.get(name)
        return default if value is None else value


# Một mode là một hàm nhận context và trả về kế hoạch chia.
SegmentationMode = Callable[[SegmentationContext], SegmentPlan]


# ===========================================================================
# 3. SỔ ĐĂNG KÝ MODE
# ===========================================================================

_MODE_REGISTRY: dict[str, SegmentationMode] = {}
_MODE_FAMILY: dict[str, str] = {}
_MODE_LEGACY_NAMES: dict[str, str] = {}


def register_mode(
    name: str, *, family: str, legacy_names: Sequence[str] = ()
) -> Callable[[SegmentationMode], SegmentationMode]:
    """Decorator đăng ký một mode vào sổ để ``segment_topics`` gọi được.

    Đầu vào:
        name: tên chuẩn của mode, chính là chuỗi đặt trong config.
        family: "baseline" | "sequential" | "dp". Dùng để nhóm khi in bảng so
            sánh, và để quyết định có bật chốt ngân sách token hay không.
        legacy_names: các tên cũ trỏ về mode này, giúp config cũ vẫn chạy
            đúng thứ nó vẫn chạy trước đây.

    Đầu ra:
        Decorator trả về nguyên hàm được trang trí.

    Lỗi:
        ValueError nếu tên đã tồn tại trong sổ.
    """

    def decorator(function: SegmentationMode) -> SegmentationMode:
        if name in _MODE_REGISTRY:
            raise ValueError(f"mode {name!r} đã được đăng ký")
        _MODE_REGISTRY[name] = function
        _MODE_FAMILY[name] = family
        for legacy in legacy_names:
            _MODE_LEGACY_NAMES[legacy] = name
        return function

    return decorator


def normalize_mode_name(name: str) -> str:
    """Đổi tên cũ thành tên chuẩn, và kiểm tra mode có tồn tại không.

    Đầu vào:
        name: tên chuẩn hoặc tên cũ.

    Đầu ra:
        Tên chuẩn.

    Lỗi:
        ValueError kèm danh sách mode hợp lệ nếu không tìm thấy.
    """

    canonical = _MODE_LEGACY_NAMES.get(name, name)
    if canonical not in _MODE_REGISTRY:
        raise ValueError(
            f"không có mode {name!r}; các mode hiện có: " + ", ".join(sorted(_MODE_REGISTRY))
        )
    return canonical


def get_mode(name: str) -> SegmentationMode:
    """Lấy hàm mode theo tên (chấp nhận cả tên cũ)."""

    return _MODE_REGISTRY[normalize_mode_name(name)]


def get_mode_family(name: str) -> str:
    """Trả về nhóm của mode: "baseline", "sequential" hoặc "dp"."""

    return _MODE_FAMILY[normalize_mode_name(name)]


def list_modes(family: str | None = None) -> tuple[str, ...]:
    """Liệt kê các mode đã đăng ký.

    Đầu vào:
        family: lọc theo nhóm; None thì lấy tất cả.

    Đầu ra:
        Tuple tên mode, đã sắp xếp theo bảng chữ cái.
    """

    return tuple(
        sorted(name for name in _MODE_REGISTRY if family is None or _MODE_FAMILY[name] == family)
    )


# ===========================================================================
# 4. TẠO VÀ KIỂM TRA KẾ HOẠCH CHIA
# ===========================================================================


def build_plan_from_cuts(
    cut_points: Sequence[int],
    atom_count: int,
    *,
    scores: Mapping[int, float] | None = None,
    notes: Mapping[int, str] | None = None,
) -> SegmentPlan:
    """Dựng kế hoạch chia từ danh sách điểm cắt.

    Đây là cách hầu hết các mode tự diễn đạt: chỉ cần chọn ra các vị trí cắt,
    phần bookkeeping để hàm này lo.

    Đầu vào:
        cut_points: các chỉ số atom bắt đầu một đoạn mới. Vị trí 0 và các giá
            trị ngoài khoảng hợp lệ bị bỏ qua; trùng lặp được gộp.
        atom_count: tổng số atom của cuộc họp.
        scores: điểm biên theo từng vị trí cắt (tuỳ chọn).
        notes: ghi chú theo từng vị trí cắt (tuỳ chọn).

    Đầu ra:
        Kế hoạch chia liền mạch, phủ hết ``atom_count`` atom.

    Ví dụ:
        build_plan_from_cuts([6], 10) -> hai đoạn: [0,6) và [6,10)
    """

    sorted_cuts = sorted({int(cut) for cut in cut_points if 0 < int(cut) < atom_count})
    scores, notes = scores or {}, notes or {}
    return tuple(
        Span(start, end, scores.get(start), notes.get(start, ""))
        for start, end in zip([0, *sorted_cuts], [*sorted_cuts, atom_count])
    )


def validate_plan(plan: SegmentPlan, atom_count: int) -> SegmentPlan:
    """Kiểm tra kế hoạch có liền mạch và phủ hết chuỗi atom không.

    Biến một lỗi logic trong mode thành tiếng nổ ngay tại đây, thay vì thành
    một segment méo mó phát hiện ra ở ba stage sau.

    Đầu vào:
        plan: danh sách đoạn cần kiểm tra.
        atom_count: tổng số atom phải được phủ.

    Đầu ra:
        Chính ``plan`` nếu hợp lệ.

    Lỗi:
        AssertionError nếu có khoảng trống, chồng lấn, hoặc phủ thiếu/thừa.
    """

    if atom_count == 0:
        if plan:
            raise AssertionError("chuỗi atom rỗng thì kế hoạch phải rỗng")
        return plan
    if not plan:
        raise AssertionError("chuỗi atom không rỗng nhưng kế hoạch rỗng")

    cursor = 0
    for span in plan:
        if span.start != cursor:
            raise AssertionError(
                f"kế hoạch không liền mạch: chờ đoạn bắt đầu tại {cursor}, "
                f"nhận được {span.start}"
            )
        cursor = span.end
    if cursor != atom_count:
        raise AssertionError(f"kế hoạch mới phủ {cursor}/{atom_count} atom")
    return plan


# ===========================================================================
# 5. LẮP RÁP: KẾ HOẠCH -> TOPIC SEGMENT
# ===========================================================================


def _get_start_ms(atom: AnalysisAtom, atom_meta: Mapping[str, AtomMeta] | None) -> int | None:
    """Lấy mốc thời gian bắt đầu của một atom.

    AnalysisAtom không tự mang timestamp (TIP-003 / D-003); nguồn duy nhất là
    bảng tra ``atom_meta``. Thiếu dữ liệu thì trả None, không báo lỗi.
    """

    if atom_meta is None:
        return None
    record = atom_meta.get(atom.atom_id)
    return record.start_ms if record is not None else None


def _get_end_ms(atom: AnalysisAtom, atom_meta: Mapping[str, AtomMeta] | None) -> int | None:
    """Lấy mốc thời gian kết thúc của một atom. Thiếu dữ liệu thì trả None."""

    if atom_meta is None:
        return None
    record = atom_meta.get(atom.atom_id)
    return record.end_ms if record is not None else None


def build_topic_segments(
    plan: SegmentPlan,
    atoms: Sequence[AnalysisAtom],
    *,
    mode_name: str,
    atom_meta: Mapping[str, AtomMeta] | None = None,
) -> tuple[TopicSegment, ...]:
    """Biến kế hoạch chia thành các ``TopicSegment`` hoàn chỉnh.

    Đây là NƠI DUY NHẤT trong Stage 6 dựng TopicSegment. Code cũ dựng segment
    ở hai chỗ khác nhau và hai bản đã trôi khỏi nhau; giờ mọi mode đi qua
    đúng hàm này.

    Đầu vào:
        plan: danh sách đoạn do một mode trả về.
        atoms: chuỗi atom gốc.
        mode_name: chuỗi ghi vào trường ``segmentation_method``.
        atom_meta: bảng tra mốc thời gian; None thì mọi mốc là None.

    Đầu ra:
        Tuple TopicSegment. Mỗi segment có ID dạng ``TOPIC_SEG_000001``, danh
        sách atom_id, mốc thời gian đầu/cuối, số token, điểm biên.

    Lỗi:
        AssertionError nếu kết quả không sở hữu mỗi atom đúng một lần, đúng
        thứ tự.
    """

    validate_plan(plan, len(atoms))
    if not plan:
        return ()

    segments: list[TopicSegment] = []
    for position, span in enumerate(plan, start=1):
        indices = range(span.start, span.end)
        chunk = tuple(atoms[i] for i in indices)
        segments.append(
            TopicSegment(
                segment_id=f"TOPIC_SEG_{position:06d}",
                atom_ids=tuple(atom.atom_id for atom in chunk),
                text=join_atoms(chunk),
                start_ms=known_min(tuple(_get_start_ms(a, atom_meta) for a in chunk)),
                end_ms=known_max(tuple(_get_end_ms(a, atom_meta) for a in chunk)),
                token_count=count_tokens_of_atoms(atoms, indices),
                segmentation_method=(
                    mode_name + span.note if span.note.startswith("+") else mode_name
                ),
                boundary_score=span.score,
            )
        )

    # Bất biến cuối cùng: mỗi atom thuộc đúng một segment, đúng thứ tự gốc.
    owned = tuple(atom_id for segment in segments for atom_id in segment.atom_ids)
    expected = tuple(atom.atom_id for atom in atoms)
    if owned != expected or len(owned) != len(set(owned)):
        raise AssertionError("mỗi atom phải thuộc đúng một segment, đúng thứ tự")
    return tuple(segments)


def check_token_budget(
    segments: Sequence[TopicSegment], budget: int, *, on_violation: str = "warn"
) -> tuple[TopicSegment, ...]:
    """Chốt chặn cuối: báo động khi có segment vượt ngân sách prompt.

    Vá đúng cái lỗ mà nhóm mode DP để lại. ``min_len``/``max_len`` của engine
    DP đếm theo ATOM, trong khi stage07/08/12 đẩy thẳng văn bản segment vào
    prompt LLM mà không cắt bớt. Một chuỗi atom dài có thể thoả ``max_len``
    nhưng vẫn vỡ ngân sách prompt, và không chỗ nào phía trên phát hiện ra.

    Cố ý đặt ở BƯỚC SAU chứ không nhét vào hàm chi phí của DP: DP đòi hàm chi
    phí phải cộng tính trên các đoạn rời nhau, mà số token thì không. Nhét
    vào sẽ phá tính tối ưu một cách âm thầm.

    Đầu vào:
        segments: kết quả của ``build_topic_segments``.
        budget: số token tối đa cho một segment.
        on_violation: "raise" (ném lỗi), "warn" (ghi log), giá trị khác thì
            bỏ qua.

    Đầu ra:
        Chính ``segments``, không sửa đổi.

    Lỗi:
        ValueError nếu ``on_violation="raise"`` và có segment vượt ngưỡng.
    """

    violations = [s for s in segments if s.token_count > budget]
    if not violations:
        return tuple(segments)

    detail = ", ".join(f"{s.segment_id}({s.token_count} token)" for s in violations[:5])
    message = (
        f"{len(violations)} segment vượt ngân sách {budget} token: {detail}"
        f"{' ...' if len(violations) > 5 else ''}"
    )
    if on_violation == "raise":
        raise ValueError(message + "; hãy giảm segmentation.max_len hoặc nâng ngân sách")
    if on_violation == "warn":
        logger.warning(message)
    return tuple(segments)


# ===========================================================================
# 6. CỬA VÀO CHÍNH
# ===========================================================================


def build_context(
    atoms: tuple[AnalysisAtom, ...],
    *,
    topic_config: TopicSegmenterConfig,
    segmentation_config: SegmentationConfig | None = None,
    atom_features: tuple[AtomFeatures, ...] | None = None,
    similarity_adapter: CosineSimilarityAdapter | None = None,
    embedding_adapter: EmbeddingAdapter | EmbeddingCache | None = None,
    seed: int = 0,
    extra: Mapping[str, Any] | None = None,
) -> SegmentationContext:
    """Gói mọi thứ một mode cần vào một object ``SegmentationContext``.

    Đầu vào:
        atoms: chuỗi atom của cuộc họp.
        topic_config: cấu hình Stage 6.
        segmentation_config: cấu hình engine DP; None thì lấy mặc định.
        atom_features: đặc trưng Stage 5; None thì tự tính lại tại chỗ.
        similarity_adapter, embedding_adapter, seed, extra: xem docstring của
            ``SegmentationContext``.

    Đầu ra:
        Object SegmentationContext đầy đủ, sẵn sàng đưa vào bất kỳ mode nào.
    """

    if atom_features is None:
        from .stage05_atom_features import build_atom_features

        atom_features = build_atom_features(atoms, FeatureBuilderConfig())
    return SegmentationContext(
        atoms=atoms,
        atom_features=atom_features,
        topic_config=topic_config,
        segmentation_config=segmentation_config or SegmentationConfig(),
        similarity_adapter=similarity_adapter,
        embedding_adapter=embedding_adapter,
        seed=seed,
        extra=dict(extra or {}),
    )


def segment_topics(
    atoms: tuple[AnalysisAtom, ...],
    config: TopicSegmenterConfig,
    *,
    similarity_adapter: CosineSimilarityAdapter | None = None,
    atom_features: tuple[AtomFeatures, ...] | None = None,
    atom_meta: Mapping[str, AtomMeta] | None = None,
    segmentation_config: SegmentationConfig | None = None,
    embedding_adapter: EmbeddingAdapter | EmbeddingCache | None = None,
    seed: int = 0,
    extra: Mapping[str, Any] | None = None,
    token_budget: int | None = None,
    on_budget_violation: str = "warn",
) -> tuple[TopicSegment, ...]:
    """Chạy trọn vẹn Stage 6: từ chuỗi atom ra danh sách đoạn cùng chủ đề.

    Tên hàm và các tham số cũ được giữ nguyên để pipeline không phải sửa gì.

    Các bước:
        1. Kiểm tra atom_id không trùng.
        2. Chuẩn hoá tên mode (chấp nhận tên cũ).
        3. Gói dữ liệu vào SegmentationContext.
        4. Gọi mode -> nhận kế hoạch chia -> kiểm tra tính liền mạch.
        5. Lắp ráp thành TopicSegment.
        6. Chốt ngân sách token nếu cần.

    Đầu vào:
        atoms: chuỗi atom của một cuộc họp, đúng thứ tự.
        config: cấu hình Stage 6; trường ``strategy`` quyết định chạy mode nào.
        atom_meta: bảng tra mốc thời gian theo atom_id.
        token_budget: ngưỡng token cho mỗi segment. None thì mặc định lấy
            ``config.max_tokens`` với nhóm mode DP (vốn không tự chặn), và bỏ
            qua với nhóm tham lam (vốn đã chặn trong lúc đóng gói).
        on_budget_violation: "raise" | "warn" | giá trị khác để bỏ qua.
        Các tham số còn lại: xem ``build_context``.

    Đầu ra:
        Tuple TopicSegment phủ hết chuỗi atom, mỗi atom đúng một lần. Chuỗi
        atom rỗng thì trả về tuple rỗng.

    Lỗi:
        ValueError nếu atom_id trùng nhau hoặc tên mode không tồn tại.
        AssertionError nếu mode trả về kế hoạch không hợp lệ.
    """

    # Import ở đây để các mode tự đăng ký vào sổ, và để tránh import vòng.
    from . import stage06_modes  # noqa: F401

    if not atoms:
        return ()
    atom_ids = tuple(atom.atom_id for atom in atoms)
    if len(atom_ids) != len(set(atom_ids)):
        raise ValueError("Stage 6 yêu cầu atom_id không được trùng nhau")

    mode_name = normalize_mode_name(config.strategy)
    context = build_context(
        atoms,
        topic_config=config,
        segmentation_config=segmentation_config,
        atom_features=atom_features,
        similarity_adapter=similarity_adapter,
        embedding_adapter=embedding_adapter,
        seed=seed,
        extra=extra,
    )

    plan = validate_plan(get_mode(mode_name)(context), len(atoms))
    segments = build_topic_segments(plan, atoms, mode_name=config.strategy, atom_meta=atom_meta)

    # Nhóm DP không có chốt token nào bên trong, nên bật mặc định ở đây.
    if token_budget is None and get_mode_family(mode_name) == "dp":
        token_budget = config.max_tokens
    if token_budget is not None:
        segments = check_token_budget(segments, token_budget, on_violation=on_budget_violation)
    return segments


__all__ = [
    "SegmentPlan",
    "SegmentationContext",
    "SegmentationMode",
    "Span",
    "build_context",
    "build_plan_from_cuts",
    "build_topic_segments",
    "check_token_budget",
    "count_tokens",
    "count_tokens_of_atoms",
    "get_mode",
    "get_mode_family",
    "list_modes",
    "normalize_mode_name",
    "register_mode",
    "segment_topics",
    "validate_plan",
]