"""Action-scoped 宿主执行的严格请求、回执与后端协议。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ActionExecutionContractError(ValueError):
    """Action-scoped 请求或回执违反稳定协议。"""


def _exact_fields(value: Mapping[str, Any], expected: set[str], code: str) -> None:
    if set(value) != expected:
        raise ActionExecutionContractError(code)


def _text(value: object, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise ActionExecutionContractError(code)
    return value


def _digest(value: object) -> str:
    text = _text(value, "ACTION_EXECUTION_DIGEST_INVALID")
    if _SHA256.fullmatch(text) is None:
        raise ActionExecutionContractError("ACTION_EXECUTION_DIGEST_INVALID")
    return text


def _relative_path(value: object) -> str:
    text = _text(value, "ACTION_EXECUTION_PATH_INVALID")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise ActionExecutionContractError("ACTION_EXECUTION_PATH_INVALID")
    return text


@dataclass(frozen=True, slots=True)
class ActionExecutionRequest:
    """一个且仅一个 Canonical Action 的无历史宿主执行请求。"""

    schema_version: str
    thread_id: str
    action_message_id: str
    tick: int
    stage: str
    build_id: str
    project_root: str
    compact_envelope_ref: str
    compact_envelope_sha256: str
    coordinator_ref: str
    coordinator_sha256: str
    work_files: dict[str, str]
    allowed_tools: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ActionExecutionRequest:
        expected = set(cls.__dataclass_fields__)
        _exact_fields(value, expected, "ACTION_EXECUTION_REQUEST_FIELDS_INVALID")
        if value.get("schema_version") != "1.0":
            raise ActionExecutionContractError("ACTION_EXECUTION_SCHEMA_UNSUPPORTED")
        tick = value.get("tick")
        if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
            raise ActionExecutionContractError("ACTION_EXECUTION_TICK_INVALID")
        root = Path(_text(value.get("project_root"), "ACTION_EXECUTION_ROOT_INVALID"))
        if not root.is_absolute():
            raise ActionExecutionContractError("ACTION_EXECUTION_ROOT_INVALID")
        raw_work_files = value.get("work_files")
        if not isinstance(raw_work_files, Mapping):
            raise ActionExecutionContractError("ACTION_EXECUTION_WORK_FILES_INVALID")
        work_keys = {"outcomes", "coordinator_result", "result"}
        _exact_fields(
            raw_work_files,
            work_keys,
            "ACTION_EXECUTION_WORK_FILES_INVALID",
        )
        raw_tools = value.get("allowed_tools")
        if (
            not isinstance(raw_tools, list)
            or any(not isinstance(item, str) or not item for item in raw_tools)
            or len(set(raw_tools)) != len(raw_tools)
        ):
            raise ActionExecutionContractError("ACTION_EXECUTION_TOOLS_INVALID")
        return cls(
            schema_version="1.0",
            thread_id=_text(value.get("thread_id"), "ACTION_EXECUTION_IDENTITY_INVALID"),
            action_message_id=_text(
                value.get("action_message_id"),
                "ACTION_EXECUTION_IDENTITY_INVALID",
            ),
            tick=tick,
            stage=_text(value.get("stage"), "ACTION_EXECUTION_STAGE_INVALID"),
            build_id=_text(value.get("build_id"), "ACTION_EXECUTION_IDENTITY_INVALID"),
            project_root=str(root),
            compact_envelope_ref=_relative_path(value.get("compact_envelope_ref")),
            compact_envelope_sha256=_digest(value.get("compact_envelope_sha256")),
            coordinator_ref=_relative_path(value.get("coordinator_ref")),
            coordinator_sha256=_digest(value.get("coordinator_sha256")),
            work_files={key: _relative_path(raw_work_files[key]) for key in sorted(work_keys)},
            allowed_tools=tuple(raw_tools),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["allowed_tools"] = list(self.allowed_tools)
        return value


@dataclass(frozen=True, slots=True)
class ActionExecutionReceipt:
    """一次宿主 context 的有界、可审计执行回执。"""

    schema_version: str
    thread_id: str
    action_message_id: str
    build_id: str
    host_context_id: str
    backend: str
    status: str
    exit_code: int | None
    work_file_digests: dict[str, str]
    usage: dict[str, int | float | None]
    error_code: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ActionExecutionReceipt:
        required = set(cls.__dataclass_fields__) - {"error_code"}
        keys = frozenset(value)
        if keys not in {frozenset(required), frozenset(required | {"error_code"})}:
            raise ActionExecutionContractError("ACTION_EXECUTION_RECEIPT_FIELDS_INVALID")
        if value.get("schema_version") != "1.0":
            raise ActionExecutionContractError("ACTION_EXECUTION_SCHEMA_UNSUPPORTED")
        backend = _text(value.get("backend"), "ACTION_EXECUTION_BACKEND_INVALID")
        if backend not in {"codex", "claude"}:
            raise ActionExecutionContractError("ACTION_EXECUTION_BACKEND_INVALID")
        status = _text(value.get("status"), "ACTION_EXECUTION_STATUS_INVALID")
        if status not in {"completed", "failed", "cancelled", "timed_out"}:
            raise ActionExecutionContractError("ACTION_EXECUTION_STATUS_INVALID")
        exit_code = value.get("exit_code")
        if exit_code is not None and (
            not isinstance(exit_code, int) or isinstance(exit_code, bool)
        ):
            raise ActionExecutionContractError("ACTION_EXECUTION_EXIT_INVALID")
        raw_digests = value.get("work_file_digests")
        raw_usage = value.get("usage")
        if not isinstance(raw_digests, Mapping) or not isinstance(raw_usage, Mapping):
            raise ActionExecutionContractError("ACTION_EXECUTION_RECEIPT_INVALID")
        usage_keys = {"input_tokens", "cached_input_tokens", "output_tokens"}
        if not usage_keys.issubset(raw_usage) or set(raw_usage) - (usage_keys | {"cost_usd"}):
            raise ActionExecutionContractError("ACTION_EXECUTION_USAGE_INVALID")
        usage: dict[str, int | float | None] = {}
        for key, item in raw_usage.items():
            if item is not None and (
                not isinstance(item, (int, float))
                or isinstance(item, bool)
                or item < 0
            ):
                raise ActionExecutionContractError("ACTION_EXECUTION_USAGE_INVALID")
            usage[str(key)] = item
        error_code = value.get("error_code")
        if error_code is not None:
            error_code = _text(error_code, "ACTION_EXECUTION_ERROR_CODE_INVALID")
        return cls(
            schema_version="1.0",
            thread_id=_text(value.get("thread_id"), "ACTION_EXECUTION_IDENTITY_INVALID"),
            action_message_id=_text(
                value.get("action_message_id"),
                "ACTION_EXECUTION_IDENTITY_INVALID",
            ),
            build_id=_text(value.get("build_id"), "ACTION_EXECUTION_IDENTITY_INVALID"),
            host_context_id=_text(
                value.get("host_context_id"),
                "ACTION_EXECUTION_CONTEXT_INVALID",
            ),
            backend=backend,
            status=status,
            exit_code=exit_code,
            work_file_digests={str(key): _digest(item) for key, item in raw_digests.items()},
            usage=usage,
            error_code=error_code,
        )

    def validate_for(self, request: ActionExecutionRequest) -> None:
        if (
            self.thread_id != request.thread_id
            or self.action_message_id != request.action_message_id
            or self.build_id != request.build_id
        ):
            raise ActionExecutionContractError("ACTION_EXECUTION_IDENTITY_MISMATCH")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.error_code is None:
            value.pop("error_code")
        return value


@dataclass(frozen=True, slots=True)
class HostInvocationProbe:
    supported: bool
    backend: str
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if not self.backend or self.supported == (self.reason_code is not None):
            raise ActionExecutionContractError("HOST_INVOCATION_PROBE_INVALID")

    @classmethod
    def available(cls, backend: str) -> HostInvocationProbe:
        return cls(True, backend)

    @classmethod
    def unsupported(cls, backend: str, reason_code: str) -> HostInvocationProbe:
        if not reason_code:
            raise ActionExecutionContractError("HOST_INVOCATION_PROBE_INVALID")
        return cls(False, backend, reason_code)

    def require_supported(self) -> None:
        if not self.supported:
            raise ActionExecutionContractError(
                f"HOST_ACTION_CONTEXT_UNAVAILABLE: {self.reason_code}"
            )


class HostInvocationBackend(Protocol):
    """宿主一次性 context 后端；实现不得持有 Core 业务状态。"""

    def probe(self) -> HostInvocationProbe: ...

    def execute(self, request: ActionExecutionRequest) -> ActionExecutionReceipt: ...

    def cancel(self, host_context_id: str) -> None: ...


__all__ = [
    "ActionExecutionContractError",
    "ActionExecutionReceipt",
    "ActionExecutionRequest",
    "HostInvocationBackend",
    "HostInvocationProbe",
]
