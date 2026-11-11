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
from ..shared.prompts import VIETNAMESE_VALUE
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
        title_schema: dict = {"type": "string", "description": VIETNAMESE_VALUE}
        result = self.llm.generate_json(
            system_prompt=(
                """
You are a meeting secretary who edits ASR transcripts into specific, accurate, easy-to-read titles
and summaries.

TASK
Read the transcript of one topic segment and return:
- title: the concrete issue or task being discussed.
- summary: the substance of the exchange, including the important information stated clearly in
  the segment.

Do not merely describe that people are meeting, discussing or coordinating.
The reader must learn what this segment is about, how it is handled, and what results,
requirements or blockers there are, if that information appears.

1. FIND THE FOCUS
- Read the whole segment and identify the domain from the flow of content.
- Identify the concrete object being discussed and the action or issue tied to that object.
- Prioritize content that is explained, demoed, evaluated or settled as a task;
  do not let a noisy word or a transition sentence drive the topic.
- If the segment holds several points, pick the central point for the title and keep the other
  important points in the summary. Do not invent relations between independent points.

2. TITLE: AS SPECIFIC AS THE CONTENT ALLOWS
- Title at the level of a specific task, feature, procedure or issue;
  do not stop at the level of "dự án", "sản phẩm", "công nghệ" or "công việc".
- Prefer a natural structure:
  [Main action/issue] + [specific object] + [scope if needed].
- Use verbs that match the content, such as: demo, rà soát, điều chỉnh,
  xây dựng, tích hợp, xử lý, đánh giá, phân công.
  Do not assume every segment is "Thảo luận về...".
- If the transcript identifies the item, function or procedure, name exactly that item, function
  or procedure in the title instead of replacing it with a generic noun.
- Do not list every point in the title. Do not add goals or results that were not stated to make
  the title look specific.
- Capitalize by ordinary Vietnamese rules.

3. SUMMARY: SUMMARIZE THE CONTENT, NOT THE ACT OF DISCUSSING
- Write one paragraph of 2-4 sentences, shorter if there is little information.
- The first sentence states the issue, progress or main content directly.
  Do not start with "Cuộc họp tập trung vào", "Nội dung xoay quanh"
  or "Trong cuộc họp, các thành viên đã thảo luận".
- The following sentences state options, important technical/business details,
  results, blockers or next actions if any.
- Each sentence must add information verifiable from the transcript.
  Drop sentences that only express a general goal without new content.

Keep the details that distinguish the topic when the transcript is clear enough:
- Which feature was demoed or needs finishing.
- Which items are done, in progress or still blocked.
- What input a procedure takes, what output it produces, through which main steps.
- Which option was proposed, changed or removed from scope.
- Which requirements or constraints affect the implementation.
- Who does what, by which deadline, if identifiable.

Do not replace concrete information with sentences such as:
- "Sử dụng công nghệ mới" when the kind of technology and its purpose are known.
- "Cải thiện quy trình" when the step to change is known.
- "Có một số khó khăn kỹ thuật" when the blocker is known.
- "Đã phân công nhiệm vụ" when the person and the task are known.
- "Đảm bảo hiệu quả và đáp ứng yêu cầu" in place of the actual option.

You do not have to fill in every kind of information listed above.
If one detail is noisy, generalize only that detail; do not make the whole summary vague or drop
other details that are clear.

4. RECOVER MEANING FROM ASR
- The transcript may get Vietnamese words, English terms and proper names wrong.
  Do not assume that a meaningful or capitalized word was recognized correctly.
- Normalize ASR errors when both the sound and the flow of content support that reading.
- For a noisy term whose function or meaning is clear, prefer a clear Vietnamese
  wording over copying the phonetic transcription.
- For a proper name or term that cannot be identified, describe it by its clear role or function;
  do not make up a name or pick a familiar brand.
- Do not infer the domain from one ambiguous word and then use that domain to justify how other
  words are interpreted.
- Domain knowledge only serves to understand and normalize the content,
  not as a source of extra facts, purposes or solutions.

5. DO NOT CHANGE THE INFORMATION
- Do not invent figures, actors, events, causal relations or tasks.
- Do not shift the meaning to a similar but essentially different concept.
- Distinguish current state, proposals, illustrative examples, requirements, decisions
  and completed results; use verbs matching the state.
- Keep conditions and the direction of comparisons.
- Only state the person in charge, figures, proper names and deadlines when clear enough.
  The speaker labels in the transcript are not always accurate.
- Do not convert relative time into a specific date without grounds.
- Do not turn jokes, dialogue from demo content or quotations into meeting decisions.

6. CHECK BEFORE ANSWERING
- If the title could be used for many different meeting segments without changes,
  replace the generic noun with the object or task that is clear in the transcript.
- If the summary only says "có thảo luận", "cần cải thiện", "đã phân công",
  state the corresponding content when there are grounds.
- Remove details guessed from noisy words or outside knowledge.
- Check that no negation, condition, scope or state was lost.
- Do not pad the number of sentences with generic information.

OUTPUT
Return only JSON matching the schema with the two fields "title" and "summary", both written in
VIETNAMESE, the language of the transcript.
Do not add explanations or your analysis process.
"""
            ),
            user_prompt=f"""
            Content: {text}
            """,
            schema={
                "type": "object",
                "required": ["title", "summary"],
                "properties": {
                    "title": title_schema,
                    "summary": {"type": "string", "description": VIETNAMESE_VALUE},
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
