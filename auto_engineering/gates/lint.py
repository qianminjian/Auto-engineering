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
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from auto_engineering.gates.base import Gate, Verdict

_DEFAULT_TIMEOUT = 60.0
_DEFAULT_LINTER = "ruff"


class LintGate(Gate):
    """Gate 1: 静态检查 (默认 ruff check).

    Args:
        linter_bin: 静态检查工具可执行文件名(默认 'ruff', v5.0 §IL-AC-02)
        linter_subcommand: linter 的子命令(默认 'check', 适用 ruff/eslint/golangci-lint)
        timeout: subprocess 超时(秒)
        extra_args: 额外传给 linter 的参数(如 ["--select", "E,F"])

    v5.0 §B6.1: applies_to_stages = (architect, developer, critic)
        静态检查每个 stage 都需通过
    """

    name = "lint"
    applies_to_stages = ("architect", "developer", "critic")

    def __init__(
        self,
        linter_bin: str | None = None,
        linter_subcommand: str = "check",
        timeout: float = _DEFAULT_TIMEOUT,
        extra_args: list[str] | None = None,
    ):
        # 向后兼容: 旧参数名 ruff_bin 改为 linter_bin
        self.linter_bin = linter_bin or _DEFAULT_LINTER
        self.linter_subcommand = linter_subcommand
        self.timeout = timeout
        self.extra_args = extra_args or []
        # 保留旧字段名 ruff_bin 以兼容已存在的 DEFAULT_GATES 构造
        self.ruff_bin: str | None = linter_bin  # 向后兼容

    @classmethod
    def from_manifest(
        cls,
        manifest: dict,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> "LintGate":
        """v5.0 §IL-AC-02: 从 init-manifest.json 构造 LintGate.

        读 manifest.conventions.linter, 缺则用 LANGUAGE_TOOLS 默认.
        """
        from auto_engineering.loop.init_contract import get_gate_tools_from_manifest

        tools = get_gate_tools_from_manifest(manifest)
        return cls(linter_bin=tools["linter"], timeout=timeout)

    def _resolve_lint_cmd(self) -> list[str]:
        """解析 lint 命令.

        优先级:
            1. 显式 linter_bin(若指定)
            2. PATH 中的 linter_bin
            3. sys.executable -m {linter_bin} (兜底, 兼容 venv 中 linter)
        """
        if self.ruff_bin:
            # 向后兼容: ruff_bin 优先 (Phase 04 旧 API)
            return [self.ruff_bin, self.linter_subcommand]
        if shutil.which(self.linter_bin):
            return [self.linter_bin, self.linter_subcommand]
        # 兜底: 当前 Python 解释器 -m linter (若 venv 安装, 仅 Python 生态)
        return [sys.executable, "-m", self.linter_bin, self.linter_subcommand]

    def run(self, project_root: Path, contracts: dict | None = None) -> Verdict:
        """执行 lint 检查.

        Args:
            project_root: 项目根目录
            contracts: v5.0 §B6.1a — 契约字典 (LintGate 不使用, 仅签名兼容)

        Returns:
            Verdict: passed=True 表示 lint 0 错误; passed=False 表示有错误或命令失败.
        """
        project_root = Path(project_root)
        if not project_root.exists():
            return Verdict.failed(
                f"project_root 不存在: {project_root}",
                gate_name=self.name,
            )

        cmd = [*self._resolve_lint_cmd(), str(project_root), *self.extra_args]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return Verdict.failed(
                f"{self.linter_bin} 超时 (>{self.timeout}s): {' '.join(cmd)}",
                gate_name=self.name,
            )
        except FileNotFoundError as e:
            return Verdict.failed(
                f"{self.linter_bin} 命令未找到 ({e}): {' '.join(cmd)}",
                gate_name=self.name,
            )

        if result.returncode == 0:
            return Verdict.passed(
                f"{self.linter_bin} {self.linter_subcommand} 通过 (0 errors)",
                gate_name=self.name,
            )

        # linter 输出: stdout 或 stderr
        output = result.stdout or result.stderr or ""
        # 截断到 1500 字符
        snippet = output[:1500] + ("..." if len(output) > 1500 else "")
        return Verdict.failed(
            f"{self.linter_bin} {self.linter_subcommand} 失败 (exit={result.returncode}):\n{snippet}",
            gate_name=self.name,
        )