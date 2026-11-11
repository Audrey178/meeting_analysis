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
        "Input là trích đoạn cuộc họp tiếng Việt: VIỆC ĐANG XÉT, vài lượt ngữ cảnh rồi LƯỢT CẦN XÉT. "
        "Chỉ phân loại điều LƯỢT CẦN XÉT nói về tiến độ của VIỆC ĐANG XÉT, dùng ngữ cảnh để hiểu nó. "
        "Xét theo nghĩa, không theo từ khoá. Báo cáo của người thực hiện và chỉ đạo của người chủ trì "
        "đều tính; nhận xét, hỏi lại, bàn nội dung mà không nêu tình trạng thực hiện là mention_only. "
        "Lượt chỉ nói về cả đề án/kế hoạch lớn chứa việc (đề án phải bổ sung, đánh giá lại, tiếp tục hoàn "
        "thiện) mà không nêu sản phẩm hay đối tượng riêng của VIỆC ĐANG XÉT là other."
    ),
    "choices": [
        {"value": "reported_done", "description": "Việc đã làm xong, đã hoàn thành, đã có kết quả/văn bản."},
        {"value": "reported_in_progress", "description": "Việc đang được thực hiện, đang làm thủ tục, mới xong một phần, hoặc chưa xong và được thêm thời gian, lùi hạn."},
        {"value": "reported_blocked", "description": "Việc bị vướng, chậm, thiếu điều kiện, cần tháo gỡ."},
        {"value": "redo_requested", "description": "Yêu cầu làm lại, đánh giá lại, bổ sung, chỉnh sửa kết quả của việc."},
        {"value": "paused_or_cancelled", "description": "Huỷ, dừng hẳn, không làm nữa; hoặc hoãn, tạm dừng việc."},
        {"value": "mention_only", "description": "Chỉ nhắc tới, hỏi, bàn nội dung; không nêu tình trạng thực hiện."},
        {"value": "other", "description": "Không nói về việc này, hoặc chỉ nói về cả đề án/kế hoạch lớn chứa việc."},
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
        "Input là trích đoạn cuộc họp tiếng Việt: VIỆC ĐANG XÉT (một việc báo cáo tình hình cho cuộc họp), vài lượt "
        "ngữ cảnh rồi LƯỢT CẦN XÉT. Chỉ phân loại điều LƯỢT CẦN XÉT nói về việc báo cáo đó, dùng ngữ cảnh để hiểu nó. "
        "Xét theo nghĩa, không theo từ khoá. Tình hình của đối tượng được báo cáo (dự án đang làm, chưa xong, vướng...) "
        "là NỘI DUNG báo cáo, không phải tình trạng của việc báo cáo. Lượt chỉ nói về cả đề án/kế hoạch lớn "
        "(đề án phải bổ sung, đánh giá lại, chuẩn bị trình) mà không nói tới việc báo cáo này là other."
    ),
    "choices": [
        {"value": "report_given", "description": "Lượt nói trình bày nội dung mà việc yêu cầu báo cáo, kể cả khi trả lời câu hỏi về nội dung đó."},
        {"value": "report_not_ready", "description": "Nói báo cáo chưa xong, đang chuẩn bị, chưa đủ số liệu."},
        {"value": "report_postponed", "description": "Xin lùi, hoãn báo cáo sang lúc khác."},
        {"value": "report_redo_requested", "description": "Yêu cầu báo cáo lại, bổ sung, làm rõ thêm nội dung đã báo cáo."},
        {"value": "mention_only", "description": "Chỉ nhắc tới hoặc hỏi về nội dung; chưa trình bày."},
        {"value": "other", "description": "Không nói về việc này."},
    ],
}

# Xếp kiểu việc theo tên việc, một lần mỗi việc (``DecisionsApiProgressActJudge.is_report_task``).
TASK_KIND_QUESTION: dict[str, Any] = {
    "type": "choice",
    "name": "task_kind",
    "instructions": (
        "Input là tên một việc trong danh sách việc cần báo cáo tiến độ tại một cuộc họp tiếng Việt. "
        "Xét theo nghĩa, không theo từ khoá: việc này hoàn thành bằng cách nào?"
    ),
    "choices": [
        {"value": "report_at_meeting", "description": "Việc chỉ yêu cầu báo cáo, trình bày tình hình hay thông tin về một đối tượng (dự án, công việc, số liệu) cho cuộc họp; xong khi đã báo cáo."},
        {"value": "deliverable", "description": "Việc phải làm ra một sản phẩm hay kết quả: văn bản, tờ trình, hồ sơ, báo cáo viết, ý kiến được tiếp thu, công trình, thủ tục được duyệt...; xong khi có sản phẩm đó."},
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

    return f"VIỆC ĐANG XÉT:\n{task_title}\n\n{render_turn_act_input(turn, context)}"


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
        answer = self._ask(f"VIỆC:\n{task_title}", TASK_KIND_QUESTION)
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
