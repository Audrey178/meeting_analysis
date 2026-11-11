"""Dựng ``MeetingAnalyzer`` từ biến môi trường: LLM (OpenAI-compatible), Verifier riêng nếu có,
bộ phân loại Decisions và cấu hình ``V3_*``. Gọi một lần mỗi tiến trình (``dependencies.get_analyzer_v3``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Thiết lập sys.path viết trực tiếp tại đây; lý do không đưa vào module dùng chung xem
# khối tương tự trong main.py.
_BE_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BE_DIR.parent
for _dir in (_BE_DIR, _REPO_ROOT):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from src.pipeline.config import AnalysisConfig
from src.pipeline.run import MeetingAnalyzer
from src.utils.config import load_default_config


def build_v3_config_from_env() -> AnalysisConfig:
    """Cấu hình v3 từ biến môi trường ``V3_*`` (giá trị thiếu dùng mặc định của ``AnalysisConfig``).

    Đầu ra: AnalysisConfig.
    """

    defaults = AnalysisConfig()
    return AnalysisConfig(
        extract_attempts=int(os.environ.get("V3_EXTRACT_ATTEMPTS", defaults.extract_attempts)),
        verifier_max_tool_calls=int(os.environ.get("V3_VERIFIER_MAX_TOOL_CALLS", defaults.verifier_max_tool_calls)),
        consensus_max_rounds=int(os.environ.get("V3_CONSENSUS_MAX_ROUNDS", defaults.consensus_max_rounds)),
        max_concurrency=int(os.environ.get("V3_MAX_CONCURRENCY", defaults.max_concurrency)),
    )


def _build_verifier_llm(default_llm):
    """LLM cho Verifier: backend riêng nếu có ``VERIFIER_MODEL_NAME``, không thì ``default_llm``.

    Biến môi trường (chỉ đọc khi có ``VERIFIER_MODEL_NAME``):
        VERIFIER_BASE_URL, VERIFIER_API_KEY: endpoint OpenAI-compatible (vd DeepSeek).
        VERIFIER_RESPONSE_MODE: ``json_object`` (mặc định, DeepSeek không hỗ trợ
            ``json_schema`` strict) hoặc ``json_schema``.
        VERIFIER_LLM_CONCURRENCY: số lời gọi Verifier đồng thời (gate riêng, mặc định 8).
        VERIFIER_MAX_OUTPUT_TOKENS: trần token đầu ra mỗi lời gọi (mặc định 1024; một bước ReAct chỉ vài
            trăm token). Khi model lặp từ khoá trong ``argument`` (gpt-4o, progress verifier), lời gọi
            hỏng ở trần này thay vì chạy tới ``OPENAI_MAX_OUTPUT_TOKENS``.
        VERIFIER_THINKING: ``enabled``/``disabled`` gửi kèm ``{"thinking": {"type": ...}}``
            (DeepSeek V4); để trống thì không gửi. ``deepseek-flash`` bật thinking thì
            hay trả ``content`` toàn khoảng trắng ở chế độ ``json_object``.

    Đầu vào: default_llm - LLM dùng chung của các vai trò khác.
    Đầu ra: (adapter, số lời gọi đồng thời hoặc None nếu dùng chung gate).
    Lỗi: ValueError nếu có ``VERIFIER_MODEL_NAME`` mà thiếu ``VERIFIER_BASE_URL``/``VERIFIER_API_KEY``.
    """

    from src.utils.openai_adapters import OpenAIChatJSONAdapter

    model = os.environ.get("VERIFIER_MODEL_NAME", "").strip()
    if not model:
        return default_llm, None
    base_url = os.environ.get("VERIFIER_BASE_URL", "").strip()
    api_key = os.environ.get("VERIFIER_API_KEY", "").strip()
    if not base_url or not api_key:
        raise ValueError("VERIFIER_MODEL_NAME cần đi kèm VERIFIER_BASE_URL và VERIFIER_API_KEY")
    thinking = os.environ.get("VERIFIER_THINKING", "").strip().lower()
    if thinking not in ("", "enabled", "disabled"):
        raise ValueError(f"VERIFIER_THINKING không hợp lệ: {thinking!r} (enabled | disabled)")
    llm = OpenAIChatJSONAdapter(
        model=model,
        base_url=base_url,
        api_key=api_key,
        response_mode=os.environ.get("VERIFIER_RESPONSE_MODE", "json_object"),
        extra_body={"thinking": {"type": thinking}} if thinking else None,
    )
    llm.max_output_tokens = int(os.environ.get("VERIFIER_MAX_OUTPUT_TOKENS", "1024"))
    return llm, int(os.environ.get("VERIFIER_LLM_CONCURRENCY", "8"))


def _build_decisions_client():
    """Client Decisions API (TypeSafe JEV qua OpenRouter, hoặc OpenAI), hoặc None nếu chưa bật.

    Dùng chung cho bộ phân loại lượt chốt (``_build_turn_judge``) và lượt nêu trạng thái
    tiến độ (``_build_progress_judge``).

    Biến môi trường:
        TURN_ACT_MODEL: model Decisions (vd ``typesafe/jev-1.13`` trên OpenRouter, ``gpt-6-luna`` trên OpenAI); để
            trống thì không bật, evidence-check không xét được lượt chốt và gửi candidate cho Verifier.
        DECISIONS_PROVIDER: ``openrouter`` (mặc định) hoặc ``openai`` (Decisions API của OpenAI, gọi thẳng
            endpoint qua ``src/utils/openai_decisions.py`` vì SDK ``openai`` 2.x không có ``decisions``).
        DECISIONS_OPENAI_API_KEY, DECISIONS_OPENAI_BASE_URL: key và base URL khi ``DECISIONS_PROVIDER=openai``
            (base URL mặc định ``https://api.openai.com/v1``; KHÔNG dùng ``OPENAI_BASE_URL``, đó là gateway LLM).
        OPENROUTER_API_KEY: API key của OpenRouter.
        OPENROUTER_DECISIONS_URL: mặc định ``https://openrouter.ai/api/alpha/decisions``.
        TURN_ACT_TIMEOUT_SECONDS: timeout mỗi lời gọi (mặc định 10; quá hạn thì candidate đi Verifier).

    Đầu ra: (client, model) hoặc None.
    Lỗi: ValueError nếu có ``TURN_ACT_MODEL`` mà không tìm được API key.
    """

    from src.utils.openrouter_decisions import OpenRouterDecisionsClient

    model = os.environ.get("TURN_ACT_MODEL", "").strip()
    if not model:
        return None
    timeout = float(os.environ.get("TURN_ACT_TIMEOUT_SECONDS", "10"))
    if os.environ.get("DECISIONS_PROVIDER", "openrouter").strip().lower() == "openai":
        # SDK ``openai`` 2.x không có ``client.decisions``: gọi thẳng endpoint (``openai_decisions.py``).
        from src.utils.openai_decisions import DEFAULT_BASE_URL, OpenAIDecisionsClient

        api_key = os.environ.get("DECISIONS_OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("DECISIONS_PROVIDER=openai cần DECISIONS_OPENAI_API_KEY")
        base_url = os.environ.get("DECISIONS_OPENAI_BASE_URL", "").strip() or DEFAULT_BASE_URL
        return OpenAIDecisionsClient(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=2), model
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise ValueError("TURN_ACT_MODEL cần OPENROUTER_API_KEY")
    client = OpenRouterDecisionsClient(
        api_key=api_key,
        url=os.environ.get("OPENROUTER_DECISIONS_URL", "").strip()
        or "https://openrouter.ai/api/alpha/decisions",
        timeout=timeout,
        max_retries=2,
    )
    return client, model


def _build_turn_judge(decisions=None):
    """Bộ phân loại lượt chốt và kiểm độ khớp nội dung (Decisions), hoặc None.

    Đầu vào: decisions - kết quả ``_build_decisions_client`` (None thì không bật; evidence-check
        gửi candidate có lượt chốt cho Verifier).
    Đầu ra: ``DecisionsApiTurnActJudge`` hoặc None.
    """

    from src.pipeline.shared.judges.turn_act import DecisionsApiTurnActJudge

    if decisions is None:
        return None
    client, model = decisions
    return DecisionsApiTurnActJudge(client, model=model)


def _build_progress_judge(decisions=None):
    """Bộ phân loại lượt nêu trạng thái tiến độ (Decisions), hoặc None nếu chưa bật.

    Chưa bật thì trạng thái Action agent khai cho tiến độ được giữ và đánh dấu ``unchecked``.

    Đầu vào: decisions - kết quả ``_build_decisions_client``.
    Đầu ra: ``DecisionsApiProgressActJudge`` hoặc None.
    """

    from src.pipeline.shared.judges.progress_act import DecisionsApiProgressActJudge

    if decisions is None:
        return None
    client, model = decisions
    return DecisionsApiProgressActJudge(client, model=model)


def build_analyzer_v3() -> MeetingAnalyzer:
    """Dựng analyzer v3 dùng adapter OpenAI thật (gọi lười, lần đầu có request v3).

    Một instance LLM dùng chung cho gán nhãn + ba agent trích xuất; Verifier có thể trỏ sang backend riêng
    (``_build_verifier_llm``). Số lời gọi đồng thời đọc từ ``V3_LLM_CONCURRENCY`` (mặc định 8).
    Lượt chốt và lượt nêu trạng thái tiến độ được xét theo nghĩa khi có ``TURN_ACT_MODEL``
    (``_build_turn_judge``, ``_build_progress_judge``, chung một client).

    Đầu ra: MeetingAnalyzer.
    """

    from src.pipeline.step3_label import StructuredLLMTopicLabeler
    from src.utils.openai_adapters import OpenAIChatJSONAdapter

    llm = OpenAIChatJSONAdapter()
    verifier_llm, verifier_concurrency = _build_verifier_llm(llm)
    labeler = StructuredLLMTopicLabeler(llm, model_name=getattr(llm, "model_name", "openai"))
    decisions = _build_decisions_client()
    return MeetingAnalyzer(
        content_llm=llm,
        action_llm=llm,
        decision_llm=llm,
        verifier_llm=verifier_llm,
        labeler=labeler,
        labeler_config=load_default_config().topic_labeler,
        config=build_v3_config_from_env(),
        llm_concurrency=int(os.environ.get("V3_LLM_CONCURRENCY", "8")),
        verifier_llm_concurrency=verifier_concurrency,
        turn_judge=_build_turn_judge(decisions),
        progress_judge=_build_progress_judge(decisions),
    )


__all__ = [
    "build_analyzer_v3",
    "build_v3_config_from_env",
]
