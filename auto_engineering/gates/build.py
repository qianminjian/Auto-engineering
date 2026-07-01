"""v2.0 Phase 04 — Gate 6: Build (Python import 验证).

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 6.

实现方式 (Python 应用):
    - `python -c "import <module>"` 验证模块可导入
    - 默认验证 auto_engineering
    - 失败 → fail (passed=False)

设计决策:
    - 不跑 `pip install .` / `python -m build` (过重, dev-loop 内不合适)
    - 仅验证核心模块 import 即可证明构建基本健康
    - 完整 wheel build 在 CI / 发布前跑
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from auto_engineering.gates.base import Gate, Verdict

DEFAULT_TIMEOUT = 30.0


class BuildGate(Gate):
    """Gate 6: Python 模块导入验证.

    Args:
        module: 要验证可导入的模块名(默认 "auto_engineering")
        timeout: subprocess 超时(秒)
        cwd: 工作目录(None = 当前目录)

    v5.0 §B6.1: applies_to_stages = ("developer",)
        构建验证仅在 developer 阶段跑 (有代码产出才有意义)
    """

    name = "build"
    applies_to_stages = ("developer",)

    def __init__(
        self,
        module: str = "auto_engineering",
        timeout: float = DEFAULT_TIMEOUT,
        cwd: Path | None = None,
    ):
        self.module = module
        self.timeout = timeout
        self.cwd = cwd

    def run(self, project_root: Path | None = None) -> Verdict:
        """执行 build 验证.

        Args:
            project_root: 项目根目录(用于设置 cwd); None = 当前目录

        Returns:
            Verdict: passed=True 表示模块可导入; passed=False 表示导入失败.
        """
        cwd = Path(project_root) if project_root else (self.cwd or Path.cwd())

        cmd = [sys.executable, "-c", f"import {self.module}"]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return Verdict.failed(
                f"import 超时 (>{self.timeout}s): {' '.join(cmd)}",
                gate_name=self.name,
            )

        if result.returncode == 0:
            return Verdict.passed(
                f"import {self.module} 成功",
                gate_name=self.name,
            )

        output = (result.stdout or "") + (result.stderr or "")
        snippet = output[-1000:] if len(output) > 1000 else output
        return Verdict.failed(
            f"import {self.module} 失败 (exit={result.returncode}):\n{snippet}",
            gate_name=self.name,
        )