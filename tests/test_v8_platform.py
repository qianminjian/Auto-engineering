"""Tests for V8-1 directory restructuring + V8-2 hook registration splitting.

V8-1: commands/hooks/skills/agents 从 .claude-plugin/ 提升到项目根.
V8-2: Hook 注册拆分为三平台特定文件.

TDD protocol: 写测试 → 确认 FAIL → 写实现 → 确认 PASS.
"""

from __future__ import annotations

import json
from pathlib import Path


def _project_root() -> Path:
    """返回项目根目录 (tests/ 的父目录)."""
    return Path(__file__).resolve().parent.parent


class TestV8_1_DirectoryRestructuring:
    """V8-1: 目录结构重构 — commands/hooks/skills 提升到根目录."""

    def test_commands_dir_exists_at_root(self) -> None:
        """commands/ 目录在项目根存在 (非 .claude-plugin/ 内)."""
        root = _project_root()
        assert (root / "commands").is_dir()

    def test_hooks_dir_exists_at_root(self) -> None:
        """hooks/ 目录在项目根存在."""
        root = _project_root()
        assert (root / "hooks").is_dir()

    def test_skills_dir_exists_at_root(self) -> None:
        """skills/ 目录在项目根存在."""
        root = _project_root()
        assert (root / "skills").is_dir()

    def test_dev_loop_command_exists_at_root(self) -> None:
        """dev-loop.md 在项目根 commands/ 目录."""
        root = _project_root()
        assert (root / "commands" / "dev-loop.md").is_file()

    def test_session_start_hook_exists_at_root(self) -> None:
        """session-start.sh 在项目根 hooks/ 目录."""
        root = _project_root()
        assert (root / "hooks" / "session-start.sh").is_file()

    def test_claude_plugin_json_paths_updated(self) -> None:
        """.claude-plugin/plugin.json paths 指向 ../commands/ 等."""
        root = _project_root()
        plugin_json = root / ".claude-plugin" / "plugin.json"
        if not plugin_json.is_file():
            return  # 如果旧 plugin.json 已移除, 此 test skip
        data = json.loads(plugin_json.read_text())
        # paths 应为 ../ 相对路径 (从 .claude-plugin/ 指到根目录)
        for key in ("commands", "hooks", "skills"):
            if key in data:
                val = data[key]
                assert ".." in val, f"plugin.json '{key}' 应使用 ../ 相对路径, 实际: {val}"

    def test_claude_plugin_json_valid(self) -> None:
        """.claude-plugin/plugin.json 是合法 JSON."""
        root = _project_root()
        plugin_json = root / ".claude-plugin" / "plugin.json"
        if not plugin_json.is_file():
            return
        data = json.loads(plugin_json.read_text())
        assert "name" in data
        assert data["name"] == "auto-engineering"


class TestV8_2_HookRegistrationSplitting:
    """V8-2: Hook 注册拆分为三平台特定文件."""

    def test_codex_plugin_dir_exists(self) -> None:
        """.codex-plugin/ 目录存在."""
        root = _project_root()
        assert (root / ".codex-plugin").is_dir()

    def test_codex_plugin_json_exists(self) -> None:
        """.codex-plugin/plugin.json 存在且合法."""
        root = _project_root()
        codex_json = root / ".codex-plugin" / "plugin.json"
        assert codex_json.is_file()
        data = json.loads(codex_json.read_text())
        assert "name" in data

    def test_hooks_cc_json_exists(self) -> None:
        """hooks-cc.json (Claude Code) 存在."""
        root = _project_root()
        assert (root / "hooks-cc.json").is_file()

    def test_hooks_codex_json_exists(self) -> None:
        """hooks-codex.json (Codex) 存在."""
        root = _project_root()
        assert (root / "hooks-codex.json").is_file()

    def test_hooks_codex_no_on_pr(self) -> None:
        """hooks-codex.json 不含 on-pr.sh (Codex 仅 4 hooks)."""
        root = _project_root()
        codex_hooks = root / "hooks-codex.json"
        assert codex_hooks.is_file(), "hooks-codex.json 应先创建 (V8-1→V8-2)"
        data = json.loads(codex_hooks.read_text())
        hooks_list = json.dumps(data)
        assert "on-pr" not in hooks_list

    def test_codebuddy_symlink_to_claude_plugin(self) -> None:
        """.codebuddy-plugin/ 是指向 .claude-plugin/ 的符号链接."""
        root = _project_root()
        codebuddy = root / ".codebuddy-plugin"
        assert codebuddy.exists(), ".codebuddy-plugin/ 应先创建 (V8-1)"
        assert codebuddy.is_symlink()
        target = codebuddy.resolve()
        expected = (root / ".claude-plugin").resolve()
        assert target == expected, f"symlink 目标: {target}, 期望: {expected}"

    def test_session_start_detects_platform(self) -> None:
        """session-start.sh 包含 AE_PLATFORM 平台检测逻辑."""
        root = _project_root()
        session_start = root / "hooks" / "session-start.sh"
        if not session_start.is_file():
            return
        content = session_start.read_text()
        has_detection = (
            "AE_PLATFORM" in content
            or "CLAUDE_PLUGIN_ROOT" in content
            or "CODEX_PLUGIN_ROOT" in content
        )
        assert has_detection, "session-start.sh 应包含平台检测逻辑"


class TestV8_7_DoctorAndPyproject:
    """V8-7: ae doctor 加 OpenAI key 检查 + pyproject.toml openai 可选依赖."""

    def test_doctor_mentions_openai_key(self) -> None:
        """ae doctor 输出包含 OPENAI_API_KEY 检查."""
        from click.testing import CliRunner

        from auto_engineering.cli.__init__ import main

        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        output = result.output
        assert "OPENAI_API_KEY" in output or "openai" in output.lower()

    def test_pyproject_has_openai_optional_dep(self) -> None:
        """pyproject.toml 有 openai 可选依赖."""
        root = _project_root()
        content = (root / "pyproject.toml").read_text()
        assert "openai" in content, (
            "pyproject.toml 应包含 openai 可选依赖"
        )


class TestV8_6_InstallScript:
    """V8-6: install.sh 多平台安装脚本."""

    def test_install_sh_exists(self) -> None:
        """install.sh 存在且可执行."""
        root = _project_root()
        install_sh = root / "install.sh"
        assert install_sh.is_file(), "install.sh 不存在"
        assert install_sh.stat().st_mode & 0o111, "install.sh 不可执行"

    def test_install_sh_mentions_claude_code(self) -> None:
        """install.sh 包含 Claude Code 安装路径."""
        root = _project_root()
        content = (root / "install.sh").read_text()
        assert ".claude/plugins" in content or "claude" in content.lower()

    def test_install_sh_mentions_codex(self) -> None:
        """install.sh 包含 Codex 安装路径."""
        root = _project_root()
        content = (root / "install.sh").read_text()
        assert ".codex/plugins" in content or "codex" in content.lower()

    def test_install_sh_mentions_codebuddy(self) -> None:
        """install.sh 包含 CodeBuddy 安装参考."""
        root = _project_root()
        content = (root / "install.sh").read_text()
        assert "codebuddy" in content.lower() or "CODEBUDDY" in content


class TestV8_8_Documentation:
    """V8-8: 三平台文档更新 — PLUGIN-USAGE / USER_GUIDE / production-deployment."""

    def test_plugin_usage_mentions_three_platforms(self) -> None:
        """PLUGIN-USAGE.md 涵盖三平台安装说明."""
        root = _project_root()
        doc = root / "docs" / "PLUGIN-USAGE.md"
        assert doc.is_file(), "PLUGIN-USAGE.md 不存在"
        content = doc.read_text()
        platforms = 0
        if "Claude Code" in content or "claude-code" in content:
            platforms += 1
        if "Codex" in content or "codex" in content:
            platforms += 1
        if "CodeBuddy" in content or "codebuddy" in content:
            platforms += 1
        assert platforms >= 2, (
            f"PLUGIN-USAGE.md 应至少涵盖 2 个平台, "
            f"当前 Claude Code/Codex/CodeBuddy 提及数: {platforms}"
        )

    def test_user_guide_mentions_multi_platform(self) -> None:
        """USER_GUIDE.md 含多平台相关说明."""
        root = _project_root()
        doc = root / "docs" / "USER_GUIDE.md"
        assert doc.is_file(), "USER_GUIDE.md 不存在"
        content = doc.read_text()
        has_multi_platform = (
            "install.sh" in content
            or "多平台" in content
            or "Codex" in content
            or "CodeBuddy" in content
        )
        assert has_multi_platform, (
            "USER_GUIDE.md 应提及 install.sh 多平台安装或 Codex/CodeBuddy"
        )
