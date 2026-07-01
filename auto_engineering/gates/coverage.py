"""⚠️ 冻结 (FROZEN) — CoverageGate 名存实亡, 保留仅为向后兼容.

冻结标记: 2026-06-27 (v2.4 P0-C)
BEACON 决策 25: CoverageGate 冻结 — Gate 永远返回 "skip: 未提取到覆盖率数据",
因为本项目未安装 pytest-cov, pyproject.toml addopts 不含 --cov.

为什么不激活 CoverageGate (决策 25 选择 b 冻结而非 a 安装):

    (a) 安装 pytest-cov + pyproject.toml addopts 加 --cov=auto_engineering:
        - 风险: pytest + cov instrumentation ~2x 内存 (见 .claude/rules/pytest-memory-management.md)
        - 后果: 全量 pytest 跑可能爆 16G 物理内存, 触发 macOS vm-compressor
        - 缓解: 加 --no-cov on dev-loop, 但与全局 addopts 冲突, 需要 ci-only 配置
        - 实际产物: dev-loop 内单进程跑 coverage 收益低 (数据不全, 漏 CLI / 集成路径)

    (b) 冻结 CoverageGate + 引导 CI 负责: 选择本方案
        - dev-loop 内: Gate 跑 → 永远返回 skip Verdict (保持向后兼容)
        - CI (.github/workflows/): 配独立 coverage job, 独立环境/独立内存预算
        - 与"冻结 + 引导迁移"模式一致 (历史参考: builtin.py 决策 22,
          engine/checkpoint.py 决策 24 — 两者本身 v2.5 P0-FINAL 删除,
          决策 22/24 被决策 27 撤销; CoverageGate 决策 25 保留 —
          pytest-cov 仍未装, 内存约束仍在, 冻结理由独立成立)
        - 真实覆盖率数据走 CI artifact, 不污染 dev-loop 主循环

设计要点 (保留):
    - 解析 pytest --cov 输出 TOTAL 行, 计算百分比
    - threshold 默认 80.0%, strict=False (低于阈值仅 warn, 不阻塞 dev-loop)
    - 永远返回 passed=True 的 Verdict (drop 语义, 不阻塞开发循环)

历史:
    - v2.0 Phase 04 (设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 5)
    - v2.4 P0-C 冻结 (2026-06-27): 见 BEACON 决策 25

替代方案:
    - CI 配置独立 coverage 检查 (推荐路径)
    - 重构 Gate 为 optional + 用户显式 opt-in (未来 v3.0+ 决策)
"""

from __future__ import annotations

import re
import shutil
import subprocess
import warnings
from pathlib import Path

from auto_engineering.gates.base import Gate, Verdict

DEFAULT_TIMEOUT = 120.0
DEFAULT_THRESHOLD = 80.0
DEFAULT_COV_TARGET = "auto_engineering"

# pytest-cov output 总覆盖率正则
_TOTAL_COV_RE = re.compile(r"TOTAL\s+\d+\s+\d+\s+(\d+)%")

# DeprecationWarning: 每 N 次 run 触发 1 次 (避免刷屏, 保留信号)
_WARN_EVERY_N_RUNS = 5
_run_counter = 0


def _emit_freeze_warning() -> None:
    """触发一次 DeprecationWarning — 通知调用方 CoverageGate 已冻结.

    策略: 全局计数器, 每 5 次 run 触发 1 次 (避免每次 run 都刷屏).
    保留信号: 用户 / CI 能看到至少 1 次警告, 知道 Gate 失效.
    """
    global _run_counter
    _run_counter += 1
    if _run_counter % _WARN_EVERY_N_RUNS == 1:  # 1, 6, 11, ...
        warnings.warn(
            "CoverageGate 已冻结 (BEACON 决策 25, 2026-06-27): "
            "本 Gate 永远返回 'skip: 未提取到覆盖率数据', "
            "因为本项目未安装 pytest-cov. 真实覆盖率检查应在 CI (.github/workflows/) 独立配置. "
            "dev-loop 内此 Gate 不阻塞, 但不产生有意义数据.",
            DeprecationWarning,
            stacklevel=2,
        )


class CoverageGate(Gate):
    """Gate 5: pytest + coverage 阈值检查.

    Args:
        threshold: 覆盖率阈值百分比(默认 80.0)
        cov_target: --cov=<target>(默认 "auto_engineering")
        pytest_bin: pytest 命令路径
        timeout: subprocess 超时(秒)
        strict: True = 低于阈值失败; False = 仅 warning(passed=True)

    v5.0 §B6.1: applies_to_stages = ("developer",)
        覆盖率仅在 developer 阶段跑 (有代码产出才有意义).
        BEACON 决策 25: 永远 skip, 仅作注册.
    """

    name = "coverage"
    applies_to_stages = ("developer",)

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
        # v2.4 P0-C 冻结 (BEACON 决策 25): 触发 DeprecationWarning 信号
        _emit_freeze_warning()

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