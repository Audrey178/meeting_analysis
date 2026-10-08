"""Lõi thuật toán TreeSeg (Gklezakos et al., 2024, arXiv:2407.12028).

Thuật toán thuần: phân cụm chia dần (divisive clustering) trên một dãy vector
embedding tính sẵn, dựng ra một cây phân hoạch nhị phân. Không phụ thuộc miền dữ
liệu: người gọi tự quyết "một phần tử" của dòng thời gian là gì (lượt nói, atom...)
và cung cấp hàm embedding; module này không bao giờ đọc nội dung transcript.

Hàm mất mát (loss) khi tách đoạn [lo, hi) tại vị trí i thành [lo, i) và [i, hi)
(bài báo mục 2.3.2, công thức 1):

    L(i) = sum_{t=lo}^{i-1} ||e_t - mu_L||^2 + sum_{t=i}^{hi-1} ||e_t - mu_R||^2

Tính nhanh nhờ đẳng thức sum||x-mean||^2 = sum||x||^2 - n*||mean||^2, nên loss của
cả một đoạn chỉ cần bốn lần tra bảng tổng tích lũy (prefix-sum) thay vì quét lại.
Đây chính là cách "một lượt tuyến tính / tổng tích lũy" mà bài báo mô tả ở mục 2.3.2.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
import heapq

import numpy as np
from utils.contracts import AnalysisAtom, SpeakerTurn, TopicSegment

EmbedFn = Callable[[str], Sequence[float]]


def embed_items_with_preceding_context(
    texts: Sequence[str],
    embed_fn: EmbedFn,
    width: int,
    separator: str = " ",
) -> np.ndarray:
    """Tính embedding cho từng phần tử, kèm tối đa ``width`` phần tử đứng TRƯỚC nó làm ngữ cảnh.

    Theo bài báo mục 2.3.1: "khối" của phần tử t là ``texts[t-width : t+1]``, được
    nối lại thành một chuỗi rồi embed một lần. Nhờ vậy mỗi vector có ngữ cảnh cục
    bộ mà không cần thành phần huấn luyện. ``width`` là siêu tham số duy nhất của TreeSeg.

    Đầu vào:
        texts: văn bản của từng phần tử, theo thứ tự thời gian.
        embed_fn: hàm nhận một chuỗi, trả về vector embedding.
        width: số phần tử đứng trước đưa vào ngữ cảnh (>= 0).
        separator: chuỗi nối các phần tử trong một khối.

    Đầu ra: np.ndarray hình (số phần tử, số chiều embedding), kiểu float64.

    Lỗi: ValueError nếu ``width`` < 0 hoặc ``texts`` rỗng.
    """
    if width < 0:
        raise ValueError(f"width must be >= 0, got {width}")
    if not texts:
        raise ValueError("texts must be non-empty")
    vectors = [
        embed_fn(separator.join(texts[max(0, t - width) : t + 1]))
        for t in range(len(texts))
    ]
    return np.asarray(vectors, dtype=np.float64)


@dataclass(frozen=True)
class _PrefixSums:
    """Bảng tổng tích lũy giúp tính tổng bình phương trong cụm của MỌI đoạn liên tiếp trong O(1).

    Dùng thay cho việc quét lại đoạn ở mỗi điểm tách ứng viên.

    Các trường: ``vec`` là tổng tích lũy các vector, ``sq`` là tổng tích lũy bình phương độ dài.
    """

    vec: np.ndarray  # shape (T+1, D); vec[i] = sum of embeddings[0:i]
    sq: np.ndarray  # shape (T+1,); sq[i] = sum of ||embeddings[t]||^2, t in [0,i)

    @classmethod
    def from_embeddings(cls, embeddings: np.ndarray) -> "_PrefixSums":
        """Dựng bảng tổng tích lũy từ ma trận embedding.

        Đầu vào: embeddings - ma trận hình (T, D).
        Đầu ra: ``_PrefixSums`` với ``vec`` hình (T+1, D) và ``sq`` hình (T+1,).
        """

        t = embeddings.shape[0]
        vec = np.zeros((t + 1, embeddings.shape[1]), dtype=np.float64)
        vec[1:] = np.cumsum(embeddings, axis=0)
        sq = np.zeros(t + 1, dtype=np.float64)
        sq[1:] = np.cumsum(np.sum(embeddings**2, axis=1))
        return cls(vec=vec, sq=sq)

    def within_cluster_sum_of_squares(self, lo: int, hi: int) -> float:
        """Tổng bình phương khoảng cách tới tâm cụm của đoạn [lo, hi).

        Công thức: sum_{t=lo}^{hi-1} ||e_t - mean(e_lo..e_{hi-1})||^2.

        Đầu vào: lo, hi - chỉ số đầu (gồm) và cuối (không gồm) của đoạn.
        Đầu ra: float - giá trị trên; 0.0 nếu đoạn rỗng.
        """
        n = hi - lo
        if n <= 0:
            return 0.0
        vec_sum = self.vec[hi] - self.vec[lo]
        sq_sum = self.sq[hi] - self.sq[lo]
        return float(sq_sum - vec_sum.dot(vec_sum) / n)


def _find_best_split_point(
    prefix: _PrefixSums, lo: int, hi: int, min_size: int
) -> tuple[int, float] | None:
    """Tìm điểm tách tốt nhất i trong (lo, hi) sao cho cả hai bên có ít nhất ``min_size`` phần tử.

    Điểm tốt nhất là điểm làm loss L(i) (xem docstring module) nhỏ nhất. Tính vector
    hóa cho mọi điểm ứng viên cùng lúc (một lượt tuyến tính như bài báo mô tả).

    Đầu vào:
        prefix: bảng tổng tích lũy của toàn dãy.
        lo, hi: đoạn [lo, hi) cần tách.
        min_size: kích thước tối thiểu của mỗi bên sau khi tách.

    Đầu ra: tuple ``(vị_trí_tách, loss)``; None nếu đoạn quá nhỏ để tách.
    """
    lo_candidate = lo + min_size
    hi_candidate = hi - min_size + 1  # exclusive
    if lo_candidate >= hi_candidate:
        return None

    idx = np.arange(lo_candidate, hi_candidate)

    left_n = (idx - lo).astype(np.float64)
    left_vec = prefix.vec[idx] - prefix.vec[lo]
    left_sq = prefix.sq[idx] - prefix.sq[lo]
    left_loss = left_sq - np.sum(left_vec**2, axis=1) / left_n

    right_n = (hi - idx).astype(np.float64)
    right_vec = prefix.vec[hi] - prefix.vec[idx]
    right_sq = prefix.sq[hi] - prefix.sq[idx]
    right_loss = right_sq - np.sum(right_vec**2, axis=1) / right_n

    total_loss = left_loss + right_loss
    best_pos = int(np.argmin(total_loss))
    return int(idx[best_pos]), float(total_loss[best_pos])


@dataclass
class PartitionTreeNode:
    """Một nút của cây phân hoạch, ứng với đoạn chỉ số nửa mở [lo, hi) trong mảng embedding.

    Là nút lá khi ``children`` rỗng.

    ``gain`` chỉ được đặt khi nút thực sự bị tách (xem ``build_partition_tree``): là
    mức giảm phương sai khi thay nút bằng hai nút con, bằng
    ``within_cluster_sum_of_squares(lo, hi)`` (coi nút là một cụm) trừ đi loss gộp của
    hai con. Là ``None`` nếu nút chưa từng bị tách (chưa tới lượt, hoặc nhỏ hơn ``min_size``).
    """

    lo: int
    hi: int
    children: list["PartitionTreeNode"] = field(default_factory=list)
    gain: float | None = None

    @property
    def is_leaf(self) -> bool:
        """True nếu nút chưa có nút con (là một đoạn cuối cùng tiềm năng)."""

        return not self.children


@dataclass
class TreeSegResult:
    """Kết quả của TreeSeg: toàn bộ cây phân hoạch cùng thứ tự các nút được tách.

    Cắt cây ở độ phân giải bất kỳ (``cut_tree_into_n_segments``) chính là phát lại một
    đoạn đầu của ``split_order``. Vì vậy các phân hoạch lồng nhau (bài báo mục 2.2:
    "khi K tăng, thêm ranh giới mới chứ không xóa ranh giới cũ").

    Các trường:
        root: nút gốc, phủ cả dãy.
        split_order: các nút theo thứ tự đã bị tách.
        split_gains: ``split_gains[i]`` là mức giảm phương sai (gain) của ``split_order[i]``,
            bằng tổng bình phương trong cụm của nút cha trừ loss gộp của hai con.
        root_variance: tổng bình phương trong cụm của cả dãy trước khi tách, dùng để
            chuẩn hóa gain thành tỷ lệ không phụ thuộc thang đo (xem ``cut_tree_by_gain_threshold``).
    """

    root: PartitionTreeNode
    split_order: list[PartitionTreeNode]
    split_gains: list[float]
    root_variance: float


def build_partition_tree(embeddings: np.ndarray, min_size: int) -> TreeSegResult:
    """Dựng cây phân hoạch bằng phân cụm chia dần (bài báo mục 2.3.2).

    Lặp lại: tách chiếc lá có điểm tách ứng viên tốt nhất (loss thấp nhất), cho đến
    khi không lá nào tách được mà không để một bên nhỏ hơn ``min_size`` (tức mọi lá có
    kích thước < 2M). Luôn dựng cây đầy đủ; việc chọn độ phân giải do
    ``cut_tree_into_n_segments`` / ``cut_tree_by_gain_threshold`` đảm nhiệm.

    Đầu vào:
        embeddings: ma trận embedding hình (T, D).
        min_size: kích thước tối thiểu của mỗi đoạn sau khi tách (>= 1).

    Đầu ra: ``TreeSegResult`` chứa cây và thứ tự tách.

    Lỗi: ValueError nếu ``min_size`` < 1 hoặc không có embedding nào.
    """
    t = embeddings.shape[0]
    if min_size < 1:
        raise ValueError(f"min_size must be >= 1, got {min_size}")
    if t < 1:
        raise ValueError("need at least one embedding")

    prefix = _PrefixSums.from_embeddings(embeddings)
    root = PartitionTreeNode(lo=0, hi=t)
    split_order: list[PartitionTreeNode] = []
    split_gains: list[float] = []

    heap: list[tuple[float, int, PartitionTreeNode, int]] = []
    counter = 0

    def push_node_if_splittable(node: PartitionTreeNode) -> None:
        """Nếu nút còn tách được, đẩy nó vào heap theo loss (nhỏ nhất ra trước)."""

        nonlocal counter
        found = _find_best_split_point(prefix, node.lo, node.hi, min_size)
        if found is None:
            return
        split_i, loss = found
        counter += 1
        heapq.heappush(heap, (loss, counter, node, split_i))

    push_node_if_splittable(root)

    while heap:
        loss, _tie, node, split_i = heapq.heappop(heap)
        parent_ss = prefix.within_cluster_sum_of_squares(node.lo, node.hi)
        gain = parent_ss - loss
        left = PartitionTreeNode(lo=node.lo, hi=split_i)
        right = PartitionTreeNode(lo=split_i, hi=node.hi)
        node.children = [left, right]
        node.gain = gain
        split_order.append(node)
        split_gains.append(gain)
        push_node_if_splittable(left)
        push_node_if_splittable(right)

    root_variance = prefix.within_cluster_sum_of_squares(0, t)
    return TreeSegResult(
        root=root, split_order=split_order, split_gains=split_gains, root_variance=root_variance
    )


def cut_tree_into_n_segments(result: TreeSegResult, n_segments: int) -> list[tuple[int, int]]:
    """Cắt cây thành đúng ``n_segments`` đoạn liên tiếp (bài báo mục 2.2: hỏi cây với K mong muốn).

    Đầu vào:
        result: kết quả từ ``build_partition_tree``.
        n_segments: số đoạn mong muốn (>= 1).

    Đầu ra: danh sách ``(lo, hi)`` theo thứ tự thời gian. Trả ÍT hơn ``n_segments`` đoạn
    nếu cây không đủ độ phân giải (mọi lá đã nhỏ hơn 2*min_size).

    Lỗi: ValueError nếu ``n_segments`` < 1.
    """
    if n_segments < 1:
        raise ValueError(f"n_segments must be >= 1, got {n_segments}")

    n_splits = min(n_segments - 1, len(result.split_order))
    expanded = {id(node) for node in result.split_order[:n_splits]}

    frontier: list[PartitionTreeNode] = []

    def collect_frontier_leaves(node: PartitionTreeNode) -> None:
        """Duyệt cây, gom các nút biên (không bị mở rộng) vào ``frontier`` -- tức các đoạn cuối cùng."""

        if id(node) in expanded:
            for child in node.children:
                collect_frontier_leaves(child)
        else:
            frontier.append(node)

    collect_frontier_leaves(result.root)
    frontier.sort(key=lambda n: n.lo)
    return [(node.lo, node.hi) for node in frontier]


def cut_tree_by_gain_threshold(
    result: TreeSegResult,
    *,
    min_relative_gain: float = 0.0015,
    max_segments: int | None = None,
    weights: Sequence[float] | None = None,
    max_span_weight: float | None = None,
) -> list[tuple[int, int]]:
    """Chọn phân hoạch của cây bằng cách giữ mọi lần tách có gain đủ lớn, ưu tiên gain cao trước.

    Một lần tách được giữ nếu gain >= ``min_relative_gain * root_variance``. Ngưỡng này
    là ngưỡng TOÀN CỤC nên với cuộc họp dài có thể dừng quá sớm và để lại vài đoạn khổng
    lồ. ``max_span_weight`` (kèm ``weights`` từng phần tử, ví dụ số ký tự) là lớp chặn
    việc đó: đoạn nặng hơn mức trần vẫn tiếp tục bị tách, kể cả khi gain dưới ngưỡng, cho
    đến khi mỗi phần vừa mức trần hoặc không tách được nữa (dưới ``2 * min_size`` phần tử).
    ``max_segments`` có quyền cao nhất, thắng cả hai điều kiện trên.

    Đầu vào:
        result: kết quả từ ``build_partition_tree``.
        min_relative_gain: ngưỡng gain tương đối so với ``root_variance``.
        max_segments: số đoạn tối đa; None là không giới hạn.
        weights: "trọng lượng" từng phần tử (phải đi cùng ``max_span_weight``).
        max_span_weight: trọng lượng tối đa của một đoạn (phải đi cùng ``weights``).

    Đầu ra: danh sách ``(lo, hi)`` theo thứ tự thời gian, phủ hết dãy.

    Lỗi: ValueError nếu chỉ truyền một trong hai ``weights`` / ``max_span_weight``.
    """
    if (weights is None) != (max_span_weight is None):
        raise ValueError("weights and max_span_weight must be given together")
    weight_prefix = np.concatenate(([0.0], np.cumsum(weights))) if weights is not None else None

    def is_span_over_weight_cap(node: PartitionTreeNode) -> bool:
        """True nếu tổng trọng lượng của đoạn vượt ``max_span_weight`` (nên phải tiếp tục tách)."""

        return weight_prefix is not None and weight_prefix[node.hi] - weight_prefix[node.lo] > max_span_weight

    threshold = min_relative_gain * result.root_variance if result.root_variance > 0.0 else float("inf")

    heap: list[tuple[float, int, PartitionTreeNode]] = []
    counter = 0

    def push_node_by_gain(node: PartitionTreeNode) -> None:
        """Đẩy nút đã từng bị tách vào heap theo gain (gain lớn ra trước, do lưu dấu âm)."""

        nonlocal counter
        if node.gain is None:  # chưa từng bị tách (là lá, hoặc nhỏ hơn min_size)
            return
        counter += 1
        heapq.heappush(heap, (-node.gain, counter, node))

    push_node_by_gain(result.root)
    expanded: set[int] = set()
    n_segments = 1  # cả dãy là một đoạn, trước khi tách lần nào

    while heap:
        neg_gain, _tie, node = heapq.heappop(heap)
        gain = -neg_gain
        if max_segments is not None and n_segments >= max_segments:
            break
        if gain < threshold and not is_span_over_weight_cap(node):
            # Heap sắp theo gain, nhưng các nút quá nặng vẫn có thể nằm phía sau nút
            # này, nên bỏ qua nút này thay vì dừng hẳn.
            continue
        expanded.add(id(node))
        n_segments += 1  # mỗi lần mở rộng thay 1 lá bằng 2 lá
        for child in node.children:
            push_node_by_gain(child)

    frontier: list[PartitionTreeNode] = []

    def collect_frontier_leaves(node: PartitionTreeNode) -> None:
        """Duyệt cây, gom các nút biên (không bị mở rộng) vào ``frontier`` -- tức các đoạn cuối cùng."""

        if id(node) in expanded:
            for child in node.children:
                collect_frontier_leaves(child)
        else:
            frontier.append(node)

    collect_frontier_leaves(result.root)
    frontier.sort(key=lambda n: n.lo)
    return [(node.lo, node.hi) for node in frontier]


def spans_to_boundary_indices(spans: Sequence[tuple[int, int]]) -> list[int]:
    """Đổi các đoạn liên tiếp ``(lo, hi)`` sang danh sách chỉ số ranh giới.

    Theo quy ước của ``eval/segmentation_metrics.py``: ranh giới là chỉ số phần tử nơi
    một đoạn MỚI bắt đầu (không phải chỉ số cuối của đoạn trước). Với các đoạn kề nhau
    (lo0, hi0), (hi0, hi1), ... đó chính là ``hi`` của mỗi đoạn trừ đoạn cuối (điểm
    cuối của đoạn cuối là hết dãy, không phải ranh giới).

    Đầu vào: spans - các đoạn ``(lo, hi)`` liên tiếp, theo thứ tự.
    Đầu ra: list[int] các chỉ số ranh giới; rỗng nếu chỉ có một đoạn.
    """
    return [hi for _lo, hi in spans[:-1]]


def _get_item_id(item: SpeakerTurn | AnalysisAtom, index: int) -> str:
    """Lấy mã ổn định của một phần tử đầu vào TreeSeg.

    Dùng ``atom_id`` nếu người gọi truyền ``AnalysisAtom`` (cờ ``--atoms``), dùng
    ``turn_id`` nếu là ``SpeakerTurn`` (mặc định). Nếu phần tử không có thuộc tính nào
    (kiểu duck-typing) thì lấy chỉ số vị trí, để đoạn vẫn truy vết được thay vì âm thầm
    mất khóa nối.

    Đầu vào: item - phần tử đầu vào; index - vị trí của nó trong dãy.
    Đầu ra: str - mã của phần tử.
    """

    return getattr(item, "atom_id", None) or getattr(item, "turn_id", None) or str(index)


def segment_turns_with_treeseg(
    turns: Sequence[SpeakerTurn | AnalysisAtom],
    embed_fn: EmbedFn,
    width: int,
    min_size: int,
    *,
    min_relative_gain: float = 0.0015,
    max_segment_chars: int | None = None,
) -> list[TopicSegment]:
    """Chạy trọn quy trình TreeSeg trên dãy lượt nói và trả về các đoạn chủ đề.

    Các bước: dựng văn bản "người nói: nội dung" cho từng lượt, tính embedding kèm ngữ
    cảnh (``embed_items_with_preceding_context``), dựng cây (``build_partition_tree``), cắt
    cây theo ngưỡng gain (``cut_tree_by_gain_threshold``), rồi đóng gói mỗi đoạn thành
    ``TopicSegment`` với mã ``TOPIC_SEG_000000``, ``TOPIC_SEG_000001``...

    ``max_segment_chars`` giới hạn độ dài văn bản của một đoạn (xem
    ``cut_tree_by_gain_threshold``) để các lời gọi LLM phía sau không nhận chủ đề quá lớn.

    Đầu vào:
        turns: các lượt nói (hoặc atom), theo thứ tự thời gian.
        embed_fn: hàm nhận một chuỗi, trả về vector embedding.
        width: số phần tử đứng trước dùng làm ngữ cảnh khi embed.
        min_size: kích thước tối thiểu của một đoạn.
        min_relative_gain: ngưỡng gain tương đối để giữ một lần tách.
        max_segment_chars: số ký tự tối đa của một đoạn; None là không giới hạn.

    Đầu ra: list[TopicSegment], mỗi đoạn có ``atom_ids`` là mã các lượt nói của nó.

    Lưu ý: ``start_ms`` / ``end_ms`` của ``TopicSegment`` ở đây chứa CHỈ SỐ lượt nói
    (nửa mở [start, end)), KHÔNG phải mili-giây như tên gọi gợi ý.
    """
    text_speakers = [f"{turn.speaker}: {turn.text_exact}" if turn.text_exact is not None else turn.text for turn in turns]
    texts = [turn.text_exact if turn.text_exact is not None else turn.text for turn in turns]
    embeddings = embed_items_with_preceding_context(texts, embed_fn, width)
    tree_result = build_partition_tree(embeddings, min_size)
    spans = cut_tree_by_gain_threshold(
        tree_result,
        min_relative_gain=min_relative_gain,
        weights=[len(line) + 1 for line in text_speakers] if max_segment_chars else None,
        max_span_weight=max_segment_chars,
    )
    return boundaries_to_topic_segments(turns, spans_to_boundary_indices(spans))


def boundaries_to_topic_segments(
    turns: Sequence[SpeakerTurn | AnalysisAtom], boundaries: Sequence[int]
) -> list[TopicSegment]:
    """Đóng gói dãy lượt nói đã cắt tại ``boundaries`` thành các ``TopicSegment``.

    Dùng chung cho mọi bộ cắt chủ đề (TreeSeg, DialSTART...) để đầu ra cùng định dạng:
    mã ``TOPIC_SEG_000000``..., ``text`` là các dòng "người nói: nội dung", và
    ``start_ms`` / ``end_ms`` là CHỈ SỐ lượt nói (nửa mở), không phải mili-giây.

    Đầu vào:
        turns: các lượt nói (hoặc atom), theo thứ tự thời gian.
        boundaries: chỉ số bắt đầu mỗi đoạn mới, tăng dần, trong (0, len(turns)).
    Đầu ra: list[TopicSegment] phủ kín ``turns``.
    """

    text_speakers = [f"{turn.speaker}: {turn.text_exact}" if turn.text_exact is not None else turn.text for turn in turns]
    edges = [0, *boundaries, len(turns)]
    return [
        TopicSegment(
            segment_id=f"TOPIC_SEG_{index:06d}",
            atom_ids=tuple(_get_item_id(t, i) for i, t in enumerate(turns[lo:hi], start=lo)),
            text="\n".join(text_speakers[lo:hi]),
            start_ms=lo,
            end_ms=hi,
        )
        for index, (lo, hi) in enumerate(
            (lo, hi) for lo, hi in zip(edges[:-1], edges[1:]) if hi > lo
        )
    ]
