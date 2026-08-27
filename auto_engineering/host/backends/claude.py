"""Claude Code print-mode Action context 后端。"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from auto_engineering.host.backends.common import (
    CancellableProcessRunner,
    ProcessRunner,
    command_supports_flags,
    existing_work_file_digests,
    jsonl_events,
    launcher_prompt,
    non_negative_number,
    normalize_coordinator_work_output,
    write_invocation_diagnostic,
)
from auto_engineering.host.invocation import (
    ActionExecutionContractError,
    ActionExecutionReceipt,
    ActionExecutionRequest,
    HostInvocationProbe,
)

_BUDGET_LIMIT_MARKERS = (
    "error_max_budget_usd",
    "maximum budget reached",
    "max budget reached",
)


def _is_budget_exhausted(stdout: str, stderr: str) -> bool:
    evidence = f"{stdout}\n{stderr}".lower()
    return any(marker in evidence for marker in _BUDGET_LIMIT_MARKERS)


class ClaudeInvocationBackend:
    def __init__(
        self,
        *,
        executable: str | None = None,
        environ: Mapping[str, str] | None = None,
        max_budget_usd: float = 10.0,
        max_invocation_budget_usd: float = 2.0,
        spent_budget_usd: float = 0.0,
        budget_reserve_usd: float = 0.2,
        runner: ProcessRunner | None = None,
        timeout_seconds: int = 900,
        progress_callback: Callable[[float], None] | None = None,
    ) -> None:
        self.executable = executable or shutil.which("claude") or "claude"
        self._environ = dict(os.environ if environ is None else environ)
        self.max_budget_usd = max_budget_usd
        self.max_invocation_budget_usd = max(0.0, max_invocation_budget_usd)
        self._spent_budget_usd = max(0.0, spent_budget_usd)
        self.budget_reserve_usd = max(0.0, budget_reserve_usd)
        self._runner = runner or CancellableProcessRunner(
            progress_callback=progress_callback,
        )
        self.timeout_seconds = timeout_seconds
        self._active_context_id: str | None = None

    @property
    def active_context_id(self) -> str | None:
        return self._active_context_id

    @property
    def remaining_budget_usd(self) -> float:
        return max(0.0, self.max_budget_usd - self._spent_budget_usd)

    @property
    def invocation_budget_usd(self) -> float:
        """扣除一次推理单元超调预留后的可调用额度。"""
        return min(
            self.max_invocation_budget_usd,
            max(0.0, self.remaining_budget_usd - self.budget_reserve_usd),
        )

    def child_environment(self) -> dict[str, str]:
        """原样继承宿主保护变量，禁止通过删除变量绕过嵌套限制。"""
        return dict(self._environ)

    def probe(self) -> HostInvocationProbe:
        if self._environ.get("CLAUDECODE"):
            return HostInvocationProbe.unsupported(
                "claude",
                "HOST_NESTED_INVOCATION_UNAVAILABLE",
            )
        resolved = (
            self.executable
            if "/" in self.executable and Path(self.executable).is_file()
            else shutil.which(self.executable)
        )
        if resolved is None:
            return HostInvocationProbe.unsupported(
                "claude",
                "HOST_CLAUDE_CLI_MISSING",
            )
        if not command_supports_flags(
            (str(resolved), "--help"),
            frozenset({
                "--no-session-persistence", "--output-format",
                "--max-budget-usd", "--permission-mode",
                "--strict-mcp-config", "--mcp-config",
                "--disable-slash-commands", "--no-chrome", "--effort",
                "--safe-mode",
            }),
        ):
            return HostInvocationProbe.unsupported(
                "claude",
                "HOST_CLAUDE_CAPABILITY_MISSING",
            )
        return HostInvocationProbe.available("claude")

    def build_command(self, request: ActionExecutionRequest) -> tuple[str, ...]:
        return (
            self.executable,
            "-p",
            "--no-session-persistence",
            # safe-mode 同时保留用户认证并禁用 CLAUDE.md、hooks、plugins、
            # skills 与自定义 Agent；project-only settings 会连 OAuth 一起排除。
            "--safe-mode",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--disable-slash-commands",
            "--no-chrome",
            "--effort",
            "low",
            "--output-format",
            "stream-json",
            "--verbose",
            "--max-budget-usd",
            str(self.invocation_budget_usd),
            "--permission-mode",
            "acceptEdits",
        )

    def execute(self, request: ActionExecutionRequest) -> ActionExecutionReceipt:
        invocation_id = f"claude-invocation-{uuid4()}"
        if self.invocation_budget_usd <= 0:
            return ActionExecutionReceipt.from_dict({
                "schema_version": "1.0",
                "thread_id": request.thread_id,
                "action_message_id": request.action_message_id,
                "build_id": request.build_id,
                "host_context_id": invocation_id,
                "backend": "claude",
                "status": "failed",
                "exit_code": None,
                "error_code": "HOST_CLAUDE_BUDGET_EXHAUSTED",
                "work_file_digests": existing_work_file_digests(request),
                "usage": {
                    "input_tokens": None,
                    "cached_input_tokens": None,
                    "output_tokens": None,
                    "cost_usd": 0.0,
                },
            })
        self._active_context_id = invocation_id
        try:
            process = self._runner(
                self.build_command(request),
                input=launcher_prompt(request),
                cwd=request.project_root,
                env=self.child_environment(),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ActionExecutionReceipt.from_dict({
                "schema_version": "1.0",
                "thread_id": request.thread_id,
                "action_message_id": request.action_message_id,
                "build_id": request.build_id,
                "host_context_id": invocation_id,
                "backend": "claude",
                "status": "timed_out",
                "exit_code": None,
                "error_code": "HOST_CLAUDE_EXECUTION_TIMEOUT",
                "work_file_digests": existing_work_file_digests(request),
                "usage": {
                    "input_tokens": None,
                    "cached_input_tokens": None,
                    "output_tokens": None,
                },
            })
        finally:
            self._active_context_id = None
        context_id = invocation_id
        usage: dict[str, int | float | None] = {
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
        }
        is_error = process.returncode != 0
        for event in jsonl_events(process.stdout):
            session_id = event.get("session_id")
            if isinstance(session_id, str) and session_id:
                context_id = session_id
            raw_usage = event.get("usage")
            if event.get("type") == "result":
                is_error = is_error or event.get("is_error") is True
                model_usage = event.get("modelUsage")
                if isinstance(model_usage, dict) and model_usage:
                    usage = self._aggregate_model_usage(
                        model_usage,
                        total_cost=event.get("total_cost_usd"),
                    )
                elif isinstance(raw_usage, dict):
                    usage = {
                        "input_tokens": non_negative_number(raw_usage.get("input_tokens")),
                        "cached_input_tokens": non_negative_number(
                            raw_usage.get("cache_read_input_tokens")
                        ),
                        "output_tokens": non_negative_number(raw_usage.get("output_tokens")),
                        "cost_usd": non_negative_number(event.get("total_cost_usd")),
                    }
        actual_cost = usage.get("cost_usd")
        if isinstance(actual_cost, (int, float)):
            self._spent_budget_usd += float(actual_cost)
        if not is_error:
            # 业务拒绝由 Assembler/Core 返回可执行的同 Action repair。
            with suppress(ValueError):
                normalize_coordinator_work_output(request)
        digests = existing_work_file_digests(request)
        output_missing = "coordinator_result" not in digests
        execution_failed = is_error
        budget_exhausted = execution_failed and _is_budget_exhausted(
            process.stdout,
            process.stderr,
        )
        launch_config_invalid = (
            execution_failed
            and "invalid mcp configuration" in process.stderr.lower()
        )
        is_error = is_error or output_missing
        if is_error:
            write_invocation_diagnostic(
                request,
                backend="claude",
                context_id=context_id,
                status="failed",
                exit_code=process.returncode,
                stdout=process.stdout,
                stderr=process.stderr,
            )
        return ActionExecutionReceipt.from_dict({
            "schema_version": "1.0",
            "thread_id": request.thread_id,
            "action_message_id": request.action_message_id,
            "build_id": request.build_id,
            "host_context_id": context_id,
            "backend": "claude",
            "status": "failed" if is_error else "completed",
            "exit_code": process.returncode,
            "error_code": (
                "HOST_CLAUDE_LAUNCH_CONFIG_INVALID"
                if launch_config_invalid
                else "HOST_CLAUDE_BUDGET_EXHAUSTED"
                if budget_exhausted
                else "HOST_CLAUDE_EXECUTION_FAILED"
                if execution_failed
                else ("HOST_ACTION_OUTPUT_MISSING" if output_missing else None)
            ),
            "work_file_digests": digests,
            "usage": usage,
        })

    @staticmethod
    def _aggregate_model_usage(
        model_usage: Mapping[str, object],
        *,
        total_cost: object,
    ) -> dict[str, int | float | None]:
        totals = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        }
        for raw in model_usage.values():
            if not isinstance(raw, Mapping):
                continue
            for target, source in (
                ("input_tokens", "inputTokens"),
                ("cached_input_tokens", "cacheReadInputTokens"),
                ("output_tokens", "outputTokens"),
            ):
                value = non_negative_number(raw.get(source))
                if isinstance(value, (int, float)):
                    totals[target] += int(value)
        return {
            **totals,
            "cost_usd": non_negative_number(total_cost),
        }

    def cancel(self, host_context_id: str) -> None:
        if host_context_id != self._active_context_id:
            raise ActionExecutionContractError("HOST_INVOCATION_NOT_ACTIVE")
        cancel = getattr(self._runner, "cancel", None)
        if not callable(cancel):
            raise ActionExecutionContractError("HOST_INVOCATION_CANCEL_UNAVAILABLE")
        cancel()


__all__ = ["ClaudeInvocationBackend"]
