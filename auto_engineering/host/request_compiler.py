"""Canonical Action 到一次性宿主执行请求的确定性编译器。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from auto_engineering.host.invocation import (
    ActionExecutionContractError,
    ActionExecutionRequest,
)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ActionExecutionContractError("ACTION_EXECUTION_ACTION_INVALID")
    return value


def _bound_file(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ActionExecutionContractError("ACTION_EXECUTION_PATH_INVALID")
    return path


def _build_id(action: Mapping[str, Any]) -> str:
    runtime_vector = action.get("runtime_vector")
    if isinstance(runtime_vector, Mapping):
        value = runtime_vector.get("engine_build_id")
        if isinstance(value, str) and value:
            return value
    extensions = action.get("extensions")
    ae = extensions.get("ae") if isinstance(extensions, Mapping) else None
    for key in ("runtime_revision", "runtime"):
        runtime = ae.get(key) if isinstance(ae, Mapping) else None
        if isinstance(runtime, Mapping):
            value = runtime.get("engine_build_id") or runtime.get("build_id")
            if isinstance(value, str) and value:
                return value
    raise ActionExecutionContractError("ACTION_EXECUTION_BUILD_ID_MISSING")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ActionExecutionContractError("ACTION_EXECUTION_ENVELOPE_CONFLICT")
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".action-envelope-",
        suffix=".json",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def compile_action_execution_request(
    action: Mapping[str, Any],
    *,
    compact_envelope: Mapping[str, Any],
    project_root: Path,
    allowed_tools: Sequence[str],
) -> ActionExecutionRequest:
    """编译并物化一个不含历史 transcript 的 ActionExecutionRequest。"""
    root = project_root.resolve()
    declared_root = Path(_text(action.get("project_root"))).resolve()
    if declared_root != root:
        raise ActionExecutionContractError("ACTION_EXECUTION_ROOT_MISMATCH")
    host_execution = action.get("host_execution")
    work_files = (
        host_execution.get("work_files")
        if isinstance(host_execution, Mapping)
        else None
    )
    if not isinstance(work_files, Mapping):
        raise ActionExecutionContractError("ACTION_EXECUTION_WORK_FILES_INVALID")
    work = {
        key: _text(work_files.get(key))
        for key in ("outcomes", "coordinator_result", "result")
    }
    for relative in work.values():
        _bound_file(root, relative)
    prompt_ref = compact_envelope.get("coordinator_prompt_ref")
    if not isinstance(prompt_ref, Mapping):
        raise ActionExecutionContractError("ACTION_EXECUTION_COORDINATOR_MISSING")
    coordinator_relative = _text(prompt_ref.get("path"))
    expected_digest = _text(prompt_ref.get("sha256"))
    coordinator_path = _bound_file(root, coordinator_relative)
    try:
        coordinator_digest = hashlib.sha256(coordinator_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ActionExecutionContractError(
            "ACTION_EXECUTION_COORDINATOR_MISSING"
        ) from exc
    if coordinator_digest != expected_digest:
        raise ActionExecutionContractError("ACTION_EXECUTION_COORDINATOR_DRIFT")
    envelope_payload = dict(compact_envelope)
    envelope_payload.pop("instruction", None)
    envelope_bytes = json.dumps(
        envelope_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    envelope_digest = hashlib.sha256(envelope_bytes).hexdigest()
    work_root = Path(work["result"]).parent
    envelope_relative = (
        work_root / f"action-envelope-{envelope_digest}.json"
    ).as_posix()
    _atomic_write(_bound_file(root, envelope_relative), envelope_bytes)
    return ActionExecutionRequest.from_dict({
        "schema_version": "1.0",
        "thread_id": _text(action.get("thread_id")),
        "action_message_id": _text(action.get("message_id")),
        "tick": action.get("tick"),
        "stage": _text(action.get("stage")),
        "build_id": _build_id(action),
        "project_root": str(root),
        "compact_envelope_ref": envelope_relative,
        "compact_envelope_sha256": envelope_digest,
        "coordinator_ref": coordinator_relative,
        "coordinator_sha256": coordinator_digest,
        "work_files": work,
        "allowed_tools": list(allowed_tools),
    })


__all__ = ["compile_action_execution_request"]
