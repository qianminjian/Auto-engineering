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
