"""Chạy các agent trích xuất cho một chủ đề (bước 4).

Mỗi agent gọi mô hình một lần cho mỗi chủ đề (gọi lại nếu phải thử lại). Trước khi gọi, đầu prompt
được thêm một dòng cho biết người chủ trì cuộc họp, hoặc báo rằng phiên họp không cung cấp thông tin
này; nếu cuộc họp có danh sách việc cần báo cáo, agent giao việc được thêm hướng dẫn để ghi cả tiến
độ trong cùng lời gọi.

Nếu lời gọi lỗi tạm thời thì thử lại ngay trong chủ đề đó. Lỗi không thể tự hết (sai khoá truy cập,
hết tiền) thì dừng cả lượt chạy. Nếu mô hình trả về kết quả không đọc được thì chỉ chủ đề đó bị
đánh dấu lỗi, các chủ đề khác vẫn chạy bình thường.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Mapping, Sequence

from ...utils.ports import LLMAdapter, LLMUpstreamError
from ..shared.prompts import (
    ACTION_AGENDA_RULE,
    ACTION_SYSTEM_PROMPT,
    CONTENT_SYSTEM_PROMPT,
    DECISION_SYSTEM_PROMPT,
    PROGRESS_TRACKING_SLOT,
    format_chair_element,
)
from ..shared.schemas import AnalysisPart, ExtractorInput, SpeakerRegistry, TopicFailure
from .action import ACTION_SCHEMA, run_action_agent
from .content import CONTENT_SCHEMA, run_content_agent
from .decision import DECISION_SCHEMA, run_decision_agent
from .progress_extract import build_update_schema

logger = logging.getLogger(__name__)


class _PromptPrefixedLLM:
    """Bọc một adapter LLM: chèn phần đầu user prompt và (tuỳ chọn) sửa schema trước mỗi lời gọi.

    Nhờ lớp này, các agent không cần biết về dòng người chủ trì hay trường tiến độ; chúng vẫn gọi
    ``generate_json`` như bình thường.

    Args:
        llm: Adapter LLM thật.
        user_prefix: Đoạn văn bản đặt trước user prompt, cách một dòng trống.
        schema_hook: Hàm biến đổi schema của agent trước khi gửi đi. None thì giữ nguyên schema.
    """

    def __init__(
        self,
        llm: LLMAdapter,
        user_prefix: str,
        schema_hook: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None,
    ) -> None:
        self._llm = llm
        self._user_prefix = user_prefix # đặt thông tin chair lên đầu 
        self._schema_hook = schema_hook # hàm xử lý schema

    def generate_json(self, *, system_prompt: str, user_prompt: str, schema: Mapping[str, object]):
        """Gọi LLM thật với user prompt đã thêm phần đầu và schema đã qua ``schema_hook``."""
        return self._llm.generate_json(
            system_prompt=system_prompt,
            user_prompt=f"{self._user_prefix}\n\n{user_prompt}",
            schema=self._schema_hook(schema) if self._schema_hook else schema,
        )


def with_agenda_fields(schema: Mapping[str, object], task_ids: Sequence[str]) -> dict:
    """Thêm trường tiến độ ``updates`` vào đầu schema của agent giao việc.

    ``updates`` đứng trước ``member_requests`` và ``action_items`` để mô hình xếp lời nói về việc cũ
    vào tiến độ trước, tránh để lời đó lọt sang việc giao mới.

    Args:
        schema: Schema gốc của agent giao việc; không bị sửa.
        task_ids: Mã các việc trong danh sách việc cần báo cáo.

    Returns:
        Bản sao schema đã thêm ``updates`` vào cả ``properties`` lẫn ``required``.
    """

    schema = copy.deepcopy(dict(schema))
    schema["properties"] = {"updates": build_update_schema(task_ids), **schema["properties"]}
    schema["required"] = ["updates", *schema["required"]]
    return schema


def render_system_prompt(template: str, progress: str = "") -> str:
    """Điền thẻ giữ chỗ ``<progress_tracking/>`` của system prompt agent trích xuất.

    Args:
        template: System prompt XML của agent trích xuất.
        progress: Khối hướng dẫn tiến độ; rỗng khi cuộc họp không có danh sách việc.

    Returns:
        System prompt hoàn chỉnh.
    """

    return template.replace(PROGRESS_TRACKING_SLOT, progress)


def call_extractor(name: str, llm: LLMAdapter, topic: ExtractorInput, registry: SpeakerRegistry) -> dict:
    """Gọi một agent trích xuất đúng một lần cho một chủ đề.

    Mọi agent đều nhận dòng người chủ trì ở đầu user prompt. Riêng agent giao việc, nếu cuộc họp có
    danh sách việc cần báo cáo thì system prompt được thêm luật ghi tiến độ và schema được thêm trường
    ``updates``.

    Args:
        name: Tên agent: "content_agent", "action_agent" hoặc "decision_agent".
        llm: Adapter LLM.
        topic: Gói dữ liệu của chủ đề.
        registry: Danh bạ cả cuộc họp; dùng người chủ trì và danh sách việc.

    Returns:
        Dict kết quả của agent; có thêm ``topic_failures`` khi LLM lỗi tạm thời.

    Raises:
        ValueError: Khi ``name`` không phải tên agent hợp lệ.
        LLMUpstreamError: Khi LLM lỗi loại ``fatal``.
    """

    chair_line = format_chair_element(registry.chair)
    if name == "content_agent":
        prompt = render_system_prompt(CONTENT_SYSTEM_PROMPT)
        return run_content_agent(_PromptPrefixedLLM(llm, chair_line), prompt, topic)
    if name == "decision_agent":
        prompt = render_system_prompt(DECISION_SYSTEM_PROMPT)
        return run_decision_agent(_PromptPrefixedLLM(llm, chair_line), prompt, topic, registry.chair)
    if name != "action_agent":
        raise ValueError(f"agent trích xuất không tồn tại: {name!r}")
    prompt, schema_hook = render_system_prompt(ACTION_SYSTEM_PROMPT), None
    task_ids = registry.agenda.task_ids
    if task_ids:
        prompt = render_system_prompt(ACTION_SYSTEM_PROMPT, progress=ACTION_AGENDA_RULE)

        def schema_hook(schema: Mapping[str, object]) -> dict:
            return with_agenda_fields(schema, task_ids)

    prefixed = _PromptPrefixedLLM(llm, chair_line, schema_hook)
    return run_action_agent(prefixed, prompt, topic, registry.agenda, registry.chair)


def _call_isolated(name: str, llm: LLMAdapter, topic: ExtractorInput, registry: SpeakerRegistry) -> dict:
    """Gọi ``call_extractor`` một lần; lỗi khi đọc kết quả của mô hình thành lỗi riêng của chủ đề.

    Chỉ bắt các lỗi đọc dữ liệu (sai kiểu, thiếu khoá...) và ghi traceback vào log: một kết quả lạ
    không được làm hỏng cả cuộc họp, nhưng lỗi lập trình vẫn phải thấy được. Lỗi được ghi với loại
    "malformed_output" nên không được thử lại. ``LLMUpstreamError`` lọt tới đây chỉ còn loại ``fatal``
    và được ném tiếp.
    """

    try:
        return call_extractor(name, llm, topic, registry)
    except LLMUpstreamError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, IndexError) as exc:
        segment_id = topic["segment_id"]
        logger.exception("%s không đọc được kết quả LLM ở segment %s", name, segment_id)
        failure = TopicFailure(segment_id, name, f"{type(exc).__name__}: {exc}", "malformed_output")
        return {"topic_failures": (failure,)}


# Tên node agent trích xuất -> các (khoá kết quả của agent, khoá trong TopicState, phần kết quả).
EXTRACTOR_OUTPUTS: dict[str, tuple[tuple[str, str, AnalysisPart], ...]] = {
    "content_agent": (("discussion_points", "discussion_points", "content"),),
    "action_agent": (
        ("action_item_candidates_raw", "action_candidates_raw", "assignments"),
        ("progress_updates_raw", "progress_updates_raw", "progress"),
    ),
    "decision_agent": (("decision_candidates_raw", "decision_candidates_raw", "decisions"),),
}


def extract_topic(
    name: str,
    llm: LLMAdapter,
    topic: ExtractorInput,
    registry: SpeakerRegistry,
    parts: frozenset[AnalysisPart],
    attempts: int,
) -> dict:
    """Chạy một agent trích xuất cho một chủ đề, thử lại khi lỗi có thể tự hết.

    Ngừng thử lại khi lời gọi thành công hoặc có lỗi mà gọi lại cũng vô ích (ví dụ kết quả không đọc
    được). Chỉ ghi các phần kết quả nằm trong ``parts``: khi chỉ cần tiến độ thì các việc giao mà agent
    giao việc trích trong cùng lời gọi bị bỏ, không đi tiếp sang kiểm chứng, và ngược lại.

    Args:
        name: Tên agent, là một khoá của ``EXTRACTOR_OUTPUTS``.
        llm: Adapter LLM.
        topic: Gói dữ liệu của chủ đề.
        registry: Danh bạ cả cuộc họp.
        parts: Các phần kết quả cần ghi (nội dung, kết luận, việc giao, tiến độ).
        attempts: Số lần gọi tối đa, tính cả lần đầu.

    Returns:
        Dict cập nhật trạng thái chủ đề: một danh sách kết quả cho mỗi phần được yêu cầu, kèm
        ``topic_failures`` nếu lần gọi cuối vẫn lỗi.

    Raises:
        LLMUpstreamError: Khi LLM lỗi loại ``fatal``; mọi lời gọi sau cũng sẽ lỗi nên cả lượt chạy dừng.
    """

    result: dict = {}
    for _ in range(attempts):
        result = _call_isolated(name, llm, topic, registry)
        failures = result.get("topic_failures", ())
        if not failures or not all(failure.retryable for failure in failures):
            break
    update: dict = {
        target_key: list(result.get(source_key, []))
        for source_key, target_key, part in EXTRACTOR_OUTPUTS[name]
        if part in parts
    }
    failures = result.get("topic_failures", ())
    if failures:
        update["topic_failures"] = list(failures)
    return update


__all__ = [
    "EXTRACTOR_OUTPUTS",
    "call_extractor",
    "extract_topic",
    "render_system_prompt",
    "with_agenda_fields",
]
