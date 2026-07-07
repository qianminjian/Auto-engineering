"""v2.1 Phase D 测试 — 修复 Phase A load() 半完成 + 集成验证.

设计来源: design/v2.0-Design-Loop.md §3.4 Checkpoint 持久化
BEACON 决策 17: SQLiteCheckpointStore.load() 必须返回 LoopState 实例 + Channel 实例 (完整闭环)

Phase A 已修复 save() 不抛异常, 但 load() 半完成:
- 实际: store.load(id).state 返回 dict (JSON 反序列化结果)
- 期望: store.load(id).state 返回 CheckpointEnvelope 实例, channels 是 Channel 实例
    (v2.3 P0-A: 原 LoopState 重命名为 CheckpointEnvelope)

实现路径 (当前):
    store.load() → _row_to_checkpoint() → deserialize_state() →
    → deserialize_loop_state() (in loop/state/checkpoint_envelope.py) →
    → _rebuild_channel() (per channel) → Channel 实例

测试约束 (遵循 pytest-memory-management.md):
- 单文件 pytest --no-cov --timeout=60
- 测试严禁虚化: 必须真实 save → load → 验证返回类型
"""

from __future__ import annotations

from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
from auto_engineering.loop.state import (
    CheckpointEnvelope,
)
from auto_engineering.loop.checkpoint._serialization import (
    AccumulatingChannel,
    BarrierChannel,
    LastValueChannel,
)


def test_load_returns_loopstate_instance_not_dict():
    """SQLiteCheckpointStore.load(cp_id).state 必须返回 CheckpointEnvelope 实例, 不是 dict.

    Phase A 缺陷修复: 旧实现返回 dict, 集成代码需手动重建.
    新实现: load() 直接返回 CheckpointEnvelope, channels 已是 Channel 实例.
    (v2.3 P0-A: 原 LoopState 重命名为 CheckpointEnvelope)
    """
    store = SQLiteCheckpointStore(":memory:")
    state = CheckpointEnvelope(
        round=1,
        step=2,
        status="running",
        channels={"plan": LastValueChannel("plan")},
    )
    state.channels["plan"].update(["hello"])

    cp_id = store.save(state, round=1)
    loaded = store.load(cp_id)

    assert isinstance(loaded.state, CheckpointEnvelope), (
        f"load() returns {type(loaded.state).__name__}, expected CheckpointEnvelope"
    )


def test_load_returns_channels_as_channel_instances():
    """SQLiteCheckpointStore.load() 后 channels[name] 必须是 Channel 实例.

    Phase A 缺陷修复: 旧实现 channels 是 dict (raw checkpoint 值),
    集成代码需手动遍历重建. 新实现直接给出 Channel 实例.
    """
    store = SQLiteCheckpointStore(":memory:")
    state = CheckpointEnvelope(
        round=1,
        channels={
            "plan": LastValueChannel("plan"),
            "logs": AccumulatingChannel("logs"),
            "sync": BarrierChannel("sync", expected=2),
        },
    )
    state.channels["plan"].update(["v1"])
    state.channels["logs"].update(["log-1"])
    state.channels["logs"].update(["log-2"])
    state.channels["sync"].update([None])
    state.channels["sync"].update([None])

    cp_id = store.save(state, round=1)
    loaded = store.load(cp_id)

    assert isinstance(loaded.state, CheckpointEnvelope)
    # 每个 channel 是对应类型实例 (非 dict)
    assert isinstance(loaded.state.channels["plan"], LastValueChannel)
    assert isinstance(loaded.state.channels["logs"], AccumulatingChannel)
    assert isinstance(loaded.state.channels["sync"], BarrierChannel)


def test_load_restores_channel_values_via_get():
    """load 后 channels[name].get() 返回保存时的真值 (非 None/空)."""
    store = SQLiteCheckpointStore(":memory:")
    state = CheckpointEnvelope(
        round=1,
        channels={
            "plan": LastValueChannel("plan"),
            "logs": AccumulatingChannel("logs"),
            "sync": BarrierChannel("sync", expected=2),
        },
    )
    state.channels["plan"].update(["test plan v3"])
    state.channels["logs"].update(["event-A"])
    state.channels["sync"].update([None])

    cp_id = store.save(state, round=1)
    loaded = store.load(cp_id)

    # 关键: get() 返回保存值, 不是 None
    assert loaded.state.channels["plan"].get() == "test plan v3"
    assert loaded.state.channels["logs"].get() == ["event-A"]
    assert loaded.state.channels["sync"].get() == 1


def test_load_restores_loopstate_business_fields():
    """load 后 CheckpointEnvelope.round/step/status/tasks 等字段正确恢复."""
    store = SQLiteCheckpointStore(":memory:")

    tasks_dict = {
        "t1": {
            "id": "t1",
            "title": "Test Task",
            "description": "d",
            "expected_output": "json",
            "role": "developer",
            "agent_type": "developer",
            "depends_on": [],
            "target_files": [],
            "estimated_minutes": 30,
            "status": "pending",
        },
    }
    state = CheckpointEnvelope(
        round=2,
        step=3,
        status="running",
        tasks=tasks_dict,
    )

    cp_id = store.save(state, round=2)
    loaded = store.load(cp_id)

    assert loaded.state.round == 2
    assert loaded.state.step == 3
    assert loaded.state.status == "running"


def test_load_then_update_works_correctly():
    """load 后修改 channel 不影响原状态 (独立副本语义)."""
    store = SQLiteCheckpointStore(":memory:")
    state = CheckpointEnvelope(channels={"plan": LastValueChannel("plan")})
    state.channels["plan"].update(["original"])

    cp_id = store.save(state, round=1)
    loaded = store.load(cp_id)

    # 修改 loaded 不影响原 state
    loaded.state.channels["plan"].update(["modified"])
    assert state.channels["plan"].get() == "original"
    assert loaded.state.channels["plan"].get() == "modified"


def test_load_preserves_barrier_expected_field():
    """load 后 BarrierChannel.expected 正确恢复 (否则 wait() 行为不对)."""
    store = SQLiteCheckpointStore(":memory:")
    state = CheckpointEnvelope(
        channels={"sync": BarrierChannel("sync", expected=5)},
    )
    state.channels["sync"].update([None])  # count=1, expected=5
    state.channels["sync"].update([None])  # count=2

    cp_id = store.save(state, round=1)
    loaded = store.load(cp_id)

    barrier = loaded.state.channels["sync"]
    assert isinstance(barrier, BarrierChannel)
    # count 是 2, expected 是 5 (load 后从 checkpoint 恢复)
    assert barrier.get() == 2
    assert barrier.empty() is True  # 未达 expected


def test_load_empty_state_returns_loopstate_with_defaults():
    """空 CheckpointEnvelope (无 channels) load 后仍是 CheckpointEnvelope 实例."""
    store = SQLiteCheckpointStore(":memory:")
    state = CheckpointEnvelope(round=1)

    cp_id = store.save(state, round=1)
    loaded = store.load(cp_id)

    assert isinstance(loaded.state, CheckpointEnvelope)
    assert loaded.state.channels == {}


def test_load_latest_returns_loopstate_instance():
    """load_latest().state 也必须是 CheckpointEnvelope 实例."""
    store = SQLiteCheckpointStore(":memory:")
    state = CheckpointEnvelope(
        round=1,
        channels={"plan": LastValueChannel("plan")},
    )
    state.channels["plan"].update(["latest"])
    store.save(state, round=1)

    latest = store.load_latest()
    assert latest is not None
    assert isinstance(latest.state, CheckpointEnvelope)
    assert latest.state.channels["plan"].get() == "latest"