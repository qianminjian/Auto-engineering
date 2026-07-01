"""test_tools_extended — tools/test_tools.py 64% → ≥90% (Phase 12.12).

覆盖目标:
- L67-74: TimeoutExpired 分支
- L77-88: _detect_runner 各分支 (pyproject.toml / pytest.ini / uv.lock / package.json / fallback)
- L40-42: cwd/timeout 参数传递
- L60-65: stdout/stderr 拼接 + tail 截断
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from auto_engineering.tools import RunTestsTool
from auto_engineering.tools.base import ToolResult


def _run(coro):
    """简易 async runner (与现有 test_tools_integration.py 一致)."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(coro)


# ============================================================
# 1. detect_runner — 5 种文件探测分支
# ============================================================


class TestDetectRunner:
    """RunTestsTool._detect_runner 路径覆盖 (5 文件探测分支 + fallback)."""

    def test_pyproject_toml_triggers_pytest(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        assert RunTestsTool._detect_runner(str(tmp_path)) == "pytest"

    def test_pytest_ini_triggers_pytest(self, tmp_path: Path) -> None:
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        assert RunTestsTool._detect_runner(str(tmp_path)) == "pytest"

    def test_uv_lock_triggers_uv(self, tmp_path: Path) -> None:
        (tmp_path / "uv.lock").write_text("# lock\n")
        assert RunTestsTool._detect_runner(str(tmp_path)) == "uv"

    def test_package_json_triggers_npm(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}\n")
        assert RunTestsTool._detect_runner(str(tmp_path)) == "npm"

    def test_no_project_files_fallback_to_pytest(self, tmp_path: Path) -> None:
        # 空目录, 无任何项目文件
        assert RunTestsTool._detect_runner(str(tmp_path)) == "pytest"

    def test_detect_runner_with_none_cwd(self) -> None:
        """cwd=None → Path('.'); 若当前目录有 pyproject.toml 则 pytest, 否则 fallback pytest."""
        # 当前项目根有 pyproject.toml, 所以应返回 pytest
        assert RunTestsTool._detect_runner(None) == "pytest"


# ============================================================
# 2. execute — timeout / 工具缺失 / subprocess 异常 / 参数
# ============================================================


class TestExecuteTimeoutAndExceptions:
    """L67-74: TimeoutExpired + Exception 分支."""

    def test_timeout_expired_returns_failure(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        tool = RunTestsTool()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=1)):
            result = _run(tool.execute(runner="pytest", cwd=str(tmp_path), timeout=1))
        assert result.success is False
        assert "timed out" in result.error.lower()
        assert "1s" in result.error

    def test_generic_exception_returns_failure(self, tmp_path: Path) -> None:
        tool = RunTestsTool()
        with patch("subprocess.run", side_effect=OSError("disk full")):
            result = _run(tool.execute(runner="pytest", cwd=str(tmp_path), timeout=10))
        assert result.success is False
        assert "disk full" in result.error


# ============================================================
# 3. execute — stdout/stderr 拼接 + tail 截断 (L60-61)
# ============================================================


class TestOutputFormatting:
    """stdout+stderr 拼接, 仅保留最后 30 行."""

    def test_output_combines_stdout_and_stderr(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        tool = RunTestsTool()

        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "line-stdout-1\nline-stdout-2\n"
        fake_result.stderr = "line-stderr-1\n"

        with patch("subprocess.run", return_value=fake_result):
            result = _run(tool.execute(runner="pytest", cwd=str(tmp_path)))
        assert result.success is True
        assert "line-stdout-1" in result.content
        assert "line-stderr-1" in result.content
        assert "pytest" in result.content  # === pytest === header

    def test_output_truncates_to_30_lines(self, tmp_path: Path) -> None:
        """输出超过 30 行 → 仅保留最后 30 行."""
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        tool = RunTestsTool()

        # 50 行输出
        many_lines = "\n".join(f"line-{i}" for i in range(50)) + "\n"

        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = many_lines
        fake_result.stderr = ""

        with patch("subprocess.run", return_value=fake_result):
            result = _run(tool.execute(runner="pytest", cwd=str(tmp_path)))
        assert result.success is False
        # line-0..19 应被截断, line-20..49 保留 (最后 30 行)
        assert "line-0" not in result.content
        assert "line-19" not in result.content
        assert "line-20" in result.content
        assert "line-49" in result.content

    def test_output_handles_none_stdout_stderr(self, tmp_path: Path) -> None:
        """stdout/stderr 为 None → 空字符串 (L60: or '')."""
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        tool = RunTestsTool()

        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = None
        fake_result.stderr = None

        with patch("subprocess.run", return_value=fake_result):
            result = _run(tool.execute(runner="pytest", cwd=str(tmp_path)))
        assert result.success is True
        # 不应崩溃, content 应包含 header
        assert "=== pytest ===" in result.content


# ============================================================
# 4. execute — auto-detect runner via cwd
# ============================================================


class TestAutoDetectInExecute:
    """runner=None + cwd=含 package.json → 自动选 npm."""

    def test_auto_detect_npm_via_cwd(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"scripts":{"test":"echo hi"}}\n')
        tool = RunTestsTool()

        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "hi\n"
        fake_result.stderr = ""

        with patch("subprocess.run", return_value=fake_result) as mock_run:
            result = _run(tool.execute(cwd=str(tmp_path)))
        assert result.success is True
        # cmd 应是 npm test
        called_cmd = mock_run.call_args[0][0]
        assert called_cmd[0] == "npm"
        assert called_cmd[1] == "test"


# ============================================================
# 5. tool metadata
# ============================================================


class TestToolMetadata:
    """name/description/parameters 元数据."""

    def test_tool_name_and_description(self) -> None:
        tool = RunTestsTool()
        assert tool.name == "run_tests"
        assert "test" in tool.description.lower()

    def test_parameters_schema(self) -> None:
        tool = RunTestsTool()
        params = tool.parameters
        assert "scope" in params
        assert "runner" in params
        assert "cwd" in params
        assert "timeout" in params
        assert params["timeout"]["type"] == "integer"