"""v2.0 Checkpoint 数据信封 + 序列化/反序列化.

CheckpointEnvelope (原名 LoopState, v2.3 P0-A 重命名):
    v2.0 Checkpoint 持久化的数据结构 (Pydantic BaseModel).
    仅供 checkpoint 持久化 / migrate (v2.0->v2.0) 使用.
    运行时 Orchestrator 不使用此类型 (走 engine.state.LoopState v2.0 dataclass).
    详见 BEACON.md 决策 23 (Channel 体系归属: checkpoint 专用).

    重命名原因: 消除 "LoopState" 同名双义 -- engine.state.LoopState (v2.0 dataclass,
    运行时生产代码用) vs loop.state.LoopState (v2.0 Pydantic, checkpoint 专用).
    新名 "CheckpointEnvelope" 明确语义: v2.0 Checkpoint 数据信封.

设计文档:
- v2.0-D: 8 个核心字段 + Task 字段补全 + load() 重建 Channel 实例.
- design/v2.0-Design-Loop.md §3.1
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

_logger = logging.getLogger("ae.loop.state.cp")

from auto_engineering.loop.checkpoint._serialization import (
    AccumulatingChannel,
    BarrierChannel,
    Channel,
    LastValueChannel,
)
from auto_engineering.loop.plan import Task, TaskValidation
from auto_engineering.loop.round import TaskOutcome
from auto_engineering.loop.state.metrics import MetricsSnapshot, Signal


class CheckpointEnvelope(BaseModel):
    """v2.0 Checkpoint 数据信封 (v2.0-D 补全字段).

    设计文档 §3.1: 8 个核心字段 + 底层 channels 存储.

    v2.3 P0-A 重命名: 原名 LoopState -> CheckpointEnvelope.
    语义: v2.0 Checkpoint 持久化的数据结构 (Pydantic BaseModel),
    仅供 SQLite checkpoint store + migrate (v2.0->v2.0) 使用.
    运行时 Orchestrator / Runtime / Gates 走 engine.state.LoopState (v2.0 dataclass).

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

    # v2.0-B: channel_versions 跟踪每个 channel 的版本号
    # 借鉴 LangGraph Pregel.channel_versions (pregel/main.py:1140, 1736-1740)
    # 用途: 增量触发 (_get_new_channel_versions diff)
    channel_versions: dict[str, int] = Field(default_factory=dict)

    # ============================================================
    # 便捷属性 (v2.0-D 新增)
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
    # Channel 系统 API (v2.0-A 已有, 保留)
    # ============================================================

    def get_channel(self, name: str) -> Any:
        """读取指定 channel 的当前值. 缺失返回 None."""
        ch = self.channels.get(name)
        if ch is None:
            return None
        return ch.get()

    def set_channel(self, name: str, value: Any) -> bool:
        """写入指定 channel. 未知 channel 抛 KeyError(显式错误优于静默失败).

        v2.0-B: 累加 channel_versions[name] (借鉴 LangGraph Pregel 增量触发).
        - 返回值仍来自 Channel.update(): True 表示有变化
        - 仅当 update() 返回 True 时累加 version (重复值不增)

        v2.5 P2-C-2 并发不变量: 当前 envelope.channels 在 v2.0 架构中
        不在并发路径 (见 channels.py::Channel 文档). 写入由单线程
        负责. 如果未来需要并发写, 加 asyncio.Lock 守护此方法 + 整个
        envelope 修改 (channel_versions 也是共享状态).

        Returns:
            bool: Channel 是否报告有变化 (对齐 update() 新签名).
        """
        if name not in self.channels:
            raise KeyError(
                f"Channel '{name}' not registered in CheckpointEnvelope. "
                f"Available: {list(self.channels.keys())}"
            )
        changed = self.channels[name].update([value])
        if changed:
            self.channel_versions[name] = self.channel_versions.get(name, 0) + 1
        return changed

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Pydantic v2 序列化: 自动用 Channel.checkpoint() 替换 Channel 实例.

        这是 Phase 1 审计 PydanticSerializationError 的修复点:
        - 父类 model_dump 会尝试序列化 Channel 对象 -> 失败
        - 覆盖后先用 checkpoint() 转 dict, 再 dict-to-dict 序列化

        v2.0-D: 输出包含全部 8 业务字段 + channels (含 checkpoint 值).
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
# 反序列化: checkpoint dict -> CheckpointEnvelope (v2.0-D 修复 Phase A)
# ============================================================


def deserialize_loop_state(data: dict[str, Any]) -> CheckpointEnvelope:
    """从 checkpoint dict 重建 CheckpointEnvelope (channels 重建为 Channel 实例).

    这是 SQLiteCheckpointStore.load() 的核心辅助:
    - data 是 JSON 反序列化后的 dict (含 8 业务字段 + channels)
    - 业务字段直接传入 CheckpointEnvelope 构造
    - channels[name] (raw checkpoint 值) -> 对应类型 Channel 实例 (调 from_checkpoint)
    - tasks/task_results: 重建 dataclass (v2.0-D: 优先重建为 Task/TaskOutcome,
      无法识别时回退 dict -- 兼容旧 schema)

    Channel 类型识别:
    - dict 含 "expected" 字段 -> BarrierChannel
    - list -> AccumulatingChannel
    - 其他 -> LastValueChannel (含 None / dict / str / int)

    Args:
        data: checkpoint dict (含 round/step/status/tasks/channels 等)

    Returns:
        CheckpointEnvelope 实例 (channels 是 Channel 实例, 非 dict)

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

    # 2. 重建 tasks (dict -> Task 实例)
    rebuilt_tasks: dict[str, Any] = {}
    raw_tasks = data.get("tasks", {})
    if isinstance(raw_tasks, dict):
        for tid, tval in raw_tasks.items():
            rebuilt_tasks[tid] = _rebuild_task(tval)

    # 3. 重建 task_results (dict -> TaskOutcome 实例)
    rebuilt_results: dict[str, Any] = {}
    raw_results = data.get("task_results", {})
    if isinstance(raw_results, dict):
        for tid, rval in raw_results.items():
            rebuilt_results[tid] = _rebuild_task_outcome(rval)

    # 4. 构造 CheckpointEnvelope (复制业务字段, 不包括 channels/tasks/task_results)
    business_fields = {
        k: v
        for k, v in data.items()
        if k not in ("channels", "tasks", "task_results")
    }
    business_fields["tasks"] = rebuilt_tasks
    business_fields["task_results"] = rebuilt_results

    return CheckpointEnvelope(channels=rebuilt_channels, **business_fields)


def _rebuild_channel(name: str, value: Any) -> Channel[Any]:
    """从 checkpoint value 重建 Channel 实例.

    类型识别:
    - dict 含 "expected" 字段 -> BarrierChannel (构造需 expected)
    - list -> AccumulatingChannel
    - 其他 -> LastValueChannel (None / str / int / dict 都合法)
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
        _logger.debug("Task 重建失败, 回退 dict: %s", exc_info=True)
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
    field_names = set(TaskOutcome.__dataclass_fields__)
    kwargs = {k: v for k, v in value.items() if k in field_names}
    try:
        return TaskOutcome(**kwargs)
    except Exception:
        _logger.debug("TaskOutcome 重建失败, 回退 dict: %s", exc_info=True)
        return value
