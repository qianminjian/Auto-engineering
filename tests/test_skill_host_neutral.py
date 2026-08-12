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


def test_host_contract_recovers_transient_agent_capacity_without_forgery() -> None:
    for content in (SKILL.read_text(), DEV_LOOP.read_text()):
        assert "HOST_AGENT_CAPACITY" in content
        assert "WAIT_RESOURCE" in content
        assert "resource_wait" in content
        assert "重试一次" in content
        assert "原 active Action" in content


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
