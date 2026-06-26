"""v2.0 Channel 系统 + LoopState 容器.

参考 LangGraph Channel 系统(LastValue / Topic / NamedBarrierValue).
简化: 三种类型覆盖 LOOP 子系统的核心语义, 不引入 Pregel 的版本触发机制.

设计来源: design/v2.0-Analysis-Loop.md §4.4 状态管理
Phase 2.1-A 增强: LangGraph 对齐的 copy/checkpoint/from_checkpoint 序列化三件套.
Phase 2.1-D 增强: LoopState 8 字段 + Task 字段补全 + load() 重建 Channel 实例.
"""

from __future__ import annotations

import asyncio
import copy as _copy
from abc import ABC, abstractmethod
from collections.abc import Sequence
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
    单一权威输出. v1.1 dataclass LoopState 的核心字段都可映射为此类型.
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


# ============================================================
# LoopState 辅助类型 (Phase 2.1-D)
# 设计文档: design/v2.0-Design-Loop.md §3.1
# ============================================================


@dataclass
class Signal:
    """跨 Agent 信号 (Signal 流).

    Attributes:
        type: 信号类型 (e.g. "metric.update", "task.done", "round.complete")
        payload: 信号数据 (任意 JSON 可序列化值)
        source: 信号源 (可选, agent/task id)
    """

    type: str
    payload: Any
    source: str | None = None


@dataclass
class GateVerdict:
    """Gate 验证结果 (LoopState.gate_results value).

    Attributes:
        passed: Gate 是否通过
        reason: 通过/失败原因
        details: 详细结果 (任意 JSON 可序列化值)
    """

    passed: bool
    reason: str = ""
    details: Any = None


class MetricsSnapshot(BaseModel):
    """指标快照 (LoopState.metrics).

    Attributes:
        values: 指标名 → 值
    """

    model_config = {"arbitrary_types_allowed": True}

    values: dict[str, float | int] = Field(default_factory=dict)

    def __getitem__(self, key: str) -> float | int | None:
        return self.values.get(key)

    def __setitem__(self, key: str, value: float | int) -> None:
        self.values[key] = value

    def get(self, key: str, default: float | int | None = None) -> float | int | None:
        return self.values.get(key, default)


class LoopState(BaseModel):
    """v2.0 多 Agent 共享状态容器 (Phase 2.1-D 补全字段).

    设计文档 §3.1: 8 个核心字段 + 底层 channels 存储.

    Attributes:
        round: 当前 Round 编号 (0 = 未开始)
        step: 当前 Step 编号 (L1 Inner Loop iteration)
        status: 运行状态 (running / converged / failed / interrupted)
        tasks: 任务字典 (LastValue 语义, 最后写入的 Task 是权威)
        task_results: 任务结果字典 (Accumulating 语义, 历史保留)
        gate_results: Gate 验证结果 (LastValue 语义)
        signals: 信号流列表 (Topic 语义, 按时间顺序)
        metrics: 指标快照 (BinaryOperatorAggregate 语义)
        channels: 底层 Channel 存储 (保留, 用于 Channel 系统 API)
    """

    model_config = {"arbitrary_types_allowed": True}

    # 基础控制字段
    round: int = 0
    step: int = 0
    status: str = "running"

    # 任务追踪
    tasks: dict[str, Any] = Field(default_factory=dict)
    task_results: dict[str, Any] = Field(default_factory=dict)

    # 质量验证
    gate_results: dict[str, Any] = Field(default_factory=dict)

    # 信号流 (跨 Agent)
    signals: list[Signal] = Field(default_factory=list)

    # 指标
    metrics: MetricsSnapshot = Field(default_factory=MetricsSnapshot)

    # 底层 channel 存储 (保留, 用于 Channel 系统 API)
    channels: dict[str, Channel[Any]] = Field(default_factory=dict)

    # ============================================================
    # 便捷属性 (Phase 2.1-D 新增)
    # ============================================================

    def get_task(self, task_id: str) -> Any | None:
        """按 ID 读取 Task. 不存在返回 None."""
        return self.tasks.get(task_id)

    def get_signal(self, signal_type: str) -> Signal | None:
        """返回第一个匹配 type 的 Signal. 不存在返回 None."""
        for sig in self.signals:
            if sig.type == signal_type:
                return sig
        return None

    def get_metric(self, name: str, default: float | int | None = None) -> float | int | None:
        """按名读取指标值. 不存在返回 default."""
        return self.metrics.get(name, default)

    # ============================================================
    # Channel 系统 API (Phase 2.1-A 已有, 保留)
    # ============================================================

    def get_channel(self, name: str) -> Any:
        """读取指定 channel 的当前值. 缺失返回 None."""
        ch = self.channels.get(name)
        if ch is None:
            return None
        return ch.get()

    def set_channel(self, name: str, value: Any) -> bool:
        """写入指定 channel. 未知 channel 抛 KeyError(显式错误优于静默失败).

        Returns:
            bool: Channel 是否报告有变化 (对齐 update() 新签名).
        """
        if name not in self.channels:
            raise KeyError(
                f"Channel '{name}' not registered in LoopState. "
                f"Available: {list(self.channels.keys())}"
            )
        return self.channels[name].update([value])

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Pydantic v2 序列化: 自动用 Channel.checkpoint() 替换 Channel 实例.

        这是 Phase 1 审计 PydanticSerializationError 的修复点:
        - 父类 model_dump 会尝试序列化 Channel 对象 → 失败
        - 覆盖后先用 checkpoint() 转 dict, 再 dict-to-dict 序列化

        Phase 2.1-D: 输出包含全部 8 业务字段 + channels (含 checkpoint 值).
        """
        # 排除 channels 字段从父类 dump (Channel 不可被 pydantic 序列化)
        kwargs.setdefault("mode", "json")
        kwargs.setdefault("exclude", {"channels"})
        base = super().model_dump(**kwargs)
        # 手动序列化 channels 为 checkpoint 值
        channels_data: dict[str, Any] = {}
        for name, ch in self.channels.items():
            channels_data[name] = ch.checkpoint()
        base["channels"] = channels_data
        return base


# ============================================================
# 反序列化: checkpoint dict → LoopState (Phase 2.1-D 修复 Phase A)
# ============================================================


def deserialize_loop_state(data: dict[str, Any]) -> LoopState:
    """从 checkpoint dict 重建 LoopState (channels 重建为 Channel 实例).

    这是 SQLiteCheckpointStore.load() 的核心辅助:
    - data 是 JSON 反序列化后的 dict (含 8 业务字段 + channels)
    - 业务字段直接传入 LoopState 构造
    - channels[name] (raw checkpoint 值) → 对应类型 Channel 实例 (调 from_checkpoint)
    - tasks/task_results: 重建 dataclass (Phase 2.1-D: 优先重建为 Task/TaskOutcome,
      无法识别时回退 dict — 兼容旧 schema)

    Channel 类型识别:
    - dict 含 "expected" 字段 → BarrierChannel
    - list → AccumulatingChannel
    - 其他 → LastValueChannel (含 None / dict / str / int)

    Args:
        data: checkpoint dict (含 round/step/status/tasks/channels 等)

    Returns:
        LoopState 实例 (channels 是 Channel 实例, 非 dict)

    Raises:
        ValueError: data 缺关键字段 / channels 结构异常
    """
    # 1. 提取 channels 并重建
    raw_channels = data.get("channels", {})
    if not isinstance(raw_channels, dict):
        raise ValueError(
            f"deserialize_loop_state: 'channels' must be dict, got {type(raw_channels).__name__}"
        )

    rebuilt_channels: dict[str, Channel[Any]] = {}
    for name, value in raw_channels.items():
        ch = _rebuild_channel(name, value)
        rebuilt_channels[name] = ch

    # 2. 重建 tasks (dict → Task 实例)
    rebuilt_tasks: dict[str, Any] = {}
    raw_tasks = data.get("tasks", {})
    if isinstance(raw_tasks, dict):
        for tid, tval in raw_tasks.items():
            rebuilt_tasks[tid] = _rebuild_task(tval)

    # 3. 重建 task_results (dict → TaskOutcome 实例)
    rebuilt_results: dict[str, Any] = {}
    raw_results = data.get("task_results", {})
    if isinstance(raw_results, dict):
        for tid, rval in raw_results.items():
            rebuilt_results[tid] = _rebuild_task_outcome(rval)

    # 4. 构造 LoopState (复制业务字段, 不包括 channels/tasks/task_results)
    business_fields = {
        k: v
        for k, v in data.items()
        if k not in ("channels", "tasks", "task_results")
    }
    business_fields["tasks"] = rebuilt_tasks
    business_fields["task_results"] = rebuilt_results

    return LoopState(channels=rebuilt_channels, **business_fields)


def _rebuild_channel(name: str, value: Any) -> Channel[Any]:
    """从 checkpoint value 重建 Channel 实例.

    类型识别:
    - dict 含 "expected" 字段 → BarrierChannel (构造需 expected)
    - list → AccumulatingChannel
    - 其他 → LastValueChannel (None / str / int / dict 都合法)
    """
    if isinstance(value, dict) and "expected" in value:
        # BarrierChannel: 必须从 value 拿 expected (构造需)
        ch = BarrierChannel(name, expected=value["expected"])
        ch.from_checkpoint(value)
        return ch
    elif isinstance(value, list):
        ch: AccumulatingChannel[Any] = AccumulatingChannel(name)
        ch.from_checkpoint(value)
        return ch
    else:
        ch = LastValueChannel(name)
        ch.from_checkpoint(value)
        return ch


def _rebuild_task(value: Any) -> Any:
    """从 dict 重建 Task 实例 (若可识别).

    Args:
        value: dict 含 task 字段, 或非 dict (回退直接返回)

    Returns:
        Task 实例 (识别成功) 或原始 value (回退)
    """
    if not isinstance(value, dict):
        return value
    # 避免循环依赖: 延迟导入
    from auto_engineering.loop.plan import Task, TaskValidation

    # 过滤: 只保留 Task 字段 (避免 Pydantic 报警)
    field_names = set(Task.__dataclass_fields__)
    kwargs = {k: v for k, v in value.items() if k in field_names}

    # 重建 validation (TaskValidation 是 dataclass)
    if "validation" in kwargs and isinstance(kwargs["validation"], dict):
        val_field_names = set(TaskValidation.__dataclass_fields__)
        val_kwargs = {
            k: v for k, v in kwargs["validation"].items() if k in val_field_names
        }
        kwargs["validation"] = TaskValidation(**val_kwargs)

    # target_files 需要 frozenset
    if "target_files" in kwargs and isinstance(kwargs["target_files"], list):
        kwargs["target_files"] = frozenset(kwargs["target_files"])

    try:
        return Task(**kwargs)
    except Exception:
        # 字段不兼容 (旧 schema) → 回退 dict
        return value


def _rebuild_task_outcome(value: Any) -> Any:
    """从 dict 重建 TaskOutcome 实例 (若可识别).

    Args:
        value: dict 含 outcome 字段, 或非 dict (回退直接返回)

    Returns:
        TaskOutcome 实例 (识别成功) 或原始 value (回退)
    """
    if not isinstance(value, dict):
        return value
    # 避免循环依赖: 延迟导入
    from auto_engineering.loop.round import TaskOutcome

    field_names = set(TaskOutcome.__dataclass_fields__)
    kwargs = {k: v for k, v in value.items() if k in field_names}
    try:
        return TaskOutcome(**kwargs)
    except Exception:
        return value


__all__ = [
    "AccumulatingChannel",
    "BarrierChannel",
    "BarrierState",
    "Channel",
    "GateVerdict",
    "LastValueChannel",
    "LoopState",
    "MetricsSnapshot",
    "Signal",
    "deserialize_loop_state",
]