"""Suy luận DialSTART (``model.SegModel``) trên dãy lượt nói, dùng cho pipeline API.

Tính điểm mạch lạc cho từng khe (gap) giữa lượt i và i+1 như ``eval_utils.evaluate_dataset``:

    score(i) = sigmoid( NSP_logit[0](ngữ cảnh trái, lượt i+1)
                        + cos(mean topic_emb(trái), mean topic_emb(phải)) )

rồi lấy depth score kiểu TextTiling (``depth_score_cal``). Khác ``eval_utils`` ở ba điểm:

1. Embedding chủ đề của mỗi lượt được tính MỘT lần rồi lấy trung bình theo cửa sổ, thay vì
   mã hoá lại cả cửa sổ cho từng khe. Pooled output của BERT không phụ thuộc padding (đã
   có attention mask), nên kết quả tương đương mà nhanh hơn ~2*window_size lần.
2. Không có số ranh giới "oracle" khi chạy thật, nên tự chọn ranh giới (xem
   ``select_boundaries``): làm mượt điểm, ngưỡng depth, bỏ đoạn quá ngắn, gộp đoạn liền
   kề cùng chủ đề, rồi tách đoạn vượt trần ký tự.
3. Mặc định KHÔNG cắt mỗi lượt còn 128 ký tự như ``eval_utils`` mà mã hoá giống lúc train
   (``dial-start/data_preprocess.py``): topic embedding lấy cả lượt (tối đa 256 token),
   ngữ cảnh trái của NSP giữ 256 token CUỐI (sát khe). Lượt nói trong cuộc họp thật dài
   hơn nhiều so với dữ liệu synth (~1/3 lượt > 128 ký tự, cắt 128 bỏ ~half số ký tự).
   ``utterance_char_limit=128`` tái lập đúng cách eval cũ để so sánh.

Module này chỉ trả về CHỈ SỐ ranh giới; người gọi tự đóng gói thành ``TopicSegment``.
"""

from __future__ import annotations

import bisect
import importlib.util
import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from transformers import BertTokenizer

logger = logging.getLogger(__name__)

_EXPERIMENT_DIR = Path(__file__).resolve().parent
DEFAULT_CHECKPOINT_PATH = _EXPERIMENT_DIR / "model_vn3" / "best.pt"
# Cả hai nhánh (topic + coherence) của best.pt đều fine-tune từ backbone này (vocab 62000).
DEFAULT_BACKBONE_NAME = "NlpHUST/vibert4news-base-cased"

# Khớp lúc train (``dial-start/data_preprocess.py``): mỗi câu / ngữ cảnh tối đa 256 token.
_ENCODE_MAX_TOKENS = 256


def _load_seg_model_class() -> type:
    """Import ``SegModel`` từ ``model.py`` cạnh file này dưới một tên module riêng.

    ``model`` là tên quá chung để đưa thư mục thí nghiệm vào ``sys.path``; nạp theo đường
    dẫn tránh đụng với module ``model`` khác trong tiến trình API.
    """

    spec = importlib.util.spec_from_file_location("dialstart_model", _EXPERIMENT_DIR / "model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SegModel


def depth_scores(scores: Sequence[float]) -> list[float]:
    """Depth score từng khe: khe "lõm" sâu bao nhiêu so với đỉnh gần nhất hai bên.

    Giống ``eval_utils.depth_score_cal`` (khe đầu chỉ nhìn phải, khe cuối chỉ nhìn trái).
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
    """Trung bình trượt (cửa sổ ``window`` khe, căn giữa, co lại ở hai đầu) như TextTiling.

    Lấp các chỗ trũng giả một-khe (câu xen ngang, "Vâng", "Mời anh...") trước khi tính
    depth. ``window <= 1`` trả nguyên điểm.
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
    """Tách [start, end) tại ``boundary`` có để hai phía đều đủ ``min_size`` phần tử không."""

    return boundary - start >= min_size and end - boundary >= min_size


def _threshold_edges(depths: np.ndarray, n_items: int, min_size: int, threshold_std: float) -> list[int]:
    """Giữ khe có depth > ``mean + threshold_std * std``, duyệt depth giảm dần, bỏ khe tạo
    đoạn ngắn hơn ``min_size``. Trả ``edges`` = [0, ranh giới..., n_items]."""

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
    """Lặp: đoạn ngắn nhất (theo ký tự) còn dưới ``min_segment_chars`` thì bỏ ranh giới
    yếu hơn (depth thấp hơn) trong hai mép của nó, tức gộp vào đoạn bên cạnh."""

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
    """Lặp: gộp cặp đoạn liền kề có cosine (embedding chủ đề trung bình) cao nhất nếu
    >= ``merge_threshold`` và đoạn gộp không vượt ``max_segment_chars``."""

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
    """Đoạn dài hơn ``max_segment_chars`` thì tách tại khe depth cao nhất bên trong (ưu tiên
    khe tôn trọng ``min_size``; không có thì bỏ qua vì trần ký tự là ràng buộc cứng)."""

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
    """Chọn ranh giới từ depth score.

    Ranh giới ``b`` nghĩa là đoạn mới bắt đầu ở phần tử ``b`` (khe ``b - 1``). Các bước:

    1. Ngưỡng depth ``mean + threshold_std * std``, mỗi đoạn >= ``min_size`` phần tử.
    2. ``min_segment_chars``: bỏ đoạn vụn quá ngắn (gộp qua mép có depth thấp hơn).
    3. ``merge_threshold``: gộp đoạn liền kề có embedding chủ đề trung bình giống nhau
       (cần ``embeddings``) -- chữa một chủ đề bị cắt đôi bởi đoạn xen ngang.
    4. ``max_segment_chars``: tách đoạn vượt trần ký tự (ràng buộc cứng cho prompt LLM).

    Đầu vào:
        depths: depth score của n-1 khe (n = số phần tử).
        item_chars: độ dài (ký tự) của từng phần tử.
        min_size, threshold_std, min_segment_chars, merge_threshold, max_segment_chars:
            như trên; None là bỏ bước tương ứng.
        embeddings: (n, d) embedding chủ đề từng phần tử, dùng cho bước 3.
    Đầu ra: list[int] các ranh giới, tăng dần, nằm trong (0, n).
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
    """Bọc checkpoint DialSTART đã train để cắt chủ đề trên dãy lượt nói.

    Dựng một lần (nạp ~1GB trọng số) rồi dùng lại cho mọi request.
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
        """Nạp tokenizer, dựng ``SegModel`` với backbone và đổ trọng số checkpoint vào.

        Đầu vào:
            checkpoint_path: file ``state_dict`` của ``SegModel`` (vd. ``model/best.pt``).
            backbone_name: tên HF của backbone đã dùng khi train (cả hai nhánh).
            device: thiết bị suy luận; None thì dùng CUDA nếu có.
            window_size: số lượt mỗi phía của khe, phải khớp ``--window_size`` lúc eval.
            max_len: độ dài tối đa cặp coherence, phải khớp ``--max_len`` lúc train.
            batch_size: số câu/cặp tối đa mỗi lượt forward.
            max_batch_tokens: trần (số câu x độ dài câu dài nhất) mỗi batch, để lượt nói dài
                không làm tràn GPU nhỏ; câu được xếp theo độ dài trước khi gom batch.
            utterance_char_limit: cắt mỗi lượt còn bấy nhiêu ký tự trước khi mã hoá. None
                (mặc định) = giống lúc train; 128 = giống ``eval_utils`` (xem docstring module).
        """

        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.window_size = window_size
        self.max_len = max_len
        self.batch_size = batch_size
        self.max_batch_tokens = max_batch_tokens
        self.utterance_char_limit = utterance_char_limit

        self.tokenizer = BertTokenizer.from_pretrained(backbone_name)
        seg_model_cls = _load_seg_model_class()
        self.model = seg_model_cls(topic_model_name=backbone_name, coheren_model_name=backbone_name)
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
        """Cắt lượt nói theo ``utterance_char_limit`` (không cắt nếu None)."""

        return text if self.utterance_char_limit is None else text[: self.utterance_char_limit]

    def _length_batches(self, lengths: Sequence[int]) -> list[list[int]]:
        """Gom chỉ số câu thành batch theo độ dài tăng dần, mỗi batch <= ``batch_size`` câu
        và <= ``max_batch_tokens`` (số câu x độ dài câu dài nhất, vì mọi câu pad bằng nó)."""

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
        """Chạy ``forward(input_ids, attention_mask, type_ids)`` trên các chuỗi token đã mã
        hoá, theo batch gom độ dài; trả kết quả theo đúng thứ tự ``sequences``."""

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
        """Pooled output của nhánh topic cho từng lượt (tối đa ``_ENCODE_MAX_TOKENS`` token)."""

        sequences = []
        for text in texts:
            ids = self.tokenizer.encode(self._clip(text), add_special_tokens=True, truncation=True, max_length=_ENCODE_MAX_TOKENS)
            sequences.append((ids, [0] * len(ids)))
        return self._forward_padded(
            sequences, lambda ids, mask, types: self.model.topic_model(ids, mask, types)[1]
        )

    def _encode_coherence_pair(self, context: Sequence[str], next_text: str) -> tuple[list[int], list[int]]:
        """Mã hoá cặp (ngữ cảnh trái nối bằng [SEP], lượt kế tiếp) như lúc train.

        Ngữ cảnh giữ ``_ENCODE_MAX_TOKENS`` token CUỐI (bỏ [SEP] chót), tức phần sát khe
        nhất -- đúng ``encoded_sent1[-257:-1]`` của ``data_preprocess.py``; lượt kế tiếp cắt
        phía sau ở ``_ENCODE_MAX_TOKENS`` token.
        """

        sent1 = "".join(f"{sentence}[SEP]" for sentence in context)
        ids1 = self.tokenizer.encode(sent1, add_special_tokens=True)[-(_ENCODE_MAX_TOKENS + 1) : -1]
        ids2 = self.tokenizer.encode(next_text, add_special_tokens=True, truncation=True, max_length=_ENCODE_MAX_TOKENS)
        input_ids = (ids1 + ids2[1:])[: self.max_len]
        type_ids = ([0] * len(ids1) + [1] * (len(ids2) - 1))[: self.max_len]
        return input_ids, type_ids

    def _coherence_logits(self, texts: Sequence[str]) -> torch.Tensor:
        """Logit NSP (cột 0 = "liền mạch") cho từng khe giữa ``texts[i]`` và ``texts[i+1]``."""

        pairs = []
        for gap in range(len(texts) - 1):
            context = [self._clip(texts[j]) for j in range(max(0, gap - self.window_size + 1), gap + 1)]
            pairs.append(self._encode_coherence_pair(context, texts[gap + 1]))
        return self._forward_padded(
            pairs, lambda ids, mask, types: self.model.coheren_model(ids, mask, types)[0][0][:, 0]
        )

    def score_gaps(self, texts: Sequence[str]) -> list[float]:
        """Điểm mạch lạc sigmoid(NSP + cos chủ đề) cho n-1 khe; thấp = dễ là ranh giới."""

        return self.score_gaps_with_embeddings(texts)[0]

    def score_gaps_with_embeddings(self, texts: Sequence[str]) -> tuple[list[float], np.ndarray]:
        """Như ``score_gaps`` nhưng trả thêm embedding chủ đề (n, d) của từng lượt."""

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
        """Chỉ số ranh giới chủ đề cho dãy lượt nói.

        Đầu vào:
            texts: nội dung từng lượt nói (không kèm tên người nói, như dữ liệu train).
            smooth_window: cửa sổ làm mượt điểm trước khi tính depth (``smooth_scores``).
            min_size, threshold_std, min_segment_chars, merge_threshold, max_segment_chars:
                xem ``select_boundaries``.
            item_chars: độ dài dùng cho các ràng buộc ký tự; mặc định ``len`` của ``texts``.
        Đầu ra: list[int] ranh giới tăng dần.
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
