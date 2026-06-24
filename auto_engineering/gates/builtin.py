"""5 个内置 Guardrail — 确定性代码级检查.

设计要点:
    - 每个 Guardrail 构造时接受 project_root(避免全局状态,便于测试)
    - subprocess 调用带 timeout(避免阻塞 loop 循环)
    - 超时/异常 → action="drop"(不阻塞整个流程)
    - 失败信息 reason 携带具体细节(便于排查)

参考:
    - CrewAI Task.guardrails (单 guardrail 字符串列表)
    - AutoGen InterventionHandler Protocol
    - Phase 1 gates/gates.py: PlanExistsGate / GitCleanGate / TestsPassGate / GitDiffExistsGate
      (升级为 Guardrail 4 态)

5 个 Guardrail:
    1. RequirementGuardrail    — requirement 非空
    2. PlanExistsGuardrail     — plan 文件存在
    3. GitCleanGuardrail       — git status 干净
    4. TestsPassGuardrail      — pytest 绿
    5. GitDiffExistsGuardrail  — 有 commit 可审查
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from auto_engineering.engine.graph import Stage
from auto_engineering.engine.state import LoopState
from auto_engineering.gates.guardrail import GuardrailResult

# Default subprocess timeout (seconds). 测试可用更短 timeout.
_DEFAULT_SUBPROCESS_TIMEOUT = 30.0


def _run_subprocess(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    """Helper: 跑 subprocess,统一 timeout + 异常处理.

    Raises:
        subprocess.TimeoutExpired: 超时
        subprocess.CalledProcessError: 非零 exit(但这里不 raise,返回 result 供 caller 判断)
    """
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class RequirementGuardrail:
    """检查 LoopState.requirement 非空(防止误调)."""

    def check(self, stage: Stage, state: LoopState) -> GuardrailResult:
        if not state.requirement or not state.requirement.strip():
            return GuardrailResult(
                action="block",
                reason="requirement 为空或仅空白,dev-loop 无法执行",
            )
        return GuardrailResult(action="pass")


class PlanExistsGuardrail:
    """检查 plan 文件存在. 默认 design/dev-loop-plan.md,可覆盖."""

    def __init__(
        self,
        project_root: Path,
        plan_path: Path | None = None,
    ):
        self.project_root = Path(project_root)
        self.plan_path = plan_path or self.project_root / "design" / "dev-loop-plan.md"

    def check(self, stage: Stage, state: LoopState) -> GuardrailResult:
        if not self.plan_path.exists():
            return GuardrailResult(
                action="block",
                reason=f"plan 文件不存在: {self.plan_path}",
            )
        return GuardrailResult(action="pass")


class GitCleanGuardrail:
    """检查 git working directory 干净(无未提交变更)."""

    def __init__(
        self,
        project_root: Path,
        timeout: float = _DEFAULT_SUBPROCESS_TIMEOUT,
    ):
        self.project_root = Path(project_root)
        self.timeout = timeout

    def check(self, stage: Stage, state: LoopState) -> GuardrailResult:
        try:
            result = _run_subprocess(
                ["git", "status", "--porcelain"],
                cwd=self.project_root,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return GuardrailResult(
                action="drop",
                reason=f"git status 超时 (>{self.timeout}s),跳过检查",
            )
        except FileNotFoundError:
            return GuardrailResult(
                action="drop",
                reason="git 命令未找到,跳过检查",
            )

        if result.stdout.strip():
            return GuardrailResult(
                action="block",
                reason=f"存在未提交变更:\n{result.stdout}",
            )
        return GuardrailResult(action="pass")


class TestsPassGuardrail:
    """检查 pytest 跑通(退出码 0)."""

    def __init__(
        self,
        project_root: Path,
        test_runner: str = "pytest",
        timeout: float = 300.0,  # 测试可能慢,默认 5 分钟
    ):
        self.project_root = Path(project_root)
        self.test_runner = test_runner
        self.timeout = timeout

    def check(self, stage: Stage, state: LoopState) -> GuardrailResult:
        try:
            result = _run_subprocess(
                [self.test_runner],
                cwd=self.project_root,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return GuardrailResult(
                action="drop",
                reason=f"{self.test_runner} 超时 (>{self.timeout}s),跳过检查",
            )
        except FileNotFoundError:
            return GuardrailResult(
                action="drop",
                reason=f"{self.test_runner} 命令未找到,跳过检查",
            )

        if result.returncode != 0:
            return GuardrailResult(
                action="block",
                reason=(f"测试未通过 (exit={result.returncode})\nstderr: {result.stderr[:500]}"),
            )
        return GuardrailResult(action="pass")


class GitDiffExistsGuardrail:
    """检查有 git commit 可审查(critic 入口)."""

    def __init__(
        self,
        project_root: Path,
        timeout: float = _DEFAULT_SUBPROCESS_TIMEOUT,
    ):
        self.project_root = Path(project_root)
        self.timeout = timeout

    def check(self, stage: Stage, state: LoopState) -> GuardrailResult:
        try:
            result = _run_subprocess(
                ["git", "log", "-1", "--format=%H"],
                cwd=self.project_root,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return GuardrailResult(
                action="drop",
                reason=f"git log 超时 (>{self.timeout}s),跳过检查",
            )
        except FileNotFoundError:
            return GuardrailResult(
                action="drop",
                reason="git 命令未找到,跳过检查",
            )

        if result.returncode != 0 or not result.stdout.strip():
            return GuardrailResult(
                action="block",
                reason="无 git commit,developer 必须先提交",
            )
        return GuardrailResult(
            action="pass",
            payload={"commit": result.stdout.strip()},
        )
