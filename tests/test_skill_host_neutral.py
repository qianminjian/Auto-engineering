"""Auto-Engineering Skill 的跨宿主契约测试。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "auto-engineering" / "SKILL.md"
DEV_LOOP = ROOT / "commands" / "dev-loop.md"


def test_skill_declares_codex_entry_and_current_cli_surface() -> None:
    content = SKILL.read_text()

    assert "$auto-engineering" in content
    assert "ae-run dev-loop" in content
    assert "ae-run dev-loop --status --format json" in content
    assert "| 查看循环状态 | `ae-run status --format json` |" not in content
    assert "scripts/ae-run" not in content
    assert "AE_HOST_PLATFORM=codex" in content
    for removed_command in (
        "/checkpoint",
        "/project-tdd",
        "/project-worktree",
        "/project-agent",
        "/project-ci",
    ):
        assert removed_command not in content


def test_skill_is_host_and_model_neutral() -> None:
    content = SKILL.read_text()

    for platform_detail in (
        "Claude Code Plugin",
        "Sonnet",
        "Haiku",
        "Agent tool",
        "Standalone",
    ):
        assert platform_detail not in content

    assert "HostCapabilities" in content
    assert "宿主原生子代理能力" in content


def test_skill_handles_unavailable_subagent_capability_explicitly() -> None:
    content = SKILL.read_text()

    assert "HOST_CAPABILITY_UNAVAILABLE" in content
    assert "不得伪造" in content
    assert "action.spawn.count" in content
    assert "action.spawn.parallel" in content
    assert "action.spawn.effort" in content


def test_codex_skill_binds_native_spawn_tool_before_reporting_unavailable() -> None:
    content = SKILL.read_text()

    assert "collaboration.spawn_agent" in content
    assert "reasoning_effort" in content
    assert "工具调用明确失败前，不得报告 `HOST_CAPABILITY_UNAVAILABLE`" in content
    assert "不得因为当前回复尚未调用子代理就判定能力不存在" in content
    assert "multi_agent_v1__spawn_agent" in content
    assert "first_complete_exposed_family" in content
    assert "任一完整工具族" in content


def test_host_contract_recovers_transient_agent_capacity_without_forgery() -> None:
    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "HOST_AGENT_CAPACITY" in content
        assert "WAIT_RESOURCE" in content
        assert "resource_wait" in content
        assert "重试一次" in content
        assert "原 active Action" in content


def test_skill_reclaims_every_completed_worker_before_next_action() -> None:
    content = SKILL.read_text()

    assert "每个 Worker 完成且 outcome 已记录后立即回收" in content
    assert "不得把已完成句柄保留到下一 Action" in content
    assert "close/reclaim" in content
    assert "成功后才能执行 finalize" in content
    assert "close_agent" in content
    assert "wait → record_worker_outcome → reclaim → finalize" in content
    assert "agents_states[agent_id].message" in content
    assert "逐字节复制到 `--native-result-stdin`" in DEV_LOOP.read_text()


def test_worker_payload_and_finalize_failures_have_explicit_boundaries() -> None:
    skill = SKILL.read_text()
    command = DEV_LOOP.read_text()

    for content in (skill, command):
        assert "expected_fields" in content
        assert "当前 stage 合同" in content
        assert "finalize 非零退出" in content
        assert "禁止继续" in content
        assert "`ERROR`" in content


def test_claude_async_worker_must_use_same_handle_task_output() -> None:
    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "async_launched" in content
        assert "同一" in content
        assert "agentId" in content
        assert "TaskOutput" in content
        assert "禁止 Stop、TaskStop" in content


def test_skill_batches_native_worker_waits_without_polling() -> None:
    content = SKILL.read_text()

    assert "禁止 30 秒轮询" in content
    assert "5 / 10 / 15 分钟" in content
    assert "等待期间不得重复读取 diff" in content
    assert 'collaboration.wait_agent({"timeout_ms":300000})' in content
    assert "multi_agent_v1__wait_agent" in content


def test_host_contract_uses_action_scoped_work_files() -> None:
    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "action.host_execution.work_files" in content
        assert "不得复用上一 Action" in content


def test_host_contract_rechecks_core_after_native_process_returns() -> None:
    """宿主进程退出不能把非终态 Core 状态误报成成功。"""

    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "after_host_return" in content
        assert "recheck_core_status" in content
        assert "宿主调用返回后" in content
        assert "work_files" in content
        assert "父目录" in content
        assert "CONTINUE" in content
        assert "不得报告成功" in content
        assert "resume_active_action" in content
        assert "thread_id + message_id" in content
        assert "developer B1" in content
        assert "stage 名相同" in content or "stage`、`tick" in content


def test_host_contract_has_one_repair_operation_and_no_fake_handle_fallback() -> None:
    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "repair_coordinator_then_finalize" in content
        assert "validate_then_submit_or_repair" not in content
        assert "不得启动回显 Agent" in content
        assert "不得伪造 completed Worker" in content


def test_host_contract_has_explicit_project_setup_driver_branch() -> None:
    """Project Setup 不能依赖宿主从通用 non-spawn 文案自行推断。"""

    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "project_setup_required" in content
        assert "missing_capabilities" in content
        assert "operations.finalize.argv" in content
        assert "operations.validate.argv" in content
        assert "operations.submit.argv" in content
        assert ".ae-state/.ae-runtime" in content
        assert "UV_PROJECT_ENVIRONMENT" in content
        assert "VIRTUAL_ENV" in content
        assert "uv venv .venv" in content
        assert "uv sync --dev" in content
        assert "pytest" in content
        assert "ruff" in content
        assert "mypy" in content
        assert "设计文档是" in content
        assert "design_change_requests[]" in content
        assert "capability_only" in content
        assert "不得实现用户业务功能" in content
        assert "不得创建业务测试" in content
        assert "PEP 735" in content
        assert "src_paths" in content
        assert "路径数组" in content or "path array" in content
        assert "[dependency-groups]" in content
        assert "[project.optional-dependencies]" in content
        assert "不得执行 `rm -rf .venv`" in content or "never run\n             rm -rf .venv" in content
        assert "绝对路径 symlink" in content or "absolute-path symlinks" in content
        assert "同一 Action 内" in content or "same failed command" in content


def test_project_setup_branch_preserves_single_coordinator_boundary() -> None:
    skill = SKILL.read_text()
    command = DEV_LOOP.read_text()

    assert "不得调用\n  Worker 或启动第二个 Loop" in skill
    assert "spawn workers" in command
    assert "start another loop" in command


def test_host_contract_locks_startup_project_root_before_init() -> None:
    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "invocation_project_root" in content
        assert "HOST_PROJECT_ROOT_DRIFT" in content
        assert "禁止搜索父目录" in content
        assert "禁止改写 `--project-root`" in content


def test_outer_adapter_owns_claude_exit_facts() -> None:
    """入口说明必须保留 Hook 延后与具体 provider 故障分类合同。"""

    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "AE_HOST_ADAPTER_ACTIVE=1" in content
        assert "SessionEnd`/`StopFailure" in content
        assert "HOST_PROVIDER_STREAM_IDLE_TIMEOUT" in content
        assert "不得先清理" in content or "不得抢先清理" in content


def test_skill_does_not_assume_git_authorization() -> None:
    content = SKILL.read_text()

    assert "MUST commit" not in content
    assert "自动 commit" not in content
    assert "用户明确授权" in content


def test_dev_loop_reference_is_host_neutral() -> None:
    content = DEV_LOOP.read_text()

    for stale_detail in (
        "Agent tool",
        "Standalone mode",
        "Standalone 模式",
        "Claude Code 原生",
        "创建 PR",
    ):
        assert stale_detail not in content

    assert "宿主原生子代理能力" in content
    assert "HOST_CAPABILITY_UNAVAILABLE" in content
    assert "AE_HOST_PLATFORM=claude-code" in content


def test_entry_keeps_coordination_in_current_host_agent() -> None:
    """主 Agent 是唯一 Coordinator，Core 不启动宿主会话。"""

    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        routing_start = (
            content.index("## Action 执行协议")
            if "## Action 执行协议" in content
            else content.index("## 驱动循环")
        )
        routing_end = (
            content.index("### Codex 原生能力绑定", routing_start)
            if "### Codex 原生能力绑定" in content
            else content.index("## CLI 契约", routing_start)
        )
        routing = content[routing_start:routing_end]
        assert "主 Agent" in routing
        assert "Supervisor" not in routing
        assert "--supervise" not in routing


def test_retired_supervisor_has_no_runtime_surface() -> None:
    """旧 Supervisor 退役后不能通过文件或 CLI 符号重新进入运行时。"""

    retired_paths = (
        ROOT / "auto_engineering" / "host" / "supervisor.py",
        ROOT / "auto_engineering" / "host" / "invocation.py",
        ROOT / "auto_engineering" / "host" / "request_compiler.py",
        ROOT / "auto_engineering" / "host" / "driver_contract.py",
        ROOT / "auto_engineering" / "loop" / "action-execution-request.schema.json",
        ROOT / "auto_engineering" / "loop" / "action-execution-receipt.schema.json",
    )
    assert all(not path.exists() for path in retired_paths)

    for entrypoint in (
        ROOT / "auto_engineering" / "cli" / "__init__.py",
        ROOT / "auto_engineering" / "cli" / "dev_loop.py",
    ):
        content = entrypoint.read_text()
        assert "run_action_supervisor" not in content
        assert "--supervise" not in content

    runtime_boundaries = (
        ROOT / "auto_engineering" / "host" / "stop_report.py",
        ROOT / "auto_engineering" / "host" / "process_exit.py",
        ROOT / "scripts" / "collect_product_evidence.py",
    )
    for runtime_boundary in runtime_boundaries:
        content = runtime_boundary.read_text()
        assert "HOST_SUPERVISOR_PROTOCOL_ERROR" not in content
    for runtime_boundary in (runtime_boundaries[0], runtime_boundaries[2]):
        content = runtime_boundary.read_text()
        assert "HOST_RUNTIME_PROTOCOL_ERROR" in content


def test_python_cli_is_single_tick_boundary_not_long_running_coordinator() -> None:
    """Python CLI 只能执行一次 Core 操作，持续循环归宿主 Agent。"""

    source = (ROOT / "auto_engineering" / "cli" / "dev_loop.py").read_text()
    tree = ast.parse(source)
    assert not any(isinstance(node, ast.While) for node in ast.walk(tree))
    assert not any(
        isinstance(node, ast.Import)
        and any(alias.name == "subprocess" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "subprocess"
        for node in ast.walk(tree)
    )
    tick_step = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_tick_step"
    )
    tick_calls = [
        node for node in ast.walk(tick_step)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "tick"
    ]
    assert len(tick_calls) == 1


def test_plan_models_have_one_canonical_runtime_module() -> None:
    """Plan/Task 已归属 engine.models，旧 loop.plan 入口不得复活。"""

    assert not (ROOT / "auto_engineering" / "loop" / "plan.py").exists()
    for path in (
        ROOT / "auto_engineering" / "loop" / "__init__.py",
        ROOT / "auto_engineering" / "loop" / "task_factory.py",
        ROOT / "auto_engineering" / "loop" / "architecture_activation.py",
        ROOT / "auto_engineering" / "loop" / "tick_orchestrator.py",
        ROOT / "auto_engineering" / "engine" / "models.py",
    ):
        content = path.read_text()
        assert "from auto_engineering.loop.plan import" not in content
        assert "import auto_engineering.loop.plan" not in content


def test_default_contract_keeps_wait_as_observation() -> None:
    """Phase 85 T611：等待未完成时不能直接制造失败结果或重启 Worker。"""

    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "等待到期不是失败" in content
        assert "无法确认旧\nWorker 已终止" in content
        assert "禁止并发重跑" in content
        assert "三次长等待后 Worker 仍未完成时，不得" not in content


def test_codex_wait_contract_extracts_completion_body_not_outer_wrapper() -> None:
    """Codex wait 回包只能转交当前 Worker 完成正文，不能整包回写。"""

    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "agents_states[agent_id].message" in content
        assert "status[agent_id].completed" in content
        assert "外层 `status`/`agents_states`" in content
        assert "等待包装整体回写" in content or "映射整体" in content
