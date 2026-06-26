"""v2.1 Phase D 测试 — LoopState 8 字段补全 + Task 10 字段补全 + Plan.validate contract.

设计来源: design/v2.0-Design-Loop.md §3.1-3.2
v2.1 Phase D: 补齐设计文档字段(实际代码与设计对齐).

关键点:
- LoopState 字段: round/step/tasks/task_results/gate_results/signals/metrics/status/channels
- Task 字段: title/expected_output/role/context_files/validation/output (新增)
- Plan.validate: 校验 expected_output 非空 + title 非空 + role 在枚举中
- tests/test_loop_state_v2.py: 已有 Phase A 序列化测试, 本文件独立测试 Phase D 字段补全

测试约束 (遵循 pytest-memory-management.md):
- 单文件 pytest --no-cov --timeout=60
- 测试严禁虚化 (Phase A 教训): 必须真实集成 SQLiteCheckpointStore
"""

from __future__ import annotations

import pytest

from auto_engineering.loop.plan import (
    Plan,
    Task,
    TaskStatus,
)
from auto_engineering.loop.round import TaskOutcome
from auto_engineering.loop.state import (
    LastValueChannel,
    LoopState,
)

# ============================================================
# D.1 LoopState 8 字段测试
# ============================================================


def test_loop_state_default_round_is_zero():
    """LoopState.round 默认 0 (启动时未跑任何轮)."""
    state = LoopState()
    assert state.round == 0


def test_loop_state_default_step_is_zero():
    """LoopState.step 默认 0 (L1 Inner Loop 起步)."""
    state = LoopState()
    assert state.step == 0


def test_loop_state_default_status_is_running():
    """LoopState.status 默认 'running'."""
    state = LoopState()
    assert state.status == "running"


def test_loop_state_default_tasks_is_empty_dict():
    """LoopState.tasks 默认空 dict (没有 task)."""
    state = LoopState()
    assert state.tasks == {}


def test_loop_state_default_task_results_is_empty_dict():
    """LoopState.task_results 默认空 dict."""
    state = LoopState()
    assert state.task_results == {}


def test_loop_state_default_gate_results_is_empty_dict():
    """LoopState.gate_results 默认空 dict."""
    state = LoopState()
    assert state.gate_results == {}


def test_loop_state_default_signals_is_empty_list():
    """LoopState.signals 默认空 list (信号流未触发)."""
    state = LoopState()
    assert state.signals == []


def test_loop_state_default_metrics_is_metrics_snapshot():
    """LoopState.metrics 默认 MetricsSnapshot 实例 (不是 None)."""
    from auto_engineering.loop.state import MetricsSnapshot

    state = LoopState()
    assert isinstance(state.metrics, MetricsSnapshot)


def test_loop_state_default_channels_is_empty_dict():
    """LoopState.channels 默认空 dict (保留为底层 Channel 系统 API)."""
    state = LoopState()
    assert state.channels == {}


def test_loop_state_construct_with_all_8_fields():
    """LoopState 可构造时一次性传入 8 字段."""
    from auto_engineering.loop.state import MetricsSnapshot

    metrics = MetricsSnapshot()
    state = LoopState(
        round=3,
        step=5,
        status="converged",
        tasks={},
        task_results={},
        gate_results={},
        signals=[],
        metrics=metrics,
        channels={"plan": LastValueChannel("plan")},
    )
    assert state.round == 3
    assert state.step == 5
    assert state.status == "converged"
    assert state.channels["plan"].name == "plan"


def test_loop_state_get_task_returns_task_by_id():
    """LoopState.get_task(id) 便捷读取 tasks[id]."""
    task = Task(
        id="t1",
        title="Task 1",
        description="d",
        expected_output="x",
        role="developer",
        target_files=frozenset(),
    )
    state = LoopState(tasks={"t1": task})
    assert state.get_task("t1") is task
    assert state.get_task("nonexistent") is None


def test_loop_state_get_signal_returns_first_signal_of_type():
    """LoopState.get_signal(type) 返回第一个匹配 type 的信号."""
    from auto_engineering.loop.state import Signal

    sig1 = Signal(type="metric.update", payload={"name": "tokens", "value": 100})
    sig2 = Signal(type="task.done", payload={"task_id": "t1"})
    sig3 = Signal(type="metric.update", payload={"name": "errors", "value": 0})
    state = LoopState(signals=[sig1, sig2, sig3])
    result = state.get_signal("metric.update")
    assert result is sig1  # 第一个匹配


def test_loop_state_get_metric_returns_value():
    """LoopState.get_metric(name) 返回 metrics dict 中对应值."""
    state = LoopState()
    state.metrics.values["tokens_used"] = 1500
    assert state.get_metric("tokens_used") == 1500


def test_loop_state_model_dump_includes_all_8_fields():
    """LoopState.model_dump 输出包含 8 字段 + channels."""
    state = LoopState(
        round=2,
        step=4,
        status="running",
        channels={"plan": LastValueChannel("plan")},
    )
    state.channels["plan"].update(["test plan"])

    dumped = state.model_dump(mode="json")
    # 8 个业务字段 + channels (底层存储)
    assert dumped["round"] == 2
    assert dumped["step"] == 4
    assert dumped["status"] == "running"
    assert dumped["tasks"] == {}
    assert dumped["task_results"] == {}
    assert dumped["gate_results"] == {}
    assert dumped["signals"] == []
    assert "metrics" in dumped
    # channels 是 LastValueChannel.checkpoint() 输出
    assert dumped["channels"]["plan"] == "test plan"


# ============================================================
# D.2 Task 10 字段测试
# ============================================================


def test_task_default_title_is_empty_string():
    """Task.title 默认空串 (必须显式赋值才能通过 Plan.validate)."""
    task = Task(
        id="t1",
        title="",
        description="d",
        expected_output="x",
        role="developer",
        target_files=frozenset(),
    )
    assert task.title == ""


def test_task_default_expected_output_is_empty_string():
    """Task.expected_output 默认空串 (必须显式赋值才能通过 Plan.validate)."""
    task = Task(
        id="t1",
        title="T",
        description="d",
        expected_output="",
        role="developer",
        target_files=frozenset(),
    )
    assert task.expected_output == ""


def test_task_default_role_is_developer():
    """Task.role 默认 'developer' (向后兼容旧调用)."""
    task = Task(
        id="t1",
        title="T",
        description="d",
        expected_output="x",
        role="developer",
        target_files=frozenset(),
    )
    assert task.role == "developer"


def test_task_default_context_files_is_empty_list():
    """Task.context_files 默认空 list."""
    task = Task(
        id="t1",
        title="T",
        description="d",
        expected_output="x",
        role="developer",
        target_files=frozenset(),
    )
    assert task.context_files == []


def test_task_default_validation_is_none():
    """Task.validation 默认 None (可选验证规则)."""
    task = Task(
        id="t1",
        title="T",
        description="d",
        expected_output="x",
        role="developer",
        target_files=frozenset(),
    )
    assert task.validation is None


def test_task_default_output_is_none():
    """Task.output 默认 None (执行后才有)."""
    task = Task(
        id="t1",
        title="T",
        description="d",
        expected_output="x",
        role="developer",
        target_files=frozenset(),
    )
    assert task.output is None


def test_task_construct_with_all_10_fields():
    """Task 可一次性构造 10 字段 (含 title/expected_output/role/context_files/validation/output)."""
    from auto_engineering.loop.plan import TaskValidation

    validation = TaskValidation(required_files=["out.py"])
    outcome = TaskOutcome(task_id="t1", status="completed", output="done")
    task = Task(
        id="t1",
        title="实现 X 模块",
        description="详细描述",
        expected_output="src/x.py 含 class X",
        role="developer",
        target_files=frozenset({"src/x.py"}),
        context_files=["docs/spec.md"],
        validation=validation,
        deps=["t0"],
        estimated_minutes=45,
        status=TaskStatus.COMPLETED,
        output=outcome,
        agent_type="developer",
        depends_on=["t0"],
    )
    assert task.title == "实现 X 模块"
    assert task.expected_output == "src/x.py 含 class X"
    assert task.role == "developer"
    assert task.context_files == ["docs/spec.md"]
    assert task.validation is validation
    assert task.output is outcome
    # 保留旧字段
    assert task.agent_type == "developer"
    assert task.depends_on == ["t0"]


# ============================================================
# D.3 Plan.validate 加 contract 校验
# ============================================================


def test_plan_validate_accepts_task_with_title_and_expected_output():
    """Plan.validate 接受 title/expected_output/role 都正确的 task."""
    tasks = [
        Task(
            id="t1",
            title="T1 Title",
            description="d",
            expected_output="output spec",
            role="developer",
            target_files=frozenset({"src/a.py"}),
        ),
        Task(
            id="t2",
            title="T2 Title",
            description="d",
            expected_output="output spec 2",
            role="critic",
            target_files=frozenset({"src/b.py"}),
        ),
    ]
    plan = Plan(tasks=tasks)
    plan.validate()  # 不抛


def test_plan_validate_rejects_empty_title():
    """Plan.validate 拒绝 title 为空的 task."""
    tasks = [
        Task(
            id="t1",
            title="",
            description="d",
            expected_output="x",
            role="developer",
            target_files=frozenset({"src/a.py"}),
        ),
    ]
    plan = Plan(tasks=tasks)
    with pytest.raises(ValueError, match=r"[Tt]itle|empty"):
        plan.validate()


def test_plan_validate_rejects_empty_expected_output():
    """Plan.validate 拒绝 expected_output 为空的 task."""
    tasks = [
        Task(
            id="t1",
            title="T1",
            description="d",
            expected_output="",
            role="developer",
            target_files=frozenset({"src/a.py"}),
        ),
    ]
    plan = Plan(tasks=tasks)
    with pytest.raises(ValueError, match=r"expected_output|empty"):
        plan.validate()


def test_plan_validate_rejects_invalid_role():
    """Plan.validate 拒绝 role 不在枚举中的 task."""
    tasks = [
        Task(
            id="t1",
            title="T1",
            description="d",
            expected_output="x",
            role="invalid-role",  # 不在 developer/critic/reviewer/architect
            target_files=frozenset({"src/a.py"}),
        ),
    ]
    plan = Plan(tasks=tasks)
    with pytest.raises(ValueError, match=r"[Rr]ole|invalid"):
        plan.validate()


def test_plan_validate_accepts_all_valid_roles():
    """Plan.validate 接受所有 4 个合法 role 值."""
    for role in ("developer", "critic", "reviewer", "architect"):
        tasks = [
            Task(
                id="t1",
                title="T1",
                description="d",
                expected_output="x",
                role=role,
                target_files=frozenset({"src/a.py"}),
            ),
        ]
        plan = Plan(tasks=tasks)
        plan.validate()  # 不抛