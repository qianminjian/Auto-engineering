"""Git 工具 — v2.0 真接.
3 个工具: GitStatus / GitCommit / GitDiff.

2026-07-04 修复 (v5.0 深度审计 P1-S-02): 加 project_root 白名单沙箱.
之前 _run_git 接受任意 cwd, 无沙箱验证 (与 file_tools 不一致).
现在: 3 个 Git Tool 都接受 project_root 参数 (与 file_tools 同模式),
_run_git 跑前 realpath 验证 cwd 在 project_root 内, 否则拒绝.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, ClassVar

from .base import BaseTool, ToolResult


def _run_git(args: list[str], cwd: str | None, project_root: Path | None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Helper: 跑 git 命令 + timeout + 沙箱验证.

    P1-S-02 (2026-07-04): 加 project_root 沙箱验证, realpath 双侧归一化
    (与 file_tools._is_path_safe 同模式, 防御 macOS symlink).
    """
    if project_root is not None and cwd is not None:
        try:
            root_real = os.path.realpath(project_root)
            target_real = os.path.realpath(cwd)
            root_prefix = root_real if root_real.endswith(os.sep) else root_real + os.sep
            if not (target_real == root_real or target_real.startswith(root_prefix)):
                raise ValueError(
                    f"git cwd outside project_root: {cwd} (resolved={target_real})"
                )
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"invalid git cwd: {cwd} ({e})") from e
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class GitStatusTool(BaseTool):
    """Show git working tree status."""

    name = "git_status"
    description = "Show git status. Returns porcelain-format output."
    parameters: ClassVar[dict] = {
        "cwd": {"type": "string", "description": "Repository path (optional)"},
    }

    def __init__(self, project_root: Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.project_root = project_root

    async def execute(self, **kwargs) -> ToolResult:
        cwd = kwargs.get("cwd")
        try:
            result = _run_git(["status", "--porcelain"], cwd=cwd, project_root=self.project_root)
            if result.returncode != 0:
                return ToolResult(success=False, content="", error=result.stderr.strip())
            return ToolResult(
                success=True,
                content=result.stdout.strip() or "(clean)",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content="", error="git status timeout")
        except ValueError as exc:
            return ToolResult(success=False, content="", error=str(exc))
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))


class GitCommitTool(BaseTool):
    """Commit all staged changes with a message."""

    name = "git_commit"
    description = "Stage all changes and commit with message."
    parameters: ClassVar[dict] = {
        "message": {"type": "string", "description": "Commit message"},
        "cwd": {"type": "string", "description": "Repository path (optional)"},
    }

    def __init__(self, project_root: Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.project_root = project_root

    async def execute(self, **kwargs) -> ToolResult:
        cwd = kwargs.get("cwd")
        message = kwargs.get("message", "")
        try:
            if not message:
                return ToolResult(success=False, content="", error="commit message is empty")
            add_result = _run_git(["add", "-A"], cwd=cwd, project_root=self.project_root)
            if add_result.returncode != 0:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"git add failed: {add_result.stderr.strip()}",
                )
            commit_result = _run_git(["commit", "-m", message], cwd=cwd, project_root=self.project_root)
            if commit_result.returncode != 0:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"git commit failed: {commit_result.stderr.strip()}",
                )
            return ToolResult(
                success=True,
                content=commit_result.stdout.strip() or "(commit created)",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content="", error="git commit timeout")
        except ValueError as exc:
            return ToolResult(success=False, content="", error=str(exc))
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))


class GitDiffTool(BaseTool):
    """Show git diff for staged or unstaged changes."""

    name = "git_diff"
    description = "Show git diff. Default shows unstaged. Set staged=true for staged."
    parameters: ClassVar[dict] = {
        "staged": {"type": "boolean", "description": "Show staged diff (default false)"},
        "target": {"type": "string", "description": "Compare against ref/branch (e.g. HEAD~1)"},
        "cwd": {"type": "string", "description": "Repository path (optional)"},
    }

    def __init__(self, project_root: Path | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.project_root = project_root

    async def execute(self, **kwargs) -> ToolResult:
        cwd = kwargs.get("cwd")
        staged = kwargs.get("staged", False)
        target = kwargs.get("target")
        try:
            args = ["diff", "--stat", "-p"]
            if staged:
                args.append("--cached")
            if target:
                args.append(target)
            result = _run_git(args, cwd=cwd, project_root=self.project_root)
            if result.returncode != 0:
                return ToolResult(success=False, content="", error=result.stderr.strip())
            return ToolResult(
                success=True,
                content=result.stdout.strip() or "(no changes)",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content="", error="git diff timeout")
        except ValueError as exc:
            return ToolResult(success=False, content="", error=str(exc))
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))