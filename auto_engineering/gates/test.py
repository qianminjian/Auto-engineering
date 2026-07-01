"""v2.0 Phase 04 — Gate 4: Test (pytest).

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 4.

约束(项目级 .claude/rules/pytest-memory-management.md):
    - 单文件 pytest + --no-cov + --timeout=60 (防内存爆炸)
    - 默认 pytest 命令: pytest --no-cov --timeout=60
    - 超时强制 fail(防 hang)
    - cov 默认关闭(避免 2x 内存叠加)

实现方式:
    - subprocess 调用 pytest
    - exit 0 → pass
    - exit 非 0 → fail(携带 stderr 输出)
    - 超时 → fail(明确告知)
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from auto_engineering.gates.base import Gate, Verdict

# 默认 timeout 与 .claude/rules/pytest-memory-management.md 对齐
DEFAULT_TIMEOUT = 60.0


class TestGate(Gate):
    """Gate 4: pytest 测试执行.

    Args:
        pytest_bin: pytest 可执行文件路径(默认 PATH)
        timeout: subprocess 超时(秒, 默认 60.0 — 对齐项目规范)
        pytest_args: 额外 pytest 参数(默认 [] — 视项目 inifile 而定)
        test_paths: 要测试的路径(默认 ["tests"])

    v5.0 §B6.1: applies_to_stages = (developer, critic)
        测试执行仅在有代码产出 (developer) + 评审 (critic) 阶段跑
    """

    name = "test"
    applies_to_stages = ("developer", "critic")

    def __init__(
        self,
        pytest_bin: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        pytest_args: list[str] | None = None,
        test_paths: list[str] | None = None,
    ):
        self.pytest_bin = pytest_bin
        self.timeout = timeout
        self.pytest_args = pytest_args if pytest_args is not None else []
        self.test_paths = test_paths if test_paths is not None else ["tests"]

    def _resolve_pytest_cmd(self) -> list[str] | None:
        """解析 pytest 命令."""
        if self.pytest_bin:
            return [self.pytest_bin]
        if shutil.which("pytest"):
            return ["pytest"]
        # 兜底: python -m pytest
        if shutil.which("python"):
            return ["python", "-m", "pytest"]
        return None

    def _build_cmd(self, project_root: Path) -> list[str]:
        """构造 pytest 命令.

        项目级约定 (.claude/rules/pytest-memory-management.md):
            - 使用 --timeout=60 防 hang
            - 默认不开 --cov(显式 --cov=... 才启用)
            - 兼容无 pyproject.toml 的临时目录: 检测不到 inifile 时不强制加 --timeout
        """
        cmd_base = self._resolve_pytest_cmd()
        if cmd_base is None:
            return []

        cmd = list(cmd_base)

        # 构造参数列表: 用户传的 + 默认行为(仅在项目有 inifile 时)
        args = list(self.pytest_args)

        # 仅在项目根有 pytest inifile 时加 --timeout(避免陌生环境 fail)
        has_inifile = any(
            (project_root / name).exists()
            for name in ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")
        )
        if has_inifile and not any(a.startswith("--timeout") for a in args):
            args = [*args, "--timeout=60"]

        cmd.extend(args)
        cmd.extend(self.test_paths)
        return cmd

    def run(self, project_root: Path, contracts: dict | None = None) -> Verdict:
        """执行 pytest.

        Returns:
            Verdict: passed=True 表示所有测试通过;
                     passed=False 表示有测试失败或 pytest 错误.
        """
        project_root = Path(project_root)
        if not project_root.exists():
            return Verdict.failed(
                f"project_root 不存在: {project_root}",
                gate_name=self.name,
            )

        cmd = self._build_cmd(project_root)
        if not cmd:
            return Verdict.failed(
                "pytest 命令未找到 (PATH 也无 python)",
                gate_name=self.name,
            )

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
                f"pytest 超时 (>{self.timeout}s): {' '.join(cmd)}",
                gate_name=self.name,
            )
        except FileNotFoundError as e:
            return Verdict.failed(
                f"pytest 命令未找到 ({e})",
                gate_name=self.name,
            )

        if result.returncode == 0:
            # 提取 passed 数(若有)
            output = (result.stdout or "") + (result.stderr or "")
            return Verdict.passed(
                f"pytest 通过: {self._extract_summary(output)}",
                gate_name=self.name,
            )

        # exit 5 = no tests collected, 视为失败(项目应至少有测试)
        # exit 1/2/3/4 = 测试失败
        output = (result.stdout or "") + (result.stderr or "")
        snippet = output[-1500:] if len(output) > 1500 else output
        return Verdict.failed(
            f"pytest 失败 (exit={result.returncode}):\n{snippet}",
            gate_name=self.name,
        )

    @staticmethod
    def _extract_summary(output: str) -> str:
        """从 pytest 输出提取 summary 行."""
        for line in output.splitlines():
            line_lower = line.lower()
            if "passed" in line_lower and (
                "failed" in line_lower or "error" in line_lower
            ):
                return line.strip()
            if line.strip().endswith("passed"):
                return line.strip()
        return "tests passed"