"""v2.0 Phase 04 — Gate 4: Test (pytest / vitest / go test, v5.0 §IL-AC-02 可配置).

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 4.

约束(项目级 .claude/rules/pytest-memory-management.md):
    - 单文件 pytest + --no-cov + --timeout=60 (防内存爆炸)
    - 默认 pytest 命令: pytest --no-cov --timeout=60
    - 超时强制 fail(防 hang)
    - cov 默认关闭(避免 2x 内存叠加)

实现方式:
    - subprocess 调用 {test_runner} (默认 pytest)
    - exit 0 → pass
    - exit 非 0 → fail(携带 stderr 输出)
    - 超时 → fail(明确告知)

v5.0 §IL-AC-02 扩展:
    - 优先使用 init-manifest.json conventions.test_runner
    - 可选: pytest / vitest / go test / cargo test / bats
    - 缺则用默认 (python=pytest)
"""

from __future__ import annotations

import shutil
from pathlib import Path

from auto_engineering.gates._tools import get_gate_tools_from_manifest
from auto_engineering.gates.base import Gate, GateVerdict, run_gate_command

__all__ = ["TestGate", "DEFAULT_TIMEOUT"]

# 默认 timeout 与 .claude/rules/pytest-memory-management.md 对齐
DEFAULT_TIMEOUT = 60.0
_DEFAULT_TEST_RUNNER = "pytest"


class TestGate(Gate):
    """Gate 4: 测试执行 (默认 pytest).

    Args:
        test_runner_bin: 测试工具名(默认 'pytest', v5.0 §IL-AC-02)
                         可选: pytest / vitest / go test / cargo test / bats
        timeout: subprocess 超时(秒, 默认 60.0 — 对齐项目规范)
        pytest_args: 额外参数(默认 [])
        test_paths: 要测试的路径(默认 ["tests"])

    v5.0 §B6.1: applies_to_stages = (developer, critic)
        测试执行仅在有代码产出 (developer) + 评审 (critic) 阶段跑
    """

    name = "test"
    applies_to_stages = ("developer", "critic")

    def __init__(
        self,
        test_runner_bin: str | None = None,
        timeout: float | None = None,
        pytest_args: list[str] | None = None,
        test_paths: list[str] | None = None,
    ):
        self.test_runner_bin = test_runner_bin or _DEFAULT_TEST_RUNNER
        self.timeout = timeout if timeout is not None else Gate._resolve_timeout(DEFAULT_TIMEOUT)
        self.pytest_args = pytest_args if pytest_args is not None else []
        self.test_paths = test_paths if test_paths is not None else ["tests"]

    @classmethod
    def from_manifest(
        cls,
        manifest: dict,
        timeout: float | None = None,
    ) -> "TestGate":
        """v5.0 §IL-AC-02: 从 init-manifest.json 构造 TestGate.

        读 manifest.conventions.test_runner, 缺则用 LANGUAGE_TOOLS 默认.
        """
        tools = get_gate_tools_from_manifest(manifest)
        return cls(test_runner_bin=tools["test_runner"], timeout=timeout)

    def _resolve_test_cmd(self) -> list[str] | None:
        """解析 test_runner 命令.

        v5.0 §IL-AC-02 兼容 5 语言 test_runner:
            - pytest / vitest / go test / cargo test / bats
        """
        if self.test_runner_bin:
            return [self.test_runner_bin]
        if shutil.which(self.test_runner_bin):
            return [self.test_runner_bin]
        # 兜底: python -m pytest (仅 Python 生态)
        if self.test_runner_bin == "pytest" and shutil.which("python"):
            return ["python", "-m", "pytest"]
        return None

    def _build_cmd(self, project_root: Path) -> list[str]:
        """构造 test_runner 命令.

        项目级约定 (.claude/rules/pytest-memory-management.md):
            - 使用 --timeout=60 防 hang (仅 pytest 适用)
            - 默认不开 --cov(显式 --cov=... 才启用)
            - 兼容无 pyproject.toml 的临时目录: 检测不到 inifile 时不强制加 --timeout
        """
        cmd_base = self._resolve_test_cmd()
        if cmd_base is None:
            return []

        cmd = list(cmd_base)

        # 构造参数列表: 用户传的 + 默认行为(仅在项目有 inifile 时)
        args = list(self.pytest_args)

        # 仅在项目根有 pytest inifile 且 test_runner=pytest 时加 --timeout
        if self.test_runner_bin == "pytest":
            has_inifile = any(
                (project_root / name).exists()
                for name in ("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")
            )
            if has_inifile and not any(a.startswith("--timeout") for a in args):
                args = [*args, "--timeout=60"]

        cmd.extend(args)
        cmd.extend(self.test_paths)
        return cmd

    def run(self, project_root: Path) -> GateVerdict:
        """执行 test_runner.

        Returns:
            GateVerdict: passed=True 表示所有测试通过;
                     passed=False 表示有测试失败或 test_runner 错误.
        """
        project_root = Path(project_root)
        if verdict := self._validate_project_root(project_root):
            return verdict

        cmd = self._build_cmd(project_root)
        if not cmd:
            return GateVerdict.failed(
                f"{self.test_runner_bin} 命令未找到 (PATH 也无 python)",
                gate_name=self.name,
            )

        result = run_gate_command(cmd, project_root, self.timeout)

        if result.timed_out:
            return GateVerdict.failed(
                f"{self.test_runner_bin} 超时 (>{self.timeout}s): {' '.join(cmd)}",
                gate_name=self.name,
            )
        if result.not_found:
            return GateVerdict.failed(
                f"{self.test_runner_bin} 命令未找到",
                gate_name=self.name,
            )

        if result.returncode == 0:
            output = result.stdout + result.stderr
            return GateVerdict.ok(
                f"{self.test_runner_bin} 通过: {self._extract_summary(output)}",
                gate_name=self.name,
            )

        if result.returncode in (4, 5):
            output = result.stdout + result.stderr
            snippet = output[-300:] if len(output) > 300 else output
            return GateVerdict.ok(
                f"{self.test_runner_bin} skip: 未收集到测试 (exit={result.returncode})\n{snippet}",
                gate_name=self.name,
            )

        output = result.stdout + result.stderr
        snippet = output[-1500:] if len(output) > 1500 else output
        return GateVerdict.failed(
            f"{self.test_runner_bin} 失败 (exit={result.returncode}):\n{snippet}",
            gate_name=self.name,
        )

    @staticmethod
    def _extract_summary(output: str) -> str:
        """从测试输出提取 summary 行."""
        for line in output.splitlines():
            line_lower = line.lower()
            if "passed" in line_lower and (
                "failed" in line_lower or "error" in line_lower
            ):
                return line.strip()
            if line.strip().endswith("passed"):
                return line.strip()
        return "tests passed"


# v5.5 audit P2-15: 向后兼容别名, v6.0 移除
TestGate._register_alias("pytest_bin", "test_runner_bin")