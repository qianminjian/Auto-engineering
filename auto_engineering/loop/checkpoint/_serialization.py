"""Checkpoint 序列化辅助 — 状态 JSON 互转 + 嵌套 dataclass 归一化 + Channel 类型.

从 loop/checkpoint/store.py 拆分 (v2.5 P1-D). 与 _connection.py 一起, 让 store.py
专注于 Save/Load/Delete/Clear/Count 等业务方法, 不再混入 100+ 行样板.

v5.5 P1-3: Channel 系统 (原 loop/state/channels.py) 折叠到本文件.
Channel 类型仅用于 CheckpointEnvelope 的 checkpoint 序列化/反序列化,
不参与运行时主循环 (主循环走 engine.state.EngineState dataclass).
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
    """反序列化 JSON → 按 dict 形状三路分派 (checkpoint 契约修复).

    历史行为 (v2.0-D) 无条件强构造 CheckpointEnvelope, 导致两类 bug:
      - plain dict (step 为 string) → pydantic ValidationError → CheckpointError
      - production EngineState checkpoint → 丢 critic_verdict/thread_id/batch_state_json

    修复: 按 dict 形状分派 (marker 不重叠, 见 test_dispatch_markers_*):
      1. "channels" in data   → CheckpointEnvelope  (migration/历史, model_dump 恒发 channels)
      2. "thread_id" in data  → EngineState          (production 主循环状态, asdict 恒发 thread_id)
      3. else                 → 返回原始 dict        (plain/partial, 不强构造)

    非 dict / 无法解析的 JSON 原样返回.
    CheckpointError 仅在 envelope 分支真异常时抛出 (不再无条件包装).
    """
    try:
        data = json.loads(state_json)
    except (json.JSONDecodeError, TypeError):
        return state_json  # 原始字符串 (无法解析)

    if not isinstance(data, dict):
        return data

    # 分派 1 — migration/历史: CheckpointEnvelope model_dump 恒发 "channels" 键
    if "channels" in data:
        # 延迟导入避免循环依赖
        from auto_engineering.loop.checkpoint.records import CheckpointError
        from auto_engineering.loop.state import deserialize_loop_state

        try:
            return deserialize_loop_state(data)
        except Exception as exc:
            raise CheckpointError(
                f"反序列化失败 (schema 可能不一致): {exc}"
            ) from exc

    # 分派 2 — production 主循环状态: EngineState asdict 恒发 "thread_id", 无 "channels"
    if "thread_id" in data:
        from auto_engineering.engine.state import EngineState

        return EngineState.from_dict(data)

    # 分派 3 — plain/partial dict: 不强构造, 原样返回 (满足 store 层 ck.state == state)
    return data


__all__ = [
    "normalize_history_item",
    "normalize_value",
    "serialize_state",
    "deserialize_state",
    # Channel 类型 (v5.5 P1-3: 从 loop/state/channels.py 折叠)
    "Channel",
    "LastValueChannel",
    "AccumulatingChannel",
    "BarrierChannel",
    "BarrierState",
]


# ============================================================
# Channel 类型 (v5.5 P1-3: 从 loop/state/channels.py 折叠)
# ============================================================
# 仅用于 CheckpointEnvelope 的 checkpoint 序列化/反序列化.
# 主循环状态管理走 engine.state.EngineState dataclass, 不经过 Channel.
# 若未来引入多 Agent 并发写同一 Channel 的用例, 需在 Envelope 层加
# asyncio.Lock + 按 Agent role 分区.

import asyncio
import copy as _copy
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self, TypeVar

T = TypeVar("T")


class Channel[T](ABC):
    """Channel 抽象基类.

    所有 Channel 持有 name(用于在 CheckpointEnvelope 中标识)和内部 value.
    子类必须实现: get / update / empty / copy / checkpoint / from_checkpoint.

    v2.5 P2-C-2 并发不变量:
        Channel 在 v2.0 架构中**不在并发路径上** —
        - 构造时通过 Pydantic 设置初始值 (单线程, 一次性)
        - 运行时读写由单个 agent / 阶段负责
        - v2.0 multi-agent 走 engine.state.EngineState, 不写 CheckpointEnvelope.channels
        - asyncio.gather 并行的多个 agent 通过 task_role 隔离 (e.g., "plan" channel
          只由 architect agent 写, "files_changed" 只由 developer agent 写)
        Channel 名字 = agent role, 天然 partition, 无共享写.
    如果未来 CheckpointEnvelope.set_channel / channel.update 在多 agent
    并发路径被调用, 需要在 Envelope 层加 asyncio.Lock 或
    重新审视 channel partition 不变量.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def get(self) -> T | None:
        """读取 channel 当前值. 未写入时返回 None."""
        ...

    @abstractmethod
    def update(self, values: Sequence[T]) -> bool:
        """批量更新 Channel, 返回 True 表示有变化 (可触发下游), False 表示无变化.

        对齐 LangGraph BaseChannel.update(values: Sequence[Update]) -> bool
        参考: langgraph/libs/langgraph/langgraph/channels/base.py:90

        设计要点:
        - 接 Sequence[T] 而非单值 T, 支持一次调用批量写入
        - 返回 bool 替代旧版的 T, 用于驱动下游触发逻辑
        - 空序列是合法调用, 表示无更新 (Pregel 在每步结束会调用一次)
        """
        ...

    @abstractmethod
    def empty(self) -> bool:
        """Channel 是否未写入/未满足完成条件."""
        ...

    @abstractmethod
    def copy(self) -> Self:
        """深拷贝 Channel. 副本与原对象 state 独立.

        用于 Checkpoint 加载时重建 Channel,避免与已存在的 Channel 共享状态.
        """
        ...

    @abstractmethod
    def checkpoint(self) -> Any:
        """导出 JSON 可序列化的状态值.

        返回值必须能被 json.dumps() 序列化,作为 Pydantic model_dump 的一部分.
        返回结构由子类自定义(from_checkpoint 必须能反序列化).
        """
        ...

    @abstractmethod
    def from_checkpoint(self, value: Any) -> None:
        """从 checkpoint 值恢复 Channel 内部状态.

        Args:
            value: 必须由同类型的 checkpoint() 返回,类型不匹配抛 ValueError.
        """
        ...

    def set(self, value: T) -> bool:
        """便捷方法: 单值写入. 内部包装为 [value] 序列调用 update()."""
        return self.update([value])


class LastValueChannel(Channel[T]):
    """单写覆盖语义.

    每次 update 覆盖前一值. 适用于: Plan 状态、Review 结论、
    单一权威输出. v2.0 dataclass LoopState (engine.state) 的核心字段都可映射为此类型.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._value: T | None = None

    def get(self) -> T | None:
        return self._value

    def update(self, values: Sequence[T]) -> bool:
        """批量写入: 取序列最后值覆盖 _value, 有变化返回 True.

        对齐 LangGraph LastValue.update(values: Sequence[Value]) -> bool.
        空序列不改变状态, 返回 False (无变化).

        Returns:
            bool: 是否有变化 (用于驱动下游触发).
        """
        if not values:
            return False
        new_value = values[-1]
        changed = new_value != self._value
        self._value = new_value
        return changed

    def empty(self) -> bool:
        return self._value is None

    def copy(self) -> Self:
        """深拷贝 LastValueChannel(包含 _value)."""
        new = LastValueChannel(self.name)
        # 深拷贝 _value 避免可变对象共享(JSON 序列化值可能是 dict/list)
        new._value = _copy.deepcopy(self._value)
        return new  # type: ignore[return-value]

    def checkpoint(self) -> Any:
        """导出 JSON 序列化值.

        Returns:
            self._value (None 或 JSON 可序列化的值)
        """
        return self._value

    def from_checkpoint(self, value: Any) -> None:
        """从 checkpoint 值恢复 _value.

        Args:
            value: 任意 JSON 可序列化值(或 None)
        """
        self._value = value


class AccumulatingChannel(Channel[T]):
    """多写 append 语义.

    每次 update 将值追加到列表. 适用于: Task 完成列表、Gate 结果汇总、
    Agent 发现列表. 保留写入顺序, 支持 initial 初始化.
    """

    def __init__(self, name: str, initial: list[T] | None = None) -> None:
        super().__init__(name)
        self._values: list[T] = list(initial) if initial else []

    def get(self) -> list[T]:
        return list(self._values)  # 防御性拷贝, 防止外部修改内部状态

    def update(self, values: Sequence[T | list[T]]) -> bool:
        """批量写入: 扩展 _values, 序列中每个元素若是 list 则展平后追加.

        对齐 LangGraph Topic.update(values: Sequence[Value | list[Value]]) -> bool.
        参考: langgraph/libs/langgraph/langgraph/channels/topic.py:77

        Returns:
            bool: 非空序列返回 True (有新增), 空序列返回 False.
        """
        if not values:
            return False
        for v in values:
            if isinstance(v, list):
                self._values.extend(v)
            else:
                self._values.append(v)  # type: ignore[arg-type]
        return True

    def empty(self) -> bool:
        return len(self._values) == 0

    def copy(self) -> Self:
        """深拷贝 AccumulatingChannel(包含 _values)."""
        new = AccumulatingChannel(self.name)
        new._values = _copy.deepcopy(self._values)
        return new  # type: ignore[return-value]

    def checkpoint(self) -> list[T]:
        """导出 JSON 序列化值.

        Returns:
            self._values 列表(浅拷贝,元素由调用方不可变时 JSON 友好)
        """
        return list(self._values)

    def from_checkpoint(self, value: Any) -> None:
        """从 list 恢复 _values.

        Args:
            value: list 类型(JSON 可序列化数组)
        """
        if not isinstance(value, list):
            raise ValueError(
                f"AccumulatingChannel.from_checkpoint expects list, "
                f"got {type(value).__name__}"
            )
        # 深拷贝恢复的元素,避免外部修改影响 Channel 状态
        self._values = _copy.deepcopy(value)


# ============================================================
# BarrierChannel 状态重构 (v2.0-A)
# 原实现: asyncio.Event (不可 JSON 序列化)
# 新实现: BarrierState dataclass + asyncio.Event (Event 从 state 重建)
# 设计权衡:
#   - 状态字段拆为 dataclass, JSON 可序列化
#   - 保留 asyncio.Event 用于 wait() 性能(polling 改为可选)
#   - 序列化时只持久化 BarrierState, Event 状态从 is_set 重建
# ============================================================


@dataclass
class BarrierState:
    """BarrierChannel 的 JSON 可序列化状态.

    替代 asyncio.Event 作为权威状态:
    - expected: 总需写入数量
    - count: 当前已写入数量
    - is_set: 是否达成(expected <= count)

    Event 状态从 is_set 重建,避免序列化 Event 对象本身.
    """

    expected: int
    count: int
    is_set: bool


class BarrierChannel(Channel[Any]):
    """同步点: 等待所有写入者完成.

    构造时指定 expected 数量. 每次 update 计数 +1, 达到 expected 时
    唤醒所有 wait(). 适用于: 多 Agent 同步点、Round 收齐信号.

    实现细节:
    - 状态权威: BarrierState (dataclass, JSON 可序列化)
    - 事件机制: asyncio.Event (从 is_set 重建, 不持久化)
    - expected=0 时立即 set, wait() 立即返回.
    """

    def __init__(self, name: str, expected: int) -> None:
        super().__init__(name)
        if expected < 0:
            raise ValueError(f"BarrierChannel.expected must be >= 0, got {expected}")
        # 状态权威: BarrierState (可序列化)
        self._state = BarrierState(expected=expected, count=0, is_set=(expected == 0))
        # 事件: 从 _state.is_set 重建, 仅用于 wait() 唤醒
        self._event = asyncio.Event()
        self._sync_event()

    def _sync_event(self) -> None:
        """根据当前 _state.is_set 同步 asyncio.Event 状态.

        BarrierChannel 的核心不变量: _event.is_set() == _state.is_set.
        __init__ / update / copy / from_checkpoint 修改 state 后必须调用本方法.
        """
        if self._state.is_set:
            self._event.set()
        else:
            self._event.clear()

    def get(self) -> int:
        """返回当前已写入数量(用于监控)."""
        return self._state.count

    def update(self, values: Sequence[Any]) -> bool:
        """批量写入: 每次调用按序列长度 +count, 达到 expected 时唤醒所有 waiter.

        对齐 LangGraph BaseChannel.update 签名: 接 Sequence + 返回 bool.
        单值语义: BarrierChannel.update([None]) 等价旧 update(None) (+1).

        Returns:
            bool: 达到 expected 返回 True (触发下游), 否则 False.
        """
        if not values:
            return False
        self._state.count += len(values)
        if self._state.count >= self._state.expected and not self._state.is_set:
            self._state.is_set = True
            self._sync_event()
            return True
        return False

    def empty(self) -> bool:
        """未达到 expected 时为空."""
        return not self._state.is_set

    async def wait(self) -> None:
        """等待直到达到 expected 数量."""
        await self._event.wait()

    def copy(self) -> Self:
        """深拷贝 BarrierChannel(包含 _state 副本)."""
        new = BarrierChannel(self.name, expected=self._state.expected)
        # 深拷贝 BarrierState (dataclass, 含基本类型)
        new._state = BarrierState(
            expected=self._state.expected,
            count=self._state.count,
            is_set=self._state.is_set,
        )
        new._sync_event()
        return new  # type: ignore[return-value]

    def checkpoint(self) -> dict[str, Any]:
        """导出 JSON 序列化值.

        Returns:
            {"expected": int, "count": int, "is_set": bool}
        """
        return {
            "expected": self._state.expected,
            "count": self._state.count,
            "is_set": self._state.is_set,
        }

    def from_checkpoint(self, value: Any) -> None:
        """从 {"expected", "count", "is_set"} 恢复状态."""
        if not isinstance(value, dict):
            raise ValueError(
                f"BarrierChannel.from_checkpoint expects dict, got {type(value).__name__}"
            )
        expected = value.get("expected")
        count = value.get("count")
        is_set = value.get("is_set")
        if not isinstance(expected, int) or expected < 0:
            raise ValueError(
                f"BarrierChannel.from_checkpoint 'expected' must be int >= 0, "
                f"got {expected!r}"
            )
        if not isinstance(count, int) or count < 0:
            raise ValueError(
                f"BarrierChannel.from_checkpoint 'count' must be int >= 0, "
                f"got {count!r}"
            )
        if not isinstance(is_set, bool):
            raise ValueError(
                f"BarrierChannel.from_checkpoint 'is_set' must be bool, "
                f"got {type(is_set).__name__}"
            )
        # 重建 BarrierState
        self._state = BarrierState(expected=expected, count=count, is_set=is_set)
        self._sync_event()
