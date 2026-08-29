"""回归覆盖：安全日志与宿主预算边界必须 fail-closed。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_engineering.host.invocation import (
    ActionExecutionContractError,
    ActionExecutionReceipt,
)
from auto_engineering.observability.audit_log import AuditLogger, _canonical_bytes


def test_audit_logger_rejects_invalid_size_limits(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="单条上限"):
        AuditLogger(tmp_path, max_entry_bytes=128)
    with pytest.raises(ValueError, match="文件上限"):
        AuditLogger(tmp_path, max_entry_bytes=512, max_log_bytes=256)


def test_audit_summary_handles_circular_values_without_crashing() -> None:
    circular: list[object] = []
    circular.append(circular)
    assert _canonical_bytes(circular)


def test_audit_logger_bounds_debug_payload_and_tool_summary(tmp_path: Path) -> None:
    logger = AuditLogger(
        tmp_path,
        debug_full=True,
        max_entry_bytes=256,
        max_log_bytes=4096,
    )
    logger.log_call(
        stage="developer",
        provider="test",
        model="test-model",
        request_messages=[{"role": "user", "content": "x" * 2000}],
        request_tools=[{"name": "tool"}],
        response={"content": "y" * 2000},
    )
    payload = json.loads((tmp_path / "llm-calls.jsonl").read_text())
    assert payload["bounded"] is True
    assert payload["entry_bytes"] > 256


def test_audit_logger_replaces_previous_rotated_file(tmp_path: Path) -> None:
    logger = AuditLogger(tmp_path, max_entry_bytes=256, max_log_bytes=256)
    for _ in range(3):
        logger.log_event(event="tick", payload="z" * 2000)
    assert (tmp_path / "llm-calls.jsonl.1").is_file()


def test_supervisor_rejects_non_finite_and_invalid_limits() -> None:
    from auto_engineering.host.supervisor import HostSupervisor

    class _Backend:
        def probe(self):
            raise AssertionError("probe should not be called")

    with pytest.raises(ValueError, match="有限正数"):
        HostSupervisor(_Backend(), max_elapsed_seconds=float("inf"))
    with pytest.raises(ValueError, match="有限正数"):
        HostSupervisor(_Backend(), max_total_cost_usd=float("nan"))
    with pytest.raises(ValueError, match="输出 Token"):
        HostSupervisor(_Backend(), max_total_output_tokens=0)


def test_receipt_journal_rejects_non_finite_persisted_cost(tmp_path: Path) -> None:
    from auto_engineering.host.supervisor import ActionReceiptJournal

    directory = tmp_path / ".ae-state/host-runtime/receipts"
    directory.mkdir(parents=True)
    (directory / "invalid.json").write_text(
        json.dumps({"thread_id": "thread-1", "usage": {"cost_usd": "nan"}}),
        encoding="utf-8",
    )
    with pytest.raises(ActionExecutionContractError, match="PRODUCT_RECEIPT_INVALID"):
        ActionReceiptJournal(tmp_path).total_cost_usd("thread-1")


def test_receipt_rejects_non_finite_usage_values() -> None:
    with pytest.raises(ValueError, match="ACTION_EXECUTION_USAGE_INVALID"):
        ActionExecutionReceipt.from_dict({
            "schema_version": "1.0",
            "thread_id": "thread-1",
            "action_message_id": "action-1",
            "build_id": "build-1",
            "host_context_id": "context-1",
            "backend": "codex",
            "status": "completed",
            "exit_code": 0,
            "work_file_digests": {},
            "usage": {"input_tokens": float("inf")},
        })


def test_stop_report_next_steps_are_deterministic() -> None:
    from auto_engineering.host.supervisor import LoopStopReportJournal

    action = {"stage": "developer"}
    assert LoopStopReportJournal._next_step(action, "WAIT_USER").startswith("按 Core")
    assert "ResumeCapsule" in LoopStopReportJournal._next_step(action, "HANDOFF_REQUIRED")
    assert "同一 active Action" in LoopStopReportJournal._next_step(action, "UNKNOWN")


def test_stop_report_is_machine_generated_without_receipts(tmp_path: Path) -> None:
    from auto_engineering.host.supervisor import LoopStopReportJournal

    report = LoopStopReportJournal(tmp_path).record(
        thread_id="thread-1",
        final_action={
            "message_id": "action-1",
            "stage": "developer",
            "tick": 3,
            "reason_code": "HOST_USAGE_MISSING",
            "message": "需要补充宿主用量",
            "extensions": {"ae": {"execution_control": {
                "disposition": "WAIT_RESOURCE",
            }}},
        },
    )
    content = report.read_text(encoding="utf-8")
    assert "HOST_USAGE_MISSING" in content
    assert "无已持久化宿主回执" in content
