"""Auto-Engineering Skill 的跨宿主契约测试。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "auto-engineering" / "SKILL.md"
DEV_LOOP = ROOT / "commands" / "dev-loop.md"


def test_skill_declares_codex_entry_and_current_cli_surface() -> None:
    content = SKILL.read_text()

    assert "$auto-engineering" in content
    assert "ae-run dev-loop" in content
    assert "ae-run status" in content
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


def test_host_contract_locks_startup_project_root_before_init() -> None:
    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "invocation_project_root" in content
        assert "HOST_PROJECT_ROOT_DRIFT" in content
        assert "禁止搜索父目录" in content
        assert "禁止改写 `--project-root`" in content


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


def test_default_entry_keeps_coordination_in_current_host_agent() -> None:
    """Phase 85 T609：默认入口不能把主控权交给 Python Supervisor。"""

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
        assert "final_action = ae-run dev-loop --supervise" not in routing


def test_default_contract_keeps_wait_as_observation() -> None:
    """Phase 85 T611：等待未完成时不能直接制造失败结果或重启 Worker。"""

    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "等待到期不是失败" in content
        assert "无法确认旧\nWorker 已终止" in content
        assert "禁止并发重跑" in content
        assert "三次长等待后 Worker 仍未完成时，不得" not in content
