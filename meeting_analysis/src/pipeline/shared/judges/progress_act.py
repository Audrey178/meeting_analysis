"""Phân loại theo nghĩa: một lượt nói cho biết việc cần báo cáo đang ở trạng thái nào (đã xong, đang
làm, bị huỷ, được gia hạn...). Lượt nói quá dài được chia nhỏ để xét từng phần.

Có một loại việc đặc biệt: việc chỉ yêu cầu báo cáo tình hình ngay tại cuộc họp. Với loại này, việc
"xong" khi người được giao đã trình bày; tình hình của đối tượng được báo cáo (dự án còn vướng, chưa
xong...) chỉ là nội dung báo cáo, không phải trạng thái của việc. Vì vậy mỗi việc được xếp loại một
lần trước, rồi lượt nói được hỏi bằng bộ lựa chọn phù hợp với loại việc đó.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ....utils.contracts import SpeakerTurn
from .turn_act import DEFAULT_MODEL, render_turn_act_input, turn_windows


STATUS_CLEAR_MIN = 0.8
STATUS_AGREE_MIN = 0.5
REPORT_TASK_MIN = 0.8

PROGRESS_ACT_TO_STATUS: dict[str, str] = {
    "reported_done": "done",
    "reported_in_progress": "in_progress",
    "reported_blocked": "in_progress",
    "redo_requested": "in_progress",
    "paused_or_cancelled": "cancelled",
    "mention_only": "mentioned",
}

PROGRESS_ACT_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "progress_act",
    "instructions": (
        "The input is an excerpt of a Vietnamese meeting: the TASK UNDER REVIEW, a few context turns, then the TURN TO JUDGE. "
        "Classify only what the TURN TO JUDGE says about the progress of the TASK UNDER REVIEW, using the context to understand it. "
        "Judge by meaning, not keywords. Reports by the doer and directives by the chair "
        "both count; remarks, follow-up questions, or discussing content without stating how the work stands is mention_only. "
        "A turn only about the whole proposal/larger plan containing the task (the proposal must be supplemented, re-assessed, "
        "further completed) without naming the TASK UNDER REVIEW's own product or object is other."
    ),
    "choices": [
        {"value": "reported_done", "description": "The task is done, completed, its result/document exists."},
        {"value": "reported_in_progress", "description": "The task is being done, going through procedures, only partly finished, or unfinished and given more time or a later deadline."},
        {"value": "reported_blocked", "description": "The task is stuck, delayed, lacks conditions, needs unblocking."},
        {"value": "redo_requested", "description": "A request to redo, re-assess, supplement or revise the task's result."},
        {"value": "paused_or_cancelled", "description": "Cancelled, stopped for good, no longer done; or postponed, suspended."},
        {"value": "mention_only", "description": "Only mentions, asks about or discusses content; does not state how the work stands."},
        {"value": "other", "description": "Not about this task, or only about the whole proposal/larger plan containing the task."},
    ],
}

# Câu hỏi cho việc chỉ là báo cáo tình hình tại cuộc họp (xem docstring module).
REPORT_ACT_TO_STATUS: dict[str, str] = {
    "report_given": "done",
    "report_not_ready": "in_progress",
    "report_postponed": "in_progress",
    "report_redo_requested": "in_progress",
    "mention_only": "mentioned",
}

REPORT_ACT_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "report_act",
    "instructions": (
        "The input is an excerpt of a Vietnamese meeting: the TASK UNDER REVIEW (a task of reporting a situation to the meeting), "
        "a few context turns, then the TURN TO JUDGE. Classify only what the TURN TO JUDGE says about that report, using the context to understand it. "
        "Judge by meaning, not keywords. The situation of the reported object (the project is under way, unfinished, stuck...) "
        "is the CONTENT of the report, not the state of the reporting task. A turn only about the whole proposal/larger plan "
        "(the proposal must be supplemented, re-assessed, prepared for submission) without mentioning this report is other."
    ),
    "choices": [
        {"value": "report_given", "description": "The turn presents the content the task asks to report, including when answering a question about that content."},
        {"value": "report_not_ready", "description": "Says the report is not finished, being prepared, or lacks figures."},
        {"value": "report_postponed", "description": "Asks to push back or postpone the report to another time."},
        {"value": "report_redo_requested", "description": "Asks to report again, supplement, or further clarify the reported content."},
        {"value": "mention_only", "description": "Only mentions or asks about the content; not yet presented."},
        {"value": "other", "description": "Not about this task."},
    ],
}

# Xếp kiểu việc theo tên việc, một lần mỗi việc (``DecisionsApiProgressActJudge.is_report_task``).
TASK_KIND_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "task_kind",
    "instructions": (
        "The input is the name of a task in the list of tasks to report progress on at a Vietnamese meeting. "
        "Judge by meaning, not keywords: how is this task completed?"
    ),
    "choices": [
        {"value": "report_at_meeting", "description": "The task only asks to report or present the situation or information about an object (project, work, figures) to the meeting; done once reported."},
        {"value": "deliverable", "description": "The task must produce a product or result: a document, submission, dossier, written report, opinions taken in, a construction work, an approved procedure...; done once that product exists."},
    ],
}

# Hai câu hỏi dùng tên lựa chọn riêng ("mention_only", "other" dùng chung, cùng nghĩa) nên gộp được.
_CHOICE_TO_STATUS: dict[str, str] = {**PROGRESS_ACT_TO_STATUS, **REPORT_ACT_TO_STATUS}


@dataclass(frozen=True, slots=True)
class ProgressActJudgement:
    """Kết quả phân loại một lượt nói cho một việc cần báo cáo tiến độ.

    Attributes:
        label: Lựa chọn có xác suất cao nhất (một giá trị của câu hỏi đã dùng).
        probabilities: Xác suất của từng lựa chọn.
        report_task: True nếu việc chỉ là báo cáo tại cuộc họp và lượt được hỏi bằng bộ lựa chọn
            dành cho việc báo cáo; False nếu dùng bộ lựa chọn tiến độ thông thường.
    """

    label: str
    probabilities: Mapping[str, float]
    report_task: bool = False

    def p_status(self, status: str) -> float:
        """Tính xác suất lượt nói thể hiện một trạng thái, bằng tổng xác suất các lựa chọn ứng với nó.

        Args:
            status: Trạng thái việc, ví dụ "done", "in_progress", "cancelled", "mentioned".

        Returns:
            Xác suất trong [0, 1]; 0 nếu không lựa chọn nào ứng với trạng thái đó.
        """

        return sum(p for choice, p in self.probabilities.items() if _CHOICE_TO_STATUS.get(choice) == status)

    def p_unrelated(self) -> float:
        """Trả xác suất lượt nói KHÔNG nói về việc đang xét (lựa chọn "other"); thiếu thì 0."""

        return self.probabilities.get("other", 0.0)

    def agrees_with(self, status: str) -> bool:
        """Kiểm tra Decisions API có ủng hộ một trạng thái hay không.

        Trạng thái được ủng hộ khi xác suất của nó đạt ngưỡng đồng thuận VÀ lớn hơn hẳn xác suất của mọi
        trạng thái khác lẫn xác suất "không liên quan"; hoà điểm thì không tính là ủng hộ.

        Args:
            status: Trạng thái cần kiểm, thường là trạng thái agent khai.

        Returns:
            True nếu trạng thái đó đứng đầu rõ ràng và đủ ngưỡng.
        """

        p_status = self.p_status(status)
        others = (
            self.p_status(other) for other in {*_CHOICE_TO_STATUS.values()} - {status}
        )
        return p_status >= STATUS_AGREE_MIN and all(p_status > p for p in (*others, self.p_unrelated()))

    def as_pairs(self) -> tuple[tuple[str, float], ...]:
        """Trả phân bố xác suất dạng cặp (lựa chọn, xác suất), giảm dần, bỏ các lựa chọn dưới 0.05."""

        ranked = sorted(self.probabilities.items(), key=lambda kv: -kv[1])
        return tuple((choice, round(p, 3)) for choice, p in ranked if p >= 0.05)

    def describe(self) -> str:
        """Trả phân bố xác suất dạng ngắn cho lý do, ví dụ "reported_done 0.55, redo_requested 0.30"."""

        return ", ".join(f"{choice} {p:.2f}" for choice, p in self.as_pairs())


class ProgressActJudge(Protocol):
    """Hợp đồng của bộ phân loại tiến độ: xếp một lượt nói cho một việc vào một trạng thái.

    Bên cài đặt nhận tên việc, lượt cần xét và các lượt đứng trước làm ngữ cảnh. Bên cài đặt tự
    chọn bộ lựa chọn theo loại việc và ghi lại vào ``ProgressActJudgement.report_task``. Khi không
    phân loại được thì ném exception; nơi gọi giữ trạng thái agent khai và đánh dấu là chưa kiểm,
    không quay về luật từ khoá.
    """

    def judge(self, task_title: str, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> ProgressActJudgement: ...


def render_progress_act_input(task_title: str, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> str:
    """Ghép tên việc, ngữ cảnh và lượt cần xét thành input gửi Decisions API.

    Args:
        task_title: Tên việc đang xét.
        turn: Lượt cần xét.
        context: Các lượt ngay trước, theo thứ tự (chỉ vài lượt cuối được dùng).

    Returns:
        Văn bản input.
    """

    return f"TASK UNDER REVIEW:\n{task_title}\n\n{render_turn_act_input(turn, context)}"


def judge_turn_windows(
    judge: ProgressActJudge, task_title: str, turn: SpeakerTurn, context: Sequence[SpeakerTurn]
) -> tuple[ProgressActJudgement, ...]:
    """Phân loại một lượt nói cho một việc; lượt quá dài được cắt thành nhiều đoạn và xét từng đoạn.

    Args:
        judge: Bộ phân loại tiến độ.
        task_title: Tên việc đang xét.
        turn: Lượt cần xét.
        context: Các lượt đứng trước, theo thứ tự.

    Returns:
        Kết quả của từng đoạn theo thứ tự trong lượt; một phần tử nếu lượt đủ ngắn. Nơi gọi tự
        quyết định gộp các kết quả này thế nào.

    Raises:
        Exception: Lỗi của ``judge`` được ném tiếp.
    """

    return tuple(judge.judge(task_title, part, previous) for part, previous in turn_windows(turn, context))


class DecisionsApiProgressActJudge:
    """Bộ phân loại tiến độ gọi JEV qua Decisions API, nhớ kết quả để không hỏi lặp.

    Mỗi tên việc được xếp loại (chỉ báo cáo tại họp hay phải làm ra sản phẩm) đúng một lần; mỗi cặp
    (câu hỏi, input) chỉ được hỏi một lần. Bộ nhớ đệm được khoá nên dùng được từ nhiều luồng.

    Args:
        client: Đối tượng có ``.decisions.create`` để gọi Decisions API.
        model: Tên mô hình Decisions API.
    """

    def __init__(self, client: Any, model: str = DEFAULT_MODEL) -> None:
        self._client = client
        self.model = model
        self._cache: dict[tuple[str, str], ProgressActJudgement] = {}
        self._kinds: dict[str, bool] = {}
        self._lock = threading.Lock()

    def _ask(self, text: str, question: Mapping[str, Any]) -> Any:
        """Gọi Decisions API với MỘT câu hỏi lựa chọn và trả câu trả lời.

        Raises:
            ValueError: Khi câu trả lời không phải dạng lựa chọn.
        """

        response = self._client.decisions.create(model=self.model, input=text, questions=[question])
        answer = response.answers[0]
        if getattr(answer, "type", None) != "choice":
            raise ValueError(
                f"Decisions API không trả lời câu hỏi {question['name']} (type={getattr(answer, 'type', None)!r})"
            )
        return answer

    def is_report_task(self, task_title: str) -> bool:
        """Kiểm tra một việc có chỉ là báo cáo tình hình tại cuộc họp hay không.

        Chỉ coi là việc báo cáo khi xác suất đủ cao; trường hợp lưỡng lự được xem là việc phải làm ra
        sản phẩm. Mỗi tên việc chỉ tốn một lời gọi, các lần sau lấy từ bộ nhớ.

        Args:
            task_title: Tên việc trong danh sách việc cần báo cáo.

        Returns:
            True nếu việc chỉ yêu cầu báo cáo tại cuộc họp.
        """

        with self._lock:
            known = self._kinds.get(task_title)
        if known is not None:
            return known
        answer = self._ask(f"TASK:\n{task_title}", TASK_KIND_QUESTION)
        probabilities = {p.value: p.probability for p in answer.probabilities}
        report = probabilities.get("report_at_meeting", 0.0) >= REPORT_TASK_MIN
        with self._lock:
            self._kinds[task_title] = report
        return report

    def judge(self, task_title: str, turn: SpeakerTurn, context: Sequence[SpeakerTurn]) -> ProgressActJudgement:
        """Phân loại một lượt nói cho một việc, chọn bộ lựa chọn theo loại việc.

        Args:
            task_title: Tên việc đang xét.
            turn: Lượt cần xét.
            context: Các lượt đứng trước, theo thứ tự.

        Returns:
            Kết quả phân loại, có ghi loại việc đã dùng.

        Raises:
            ValueError: Khi Decisions API không trả lời dạng lựa chọn.
        """

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
    "DecisionsApiProgressActJudge",
    "PROGRESS_ACT_QUESTION",
    "PROGRESS_ACT_TO_STATUS",
    "ProgressActJudge",
    "ProgressActJudgement",
    "REPORT_ACT_QUESTION",
    "REPORT_ACT_TO_STATUS",
    "REPORT_TASK_MIN",
    "STATUS_AGREE_MIN",
    "STATUS_CLEAR_MIN",
    "TASK_KIND_QUESTION",
    "judge_turn_windows",
    "render_progress_act_input",
]
