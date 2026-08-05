"""由 ProjectProfile 精确参数数组驱动的 Gate。"""

from __future__ import annotations

from pathlib import Path

from auto_engineering.gates.base import Gate, GateVerdict, run_gate_command


class ProfileCommandGate(Gate):
    """执行 Profile 已验证命令；命令缺失时明确失败，不使用语言默认值。"""

    def __init__(
        self,
        name: str,
        command: tuple[str, ...] | None,
        *,
        timeout: float | None = None,
    ) -> None:
        self.name = name
        self.command = command
        self.timeout = timeout if timeout is not None else Gate._resolve_timeout(120.0)

    def run(self, project_root: Path) -> GateVerdict:
        if verdict := self._validate_project_root(project_root):
            return verdict
        if not self.command:
            return GateVerdict.failed(
                f"PROJECT_COMMAND_UNVERIFIED: ProjectProfile 未提供 {self.name} 命令",
                gate_name=self.name,
            )
        result = run_gate_command(list(self.command), project_root, self.timeout)
        rendered = " ".join(self.command)
        if result.timed_out:
            return GateVerdict.failed(
                f"{rendered} 超时 (>{self.timeout}s)",
                gate_name=self.name,
            )
        if getattr(result, "not_found", False) is True or result.returncode < 0:
            raw_error = getattr(result, "error", "")
            reason = raw_error if isinstance(raw_error, str) and raw_error else (
                result.stderr or "进程启动失败"
            )
            return GateVerdict.failed(
                f"{rendered} 无法执行: {reason[-1000:]}",
                gate_name=self.name,
            )
        output = f"{result.stdout}\n{result.stderr}".strip()
        if result.returncode != 0:
            return GateVerdict.failed(
                f"{rendered} 失败 (exit={result.returncode}):\n{output[-1000:]}",
                gate_name=self.name,
            )
        if self.name == "test" and self._reports_zero_tests(output):
            return GateVerdict.failed(
                f"{rendered} 未收集到测试",
                gate_name=self.name,
            )
        return GateVerdict.ok(f"{rendered} 通过", gate_name=self.name)

    @staticmethod
    def _reports_zero_tests(output: str) -> bool:
        normalized = output.lower()
        return any(
            marker in normalized
            for marker in (
                "no tests collected",
                "no test files found",
                "0 tests",
                "tests  0 passed",
            )
        )


__all__ = ["ProfileCommandGate"]
