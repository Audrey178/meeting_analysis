"""Mô tả "cách dùng" mà mọi kết nối tới mô hình phải tuân theo (sinh kết quả dạng JSON, đặt tên chủ
đề), để có thể thay nhà cung cấp mà không sửa pipeline. Cũng định nghĩa các loại lỗi khi gọi mô
hình: lỗi tạm thời (nên thử lại), lỗi do yêu cầu (thử lại vẫn hỏng), và lỗi nghiêm trọng như sai
khoá truy cập hay hết tiền (nên dừng cả lượt chạy).
"""

from __future__ import annotations

from typing import Literal, Mapping, Protocol, runtime_checkable

from .contracts import TopicLabel, TopicSegment

# Why an LLM call gave up, so callers above the adapter can pick a policy:
#   timeout / connection / rate_limit / server / invalid_json -- transient,
#       worth another try at the caller's level;
#   client -- 4xx other than auth (e.g. prompt too long): retrying the same
#       request fails the same way;
#   fatal -- 401/402/403 (bad key, no balance): every later call fails too,
#       so the whole run should stop instead of losing topics one by one;
#   unknown -- not classified (non-OpenAI adapters, test doubles).
LLMErrorKind = Literal[
    "timeout", "connection", "rate_limit", "server", "invalid_json", "client", "fatal", "unknown"
]
_NON_RETRYABLE_KINDS: frozenset[str] = frozenset({"client", "fatal"})


@runtime_checkable
class TopicLabelAdapter(Protocol):
    """Hợp đồng cho bộ đặt tên chủ đề: sinh tiêu đề + tóm tắt cho một đoạn chủ đề.

    Bên cài đặt chỉ được đặt tên, không được đổi ranh giới đoạn (danh sách lượt nói giữ nguyên).
    """

    def label_topic(self, segment: TopicSegment) -> TopicLabel: ...


class LLMUpstreamError(ValueError):
    """Lỗi do phía dịch vụ LLM, không phải do dữ liệu đầu vào của bên gọi.

    Gồm: hết thời gian chờ, rớt kết nối, lỗi máy chủ 5xx, sai khoá hoặc hết tiền, bị giới hạn tần suất
    quá số lần thử, trả lời không đọc được thành JSON. Tầng trên dựa vào ``retryable`` và ``fatal`` để
    chọn: thử lại, bỏ qua chủ đề này, hay dừng cả lượt chạy.

    Args:
        message: Thông điệp lỗi.
        timed_out: Đánh dấu lỗi do hết thời gian chờ; tầng HTTP dùng để chọn trả 504 hay 502.
        kind: Loại lỗi (``LLMErrorKind``). None thì suy ra: ``"timeout"`` nếu ``timed_out``, ngược lại
            ``"unknown"``.

    Attributes:
        kind: Loại lỗi đã chốt.
        timed_out: True khi lỗi do hết thời gian chờ; luôn True nếu ``kind == "timeout"``.
    """

    def __init__(
        self, message: str, *, timed_out: bool = False, kind: LLMErrorKind | None = None
    ) -> None:
        super().__init__(message)
        if kind is None:
            kind = "timeout" if timed_out else "unknown"
        self.kind: LLMErrorKind = kind
        self.timed_out = timed_out or kind == "timeout"

    @property
    def retryable(self) -> bool:
        """Cho biết gửi lại đúng yêu cầu này có thể thành công không.

        False với lỗi do yêu cầu (``client``, ví dụ prompt quá dài) và lỗi nghiêm trọng (``fatal``).
        """

        return self.kind not in _NON_RETRYABLE_KINDS

    @property
    def fatal(self) -> bool:
        """Cho biết mọi lời gọi sau cũng sẽ hỏng (sai khoá, hết tiền), nên dừng cả lượt chạy."""

        return self.kind == "fatal"


@runtime_checkable
class LLMAdapter(Protocol):
    """Hợp đồng tối thiểu cho mọi kết nối LLM: nhận prompt và schema, trả về một object JSON.

    Bên cài đặt tự quản lý SDK/HTTP của mình, nên pipeline có thể đổi nhà cung cấp mà không sửa code.
    Hàm ``generate_json`` nhận ``system_prompt``, ``user_prompt`` và ``schema`` (JSON schema dạng
    ``{"properties": ..., "required": ...}``), trả về dict đã giải mã. Khi dịch vụ hỏng, bên cài đặt
    nên ném ``LLMUpstreamError`` kèm ``kind`` phù hợp.
    """

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: Mapping[str, object],
    ) -> Mapping[str, object]: ...


__all__ = [
    "LLMAdapter",
    "LLMErrorKind",
    "LLMUpstreamError",
    "TopicLabelAdapter",
]
