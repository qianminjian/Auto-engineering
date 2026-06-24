"""P1.5 — Tool 沙箱/权限控制测试.

验收:
- run_bash("rm -rf /") → error="dangerous command"
- run_bash("ls") → 正常
- run_bash("dd if=/dev/zero of=/dev/null") → error="dangerous command"
- run_bash("chmod 777 /etc/something") → error="dangerous command"
- write_file("/etc/passwd", "x") → error="path not in project_root"
- write_file("src/x.py", "x") → 正常(project_root 内)
- write_file("../outside.txt", "x") → error="path traversal"
- edit_file("/etc/hosts", ...) → error="path not in project_root"
- edit_file("src/x.py", ...) → 正常
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from auto_engineering.tools.bash_tools import RunBashTool
from auto_engineering.tools.file_tools import EditFileTool, WriteFileTool
from tests.conftest import run_async


class TestBashSandbox:
    """Bash 危险命令黑名单."""

    def test_rm_rf_root_blocked(self):
        """rm -rf / 被拦截."""
        result = run_async(RunBashTool().execute(command="rm -rf /"))
        assert result.success is False
        assert "dangerous" in result.error.lower()

    def test_dd_if_blocked(self):
        """dd if= 被拦截."""
        result = run_async(
            RunBashTool().execute(command="dd if=/dev/zero of=/dev/null bs=1M count=1")
        )
        assert result.success is False
        assert "dangerous" in result.error.lower()

    def test_mkfs_blocked(self):
        """mkfs 被拦截."""
        result = run_async(RunBashTool().execute(command="mkfs.ext4 /dev/sda1"))
        assert result.success is False
        assert "dangerous" in result.error.lower()

    def test_chmod_777_etc_blocked(self):
        """chmod 777 /etc/ 被拦截."""
        result = run_async(RunBashTool().execute(command="chmod 777 /etc/somefile"))
        assert result.success is False
        assert "dangerous" in result.error.lower()

    def test_redirect_to_etc_blocked(self):
        """> /etc/ 写 etc 被拦截."""
        result = run_async(RunBashTool().execute(command="echo x > /etc/test"))
        assert result.success is False
        assert "dangerous" in result.error.lower()

    def test_normal_ls_allowed(self):
        """ls 正常执行(允许命令)."""
        result = run_async(RunBashTool().execute(command="ls"))
        assert result.success is True

    def test_echo_allowed(self):
        """echo 正常执行."""
        result = run_async(RunBashTool().execute(command="echo hello"))
        assert result.success is True
        assert "hello" in result.content

    def test_git_status_allowed(self):
        """git status 正常执行."""
        result = run_async(RunBashTool().execute(command="git status --porcelain"))
        assert result.success is True

    def test_empty_command_rejected(self):
        """空命令被拒绝."""
        result = run_async(RunBashTool().execute(command=""))
        assert result.success is False
        assert "empty" in result.error.lower()


class TestFileSandbox:
    """文件 path 白名单(project_root 内)."""

    def setup_method(self):
        self.project_root = Path(tempfile.mkdtemp())
        self.write_tool = WriteFileTool(project_root=self.project_root)
        self.edit_tool = EditFileTool(project_root=self.project_root)

    def test_write_inside_project_allowed(self):
        """写 project_root 内文件 → 正常."""
        result = run_async(
            self.write_tool.execute(
                file_path=str(self.project_root / "src" / "x.py"),
                content="print('hello')",
            )
        )
        assert result.success is True

    def test_write_outside_project_rejected(self):
        """写 project_root 外文件 → error."""
        result = run_async(
            self.write_tool.execute(
                file_path="/etc/testfile",
                content="x",
            )
        )
        assert result.success is False
        assert "project_root" in result.error.lower()

    def test_write_etc_passwd_rejected(self):
        """/etc/passwd 写入被拒绝."""
        result = run_async(
            self.write_tool.execute(
                file_path="/etc/passwd",
                content="malicious",
            )
        )
        assert result.success is False
        assert "project_root" in result.error.lower() or "outside" in result.error.lower()

    def test_path_traversal_rejected(self):
        """../ traversal 路径被拒绝."""
        parent = self.project_root.parent
        result = run_async(
            self.write_tool.execute(
                file_path=str(parent / "outside.txt"),
                content="x",
            )
        )
        assert result.success is False
        assert "traversal" in result.error.lower() or "project_root" in result.error.lower()

    def test_edit_inside_project_allowed(self):
        """编辑 project_root 内文件 → 正常."""
        test_file = self.project_root / "test.txt"
        test_file.write_text("hello world")
        result = run_async(
            self.edit_tool.execute(
                file_path=str(test_file),
                old_string="world",
                new_string="ae",
            )
        )
        assert result.success is True

    def test_edit_outside_project_rejected(self):
        """编辑 project_root 外文件 → error."""
        result = run_async(
            self.edit_tool.execute(
                file_path="/etc/hosts",
                old_string="x",
                new_string="y",
            )
        )
        assert result.success is False
        assert "project_root" in result.error.lower() or "outside" in result.error.lower()

