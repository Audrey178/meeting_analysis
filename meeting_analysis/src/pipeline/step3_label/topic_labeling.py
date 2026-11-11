"""Bước 3: đặt cho mỗi đoạn chủ đề (đã chia ở bước 2) một tiêu đề ngắn và một câu tóm tắt.

Các đoạn được đặt tên song song. Kết quả của mô hình được kiểm tra đúng khuôn dạng và không phải
một tên chung chung vô nghĩa; nếu sai thì thử lại, thử mãi không được thì lấy phần đầu của đoạn làm
tên tạm.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from ...utils.config import TopicLabelerConfig
from ...utils.contracts import TopicLabel, TopicSegment
from ...utils.llm_call_log import llm_call
from ...utils.ports import LLMAdapter, LLMUpstreamError, TopicLabelAdapter
from ..shared.text import VN_STOPWORDS, word_tokens

logger = logging.getLogger(__name__)

# Số đoạn gán nhãn song song mặc định (ghi đè bằng TOPIC_LABELER_MAX_WORKERS).
_DEFAULT_LABEL_MAX_WORKERS = 8


class StructuredLLMTopicLabeler:
    """Bộ đặt tên chủ đề dùng LLM: từ một đoạn chủ đề sinh ra tiêu đề và tóm tắt.

    Class này chỉ gọi LLM rồi đóng gói JSON trả về thành nhãn. Nó KHÔNG kiểm tra tiêu đề có chung
    chung hay không và không tự thử lại; việc đó, cùng phương án dự phòng, do ``label_topics`` đảm
    nhận.

    Args:
        llm: Adapter LLM có khả năng sinh JSON theo schema.
        model_name: Tên mô hình ghi vào nhãn để truy vết.
        max_title_chars: Độ dài tối đa của tiêu đề (ký tự); None là không giới hạn. Tiêu đề dài
            hơn bị cắt ở ranh giới từ thay vì làm hỏng cả đoạn.
    """

    def __init__(
        self,
        llm: LLMAdapter,
        *,
        model_name: str = "configured-llm",
        max_title_chars: int | None = None,
    ) -> None:
        """Lưu adapter LLM và cấu hình đặt tên (xem docstring class)."""

        self.llm = llm
        self.model_name = model_name
        self.max_title_chars = max_title_chars

    def label_topic(self, segment: TopicSegment) -> TopicLabel:
        """Hỏi LLM một tiêu đề và một đoạn tóm tắt cho một đoạn chủ đề.

        Prompt yêu cầu tiêu đề cụ thể tới mức đầu việc (ví dụ "Rà soát tiến độ tích hợp cổng thanh
        toán" thay vì "Thảo luận về dự án"), tóm tắt bám nội dung thực chất, và tự sửa lỗi nhận
        dạng giọng nói mà không bịa thêm thông tin.

        Args:
            segment: Đoạn chủ đề cần đặt tên; phải có mã đoạn và nội dung.

        Returns:
            Nhãn gồm tiêu đề và tóm tắt đã bỏ khoảng trắng hai đầu, kèm nguyên văn đoạn, đánh dấu
            phương pháp ``"llm_structured"``.

        Raises:
            ValueError: Khi thiếu mã đoạn, hoặc LLM trả tiêu đề/tóm tắt rỗng hay không phải chuỗi.
        """

        if segment.segment_id is None:
            raise ValueError("segment must have a segment_id")
        text = segment.text
        title_schema: dict = {"type": "string"}
        result = self.llm.generate_json(
            system_prompt=(
                """
Bạn là thư ký cuộc họp chuyên biên tập bản ghi ASR thành tiêu đề và
tóm tắt có nội dung cụ thể, chính xác, dễ hiểu.

NHIỆM VỤ
Đọc bản ghi của một đoạn chủ đề và trả về:
- title: vấn đề hoặc đầu việc cụ thể đang được trao đổi.
- summary: nội dung thực chất của trao đổi, gồm các thông tin quan trọng
  đã được nêu rõ trong đoạn.

Không chỉ mô tả rằng mọi người đang họp, thảo luận hoặc phối hợp.
Người đọc phải biết đoạn này bàn việc gì, xử lý như thế nào và có
kết quả, yêu cầu hoặc vướng mắc gì nếu các thông tin đó xuất hiện.

1. XÁC ĐỊNH TRỌNG TÂM
- Đọc toàn bộ đoạn, tự nhận diện lĩnh vực từ mạch nội dung.
- Xác định đối tượng cụ thể đang được bàn đến và hành động hoặc vấn đề
  gắn với đối tượng đó.
- Ưu tiên các nội dung được giải thích, demo, đánh giá hoặc chốt đầu việc;
  không để một từ nhiễu hay câu chuyển tiếp chi phối chủ đề.
- Nếu đoạn chứa nhiều ý, chọn ý trọng tâm cho title và giữ các ý quan trọng
  còn lại trong summary. Không tự tạo quan hệ giữa những ý độc lập.

2. TITLE: CỤ THỂ ĐẾN MỨC NỘI DUNG CHO PHÉP
- Đặt tiêu đề ở cấp độ đầu việc, tính năng, quy trình hoặc vấn đề cụ thể;
  không dừng ở cấp độ “dự án”, “sản phẩm”, “công nghệ” hoặc “công việc”.
- Ưu tiên cấu trúc tự nhiên:
  [Hành động/vấn đề chính] + [đối tượng cụ thể] + [phạm vi nếu cần].
- Dùng động từ đúng với nội dung như: demo, rà soát, điều chỉnh,
  xây dựng, tích hợp, xử lý, đánh giá, phân công.
  Không mặc định mọi đoạn đều là “Thảo luận về...”.
- Nếu bản ghi xác định được hạng mục, chức năng hoặc quy trình,
  phải gọi đúng hạng mục, chức năng hoặc quy trình đó trong tiêu đề,
  thay vì thay bằng một danh từ bao quát.
- Không liệt kê mọi ý vào tiêu đề. Không thêm mục tiêu hoặc kết quả
  chưa được nêu để làm tiêu đề có vẻ cụ thể.
- Viết hoa theo quy tắc tiếng Việt thông thường.

3. SUMMARY: TÓM TẮT NỘI DUNG, KHÔNG TÓM TẮT HÀNH VI THẢO LUẬN
- Viết một đoạn 2–4 câu, có thể ngắn hơn nếu ít thông tin.
- Câu đầu nêu trực tiếp vấn đề, tiến độ hoặc nội dung chính.
  Không mở đầu bằng “Cuộc họp tập trung vào”, “Nội dung xoay quanh”
  hoặc “Trong cuộc họp, các thành viên đã thảo luận”.
- Các câu tiếp theo nêu phương án, chi tiết kỹ thuật/nghiệp vụ quan trọng,
  kết quả, vướng mắc hoặc hành động tiếp theo nếu có.
- Mỗi câu phải bổ sung thông tin có thể kiểm chứng từ bản ghi.
  Bỏ câu chỉ diễn đạt mục tiêu chung mà không cung cấp nội dung mới.

Giữ lại các chi tiết phân biệt topic khi bản ghi đủ rõ:
- Tính năng nào được demo hoặc cần hoàn thiện.
- Hạng mục nào đã xong, đang làm hoặc còn vướng.
- Quy trình nhận đầu vào gì, tạo đầu ra gì, qua các bước chính nào.
- Phương án nào được đề xuất, thay đổi hoặc loại khỏi phạm vi.
- Yêu cầu hoặc ràng buộc nào ảnh hưởng đến cách triển khai.
- Ai thực hiện việc gì, thời hạn nào, nếu xác định được.

Không thay thông tin cụ thể bằng các câu như:
- “Sử dụng công nghệ mới” nếu xác định được loại công nghệ và mục đích.
- “Cải thiện quy trình” nếu xác định được bước cần thay đổi.
- “Có một số khó khăn kỹ thuật” nếu xác định được vướng mắc.
- “Đã phân công nhiệm vụ” nếu xác định được người và công việc.
- “Đảm bảo hiệu quả và đáp ứng yêu cầu” thay cho phương án thực tế.

Không bắt buộc điền đủ mọi loại thông tin kể trên.
Nếu một chi tiết bị nhiễu, chỉ khái quát chi tiết đó; không làm chung chung
toàn bộ đoạn tóm tắt hoặc bỏ các chi tiết khác đã rõ.

4. PHỤC HỒI Ý NGHĨA TỪ ASR
- Bản ghi có thể sai cả từ tiếng Việt, thuật ngữ tiếng Anh và tên riêng.
  Không mặc định một từ có nghĩa hoặc viết hoa là từ được nhận dạng đúng.
- Chuẩn hóa lỗi ASR khi ngữ âm và mạch nội dung cùng hỗ trợ cách hiểu đó.
- Với thuật ngữ bị nhiễu nhưng chức năng hoặc ý nghĩa đã rõ, ưu tiên
  diễn đạt bằng tiếng Việt rõ nghĩa thay vì chép lại từ phiên âm.
- Với tên riêng hoặc thuật ngữ không xác định được, dùng mô tả theo vai trò
  hoặc chức năng đã rõ; không tự đặt tên hoặc chọn thương hiệu quen thuộc.
- Không suy ra lĩnh vực chỉ từ một từ mơ hồ rồi dùng lĩnh vực đó để
  hợp thức hóa cách giải nghĩa các từ khác.
- Kiến thức chuyên ngành chỉ phục vụ hiểu và chuẩn hóa nội dung,
  không phải nguồn bổ sung sự kiện, mục đích hay giải pháp.

5. KHÔNG THAY ĐỔI THÔNG TIN
- Không bịa số liệu, chủ thể, sự kiện, quan hệ nhân quả hoặc nhiệm vụ.
- Không chuyển nghĩa sang một khái niệm gần giống nhưng khác bản chất.
- Phân biệt hiện trạng, đề xuất, ví dụ minh họa, yêu cầu, quyết định
  và kết quả đã hoàn thành; dùng động từ đúng trạng thái.
- Giữ nguyên điều kiện và chiều so sánh.
- Chỉ nêu người phụ trách, số liệu, tên riêng và thời hạn khi đủ rõ.
  Nhãn người nói trong bản ghi không phải lúc nào cũng chính xác.
- Không quy đổi thời gian tương đối thành ngày cụ thể nếu thiếu căn cứ.
- Không đưa lời đùa, lời thoại từ nội dung demo hoặc lời trích dẫn
  thành quyết định của cuộc họp.

6. KIỂM TRA TRƯỚC KHI TRẢ LỜI
- Nếu title có thể dùng cho nhiều đoạn họp khác nhau mà không cần sửa,
  hãy thay danh từ chung bằng đối tượng hoặc đầu việc đã rõ trong bản ghi.
- Nếu summary chỉ nói “có thảo luận”, “cần cải thiện”, “đã phân công”,
  hãy nêu rõ nội dung tương ứng khi có căn cứ.
- Xóa các chi tiết được đoán từ từ nhiễu hoặc kiến thức bên ngoài.
- Kiểm tra không bỏ mất ý phủ định, điều kiện, phạm vi hoặc trạng thái.
- Không cố viết đủ số câu bằng thông tin chung chung.

ĐẦU RA
Chỉ trả về JSON phù hợp schema với hai trường "title" và "summary".
Không thêm giải thích hoặc quá trình phân tích.
"""
            ),
            user_prompt=f"""
            Nội dung: {text}
            """,
            schema={
                "type": "object",
                "required": ["title", "summary"],
                "properties": {
                    "title": title_schema,
                    "summary": {"type": "string"},
                },
            },
        )
        title = result.get("title")
        summary = result.get("summary")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("topic label LLM must return a non-empty title")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("topic label LLM must return a non-empty summary")
        title = title.strip()
        if self.max_title_chars is not None and len(title) > self.max_title_chars:
            # Schema/prompt đã yêu cầu giới hạn này; model vẫn vượt thì cắt ở ranh
            # giới từ giống fallback trích văn bản, thay vì làm hỏng cả segment.
            truncated = title[: self.max_title_chars].rstrip()
            shortened = truncated.rsplit(" ", 1)[0] if " " in truncated else truncated
            title = shortened or truncated
        return TopicLabel(
            segment_id=segment.segment_id,
            title=title.strip(),
            summary=summary.strip(),
            text=text.strip(),
            evidence_turn_ids=None,
            method="llm_structured",
            model_name=self.model_name,
        )


def _find_label_grounding_issues(label: TopicLabel, config: TopicLabelerConfig) -> tuple[str, ...]:
    """Kiểm tra tiêu đề do LLM sinh có phải tên chung chung bị cấm hay không.

    Tiêu đề bị chặn khi trùng hẳn một mục trong danh sách cấm (không phân biệt hoa thường), hoặc,
    nếu bật kiểm tra tập con, khi mọi từ còn lại sau khi bỏ stopword đều nằm trong một mục cấm
    (ví dụ "Thảo luận về nội dung" so với mục "nội dung thảo luận"). Hàm không kiểm tra tiêu đề
    có bám nội dung đoạn hay không.

    Args:
        label: Nhãn do LLM sinh.
        config: Cấu hình đặt tên (danh sách cấm, cờ kiểm tra tập con).

    Returns:
        Tuple mã lý do (hiện chỉ có ``"title_is_generic_blacklisted"``); rỗng nghĩa là tiêu đề đạt.
    """

    issues: list[str] = []
    normalized_title = unicodedata.normalize("NFC", label.title).strip().casefold()
    exact_blacklist_match = any(
        normalized_title == unicodedata.normalize("NFC", entry).strip().casefold()
        for entry in config.title_blacklist
    )
    if exact_blacklist_match:
        issues.append("title_is_generic_blacklisted")
    elif config.blacklist_subset_check:
        title_remainder = set(_remove_stopwords(label.title))
        if title_remainder and any(
            title_remainder <= set(_remove_stopwords(entry))
            for entry in config.title_blacklist
        ):
            issues.append("title_is_generic_blacklisted")
    return tuple(issues)


def _remove_stopwords(text: str) -> tuple[str, ...]:
    """Tách văn bản thành từ và bỏ stopword tiếng Việt, giữ thứ tự các từ còn lại."""

    return tuple(word for word in word_tokens(text) if word not in VN_STOPWORDS)


def label_topics(
    segments: tuple[TopicSegment, ...],
    config: TopicLabelerConfig | None = None,
    *,
    adapter: TopicLabelAdapter | None = None,
) -> tuple[TopicLabel, ...]:
    """Đặt tiêu đề và tóm tắt cho từng đoạn chủ đề, chạy song song, giữ đúng thứ tự.

    Mỗi đoạn được gọi LLM độc lập; nhãn sai khuôn dạng hoặc tiêu đề chung chung thì hỏi lại, quá số
    lần cho phép thì lấy phần đầu nội dung đoạn làm nhãn dự phòng, nên một đoạn lỗi không làm hỏng
    cả cuộc họp. Riêng lỗi LLM nghiêm trọng (adapter đánh dấu là không thể thử lại) thì được ném
    ra ngoài. Số luồng song song đọc từ biến môi trường ``TOPIC_LABELER_MAX_WORKERS``.

    Args:
        segments: Các đoạn chủ đề theo thứ tự.
        config: Cấu hình đặt tên; None thì dùng cấu hình mặc định.
        adapter: Bộ đặt tên cho một đoạn; bắt buộc dù có mặc định None.

    Returns:
        Tuple nhãn, cùng số lượng và thứ tự với ``segments``; rỗng nếu ``segments`` rỗng.

    Raises:
        ValueError: Khi không truyền ``adapter``.
        LLMUpstreamError: Khi adapter gặp lỗi LLM nghiêm trọng.
    """

    if config is None:
        config = TopicLabelerConfig()
    if adapter is None:
        raise ValueError("topic_labeler requires a TopicLabelAdapter")
    if not segments:
        return ()
    max_workers = min(len(segments), _label_max_workers())
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        labels = pool.map(
            lambda segment: _label_one_segment(segment, config, adapter),
            segments,
        )
        return tuple(labels)


def _label_max_workers() -> int:
    """Đọc số lời gọi đặt tên chạy song song từ biến môi trường ``TOPIC_LABELER_MAX_WORKERS``.

    Mặc định 8, để thấp hơn số kết nối đồng thời mặc định của client OpenAI. Giá trị không phải số
    nguyên thì dùng mặc định; số nhỏ hơn 1 được nâng lên 1.

    Returns:
        Số luồng, luôn >= 1.
    """

    try:
        return max(1, int(os.environ.get("TOPIC_LABELER_MAX_WORKERS", _DEFAULT_LABEL_MAX_WORKERS)))
    except ValueError:
        return _DEFAULT_LABEL_MAX_WORKERS


def _label_one_segment(
    segment: TopicSegment,
    config: TopicLabelerConfig,
    adapter: TopicLabelAdapter,
) -> TopicLabel:
    """Đặt tên cho MỘT đoạn: gọi adapter, kiểm tra nhãn, thử lại, cuối cùng mới dùng dự phòng.

    Nhãn bị coi là hỏng khi adapter lỗi, sai khuôn dạng, hoặc tiêu đề chung chung bị cấm. Tổng số
    lần gọi tối đa là ``1 + config.max_retry_attempts``. Lỗi LLM nghiêm trọng không được thử lại
    mà ném thẳng ra ngoài.

    Args:
        segment: Đoạn cần đặt tên.
        config: Cấu hình đặt tên.
        adapter: Bộ đặt tên.

    Returns:
        Nhãn của LLM nếu qua được kiểm tra; nếu không, nhãn dự phòng trích từ nội dung đoạn.

    Raises:
        LLMUpstreamError: Khi adapter gặp lỗi LLM nghiêm trọng.
    """

    segment_text = segment.text or ""
    issues: tuple[str, ...] = ()
    attempt = 0
    while True:
        try:
            with llm_call(
                "topic_labeler",
                segment_id=segment.segment_id,
                prompt_chars=len(segment_text),
            ):
                label = adapter.label_topic(segment)
            _validate_label_structure(label, config)
        except Exception as exc:
            if isinstance(exc, LLMUpstreamError) and exc.fatal:
                raise
            issues = (f"adapter_error:{exc}",)
        else:
            label = dataclasses.replace(label, evidence_turn_ids=None)
            issues = _find_label_grounding_issues(label, config)
        if not issues or attempt >= config.max_retry_attempts:
            break
        attempt += 1
    if issues:
        logger.warning(
            "topic label rơi về keyword_fallback_after_guard_failure cho "
            "segment %s sau %d lần thử, lý do lần cuối: %s",
            segment.segment_id,
            attempt + 1,
            ", ".join(issues),
        )
        label = _make_extractive_fallback_label(segment, config)
    return label


def _make_extractive_fallback_label(segment: TopicSegment, config: TopicLabelerConfig) -> TopicLabel:
    """Tạo nhãn dự phòng trích nguyên văn từ đầu đoạn khi LLM không cho được nhãn dùng được.

    Tiêu đề là phần đầu nội dung đoạn, cắt ở ``max_title_chars`` ký tự và lùi về ranh giới từ;
    tóm tắt là 240 ký tự đầu. Đoạn rỗng thì dùng mã đoạn (hoặc "untitled") làm tiêu đề.

    Args:
        segment: Đoạn chủ đề.
        config: Cấu hình đặt tên (lấy độ dài tối đa của tiêu đề).

    Returns:
        Nhãn đánh dấu phương pháp ``"keyword_fallback_after_guard_failure"``, không có tên mô hình.
    """

    text = (segment.text or "").strip()
    truncated = text[: config.max_title_chars].rstrip()
    title = (truncated.rsplit(" ", 1)[0] if " " in truncated else truncated) or truncated
    title = title or segment.segment_id or "untitled"
    return TopicLabel(
        segment_id=segment.segment_id,
        title=title,
        summary=text[:240] or title,
        text=text,
        evidence_turn_ids=None,
        method="keyword_fallback_after_guard_failure",
    )


def _validate_label_structure(
    label: TopicLabel,
    config: TopicLabelerConfig,
) -> None:
    """Kiểm tra nhãn do adapter trả về đúng khuôn dạng; sai thì ném lỗi để vòng thử lại xử lý.

    Nhãn hợp lệ khi tiêu đề, tóm tắt và phương pháp là chuỗi không rỗng, tên mô hình (nếu có)
    không rỗng, và tiêu đề không dài quá ``config.max_title_chars`` ký tự.

    Args:
        label: Nhãn do adapter trả về.
        config: Cấu hình đặt tên.

    Raises:
        TypeError: Khi đối tượng trả về không phải nhãn chủ đề.
        ValueError: Khi vi phạm một trong các điều kiện trên.
    """

    if not isinstance(label, TopicLabel):
        raise TypeError("TopicLabelAdapter.label_topic() must return TopicLabel")
    if not isinstance(label.title, str) or not label.title.strip():
        raise ValueError("topic label title must be a non-empty string")
    if not isinstance(label.summary, str) or not label.summary.strip():
        raise ValueError("topic label summary must be a non-empty string")
    if not isinstance(label.method, str) or not label.method.strip():
        raise ValueError("topic label method must be a non-empty string")
    if label.model_name is not None and (
        not isinstance(label.model_name, str) or not label.model_name.strip()
    ):
        raise ValueError("topic label model_name must be non-empty when set")

    if len(label.title) > config.max_title_chars:
        raise ValueError("topic label title exceeds max_title_chars")


__all__ = [
    "StructuredLLMTopicLabeler",
    "label_topics",
]
