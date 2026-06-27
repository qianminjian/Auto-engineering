"""Channel 抽象基类 + 三种具体 Channel 实现.

参考 LangGraph Channel 系统(LastValue / Topic / NamedBarrierValue).
简化: 三种类型覆盖 LOOP 子系统的核心语义, 不引入 Pregel 的版本触发机制.

设计来源: design/v2.0-Analysis-Loop.md §4.4 状态管理
"""

from __future__ import annotations

import asyncio
import copy as _copy
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Self, TypeVar

T = TypeVar("T")


class Channel[T](ABC):
    """Channel 抽象基类.

    所有 Channel 持有 name(用于在 CheckpointEnvelope 中标识)和内部 value.
    子类必须实现: get / update / empty / copy / checkpoint / from_checkpoint.
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
    单一权威输出. v1.1 dataclass LoopState (engine.state) 的核心字段都可映射为此类型.
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
# BarrierChannel 状态重构 (Phase 2.1-A)
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
