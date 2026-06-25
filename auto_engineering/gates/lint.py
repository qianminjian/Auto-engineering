"""v2.0 Phase 04 — Gate 1: Lint (ruff check).

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 1.

实现方式:
    - subprocess 调用 `ruff check .`
    - 复用项目已有 ruff 配置
    - 超时/不存在 → fail (passed=False with clear message)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from auto_engineering.gates.base import Gate, Verdict

_DEFAULT_TIMEOUT = 60.0


class LintGate(Gate):
    """Gate 1: ruff check 静态检查.

    Args:
        ruff_bin: ruff 可执行文件路径(默认从 PATH 查找, 若 None 则尝试 sys.executable -m ruff)
        timeout: subprocess 超时(秒)
        extra_args: 额外传给 ruff 的参数(如 ["--select", "E,F"])
    """

    name = "lint"

    def __init__(
        self,
        ruff_bin: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        extra_args: list[str] | None = None,
    ):
        self.ruff_bin = ruff_bin
        self.timeout = timeout
        self.extra_args = extra_args or []

    def _resolve_ruff_cmd(self) -> list[str]:
        """解析 ruff 命令.

        优先级:
            1. 显式 ruff_bin(若指定)
            2. PATH 中的 ruff
            3. sys.executable -m ruff (兜底, 兼容 venv 中 ruff)
        """
        if self.ruff_bin:
            return [self.ruff_bin, "check"]
        if shutil.which("ruff"):
            return ["ruff", "check"]
        # 兜底: 当前 Python 解释器 -m ruff (若 venv 安装)
        return [sys.executable, "-m", "ruff", "check"]

    def run(self, project_root: Path) -> Verdict:
        """执行 lint 检查.

        Returns:
            Verdict: passed=True 表示 ruff 0 错误; passed=False 表示有错误或命令失败.
        """
        project_root = Path(project_root)
        if not project_root.exists():
            return Verdict.failed(
                f"project_root 不存在: {project_root}",
                gate_name=self.name,
            )

        cmd = [*self._resolve_ruff_cmd(), str(project_root), *self.extra_args]

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
                f"ruff 超时 (>{self.timeout}s): {' '.join(cmd)}",
                gate_name=self.name,
            )
        except FileNotFoundError as e:
            return Verdict.failed(
                f"ruff 命令未找到 ({e}): {' '.join(cmd)}",
                gate_name=self.name,
            )

        if result.returncode == 0:
            return Verdict.passed("ruff check 通过 (0 errors)", gate_name=self.name)

        # ruff 输出: stdout 或 stderr(取决于 config)
        output = result.stdout or result.stderr or ""
        # 截断到 1500 字符
        snippet = output[:1500] + ("..." if len(output) > 1500 else "")
        return Verdict.failed(
            f"ruff check 失败 (exit={result.returncode}):\n{snippet}",
            gate_name=self.name,
        )