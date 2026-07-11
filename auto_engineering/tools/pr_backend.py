"""pr_backend.py — PR 后端抽象层 (B13.9 #8 / B14 内化约束).

`code-review.md` / dev-loop `done` 阶段创建 PR 时不再硬编码 `gh`，改为委托
`PRBackend`。呼应 B13.6 CI 双平台 (GitHub Actions + GitLab CI)：单一逻辑入口
(create_pr) + 平台薄壳 (gh / glab)，DRY。

后端选型由 Init-Loop manifest 的 `conventions.ci_platform` 驱动 (github/gitlab/
none)；none → 按 PATH 可用性自动探测 (优先 github)。`gh`/`glab` 属**必要系统
依赖** (B14.1)，不内化但需 doctor 预检 (`available_backends`)。

参考: v5.6-Design-Loop.md §B13.9 #8 / §B14.1。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "GitHubBackend",
    "GitLabBackend",
    "PRBackend",
    "PRResult",
    "available_backends",
    "select_backend",
]

_logger = logging.getLogger("ae.tools.pr_backend")

# runner: (args, cwd, timeout) → CompletedProcess-like (returncode/stdout/stderr).
# 注入点 — 测试可传 fake runner 隔离真实 gh/glab/网络.
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _default_runner(
    args: list[str], cwd: str | None = None, timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, timeout=timeout
    )


@dataclass
class PRResult:
    """PR 创建结果. success=False 时 error 含可操作原因 (不静默假成功)."""
    success: bool
    url: str = ""
    error: str = ""


class PRBackend(ABC):
    """PR 后端抽象基类 — 单一逻辑入口 create_pr + 平台薄壳."""

    name: str = ""      # manifest ci_platform 值 (github/gitlab)
    cli: str = ""       # 平台 CLI 二进制名 (gh/glab)

    def __init__(
        self,
        *,
        runner: Runner | None = None,
        project_root: Path | str | None = None,
    ) -> None:
        self._runner: Runner = runner or _default_runner
        self.project_root = project_root

    def is_available(self) -> bool:
        """CLI 是否在 PATH — doctor 预检 + create_pr 前置校验."""
        return shutil.which(self.cli) is not None

    @abstractmethod
    def _build_create_args(
        self, title: str, body: str, base: str, head: str | None
    ) -> list[str]:
        """构造平台 CLI 的 PR 创建参数 (平台薄壳)."""

    def create_pr(
        self, *, title: str, body: str, base: str = "main", head: str | None = None
    ) -> PRResult:
        if not self.is_available():
            return PRResult(
                success=False,
                error=f"{self.cli} 不可用 (PATH 未找到)；请安装或改用其他 PR 后端",
            )
        args = self._build_create_args(title, body, base, head)
        cwd = str(self.project_root) if self.project_root else None
        try:
            proc = self._runner(args, cwd=cwd)
        except (subprocess.TimeoutExpired, OSError) as e:
            _logger.error("%s create_pr 失败: %s", self.cli, e, exc_info=True)
            return PRResult(success=False, error=f"{self.cli} 执行失败: {e}")
        if proc.returncode != 0:
            return PRResult(
                success=False,
                error=(proc.stderr or "").strip()
                or f"{self.cli} 退出码 {proc.returncode}",
            )
        return PRResult(success=True, url=(proc.stdout or "").strip())


class GitHubBackend(PRBackend):
    """GitHub 后端 — gh pr create."""

    name = "github"
    cli = "gh"

    def _build_create_args(
        self, title: str, body: str, base: str, head: str | None
    ) -> list[str]:
        args = ["gh", "pr", "create", "--title", title, "--body", body,
                "--base", base]
        if head:
            args += ["--head", head]
        return args


class GitLabBackend(PRBackend):
    """GitLab 后端 — glab mr create (非交互 --yes)."""

    name = "gitlab"
    cli = "glab"

    def _build_create_args(
        self, title: str, body: str, base: str, head: str | None
    ) -> list[str]:
        args = ["glab", "mr", "create", "--title", title, "--description", body,
                "--target-branch", base, "--yes"]
        if head:
            args += ["--source-branch", head]
        return args


# 探测顺序: github 优先 (auto-detect 平局时的确定性)。
_BACKENDS: tuple[type[PRBackend], ...] = (GitHubBackend, GitLabBackend)
_BY_NAME = {cls.name: cls for cls in _BACKENDS}


def select_backend(
    ci_platform: str | None = None,
    *,
    runner: Runner | None = None,
    project_root: Path | str | None = None,
) -> PRBackend | None:
    """按 ci_platform 选后端；none/未知 → 按 PATH 可用性自动探测 (github 优先).

    Returns None 当没有任何 PR 后端 CLI 可用 (调用方应降级为提示手动创建 PR).
    """
    cls = _BY_NAME.get((ci_platform or "").lower())
    if cls is not None:
        return cls(runner=runner, project_root=project_root)
    for candidate in _BACKENDS:
        backend = candidate(runner=runner, project_root=project_root)
        if backend.is_available():
            return backend
    return None


def available_backends(*, runner: Runner | None = None) -> list[str]:
    """doctor 预检: 返回当前 PATH 可用的 PR 后端 name 列表 (可能为空)."""
    return [
        cls.name
        for cls in _BACKENDS
        if cls(runner=runner).is_available()
    ]
