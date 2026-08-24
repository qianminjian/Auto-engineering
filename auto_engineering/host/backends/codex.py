"""Codex ephemeral Action context 后端。"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
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
    write_invocation_diagnostic,
)
from auto_engineering.host.invocation import (
    ActionExecutionContractError,
    ActionExecutionReceipt,
    ActionExecutionRequest,
    HostInvocationProbe,
)

_USAGE_LIMIT_MARKERS = (
    "you've hit your usage limit",
    "you have hit your usage limit",
    "usage limit reached",
)


def _is_usage_limit(stdout: str, stderr: str) -> bool:
    evidence = f"{stdout}\n{stderr}".lower()
    return any(marker in evidence for marker in _USAGE_LIMIT_MARKERS)


class CodexInvocationBackend:
    def __init__(
        self,
        *,
        executable: str | None = None,
        runner: ProcessRunner | None = None,
        timeout_seconds: int = 900,
        progress_callback: Callable[[float], None] | None = None,
    ) -> None:
        self.executable = executable or shutil.which("codex") or "codex"
        self._runner = runner or CancellableProcessRunner(
            progress_callback=progress_callback,
        )
        self.timeout_seconds = timeout_seconds
        self._active_context_id: str | None = None

    @property
    def active_context_id(self) -> str | None:
        return self._active_context_id

    def probe(self) -> HostInvocationProbe:
        resolved = (
            self.executable
            if "/" in self.executable and Path(self.executable).is_file()
            else shutil.which(self.executable)
        )
        if resolved is None:
            return HostInvocationProbe.unsupported(
                "codex",
                "HOST_CODEX_CLI_MISSING",
            )
        if not command_supports_flags(
            (str(resolved), "exec", "--help"),
            frozenset({
                "--ephemeral", "--ignore-user-config", "--output-schema",
                "--json", "-C", "-s",
            }),
        ):
            return HostInvocationProbe.unsupported(
                "codex",
                "HOST_CODEX_CAPABILITY_MISSING",
            )
        return HostInvocationProbe.available("codex")

    def build_command(self, request: ActionExecutionRequest) -> tuple[str, ...]:
        schema = (
            Path(__file__).resolve().parent
            / "codex-action-context-output.schema.json"
        )
        return (
            self.executable,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "-C",
            request.project_root,
            "-s",
            "workspace-write",
            "--json",
            "--output-schema",
            str(schema),
            "-",
        )

    def execute(self, request: ActionExecutionRequest) -> ActionExecutionReceipt:
        invocation_id = f"codex-invocation-{uuid4()}"
        self._active_context_id = invocation_id
        try:
            process = self._runner(
                self.build_command(request),
                input=launcher_prompt(request),
                cwd=request.project_root,
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
                "backend": "codex",
                "status": "timed_out",
                "exit_code": None,
                "error_code": "HOST_CODEX_EXECUTION_TIMEOUT",
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
        for event in jsonl_events(process.stdout):
            if event.get("type") == "thread.started" and isinstance(
                event.get("thread_id"), str
            ):
                context_id = str(event["thread_id"])
            raw_usage = event.get("usage")
            if event.get("type") == "turn.completed" and isinstance(
                raw_usage, dict
            ):
                usage = {
                    "input_tokens": non_negative_number(raw_usage.get("input_tokens")),
                    "cached_input_tokens": non_negative_number(
                        raw_usage.get("cached_input_tokens")
                    ),
                    "output_tokens": non_negative_number(raw_usage.get("output_tokens")),
                }
        digests = existing_work_file_digests(request)
        output_missing = "coordinator_result" not in digests
        failed = process.returncode != 0 or output_missing
        usage_limited = process.returncode != 0 and _is_usage_limit(
            process.stdout,
            process.stderr,
        )
        if failed:
            write_invocation_diagnostic(
                request,
                backend="codex",
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
            "backend": "codex",
            "status": "failed" if failed else "completed",
            "exit_code": process.returncode,
            "error_code": (
                "HOST_CODEX_USAGE_LIMIT"
                if usage_limited
                else "HOST_CODEX_EXECUTION_FAILED"
                if process.returncode != 0
                else ("HOST_ACTION_OUTPUT_MISSING" if output_missing else None)
            ),
            "work_file_digests": digests,
            "usage": usage,
        })

    def cancel(self, host_context_id: str) -> None:
        if host_context_id != self._active_context_id:
            raise ActionExecutionContractError("HOST_INVOCATION_NOT_ACTIVE")
        cancel = getattr(self._runner, "cancel", None)
        if not callable(cancel):
            raise ActionExecutionContractError("HOST_INVOCATION_CANCEL_UNAVAILABLE")
        cancel()


__all__ = ["CodexInvocationBackend"]
