"""Dùng mô hình DialSTART để tìm chỗ chuyển chủ đề trong cuộc họp.

Với mỗi khoảng giữa hai lượt nói liền nhau, mô hình chấm xem hai bên còn "liền mạch" với nhau tới
đâu. Chỗ điểm tụt sâu hơn hẳn xung quanh là nơi có khả năng chuyển chủ đề.

So với cách đánh giá khi nghiên cứu, bản chạy thật có ba khác biệt:

  1. Mỗi lượt nói chỉ được mã hoá một lần rồi dùng lại, thay vì mã hoá lại cho từng khoảng; kết
     quả như nhau nhưng nhanh hơn nhiều.
  2. Khi chạy thật không biết trước có bao nhiêu chủ đề, nên ranh giới được tự chọn: làm mượt điểm,
     lấy ngưỡng, bỏ đoạn quá ngắn, gộp các đoạn liền nhau cùng chủ đề, và tách đoạn quá dài.
  3. Lượt nói không bị cắt ngắn như khi đánh giá, mà giữ giống lúc huấn luyện, vì lượt nói trong
     cuộc họp thật dài hơn nhiều so với dữ liệu tổng hợp. Vẫn có thể bật lại cách cắt cũ để so sánh.

Phần này chỉ trả về vị trí các ranh giới; nơi gọi tự đóng gói thành các đoạn chủ đề.
"""

from __future__ import annotations

import bisect
import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from transformers import BertTokenizer

from .dialstart_model import SegModel

logger = logging.getLogger(__name__)

# Checkpoint (~1 GB, không commit) vẫn nằm ở thư mục thí nghiệm đã train ra nó.
DEFAULT_CHECKPOINT_PATH = Path(__file__).resolve().parents[3] / "experiments" / "dialstart" / "model_vn3" / "best.pt"
# Cả hai nhánh (topic + coherence) của best.pt đều fine-tune từ backbone này (vocab 62000).
DEFAULT_BACKBONE_NAME = "NlpHUST/vibert4news-base-cased"

# Khớp lúc train (``dial-start/data_preprocess.py``): mỗi câu / ngữ cảnh tối đa 256 token.
_ENCODE_MAX_TOKENS = 256


def depth_scores(scores: Sequence[float]) -> list[float]:
    """Tính độ tụt (depth score) của từng khe so với đỉnh gần nhất ở hai bên, kiểu TextTiling.

    Từ mỗi khe, leo dần sang trái và sang phải chừng nào điểm còn không giảm để tìm hai đỉnh; độ
    tụt là trung bình độ chênh từ hai đỉnh đó xuống điểm của khe. Khe đầu chỉ có đỉnh bên phải,
    khe cuối chỉ có đỉnh bên trái. Cách tính giống mã đánh giá gốc của DialSTART.

    Args:
        scores: Điểm liền mạch của từng khe giữa hai lượt nói liền nhau; thấp là dễ chuyển chủ đề.

    Returns:
        Độ tụt của từng khe, cùng độ dài với ``scores``, luôn không âm; càng lớn càng giống ranh
        giới chủ đề.
    """

    n = len(scores)
    output = []
    for i in range(n):
        left_peak = right_peak = scores[i]
        if i < n - 1:
            for r in range(i + 1, n):
                if right_peak <= scores[r]:
                    right_peak = scores[r]
                else:
                    break
        if i > 0:
            for l in range(i - 1, -1, -1):
                if left_peak <= scores[l]:
                    left_peak = scores[l]
                else:
                    break
        output.append(0.5 * (left_peak + right_peak - 2 * scores[i]))
    return output


def smooth_scores(scores: Sequence[float], window: int) -> list[float]:
    """Làm mượt điểm các khe bằng trung bình trượt căn giữa, như TextTiling.

    Mục đích là lấp các chỗ trũng giả chỉ rộng một khe do câu xen ngang ngắn ("Vâng.", "Mời anh
    Hùng.") trước khi tính độ tụt. Ở hai đầu dãy, cửa sổ tự co lại cho vừa.

    Args:
        scores: Điểm liền mạch của từng khe.
        window: Số khe trong cửa sổ; nên là số lẻ. ``window <= 1`` thì không làm mượt.

    Returns:
        Dãy điểm đã làm mượt, cùng độ dài với ``scores``.
    """

    if window <= 1 or len(scores) < 2:
        return list(scores)
    half = window // 2
    prefix = np.concatenate([[0.0], np.cumsum(scores)])
    n = len(scores)
    return [
        float((prefix[min(n, i + half + 1)] - prefix[max(0, i - half)]) / (min(n, i + half + 1) - max(0, i - half)))
        for i in range(n)
    ]


def _segment_ok(start: int, boundary: int, end: int, min_size: int) -> bool:
    """Kiểm tra cắt ``[start, end)`` tại ``boundary`` có để cả hai phía đủ ``min_size`` phần tử."""

    return boundary - start >= min_size and end - boundary >= min_size


def _threshold_edges(depths: np.ndarray, n_items: int, min_size: int, threshold_std: float) -> list[int]:
    """Chọn ranh giới ban đầu: các khe có độ tụt vượt ngưỡng ``mean + threshold_std * std``.

    Khe được xét theo độ tụt giảm dần; khe nào khiến một trong hai đoạn kề ngắn hơn ``min_size``
    phần tử thì bị bỏ qua.

    Returns:
        Danh sách mép đoạn ``[0, ranh giới..., n_items]``, tăng dần.
    """

    threshold = float(depths.mean() + threshold_std * depths.std())
    edges = [0, n_items]
    for gap in np.argsort(-depths, kind="stable"):
        if depths[gap] <= threshold:
            break
        boundary = int(gap) + 1
        pos = bisect.bisect(edges, boundary)
        if _segment_ok(edges[pos - 1], boundary, edges[pos], min_size):
            edges.insert(pos, boundary)
    return edges


def _drop_short_segments(
    edges: list[int], depths: np.ndarray, char_prefix: np.ndarray, min_segment_chars: int
) -> list[int]:
    """Gộp dần các đoạn vụn có ít ký tự hơn ``min_segment_chars`` vào đoạn bên cạnh.

    Mỗi vòng lấy đoạn ngắn nhất (tính theo ký tự); nếu nó còn dưới sàn thì xoá mép yếu hơn
    (độ tụt thấp hơn) trong hai mép của nó. Dừng khi mọi đoạn đạt sàn hoặc chỉ còn một đoạn.

    Returns:
        Danh sách mép đoạn mới, vẫn bắt đầu bằng 0 và kết thúc bằng số phần tử.
    """

    edges = list(edges)
    while len(edges) > 2:
        sizes = [char_prefix[b] - char_prefix[a] for a, b in zip(edges[:-1], edges[1:])]
        shortest = int(np.argmin(sizes))
        if sizes[shortest] >= min_segment_chars:
            break
        candidates = [pos for pos in (shortest, shortest + 1) if 0 < pos < len(edges) - 1]
        del edges[min(candidates, key=lambda pos: depths[edges[pos] - 1])]
    return edges


def _merge_similar_segments(
    edges: list[int],
    embeddings: np.ndarray,
    merge_threshold: float,
    char_prefix: np.ndarray,
    max_segment_chars: int | None,
) -> list[int]:
    """Gộp dần các cặp đoạn liền kề có cùng chủ đề.

    Mỗi vòng so cosine giữa embedding chủ đề trung bình của từng cặp đoạn kề nhau và gộp cặp giống
    nhau nhất nếu đạt ``merge_threshold``. Cặp nào gộp lại sẽ vượt ``max_segment_chars`` thì không
    được gộp. Dùng để chữa một chủ đề bị cắt đôi bởi một đoạn xen ngang.

    Returns:
        Danh sách mép đoạn mới.
    """

    edges = list(edges)
    emb_prefix = np.concatenate([np.zeros((1, embeddings.shape[1])), np.cumsum(embeddings, axis=0)])
    while len(edges) > 2:
        means = np.stack([(emb_prefix[b] - emb_prefix[a]) / (b - a) for a, b in zip(edges[:-1], edges[1:])])
        means /= np.linalg.norm(means, axis=1, keepdims=True) + 1e-8
        similarities = (means[:-1] * means[1:]).sum(axis=1)
        if max_segment_chars is not None:
            merged_chars = char_prefix[edges[2:]] - char_prefix[edges[:-2]]
            similarities[merged_chars > max_segment_chars] = -np.inf
        best = int(np.argmax(similarities))
        if similarities[best] < merge_threshold:
            break
        del edges[best + 1]
    return edges


def _split_long_segments(
    edges: list[int], depths: np.ndarray, char_prefix: np.ndarray, min_size: int, max_segment_chars: int
) -> list[int]:
    """Tách dần các đoạn dài hơn ``max_segment_chars`` ký tự tại khe có độ tụt cao nhất bên trong.

    Ưu tiên khe giữ được ``min_size`` phần tử mỗi bên; nếu không có khe nào như vậy thì chấp nhận
    vi phạm ``min_size``, vì trần ký tự là ràng buộc cứng của prompt LLM. Hai nửa sau khi tách được
    xét tiếp. Đoạn chỉ có một phần tử thì không tách được, kể cả khi vượt trần.

    Returns:
        Danh sách mép đoạn mới, tăng dần.
    """

    edges = list(edges)
    pending = list(zip(edges[:-1], edges[1:]))
    while pending:
        start, end = pending.pop()
        if end - start < 2 or char_prefix[end] - char_prefix[start] <= max_segment_chars:
            continue
        inner = range(start + 1, end)
        preferred = [b for b in inner if _segment_ok(start, b, end, min_size)]
        boundary = max(preferred or inner, key=lambda b: depths[b - 1])
        bisect.insort(edges, boundary)
        pending.extend([(start, boundary), (boundary, end)])
    return edges


def select_boundaries(
    depths: Sequence[float],
    item_chars: Sequence[int],
    *,
    min_size: int,
    threshold_std: float,
    min_segment_chars: int | None = None,
    embeddings: np.ndarray | None = None,
    merge_threshold: float | None = None,
    max_segment_chars: int | None = None,
) -> list[int]:
    """Chọn ranh giới chủ đề từ độ tụt của các khe khi không biết trước số chủ đề.

    Ranh giới ``b`` nghĩa là đoạn mới bắt đầu ở phần tử ``b``, tức cắt tại khe ``b - 1``. Chạy lần
    lượt bốn bước; bước 2–4 tắt được bằng cách truyền None:

    1. Lấy các khe có độ tụt vượt ngưỡng ``mean + threshold_std * std``, mỗi đoạn tối thiểu
       ``min_size`` phần tử.
    2. Gộp các đoạn vụn ít ký tự hơn ``min_segment_chars`` vào đoạn kề, qua mép yếu hơn.
    3. Gộp các đoạn liền kề có embedding chủ đề trung bình giống nhau (cần cả ``embeddings``).
    4. Tách các đoạn vượt ``max_segment_chars`` ký tự để prompt LLM phía sau không quá dài.

    Args:
        depths: Độ tụt của n-1 khe, với n là số phần tử.
        item_chars: Độ dài (ký tự) của từng phần tử; quyết định n.
        min_size: Số phần tử tối thiểu mỗi đoạn ở bước 1 (bước 4 ưu tiên giữ nhưng có thể phá).
        threshold_std: Hệ số k của độ lệch chuẩn trong ngưỡng; càng lớn càng ít ranh giới.
        min_segment_chars: Sàn ký tự mỗi đoạn cho bước 2; None để bỏ bước.
        embeddings: Mảng (n, d) embedding chủ đề từng phần tử cho bước 3; None để bỏ bước.
        merge_threshold: Ngưỡng cosine để gộp ở bước 3; None để bỏ bước.
        max_segment_chars: Trần ký tự mỗi đoạn, dùng ở bước 3 và 4; None để không giới hạn.

    Returns:
        Các ranh giới tăng dần, nằm trong ``(0, n)``; rỗng nếu không cần cắt hoặc n <= 1.
    """

    n_items = len(item_chars)
    if n_items <= 1 or not len(depths):
        return []

    depth_array = np.asarray(depths, dtype=np.float64)
    char_prefix = np.concatenate([[0], np.cumsum(item_chars)])

    edges = _threshold_edges(depth_array, n_items, min_size, threshold_std)
    if min_segment_chars is not None:
        edges = _drop_short_segments(edges, depth_array, char_prefix, min_segment_chars)
    if merge_threshold is not None and embeddings is not None:
        edges = _merge_similar_segments(edges, embeddings, merge_threshold, char_prefix, max_segment_chars)
    if max_segment_chars is not None:
        edges = _split_long_segments(edges, depth_array, char_prefix, min_size, max_segment_chars)
    return edges[1:-1]


class DialStartSegmenter:
    """Bộ chia chủ đề dùng checkpoint DialSTART đã huấn luyện, trả về ranh giới trên dãy lượt nói.

    Việc khởi tạo nạp khoảng 1 GB trọng số nên chỉ tạo một lần rồi dùng lại cho mọi request.
    Checkpoint được nạp không chặt: khóa thiếu hoặc thừa chỉ được ghi cảnh báo vào log, nên cần để
    ý log khi đổi checkpoint hoặc backbone.

    Args:
        checkpoint_path: File trọng số (state dict) của mô hình; mặc định là checkpoint trong thư
            mục thí nghiệm đã huấn luyện ra nó.
        backbone_name: Tên mô hình trên HuggingFace dùng làm backbone khi huấn luyện, áp cho cả
            nhánh chủ đề lẫn nhánh liền mạch; tokenizer cũng nạp theo tên này.
        device: Thiết bị suy luận; None thì dùng CUDA nếu có, không thì CPU.
        window_size: Số lượt nói mỗi bên khe được đưa vào ngữ cảnh; phải khớp giá trị đã dùng khi
            đánh giá checkpoint.
        max_len: Số token tối đa của một cặp đưa vào nhánh liền mạch; phải khớp lúc huấn luyện.
        batch_size: Số câu hoặc cặp tối đa trong một lần chạy mô hình.
        max_batch_tokens: Trần (số câu x độ dài câu dài nhất) mỗi batch, để lượt nói dài không làm
            tràn bộ nhớ GPU nhỏ.
        utterance_char_limit: Cắt mỗi lượt nói còn bấy nhiêu ký tự trước khi mã hoá. None (mặc
            định) giữ nguyên như lúc huấn luyện; 128 tái hiện cách cắt của mã đánh giá gốc. Lưu
            ý: lượt nói ngay sau khe trong cặp liền mạch không bị cắt theo giới hạn này.
    """

    def __init__(
        self,
        checkpoint_path: str | Path = DEFAULT_CHECKPOINT_PATH,
        *,
        backbone_name: str = DEFAULT_BACKBONE_NAME,
        device: str | torch.device | None = None,
        window_size: int = 2,
        max_len: int = 512,
        batch_size: int = 32,
        max_batch_tokens: int = 4096,
        utterance_char_limit: int | None = None,
    ) -> None:
        """Nạp tokenizer, dựng mô hình theo backbone rồi đổ trọng số checkpoint vào (xem class)."""

        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.window_size = window_size
        self.max_len = max_len
        self.batch_size = batch_size
        self.max_batch_tokens = max_batch_tokens
        self.utterance_char_limit = utterance_char_limit

        self.tokenizer = BertTokenizer.from_pretrained(backbone_name)
        self.model = SegModel(topic_model_name=backbone_name, coheren_model_name=backbone_name)
        state_dict = torch.load(checkpoint_path, map_location="cpu")
        incompatible = self.model.load_state_dict(state_dict, strict=False)
        if incompatible.missing_keys or incompatible.unexpected_keys:
            logger.warning(
                "DialSTART checkpoint %s: missing=%s unexpected=%s",
                checkpoint_path,
                incompatible.missing_keys,
                incompatible.unexpected_keys,
            )
        self.model.to(self.device)
        self.model.eval()

    def _clip(self, text: str) -> str:
        """Cắt lượt nói còn ``utterance_char_limit`` ký tự đầu; không cắt nếu giới hạn là None."""

        return text if self.utterance_char_limit is None else text[: self.utterance_char_limit]

    def _length_batches(self, lengths: Sequence[int]) -> list[list[int]]:
        """Gom chỉ số câu thành các batch theo độ dài tăng dần để giảm phần đệm.

        Mỗi batch có tối đa ``batch_size`` câu và (số câu x độ dài câu dài nhất) không vượt
        ``max_batch_tokens``, vì mọi câu trong batch được đệm bằng câu dài nhất. Một câu đơn lẻ dài
        hơn trần vẫn được xếp thành một batch riêng.

        Args:
            lengths: Số token của từng câu.

        Returns:
            Danh sách batch, mỗi batch là danh sách chỉ số câu.
        """

        batches: list[list[int]] = []
        for index in sorted(range(len(lengths)), key=lengths.__getitem__):
            batch = batches[-1] if batches else None
            if (
                batch is None
                or len(batch) >= self.batch_size
                or (len(batch) + 1) * lengths[index] > self.max_batch_tokens
            ):
                batches.append([index])
            else:
                batch.append(index)
        return batches

    @torch.no_grad()
    def _forward_padded(
        self, sequences: Sequence[tuple[list[int], list[int]]], forward
    ) -> torch.Tensor:
        """Chạy mô hình trên các chuỗi token đã mã hoá theo từng batch, giữ đúng thứ tự đầu vào.

        Chuỗi được đệm bằng token 0; mặt nạ chú ý suy ra từ token khác 0.

        Args:
            sequences: Các cặp (mã token, mã loại đoạn) của từng chuỗi.
            forward: Hàm nhận ``(input_ids, attention_mask, type_ids)`` trên thiết bị suy luận và
                trả một tensor có một hàng cho mỗi chuỗi trong batch.

        Returns:
            Tensor xếp chồng kết quả từng chuỗi, theo đúng thứ tự ``sequences``.
        """

        outputs: list[torch.Tensor | None] = [None] * len(sequences)
        for batch in self._length_batches([len(ids) for ids, _ in sequences]):
            width = max(len(sequences[i][0]) for i in batch)
            input_ids = torch.zeros((len(batch), width), dtype=torch.long)
            type_ids = torch.ones((len(batch), width), dtype=torch.long)
            for row, i in enumerate(batch):
                ids, types = sequences[i]
                input_ids[row, : len(ids)] = torch.tensor(ids)
                type_ids[row, : len(types)] = torch.tensor(types)
            attention_mask = (input_ids > 0).long()
            result = forward(input_ids.to(self.device), attention_mask.to(self.device), type_ids.to(self.device))
            for row, i in enumerate(batch):
                outputs[i] = result[row]
        return torch.stack(outputs)

    def _embed_topics(self, texts: Sequence[str]) -> torch.Tensor:
        """Tính embedding chủ đề (đầu ra gộp của nhánh chủ đề) cho từng lượt nói.

        Mỗi lượt được mã hoá một mình, cắt ở ``_ENCODE_MAX_TOKENS`` token như lúc huấn luyện.

        Returns:
            Tensor (số lượt, d) trên thiết bị suy luận.
        """

        sequences = []
        for text in texts:
            ids = self.tokenizer.encode(self._clip(text), add_special_tokens=True, truncation=True, max_length=_ENCODE_MAX_TOKENS)
            sequences.append((ids, [0] * len(ids)))
        return self._forward_padded(
            sequences, lambda ids, mask, types: self.model.topic_model(ids, mask, types)[1]
        )

    def _encode_coherence_pair(self, context: Sequence[str], next_text: str) -> tuple[list[int], list[int]]:
        """Mã hoá cặp (ngữ cảnh bên trái khe, lượt nói ngay sau khe) đúng như lúc huấn luyện.

        Các lượt ngữ cảnh được nối bằng [SEP]. Ngữ cảnh chỉ giữ ``_ENCODE_MAX_TOKENS`` token CUỐI
        (bỏ [SEP] chót), tức phần sát khe nhất; lượt kế tiếp giữ phần đầu, cũng tối đa
        ``_ENCODE_MAX_TOKENS`` token. Cả cặp còn bị cắt ở ``max_len``.

        Args:
            context: Các lượt nói bên trái khe, theo thứ tự.
            next_text: Lượt nói ngay sau khe.

        Returns:
            Cặp (mã token, mã loại đoạn), loại 0 cho ngữ cảnh và 1 cho lượt kế tiếp.
        """

        sent1 = "".join(f"{sentence}[SEP]" for sentence in context)
        ids1 = self.tokenizer.encode(sent1, add_special_tokens=True)[-(_ENCODE_MAX_TOKENS + 1) : -1]
        ids2 = self.tokenizer.encode(next_text, add_special_tokens=True, truncation=True, max_length=_ENCODE_MAX_TOKENS)
        input_ids = (ids1 + ids2[1:])[: self.max_len]
        type_ids = ([0] * len(ids1) + [1] * (len(ids2) - 1))[: self.max_len]
        return input_ids, type_ids

    def _coherence_logits(self, texts: Sequence[str]) -> torch.Tensor:
        """Tính logit "liền mạch" của nhánh dự đoán câu kế tiếp cho từng khe.

        Khe ``i`` nằm giữa ``texts[i]`` và ``texts[i+1]``; ngữ cảnh là tối đa ``window_size`` lượt
        kết thúc ở ``texts[i]``.

        Returns:
            Tensor một chiều n-1 phần tử (cột 0 của logit, lớn là liền mạch), chưa qua sigmoid.
        """

        pairs = []
        for gap in range(len(texts) - 1):
            context = [self._clip(texts[j]) for j in range(max(0, gap - self.window_size + 1), gap + 1)]
            pairs.append(self._encode_coherence_pair(context, texts[gap + 1]))
        return self._forward_padded(
            pairs, lambda ids, mask, types: self.model.coheren_model(ids, mask, types)[0][0][:, 0]
        )

    def score_gaps_with_embeddings(self, texts: Sequence[str]) -> tuple[list[float], np.ndarray]:
        """Chấm điểm liền mạch cho từng khe giữa hai lượt nói, kèm embedding chủ đề của từng lượt.

        Điểm của khe là sigmoid của tổng hai thành phần: logit "liền mạch" của nhánh dự đoán câu
        kế tiếp, và cosine giữa embedding chủ đề trung bình của ``window_size`` lượt bên trái với
        ``window_size`` lượt bên phải khe. Mỗi lượt chỉ được mã hoá chủ đề một lần rồi dùng lại.

        Args:
            texts: Nội dung từng lượt nói theo thứ tự.

        Returns:
            Cặp (điểm của n-1 khe trong khoảng (0, 1), thấp là dễ chuyển chủ đề; mảng (n, d)
            embedding chủ đề). Ít hơn hai lượt thì trả danh sách rỗng và mảng (n, 0).
        """

        if len(texts) < 2:
            return [], np.zeros((len(texts), 0))
        topic = self._embed_topics(texts)
        # Trung bình cửa sổ bằng tổng tích luỹ: trái = [gap-w+1, gap], phải = [gap+1, gap+w].
        prefix = torch.cat([torch.zeros_like(topic[:1]), topic.cumsum(dim=0)])
        n = len(texts)
        gaps = torch.arange(n - 1, device=topic.device)
        left_lo = (gaps - self.window_size + 1).clamp(min=0)
        left_hi = gaps + 1
        right_hi = (gaps + 1 + self.window_size).clamp(max=n)
        left_mean = (prefix[left_hi] - prefix[left_lo]) / (left_hi - left_lo).unsqueeze(1)
        right_mean = (prefix[right_hi] - prefix[left_hi]) / (right_hi - left_hi).unsqueeze(1)
        topic_scores = F.cosine_similarity(left_mean, right_mean, dim=1, eps=1e-08)

        scores = torch.sigmoid(self._coherence_logits(texts) + topic_scores)
        return scores.float().cpu().tolist(), topic.float().cpu().numpy()

    def predict_boundaries(
        self,
        texts: Sequence[str],
        *,
        min_size: int,
        threshold_std: float,
        smooth_window: int = 1,
        min_segment_chars: int | None = None,
        merge_threshold: float | None = None,
        max_segment_chars: int | None = None,
        item_chars: Sequence[int] | None = None,
    ) -> list[int]:
        """Tìm các ranh giới chủ đề trên dãy lượt nói.

        Chấm điểm từng khe, làm mượt, tính độ tụt rồi chọn ranh giới theo các ràng buộc
        (xem ``select_boundaries``).

        Args:
            texts: Nội dung từng lượt nói, không kèm tên người nói (giống dữ liệu huấn luyện).
            min_size: Số lượt tối thiểu mỗi đoạn.
            threshold_std: Hệ số k trong ngưỡng độ tụt ``mean + k * std``.
            smooth_window: Số khe của cửa sổ làm mượt trước khi tính độ tụt; 1 là không làm mượt.
            min_segment_chars: Sàn ký tự mỗi đoạn; None để bỏ bước gộp đoạn vụn.
            merge_threshold: Ngưỡng cosine để gộp đoạn liền kề cùng chủ đề; None để bỏ bước gộp.
            max_segment_chars: Trần ký tự mỗi đoạn; None để không giới hạn.
            item_chars: Độ dài (ký tự) từng lượt dùng cho các ràng buộc ký tự; None thì lấy độ dài
                của ``texts``. Nơi gọi có thể truyền độ dài dòng có kèm tên người nói.

        Returns:
            Chỉ số lượt nói bắt đầu mỗi đoạn mới, tăng dần, nằm trong ``(0, len(texts))``.
        """

        scores, embeddings = self.score_gaps_with_embeddings(texts)
        return select_boundaries(
            depth_scores(smooth_scores(scores, smooth_window)),
            item_chars if item_chars is not None else [len(text) for text in texts],
            min_size=min_size,
            threshold_std=threshold_std,
            min_segment_chars=min_segment_chars,
            embeddings=embeddings,
            merge_threshold=merge_threshold,
            max_segment_chars=max_segment_chars,
        )
