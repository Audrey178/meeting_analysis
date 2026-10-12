"""JSON-loadable, dependency-free pipeline configuration (``configs/default.json``)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


def _positive_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _non_negative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class TurnBuilderConfig:
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
    mode: str = "llm"
    allow_extract_fallback: bool = True
    max_title_chars: int = 80
    title_blacklist: tuple[str, ...] = _DEFAULT_TITLE_BLACKLIST
    max_retry_attempts: int = 3
    fallback_keyphrase_count: int = 3
    blacklist_subset_check: bool = True

    def __post_init__(self) -> None:
        if self.mode != "llm":
            raise ValueError("topic_labeler.mode must be 'llm'")
        if not isinstance(self.allow_extract_fallback, bool):
            raise ValueError(
                "topic_labeler.allow_extract_fallback must be a boolean"
            )
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
        _positive_int(
            "topic_labeler.fallback_keyphrase_count", self.fallback_keyphrase_count
        )
        if not isinstance(self.blacklist_subset_check, bool):
            raise ValueError(
                "topic_labeler.blacklist_subset_check must be a boolean"
            )


def _mapping_section(data: Mapping[str, Any], name: str) -> dict[str, Any]:
    section = data.get(name)
    if section is None:
        return {}
    if not isinstance(section, Mapping):
        raise ValueError(f"config section {name!r} must be a JSON object")
    return dict(section)


def _only_keys(section: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unexpected = sorted(set(section) - allowed)
    if unexpected:
        joined = ", ".join(unexpected)
        raise ValueError(f"unknown key(s) in {name}: {joined}")


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    turn_builder: TurnBuilderConfig = TurnBuilderConfig()
    topic_labeler: TopicLabelerConfig = TopicLabelerConfig()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PipelineConfig:
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
                "allow_extract_fallback",
                "max_title_chars",
                "title_blacklist",
                "max_retry_attempts",
                "fallback_keyphrase_count",
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
        config_path = Path(path)
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON config {config_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("pipeline config must be a JSON object")
        return cls.from_mapping(payload)


def load_config(path: str | Path | None = None) -> PipelineConfig:
    """Load a JSON config, or return validated defaults when ``path`` is absent."""

    return PipelineConfig() if path is None else PipelineConfig.load(path)


__all__ = [
    "PipelineConfig",
    "TopicLabelerConfig",
    "TurnBuilderConfig",
    "load_config",
]
