"""由 ProjectProfile 精确参数数组驱动的 Gate。"""

from __future__ import annotations

import json
import os
import shlex
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
        if reason := self._interactive_test_reason(project_root):
            return GateVerdict.failed(reason, gate_name=self.name)
        result = run_gate_command(
            list(self.command),
            project_root,
            self.timeout,
            env=self._project_environment(project_root),
        )
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

    def _interactive_test_reason(self, project_root: Path) -> str | None:
        """在启动前拒绝已知 watch/UI 测试命令，避免 Setup Gate 挂住。

        命令仍来自 ProjectProfile；这里只做安全策略校验，不替换或拼接命令。
        """
        if self.name != "test" or not self.command:
            return None
        command_text = " ".join(self.command)
        if len(self.command) >= 3 and self.command[1] == "run":
            package_path = project_root / "package.json"
            try:
                package = json.loads(package_path.read_text(encoding="utf-8"))
                scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
                script = scripts.get(self.command[2]) if isinstance(scripts, dict) else None
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                script = None
            if isinstance(script, str) and script.strip():
                command_text = script.strip()
        try:
            tokens = shlex.split(command_text)
        except ValueError:
            return "PROJECT_TEST_COMMAND_INTERACTIVE: 测试命令无法安全解析"
        normalized = {token.lower() for token in tokens}
        has_vitest = "vitest" in normalized or any(
            token.endswith("/vitest") for token in normalized
        )
        if has_vitest:
            has_run = "run" in normalized or "--run" in normalized or any(
                token.startswith("--run=") for token in normalized
            )
            has_watch = "--watch" in normalized or any(
                token.startswith("--watch=") and token != "--watch=false"
                for token in normalized
            )
            if has_watch or not has_run:
                return (
                    "PROJECT_TEST_COMMAND_INTERACTIVE: Vitest 必须使用一次性运行模式；"
                    "请将项目 test script 配置为 `vitest run`，禁止 `vitest`/`--watch`"
                )
        has_cypress = "cypress" in normalized or any(
            token.endswith("/cypress") for token in normalized
        )
        if has_cypress and "open" in normalized:
            return "PROJECT_TEST_COMMAND_INTERACTIVE: Cypress 必须使用 `cypress run`，禁止 `cypress open`"
        has_playwright = "playwright" in normalized or any(
            token.endswith("/playwright") for token in normalized
        )
        if has_playwright and any(token in {"ui", "show-report"} for token in normalized):
            return "PROJECT_TEST_COMMAND_INTERACTIVE: Playwright 测试必须使用无 UI 的 `playwright test`"
        has_jest = "jest" in normalized or any(
            token.endswith("/jest") for token in normalized
        )
        if has_jest and any(token in {"--watch", "--watchall"} for token in normalized):
            return "PROJECT_TEST_COMMAND_INTERACTIVE: Jest 必须关闭 watch 模式后执行"
        return None

    @staticmethod
    def _project_environment(project_root: Path) -> dict[str, str]:
        """让项目命令脱离插件运行时，使用项目自己的工具环境。

        ``ae-run`` 为插件本身设置 ``UV_PROJECT_ENVIRONMENT``，并可能把
        ``.ae-state/.ae-runtime/bin`` 放到 PATH 首位。Profile 命令属于用户项目，
        不能继承这两个运行时信号，否则 ``python -m pytest`` 会在插件环境中执行。
        项目存在 ``.venv`` 时把它置于 PATH 首位；没有项目环境时保留系统 PATH，
        让缺少依赖明确失败，而不是静默执行插件依赖。
        """
        environment = os.environ.copy()
        environment.pop("UV_PROJECT_ENVIRONMENT", None)
        environment.pop("VIRTUAL_ENV", None)

        root = project_root.resolve()
        plugin_runtime_bin = root / ".ae-state/.ae-runtime/bin"
        project_venv_bin = root / ".venv/bin"
        retained: list[str] = []
        for entry in environment.get("PATH", "").split(os.pathsep):
            if not entry:
                continue
            try:
                if Path(entry).resolve() == plugin_runtime_bin.resolve():
                    continue
            except OSError:
                if entry.rstrip("/") == str(plugin_runtime_bin):
                    continue
            retained.append(entry)
        if project_venv_bin.is_dir():
            retained.insert(0, str(project_venv_bin))
        environment["PATH"] = os.pathsep.join(retained)
        return environment

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
