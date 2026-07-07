"""Git CLI 工具函数 (v5.5 审计 P2-12/P2-16: 从 orchestrator + guardrail 提取).

统一所有 git subprocess 调用, 避免重复实现.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

_logger = logging.getLogger("ae.utils.git")


def run_git(root: Path | str, *args: str, timeout: int = 10) -> tuple[int, str]:
    """同步跑 git 命令, 返回 (rc, stdout).

    stderr 丢弃 (避免污染结果). 异常 → rc=255, stdout="".
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 255, ""


def capture_head(project_root: Path | str | None) -> str | None:
    """捕获当前 HEAD commit hash, 供 git diff 稳定基线."""
    cwd = str(project_root) if project_root is not None else "."
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except FileNotFoundError:
        return None
    except (subprocess.TimeoutExpired, OSError) as exc:
        _logger.warning(
            "git rev-parse HEAD 失败 (cwd=%s): %s", cwd, exc
        )
        return None


def run_git_diff(root: Path, diff_args: list[str]) -> tuple[int, str]:
    """git diff --numstat 封装.

    Args:
        root: 项目根.
        diff_args: 传给 git diff 的参数 (e.g. ["HEAD~1..HEAD"] 或 ["--cached"]).

    Returns:
        (rc, stdout). stdout 为空表示无 diff.
    """
    return run_git(root, "diff", "--numstat", *diff_args)
