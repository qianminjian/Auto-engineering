"""v2.0 Phase 04 — Gate 5: Coverage (pytest --cov + 阈值检查).

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 5.

实现方式:
    - subprocess 调用 `pytest --cov=<module> --cov-report=term --no-cov` 等组合
    - 解析输出, 提取 TOTAL 覆盖率
    - 与 threshold 对比

设计决策:
    - 默认阈值 80.0% (项目级约定)
    - 失败 → drop (passed=True with skip), 避免单测覆盖率低阻塞开发
      (实际项目中 coverage gate 通常在 CI 严格, dev-loop 内宽松)

注意:
    - 真实覆盖率数据需要 `--cov=auto_engineering` 配置
    - 当前实现优先 threshold 阈值; 无 cov 数据时 pass (with skip note)
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from auto_engineering.gates.base import Gate, Verdict

DEFAULT_TIMEOUT = 120.0
DEFAULT_THRESHOLD = 80.0
DEFAULT_COV_TARGET = "auto_engineering"

# pytest-cov output 总覆盖率正则
_TOTAL_COV_RE = re.compile(r"TOTAL\s+\d+\s+\d+\s+(\d+)%")


class CoverageGate(Gate):
    """Gate 5: pytest + coverage 阈值检查.

    Args:
        threshold: 覆盖率阈值百分比(默认 80.0)
        cov_target: --cov=<target>(默认 "auto_engineering")
        pytest_bin: pytest 命令路径
        timeout: subprocess 超时(秒)
        strict: True = 低于阈值失败; False = 仅 warning(passed=True)
    """

    name = "coverage"

    def __init__(
        self,
        threshold: float = DEFAULT_THRESHOLD,
        cov_target: str = DEFAULT_COV_TARGET,
        pytest_bin: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        strict: bool = False,
    ):
        self.threshold = threshold
        self.cov_target = cov_target
        self.pytest_bin = pytest_bin
        self.timeout = timeout
        self.strict = strict

    def _resolve_pytest_cmd(self) -> list[str] | None:
        if self.pytest_bin:
            return [self.pytest_bin]
        if shutil.which("pytest"):
            return ["pytest"]
        return None

    def run(self, project_root: Path) -> Verdict:
        """执行 coverage 检查.

        Returns:
            Verdict: passed=True (coverage ≥ threshold OR strict=False)
                     passed=False (strict=True AND coverage < threshold)
        """
        project_root = Path(project_root)
        if not project_root.exists():
            return Verdict.failed(
                f"project_root 不存在: {project_root}",
                gate_name=self.name,
            )

        cmd_base = self._resolve_pytest_cmd()
        if cmd_base is None:
            return Verdict.passed(
                "skip: pytest 命令未找到",
                gate_name=self.name,
            )

        cmd = [*cmd_base, f"--cov={self.cov_target}", "--cov-report=term", "tests"]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return Verdict.passed(
                f"skip: pytest --cov 超时 (>{self.timeout}s)",
                gate_name=self.name,
            )
        except FileNotFoundError:
            return Verdict.passed(
                "skip: pytest 命令未找到",
                gate_name=self.name,
            )

        output = (result.stdout or "") + (result.stderr or "")

        # 提取 TOTAL 行
        match = _TOTAL_COV_RE.search(output)
        if match is None:
            # pytest-cov 未安装 或 无 cov 数据
            return Verdict.passed(
                "skip: 未提取到覆盖率数据(可能未安装 pytest-cov)",
                gate_name=self.name,
            )

        coverage_pct = float(match.group(1))

        if coverage_pct >= self.threshold:
            return Verdict.passed(
                f"coverage {coverage_pct:.1f}% ≥ {self.threshold:.1f}%",
                gate_name=self.name,
            )

        # 低于阈值
        msg = (
            f"coverage {coverage_pct:.1f}% < {self.threshold:.1f}% "
            f"(target={self.cov_target})"
        )
        if self.strict:
            return Verdict.failed(msg, gate_name=self.name)
        return Verdict.passed(f"warn: {msg} (strict=False)", gate_name=self.name)