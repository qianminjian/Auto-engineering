"""v2.1 Phase B — Orchestrator Gate 集成 + LLM 语义 + git diff 集成测试.

设计来源: design/v2.0-Analysis-Loop.md §4.7 (4 级收敛判定).

测试覆盖 (Phase B 集成测试, 真集成非 mock):
    B.1 OrchestratorConfig.gates 字段存在
    B.2 _build_history 真跑 Gate 收集 Verdict → gate_results 非空
    B.3 OrchestratorConfig.semantic_evaluator 字段存在
    B.4 semantic_evaluator 被调用 → semantic_satisfied 写入
    B.5 git diff --numstat → lines_added/removed 写入
    B.6 Orchestrator 接受 gates + semantic_evaluator + project_root

测试约束:
    - 用真 SafetyGate (不 mock) 验证端到端集成
    - 用真 git init + commit + diff 验证 lines_added/removed
    - 跑完清理 tmp_path
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auto_engineering.loop.convergence import LEVEL_QUALITY, ConvergenceConfig
from auto_engineering.loop.orchestrator import Orchestrator, OrchestratorConfig
from auto_engineering.loop.plan import Task
from auto_engineering.loop.round import TaskOutcome

# ============================================================
# Fixtures + helpers
# ============================================================


def make_task(
    task_id: str,
    target_files: list[str] | None = None,
    deps: list[str] | None = None,
    role: str = "developer",
) -> Task:
    """构造测试 Task (target_files 用字符串列表, 内部转 frozenset).

    Phase 2.1-D: 补 title/expected_output 字段满足 Plan.validate contract.

    2026-07-04 (Bug 3 prismscan): 加 role 参数支持 critic task 测试.
    """
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        description=f"task {task_id}",
        expected_output=f"output for {task_id}",
        role=role,
        agent_type="developer",
        target_files=frozenset(target_files or []),
        depends_on=list(deps or []),
    )


async def noop_executor(task, ctx) -> TaskOutcome:
    """什么都不做的 executor — task 立即标记 completed."""
    return TaskOutcome(task_id=task.id, status="completed", output="ok")


def _init_git_repo(path: Path) -> None:
    """在 path 下初始化 git 仓库 + 首次 commit (建立 HEAD)."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    # 初始空 commit 让 HEAD 存在
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init", "-q"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )


# ============================================================
# B.1 OrchestratorConfig.gates 字段
# ============================================================


def test_orchestrator_config_accepts_gates_field():
    """OrchestratorConfig 应支持 gates 字段."""
    from auto_engineering.gates.safety import SafetyGate

    gate = SafetyGate()
    config = OrchestratorConfig(gates=[gate])
    assert config.gates == [gate]


def test_orchestrator_config_gates_default_none():
    """OrchestratorConfig.gates 默认 None (向后兼容)."""
    config = OrchestratorConfig()
    assert config.gates is None


# ============================================================
# B.2 _build_history 接入 Gate 运行结果
# ============================================================


@pytest.mark.asyncio
async def test_orchestrator_runs_real_gates_each_round(tmp_path: Path):
    """Orchestrator 真跑 SafetyGate (无 secret 时 PASS) → gate_results 非空."""
    from auto_engineering.gates.safety import SafetyGate

    # 干净项目 (无 secret)
    (tmp_path / "ok.py").write_text("x = 1\n")

    task = make_task("t1", ["ok.py"])
    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(
            max_iterations=1,
            stagnation_threshold=10,
        ),
        gates=[SafetyGate()],
        project_root=tmp_path,
    )
    orch = Orchestrator(
        requirement="gate test",
        tasks=[task],
        executor=noop_executor,
        config=config,
    )
    history = await orch.run()

    assert len(history) == 1
    assert history[0].gate_results != {}, "gate_results 必须非空"
    assert "safety" in history[0].gate_results
    # 干净 repo → safety pass (v2.3 Phase D: gate_results 是 dict[gate_name, Verdict])
    assert history[0].gate_results["safety"].passed is True


@pytest.mark.asyncio
async def test_orchestrator_gate_detects_real_secret_in_project(tmp_path: Path):
    """SafetyGate 真扫到 secret 时 gate_results["safety"] = False."""
    from auto_engineering.gates.safety import SafetyGate

    # 注入 AWS access key (固定 pattern, 必被检测)
    (tmp_path / "leak.py").write_text(
        "AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n"
    )

    task = make_task("t1", ["leak.py"])
    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(
            max_iterations=1,
            stagnation_threshold=10,
        ),
        gates=[SafetyGate()],
        project_root=tmp_path,
    )
    orch = Orchestrator(
        requirement="secret test",
        tasks=[task],
        executor=noop_executor,
        config=config,
    )
    history = await orch.run()

    # SafetyGate 真扫到 secret 时 gate_results["safety"].passed = False
    assert history[0].gate_results["safety"].passed is False


@pytest.mark.asyncio
async def test_orchestrator_gate_results_trigger_quality_convergence(tmp_path: Path):
    """全部 Gate PASS 时触发 GOAL_ACHIEVED (level=3 QUALITY).

    2026-07-04 (Bug 3 prismscan 集成): 测试期望 QUALITY 但实际 critic 空 verdict
    会升级为 HARD_LIMIT (level=4). 修复: 让 mock executor 提供 APPROVE verdict
    (模拟 critic agent 正常返回), 让 round 通过 stage_router → Judge.evaluate
    → QUALITY 路径.
    """
    from auto_engineering.gates.safety import SafetyGate

    # 干净 repo
    (tmp_path / "clean.py").write_text("y = 2\n")

    # 2026-07-04 (Bug 3): 提供 critic 输出 (模拟 critic agent 正常返回 APPROVE)
    async def critic_aware_executor(task, ctx):
        return TaskOutcome(
            task_id=task.id,
            status="completed",
            output={"verdict": "APPROVE", "findings": [], "feedback": "ok"},
            task_role="critic" if task.role == "critic" else "developer",
        )

    # 第一轮 1 个 task, 第二轮继续 1 个 task (无变化, 可能触发停滞)
    # max_iterations=10 (默认上限), 防止硬上限先于质量门触发 (P1.1 单一来源后:
    # 硬上限由 judge.config.max_iterations 决定, 而非 OrchestratorConfig.max_rounds).
    # 2026-07-04 (Bug 3 prismscan): 加 critic task 让 _apply_outcome_to_state 写入 state.verdict="APPROVE".
    # 否则 stage_router 看到 state.verdict="" → 抛 CriticVerdictInvalid → HARD_LIMIT.
    dev_task = make_task("dev1", ["clean.py"], role="developer")
    critic_task = make_task("critic1", role="critic")
    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(
            max_iterations=10,
            stagnation_threshold=10,
        ),
        gates=[SafetyGate()],
        project_root=tmp_path,
    )
    orch = Orchestrator(
        requirement="quality test",
        tasks=[dev_task, critic_task],
        executor=critic_aware_executor,
        config=config,
    )
    await orch.run()

    # 验证: critic APPROVE + safety pass → QUALITY_PASS (level=3)
    assert orch.verdict is not None
    assert orch.verdict.level == LEVEL_QUALITY
    assert orch.verdict.should_stop is True


# ============================================================
# B.3 OrchestratorConfig.semantic_evaluator 字段
# ============================================================


def test_orchestrator_config_accepts_semantic_evaluator_field():
    """OrchestratorConfig 应支持 semantic_evaluator callable 字段."""

    async def my_evaluator(round_result) -> bool:
        return True

    config = OrchestratorConfig(semantic_evaluator=my_evaluator)
    assert config.semantic_evaluator is my_evaluator


def test_orchestrator_config_semantic_evaluator_default_none(monkeypatch):
    """OrchestratorConfig.semantic_evaluator 默认 None (无 API key 时).

    2026-07-04 修复 (v5.0 深度审计): 加 monkeypatch fixture 同时清
    ANTHROPIC_API_KEY + ANTHROPIC_AUTH_TOKEN, 避免真实环境 AUTH_TOKEN
    导致测试失败 (与 test_loop_semantic_evaluator.py::clean_env 同模式).
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    config = OrchestratorConfig()
    assert config.semantic_evaluator is None


# ============================================================
# B.4 semantic_evaluator 被调用 → semantic_satisfied 写入
# ============================================================


@pytest.mark.asyncio
async def test_orchestrator_calls_semantic_evaluator_each_round(tmp_path: Path):
    """semantic_evaluator 在 critic stage 被调用一次, 返回值写入 semantic_satisfied.

    v5.0 M4 更新: semantic_evaluator 仅 critic 阶段触发 (v5.0 §B2.7).
    测试需要至少 1 个 critic role task, 才会调用 semantic_evaluator.
    """
    call_log: list[int] = []

    async def my_evaluator(round_result) -> bool:
        call_log.append(round_result.round_id)
        return True

    # v5.0: 需 critic role task 才能触发 semantic_evaluator
    dev_task = make_task("dev-1", ["a.py"])
    dev_task.role = "developer"
    critic_task = Task(
        id="critic-1", title="c", description="c",
        expected_output="ok", role="critic",
        agent_type="critic", target_files=frozenset(),
    )
    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(
            max_iterations=10,
            stagnation_threshold=10,
        ),
        semantic_evaluator=my_evaluator,
        project_root=tmp_path,
    )
    orch = Orchestrator(
        requirement="semantic test",
        tasks=[dev_task, critic_task],
        executor=noop_executor,
        config=config,
    )
    history = await orch.run()

    # semantic_evaluator 在 critic stage 至少被调用 1 次
    assert len(call_log) >= 1
    # semantic_satisfied 写入 (最近 critic 阶段)
    critic_histories = [h for h in history if h.semantic_satisfied is not None]
    assert len(critic_histories) >= 1
    assert critic_histories[-1].semantic_satisfied is True


@pytest.mark.asyncio
async def test_orchestrator_semantic_evaluator_returning_false(tmp_path: Path):
    """semantic_evaluator 返回 False → semantic_satisfied=False.

    v5.0 M4 更新: semantic_evaluator 仅 critic 阶段触发.
    """
    async def my_evaluator(round_result) -> bool:
        return False

    dev_task = make_task("dev-1", ["a.py"])
    dev_task.role = "developer"
    critic_task = Task(
        id="critic-1", title="c", description="c",
        expected_output="ok", role="critic",
        agent_type="critic", target_files=frozenset(),
    )
    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(
            max_iterations=10,
            stagnation_threshold=10,
        ),
        semantic_evaluator=my_evaluator,
        project_root=tmp_path,
    )
    orch = Orchestrator(
        requirement="semantic false test",
        tasks=[dev_task, critic_task],
        executor=noop_executor,
        config=config,
    )
    history = await orch.run()

    # critic 阶段 semantic_satisfied=False
    critic_histories = [h for h in history if h.semantic_satisfied is not None]
    assert len(critic_histories) >= 1
    assert critic_histories[-1].semantic_satisfied is False
    # 主循环 should_stop=True (任意退出原因: max_iter 或 stage router stop)
    assert orch.verdict is not None
    assert orch.verdict.should_stop is True


# ============================================================
# B.5 git diff --numstat → lines_added/removed
# ============================================================


@pytest.mark.asyncio
async def test_orchestrator_git_diff_lines_added_removed(tmp_path: Path):
    """真 git init + commit + 新增文件 → lines_added > 0."""
    _init_git_repo(tmp_path)
    # 模拟本轮产出: 新增文件 + 提交
    new_file = tmp_path / "new.py"
    new_file.write_text("a = 1\nb = 2\nc = 3\n")
    subprocess.run(
        ["git", "add", "new.py"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add new", "-q"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )

    task = make_task("t1", ["new.py"])
    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(
            max_iterations=1,
            stagnation_threshold=10,
        ),
        project_root=tmp_path,
    )
    orch = Orchestrator(
        requirement="git diff test",
        tasks=[task],
        executor=noop_executor,
        config=config,
    )
    history = await orch.run()

    # 至少 3 行被加
    assert history[0].lines_added >= 3
    # 新文件无删除
    assert history[0].lines_removed == 0


# ============================================================
# B.6 Orchestrator 接受 gates + semantic_evaluator + project_root 联合
# ============================================================


@pytest.mark.asyncio
async def test_orchestrator_combined_gates_and_semantic_evaluator(tmp_path: Path):
    """同时传 gates + semantic_evaluator → 两者都生效.

    v5.0 M4 更新: semantic_evaluator 仅 critic 阶段触发 (v5.0 §B2.7).
    """
    from auto_engineering.gates.safety import SafetyGate

    (tmp_path / "ok.py").write_text("x = 1\n")

    call_count = {"n": 0}

    async def my_evaluator(round_result) -> bool:
        call_count["n"] += 1
        return True

    dev_task = make_task("dev-1", ["ok.py"])
    dev_task.role = "developer"
    critic_task = Task(
        id="critic-1", title="c", description="c",
        expected_output="ok", role="critic",
        agent_type="critic", target_files=frozenset(),
    )
    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(
            max_iterations=10,
            stagnation_threshold=10,
        ),
        gates=[SafetyGate()],
        semantic_evaluator=my_evaluator,
        project_root=tmp_path,
    )
    orch = Orchestrator(
        requirement="combined test",
        tasks=[dev_task, critic_task],
        executor=noop_executor,
        config=config,
    )
    history = await orch.run()

    # Gate 至少跑过 1 次 (developer stage)
    developer_histories = [h for h in history if h.gate_results]
    assert len(developer_histories) >= 1
    assert "safety" in developer_histories[0].gate_results
    assert developer_histories[0].gate_results["safety"].passed is True
    # semantic_evaluator 在 critic stage 跑过
    assert call_count["n"] >= 1
    critic_histories = [h for h in history if h.semantic_satisfied is not None]
    assert len(critic_histories) >= 1
    assert critic_histories[-1].semantic_satisfied is True


@pytest.mark.asyncio
async def test_orchestrator_no_gates_no_evaluator_compat(tmp_path: Path):
    """不传 gates / semantic_evaluator → 向后兼容 (gate_results={}, semantic=None)."""
    task = make_task("t1", ["a.py"])
    config = OrchestratorConfig(
        convergence_config=ConvergenceConfig(
            max_iterations=1,
            stagnation_threshold=10,
        ),
        project_root=tmp_path,
    )
    orch = Orchestrator(
        requirement="compat test",
        tasks=[task],
        executor=noop_executor,
        config=config,
    )
    history = await orch.run()

    assert history[0].gate_results == {}
    assert history[0].semantic_satisfied is None
