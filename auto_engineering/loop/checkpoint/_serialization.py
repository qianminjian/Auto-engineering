"""Checkpoint 序列化辅助 — 状态 JSON 互转 + 嵌套 dataclass 归一化.

从 loop/checkpoint/store.py 拆分 (v2.5 P1-D). 与 _connection.py 一起, 让 store.py
专注于 Save/Load/Delete/Clear/Count 等业务方法, 不再混入 100+ 行样板.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


def _normalize_history_item(item: dict[str, Any]) -> dict[str, Any]:
    """递归序列化 history 项, 处理嵌套 Verdict 等 dataclass 实例.

    v2.3 Phase D (P0.4): RoundHistory.gate_results 现在是 dict[gate_name, Verdict],
    默认 json.dumps + default=str 会把 Verdict 序列化为 "Verdict(gate_name=...)" 字符串
    (丢失结构, message 无法还原). 此函数递归把 dataclass 实例 → asdict.

    Args:
        item: RoundHistory.__dict__ (含 gate_results / task_outcomes 等嵌套 dict)

    Returns:
        可 JSON 序列化的纯 dict (嵌套 dataclass 全部展开)
    """
    return {k: _normalize_value(v) for k, v in item.items()}


def _normalize_value(v: Any) -> Any:
    """递归归一化任意值: dataclass → dict, 嵌套 dict/list 递归处理."""
    if is_dataclass(v) and not isinstance(v, type):
        return _normalize_value(asdict(v))
    if isinstance(v, dict):
        return {kk: _normalize_value(vv) for kk, vv in v.items()}
    if isinstance(v, (list, tuple)):
        return [_normalize_value(x) for x in v]
    return v


def _serialize_state(state: Any) -> str:
    """序列化 CheckpointEnvelope → JSON string.

    优先 Pydantic v2 model_dump, 降级到 __dict__/dict.
    """
    if hasattr(state, "model_dump"):
        # Pydantic v2
        return json.dumps(state.model_dump(mode="json"))
    if hasattr(state, "dict"):
        # Pydantic v1
        return json.dumps(state.dict())
    if isinstance(state, dict):
        return json.dumps(state)
    # Fallback: 假设可 JSON 序列化
    return json.dumps(state, default=str)


def _deserialize_state(state_json: str) -> Any:
    """反序列化 JSON → CheckpointEnvelope 实例 (v2.0-D 修复).

    v2.0-D: 返回 CheckpointEnvelope 实例, channels 是 Channel 实例.
    输入是 LoopStateProtocol 序列化结果 (model_dump JSON),
    返回 CheckpointEnvelope 实例 (调用 deserialize_loop_state 重建 Channel).
    (v2.3 P0-A: 原 LoopState 重命名为 CheckpointEnvelope.)

    Fallback: 若反序列化失败, 返回原始 dict (向后兼容, 不抛异常中断 load).
    """
    try:
        data = json.loads(state_json)
    except (json.JSONDecodeError, TypeError):
        return state_json  # 原始字符串 (无法解析)

    if not isinstance(data, dict):
        return data

    # 延迟导入避免循环依赖
    from auto_engineering.loop.state import deserialize_loop_state

    try:
        return deserialize_loop_state(data)
    except Exception:
        # 反序列化失败 (例如旧版 schema), 返回原始 dict
        # 集成代码可识别 type 决定如何处理
        return data


__all__ = [
    "_normalize_history_item",
    "_normalize_value",
    "_serialize_state",
    "_deserialize_state",
]
