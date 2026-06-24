"""Git 工具 — Phase 0.2 真接.

3 个工具: GitStatus / GitCommit / GitDiff.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .base import BaseTool, ToolResult


def _run_git(args: list[str], cwd: str | None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Helper: 跑 git 命令 + timeout + 异常处理."""
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
    parameters = {
        "cwd": {"type": "string", "description": "Repository path (optional)"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        cwd = kwargs.get("cwd")
        try:
            result = _run_git(["status", "--porcelain"], cwd=cwd)
            if result.returncode != 0:
                return ToolResult(success=False, content="", error=result.stderr.strip())
            return ToolResult(
                success=True,
                content=result.stdout.strip() or "(clean)",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content="", error="git status timeout")
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))


class GitCommitTool(BaseTool):
    """Commit all staged changes with a message."""

    name = "git_commit"
    description = "Stage all changes and commit with message."
    parameters = {
        "message": {"type": "string", "description": "Commit message"},
        "cwd": {"type": "string", "description": "Repository path (optional)"},
    }

    async def execute(self, **kwargs) -> ToolResult:
        cwd = kwargs.get("cwd")
        message = kwargs.get("message", "")
        try:
            if not message:
                return ToolResult(success=False, content="", error="commit message is empty")
            add_result = _run_git(["add", "-A"], cwd=cwd)
            if add_result.returncode != 0:
                return ToolResult(
                    success=False, content="",
                    error=f"git add failed: {add_result.stderr.strip()}",
                )
            commit_result = _run_git(["commit", "-m", message], cwd=cwd)
            if commit_result.returncode != 0:
                return ToolResult(
                    success=False, content="",
                    error=f"git commit failed: {commit_result.stderr.strip()}",
                )
            return ToolResult(
                success=True,
                content=commit_result.stdout.strip() or "(commit created)",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content="", error="git commit timeout")
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))


class GitDiffTool(BaseTool):
    """Show git diff for staged or unstaged changes."""

    name = "git_diff"
    description = "Show git diff. Default shows unstaged. Set staged=true for staged."
    parameters = {
        "staged": {"type": "boolean", "description": "Show staged diff (default false)"},
        "target": {"type": "string", "description": "Compare against ref/branch (e.g. HEAD~1)"},
        "cwd": {"type": "string", "description": "Repository path (optional)"},
    }

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
            result = _run_git(args, cwd=cwd)
            if result.returncode != 0:
                return ToolResult(success=False, content="", error=result.stderr.strip())
            return ToolResult(
                success=True,
                content=result.stdout.strip() or "(no changes)",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, content="", error="git diff timeout")
        except Exception as exc:
            return ToolResult(success=False, content="", error=str(exc))
