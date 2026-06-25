"""v2.0 Channel 系统 + LoopState 容器.

参考 LangGraph Channel 系统(LastValue / Topic / NamedBarrierValue).
简化: 三种类型覆盖 LOOP 子系统的核心语义, 不引入 Pregel 的版本触发机制.

设计来源: design/v2.0-Analysis-Loop.md §4.4 状态管理
Phase 2.1-A 增强: LangGraph 对齐的 copy/checkpoint/from_checkpoint 序列化三件套.
"""

from __future__ import annotations

import asyncio
import copy as _copy
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Self, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Channel[T](ABC):
    """Channel 抽象基类.

    所有 Channel 持有 name(用于在 LoopState 中标识)和内部 value.
    子类必须实现: get / update / empty / copy / checkpoint / from_checkpoint.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    def get(self) -> T | None:
        """读取 channel 当前值. 未写入时返回 None."""
        ...

    @abstractmethod
    def update(self, value: T) -> T:
        """写入 channel, 返回写入后的当前值(便于链式调用)."""
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

    def set(self, value: T) -> None:
        """便捷方法: 写入不关心返回值. 子类按需覆盖."""
        self.update(value)


class LastValueChannel(Channel[T]):
    """单写覆盖语义.

    每次 update 覆盖前一值. 适用于: Plan 状态、Review 结论、
    单一权威输出. v1.1 dataclass LoopState 的核心字段都可映射为此类型.
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._value: T | None = None

    def get(self) -> T | None:
        return self._value

    def update(self, value: T) -> T:
        self._value = value
        return self._value

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

    def update(self, value: T) -> list[T]:
        self._values.append(value)
        return list(self._values)

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
        if self._state.is_set:
            self._event.set()

    def get(self) -> int:
        """返回当前已写入数量(用于监控)."""
        return self._state.count

    def update(self, value: Any = None) -> int:
        """写入一次, 达到 expected 时解除所有 waiter 阻塞."""
        self._state.count += 1
        if self._state.count >= self._state.expected and not self._state.is_set:
            self._state.is_set = True
            self._event.set()
        return self._state.count

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
        # 重建 Event 状态(从 is_set 同步)
        if new._state.is_set:
            new._event.set()
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
        # 同步 Event 状态
        if is_set:
            self._event.set()
        else:
            self._event.clear()


class LoopState(BaseModel):
    """v2.0 多 Agent 共享状态容器.

    持有 channels: dict[str, Channel], 各 Agent 通过 name 读写.
    类型: Pydantic BaseModel, 支持序列化 (未来 checkpoint 用).
    """

    model_config = {"arbitrary_types_allowed": True}

    channels: dict[str, Channel[Any]] = Field(default_factory=dict)

    def get_channel(self, name: str) -> Any:
        """读取指定 channel 的当前值. 缺失返回 None."""
        ch = self.channels.get(name)
        if ch is None:
            return None
        return ch.get()

    def set_channel(self, name: str, value: Any) -> None:
        """写入指定 channel. 未知 channel 抛 KeyError(显式错误优于静默失败)."""
        if name not in self.channels:
            raise KeyError(
                f"Channel '{name}' not registered in LoopState. "
                f"Available: {list(self.channels.keys())}"
            )
        self.channels[name].update(value)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Pydantic v2 序列化: 自动用 Channel.checkpoint() 替换 Channel 实例.

        这是 Phase 1 审计 PydanticSerializationError 的修复点:
        - 父类 model_dump 会尝试序列化 Channel 对象 → 失败
        - 覆盖后先用 checkpoint() 转 dict, 再 dict-to-dict 序列化
        """
        channels_data: dict[str, Any] = {}
        for name, ch in self.channels.items():
            channels_data[name] = ch.checkpoint()

        # 调用父类 model_dump 时临时用 channels_data 替换
        # 注: Pydantic v2 model_dump 用 __pydantic_serializer__, 我们通过
        # 自己构造 dict 返回 (因为 channels 字段是 dict[str, Channel],
        # 父类无法直接处理)
        return {
            "channels": channels_data,
        }
