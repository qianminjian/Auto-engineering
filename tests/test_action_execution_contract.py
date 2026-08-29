"""T537：Action-scoped 宿主执行请求与回执契约。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "auto_engineering" / "loop"


def _schema(name: str) -> dict[str, object]:
    path = SCHEMA_ROOT / name
    assert path.is_file(), f"缺少 Action-scoped 协议：{name}"
    value = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(value)
    return value


def _request() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "thread_id": "thread-1",
        "action_message_id": "action-1",
        "tick": 7,
        "stage": "developer",
        "build_id": "5.8.0+sha256.abc",
        "project_root": "/tmp/product",
        "compact_envelope_ref": ".ae-state/host-runtime/work/a/envelope.json",
        "compact_envelope_sha256": "a" * 64,
        "coordinator_ref": ".ae-state/host-runtime/work/a/coordinator.md",
        "coordinator_sha256": "b" * 64,
        "work_files": {
            "outcomes": ".ae-state/host-runtime/work/a/outcomes.json",
            "coordinator_result": ".ae-state/host-runtime/work/a/coordinator-result.json",
            "result": ".ae-state/host-runtime/work/a/result.json",
        },
        "allowed_tools": ["read", "edit", "shell"],
    }


def test_action_execution_request_schema_accepts_minimal_bounded_request() -> None:
    Draft202012Validator(_schema("action-execution-request.schema.json")).validate(
        _request()
    )


@pytest.mark.parametrize("forbidden", ["transcript", "recap", "messages", "event_store"])
def test_action_execution_request_rejects_conversation_history(
    forbidden: str,
) -> None:
    request = _request()
    request[forbidden] = "historical context"
    with pytest.raises(ValidationError):
        Draft202012Validator(
            _schema("action-execution-request.schema.json")
        ).validate(request)


def test_action_execution_receipt_requires_exact_action_and_context_identity() -> None:
    schema = _schema("action-execution-receipt.schema.json")
    receipt = {
        "schema_version": "1.0",
        "thread_id": "thread-1",
        "action_message_id": "action-1",
        "build_id": "5.8.0+sha256.abc",
        "host_context_id": "codex-ephemeral-1",
        "backend": "codex",
        "status": "completed",
        "exit_code": 0,
        "work_file_digests": {"result": "c" * 64},
        "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 2},
    }
    Draft202012Validator(schema).validate(receipt)
    del receipt["action_message_id"]
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(receipt)


def test_request_value_object_rejects_path_escape_and_round_trips() -> None:
    from auto_engineering.host.invocation import (
        ActionExecutionContractError,
        ActionExecutionRequest,
    )

    request = ActionExecutionRequest.from_dict(_request())
    assert request.to_dict() == _request()

    escaped = _request()
    escaped["coordinator_ref"] = "../outside.md"
    with pytest.raises(
        ActionExecutionContractError,
        match="ACTION_EXECUTION_PATH_INVALID",
    ):
        ActionExecutionRequest.from_dict(escaped)


@pytest.mark.parametrize(
    "escaped_path",
    [
        r"..\\outside.json",
        r"subdir\\..\\..\\outside.json",
        r"C:\\outside.json",
        r"\\\\server\\share\\outside.json",
    ],
)
def test_request_value_object_rejects_windows_path_escape_on_all_hosts(
    escaped_path: str,
) -> None:
    from auto_engineering.host.invocation import (
        ActionExecutionContractError,
        ActionExecutionRequest,
    )

    request = _request()
    request["coordinator_ref"] = escaped_path
    with pytest.raises(
        ActionExecutionContractError,
        match="ACTION_EXECUTION_PATH_INVALID",
    ):
        ActionExecutionRequest.from_dict(request)


def test_receipt_must_bind_the_expected_request_identity() -> None:
    from auto_engineering.host.invocation import (
        ActionExecutionContractError,
        ActionExecutionReceipt,
        ActionExecutionRequest,
    )

    request = ActionExecutionRequest.from_dict(_request())
    receipt = ActionExecutionReceipt.from_dict({
        "schema_version": "1.0",
        "thread_id": "thread-1",
        "action_message_id": "different-action",
        "build_id": "5.8.0+sha256.abc",
        "host_context_id": "context-1",
        "backend": "codex",
        "status": "completed",
        "exit_code": 0,
        "work_file_digests": {},
        "usage": {
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
        },
    })
    with pytest.raises(
        ActionExecutionContractError,
        match="ACTION_EXECUTION_IDENTITY_MISMATCH",
    ):
        receipt.validate_for(request)


def test_host_invocation_probe_is_fail_closed() -> None:
    from auto_engineering.host.invocation import (
        ActionExecutionContractError,
        HostInvocationProbe,
    )

    unavailable = HostInvocationProbe.unsupported(
        "claude",
        "HOST_NESTED_INVOCATION_UNAVAILABLE",
    )
    with pytest.raises(
        ActionExecutionContractError,
        match="HOST_ACTION_CONTEXT_UNAVAILABLE",
    ):
        unavailable.require_supported()

    available = HostInvocationProbe.available("codex")
    available.require_supported()
    with pytest.raises(ActionExecutionContractError):
        HostInvocationProbe(True, "codex", "contradictory-reason")


def test_only_supported_hosts_declare_action_scoped_invocation() -> None:
    from auto_engineering.host import HostPlatform, capabilities_for

    assert capabilities_for(HostPlatform.CODEX).action_scoped_invocation is True
    assert capabilities_for(HostPlatform.CLAUDE_CODE).action_scoped_invocation is True
    assert capabilities_for(HostPlatform.CODEBUDDY).action_scoped_invocation is False
    assert capabilities_for(HostPlatform.UNKNOWN).action_scoped_invocation is False


def test_request_compiler_materializes_content_addressed_compact_envelope(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.request_compiler import compile_action_execution_request

    coordinator = tmp_path / ".ae-state/effects/prompt/coordinator.txt"
    coordinator.parent.mkdir(parents=True)
    coordinator.write_text("execute one action", encoding="utf-8")
    coordinator_digest = hashlib.sha256(coordinator.read_bytes()).hexdigest()
    action = {
        "thread_id": "thread-1",
        "message_id": "action-1",
        "tick": 3,
        "stage": "developer",
        "project_root": str(tmp_path.resolve()),
        "runtime_vector": {"engine_build_id": "build-1"},
        "host_execution": {
            "work_files": {
                "outcomes": ".ae-state/host-runtime/work/a/outcomes.json",
                "coordinator_result": ".ae-state/host-runtime/work/a/coordinator.json",
                "result": ".ae-state/host-runtime/work/a/result.json",
            },
        },
    }
    compact = {
        "thread_id": "thread-1",
        "message_id": "action-1",
        "tick": 3,
        "stage": "developer",
        "action": "execute",
        "coordinator_prompt_ref": {
            "path": ".ae-state/effects/prompt/coordinator.txt",
            "sha256": coordinator_digest,
        },
        "view": "compact",
    }

    request = compile_action_execution_request(
        action,
        compact_envelope=compact,
        project_root=tmp_path,
        allowed_tools=("read", "edit", "shell", "native_subagents"),
    )

    envelope = tmp_path / request.compact_envelope_ref
    assert envelope.is_file()
    assert hashlib.sha256(envelope.read_bytes()).hexdigest() == (
        request.compact_envelope_sha256
    )
    assert request.coordinator_sha256 == coordinator_digest
    assert request.build_id == "build-1"
    assert "instruction" not in json.loads(envelope.read_text(encoding="utf-8"))


def test_request_compiler_rejects_coordinator_digest_drift(tmp_path: Path) -> None:
    from auto_engineering.host.invocation import ActionExecutionContractError
    from auto_engineering.host.request_compiler import compile_action_execution_request

    coordinator = tmp_path / "coordinator.txt"
    coordinator.write_text("changed", encoding="utf-8")
    action = {
        "thread_id": "thread-1",
        "message_id": "action-1",
        "tick": 1,
        "stage": "critic",
        "project_root": str(tmp_path.resolve()),
        "runtime_vector": {"engine_build_id": "build-1"},
        "host_execution": {"work_files": {
            "outcomes": ".ae-state/work/a/outcomes.json",
            "coordinator_result": ".ae-state/work/a/coordinator.json",
            "result": ".ae-state/work/a/result.json",
        }},
    }
    compact = {
        "coordinator_prompt_ref": {
            "path": "coordinator.txt",
            "sha256": "0" * 64,
        },
    }
    with pytest.raises(
        ActionExecutionContractError,
        match="ACTION_EXECUTION_COORDINATOR_DRIFT",
    ):
        compile_action_execution_request(
            action,
            compact_envelope=compact,
            project_root=tmp_path,
            allowed_tools=("read",),
        )
