"""Stage 7: đặt cho mỗi topic segment đã khoá (từ Stage 6) một tiêu đề ngắn.

Ranh giới segment đã cố định trước khi hàm này chạy, nên tiêu đề chỉ được
phép mô tả đúng những gì segment thực sự chứa -- tuyệt đối không được thêm
actor, số liệu hay kết luận mà đoạn văn không có. Ba tầng xử lý, thử lần
lượt cho từng segment:

1. **LLM** (``StructuredLLMTopicLabeler`` qua protocol ``TopicLabelAdapter``)
   đề xuất một tiêu đề ngắn + một đoạn tóm tắt.
2. **Grounding guard** (``_find_label_grounding_issues``): chỉ là kiểm tra chuỗi
   thuần tuý, không gọi model thêm lần nào, để loại bỏ tiêu đề nêu tên riêng
   không có trong segment, hoặc trùng một cụm từ chung chung bị cấm (vd.
   "thảo luận chung"). Tiêu đề bị từ chối sẽ được thử lại một lần, kèm
   hướng dẫn cho model biết chính xác lỗi lần trước
   (``_build_retry_instruction_from_issue``).
3. **Fallback tất định**, dùng khi lần thử lại cũng không qua guard hoặc
   adapter gọi lỗi (raise): ``_make_extractive_fallback_label`` trích tiêu đề và
   tóm tắt trực tiếp từ đầu văn bản của segment. Chỉ dùng lại text đã có sẵn
   trong segment nên không thể lặp lại lỗi "bịa nội dung". (Hiện ``label_topics``
   bắt buộc phải có adapter, không có adapter sẽ báo ``ValueError``.)

``label_topics`` bên dưới điều khiển vòng lặp này cho từng segment;
``StructuredLLMTopicLabeler`` chỉ đảm nhiệm bước 1.
"""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
import dataclasses
import logging
import math
import os
import re
import unicodedata

from ..utils.config import TopicLabelerConfig
from ..utils.contracts import (
    AnalysisAtom,
    AtomFeatures,
    EvidenceItem,
    TopicLabel,
    TopicSegment,
)
from ..utils.llm_call_log import llm_call
from ..utils.ports import LLMAdapter, TopicLabelAdapter
from ._shared import SPACE_RE, VN_STOPWORDS, WORD_RE, join_atoms, word_tokens

logger = logging.getLogger(__name__)

# Khớp các từ và các đoạn ký tự không phải từ nằm giữa chúng, để phân biệt được
# "một tên có dấu phân cách" với "hai tên đứng cạnh nhau".
_WORD_OR_SEP_RE = re.compile(r"\w+|\W+", re.UNICODE)

# Số đoạn gán nhãn song song mặc định (ghi đè bằng TOPIC_LABELER_MAX_WORKERS).
_DEFAULT_LABEL_MAX_WORKERS = 8


def _build_retry_instruction_from_issue(reason: str) -> str:
    """Chuyển một mã lý do (reason code) của grounding guard thành câu hướng dẫn sửa lỗi cho model.

    Không có bước này, lần thử lại sẽ lặp lại y hệt request cũ; mà adapter chạy
    ở temperature 0 trả lời y hệt cho request y hệt, nên lần thử lại sẽ lại trượt
    guard vì đúng lý do cũ.

    Đầu vào: reason - mã lý do từ ``_find_label_grounding_issues`` (hoặc mã
        ``adapter_error:...`` khi adapter báo lỗi).

    Đầu ra: str - câu tiếng Việt nêu rõ lỗi lần trước và cách sửa.

    Lưu ý: nhánh ``title_entity_not_in_segment:`` chưa có nơi nào sinh ra mã này
    (guard hiện chỉ kiểm tra cụm chung chung), nên nhánh đó đang chưa được dùng.
    """

    if reason.startswith("title_entity_not_in_segment:"):
        entities = reason[len("title_entity_not_in_segment:") :]
        return (
            f"Lần trước bạn đặt tên riêng {entities} không có trong nguyên "
            "văn. Chỉ dùng tên riêng xuất hiện đúng nguyên văn trong đoạn. "
            "Không hoàn thiện, không sửa chính tả tên riêng."
        )
    if reason == "title_is_generic_blacklisted":
        return (
            "Lần trước tiêu đề bị coi là chung chung. Nêu rõ nội dung cụ "
            "thể của đoạn, tránh cụm từ chung chung như 'thảo luận chung', "
            "'trao đổi công việc'."
        )
    return (
        f"Lần trước nhãn bị từ chối vì lý do: {reason}. Hãy đặt nhãn khác, "
        "bám sát nguyên văn hơn."
    )


class StructuredLLMTopicLabeler:
    """Labeler dùng LLM: biến một ``TopicSegment`` thành một ``TopicLabel``.

    Bọc quanh một ``LLMAdapter`` bất kỳ -- client nào hiện thực protocol
    ``generate_json(system_prompt, user_prompt, schema)`` nhỏ gọn này đều
    dùng được -- và hỏi nó, bằng tiếng Việt, một tiêu đề ngắn trung tính
    cùng một đoạn tóm tắt cho các atom của segment. Prompt yêu cầu model bám
    sát nguyên văn (không bịa sự kiện/actor/số liệu) và giữ nguyên tên riêng
    đúng như trong transcript, kể cả khi cách viết đó có vẻ thiếu hoặc sai.

    Class này chỉ gọi model rồi đóng gói JSON trả về thành ``TopicLabel``.
    Nó KHÔNG tự kiểm tra kết quả có bám sát nguyên văn hay không -- việc
    kiểm tra đó, cùng vòng lặp retry/fallback quanh nó, nằm ở
    ``_find_label_grounding_issues`` và ``label_topics`` bên dưới.
    """

    def __init__(
        self,
        llm: LLMAdapter,
        *,
        model_name: str = "configured-llm",
        max_title_chars: int | None = None,
    ) -> None:
        """Khởi tạo labeler.

        Đầu vào:
            llm: adapter LLM có ``generate_json``.
            model_name: tên model ghi vào ``TopicLabel.model_name`` để truy vết.
            max_title_chars: độ dài tối đa của tiêu đề; None là không giới hạn.
                Tiêu đề dài hơn bị cắt ở ranh giới từ thay vì làm hỏng cả segment.
        """

        self.llm = llm
        self.model_name = model_name
        self.max_title_chars = max_title_chars

    def label_topic(
        self,
        segment: TopicSegment,
        prev_segment: TopicSegment | None, 
        prev_topic: TopicLabel | None,
        atoms: tuple[AnalysisAtom, ...],
        evidence: tuple[EvidenceItem, ...],
        *,
        prior_issues: tuple[str, ...] = (),
    ) -> TopicLabel:
        """Hỏi LLM một tiêu đề và một đoạn tóm tắt cho một đoạn chủ đề.

        Đầu vào:
            segment: đoạn chủ đề cần gán nhãn (bắt buộc có ``segment_id``).
            prev_segment: đoạn chủ đề liền trước, hoặc None nếu là đoạn đầu.
            prev_topic: nhãn của đoạn liền trước, hoặc None. Cả hai đoạn trước
                chỉ làm ngữ cảnh cho model, không dùng để khẳng định nội dung.
            atoms, evidence: không dùng (giữ để khớp giao thức ``TopicLabelAdapter``).
            prior_issues: các lý do lần thử trước bị từ chối. Hiện chưa được đưa
                vào prompt (xem ``_build_retry_instruction_from_issue``), nên lần
                thử lại vẫn gửi đúng request cũ.

        Đầu ra: ``TopicLabel`` với ``method="llm_structured"``.

        Lỗi: ValueError nếu thiếu ``segment_id``, tiêu đề/tóm tắt rỗng hoặc
            ``confidence`` ngoài khoảng [0, 1].
        """

        del evidence
        if segment.segment_id is None:
            raise ValueError("segment must have a segment_id")
        text = segment.text
        prev_segment_text = prev_segment.text if prev_segment is not None else ""
        prev_title = prev_topic.title if prev_topic else ""
        prev_summary = prev_topic.summary if prev_topic else ""
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
            Topic đoạn trước: {prev_title}
            Tóm tắt đoạn trước: {prev_summary}
            Nội dung đoạn trước: {prev_segment_text}
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
        confidence = result.get("confidence")
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
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise ValueError("topic label confidence must be between 0 and 1")
        return TopicLabel(
            segment_id=segment.segment_id,
            title=title.strip(),
            summary=summary.strip(),
            text=text.strip(),
            evidence_ids=None,
            method="llm_structured",
            model_name=self.model_name,
            confidence=float(confidence) if confidence is not None else None,
        )


# Khớp giá trị mặc định của FeatureBuilderConfig.top_k_keyphrases: keyphrase thứ N
# (đếm từ 0) của một atom được (_RANK_WEIGHT_BASE - N) điểm hạng, nên keyphrase
# vượt top-5 mặc định không được điểm nào. Đây chỉ là thay thế cho điểm BM25 mà
# Stage 5 không xuất theo từng cụm (AtomFeatures.keyphrases là tuple chuỗi đã xếp
# hạng, không kèm số), KHÔNG phải điểm BM25 thật. Xem plan_stage_7_8.md §2.5,
# TASK-GRAPH-stage7-8.md D-103.
_RANK_WEIGHT_BASE = 5


def _find_label_grounding_issues(
    label: TopicLabel, segment_text: str, config: TopicLabelerConfig
) -> tuple[str, ...]:
    """Kiểm tra tiêu đề do LLM sinh có phải nhãn chung chung bị cấm hay không.

    Chỉ so chuỗi thuần túy, không gọi model. Có hai cách khớp:
    - khớp chính xác (sau chuẩn hóa NFC/hạ chữ thường) với một mục trong
      ``config.title_blacklist``;
    - nếu ``config.blacklist_subset_check`` bật: các từ nội dung của tiêu đề (đã
      bỏ stopword) là tập con các từ nội dung của một mục trong danh sách cấm.

    Đây là kiểm tra chất lượng nội dung, khác với kiểm tra cấu trúc (sai kiểu,
    thiếu trường) do ``_validate_label_structure`` xử lý trước và luôn gây lỗi ngay.

    Lưu ý: kiểm tra "tên riêng trong tiêu đề không có trong segment" từng được thiết
    kế nhưng CHƯA có trong hàm này; ``segment_text`` được chuẩn hóa nhưng hiện
    chưa dùng để so khớp.

    Đầu vào:
        label: nhãn do LLM sinh.
        segment_text: văn bản của đoạn chủ đề.
        config: cấu hình labeler (danh sách cấm, cờ kiểm tra tập con).

    Đầu ra: tuple mã lý do (hiện chỉ có ``"title_is_generic_blacklisted"``);
        tuple rỗng nghĩa là tiêu đề đạt.
    """

    issues: list[str] = []
    normalized_segment = (
        " "
        + " ".join(WORD_RE.findall(unicodedata.normalize("NFC", segment_text))).casefold()
        + " "
    )
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
    """Tách văn bản thành các từ và bỏ stopword tiếng Việt (``VN_STOPWORDS``).

    Đầu vào: text - chuỗi bất kỳ.
    Đầu ra: tuple các từ nội dung còn lại, giữ thứ tự.
    """

    return tuple(word for word in word_tokens(text) if word not in VN_STOPWORDS)


def label_topics(
    segments: tuple[TopicSegment, ...],
    atoms: tuple[AnalysisAtom, ...] | None = None ,
    evidence: tuple[EvidenceItem, ...] | None = None,
    config: TopicLabelerConfig | None = None,
    *,
    adapter: TopicLabelAdapter | None = None,
    # atom_features: tuple[AtomFeatures, ...] = () ,
) -> tuple[TopicLabel, ...]:
    """Gán nhãn (tiêu đề + tóm tắt) cho từng đoạn chủ đề, mỗi đoạn một ``TopicLabel``, đúng thứ tự.

    Với mỗi đoạn: gọi adapter, kiểm tra cấu trúc (``_validate_label_structure``) rồi
    kiểm tra guard (``_find_label_grounding_issues``). Nếu không đạt thì thử lại tối
    đa ``config.max_retry_attempts`` lần; vẫn không đạt thì dùng nhãn dự phòng
    trích từ văn bản (``_make_extractive_fallback_label``, có ghi log cảnh báo).
    Mỗi đoạn được cung cấp thêm đoạn và nhãn liền trước làm ngữ cảnh.

    Đầu vào:
        segments: các đoạn chủ đề theo thứ tự.
        atoms, evidence: không dùng (giữ để tương thích chữ ký cũ).
        config: cấu hình labeler; None thì dùng ``TopicLabelerConfig()`` mặc định.
        adapter: bộ gán nhãn (bắt buộc).

    Đầu ra: tuple ``TopicLabel``, cùng số lượng và thứ tự với ``segments``.

    Lỗi: ValueError nếu không có ``adapter``.
    """

    if config is None:
        config = TopicLabelerConfig()
    if adapter is None:
        raise ValueError("topic_labeler requires a TopicLabelAdapter")
    if not segments:
        return ()

    # Các đoạn được gán nhãn độc lập (không truyền đoạn/nhãn liền trước làm ngữ
    # cảnh -- bản tuần tự cũ cũng luôn truyền None vì không bao giờ cập nhật hai
    # biến đó), nên chạy song song cho kết quả y hệt mà thời gian ~ đoạn chậm nhất
    # thay vì tổng mọi đoạn. ``pool.map`` giữ đúng thứ tự ``segments``.
    max_workers = min(len(segments), _label_max_workers())
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        labels = pool.map(
            lambda segment: _label_one_segment(segment, atoms, evidence, config, adapter),
            segments,
        )
        return tuple(labels)


def _label_max_workers() -> int:
    """Số lời gọi gán nhãn chạy song song, đọc từ ``TOPIC_LABELER_MAX_WORKERS``.

    Mặc định 8, dưới ``max_connections=10`` của client OpenAI
    (``utils/openai_adapters._client``). Giá trị không hợp lệ thì dùng mặc định.

    Đầu ra: int >= 1.
    """

    try:
        return max(1, int(os.environ.get("TOPIC_LABELER_MAX_WORKERS", _DEFAULT_LABEL_MAX_WORKERS)))
    except ValueError:
        return _DEFAULT_LABEL_MAX_WORKERS


def _label_one_segment(
    segment: TopicSegment,
    atoms: tuple[AnalysisAtom, ...] | None,
    evidence: tuple[EvidenceItem, ...] | None,
    config: TopicLabelerConfig,
    adapter: TopicLabelAdapter,
) -> TopicLabel:
    """Gán nhãn MỘT đoạn: gọi adapter, kiểm tra cấu trúc + guard, thử lại, rồi fallback.

    Đầu vào: segment - đoạn cần gán nhãn; atoms, evidence - chuyển thẳng cho
        adapter (không dùng); config - cấu hình labeler; adapter - bộ gán nhãn.
    Đầu ra: TopicLabel (nhãn LLM qua guard, hoặc nhãn trích dẫn dự phòng).
    """

    segment_text = segment.text or ""
    issues: tuple[str, ...] = ()
    prior_issues: tuple[str, ...] = ()
    attempt = 0
    while True:
        try:
            with llm_call(
                "topic_labeler",
                segment_id=segment.segment_id,
                prompt_chars=len(segment_text),
            ):
                label = adapter.label_topic(
                    segment, None, None, atoms, evidence, prior_issues=prior_issues
                )
            _validate_label_structure(label, config)
        except Exception as exc:
            issues = (f"adapter_error:{exc}",)
        else:
            label = dataclasses.replace(label, evidence_ids=None)
            issues = _find_label_grounding_issues(label, segment_text, config)
        if not issues or attempt >= config.max_retry_attempts:
            break
        attempt += 1
        prior_issues = issues
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
    """Nhãn dự phòng tất định (tầng 3, xem docstring module), chỉ dựng từ văn bản có sẵn của đoạn.

    Vì chỉ dùng lại text trong đoạn nên không thể lặp lại lỗi "bịa nội dung" khiến
    nhãn LLM bị từ chối. Dùng khi LLM vẫn trượt ``_find_label_grounding_issues``
    (hoặc vẫn lỗi) sau mọi lần thử lại. Tiêu đề là phần đầu văn bản cắt ở ranh
    giới từ (tối đa ``max_title_chars``), tóm tắt là 240 ký tự đầu.

    Đầu vào: segment - đoạn chủ đề; config - cấu hình labeler.
    Đầu ra: ``TopicLabel`` với ``method="keyword_fallback_after_guard_failure"``.
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
        evidence_ids=None,
        method="keyword_fallback_after_guard_failure",
    )


def _validate_label_structure(
    label: TopicLabel,
    config: TopicLabelerConfig,
) -> None:
    """Kiểm tra ``TopicLabel`` do adapter trả về có đúng cấu trúc không; sai thì raise.

    Chỉ kiểm tra định dạng/kiểu dữ liệu: đúng kiểu ``TopicLabel``, title/summary/
    method không rỗng, ``model_name`` (nếu có) không rỗng, ``confidence`` hữu hạn
    và nằm trong [0, 1], tiêu đề không vượt ``config.max_title_chars``. Khác với
    kiểm tra nội dung ở ``_find_label_grounding_issues``. Lỗi được ``label_topics``
    bắt lại và coi như một lần thử thất bại bình thường (thử lại rồi fallback),
    không văng ra người gọi.

    Đầu vào: label - nhãn do adapter trả về; config - cấu hình labeler.
    Đầu ra: None nếu hợp lệ.
    Lỗi: TypeError nếu không phải ``TopicLabel``; ValueError nếu vi phạm điều kiện trên.
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
    if label.confidence is not None and (
        isinstance(label.confidence, bool)
        or not isinstance(label.confidence, (int, float))
        or not math.isfinite(float(label.confidence))
        or not 0.0 <= float(label.confidence) <= 1.0
    ):
        raise ValueError("topic label confidence must be between 0 and 1")

    if len(label.title) > config.max_title_chars:
        raise ValueError("topic label title exceeds max_title_chars")


_FALLBACK_METHODS = frozenset(
    {"keyword_fallback_after_guard_failure", "extractive_offline_fallback"}
)
"""Các giá trị ``TopicLabel.method`` nghĩa là title/summary đến từ một
fallback tất định, không phải từ LLM sinh có bám sát nguyên văn -- judge của
Stage 8 (TIP-010, plan_stage_7_8.md §3.6) kiểm tra membership ở đây thay vì
gõ lại hai chuỗi này, nên hai module không thể lệch nhau."""


__all__ = [
    "StructuredLLMTopicLabeler",
    "label_topics",
]
