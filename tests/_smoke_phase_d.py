"""Phase D runtime smoke — 验证端到端 save→load→Channel 实例化.

执行: .venv/bin/python -c 'from tests._smoke_phase_d import main; main()'
成功 → print "Phase D runtime smoke PASS" + return 0
失败 → raise + return non-zero

测试严禁虚化: 真实集成 SQLiteCheckpointStore + LoopState + Channel.
"""

from __future__ import annotations

from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
from auto_engineering.loop.plan import Task
from auto_engineering.loop.state import (
    AccumulatingChannel,
    BarrierChannel,
    LastValueChannel,
    LoopState,
)


def main() -> int:
    store = SQLiteCheckpointStore(":memory:")
    state = LoopState(round=1, step=3, status="running")
    state.channels = {
        "plan": LastValueChannel("plan"),
        "logs": AccumulatingChannel("logs"),
        "sync": BarrierChannel("sync", expected=2),
    }
    state.channels["plan"].update("test plan v3")
    state.channels["logs"].update("event-A")
    state.channels["sync"].update()

    tasks = {
        "t1": Task(
            id="t1",
            title="Test Task",
            description="d",
            expected_output="json",
            role="developer",
            agent_type="developer",
            target_files=frozenset(),
        ),
    }
    state.tasks = tasks

    cp_id = store.save(state, round=1)
    loaded = store.load(cp_id)

    # 关键断言: load() 返回 LoopState 实例 + Channel 实例
    assert isinstance(loaded.state, LoopState), (
        f"load() returns {type(loaded.state)}, expected LoopState"
    )
    assert isinstance(loaded.state.channels["plan"], LastValueChannel), (
        f"channels[plan] is {type(loaded.state.channels['plan'])}"
    )
    assert loaded.state.channels["plan"].get() == "test plan v3"
    assert loaded.state.channels["logs"].get() == ["event-A"]
    assert loaded.state.channels["sync"].get() == 1
    assert loaded.state.round == 1
    assert loaded.state.step == 3
    assert loaded.state.tasks["t1"].title == "Test Task"
    print("Phase A load() + Phase D fields runtime smoke PASS")
    return 0