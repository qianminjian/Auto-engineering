"""v2.0 Loop 子系统序列化帮助函数.

v5.5 P1-8: LoopStateProtocol 移除 — 项目不使用 mypy, Protocol 形同虚设.
serialize_state 接受 Any, 运行时 duck-type 检查 (model_dump / __dict__ / dict).

API:
    serialize_state(state: Any) -> str      — JSON 序列化
    deserialize_state(json_str: str) -> dict — JSON 反序列化
"""

from __future__ import annotations

import json
from typing import Any


def serialize_state(state: Any) -> str:
    """序列化对象 → JSON string.

    委托给 loop/checkpoint/_serialization.py 的统一实现.

    Args:
        state: 任意可序列化对象 (典型: CheckpointEnvelope 实例)

    Returns:
        JSON 字符串 (utf-8 safe, 包含全部业务字段 + channels)
    """
    from auto_engineering.loop.checkpoint._serialization import serialize_state as _impl
    return _impl(state)


def deserialize_state(json_str: str) -> dict[str, Any]:
    """反序列化 JSON string → dict.

    设计取舍: 返回 dict 而非 CheckpointEnvelope 实例, 因为:
        1. types.py 不应依赖 loop.state (避免循环引用)
        2. caller (SQLiteCheckpointStore.deserialize_state) 已用
           deserialize_loop_state() 重建 Channel 实例 (v2.0-D)

    Args:
        json_str: JSON 字符串 (CheckpointEnvelope 序列化结果)

    Returns:
        dict (CheckpointEnvelope 字段), 或原始字符串 (解析失败时)
    """
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return {"__raw__": json_str}  # 包装为 dict 保持类型一致
    if not isinstance(data, dict):
        return {"__value__": data}
    return data


__all__ = [
    "deserialize_state",
    "serialize_state",
]
