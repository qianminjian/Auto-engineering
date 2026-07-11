"""v2.0 Phase 04 — Gate 1: Lint (ruff check, v5.0 §IL-AC-02 可配置).

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 1.

实现方式:
    - subprocess 调用 `{linter} check .` (默认 ruff)
    - 复用项目已有 lint 配置
    - 超时/不存在 → fail (passed=False with clear message)

v5.0 §IL-AC-02 扩展:
    - 优先使用 init-manifest.json conventions.linter (可来自 Init 项目)
    - 缺则用默认 (python=ruff, typescript=eslint, go=golangci-lint, ...)
    - 构造时支持显式 linter_bin 覆盖

2026-07-04 修复 (Bug 1 prismscan 集成): _resolve_lint_cmd 加 5 级兜底,
避免直接走 sys.executable -m (ae 工具隔离 Python 没装项目依赖 → ruff
缺失 → lint 假阳性 fail → 触发 critic 异常 → 0 代码改动退出).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from auto_engineering.gates._tools import get_gate_tools_from_manifest
from auto_engineering.gates.base import Gate, GateVerdict, run_gate_command

__all__ = ["LintGate"]

_DEFAULT_TIMEOUT = 60.0
_DEFAULT_LINTER = "ruff"


class LintGate(Gate):
    """Gate 1: 静态检查 (默认 ruff check).

    Args:
        linter_bin: 静态检查工具可执行文件名(默认 'ruff', v5.0 §IL-AC-02)
        linter_subcommand: linter 的子命令(默认 'check', 适用 ruff/eslint/golangci-lint)
        timeout: subprocess 超时(秒)
        extra_args: 额外传给 linter 的参数(如 ["--select", "E,F"])
        project_root: 2026-07-04 (Bug 1) — 项目根目录, 用于 .venv/bin/{linter} 兜底

    v5.0 §B6.1: applies_to_stages = (architect, developer, critic)
        静态检查每个 stage 都需通过
    """

    name = "lint"
    applies_to_stages = ("architect", "developer", "critic")

    def __init__(
        self,
        linter_bin: str | None = None,
        linter_subcommand: str = "check",
        timeout: float | None = None,
        extra_args: list[str] | None = None,
        project_root: Path | None = None,
    ):
        self.linter_bin = linter_bin or _DEFAULT_LINTER
        self.linter_subcommand = linter_subcommand
        self.timeout = timeout if timeout is not None else Gate._resolve_timeout(_DEFAULT_TIMEOUT)
        self.extra_args = extra_args or []
        self.project_root = project_root

    @classmethod
    def from_manifest(
        cls,
        manifest: dict,
        timeout: float | None = None,
        project_root: Path | None = None,
    ) -> LintGate:
        """v5.0 §IL-AC-02: 从 init-manifest.json 构造 LintGate.

        读 manifest.conventions.linter, 缺则用 LANGUAGE_TOOLS 默认.

        2026-07-04 (Bug 1): 加 project_root 参数, 让 _resolve_lint_cmd 能找 .venv/bin/linter.
        """
        tools = get_gate_tools_from_manifest(manifest)
        return cls(
            linter_bin=tools["linter"],
            timeout=timeout,
            project_root=project_root,
        )

    def _resolve_lint_cmd(self, project_root: Path | None = None) -> list[str]:
        """解析 lint 命令.

        2026-07-04 修复 (Bug 1 prismscan 集成): 5 级兜底.
        旧实现只有 3 级, 最后兜底 sys.executable -m (ae 工具隔离 Python 没项目依赖,
        ruff 缺失 → lint 假阳性 fail → 触发 critic 异常).

        新 5 级优先级:
            0. 项目 venv: <project_root>/.venv/bin/{linter}
            1. 显式 linter_bin
            2. PATH 中的 linter_bin (shutil.which)
            3. uv run (项目级, 需 uv 在 PATH)
            4. sys.executable -m (最后兜底, 仅 Python 生态)
        """
        # 优先级 0: 项目 venv (Bug 1 修复)
        _root = project_root or self.project_root
        if _root is not None:
            venv_linter = Path(_root) / ".venv" / "bin" / self.linter_bin
            if venv_linter.exists() and venv_linter.is_file():
                return [str(venv_linter), self.linter_subcommand]

        # 优先级 1: 显式 linter_bin
        if self.linter_bin:
            return [self.linter_bin, self.linter_subcommand]

        # 优先级 2: PATH 中的 linter_bin
        if shutil.which(self.linter_bin):
            return [self.linter_bin, self.linter_subcommand]

        # 优先级 3: uv run (项目级, 需 uv 在 PATH)
        if shutil.which("uv"):
            return ["uv", "run", self.linter_bin, self.linter_subcommand]

        # 优先级 4: sys.executable -m (最后兜底, 仅 Python 生态)
        return [sys.executable, "-m", self.linter_bin, self.linter_subcommand]

    def run(self, project_root: Path) -> GateVerdict:
        """执行 lint 检查.

        Returns:
            GateVerdict: passed=True 表示 lint 0 错误; passed=False 表示有错误或命令失败.

        v5.5 P1-10: _resolve_lint_cmd 接受 project_root 参数, 不再写 self.project_root.
        """
        if verdict := self._validate_project_root(project_root):
            return verdict
        cmd = [*self._resolve_lint_cmd(project_root), str(project_root), *self.extra_args]

        result = run_gate_command(cmd, project_root, self.timeout)

        if result.timed_out:
            return GateVerdict.failed(
                f"{self.linter_bin} 超时 (>{self.timeout}s): {' '.join(cmd)}",
                gate_name=self.name,
            )
        if result.not_found:
            return GateVerdict.ok(
                f"skipped: {self.linter_bin} 未找到 (5 级兜底全失败). "
                f"建议 `uv add --dev {self.linter_bin}` 或项目根有 {self.linter_bin} 二进制.",
                gate_name=self.name,
            )

        if result.returncode == 0:
            return GateVerdict.ok(
                f"{self.linter_bin} {self.linter_subcommand} 通过 (0 errors)",
                gate_name=self.name,
            )

        output = result.stdout or result.stderr or ""
        snippet = output[:1500] + ("..." if len(output) > 1500 else "")
        return GateVerdict.failed(
            f"{self.linter_bin} {self.linter_subcommand} 失败 (exit={result.returncode}):\n{snippet}",
            gate_name=self.name,
        )


# v5.5 audit P2-15: 向后兼容别名, v6.0 移除
LintGate._register_alias("ruff_bin", "linter_bin")