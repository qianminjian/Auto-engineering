"""v2.0 Loop 子系统类型契约层.

设计动机: Phase 1 审计 P2.1 — 避免 loop/checkpoint.py ↔ loop/state.py 循环引用.

策略:
    - Protocol 定义结构化子类型 (runtime_checkable)
    - types.py 不引用 loop.state.CheckpointEnvelope, 只描述"最小接口契约"
    - checkpoint.py 可用 LoopStateProtocol 作为类型约束
    - state.py 的 CheckpointEnvelope (v2.3 P0-A 重命名, 原 LoopState) 通过 duck typing
      自动满足 Protocol

API:
    LoopStateProtocol — CheckpointEnvelope 的最小接口契约
    serialize_state(state: LoopStateProtocol) -> str  — JSON 序列化
    deserialize_state(json_str: str) -> dict          — JSON 反序列化

Note: deserialize_state 返回 dict, 由 caller (checkpoint._deserialize_state)
     负责用 deserialize_loop_state() 重建 CheckpointEnvelope 实例. 这是 v2.0-D
     已有的设计, types.py 不重复实现.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LoopStateProtocol(Protocol):
    """CheckpointEnvelope 的最小接口契约.

    任何提供这些字段/方法的类都被视为满足协议 (structural subtyping).
    CheckpointEnvelope (loop/state.py) 通过 duck typing 自动满足, 无需显式继承.
    (v2.3 P0-A: 原名 LoopState, 重命名为 CheckpointEnvelope 消除与
    engine.state.LoopState 同名双义)

    Attributes:
        round: 当前 Round 编号
        step: 当前 Step 编号
        status: 运行状态
        channels: 底层 Channel 存储 (dict)

    Methods:
        model_dump(**kwargs) -> dict: Pydantic v2 序列化 (含 Channel.checkpoint)
    """

    round: int
    step: int
    status: str
    channels: dict[str, Any]

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Pydantic v2 序列化入口. kwargs 由实现决定 (mode, exclude 等)."""
        ...


def serialize_state(state: LoopStateProtocol) -> str:
    """序列化满足 LoopStateProtocol 的对象 → JSON string.

    优先使用 state.model_dump (Pydantic v2 风格). 若无, 降级到 __dict__/dict.

    Args:
        state: 满足 LoopStateProtocol 的对象 (典型: CheckpointEnvelope 实例)

    Returns:
        JSON 字符串 (utf-8 safe, 包含全部业务字段 + channels)
    """
    if hasattr(state, "model_dump"):
        return json.dumps(state.model_dump(mode="json"))
    if isinstance(state, dict):
        return json.dumps(state)
    if hasattr(state, "__dict__"):
        return json.dumps(state.__dict__, default=str)
    # Fallback: 假设可 JSON 序列化
    return json.dumps(state, default=str)


def deserialize_state(json_str: str) -> dict[str, Any]:
    """反序列化 JSON string → dict.

    设计取舍: 返回 dict 而非 CheckpointEnvelope 实例, 因为:
        1. types.py 不应依赖 loop.state (避免循环引用)
        2. caller (SQLiteCheckpointStore._deserialize_state) 已用
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
    "LoopStateProtocol",
    "deserialize_state",
    "serialize_state",
]
