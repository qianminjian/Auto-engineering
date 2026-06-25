"""v2.0 Channel 系统 + LoopState 容器.

参考 LangGraph Channel 系统(LastValue / Topic / NamedBarrierValue).
简化: 三种类型覆盖 LOOP 子系统的核心语义, 不引入 Pregel 的版本触发机制.

设计来源: design/v2.0-Analysis-Loop.md §4.4 状态管理
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Channel[T](ABC):
    """Channel 抽象基类.

    所有 Channel 持有 name(用于在 LoopState 中标识)和内部 value.
    子类必须实现: get / update / empty.
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


class BarrierChannel(Channel[Any]):
    """同步点: 等待所有写入者完成.

    构造时指定 expected 数量. 每次 update 计数 +1, 达到 expected 时
    唤醒所有 wait(). 适用于: 多 Agent 同步点、Round 收齐信号.

    基于 asyncio.Event 实现: expected=0 时立即 set, wait() 立即返回.
    """

    def __init__(self, name: str, expected: int) -> None:
        super().__init__(name)
        if expected < 0:
            raise ValueError(f"BarrierChannel.expected must be >= 0, got {expected}")
        self._expected = expected
        self._count = 0
        self._event = asyncio.Event()
        if expected == 0:
            self._event.set()

    def get(self) -> int:
        """返回当前已写入数量(用于监控)."""
        return self._count

    def update(self, value: Any = None) -> int:
        """写入一次, 达到 expected 时解除所有 waiter 阻塞."""
        self._count += 1
        if self._count >= self._expected:
            self._event.set()
        return self._count

    def empty(self) -> bool:
        """未达到 expected 时为空."""
        return self._count < self._expected

    async def wait(self) -> None:
        """等待直到达到 expected 数量."""
        await self._event.wait()


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