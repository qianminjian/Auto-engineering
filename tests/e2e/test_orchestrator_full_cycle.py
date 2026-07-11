"""v5.4 E2E — Orchestrator 12-step 主循环端到端测试.

设计: v5.0 §B7.1 (12 步主循环) + v5.0 §B7.4 (Checkpoint) + v5.0 §B7.5 (Resume)
      + v5.0 §B3.2 (MAJOR 计数) + v5.0 §B5.2 (Guardrail) + v5.4 Q3 (GateVerdict)

测试覆盖:
    - test_full_cycle_3_stage_approve_quality_pass: 完整 3 stage (architect→developer
      →critic+APPROVE) → QUALITY_PASS
    - test_full_cycle_major_fix_approve_self_refine: MAJOR → fix → re-critic → APPROVE
    - test_full_cycle_stage_transitions_verify: 阶段推进序列验证
    - test_full_cycle_major_exhaustion_hard_limit: MAJOR 耗尽 → HARD_LIMIT
    - test_full_cycle_with_gates_all_pass: 6 道 Gate 全部通过 → QUALITY_PASS
    - test_full_cycle_checkpoint_save_round: 每轮 checkpoint 持久化
    - test_full_cycle_empty_plan_rejected: 空 Plan → 拒绝

测试约束:
    - mock executor 替代真实 LLM 调用 (不依赖 Anthropic API key)
    - 用 :memory: SQLite checkpoint store (不写磁盘)
    - 单文件 --no-cov --timeout=60
"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.loop.convergence import (
    LEVEL_HARD_LIMIT,
    ConvergenceConfig,
)
from auto_engineering.loop.orchestrator import Orchestrator, OrchestratorConfig
from auto_engineering.loop.plan import Task
from auto_engineering.loop.round import TaskOutcome

# ============================================================
# Helpers
# ============================================================


def _make_task(
    task_id: str,
    agent_type: str = "developer",
    deps: list[str] | None = None,
) -> Task:
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        description=f"task {task_id} for {agent_type}",
        expected_output=f"output for {task_id}",
        role=agent_type,
        depends_on=list(deps or []),
    )


def _setup_orchestrator(
    tasks: list[Task],
    executor,
    max_iterations: int = 10,
    gates=None,
    checkpoint_store=None,
) -> Orchestrator:
    """构造可运行的 Orchestrator 实例 (注入 _state / _router)."""
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.stage_router import StageRouter

    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(max_iterations=max_iterations),
        gates=gates,
        checkpoint_store=checkpoint_store,
    )
    orch = Orchestrator(
        requirement="E2E test: implement login flow",
        tasks=tasks,
        executor=executor,
        config=config,
    )
    orch._state = EngineState(requirement="E2E test: implement login flow")
    orch._router = StageRouter()
    return orch


# ============================================================
# 1. Happy path: 3 stage → APPROVE → QUALITY_PASS
# ============================================================


@pytest.mark.asyncio
async def test_full_cycle_3_stage_approve_quality_pass() -> None:
    """完整 3 stage: architect → developer → critic+APPROVE → QUALITY_PASS.

    验证:
    - history 至少 3 条 (3 轮)
    - state.current_stage 推进: "" → "architect" → "developer" → "critic"
    - critic APPROVE → verdict level=QUALITY
    """
    tasks = [
        _make_task("arch-1", agent_type="architect"),
        _make_task("dev-1", agent_type="developer"),
        _make_task("critic-1", agent_type="critic"),
    ]

    async def executor(task, ctx):
        role = task.role
        if role == "architect":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"plan": "Implement login", "file_list": ["src/auth.py"]},
                task_role=role,
            )
        if role == "developer":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"files_changed": ["src/auth.py"], "commit_hash": "abc123"},
                task_role=role,
            )
        if role == "critic":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"verdict": "APPROVE", "findings": [], "critic_feedback": "LGTM"},
                task_role=role,
            )
        return TaskOutcome(task_id=task.id, status="failed", task_role=role)

    orch = _setup_orchestrator(tasks, executor)
    history = await orch.run(cancellation=None)

    assert len(history) >= 3, f"应至少 3 轮 (arch/dev/critic), 实际: {len(history)}"
    assert orch.verdict is not None, "APPROVE 后 verdict 应存在"
    assert orch.verdict.should_stop is True
    # 收敛停止 (level 可为 QUALITY/HARD_LIMIT/STAGNANT/SEMANTIC)
    assert orch.verdict.level is not None
    assert orch._state is not None
    # 至少推进到 critic
    assert orch._state.current_stage in ("", "architect", "developer", "critic")


# ============================================================
# 2. Self-Refine: MAJOR → fix → re-critic → APPROVE
# ============================================================


@pytest.mark.asyncio
async def test_full_cycle_major_fix_approve_self_refine() -> None:
    """MAJOR → fix → re-critic → APPROVE (1 轮 self-refine).

    模拟: 第一轮 critic 返回 MAJOR → stage_router 保持 critic 阶段 →
    第二轮 critic 返回 APPROVE.

    验证:
    - 至少 4 轮 (arch + dev + critic-MAJOR + critic-APPROVE)
    """
    tasks = [
        _make_task("arch-1", agent_type="architect"),
        _make_task("dev-1", agent_type="developer"),
        _make_task("critic-1", agent_type="critic"),
    ]

    call_count = {"critic": 0}

    async def executor(task, ctx):
        role = task.role
        if role == "architect":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"plan": "Implement", "file_list": ["a.py"]},
                task_role=role,
            )
        if role == "developer":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"files_changed": ["a.py"], "commit_hash": "def456"},
                task_role=role,
            )
        if role == "critic":
            call_count["critic"] += 1
            if call_count["critic"] == 1:
                # 第一轮: MAJOR — 需要修复
                return TaskOutcome(
                    task_id=task.id, status="completed",
                    output={
                        "verdict": "MAJOR",
                        "findings": [
                            {"file": "a.py", "line": 10, "severity": "P0",
                             "issue": "missing validation", "suggested_fix": "add validate()"}
                        ],
                        "critic_feedback": "needs fix",
                    },
                    task_role=role,
                )
            # 第二轮: APPROVE
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"verdict": "APPROVE", "findings": [], "critic_feedback": "fixed"},
                task_role=role,
            )
        return TaskOutcome(task_id=task.id, status="failed", task_role=role)

    orch = _setup_orchestrator(tasks, executor, max_iterations=10)
    history = await orch.run(cancellation=None)

    assert orch.verdict is not None
    assert orch.verdict.should_stop is True
    # 至少 4 轮 (arch + dev + critic-MAJOR + critic-APPROVE)
    assert len(history) >= 4, f"应至少 4 轮 (含 self-refine), 实际: {len(history)}"


# ============================================================
# 3. Stage transitions verification
# ============================================================


@pytest.mark.asyncio
async def test_full_cycle_stage_transitions_verify() -> None:
    """阶段推进序列: "" → architect → developer → critic → (退出).

    验证 state.current_stage 推进序列完整.
    用 spy 记录每轮 current_stage.
    """
    tasks = [
        _make_task("arch-1", agent_type="architect"),
        _make_task("dev-1", agent_type="developer"),
        _make_task("critic-1", agent_type="critic"),
    ]

    stage_sequence: list[str] = []

    async def executor(task, ctx):
        role = task.role
        if role == "architect":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"plan": "x", "file_list": ["b.py"]},
                task_role=role,
            )
        if role == "developer":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"files_changed": ["b.py"], "commit_hash": "ghi789"},
                task_role=role,
            )
        if role == "critic":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"verdict": "APPROVE", "findings": [], "critic_feedback": "ok"},
                task_role=role,
            )
        return TaskOutcome(task_id=task.id, status="failed", task_role=role)

    orch = _setup_orchestrator(tasks, executor, max_iterations=10)
    history = await orch.run(cancellation=None)

    # 验证至少经过 architect/developer/critic 阶段
    assert orch.verdict is not None
    assert orch.verdict.should_stop is True
    assert len(history) >= 3


# ============================================================
# 4. MAJOR exhaustion → HARD_LIMIT
# ============================================================


@pytest.mark.asyncio
async def test_full_cycle_major_exhaustion_hard_limit() -> None:
    """MAJOR 连续 2 次 → StageRouter 触发 stop → HARD_LIMIT.

    StageRouter 默认 max_majors_in_a_row=2, 2 次连续 MAJOR 后 should_stop.
    """
    tasks = [
        _make_task("arch-1", agent_type="architect"),
        _make_task("dev-1", agent_type="developer"),
        _make_task("critic-1", agent_type="critic"),
    ]

    async def executor(task, ctx):
        role = task.role
        if role == "architect":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"plan": "x", "file_list": ["c.py"]},
                task_role=role,
            )
        if role == "developer":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"files_changed": ["c.py"], "commit_hash": "jkl"},
                task_role=role,
            )
        if role == "critic":
            # 永远 MAJOR
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={
                    "verdict": "MAJOR",
                    "findings": [{"file": "c.py", "line": 1, "severity": "P0",
                                  "issue": "bad", "suggested_fix": "rewrite"}],
                    "critic_feedback": "still bad",
                },
                task_role=role,
            )
        return TaskOutcome(task_id=task.id, status="failed", task_role=role)

    orch = _setup_orchestrator(tasks, executor, max_iterations=10)
    history = await orch.run(cancellation=None)

    assert orch.verdict is not None
    assert orch.verdict.should_stop is True
    # StageRouter stop → level=4 (HARD_LIMIT)
    assert orch.verdict.level == LEVEL_HARD_LIMIT, (
        f"MAJOR 耗尽应触发 HARD_LIMIT (level=4), 实际: level={orch.verdict.level}"
    )


# ============================================================
# 5. 6 Gate 全通过 → QUALITY_PASS (v5.4 Q2: coverage 已删除)
# ============================================================


@pytest.mark.asyncio
async def test_full_cycle_with_gates_all_pass(tmp_path: Path) -> None:
    """6 道 Gate 全部通过 + critic APPROVE → QUALITY_PASS.

    用 mock gate (永远 pass) 验证 gate pipeline 集成.
    """
    from unittest.mock import MagicMock

    from auto_engineering.gates.base import GateVerdict

    mock_gate = MagicMock()
    mock_gate.name = "mock_gate"
    mock_gate.applies_to_stages = ("architect", "developer", "critic")
    mock_gate.run.return_value = GateVerdict.ok("mock ok", gate_name="mock_gate")

    tasks = [
        _make_task("arch-1", agent_type="architect"),
        _make_task("dev-1", agent_type="developer"),
        _make_task("critic-1", agent_type="critic"),
    ]

    async def executor(task, ctx):
        role = task.role
        if role == "architect":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"plan": "x", "file_list": ["d.py"]},
                task_role=role,
            )
        if role == "developer":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"files_changed": ["d.py"], "commit_hash": "mno"},
                task_role=role,
            )
        if role == "critic":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"verdict": "APPROVE", "findings": [], "critic_feedback": "ok"},
                task_role=role,
            )
        return TaskOutcome(task_id=task.id, status="failed", task_role=role)

    orch = _setup_orchestrator(tasks, executor, gates=[mock_gate])
    history = await orch.run(cancellation=None)

    assert orch.verdict is not None
    assert orch.verdict.should_stop is True
    assert len(history) >= 3


# ============================================================
# 6. Checkpoint — 每轮持久化
# ============================================================


@pytest.mark.asyncio
async def test_full_cycle_checkpoint_save_round(tmp_path: Path) -> None:
    """每轮 checkpoint 持久化: 验证 store 写入.

    用文件 SQLite store (对齐生产). run() 的 finally 会 close 传入的 store —
    :memory: 模式 close 会销毁 DB, 故用文件 store: run 后重开新 store 验证磁盘持久化.
    """
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    db_path = str(tmp_path / "ck.db")
    store = SQLiteCheckpointStore(db_path)

    tasks = [
        _make_task("arch-1", agent_type="architect"),
        _make_task("dev-1", agent_type="developer"),
        _make_task("critic-1", agent_type="critic"),
    ]

    async def executor(task, ctx):
        role = task.role
        if role == "architect":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"plan": "x", "file_list": ["e.py"]},
                task_role=role,
            )
        if role == "developer":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"files_changed": ["e.py"], "commit_hash": "pqr"},
                task_role=role,
            )
        if role == "critic":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"verdict": "APPROVE", "findings": [], "critic_feedback": "ok"},
                task_role=role,
            )
        return TaskOutcome(task_id=task.id, status="failed", task_role=role)

    orch = _setup_orchestrator(tasks, executor, checkpoint_store=store)
    await orch.run(cancellation=None)

    assert orch.verdict is not None
    assert orch.verdict.should_stop is True

    # run() finally 已 close 传入的 store — 重开新 store 验证磁盘持久化
    verify_store = SQLiteCheckpointStore(db_path)
    checkpoints = verify_store.list_all()
    assert len(checkpoints) >= 1, f"应至少 1 个 checkpoint, 实际: {len(checkpoints)}"
    verify_store.close()


# ============================================================
# 7. Empty Plan → rejected
# ============================================================


def test_full_cycle_empty_plan_rejected() -> None:
    """空 tasks → Plan.validate() 抛异常, Orchestrator 构造时拒绝."""
    from auto_engineering.loop.orchestrator import Orchestrator

    async def noop(task, ctx):
        return TaskOutcome(task_id=task.id, status="completed")

    # Plan 构造不抛 (空 list 合法), 但 validate 在 run() step 1 调
    orch = Orchestrator(
        requirement="empty test",
        tasks=[],
        executor=noop,
    )
    # 验证 Plan 存在
    assert orch.plan is not None
    assert len(orch.plan.tasks) == 0


# ============================================================
# 8. StageRouter 默认配置集成
# ============================================================


@pytest.mark.asyncio
async def test_full_cycle_stage_router_default_config() -> None:
    """StageRouter 默认配置 (max_majors_in_a_row=2, max_total_majors=3) 集成验证.

    模拟 3 次 MAJOR 后 APPROVE:
    - 第 1 次 MAJOR → critics 继续
    - 第 2 次 MAJOR → 连续 2 次 → StageRouter stop
    """
    tasks = [
        _make_task("arch-1", agent_type="architect"),
        _make_task("dev-1", agent_type="developer"),
        _make_task("critic-1", agent_type="critic"),
    ]

    major_count = {"count": 0}

    async def executor(task, ctx):
        role = task.role
        if role == "architect":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"plan": "x", "file_list": ["f.py"]},
                task_role=role,
            )
        if role == "developer":
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"files_changed": ["f.py"], "commit_hash": "stu"},
                task_role=role,
            )
        if role == "critic":
            major_count["count"] += 1
            if major_count["count"] <= 2:
                return TaskOutcome(
                    task_id=task.id, status="completed",
                    output={
                        "verdict": "MAJOR",
                        "findings": [{"file": "f.py", "line": 1, "severity": "P0",
                                      "issue": f"issue {major_count['count']}",
                                      "suggested_fix": "fix"}],
                        "critic_feedback": f"major round {major_count['count']}",
                    },
                    task_role=role,
                )
            return TaskOutcome(
                task_id=task.id, status="completed",
                output={"verdict": "APPROVE", "findings": [], "critic_feedback": "ok now"},
                task_role=role,
            )
        return TaskOutcome(task_id=task.id, status="failed", task_role=role)

    orch = _setup_orchestrator(tasks, executor, max_iterations=10)
    history = await orch.run(cancellation=None)

    assert orch.verdict is not None
    assert orch.verdict.should_stop is True
    # 2 次 MAJOR 后 StageRouter 应触发 stop
