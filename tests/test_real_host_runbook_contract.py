"""真实宿主验收手册的可执行入口契约。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_real_host_runbook_uses_locked_project_runner_for_installers() -> None:
    runbook = (ROOT / "design/v5.8-Real-Host-Acceptance-Runbook.md").read_text(
        encoding="utf-8"
    )

    assert "uv run python scripts/install_codex_local.py" in runbook
    assert "uv run python scripts/install_claude_local.py" in runbook
    assert runbook.count("uv run python scripts/install_acceptance.py") == 2
    assert "python3 scripts/install_codex_local.py" not in runbook
    assert "python3 scripts/install_claude_local.py" not in runbook
    assert "python3 scripts/install_acceptance.py" not in runbook
    assert '"$PLUGIN_ROOT/bin/ae-run" build-info --expect-build-id' in runbook
    assert "必须从目标项目根执行" in runbook
    assert "不能从插件根目录执行" in runbook
    assert "AE_INVOCATION_PROJECT_ROOT" in runbook
    assert "AE_PROJECT_ROOT_DRIFT" in runbook
    assert "--setting-sources user,project" in runbook
    assert "--strict-mcp-config" in runbook
    assert "  --disable-slash-commands --no-chrome" not in runbook
    assert "会关闭所有 Skill" in runbook
    assert "--max-coordinator-polls 32" in runbook
    assert "HOST_COORDINATOR_POLL_LIMIT" in runbook
    assert "HOST_PROVIDER_STREAM_IDLE_TIMEOUT" in runbook
    assert "不得先清理 lease 或写 Stop Report" in runbook
    assert "authentication_failed / Not logged in" in runbook
    assert '--project-root "codex=$CODEX_PROJECT_ROOT"' in runbook
    assert '--project-root "claude-code=$CLAUDE_PROJECT_ROOT"' in runbook
    assert "不一致" in runbook
    assert "立即停止本次验收" in runbook
    assert "design_structure_preflight" in runbook
    assert "零 Worker" in runbook


def test_dev_loop_command_does_not_tick_a_gate_without_a_result() -> None:
    command = (ROOT / "commands/dev-loop.md").read_text(encoding="utf-8")

    assert 'if action.action in {"gate", "skip"}' not in command
    assert "operations.finalize.argv" in command
    assert "gate_resolution" in command
