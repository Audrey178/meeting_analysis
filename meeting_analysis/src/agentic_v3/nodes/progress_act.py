

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ..core.turn_act import DEFAULT_MODEL, render_turn_act_input, turn_windows
from ...utils.contracts import SpeakerTurn

# Ngưỡng tạm (chưa hiệu chỉnh, xem docstring module).
STATUS_CLEAR_MIN = 0.8
# Xác suất "việc chỉ là báo cáo tại cuộc họp" để hỏi bằng ``REPORT_ACT_QUESTION``; chưa chắc thì
# dùng câu hỏi chung. Cái Mép: báo cáo tình hình 3 dự án cảng 1.00, việc báo cáo tiến độ
# đường sắt (giả lập) 0.73, trình tờ trình 0.35, tiếp thu góp ý 0.03.
REPORT_TASK_MIN = 0.8

# Lựa chọn của câu hỏi -> trạng thái của ``ProgressUpdate`` ("khac" không ứng với trạng thái nào).
PROGRESS_ACT_TO_STATUS: dict[str, str] = {
    "bao_cao_xong": "done",
    "bao_cao_dang_lam": "in_progress",
    "bao_cao_vuong_mac": "blocked",
    "yeu_cau_lam_lai": "returned",
    "hoan_cho": "deferred",
    "chi_nhac_hoi": "mentioned",
}

PROGRESS_ACT_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "progress_act",
    "instructions": (
        "Input là trích đoạn cuộc họp tiếng Việt: VIỆC ĐANG XÉT, vài lượt ngữ cảnh rồi LƯỢT CẦN XÉT. "
        "Chỉ phân loại điều LƯỢT CẦN XÉT nói về tiến độ của VIỆC ĐANG XÉT, dùng ngữ cảnh để hiểu nó. "
        "Xét theo nghĩa, không theo từ khoá. Báo cáo của người thực hiện và chỉ đạo của người chủ trì "
        "đều tính; nhận xét, hỏi lại, bàn nội dung mà không nêu tình trạng thực hiện là chi_nhac_hoi."
    ),
    "choices": [
        {"value": "bao_cao_xong", "description": "Việc đã làm xong, đã hoàn thành, đã có kết quả/văn bản."},
        {"value": "bao_cao_dang_lam", "description": "Việc đang được thực hiện, đang làm thủ tục, mới xong một phần."},
        {"value": "bao_cao_vuong_mac", "description": "Việc bị vướng, chậm, thiếu điều kiện, cần tháo gỡ."},
        {"value": "yeu_cau_lam_lai", "description": "Yêu cầu làm lại, đánh giá lại, bổ sung, chỉnh sửa kết quả của việc."},
        {"value": "hoan_cho", "description": "Hoãn, tạm dừng, chờ điều kiện/sự kiện khác rồi mới làm tiếp."},
        {"value": "chi_nhac_hoi", "description": "Chỉ nhắc tới, hỏi, bàn nội dung; không nêu tình trạng thực hiện."},
        {"value": "khac", "description": "Không nói về việc này."},
    ],
}

# Câu hỏi cho việc chỉ là báo cáo tình hình tại cuộc họp (xem docstring module).
REPORT_ACT_TO_STATUS: dict[str, str] = {
    "da_bao_cao": "done",
    "chua_co_bao_cao": "in_progress",
    "xin_hoan_bao_cao": "deferred",
    "yeu_cau_bao_cao_lai": "returned",
    "chi_nhac_hoi": "mentioned",
}

REPORT_ACT_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "report_act",
    "instructions": (
        "Input là trích đoạn cuộc họp tiếng Việt: VIỆC ĐANG XÉT (một việc báo cáo tình hình cho cuộc họp), vài lượt "
        "ngữ cảnh rồi LƯỢT CẦN XÉT. Chỉ phân loại điều LƯỢT CẦN XÉT nói về việc báo cáo đó, dùng ngữ cảnh để hiểu nó. "
        "Xét theo nghĩa, không theo từ khoá. Tình hình của đối tượng được báo cáo (dự án đang làm, chưa xong, vướng...) "
        "là NỘI DUNG báo cáo, không phải tình trạng của việc báo cáo."
    ),
    "choices": [
        {"value": "da_bao_cao", "description": "Lượt nói trình bày nội dung mà việc yêu cầu báo cáo, kể cả khi trả lời câu hỏi về nội dung đó."},
        {"value": "chua_co_bao_cao", "description": "Nói báo cáo chưa xong, đang chuẩn bị, chưa đủ số liệu."},
        {"value": "xin_hoan_bao_cao", "description": "Xin lùi, hoãn báo cáo sang lúc khác."},
        {"value": "yeu_cau_bao_cao_lai", "description": "Yêu cầu báo cáo lại, bổ sung, làm rõ thêm nội dung đã báo cáo."},
        {"value": "chi_nhac_hoi", "description": "Chỉ nhắc tới hoặc hỏi về nội dung; chưa trình bày."},
        {"value": "khac", "description": "Không nói về việc này."},
    ],
}

# Xếp kiểu việc theo tên việc, một lần mỗi việc (``DecisionsProgressActJudge.is_report_task``).
TASK_KIND_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "task_kind",
    "instructions": (
        "Input là tên một việc trong danh sách việc cần báo cáo tiến độ tại một cuộc họp tiếng Việt. "
        "Xét theo nghĩa, không theo từ khoá: việc này hoàn thành bằng cách nào?"
    ),
    "choices": [
        {"value": "bao_cao_tai_hop", "description": "Việc chỉ yêu cầu báo cáo, trình bày tình hình hay thông tin về một đối tượng (dự án, công việc, số liệu) cho cuộc họp; xong khi đã báo cáo."},
        {"value": "lam_san_pham", "description": "Việc phải làm ra một sản phẩm hay kết quả: văn bản, tờ trình, hồ sơ, báo cáo viết, ý kiến được tiếp thu, công trình, thủ tục được duyệt...; xong khi có sản phẩm đó."},
    ],
}

# Hai câu hỏi dùng tên lựa chọn riêng ("chi_nhac_hoi", "khac" dùng chung, cùng nghĩa) nên gộp được.
_CHOICE_TO_STATUS: dict[str, str] = {**PROGRESS_ACT_TO_STATUS, **REPORT_ACT_TO_STATUS}


@dataclass(frozen=True, slots=True)
class ProgressActJudgement:
    """Kết quả phân loại một lượt nói cho một việc.

    Các trường:
        label: lựa chọn có xác suất cao nhất (một ``value`` của câu hỏi đã dùng).
        probabilities: xác suất từng lựa chọn.
        report_task: True nếu việc chỉ là báo cáo tại cuộc họp và lượt được xét bằng
            ``REPORT_ACT_QUESTION``; False khi dùng ``PROGRESS_ACT_QUESTION``.
    """

    label: str
    probabilities: Mapping[str, float]
    report_task: bool = False

    def p_status(self, status: str) -> float:
        """Xác suất lượt nói thể hiện trạng thái ``status`` (tổng các lựa chọn ứng với nó)."""

        return sum(p for choice, p in self.probabilities.items() if _CHOICE_TO_STATUS.get(choice) == status)

    def p_any(self, statuses: Sequence[str]) -> float:
        """Tổng xác suất các trạng thái trong ``statuses``."""

        return sum(self.p_status(status) for status in statuses)

    def p_unrelated(self) -> float:
        """Xác suất lượt nói KHÔNG nói về việc đang xét (lựa chọn "khac"); thiếu thì 0."""

        return self.probabilities.get("khac", 0.0)

    def best_status(self) -> tuple[str | None, float]:
        """Trạng thái có xác suất cao nhất và xác suất đó; (None, p) nếu cao nhất là "khac"."""

        scores: dict[str | None, float] = {}
        for choice, p in self.probabilities.items():
            status = _CHOICE_TO_STATUS.get(choice)
            scores[status] = scores.get(status, 0.0) + p
        if not scores:
            return None, 0.0
        status = max(scores, key=lambda key: scores[key])
        return status, scores[status]

    def as_pairs(self) -> tuple[tuple[str, float], ...]:
        """Phân bố xác suất dạng cặp (lựa chọn, xác suất), giảm dần, bỏ lựa chọn < 0.05."""

        ranked = sorted(self.probabilities.items(), key=lambda kv: -kv[1])
        return tuple((choice, round(p, 3)) for choice, p in ranked if p >= 0.05)

    def describe(self) -> str:
        """Phân bố dạng ngắn cho lý do, vd. "bao_cao_xong 0.55, yeu_cau_lam_lai 0.30"."""

        return ", ".join(f"{choice} {p:.2f}" for choice, p in self.as_pairs())


class ProgressActJudge(Protocol):
    """Phân loại ``turn`` (biết các lượt đứng trước ``context``) cho việc ``task_title``.

    Judge tự chọn câu hỏi theo kiểu việc và ghi vào ``ProgressActJudgement.report_task``.
    Lỗi: ném exception khi không phân loại được; nơi gọi giữ trạng thái agent khai và
    đánh dấu ``unchecked`` (không quay về luật từ khoá).
    """

    def judge(self, task_title: str, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> ProgressActJudgement: ...


def render_progress_act_input(task_title: str, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> str:
    """Ghép tên việc + ngữ cảnh + lượt cần xét thành input cho Decisions.

    Đầu vào: task_title - tên việc đang xét; turn - lượt cần xét; context - các lượt ngay trước.
    Đầu ra: str.
    """

    return f"VIỆC ĐANG XÉT:\n{task_title}\n\n{render_turn_act_input(turn, context)}"


def judge_turn_windows(
    judge: ProgressActJudge, task_title: str, turn: SpeakerTurn, context: Sequence[SpeakerTurn]
) -> tuple[ProgressActJudgement, ...]:
    """Phân loại một lượt cho một việc; lượt dài hơn ``MAX_TURN_CHARS`` thì xét từng đoạn.

    Mỗi đoạn là một lời gọi riêng; đoạn sau nhận đoạn trước làm ngữ cảnh. Lượt ngữ cảnh dài
    chỉ giữ phần cuối, sát lượt cần xét. Nơi gọi tự gộp kết quả các đoạn (``nodes/progress.py``).

    Đầu vào: judge - ProgressActJudge; task_title - tên việc; turn - lượt cần xét;
        context - các lượt đứng trước, theo thứ tự.
    Đầu ra: tuple ProgressActJudgement, mỗi đoạn một phần tử, theo thứ tự trong lượt.
    Lỗi: exception của judge được ném tiếp (nơi gọi đánh dấu ``unchecked``).
    """

    return tuple(judge.judge(task_title, part, previous) for part, previous in turn_windows(turn, context))


class DecisionsProgressActJudge:
    """``ProgressActJudge`` gọi OpenAI Decisions API, nhớ kết quả theo nội dung input.

    Mỗi tên việc được xếp kiểu một lần (``is_report_task``, có cache) để chọn câu hỏi:
    ``REPORT_ACT_QUESTION`` cho việc chỉ là báo cáo tại cuộc họp, ``PROGRESS_ACT_QUESTION``
    cho việc còn lại.

    Đầu vào khi tạo:
        client: ``openai.OpenAI`` (hoặc vật có ``.decisions.create`` cùng chữ ký).
        model: model Decisions.
    """

    def __init__(self, client: Any, model: str = DEFAULT_MODEL) -> None:
        self._client = client
        self.model = model
        self._cache: dict[tuple[str, str], ProgressActJudgement] = {}
        self._kinds: dict[str, bool] = {}
        self._lock = threading.Lock()

    def _ask(self, text: str, question: Mapping[str, Any]) -> Any:
        """Một lời gọi Decisions với MỘT câu hỏi chọn; trả câu trả lời."""

        response = self._client.decisions.create(model=self.model, input=text, questions=[question])
        answer = response.answers[0]
        if getattr(answer, "type", None) != "choice":
            raise ValueError(
                f"Decisions không trả lời câu hỏi {question['name']} (type={getattr(answer, 'type', None)!r})"
            )
        return answer

    def is_report_task(self, task_title: str) -> bool:
        """Việc chỉ là báo cáo tình hình tại cuộc họp (p >= ``REPORT_TASK_MIN``)? Một lời gọi mỗi tên việc."""

        with self._lock:
            known = self._kinds.get(task_title)
        if known is not None:
            return known
        answer = self._ask(f"VIỆC:\n{task_title}", TASK_KIND_QUESTION)
        probabilities = {p.value: p.probability for p in answer.probabilities}
        report = probabilities.get("bao_cao_tai_hop", 0.0) >= REPORT_TASK_MIN
        with self._lock:
            self._kinds[task_title] = report
        return report

    def judge(self, task_title: str, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> ProgressActJudgement:
        report = self.is_report_task(task_title)
        question = REPORT_ACT_QUESTION if report else PROGRESS_ACT_QUESTION
        text = render_progress_act_input(task_title, turn, context)
        key = (question["name"], text)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached
        answer = self._ask(text, question)
        judgement = ProgressActJudgement(
            label=answer.choice,
            probabilities={p.value: p.probability for p in answer.probabilities},
            report_task=report,
        )
        with self._lock:
            self._cache[key] = judgement
        return judgement


__all__ = [
    "DecisionsProgressActJudge",
    "PROGRESS_ACT_QUESTION",
    "PROGRESS_ACT_TO_STATUS",
    "ProgressActJudge",
    "ProgressActJudgement",
    "REPORT_ACT_QUESTION",
    "REPORT_ACT_TO_STATUS",
    "REPORT_TASK_MIN",
    "STATUS_CLEAR_MIN",
    "TASK_KIND_QUESTION",
    "judge_turn_windows",
    "render_progress_act_input",
]
