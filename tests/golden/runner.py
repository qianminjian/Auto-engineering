"""黄金轨迹的确定性语义归一化与比较。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_NONDETERMINISTIC_FIELDS = frozenset({
    "event_id",
    "message_id",
    "timestamp",
    "created_at",
    "updated_at",
})


def normalize_semantics(value: Any) -> Any:
    """递归移除明确的非语义字段，保留所有业务字段。"""

    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in _NONDETERMINISTIC_FIELDS:
                continue
            if key == "extensions" and isinstance(item, Mapping):
                item = {
                    extension_key: extension_value
                    for extension_key, extension_value in item.items()
                    if extension_key != "host"
                }
            normalized[str(key)] = normalize_semantics(item)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [normalize_semantics(item) for item in value]
    return value


def compare_trajectory(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    """比较黄金轨迹的四个必需语义区段。"""

    for section in ("events", "projection", "action", "verdict"):
        if section not in actual or section not in expected:
            raise AssertionError(f"轨迹缺少必需区段: {section}")
        actual_value = normalize_semantics(actual[section])
        expected_value = normalize_semantics(expected[section])
        if actual_value != expected_value:
            raise AssertionError(
                f"{section} 语义不一致: "
                f"actual={actual_value!r}, expected={expected_value!r}"
            )


def load_fixtures(path: Path) -> list[dict[str, Any]]:
    """加载并校验黄金轨迹集合的最小结构。"""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("黄金轨迹文件必须是 JSON array")
    fixtures: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("黄金轨迹条目必须是 JSON object")
        if not all(key in item for key in ("name", "input", "actual", "expected")):
            raise ValueError("黄金轨迹缺少 name/input/actual/expected")
        fixtures.append(item)
    return fixtures


def compare_host_trajectories(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> None:
    """比较两个宿主产生的 Core 轨迹，仅容许已声明的展示差异。"""

    def without_platform_label(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): without_platform_label({
                    nested_key: nested_value
                    for nested_key, nested_value in item.items()
                    if nested_key != "platform"
                } if key == "host_execution" and isinstance(item, Mapping) else item)
                for key, item in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [without_platform_label(item) for item in value]
        return value

    compare_trajectory(
        without_platform_label(left),
        without_platform_label(right),
    )


__all__ = [
    "compare_host_trajectories",
    "compare_trajectory",
    "load_fixtures",
    "normalize_semantics",
]
