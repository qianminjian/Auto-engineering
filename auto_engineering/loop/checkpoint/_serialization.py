"""Checkpoint 序列化辅助 — 状态 JSON 互转 + 嵌套 dataclass 归一化.

从 loop/checkpoint/store.py 拆分 (v2.5 P1-D). 与 _connection.py 一起, 让 store.py
专注于 Save/Load/Delete/Clear/Count 等业务方法, 不再混入 100+ 行样板.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


def normalize_history_item(item: dict[str, Any]) -> dict[str, Any]:
    """递归序列化 history 项, 处理嵌套 Verdict 等 dataclass 实例.

    v2.3 Phase D (P0.4): RoundHistory.gate_results 现在是 dict[gate_name, Verdict],
    默认 json.dumps + default=str 会把 Verdict 序列化为 "Verdict(gate_name=...)" 字符串
    (丢失结构, message 无法还原). 此函数递归把 dataclass 实例 → asdict.

    Args:
        item: RoundHistory.__dict__ (含 gate_results / task_outcomes 等嵌套 dict)

    Returns:
        可 JSON 序列化的纯 dict (嵌套 dataclass 全部展开)
    """
    return {k: normalize_value(v) for k, v in item.items()}


def normalize_value(v: Any) -> Any:
    """递归归一化任意值: dataclass → dict, 嵌套 dict/list 递归处理."""
    if is_dataclass(v) and not isinstance(v, type):
        return normalize_value(asdict(v))
    if isinstance(v, dict):
        return {kk: normalize_value(vv) for kk, vv in v.items()}
    if isinstance(v, (list, tuple)):
        return [normalize_value(x) for x in v]
    return v


def serialize_state(state: Any) -> str:
    """序列化 EngineState → JSON string.

    优先级: Pydantic model_dump → dataclass asdict → dict → to_dict → str fallback.
    """
    if hasattr(state, "model_dump"):
        return json.dumps(state.model_dump(mode="json"))
    if hasattr(state, "dict"):
        return json.dumps(state.dict())
    if is_dataclass(state):
        return json.dumps(asdict(state))
    if isinstance(state, dict):
        return json.dumps(state)
    if hasattr(state, "to_dict"):
        return json.dumps(state.to_dict())
    return json.dumps(state, default=str)


def deserialize_state(state_json: str) -> Any:
    """反序列化 JSON → CheckpointEnvelope 实例 (v2.0-D 修复).

    v2.0-D: 返回 CheckpointEnvelope 实例, channels 是 Channel 实例.
    输入是 LoopStateProtocol 序列化结果 (model_dump JSON),
    返回 CheckpointEnvelope 实例 (调用 deserialize_loop_state 重建 Channel).
    (v2.3 P0-A: 原 LoopState 重命名为 CheckpointEnvelope.)

    反序列化失败时 raise CheckpointSchemaMismatchError (不再静默降级).
    """
    try:
        data = json.loads(state_json)
    except (json.JSONDecodeError, TypeError):
        return state_json  # 原始字符串 (无法解析)

    if not isinstance(data, dict):
        return data

    # 延迟导入避免循环依赖
    from auto_engineering.loop.checkpoint.records import CheckpointError
    from auto_engineering.loop.state import deserialize_loop_state

    try:
        return deserialize_loop_state(data)
    except Exception as exc:
        raise CheckpointError(
            f"反序列化失败 (schema 可能不一致): {exc}"
        ) from exc


__all__ = [
    "normalize_history_item",
    "normalize_value",
    "serialize_state",
    "deserialize_state",
]
