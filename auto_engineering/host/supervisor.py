"""无业务对话的 Action-scoped 宿主监督器。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from auto_engineering.host.backends.common import ProcessRunner
from auto_engineering.host.driver_contract import (
    HostDriverDecision,
    decide_host_step,
)
from auto_engineering.host.invocation import (
    ActionExecutionContractError,
    ActionExecutionReceipt,
    ActionExecutionRequest,
    HostInvocationBackend,
)


@dataclass(frozen=True, slots=True)
class HostSupervisorResult:
    """一次自动驱动的有界审计结果。"""

    receipts: tuple[ActionExecutionReceipt, ...]

    @property
    def actions_completed(self) -> int:
        return len(self.receipts)


class ActionReceiptJournal:
    """持久化有界宿主回执；不记录 Prompt、环境变量或 transcript。"""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()

    def record(
        self,
        request: ActionExecutionRequest,
        receipt: ActionExecutionReceipt,
    ) -> Path:
        receipt.validate_for(request)
        directory = self._root / ".ae-state/host-runtime/receipts"
        directory.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(
            f"{request.action_message_id}:{receipt.host_context_id}".encode()
        ).hexdigest()[:24]
        target = directory / f"{identity}.json"
        payload = {
            **receipt.to_dict(),
            "tick": request.tick,
            "stage": request.stage,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".receipt-",
            suffix=".json",
            dir=directory,
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return target

    def total_cost_usd(self, thread_id: str) -> float:
        """汇总同一 thread 已持久化成本；恢复进程不得重置预算。"""
        directory = self._root / ".ae-state/host-runtime/receipts"
        total = 0.0
        for path in sorted(directory.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ActionExecutionContractError(
                    "PRODUCT_RECEIPT_INVALID"
                ) from exc
            if not isinstance(value, dict) or value.get("thread_id") != thread_id:
                continue
            usage = value.get("usage")
            cost = usage.get("cost_usd") if isinstance(usage, dict) else None
            if cost is None:
                continue
            if (
                isinstance(cost, bool)
                or not isinstance(cost, (int, float))
                or cost < 0
            ):
                raise ActionExecutionContractError("PRODUCT_RECEIPT_INVALID")
            total += float(cost)
        return total


class ProductEvidenceArtifactJournal:
    """在真实终态汇总机器事实；禁止由模型或人工重述生成。"""

    _REQUIRED_EVENTS = frozenset({
        "ActionIssued", "ResultAccepted", "LoopCompleted",
    })

    def __init__(self, project_root: Path, *, runtime_root: Path) -> None:
        self._root = project_root.resolve()
        self._runtime_root = runtime_root.resolve()

    def record_terminal(
        self,
        *,
        host: str,
        thread_id: str,
        final_action: Mapping[str, Any],
        event_types: tuple[str, ...],
    ) -> Path:
        if host not in {"codex", "claude-code"}:
            raise ActionExecutionContractError("PRODUCT_HOST_INVALID")
        if final_action.get("action") != "done":
            raise ActionExecutionContractError("PRODUCT_TERMINAL_REQUIRED")
        receipts = self._completed_receipts(thread_id)
        if not receipts:
            raise ActionExecutionContractError("PRODUCT_RECEIPTS_MISSING")
        build_ids = {str(item.get("build_id")) for item in receipts}
        if len(build_ids) != 1:
            raise ActionExecutionContractError("PRODUCT_BUILD_ID_MISMATCH")
        build_id = next(iter(build_ids))
        if self._packaged_build_id() != build_id or "+sha256." not in build_id:
            raise ActionExecutionContractError("PRODUCT_RELEASE_IDENTITY_INVALID")
        action_ids = [str(item.get("action_message_id")) for item in receipts]
        context_ids = [str(item.get("host_context_id")) for item in receipts]
        if len(action_ids) != len(set(action_ids)):
            raise ActionExecutionContractError("ACTION_ID_REUSED")
        if len(context_ids) != len(set(context_ids)):
            raise ActionExecutionContractError("HOST_CONTEXT_REUSED")
        if not self._REQUIRED_EVENTS.issubset(set(event_types)):
            raise ActionExecutionContractError("PRODUCT_TERMINAL_EVENTS_INCOMPLETE")
        payload = {
            "schema_version": "1.1",
            "host": host,
            "build_id": build_id,
            "installed_build_id": build_id,
            "plugin_discovered": True,
            "runtime_root": str(self._runtime_root),
            "event_types": sorted(set(event_types)),
            "terminal_action": {
                "action": "done",
                "reason_code": final_action.get("reason_code"),
            },
            "action_receipts": receipts,
        }
        directory = self._root / ".ae-state/reports"
        directory.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(thread_id.encode()).hexdigest()[:24]
        target = directory / f"product-evidence-{identity}.json"
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".product-evidence-",
            suffix=".json",
            dir=directory,
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return target

    def _packaged_build_id(self) -> str | None:
        try:
            payload = json.loads(
                (self._runtime_root / "build-info.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        value = payload.get("build_id") if isinstance(payload, dict) else None
        return value if isinstance(value, str) else None

    def _completed_receipts(self, thread_id: str) -> list[dict[str, Any]]:
        directory = self._root / ".ae-state/host-runtime/receipts"
        records: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ActionExecutionContractError(
                    "PRODUCT_RECEIPT_INVALID"
                ) from exc
            if not isinstance(value, dict):
                raise ActionExecutionContractError("PRODUCT_RECEIPT_INVALID")
            if (
                value.get("thread_id") == thread_id
                and value.get("status") == "completed"
            ):
                records.append(value)
        records.sort(key=lambda item: (
            int(item.get("tick", -1)),
            str(item.get("action_message_id")),
        ))
        return records


class LoopStopReportJournal:
    """从机器 Action/Receipt 生成有界停止报告，不调用模型。"""

    def __init__(self, project_root: Path) -> None:
        self._root = project_root.resolve()

    @staticmethod
    def _line(value: object, *, limit: int = 500) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        return text[:limit]

    def _latest_receipt(self, thread_id: str) -> dict[str, Any] | None:
        directory = self._root / ".ae-state/host-runtime/receipts"
        records: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(value, dict)
                and value.get("thread_id") == thread_id
            ):
                records.append(value)
        if not records:
            return None
        return max(records, key=lambda item: (
            int(item.get("tick", -1)),
            str(item.get("action_message_id", "")),
        ))

    @staticmethod
    def _disposition(action: Mapping[str, Any]) -> str:
        extensions = action.get("extensions")
        ae = extensions.get("ae") if isinstance(extensions, Mapping) else None
        control = (
            ae.get("execution_control") if isinstance(ae, Mapping) else None
        )
        value = control.get("disposition") if isinstance(control, Mapping) else None
        return str(value or "UNKNOWN")

    @staticmethod
    def _next_step(action: Mapping[str, Any], disposition: str) -> str:
        stage = str(action.get("retry_stage") or action.get("stage") or "当前阶段")
        if disposition == "WAIT_RESOURCE":
            return f"等待资源恢复后重试 {stage}"
        if disposition == "WAIT_USER":
            return "按 Core 返回的 Gate 选项取得用户决策"
        if disposition == "TERMINAL":
            return "循环已到确定性终态，无后续 Action"
        if disposition == "HANDOFF_REQUIRED":
            return "按 ResumeCapsule 创建新的宿主执行实例"
        return "修复阻断错误后重新执行同一 active Action"

    def record(
        self,
        *,
        thread_id: str,
        final_action: Mapping[str, Any],
    ) -> Path:
        disposition = self._disposition(final_action)
        receipt = self._latest_receipt(thread_id)
        action_id = self._line(final_action.get("message_id"))
        reason = self._line(
            final_action.get("reason_code") or final_action.get("error_code")
        )
        message = self._line(final_action.get("message"))
        lines = [
            "# Auto-Engineering Loop 停止报告",
            "",
            f"- Thread：`{self._line(thread_id)}`",
            f"- Disposition：`{disposition}`",
            f"- 当前 Action：`{action_id}`",
            f"- Stage：`{self._line(final_action.get('stage'))}`",
            f"- Tick：`{self._line(final_action.get('tick'))}`",
            f"- 原因码：`{reason}`",
            f"- 说明：{message or '无额外说明'}",
            "",
            "## 最近宿主回执",
            "",
        ]
        if receipt is None:
            lines.append("- 无已持久化宿主回执。")
        else:
            lines.extend([
                f"- Action：`{self._line(receipt.get('action_message_id'))}`",
                f"- Context：`{self._line(receipt.get('host_context_id'))}`",
                f"- Stage：`{self._line(receipt.get('stage'))}`",
                f"- Status：`{self._line(receipt.get('status'))}`",
                f"- Error：`{self._line(receipt.get('error_code'))}`",
            ])
        lines.extend([
            "",
            "## 下一步",
            "",
            f"- {self._next_step(final_action, disposition)}。",
            "",
            "> 本报告由 Action、Execution Control 与 Receipt 机器事实确定性生成。",
            "",
        ])
        directory = self._root / ".ae-state/reports"
        directory.mkdir(parents=True, exist_ok=True)
        identity = hashlib.sha256(
            f"{thread_id}:{action_id}:{disposition}".encode()
        ).hexdigest()[:24]
        target = directory / f"loop-stop-{identity}.md"
        encoded = "\n".join(lines)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".loop-stop-", suffix=".md", dir=directory, text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return target


class MachineOperationExecutor:
    """原样执行 Core 下发的三段 argv；不使用 Shell、不推断参数。"""

    def __init__(
        self,
        *,
        project_root: Path,
        bundled_runner: Path,
        runner: ProcessRunner = subprocess.run,
        timeout_seconds: int = 120,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._root = project_root.resolve()
        self._bundled_runner = str(bundled_runner)
        self._runner = runner
        self._timeout_seconds = timeout_seconds
        self._environ = dict(os.environ if environ is None else environ)

    def _argv(
        self,
        operations: Mapping[str, object],
        operation: str,
    ) -> tuple[str, ...]:
        raw_operation = operations.get(operation)
        raw_argv = (
            raw_operation.get("argv")
            if isinstance(raw_operation, Mapping)
            else None
        )
        if (
            not isinstance(raw_argv, list)
            or not raw_argv
            or raw_argv[0] != "__AE_BUNDLED_RUNNER__"
            or any(not isinstance(item, str) or not item for item in raw_argv)
        ):
            raise ActionExecutionContractError(
                f"HOST_OPERATION_{operation.upper()}_INVALID"
            )
        return (self._bundled_runner, *(str(item) for item in raw_argv[1:]))

    def _run_sequence(
        self,
        operations: Mapping[str, object],
        sequence: tuple[str, ...],
    ) -> dict[str, Any]:
        if set(operations) != {"finalize", "validate", "submit"}:
            raise ActionExecutionContractError("HOST_OPERATIONS_INVALID")
        submitted: dict[str, Any] | None = None
        for operation in sequence:
            try:
                process = self._runner(
                    self._argv(operations, operation),
                    cwd=str(self._root),
                    text=True,
                    capture_output=True,
                    timeout=self._timeout_seconds,
                    check=False,
                    env=self._environ,
                )
            except subprocess.TimeoutExpired as exc:
                raise ActionExecutionContractError(
                    f"HOST_OPERATION_{operation.upper()}_TIMEOUT"
                ) from exc
            if process.returncode != 0:
                self._write_diagnostic(
                    operation=operation,
                    status="failed",
                    exit_code=process.returncode,
                    stdout=process.stdout,
                    stderr=process.stderr,
                )
                raise ActionExecutionContractError(
                    f"HOST_OPERATION_{operation.upper()}_FAILED"
                )
            if operation == "submit":
                try:
                    value = json.loads(process.stdout)
                except json.JSONDecodeError as exc:
                    raise ActionExecutionContractError(
                        "HOST_OPERATION_SUBMIT_OUTPUT_INVALID"
                    ) from exc
                if not isinstance(value, dict):
                    raise ActionExecutionContractError(
                        "HOST_OPERATION_SUBMIT_OUTPUT_INVALID"
                    )
                submitted = value
        if submitted is None:
            raise ActionExecutionContractError("HOST_OPERATION_SUBMIT_OUTPUT_INVALID")
        return submitted

    def _write_diagnostic(
        self,
        *,
        operation: str,
        status: str,
        exit_code: int | None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        directory = self._root / ".ae-state/host-runtime/diagnostics"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"machine-operation-{operation}.json"
        payload = json.dumps({
            "schema_version": "1.0",
            "operation": operation,
            "status": status,
            "exit_code": exit_code,
            "stdout_tail": stdout[-4096:],
            "stderr_tail": stderr[-4096:],
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".machine-operation-",
            suffix=".json",
            dir=directory,
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def run(self, operations: Mapping[str, object]) -> dict[str, Any]:
        return self._run_sequence(operations, ("finalize", "validate", "submit"))

    def validate_and_submit(
        self,
        operations: Mapping[str, object],
    ) -> dict[str, Any]:
        return self._run_sequence(operations, ("validate", "submit"))


class HostSupervisor:
    """保持 Core thread 连续，为每个 Action 创建全新宿主 context。"""

    def __init__(self, backend: HostInvocationBackend) -> None:
        self._backend = backend

    def run(
        self,
        initial_request: ActionExecutionRequest,
        *,
        advance: Callable[
            [ActionExecutionReceipt],
            ActionExecutionRequest | None,
        ],
        on_failure: Callable[
            [ActionExecutionRequest, ActionExecutionReceipt],
            ActionExecutionRequest | None,
        ] | None = None,
        on_receipt: Callable[
            [ActionExecutionRequest, ActionExecutionReceipt],
            None,
        ] | None = None,
    ) -> HostSupervisorResult:
        self._backend.probe().require_supported()
        request: ActionExecutionRequest | None = initial_request
        receipts: list[ActionExecutionReceipt] = []
        context_ids: set[str] = set()
        while request is not None:
            receipt = self._backend.execute(request)
            receipt.validate_for(request)
            if receipt.host_context_id in context_ids:
                raise ActionExecutionContractError("HOST_CONTEXT_REUSED")
            context_ids.add(receipt.host_context_id)
            if on_receipt is not None:
                on_receipt(request, receipt)
            if receipt.status != "completed" or receipt.exit_code != 0:
                if on_failure is not None:
                    request = on_failure(request, receipt)
                    continue
                code = receipt.error_code or "HOST_ACTION_EXECUTION_FAILED"
                raise ActionExecutionContractError(code)
            receipts.append(receipt)
            request = advance(receipt)
        return HostSupervisorResult(tuple(receipts))


@dataclass(frozen=True, slots=True)
class ActionScopedProductResult:
    supervisor: HostSupervisorResult
    final_action: dict[str, Any]


class ActionScopedProductDriver:
    """把一次用户启动连接到多个隔离 Action context 和 Core 机器操作。"""

    def __init__(
        self,
        backend: HostInvocationBackend,
        *,
        compile_request: Callable[[Mapping[str, Any]], ActionExecutionRequest],
        execute_operations: Callable[[Mapping[str, object]], dict[str, Any]],
        submit_failure: Callable[
            [Mapping[str, Any], ActionExecutionReceipt],
            dict[str, Any],
        ] | None = None,
        receipt_sink: Callable[
            [ActionExecutionRequest, ActionExecutionReceipt],
            None,
        ] | None = None,
    ) -> None:
        self._supervisor = HostSupervisor(backend)
        self._compile_request = compile_request
        self._execute_operations = execute_operations
        self._submit_failure = submit_failure
        self._receipt_sink = receipt_sink

    def run(self, initial_action: Mapping[str, Any]) -> ActionScopedProductResult:
        current_action = dict(initial_action)
        if decide_host_step(current_action) is not HostDriverDecision.EXECUTE_NEXT:
            return ActionScopedProductResult(
                HostSupervisorResult(()),
                current_action,
            )

        def advance(_: ActionExecutionReceipt) -> ActionExecutionRequest | None:
            nonlocal current_action
            host_execution = current_action.get("host_execution")
            operations = (
                host_execution.get("operations")
                if isinstance(host_execution, Mapping)
                else None
            )
            if not isinstance(operations, Mapping):
                raise ActionExecutionContractError("HOST_OPERATIONS_MISSING")
            current_action = self._execute_operations(operations)
            if decide_host_step(current_action) is HostDriverDecision.EXECUTE_NEXT:
                return self._compile_request(current_action)
            return None

        def on_failure(
            _: ActionExecutionRequest,
            receipt: ActionExecutionReceipt,
        ) -> ActionExecutionRequest | None:
            nonlocal current_action
            if self._submit_failure is None:
                code = receipt.error_code or "HOST_ACTION_EXECUTION_FAILED"
                raise ActionExecutionContractError(code)
            current_action = self._submit_failure(current_action, receipt)
            if decide_host_step(current_action) is HostDriverDecision.EXECUTE_NEXT:
                return self._compile_request(current_action)
            return None

        supervisor = self._supervisor.run(
            self._compile_request(current_action),
            advance=advance,
            on_failure=on_failure,
            on_receipt=self._receipt_sink,
        )
        return ActionScopedProductResult(supervisor, current_action)


__all__ = [
    "ActionReceiptJournal",
    "ActionScopedProductDriver",
    "ActionScopedProductResult",
    "HostSupervisor",
    "HostSupervisorResult",
    "LoopStopReportJournal",
    "MachineOperationExecutor",
    "ProductEvidenceArtifactJournal",
]
