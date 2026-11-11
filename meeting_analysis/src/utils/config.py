"""Cấu hình của bước 1 (dựng lượt nói) và bước 3 (đặt tên chủ đề), đọc từ file cấu hình JSON. Cấu hình
của bước 4-6 nằm riêng trong thư mục pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


def _positive_int(name: str, value: int) -> None:
    """Kiểm ``value`` là số nguyên dương; bool không được tính là số.

    Raises:
        ValueError: Khi ``value`` sai kiểu hoặc <= 0; thông điệp nêu ``name``.
    """

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _non_negative_int(name: str, value: int) -> None:
    """Kiểm ``value`` là số nguyên >= 0; bool không được tính là số.

    Raises:
        ValueError: Khi ``value`` sai kiểu hoặc âm; thông điệp nêu ``name``.
    """

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class TurnBuilderConfig:
    """Cấu hình bước 1: gộp các dòng bản ghi liền nhau thành lượt nói.

    Giá trị được kiểm ngay khi tạo; sai kiểu hoặc âm thì báo ``ValueError``.

    Attributes:
        max_gap_ms: Khoảng nghỉ tối đa (mili-giây) giữa hai dòng của cùng một người để còn gộp vào
            chung một lượt.
        merge_when_timestamp_missing: True thì vẫn gộp khi một trong hai dòng thiếu mốc thời gian.
        merge_unknown_speakers: True thì gộp cả các dòng liền nhau không rõ người nói.
    """

    max_gap_ms: int = 1_500
    merge_when_timestamp_missing: bool = False
    merge_unknown_speakers: bool = False

    def __post_init__(self) -> None:
        _non_negative_int("turn_builder.max_gap_ms", self.max_gap_ms)
        if not isinstance(self.merge_when_timestamp_missing, bool):
            raise ValueError(
                "turn_builder.merge_when_timestamp_missing must be a boolean"
            )
        if not isinstance(self.merge_unknown_speakers, bool):
            raise ValueError("turn_builder.merge_unknown_speakers must be a boolean")


_DEFAULT_TITLE_BLACKLIST: tuple[str, ...] = (
    "thảo luận",
    "các vấn đề khác",
    "vấn đề khác",
    "nội dung khác",
    "nội dung thảo luận",
    "thảo luận chung",
    "khác",
)


@dataclass(frozen=True, slots=True)
class TopicLabelerConfig:
    """Cấu hình bước 3: đặt tên cho từng đoạn chủ đề.

    Giá trị được kiểm ngay khi tạo; sai thì báo ``ValueError``.

    Attributes:
        mode: Cách đặt tên; hiện chỉ hỗ trợ ``"llm"``.
        max_title_chars: Số ký tự tối đa của tiêu đề; dài hơn thì cắt ở ranh giới từ.
        title_blacklist: Các tiêu đề chung chung bị cấm, ví dụ "thảo luận", "vấn đề khác".
        max_retry_attempts: Số lần hỏi lại LLM khi tên bị bộ kiểm chặn, trước khi dùng tên dự phòng;
            0 nghĩa là không hỏi lại.
        blacklist_subset_check: True thì chặn cả tiêu đề mà, sau khi bỏ từ dừng, mọi từ còn lại đều
            nằm trong một mục của ``title_blacklist``.
    """

    mode: str = "llm"
    max_title_chars: int = 80
    title_blacklist: tuple[str, ...] = _DEFAULT_TITLE_BLACKLIST
    max_retry_attempts: int = 3
    blacklist_subset_check: bool = True

    def __post_init__(self) -> None:
        if self.mode != "llm":
            raise ValueError("topic_labeler.mode must be 'llm'")
        _positive_int("topic_labeler.max_title_chars", self.max_title_chars)
        if not isinstance(self.title_blacklist, tuple) or not all(
            isinstance(entry, str) and entry.strip() for entry in self.title_blacklist
        ):
            raise ValueError(
                "topic_labeler.title_blacklist must be a tuple of non-empty strings"
            )
        _non_negative_int(
            "topic_labeler.max_retry_attempts", self.max_retry_attempts
        )
        if not isinstance(self.blacklist_subset_check, bool):
            raise ValueError(
                "topic_labeler.blacklist_subset_check must be a boolean"
            )


def _mapping_section(data: Mapping[str, Any], name: str) -> dict[str, Any]:
    """Lấy bản sao mục ``name`` của cấu hình; thiếu mục hoặc mục là null thì trả dict rỗng.

    Raises:
        ValueError: Khi mục có mặt nhưng không phải object JSON.
    """

    section = data.get(name)
    if section is None:
        return {}
    if not isinstance(section, Mapping):
        raise ValueError(f"config section {name!r} must be a JSON object")
    return dict(section)


def _only_keys(section: Mapping[str, Any], allowed: set[str], name: str) -> None:
    """Kiểm mục cấu hình không có khoá lạ, để bắt lỗi gõ sai tên khoá.

    Raises:
        ValueError: Khi ``section`` có khoá ngoài ``allowed``; thông điệp liệt kê các khoá đó.
    """

    unexpected = sorted(set(section) - allowed)
    if unexpected:
        joined = ", ".join(unexpected)
        raise ValueError(f"unknown key(s) in {name}: {joined}")


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Toàn bộ cấu hình đọc từ file JSON cho bước 1 và bước 3.

    Attributes:
        turn_builder: Cấu hình gộp dòng thành lượt nói.
        topic_labeler: Cấu hình đặt tên chủ đề.
    """

    turn_builder: TurnBuilderConfig = TurnBuilderConfig()
    topic_labeler: TopicLabelerConfig = TopicLabelerConfig()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PipelineConfig:
        """Dựng cấu hình từ dict đã đọc từ JSON.

        Mục nào thiếu thì dùng giá trị mặc định. Danh sách tiêu đề cấm trong JSON là mảng, được đổi
        sang tuple.

        Args:
            data: Object gốc của file cấu hình, gồm các mục ``turn_builder`` và ``topic_labeler``.

        Returns:
            Cấu hình đã kiểm hợp lệ.

        Raises:
            ValueError: Khi gốc hoặc một mục không phải object, có khoá lạ, hoặc giá trị sai kiểu.
        """

        if not isinstance(data, Mapping):
            raise ValueError("pipeline config must be a JSON object")
        _only_keys(data, {"turn_builder", "topic_labeler"}, "root config")

        turn = _mapping_section(data, "turn_builder")
        topic_labeler = _mapping_section(data, "topic_labeler")

        _only_keys(
            turn,
            {
                "max_gap_ms",
                "merge_when_timestamp_missing",
                "merge_unknown_speakers",
            },
            "turn_builder",
        )
        _only_keys(
            topic_labeler,
            {
                "mode",
                "max_title_chars",
                "title_blacklist",
                "max_retry_attempts",
                "blacklist_subset_check",
            },
            "topic_labeler",
        )
        if "title_blacklist" in topic_labeler:
            blacklist = topic_labeler["title_blacklist"]
            if not isinstance(blacklist, list) or not all(
                isinstance(entry, str) for entry in blacklist
            ):
                raise ValueError(
                    "topic_labeler.title_blacklist must be a JSON array of strings"
                )
            topic_labeler["title_blacklist"] = tuple(blacklist)

        return cls(
            turn_builder=TurnBuilderConfig(**turn),
            topic_labeler=TopicLabelerConfig(**topic_labeler),
        )

    @classmethod
    def load(cls, path: str | Path) -> PipelineConfig:
        """Đọc cấu hình từ file JSON (UTF-8).

        Args:
            path: Đường dẫn tới file cấu hình.

        Returns:
            Cấu hình đã kiểm hợp lệ.

        Raises:
            ValueError: Khi file không phải JSON hợp lệ, gốc không phải object, hoặc nội dung sai.
            OSError: Khi không đọc được file (ví dụ file không tồn tại).
        """

        config_path = Path(path)
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON config {config_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("pipeline config must be a JSON object")
        return cls.from_mapping(payload)


def load_config(path: str | Path | None = None) -> PipelineConfig:
    """Đọc cấu hình từ file, hoặc trả cấu hình mặc định.

    Args:
        path: Đường dẫn file cấu hình JSON; None thì dùng toàn bộ giá trị mặc định trong code.

    Returns:
        Cấu hình của pipeline.
    """

    return PipelineConfig() if path is None else PipelineConfig.load(path)


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "default.json"


def load_default_config() -> PipelineConfig:
    """Đọc file cấu hình mặc định ở gốc repo; nếu không có file thì dùng giá trị mặc định trong code."""

    return load_config(DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.is_file() else None)


__all__ = [
    "PipelineConfig",
    "TopicLabelerConfig",
    "DEFAULT_CONFIG_PATH",
    "TurnBuilderConfig",
    "load_config",
    "load_default_config",
]
