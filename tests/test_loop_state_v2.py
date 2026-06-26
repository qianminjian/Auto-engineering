"""v2.0 Channel 系统 + LoopState 容器测试.

Channel 类型语义(参考 design/v2.0-Analysis-Loop.md §4.4):
- LastValueChannel[T]: 单写,后续覆盖(Plan 状态、Review 结论)
- AccumulatingChannel[T]: 多写,append 列表(Task 完成列表、Gate 结果汇总)
- BarrierChannel: 等待所有 Agent 完成(asyncio.Event,多 Agent 同步点)

本文件独立于 v1.1 tests/test_loop_state.py(后者测试 engine.state.LoopState dataclass).
"""

import asyncio

import pytest

from auto_engineering.loop.state import (
    AccumulatingChannel,
    BarrierChannel,
    Channel,
    LastValueChannel,
    LoopState,
)

# ============================================================
# LastValueChannel — 单写覆盖语义
# ============================================================


def test_last_value_channel_default_none():
    """新创建的 LastValueChannel 应为 None."""
    ch: LastValueChannel[str] = LastValueChannel("plan")
    assert ch.get() is None


def test_last_value_channel_set_overwrites():
    """LastValueChannel.set() 覆盖已有值."""
    ch: LastValueChannel[str] = LastValueChannel("plan")
    ch.set("first")
    assert ch.get() == "first"
    ch.set("second")
    assert ch.get() == "second"


def test_last_value_channel_update_returns_value():
    """update() 写入并返回新值(链式调用友好)."""
    ch: LastValueChannel[int] = LastValueChannel("count")
    result = ch.update(42)
    assert result == 42
    assert ch.get() == 42


def test_last_value_channel_empty():
    """LastValueChannel.empty() 在未写入时返回 True."""
    ch: LastValueChannel[str] = LastValueChannel("x")
    assert ch.empty() is True
    ch.set("hello")
    assert ch.empty() is False


# ============================================================
# AccumulatingChannel — 多写 append 语义
# ============================================================


def test_accumulating_channel_default_empty_list():
    """新创建的 AccumulatingChannel 应为空列表."""
    ch: AccumulatingChannel[str] = AccumulatingChannel("findings")
    assert ch.get() == []


def test_accumulating_channel_append_multiple():
    """多次 update 应按顺序追加."""
    ch: AccumulatingChannel[int] = AccumulatingChannel("results")
    ch.update(1)
    ch.update(2)
    ch.update(3)
    assert ch.get() == [1, 2, 3]


def test_accumulating_channel_initial_values():
    """AccumulatingChannel 可指定初始值列表."""
    initial = ["a", "b"]
    ch: AccumulatingChannel[str] = AccumulatingChannel("logs", initial=initial)
    assert ch.get() == ["a", "b"]
    ch.update("c")
    assert ch.get() == ["a", "b", "c"]


def test_accumulating_channel_empty():
    """AccumulatingChannel.empty() 在列表为空时返回 True."""
    ch: AccumulatingChannel[str] = AccumulatingChannel("x")
    assert ch.empty() is True
    ch.update("item")
    assert ch.empty() is False


# ============================================================
# BarrierChannel — 同步点
# ============================================================


@pytest.mark.asyncio
async def test_barrier_channel_starts_unset():
    """BarrierChannel 创建后 wait() 阻塞直到达到 expected."""
    ch: BarrierChannel = BarrierChannel("gate", expected=3)
    assert ch.empty() is True
    # 未达 expected → wait_for 应超时
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ch.wait(), timeout=0.1)


@pytest.mark.asyncio
async def test_barrier_channel_complete_unblocks_waiters():
    """达到 expected 数量后 wait() 返回."""
    ch: BarrierChannel = BarrierChannel("gate", expected=3)
    ch.update("writer-1")
    ch.update("writer-2")
    # 还差 1,应阻塞
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(ch.wait(), timeout=0.1)
    # 第 3 个达到,wait() 应立即返回
    ch.update("writer-3")
    await asyncio.wait_for(ch.wait(), timeout=0.1)
    assert ch.empty() is False


@pytest.mark.asyncio
async def test_barrier_channel_expected_zero_already_complete():
    """expected=0 时 wait() 立即返回(已完成的特殊语义)."""
    ch: BarrierChannel = BarrierChannel("instant", expected=0)
    await asyncio.wait_for(ch.wait(), timeout=0.1)
    assert ch.empty() is False


# ============================================================
# Channel 基类 — 抽象接口
# ============================================================


def test_channel_is_abstract():
    """Channel 是抽象类,不能直接实例化."""
    with pytest.raises(TypeError):
        Channel("x")  # type: ignore[abstract]


def test_channel_subclass_must_implement_methods():
    """不实现抽象方法的子类不能实例化."""
    class BrokenChannel(Channel[int]):
        pass

    with pytest.raises(TypeError):
        BrokenChannel("x")  # type: ignore[abstract]


# ============================================================
# LoopState — Pydantic 容器
# ============================================================


def test_loop_state_contains_channels_dict():
    """LoopState 初始化时 channels 为 dict[str, Channel]."""
    state = LoopState(
        channels={
            "plan": LastValueChannel("plan"),
            "results": AccumulatingChannel("results"),
        }
    )
    assert "plan" in state.channels
    assert "results" in state.channels


def test_loop_state_get_channel_value():
    """LoopState.get_channel(name) 返回该 channel 当前值."""
    state = LoopState(channels={"plan": LastValueChannel("plan")})
    state.channels["plan"].set("hello")
    assert state.get_channel("plan") == "hello"


def test_loop_state_get_missing_channel_returns_none():
    """get_channel 缺失字段返回 None,不抛异常."""
    state = LoopState()
    assert state.get_channel("nonexistent") is None


def test_loop_state_set_channel_value():
    """LoopState.set_channel(name, value) 写入对应 channel."""
    state = LoopState(channels={"verdict": LastValueChannel("verdict")})
    state.set_channel("verdict", "APPROVE")
    assert state.channels["verdict"].get() == "APPROVE"


def test_loop_state_set_channel_missing_raises():
    """set_channel 对未知 channel 抛 KeyError(显式错误优于静默失败)."""
    state = LoopState()
    with pytest.raises(KeyError):
        state.set_channel("nonexistent", "value")


def test_loop_state_mixed_channel_types():
    """LoopState 同时持有 3 种 channel 类型,各自语义独立."""
    state = LoopState(
        channels={
            "plan": LastValueChannel("plan"),
            "findings": AccumulatingChannel("findings"),
            "gate": BarrierChannel("gate", expected=2),
        }
    )

    # LastValue 覆盖
    state.set_channel("plan", "v1")
    state.set_channel("plan", "v2")
    assert state.get_channel("plan") == "v2"

    # Accumulating 追加
    state.channels["findings"].update("finding-1")
    state.channels["findings"].update("finding-2")
    assert state.get_channel("findings") == ["finding-1", "finding-2"]

    # Barrier 等待
    state.channels["gate"].update("agent-1")
    assert state.channels["gate"].empty() is True
    state.channels["gate"].update("agent-2")
    assert state.channels["gate"].empty() is False


# ============================================================
# 并发场景 — AccumulatingChannel 多写
# ============================================================


@pytest.mark.asyncio
async def test_accumulating_channel_concurrent_writes():
    """5 个 asyncio task 并发 update AccumulatingChannel,顺序可能不同但全部保留."""
    ch: AccumulatingChannel[int] = AccumulatingChannel("concurrent")

    async def writer(idx: int) -> None:
        await asyncio.sleep(0.001 * idx)  # 模拟交错
        ch.update(idx)

    await asyncio.gather(*[writer(i) for i in range(5)])

    result = ch.get()
    assert sorted(result) == [0, 1, 2, 3, 4]
    assert len(result) == 5


@pytest.mark.asyncio
async def test_barrier_channel_concurrent_waiters():
    """3 个 writer 并发 update BarrierChannel,所有 waiter 同步解除阻塞."""
    barrier: BarrierChannel = BarrierChannel("sync", expected=3)

    async def writer(name: str, delay: float) -> None:
        await asyncio.sleep(delay)
        barrier.update(name)

    async def observer() -> None:
        await barrier.wait()

    # 启动 1 个 observer + 3 个 writer
    await asyncio.gather(
        observer(),
        writer("a", 0.01),
        writer("b", 0.02),
        writer("c", 0.03),
        return_exceptions=False,
    )
    assert barrier.empty() is False


# ============================================================
# Channel 序列化 (Phase 2.1-A)
# LangGraph 对齐 API: copy / checkpoint / from_checkpoint
# 设计: auto_engineering/loop/state.py Channel 三件套
# 关键: Channel 子类必须可 JSON 序列化(替换 asyncio.Event 等不可序列化状态)
# ============================================================


# --- LastValueChannel 序列化 ---


def test_last_value_channel_checkpoint_default_none():
    """LastValueChannel.checkpoint() 在未写入时返回 None(JSON 可序列化)."""
    ch: LastValueChannel[str] = LastValueChannel("plan")
    assert ch.checkpoint() is None
    # None 必须可 JSON 序列化 (核心: 不能抛异常)
    import json
    assert json.dumps(ch.checkpoint()) == "null"


def test_last_value_channel_checkpoint_after_set():
    """LastValueChannel.checkpoint() 写入后返回当前值."""
    ch: LastValueChannel[dict] = LastValueChannel("plan")
    ch.set({"phase": "design", "step": 2})
    cp = ch.checkpoint()
    assert cp == {"phase": "design", "step": 2}
    # 必须可 JSON 序列化(这是序列化 API 的核心约束)
    import json
    json.dumps(cp)


def test_last_value_channel_from_checkpoint_restores():
    """LastValueChannel.from_checkpoint(value) 恢复 _value."""
    ch: LastValueChannel[str] = LastValueChannel("plan")
    ch.from_checkpoint("restored-value")
    assert ch.get() == "restored-value"
    # 再覆盖一次,验证 from_checkpoint 写入后正常 update 仍生效
    ch.set("new-value")
    assert ch.get() == "new-value"


def test_last_value_channel_from_checkpoint_none():
    """LastValueChannel.from_checkpoint(None) 重置为未写入状态."""
    ch: LastValueChannel[str] = LastValueChannel("plan")
    ch.set("original")
    ch.from_checkpoint(None)
    assert ch.get() is None
    assert ch.empty() is True


def test_last_value_channel_copy_independent_state():
    """LastValueChannel.copy() 返回新实例,修改副本不影响原对象."""
    original: LastValueChannel[str] = LastValueChannel("plan")
    original.set("original-value")
    copy = original.copy()
    # 副本必须有相同状态
    assert copy.get() == "original-value"
    assert copy.name == "plan"
    # 但修改副本不影响原对象
    copy.set("modified-in-copy")
    assert original.get() == "original-value"
    assert copy.get() == "modified-in-copy"


# --- AccumulatingChannel 序列化 ---


def test_accumulating_channel_checkpoint_empty():
    """AccumulatingChannel.checkpoint() 空列表时返回 []."""
    ch: AccumulatingChannel[str] = AccumulatingChannel("logs")
    cp = ch.checkpoint()
    assert cp == []
    import json
    assert json.dumps(cp) == "[]"


def test_accumulating_channel_checkpoint_after_appends():
    """AccumulatingChannel.checkpoint() 返回 values 列表的拷贝."""
    ch: AccumulatingChannel[str] = AccumulatingChannel("logs")
    ch.update("a")
    ch.update("b")
    ch.update("c")
    cp = ch.checkpoint()
    assert cp == ["a", "b", "c"]
    # 副本修改不影响原 Channel
    cp.append("hacked")
    assert ch.get() == ["a", "b", "c"]


def test_accumulating_channel_from_checkpoint_restores():
    """AccumulatingChannel.from_checkpoint(values) 恢复 _values 列表."""
    ch: AccumulatingChannel[str] = AccumulatingChannel("logs")
    ch.from_checkpoint(["x", "y", "z"])
    assert ch.get() == ["x", "y", "z"]
    # from_checkpoint 后 update 应追加
    ch.update("w")
    assert ch.get() == ["x", "y", "z", "w"]


def test_accumulating_channel_from_checkpoint_empty():
    """AccumulatingChannel.from_checkpoint([]) 等同于清空."""
    ch: AccumulatingChannel[str] = AccumulatingChannel("logs")
    ch.update("original")
    ch.from_checkpoint([])
    assert ch.get() == []
    assert ch.empty() is True


def test_accumulating_channel_copy_independent_state():
    """AccumulatingChannel.copy() 深拷贝 values,修改副本不影响原对象."""
    original: AccumulatingChannel[str] = AccumulatingChannel("logs")
    original.update("a")
    original.update("b")
    copy = original.copy()
    # 副本有相同内容
    assert copy.get() == ["a", "b"]
    assert copy.name == "logs"
    # 修改副本(append)不影响原对象
    copy.update("c")
    assert original.get() == ["a", "b"]
    assert copy.get() == ["a", "b", "c"]


# --- BarrierChannel 序列化 (重构: 内部状态 JSON 友好) ---


def test_barrier_channel_checkpoint_unmet():
    """BarrierChannel.checkpoint() 未达 expected 时返回 state JSON."""
    ch: BarrierChannel = BarrierChannel("sync", expected=3)
    cp = ch.checkpoint()
    # cp 必须是 dict-like 包含必要字段,JSON 可序列化
    import json
    serialized = json.dumps(cp)
    restored = json.loads(serialized)
    assert restored["expected"] == 3
    assert restored["count"] == 0
    assert restored["is_set"] is False


def test_barrier_channel_checkpoint_met():
    """BarrierChannel.checkpoint() 达到 expected 时 is_set=True."""
    ch: BarrierChannel = BarrierChannel("sync", expected=2)
    ch.update("writer-1")
    ch.update("writer-2")
    cp = ch.checkpoint()
    import json
    serialized = json.dumps(cp)
    restored = json.loads(serialized)
    assert restored["expected"] == 2
    assert restored["count"] == 2
    assert restored["is_set"] is True


def test_barrier_channel_from_checkpoint_restores_unmet():
    """BarrierChannel.from_checkpoint(state) 恢复未达 expected 状态."""
    ch: BarrierChannel = BarrierChannel("sync", expected=3)
    ch.from_checkpoint({"expected": 3, "count": 1, "is_set": False})
    assert ch.get() == 1
    assert ch.empty() is True


@pytest.mark.asyncio
async def test_barrier_channel_from_checkpoint_restores_met():
    """BarrierChannel.from_checkpoint(state) 恢复已达成状态,wait() 立即返回."""
    ch: BarrierChannel = BarrierChannel("sync", expected=2)
    ch.from_checkpoint({"expected": 2, "count": 2, "is_set": True})
    assert ch.get() == 2
    assert ch.empty() is False
    # wait() 立即返回,不阻塞
    await asyncio.wait_for(ch.wait(), timeout=0.1)


@pytest.mark.asyncio
async def test_barrier_channel_from_checkpoint_resumes_waiters():
    """BarrierChannel.from_checkpoint(is_set=True) 唤醒所有 waiter."""
    ch: BarrierChannel = BarrierChannel("sync", expected=2)

    # 启动 waiter(在事件循环里阻塞)
    async def waiter() -> None:
        await ch.wait()

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)  # 让 waiter 进入 await
    # 模拟 checkpoint 恢复(同步达成)
    ch.from_checkpoint({"expected": 2, "count": 2, "is_set": True})
    # waiter 应被唤醒
    await asyncio.wait_for(task, timeout=0.5)


def test_barrier_channel_copy_independent_state():
    """BarrierChannel.copy() 返回新实例,内部状态独立."""
    original: BarrierChannel = BarrierChannel("sync", expected=3)
    original.update("writer-1")
    copy = original.copy()
    # 副本 state 一致
    assert copy.get() == 1
    assert copy.name == "sync"
    # 修改副本不影响原对象
    copy.update("writer-2")
    assert original.get() == 1
    assert copy.get() == 2


# --- Channel 基类: copy/checkpoint/from_checkpoint 是抽象方法 ---


def test_channel_base_has_serialization_abstract_methods():
    """Channel 基类必须有 copy/checkpoint/from_checkpoint 三个抽象方法."""
    # 不实现新抽象方法的子类不能实例化
    class IncompleteChannel(Channel[int]):
        def get(self):  # type: ignore[override]
            return None

        def update(self, value):  # type: ignore[override]
            return value

        def empty(self):  # type: ignore[override]
            return True

    with pytest.raises(TypeError):
        IncompleteChannel("x")  # type: ignore[abstract]


# --- 集成: SQLiteCheckpointStore 序列化所有 Channel 类型 ---


def test_sqlite_checkpoint_store_saves_loopstate_with_channels():
    """SQLiteCheckpointStore.save(state_with_channels) 不再抛 PydanticSerializationError.

    Phase 1 审计发现的核心 bug:state.channels 含 Channel 实例时 save 抛
    PydanticSerializationError. 修复后 Channel 必须可序列化.
    """
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    store = SQLiteCheckpointStore(":memory:")
    state = LoopState(
        channels={
            "plan": LastValueChannel("plan"),
            "logs": AccumulatingChannel("logs"),
            "sync": BarrierChannel("sync", expected=2),
        }
    )
    # 写入各类型数据
    state.set_channel("plan", {"phase": "design", "step": 1})
    state.channels["logs"].update("log-entry-1")
    state.channels["logs"].update("log-entry-2")
    state.channels["sync"].update("writer-1")
    state.channels["sync"].update("writer-2")

    # 关键断言: 不抛异常
    cp_id = store.save(state, round=1)
    assert cp_id is not None
    assert store.count() == 1


def test_sqlite_checkpoint_store_round_trips_channels():
    """SQLiteCheckpointStore save → load:channels 内容一致.

    真实场景: 重启后从 Checkpoint 恢复,Channel 状态必须能重建.
    Phase 2.1-D 修复: load() 返回 LoopState 实例 (channels 是 Channel 实例),
    通过 .get() 读取真实值.
    """
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    store = SQLiteCheckpointStore(":memory:")
    state = LoopState(
        channels={
            "plan": LastValueChannel("plan"),
            "logs": AccumulatingChannel("logs"),
            "sync": BarrierChannel("sync", expected=2),
        }
    )
    state.set_channel("plan", "expected plan value")
    state.channels["logs"].update("log-1")
    state.channels["logs"].update("log-2")
    state.channels["sync"].update("writer-1")
    state.channels["sync"].update("writer-2")

    cp_id = store.save(state, round=1)

    # 加载并验证(Phase 2.1-D: state 是 LoopState 实例, channels 是 Channel 实例)
    loaded = store.load(cp_id).state
    assert isinstance(loaded, LoopState)
    # LastValueChannel.get() -> raw value
    assert loaded.channels["plan"].get() == "expected plan value"
    # AccumulatingChannel.get() -> list of values
    assert loaded.channels["logs"].get() == ["log-1", "log-2"]
    # BarrierChannel.get() -> count (int)
    assert loaded.channels["sync"].get() == 2
    assert loaded.channels["sync"].empty() is False


def test_checkpoint_round_trip_restores_channels_via_from_checkpoint():
    """端到端:save → load_state_json → from_checkpoint 重建 Channel.

    这是 Loop 引擎恢复检查点时的实际行为:
    1. 加载 JSON dict
    2. 遍历 channels
    3. 调用 channel.from_checkpoint(value) 恢复
    4. 验证 Channel 状态完全恢复

    Phase 2.1-D: load() 直接返回 LoopState 实例 (channels 已是 Channel 实例),
    无需手动 from_checkpoint.
    """
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    store = SQLiteCheckpointStore(":memory:")
    state = LoopState(
        channels={
            "plan": LastValueChannel("plan"),
            "logs": AccumulatingChannel("logs"),
            "sync": BarrierChannel("sync", expected=2),
        }
    )
    state.set_channel("plan", "expected plan value")
    state.channels["logs"].update("log-1")
    state.channels["logs"].update("log-2")
    state.channels["sync"].update("writer-1")
    state.channels["sync"].update("writer-2")

    cp_id = store.save(state, round=1)

    # Phase 2.1-D: load() 直接返回 LoopState, channels 已是 Channel 实例
    loaded = store.load(cp_id).state
    assert isinstance(loaded, LoopState)
    restored_plan = loaded.channels["plan"]
    restored_logs = loaded.channels["logs"]
    restored_sync = loaded.channels["sync"]

    # 验证类型
    assert isinstance(restored_plan, LastValueChannel)
    assert isinstance(restored_logs, AccumulatingChannel)
    assert isinstance(restored_sync, BarrierChannel)

    # 验证状态完全恢复
    assert restored_plan.get() == "expected plan value"
    assert restored_logs.get() == ["log-1", "log-2"]
    assert restored_sync.get() == 2
    assert restored_sync.empty() is False
    # 已达成的 Barrier wait() 立即返回
    import asyncio
    asyncio.run(restored_sync.wait())


# ============================================================
# Phase v2.3-A: Channel.update 对齐 LangGraph BaseChannel
# 设计: update(values: Sequence[T]) -> bool
# - LangGraph BaseChannel.update(values: Sequence[Update]) -> bool (langgraph/channels/base.py:90)
# - LangGraph Topic.update(values: Sequence[Value | list[Value]]) -> bool (langgraph/channels/topic.py:77)
# - 返回 bool 表示是否有变化(用于触发下游)
# ============================================================


import inspect


def test_channel_update_signature_matches_langgraph():
    """Channel.update 签名必须匹配 LangGraph BaseChannel: (values: Sequence[T]) -> bool.

    通过 inspect.signature 验证参数名 'values' 与返回注解 'bool'.
    这是 Phase 1 审计 P0.1 的核心修复点: 原签名是 update(value: T) -> T, 与 LangGraph 不兼容.
    """
    sig = inspect.signature(Channel.update)
    params = list(sig.parameters.keys())
    # 必须有 'self' 和 'values' 两个参数
    assert "values" in params, f"Channel.update must have 'values' param, got {params}"
    # 返回注解必须声明为 bool (Python 3.12+ 会把注解字符串化为 'bool', 比较 value)
    assert sig.return_annotation in (bool, "bool"), (
        f"Channel.update must return bool, got {sig.return_annotation}"
    )


def test_last_value_channel_update_batch_sets_last():
    """LastValueChannel.update([v1, v2, v3]) 后 get() == v3 (最后元素胜出).

    对齐 LangGraph LastValue.update: 序列中最后一个值覆盖.
    """
    ch: LastValueChannel[str] = LastValueChannel("plan")
    ch.update(["a", "b", "c"])
    assert ch.get() == "c"


def test_last_value_channel_update_returns_bool_on_change():
    """LastValueChannel.update 有变化时返回 True (触发下游)."""
    ch: LastValueChannel[str] = LastValueChannel("plan")
    # 从 None → "x" 视为有变化
    result = ch.update(["x"])
    assert result is True
    assert ch.get() == "x"


def test_last_value_channel_update_returns_bool_on_no_change():
    """LastValueChannel.update 重复相同值时返回 False (无变化, 不触发下游).

    对齐 LangGraph LastValue: 仅当序列中最后一个值与当前值不同时返回 True.
    """
    ch: LastValueChannel[str] = LastValueChannel("plan")
    ch.update(["same"])
    # 第二次传入相同的 "same" → 无变化 → 返回 False
    result = ch.update(["same"])
    assert result is False
    assert ch.get() == "same"


def test_last_value_channel_update_empty_sequence():
    """LastValueChannel.update([]) 空序列应不改变状态, 返回 False (无变化).

    对齐 LangGraph: 'If there are no updates, it is called with an empty sequence.'
    """
    ch: LastValueChannel[str] = LastValueChannel("plan")
    ch.update(["initial"])
    result = ch.update([])
    assert result is False
    assert ch.get() == "initial"


def test_accumulating_channel_update_batch_extends():
    """AccumulatingChannel.update([v1, v2, v3]) 批量扩展列表.

    对齐 LangGraph Topic.update: extend 而不是多次 append 调用.
    """
    ch: AccumulatingChannel[str] = AccumulatingChannel("findings")
    ch.update(["x", "y", "z"])
    assert ch.get() == ["x", "y", "z"]


def test_accumulating_channel_update_supports_nested_list():
    """AccumulatingChannel.update([[v1, v2], v3]) 支持嵌套 list 输入 (Topic 特性).

    LangGraph Topic.update(values: Sequence[Value | list[Value]]) 允许单值或 list 值混合.
    参考 langgraph/channels/topic.py:77 + _flatten(values).
    """
    ch: AccumulatingChannel[str] = AccumulatingChannel("findings")
    ch.update([["x", "y"], "z"])
    assert ch.get() == ["x", "y", "z"]


def test_accumulating_channel_update_returns_bool_on_actual_change():
    """AccumulatingChannel.update 非空序列返回 True (有新增), 空序列返回 False."""
    ch: AccumulatingChannel[str] = AccumulatingChannel("findings")
    # 非空 → True
    assert ch.update(["item"]) is True
    # 空 → False
    assert ch.update([]) is False


def test_barrier_channel_update_batch_counts_all():
    """BarrierChannel.update([None, None, None]) 一次调用 +3 (批量计数).

    对齐 LangGraph: 序列长度 = 一次性写入次数 (对齐 Topic 模式).
    """
    ch: BarrierChannel = BarrierChannel("gate", expected=5)
    ch.update([None, None, None])
    assert ch.get() == 3
    assert ch.empty() is True  # 未达 expected


def test_barrier_channel_update_returns_bool_on_reach_expected():
    """BarrierChannel.update 达到 expected 时返回 True."""
    ch: BarrierChannel = BarrierChannel("gate", expected=2)
    # 未达 → False
    assert ch.update([None]) is False
    # 达到 → True
    assert ch.update([None, None]) is True


def test_barrier_channel_update_empty_sequence_no_change():
    """BarrierChannel.update([]) 空序列不改变状态, 返回 False."""
    ch: BarrierChannel = BarrierChannel("gate", expected=2)
    ch.update([None])
    assert ch.update([]) is False
    assert ch.get() == 1