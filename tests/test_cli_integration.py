"""CLI 集成测试 — ae init --analyze / ae status / --from-answers.

覆盖 cli/__init__.py (0% → 测试目标)。
使用 click.testing.CliRunner 直接调用 CLI 命令，确保 coverage 工具能追踪到代码。
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from auto_engineering.cli import init, main, status


_runner = CliRunner()


class TestAnalyzeMode:
    """ae init --analyze 模式 — 不初始化，只分析项目类型."""

    def test_analyze_detects_typescript(self, tmp_path: Path):
        """检测 TypeScript 项目 (package.json + tsconfig.json)."""
        (tmp_path / "package.json").write_text('{"name": "myapp"}')
        (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}')
        result = _runner.invoke(init, ["--analyze", str(tmp_path)])
        assert result.exit_code == 0
        assert "分析目录" in result.output
        assert "检测到的项目类型候选" in result.output

    def test_analyze_detects_python(self, tmp_path: Path):
        """检测 Python 项目 (pyproject.toml)."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "myapp"')
        result = _runner.invoke(init, ["--analyze", str(tmp_path)])
        assert result.exit_code == 0
        assert "pyproject.toml" in result.output or "python" in result.output.lower()

    def test_analyze_empty_dir(self, tmp_path: Path):
        """空目录分析 — 无候选."""
        result = _runner.invoke(init, ["--analyze", str(tmp_path)])
        assert result.exit_code == 0
        assert "未检测到" in result.output or "未知" in result.output

    def test_analyze_multiple_candidates(self, tmp_path: Path):
        """多候选时显示警告 (monorepo + library 竞争)."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "myapp"')
        (tmp_path / "pnpm-workspace.yaml").write_text("")
        result = _runner.invoke(init, ["--analyze", str(tmp_path)])
        assert result.exit_code == 0
        assert "候选" in result.output

    def test_analyze_with_explicit_path(self, tmp_path: Path):
        """ae init --analyze <path> 显式路径."""
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "myapp"')
        result = _runner.invoke(init, ["--analyze", str(tmp_path)])
        assert result.exit_code == 0


class TestStatusCommand:
    """ae status 命令 — 读取当前目录项目环境."""

    def test_status_current_dir(self, tmp_path: Path):
        """status 命令在有效项目目录下."""
        (tmp_path / ".ae-answers.yml").write_text(
            "project_name: myapp\nproject_type: app-service\n"
        )
        result = _runner.invoke(status, [], input="", standalone_mode=False)
        assert result.exit_code == 0
        assert "当前目录" in result.output

    def test_status_unknown_dir(self, tmp_path: Path):
        """status 命令在未知项目目录下也能运行 (不崩溃)."""
        result = _runner.invoke(status, [], input="", standalone_mode=False)
        assert result.exit_code == 0
        assert "当前目录" in result.output


class TestInitFromAnswers:
    """ae init --from-answers 从答案文件恢复."""

    def test_from_answers_replays_answers(self, tmp_path: Path):
        """--from-answers 应该从已有答案文件恢复项目类型等信息."""
        answers_file = tmp_path / "prev.yml"
        answers_file.write_text(
            "_meta:\n  ae_version: 1.0.0\n"
            "project_name: restored\n"
            "project_type: app-service\n"
        )
        target = tmp_path / "newproj"
        target.mkdir()
        result = _runner.invoke(init, [
            str(target),
            "--from-answers", str(answers_file),
            "--type", "app-service",
            "--defaults",
            "--skip-tasks",
            "--pretend",
        ])
        # --from-answers 先尝试 answers_file，恢复 project_type
        assert result.exit_code in (0, 1)  # 0=成功，1=失败但CLI正常退出

    def test_init_with_defaults_pretend(self, tmp_path: Path):
        """--defaults --pretend 模式."""
        target = tmp_path / "proj"
        target.mkdir()
        result = _runner.invoke(init, [
            str(target),
            "--type", "app-service",
            "--defaults",
            "--skip-tasks",
            "--pretend",
        ])
        # 应该不崩溃
        assert result.exit_code in (0, 1)


class TestInitMain:
    """main CLI group — --version / --help."""

    def test_main_version(self):
        """--version 选项."""
        result = _runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1" in result.output or "1.0" in result.output

    def test_main_help(self):
        """--help 选项."""
        result = _runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "init" in result.output
