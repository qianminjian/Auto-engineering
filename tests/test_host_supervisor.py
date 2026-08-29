"""T539：Action-scoped Supervisor 确定性驱动。"""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from auto_engineering.host.invocation import (
    ActionExecutionContractError,
    ActionExecutionReceipt,
    ActionExecutionRequest,
    HostInvocationProbe,
)


def _request(action_id: str, tick: int) -> ActionExecutionRequest:
    return ActionExecutionRequest.from_dict({
        "schema_version": "1.0",
        "thread_id": "thread-1",
        "action_message_id": action_id,
        "tick": tick,
        "stage": "developer",
        "build_id": "build-1",
        "project_root": "/tmp/product",
        "compact_envelope_ref": f".ae-state/work/{action_id}/envelope.json",
        "compact_envelope_sha256": "a" * 64,
        "coordinator_ref": f".ae-state/work/{action_id}/coordinator.md",
        "coordinator_sha256": "b" * 64,
        "work_files": {
            "outcomes": f".ae-state/work/{action_id}/outcomes.json",
            "coordinator_result": f".ae-state/work/{action_id}/coordinator.json",
            "result": f".ae-state/work/{action_id}/result.json",
        },
        "allowed_tools": ["read", "edit", "shell"],
    })


def _receipt(request: ActionExecutionRequest, context_id: str) -> ActionExecutionReceipt:
    return ActionExecutionReceipt.from_dict({
        "schema_version": "1.0",
        "thread_id": request.thread_id,
        "action_message_id": request.action_message_id,
        "build_id": request.build_id,
        "host_context_id": context_id,
        "backend": "codex",
        "status": "completed",
        "exit_code": 0,
        "work_file_digests": {},
        "usage": {
            "input_tokens": 10,
            "cached_input_tokens": 0,
            "output_tokens": 2,
        },
    })


class _FakeBackend:
    def __init__(self, context_ids: list[str], *, supported: bool = True) -> None:
        self.context_ids = iter(context_ids)
        self.supported = supported
        self.executed: list[str] = []

    def probe(self) -> HostInvocationProbe:
        if self.supported:
            return HostInvocationProbe.available("codex")
        return HostInvocationProbe.unsupported("codex", "CLI_MISSING")

    def execute(self, request: ActionExecutionRequest) -> ActionExecutionReceipt:
        self.executed.append(request.action_message_id)
        return _receipt(request, next(self.context_ids))

    def cancel(self, host_context_id: str) -> None:
        raise AssertionError(f"unexpected cancel: {host_context_id}")


def test_supervisor_drives_multiple_actions_with_fresh_contexts() -> None:
    from auto_engineering.host.supervisor import HostSupervisor

    backend = _FakeBackend(["context-1", "context-2"])
    pending = [_request("action-2", 2)]

    result = HostSupervisor(backend).run(
        _request("action-1", 1),
        advance=lambda _receipt: pending.pop(0) if pending else None,
    )

    assert backend.executed == ["action-1", "action-2"]
    assert [item.host_context_id for item in result.receipts] == [
        "context-1",
        "context-2",
    ]
    assert result.actions_completed == 2


def test_supervisor_emits_each_receipt_with_its_bound_request() -> None:
    from auto_engineering.host.supervisor import HostSupervisor

    backend = _FakeBackend(["context-1", "context-2"])
    pending = [_request("action-2", 2)]
    observed: list[tuple[str, str]] = []

    HostSupervisor(backend).run(
        _request("action-1", 1),
        advance=lambda _receipt: pending.pop(0) if pending else None,
        on_receipt=lambda request, receipt: observed.append((
            request.action_message_id,
            receipt.host_context_id,
        )),
    )

    assert observed == [
        ("action-1", "context-1"),
        ("action-2", "context-2"),
    ]


def test_action_receipt_journal_persists_bounded_cost_and_identity(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.supervisor import ActionReceiptJournal

    request = replace(_request("action-1", 1), project_root=str(tmp_path))
    receipt = _receipt(request, "context-1")
    journal = ActionReceiptJournal(tmp_path)

    first = journal.record(request, receipt)
    second = journal.record(request, receipt)

    assert first == second
    files = list(
        (tmp_path / ".ae-state/host-runtime/receipts").glob("*.json")
    )
    assert files == [first]
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["action_message_id"] == "action-1"
    assert payload["host_context_id"] == "context-1"
    assert payload["tick"] == 1
    assert payload["stage"] == "developer"
    assert payload["usage"]["input_tokens"] == 10
    assert "prompt" not in payload


def test_action_receipt_journal_sums_persisted_thread_cost(tmp_path: Path) -> None:
    from auto_engineering.host.supervisor import ActionReceiptJournal

    journal = ActionReceiptJournal(tmp_path)
    for tick, cost in ((1, 0.4), (2, 0.7)):
        request = replace(
            _request(f"action-{tick}", tick), project_root=str(tmp_path),
        )
        receipt = replace(
            _receipt(request, f"context-{tick}"),
            usage={
                "input_tokens": 10,
                "cached_input_tokens": 0,
                "output_tokens": 2,
                "cost_usd": cost,
            },
        )
        journal.record(request, receipt)

    assert journal.total_cost_usd("thread-1") == pytest.approx(1.1)
    assert journal.total_cost_usd("other-thread") == 0.0


def test_terminal_product_evidence_is_built_from_persisted_receipts(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.supervisor import (
        ActionReceiptJournal,
        ProductEvidenceArtifactJournal,
    )

    build_id = "5.8.0-rc.5+sha256.abcdef0123456789"
    runtime_root = tmp_path / "installed-release"
    runtime_root.mkdir()
    (runtime_root / "build-info.json").write_text(
        json.dumps({"build_id": build_id}), encoding="utf-8",
    )
    receipt_journal = ActionReceiptJournal(tmp_path)
    for tick, stage in enumerate(("architect", "developer", "critic"), start=1):
        request = replace(
            _request(f"action-{tick}", tick),
            project_root=str(tmp_path),
            stage=stage,
            build_id=build_id,
        )
        receipt_journal.record(request, _receipt(request, f"context-{tick}"))

    artifact = ProductEvidenceArtifactJournal(
        tmp_path,
        runtime_root=runtime_root,
    ).record_terminal(
        host="codex",
        thread_id="thread-1",
        final_action={"action": "done", "reason_code": "GOAL_ACHIEVED"},
        event_types=("ActionIssued", "ResultAccepted", "LoopCompleted"),
    )

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.1"
    assert payload["build_id"] == build_id
    assert payload["terminal_action"]["action"] == "done"
    assert [item["stage"] for item in payload["action_receipts"]] == [
        "architect", "developer", "critic",
    ]
    assert len({
        item["host_context_id"] for item in payload["action_receipts"]
    }) == 3
    assert "prompt" not in artifact.read_text(encoding="utf-8").lower()


def test_terminal_evidence_allows_same_action_repair_in_fresh_context(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.supervisor import (
        ActionReceiptJournal,
        ProductEvidenceArtifactJournal,
    )

    build_id = "5.8.0-rc.5+sha256.abcdef0123456789"
    runtime_root = tmp_path / "installed-release"
    runtime_root.mkdir()
    (runtime_root / "build-info.json").write_text(
        json.dumps({"build_id": build_id}), encoding="utf-8"
    )
    journal = ActionReceiptJournal(tmp_path)
    for context_id in ("context-first", "context-repair"):
        request = replace(
            _request("action-gap", 1),
            project_root=str(tmp_path),
            stage="gap_scan",
            build_id=build_id,
        )
        journal.record(request, _receipt(request, context_id))

    artifact = ProductEvidenceArtifactJournal(
        tmp_path, runtime_root=runtime_root
    ).record_terminal(
        host="codex",
        thread_id="thread-1",
        final_action={"action": "done"},
        event_types=("ActionIssued", "ResultAccepted", "LoopCompleted"),
    )

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["trajectory"]["automatic_result_repairs"] == 1


def test_product_evidence_refuses_non_terminal_or_reused_context(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.supervisor import (
        ActionReceiptJournal,
        ProductEvidenceArtifactJournal,
    )

    build_id = "5.8.0-rc.5+sha256.abcdef0123456789"
    runtime_root = tmp_path / "installed-release"
    runtime_root.mkdir()
    (runtime_root / "build-info.json").write_text(
        json.dumps({"build_id": build_id}), encoding="utf-8",
    )
    request = replace(
        _request("action-1", 1),
        project_root=str(tmp_path),
        build_id=build_id,
    )
    journal = ActionReceiptJournal(tmp_path)
    journal.record(request, _receipt(request, "same-context"))
    second = replace(request, action_message_id="action-2", tick=2)
    journal.record(second, _receipt(second, "same-context"))
    evidence = ProductEvidenceArtifactJournal(
        tmp_path,
        runtime_root=runtime_root,
    )

    with pytest.raises(ActionExecutionContractError, match="PRODUCT_TERMINAL_REQUIRED"):
        evidence.record_terminal(
            host="codex", thread_id="thread-1",
            final_action={"action": "resource_wait"}, event_types=(),
        )
    with pytest.raises(ActionExecutionContractError, match="HOST_CONTEXT_REUSED"):
        evidence.record_terminal(
            host="codex", thread_id="thread-1",
            final_action={"action": "done"},
            event_types=("LoopCompleted",),
        )


def test_supervisor_rejects_reused_host_context_identity() -> None:
    from auto_engineering.host.supervisor import HostSupervisor

    backend = _FakeBackend(["same-context", "same-context"])
    pending = [_request("action-2", 2)]
    with pytest.raises(
        ActionExecutionContractError,
        match="HOST_CONTEXT_REUSED",
    ):
        HostSupervisor(backend).run(
            _request("action-1", 1),
            advance=lambda _receipt: pending.pop(0) if pending else None,
        )


def test_supervisor_fails_before_execution_when_backend_is_unavailable() -> None:
    from auto_engineering.host.supervisor import HostSupervisor

    backend = _FakeBackend([], supported=False)
    with pytest.raises(
        ActionExecutionContractError,
        match="HOST_ACTION_CONTEXT_UNAVAILABLE",
    ):
        HostSupervisor(backend).run(_request("action-1", 1), advance=lambda _: None)
    assert backend.executed == []


def test_supervisor_does_not_advance_failed_or_mismatched_receipt() -> None:
    from auto_engineering.host.supervisor import HostSupervisor

    class _InvalidBackend(_FakeBackend):
        def execute(self, request: ActionExecutionRequest) -> ActionExecutionReceipt:
            self.executed.append(request.action_message_id)
            return replace(_receipt(request, "context-1"), action_message_id="stale")

    advanced = False

    def advance(_: ActionExecutionReceipt) -> None:
        nonlocal advanced
        advanced = True

    with pytest.raises(
        ActionExecutionContractError,
        match="ACTION_EXECUTION_IDENTITY_MISMATCH",
    ):
        HostSupervisor(_InvalidBackend(["unused"])).run(
            _request("action-1", 1),
            advance=advance,
        )
    assert advanced is False


def test_machine_operations_execute_exact_argv_without_shell(tmp_path: Path) -> None:
    from auto_engineering.host.supervisor import MachineOperationExecutor

    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
    next_action = {"message_id": "action-2", "action": "execute"}

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs))
        stdout = json.dumps(next_action) if "--tick" in command else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    operations = {
        "finalize": {"argv": ["__AE_BUNDLED_RUNNER__", "dev-loop", "--finalize-result", "in.json"]},
        "validate": {"argv": ["__AE_BUNDLED_RUNNER__", "dev-loop", "--validate-result", "out.json"]},
        "submit": {"argv": ["__AE_BUNDLED_RUNNER__", "dev-loop", "--tick", "--result", "out.json"]},
    }
    result = MachineOperationExecutor(
        project_root=tmp_path,
        bundled_runner=Path("/release/scripts/ae-run"),
        runner=run,
    ).run(operations)

    assert result == next_action
    assert [call[0][0] for call in calls] == ["/release/scripts/ae-run"] * 3
    assert all(call[1]["cwd"] == str(tmp_path.resolve()) for call in calls)
    assert all("shell" not in call[1] for call in calls)


def test_machine_operations_return_same_action_repair_after_assembly_rejection(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.supervisor import MachineOperationExecutor

    calls: list[str] = []
    repair_action = {
        "message_id": "action-1",
        "action": "gap_scan",
        "result_rejection": {"repair_required": True},
    }

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append("finalize")
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(repair_action), stderr=""
        )

    operations = {
        "finalize": {"argv": ["__AE_BUNDLED_RUNNER__", "--finalize-result"]},
        "validate": {"argv": ["__AE_BUNDLED_RUNNER__", "--validate-result"]},
        "submit": {"argv": ["__AE_BUNDLED_RUNNER__", "--tick"]},
    }
    result = MachineOperationExecutor(
        project_root=tmp_path,
        bundled_runner=Path("/release/scripts/ae-run"),
        runner=run,
    ).run(operations)

    assert result == repair_action
    assert calls == ["finalize"]


def test_product_driver_fails_closed_on_outcome_journal_conflict() -> None:
    from auto_engineering.host.supervisor import ActionScopedProductDriver

    request = _request("action-1", 1)
    action = {
        "message_id": "action-1",
        "host_execution": {"operations": {"id": 1}},
        "extensions": {"ae": {"execution_control": {
            "schema_version": "1.0", "disposition": "CONTINUE",
            "continuation_required": True, "yield_allowed": False,
            "reason_code": "ACTION_REQUIRED",
        }}},
    }
    conflict = {
        **action,
        "result_rejection": {
            "repair_required": True,
            "error_code": "HOST_EVIDENCE_INVALID",
            "violations": ["OUTCOME_JOURNAL_CONFLICT"],
        },
    }
    backend = _FakeBackend(["context-1", "context-2"])

    with pytest.raises(
        ActionExecutionContractError,
        match="OUTCOME_JOURNAL_CONFLICT",
    ):
        ActionScopedProductDriver(
            backend,
            compile_request=lambda _: request,
            execute_operations=lambda _: conflict,
        ).run(action)

    assert backend.executed == ["action-1"]


def test_machine_operations_return_same_action_repair_after_prevalidation(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.supervisor import MachineOperationExecutor

    calls: list[str] = []
    repair_action = {
        "message_id": "action-gap",
        "action": "gap_scan",
        "result_rejection": {"repair_required": True},
    }

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        operation = "validate" if "--validate-result" in command else "finalize"
        calls.append(operation)
        output = json.dumps(repair_action) if operation == "validate" else "{}"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    operations = {
        "finalize": {"argv": ["__AE_BUNDLED_RUNNER__", "--finalize-result"]},
        "validate": {"argv": ["__AE_BUNDLED_RUNNER__", "--validate-result"]},
        "submit": {"argv": ["__AE_BUNDLED_RUNNER__", "--tick"]},
    }

    result = MachineOperationExecutor(
        project_root=tmp_path,
        bundled_runner=Path("/release/scripts/ae-run"),
        runner=run,
    ).run(operations)

    assert result == repair_action
    assert calls == ["finalize", "validate"]


def test_machine_operations_stop_before_submit_on_validation_failure(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.supervisor import (
        ActionExecutionContractError,
        MachineOperationExecutor,
    )

    calls: list[str] = []

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        operation = "validate" if "--validate-result" in command else "finalize"
        calls.append(operation)
        return subprocess.CompletedProcess(
            command,
            4 if operation == "validate" else 0,
            stdout="",
            stderr="invalid",
        )

    operations = {
        "finalize": {"argv": ["__AE_BUNDLED_RUNNER__", "--finalize-result"]},
        "validate": {"argv": ["__AE_BUNDLED_RUNNER__", "--validate-result"]},
        "submit": {"argv": ["__AE_BUNDLED_RUNNER__", "--tick"]},
    }
    with pytest.raises(
        ActionExecutionContractError,
        match="HOST_OPERATION_VALIDATE_FAILED",
    ):
        MachineOperationExecutor(
            project_root=tmp_path,
            bundled_runner=Path("/release/scripts/ae-run"),
            runner=run,
        ).run(operations)
    assert calls == ["finalize", "validate"]
    diagnostic_path = (
        tmp_path
        / ".ae-state/host-runtime/diagnostics/machine-operation-validate.json"
    )
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    assert diagnostic == {
        "schema_version": "1.0",
        "operation": "validate",
        "status": "failed",
        "exit_code": 4,
        "stdout_tail": "",
        "stderr_tail": "invalid",
    }


def test_failure_path_validates_and_submits_without_finalize(tmp_path: Path) -> None:
    from auto_engineering.host.supervisor import MachineOperationExecutor

    calls: list[str] = []

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        operation = "submit" if "--tick" in command else "validate"
        calls.append(operation)
        output = json.dumps({"message_id": "wait-1"}) if operation == "submit" else ""
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    operations = {
        "finalize": {"argv": ["__AE_BUNDLED_RUNNER__", "--finalize-result"]},
        "validate": {"argv": ["__AE_BUNDLED_RUNNER__", "--validate-result"]},
        "submit": {"argv": ["__AE_BUNDLED_RUNNER__", "--tick"]},
    }
    result = MachineOperationExecutor(
        project_root=tmp_path,
        bundled_runner=Path("/release/scripts/ae-run"),
        runner=run,
    ).validate_and_submit(operations)
    assert result == {"message_id": "wait-1"}
    assert calls == ["validate", "submit"]


def test_machine_operation_timeout_stops_the_sequence(tmp_path: Path) -> None:
    from auto_engineering.host.supervisor import MachineOperationExecutor

    calls: list[str] = []

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        operation = "validate" if "--validate-result" in command else "finalize"
        calls.append(operation)
        if operation == "validate":
            raise subprocess.TimeoutExpired(command, timeout=2)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    operations = {
        "finalize": {"argv": ["__AE_BUNDLED_RUNNER__", "--finalize-result"]},
        "validate": {"argv": ["__AE_BUNDLED_RUNNER__", "--validate-result"]},
        "submit": {"argv": ["__AE_BUNDLED_RUNNER__", "--tick"]},
    }
    with pytest.raises(
        ActionExecutionContractError,
        match="HOST_OPERATION_VALIDATE_TIMEOUT",
    ):
        MachineOperationExecutor(
            project_root=tmp_path,
            bundled_runner=Path("/release/scripts/ae-run"),
            runner=run,
            timeout_seconds=2,
        ).run(operations)
    assert calls == ["finalize", "validate"]


def test_product_driver_runs_actions_until_terminal_without_model_for_terminal() -> None:
    from auto_engineering.host.supervisor import ActionScopedProductDriver

    backend = _FakeBackend(["context-1", "context-2"])
    actions = [
        {"message_id": "action-1", "host_execution": {"operations": {"id": 1}},
         "extensions": {"ae": {"execution_control": {
             "schema_version": "1.0",
             "disposition": "CONTINUE", "continuation_required": True,
             "yield_allowed": False, "reason_code": "ACTION_REQUIRED",
         }}}},
        {"message_id": "action-2", "host_execution": {"operations": {"id": 2}},
         "extensions": {"ae": {"execution_control": {
             "schema_version": "1.0",
             "disposition": "CONTINUE", "continuation_required": True,
             "yield_allowed": False, "reason_code": "ACTION_REQUIRED",
         }}}},
        {"message_id": "terminal", "extensions": {"ae": {"execution_control": {
            "schema_version": "1.0",
            "disposition": "TERMINAL", "continuation_required": False,
            "yield_allowed": True, "reason_code": "GOAL_ACHIEVED",
        }}}},
    ]
    requests = {
        "action-1": _request("action-1", 1),
        "action-2": _request("action-2", 2),
    }
    operation_ids: list[int] = []

    def execute_operations(raw: object) -> dict[str, object]:
        assert isinstance(raw, dict)
        operation_ids.append(int(raw["id"]))
        return actions[len(operation_ids)]

    result = ActionScopedProductDriver(
        backend,
        compile_request=lambda action: requests[str(action["message_id"])],
        execute_operations=execute_operations,
    ).run(actions[0])

    assert result.final_action["message_id"] == "terminal"
    assert result.supervisor.actions_completed == 2
    assert operation_ids == [1, 2]
    assert backend.executed == ["action-1", "action-2"]


def test_supervisor_routes_failed_receipt_to_deterministic_failure_handler() -> None:
    from auto_engineering.host.supervisor import HostSupervisor

    request = _request("action-1", 1)

    class FailedBackend(_FakeBackend):
        def execute(self, request):
            return replace(
                _receipt(request, "context-failed"),
                status="timed_out",
                exit_code=None,
                error_code="HOST_CODEX_EXECUTION_TIMEOUT",
            )

    failures: list[str] = []
    result = HostSupervisor(FailedBackend(["unused"])).run(
        request,
        advance=lambda _: pytest.fail("failed receipt must not use normal advance"),
        on_failure=lambda _request, receipt: failures.append(
            str(receipt.error_code)
        ) or None,
    )
    assert failures == ["HOST_CODEX_EXECUTION_TIMEOUT"]
    assert result.actions_completed == 0


def test_product_driver_submits_context_failure_to_core_wait_state() -> None:
    from auto_engineering.host.supervisor import ActionScopedProductDriver

    request = _request("action-1", 1)
    action = {
        "message_id": "action-1",
        "host_execution": {"operations": {"id": 1}},
        "extensions": {"ae": {"execution_control": {
            "schema_version": "1.0", "disposition": "CONTINUE",
            "continuation_required": True, "yield_allowed": False,
            "reason_code": "ACTION_REQUIRED",
        }}},
    }

    class FailedBackend(_FakeBackend):
        def execute(self, request):
            return replace(
                _receipt(request, "context-failed"),
                status="failed",
                exit_code=8,
                error_code="HOST_CODEX_EXECUTION_FAILED",
            )

    failures: list[str] = []

    def submit_failure(_action, receipt):
        failures.append(str(receipt.error_code))
        return {
            "message_id": "wait-1",
            "extensions": {"ae": {"execution_control": {
                "schema_version": "1.0", "disposition": "WAIT_RESOURCE",
                "continuation_required": False, "yield_allowed": True,
                "reason_code": "HOST_WORKER_FAILED",
            }}},
        }

    result = ActionScopedProductDriver(
        FailedBackend(["unused"]),
        compile_request=lambda _: request,
        execute_operations=lambda _: pytest.fail("normal operations must not run"),
        submit_failure=submit_failure,
    ).run(action)
    assert failures == ["HOST_CODEX_EXECUTION_FAILED"]
    assert result.final_action["message_id"] == "wait-1"


def test_stop_report_uses_action_and_receipt_facts_without_transcript(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.supervisor import (
        ActionReceiptJournal,
        LoopStopReportJournal,
    )

    request = _request("action-1", 7)
    receipt = _receipt(request, "context-1")
    ActionReceiptJournal(tmp_path).record(request, receipt)
    final_action = {
        "schema_version": "1.1",
        "message_type": "action",
        "message_id": "wait-1",
        "thread_id": request.thread_id,
        "tick": 7,
        "stage": "critic",
        "action": "resource_wait",
        "reason_code": "HOST_ACTION_CONTEXT_FAILED",
        "message": "结果协议无效",
        "retry_stage": "critic",
        "extensions": {"ae": {"execution_control": {
            "schema_version": "1.0",
            "disposition": "WAIT_RESOURCE",
            "continuation_required": False,
            "yield_allowed": True,
            "reason_code": "HOST_ACTION_CONTEXT_FAILED",
        }}},
    }

    path = LoopStopReportJournal(tmp_path).record(
        thread_id=request.thread_id,
        final_action=final_action,
    )
    report = path.read_text(encoding="utf-8")

    assert "WAIT_RESOURCE" in report
    assert "HOST_ACTION_CONTEXT_FAILED" in report
    assert "action-1" in report
    assert "context-1" in report
    assert "等待资源恢复后重试 critic" in report
    assert "transcript" not in report.lower()
    assert "prompt" not in report.lower()
