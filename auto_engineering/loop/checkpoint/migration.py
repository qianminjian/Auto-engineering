"""CheckpointEnvelope schema_version 迁移 + 验证.

与 store.py::SCHEMA_VERSION (int, SQLite 表 schema 版本) 不同,
本文件的 SCHEMA_VERSION 是 CheckpointEnvelope 数据格式版本 (str).
二者独立演化: 表结构变更不必然触发 envelope 格式变更, 反之亦然.

设计来源: Phase 14.3 (P2-3) — CheckpointEnvelope 向前兼容性.
"""

from __future__ import annotations

from typing import Any

# CheckpointEnvelope 数据格式版本 (str, 语义化版本)
SCHEMA_VERSION = "1.0"

# 1.0 格式必需字段 → 类型映射
_REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "round": int,
    "step": int,
    "status": str,
    "tasks": dict,
    "task_results": dict,
    "gate_results": dict,
    "signals": list,
    "metrics": dict,
    "channels": dict,
    "channel_versions": dict,
    "schema_version": str,
}

# 0.9 → 1.0 迁移: 缺失字段 → 默认值
_MIGRATE_0_9_DEFAULTS: dict[str, Any] = {
    "step": 0,
    "task_results": {},
    "gate_results": {},
    "signals": [],
    "metrics": {"values": {}},
    "channel_versions": {},
}


def _parse_version(version: str) -> tuple[int, ...]:
    """解析语义化版本字符串为整数元组, 用于可比对."""
    try:
        return tuple(int(p) for p in version.split("."))
    except (ValueError, AttributeError):
        raise ValueError(
            f"Invalid schema_version format: {version!r}. "
            f"Expected semantic version (e.g. '1.0', '0.9')."
        )


def migrate_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """迁移 CheckpointEnvelope dict 到当前 SCHEMA_VERSION.

    迁移路径:
      - schema_version == "1.0" (当前) → 直接返回, 不修改
      - schema_version == "0.9" → 添加 1.0 新增字段 (默认值)
      - schema_version < "0.9" → 拒绝 (raise ValueError)
      - 无 schema_version → 按 0.9 处理 (向前兼容)

    Args:
        envelope: CheckpointEnvelope 的 dict 表示 (state_json 反序列化后).

    Returns:
        迁移后的 dict (schema_version 已更新为 SCHEMA_VERSION).

    Raises:
        ValueError: schema_version 格式非法或版本过低 (<0.9).
        TypeError: envelope 不是 dict.
    """
    if not isinstance(envelope, dict):
        raise TypeError(
            f"migrate_envelope expects dict, got {type(envelope).__name__}"
        )

    # 获取当前版本
    raw_version = envelope.get("schema_version")

    if raw_version is None:
        # 无版本 → 按 0.9 处理
        current = _parse_version("0.9")
    else:
        if not isinstance(raw_version, str):
            raise ValueError(
                f"schema_version must be str, got {type(raw_version).__name__}: "
                f"{raw_version!r}"
            )
        current = _parse_version(raw_version)

    target = _parse_version(SCHEMA_VERSION)

    if current == target:
        # 已是最新, 不修改
        return envelope

    if current > target:
        # 未来版本 → 拒绝 (不支持降级)
        raise ValueError(
            f"Envelope schema_version {raw_version} is newer than current "
            f"{SCHEMA_VERSION}. Downgrade not supported. "
            f"Please upgrade Auto-Engineering."
        )

    # 0.9 → 1.0 迁移
    if current == _parse_version("0.9"):
        return _migrate_0_9_to_1_0(envelope)

    # < 0.9 → 拒绝
    raise ValueError(
        f"Envelope schema_version {raw_version or '0.9 (inferred)'} "
        f"is too old (<0.9). Please re-run 'ae init' to create a fresh "
        f"project environment."
    )


def _migrate_0_9_to_1_0(envelope: dict[str, Any]) -> dict[str, Any]:
    """0.9 → 1.0: 添加 1.0 新增字段 (默认值)."""
    migrated = dict(envelope)  # 浅拷贝, 保留原有所有字段
    for field, default in _MIGRATE_0_9_DEFAULTS.items():
        if field not in migrated:
            migrated[field] = default
    migrated["schema_version"] = SCHEMA_VERSION
    return migrated


def validate_envelope(envelope: dict[str, Any]) -> bool:
    """验证 CheckpointEnvelope dict 是否符合当前 SCHEMA_VERSION 格式.

    检查项:
      1. envelope 是 dict
      2. schema_version 匹配 SCHEMA_VERSION
      3. 所有必需字段存在且类型正确

    Args:
        envelope: CheckpointEnvelope 的 dict 表示.

    Returns:
        True = 格式有效, False = 格式无效.
    """
    if not isinstance(envelope, dict):
        return False

    # 版本检查
    if envelope.get("schema_version") != SCHEMA_VERSION:
        return False

    # 字段存在 + 类型检查
    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in envelope:
            return False
        if not isinstance(envelope[field], expected_type):
            return False

    return True
