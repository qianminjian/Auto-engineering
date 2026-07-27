"""CLAUDE.md / AGENTS.md 单一事实源同步行为测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import sync_agent_instructions

_TEMPLATE = """# {{INSTRUCTION_FILE}}

Agent: {{AGENT_NAME}}
Site: {{AGENT_SITE}}
Plugin: {{PLUGIN_DIR}}
Rules: {{RULES_DIR}}
"""


def _write_template(root: Path, content: str = _TEMPLATE) -> None:
    template = root / "agent-rules" / "instructions.md.tmpl"
    template.parent.mkdir(parents=True)
    template.write_text(content, encoding="utf-8")
    (template.parent / "claude.md.tmpl").write_text(
        "Claude adapter: {{AGENT_NAME}}\n",
        encoding="utf-8",
    )
    (template.parent / "codex.md.tmpl").write_text(
        "Codex adapter: {{AGENT_NAME}}\n",
        encoding="utf-8",
    )


def test_rendering_uses_platform_specific_values(tmp_path: Path) -> None:
    _write_template(tmp_path)

    changed = sync_agent_instructions.sync_instructions(tmp_path)

    assert changed == [tmp_path / "CLAUDE.md", tmp_path / "AGENTS.md"]
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    codex = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "# CLAUDE.md" in claude
    assert "Agent: Claude Code" in claude
    assert "Site: claude.ai/code" in claude
    assert "Plugin: .claude-plugin/" in claude
    assert "# AGENTS.md" in codex
    assert "Agent: Codex" in codex
    assert "Site: Codex.ai/code" in codex
    assert "Plugin: .codex-plugin/" in codex
    assert "Rules: .claude/rules/" in claude
    assert "Rules: .claude/rules/" in codex
    assert "Claude adapter: Claude Code" in claude
    assert "Claude adapter:" not in codex
    assert "Codex adapter: Codex" in codex
    assert "Codex adapter:" not in claude


def test_repository_uses_core_and_two_adapter_templates() -> None:
    root = Path(__file__).parents[1]

    for filename in (
        "instructions.md.tmpl",
        "claude.md.tmpl",
        "codex.md.tmpl",
    ):
        assert (root / "agent-rules" / filename).is_file()


def test_codex_output_embeds_critical_rules_without_claude_includes() -> None:
    root = Path(__file__).parents[1]
    codex = (root / "AGENTS.md").read_text(encoding="utf-8")

    assert "@.claude/rules/" not in codex
    assert "禁止并发运行多个 pytest 进程" in codex
    assert "5 / 10 / 15 分钟心跳" in codex
    assert "BEACON 决策状态翻转必须先获得用户审批" in codex
    assert "先记录 → 再执行 → 再更新" in codex


def test_current_rules_do_not_advertise_retired_cli_or_stale_baseline() -> None:
    """公共模板及生成文件只能描述当前真实入口。"""
    root = Path(__file__).parents[1]
    retired_claims = (
        "ae gate-check",
        "ae agent architect",
        "ae progress",
        'ae dev-loop "需求"',
        "1702 passed",
        "~1703 tests",
    )

    for relative in (
        "agent-rules/instructions.md.tmpl",
        "CLAUDE.md",
        "AGENTS.md",
    ):
        content = (root / relative).read_text(encoding="utf-8")
        for retired in retired_claims:
            assert retired not in content, f"{relative} 仍宣称退役入口: {retired}"
        assert "scripts/ae-run doctor" in content
        assert "scripts/ae-run status --format json" in content
        assert "[tool.auto-engineering.baseline]" in content


def test_check_returns_zero_when_generated_files_match(tmp_path: Path) -> None:
    _write_template(tmp_path)
    sync_agent_instructions.sync_instructions(tmp_path)

    assert sync_agent_instructions.main(["--check"], root=tmp_path) == 0


def test_check_reports_drift_without_writing(tmp_path: Path) -> None:
    _write_template(tmp_path)
    sync_agent_instructions.sync_instructions(tmp_path)
    target = tmp_path / "AGENTS.md"
    target.write_text("人工漂移\n", encoding="utf-8")

    assert sync_agent_instructions.main(["--check"], root=tmp_path) == 1
    assert target.read_text(encoding="utf-8") == "人工漂移\n"


def test_write_mode_repairs_drift(tmp_path: Path) -> None:
    _write_template(tmp_path)
    sync_agent_instructions.sync_instructions(tmp_path)
    target = tmp_path / "CLAUDE.md"
    target.write_text("人工漂移\n", encoding="utf-8")

    changed = sync_agent_instructions.sync_instructions(tmp_path)

    assert changed == [target]
    assert "Agent: Claude Code" in target.read_text(encoding="utf-8")


def test_sync_is_idempotent(tmp_path: Path) -> None:
    _write_template(tmp_path)

    first = sync_agent_instructions.sync_instructions(tmp_path)
    second = sync_agent_instructions.sync_instructions(tmp_path)

    assert len(first) == 2
    assert second == []


def test_unknown_template_variable_fails_fast(tmp_path: Path) -> None:
    _write_template(tmp_path, "{{UNKNOWN_PLATFORM_VALUE}}\n")

    with pytest.raises(ValueError, match="UNKNOWN_PLATFORM_VALUE"):
        sync_agent_instructions.sync_instructions(tmp_path)


def test_sync_rejects_targets_outside_project_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.md"

    with pytest.raises(ValueError, match="不允许的生成目标"):
        sync_agent_instructions.write_generated_file(
            root=tmp_path,
            target=outside,
            content="禁止写出项目边界",
            check=False,
        )

    assert not outside.exists()
