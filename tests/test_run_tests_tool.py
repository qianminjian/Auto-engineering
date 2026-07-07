"""v5.5 audit P1-4: RunTestsTool 测试."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestRunTestsToolBasics:
    """RunTestsTool 默认构造 + 元数据."""

    def test_default_construction(self):
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        tool = RunTestsTool()
        assert tool.name == "run_tests"
        assert "scope" in tool.parameters
        assert "runner" in tool.parameters
        assert "cwd" in tool.parameters
        assert "timeout" in tool.parameters


class TestDetectRunner:
    """RunTestsTool._detect_runner 项目类型检测."""

    def test_detect_pytest_from_pyproject(self, tmp_path: Path):
        """pyproject.toml 存在 → 返回 pytest."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        (tmp_path / "pyproject.toml").write_text("[project]\nname='x'")
        runner = RunTestsTool._detect_runner(str(tmp_path))
        assert runner == "pytest"

    def test_detect_pytest_from_pytest_ini(self, tmp_path: Path):
        """pytest.ini 存在 → 返回 pytest."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        runner = RunTestsTool._detect_runner(str(tmp_path))
        assert runner == "pytest"

    def test_detect_uv_from_uv_lock(self, tmp_path: Path):
        """uv.lock 存在 → 返回 uv."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        (tmp_path / "uv.lock").write_text("")
        runner = RunTestsTool._detect_runner(str(tmp_path))
        assert runner == "uv"

    def test_detect_npm_from_package_json(self, tmp_path: Path):
        """package.json 存在 → 返回 npm."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        (tmp_path / "package.json").write_text('{"name":"x"}')
        runner = RunTestsTool._detect_runner(str(tmp_path))
        assert runner == "npm"

    def test_detect_fallback_pytest(self, tmp_path: Path):
        """空目录 → fallback 返回 pytest."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        runner = RunTestsTool._detect_runner(str(tmp_path))
        assert runner == "pytest"

    def test_detect_priority_pyproject_over_uv_lock(self, tmp_path: Path):
        """pyproject.toml 优先级高于 uv.lock."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        (tmp_path / "pyproject.toml").write_text("")
        (tmp_path / "uv.lock").write_text("")
        runner = RunTestsTool._detect_runner(str(tmp_path))
        assert runner == "pytest"

    def test_detect_priority_pytest_ini_over_package_json(self, tmp_path: Path):
        """pytest.ini 优先级高于 package.json."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        (tmp_path / "pytest.ini").write_text("")
        (tmp_path / "package.json").write_text("{}")
        runner = RunTestsTool._detect_runner(str(tmp_path))
        assert runner == "pytest"

    def test_detect_none_cwd_uses_cwd(self, monkeypatch):
        """cwd=None → 用当前工作目录."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        # None cwd → Path(".") 也就是当前目录
        runner = RunTestsTool._detect_runner(None)
        # 当前项目有 pyproject.toml
        assert runner == "pytest"


class TestExecute:
    """RunTestsTool.execute 端到端 (mock subprocess)."""

    @pytest.mark.asyncio
    async def test_execute_unknown_runner(self):
        """未知 runner → success=False."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        tool = RunTestsTool()
        result = await tool.execute(runner="unknown-runner-xyz")
        assert result.success is False
        assert "Unknown runner" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_pytest_success(self):
        """pytest exit=0 → success=True."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "10 passed\n"
        mock_result.stderr = ""

        tool = RunTestsTool()
        with patch.object(subprocess, "run", return_value=mock_result):
            result = await tool.execute(runner="pytest", cwd="/tmp")
        assert result.success is True
        assert "pytest" in result.content

    @pytest.mark.asyncio
    async def test_execute_pytest_failure(self):
        """pytest exit≠0 → success=False."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "1 failed\n"

        tool = RunTestsTool()
        with patch.object(subprocess, "run", return_value=mock_result):
            result = await tool.execute(runner="pytest", cwd="/tmp")
        assert result.success is False
        assert "exit code 1" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        """subprocess.TimeoutExpired → success=False, 含 timeout 信息."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        tool = RunTestsTool()
        with patch.object(
            subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd=["pytest"], timeout=5),
        ):
            result = await tool.execute(runner="pytest", cwd="/tmp", timeout=5)
        assert result.success is False
        assert "timed out" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_execute_generic_exception(self):
        """通用异常 → success=False."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        tool = RunTestsTool()
        with patch.object(subprocess, "run", side_effect=OSError("disk full")):
            result = await tool.execute(runner="pytest", cwd="/tmp")
        assert result.success is False
        assert "disk full" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_auto_detect_runner(self):
        """不传 runner → 自动检测 (用 pytest 项目)."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "5 passed\n"
        mock_result.stderr = ""

        tool = RunTestsTool()
        with patch.object(subprocess, "run", return_value=mock_result):
            # 自动检测: pyproject.toml 存在 → pytest
            result = await tool.execute(cwd=".")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_output_truncation(self):
        """输出 > 30 行时截断为最后 30 行."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "\n".join(f"line {i}" for i in range(50))
        mock_result.stderr = ""

        tool = RunTestsTool()
        with patch.object(subprocess, "run", return_value=mock_result):
            result = await tool.execute(runner="pytest", cwd="/tmp")
        assert result.success is True
        # 应该包含最后 30 行 (从 line 20 开始)
        lines = result.content.splitlines()
        assert any("line 49" in line for line in lines)

    @pytest.mark.asyncio
    async def test_execute_npm_runner(self):
        """runner=npm → 用 npm test 命令."""
        from auto_engineering.tools.run_tests_tool import RunTestsTool

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "all tests passed\n"
        mock_result.stderr = ""

        tool = RunTestsTool()
        with patch.object(subprocess, "run", return_value=mock_result):
            result = await tool.execute(runner="npm", cwd="/tmp")
        assert result.success is True
        assert "npm" in result.content
