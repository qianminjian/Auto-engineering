"""宿主连续驱动租约与停止门禁。

本模块只固化宿主执行义务，不调用 LLM、不推进 Tick，也不修改业务状态。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from auto_engineering.host import HostPlatform
from auto_engineering.loop.execution_control import ExecutionControl


class HostRunLeaseError(ValueError):
    """运行租约缺失或与 Action 不一致。"""


class StopGuardDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


def fencing_token_for(action_message_id: str, host_session_id: str, generation: int) -> str:
    return hashlib.sha256(
        f"{action_message_id}:{host_session_id}:{generation}".encode()
    ).hexdigest()


def _resolve_fencing_token(
    *,
    action_message_id: str,
    host_session_id: str,
    generation: int,
    supplied: object,
    supplied_present: bool,
) -> str:
    """Return the identity-bound fence; reject explicit forged values."""

    expected = fencing_token_for(action_message_id, host_session_id, generation)
    # v1.0 callers could construct HostRunLease without the optional field,
    # which serializes as an empty string. Treat that legacy sentinel like a
    # missing value; any non-empty explicit value must still match exactly.
    if not supplied_present or supplied == "":
        return expected
    if (
        not isinstance(supplied, str)
        or len(supplied) != len(expected)
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HostRunLeaseError("HOST_RUN_LEASE_FENCE_INVALID")
    return expected


@dataclass(frozen=True, slots=True)
class HostRunLease:
    """绑定一次宿主会话与一个 active Action 的不可变执行义务。"""

    schema_version: str
    thread_id: str
    action_message_id: str
    platform: str
    host_session_id: str
    build_id: str
    disposition: str
    continuation_required: bool
    yield_allowed: bool
    execution_generation: int = 1
    fencing_token: str = ""

    @classmethod
    def from_action(
        cls,
        action: Mapping[str, Any],
        *,
        platform: str,
        host_session_id: str,
    ) -> HostRunLease:
        thread_id = action.get("thread_id")
        message_id = action.get("message_id")
        if (
            not isinstance(thread_id, str)
            or not thread_id
            or not isinstance(message_id, str)
            or not message_id
            or not platform
            or not host_session_id
        ):
            raise HostRunLeaseError("HOST_RUN_LEASE_IDENTITY_INVALID")
        generation = action.get("execution_generation", 1)
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
        ):
            raise HostRunLeaseError("HOST_RUN_LEASE_GENERATION_INVALID")
        fencing_token = _resolve_fencing_token(
            action_message_id=message_id,
            host_session_id=host_session_id,
            generation=generation,
            supplied=action.get("fencing_token"),
            supplied_present="fencing_token" in action,
        )
        extensions = action.get("extensions")
        ae = extensions.get("ae") if isinstance(extensions, Mapping) else None
        control_raw = ae.get("execution_control") if isinstance(ae, Mapping) else None
        if not isinstance(control_raw, Mapping):
            raise HostRunLeaseError("HOST_ACTION_EXECUTION_CONTROL_MISSING")
        control = ExecutionControl.from_dict(control_raw)
        runtime_vector = action.get("runtime_vector")
        build_id = (
            runtime_vector.get("engine_build_id")
            if isinstance(runtime_vector, Mapping)
            else None
        )
        if not isinstance(build_id, str) or not build_id:
            runtime_revision = (
                ae.get("runtime_revision") if isinstance(ae, Mapping) else None
            )
            build_id = (
                runtime_revision.get("engine_build_id")
                if isinstance(runtime_revision, Mapping)
                else None
            )
        if not isinstance(build_id, str) or not build_id:
            runtime = ae.get("runtime") if isinstance(ae, Mapping) else None
            build_id = runtime.get("build_id") if isinstance(runtime, Mapping) else None
        if not isinstance(build_id, str) or not build_id.strip():
            raise HostRunLeaseError("HOST_RUN_LEASE_BUILD_ID_MISSING")
        return cls(
            schema_version="1.0",
            thread_id=thread_id,
            action_message_id=message_id,
            platform=platform,
            host_session_id=host_session_id,
            build_id=build_id,
            disposition=control.disposition.value,
            continuation_required=control.continuation_required,
            yield_allowed=control.yield_allowed,
            execution_generation=generation,
            fencing_token=fencing_token,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> HostRunLease:
        expected = set(cls.__dataclass_fields__)
        optional = {"execution_generation", "fencing_token"}
        if set(value) - expected or (set(value) | optional) < expected:
            raise HostRunLeaseError("HOST_RUN_LEASE_FIELDS_INVALID")
        raw = dict(value)
        raw.setdefault("execution_generation", 1)
        generation = raw.get("execution_generation")
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
        ):
            raise HostRunLeaseError("HOST_RUN_LEASE_GENERATION_INVALID")
        action_message_id = raw.get("action_message_id")
        host_session_id = raw.get("host_session_id")
        if not isinstance(action_message_id, str) or not isinstance(
            host_session_id, str
        ):
            raise HostRunLeaseError("HOST_RUN_LEASE_INVALID")
        raw["fencing_token"] = _resolve_fencing_token(
            action_message_id=action_message_id,
            host_session_id=host_session_id,
            generation=generation,
            supplied=raw.get("fencing_token"),
            supplied_present="fencing_token" in raw,
        )
        try:
            lease = cls(**raw)
        except TypeError as exc:
            raise HostRunLeaseError("HOST_RUN_LEASE_INVALID") from exc
        if (
            lease.schema_version != "1.0"
            or not all(
                isinstance(item, str) and item
                for item in (
                    lease.thread_id,
                    lease.action_message_id,
                    lease.platform,
                    lease.host_session_id,
                    lease.build_id,
                    lease.disposition,
                )
            )
            or not isinstance(lease.continuation_required, bool)
            or not isinstance(lease.yield_allowed, bool)
            or not isinstance(lease.execution_generation, int)
            or isinstance(lease.execution_generation, bool)
            or lease.execution_generation < 1
            or not isinstance(lease.fencing_token, str)
            or len(lease.fencing_token) != 64
        ):
            raise HostRunLeaseError("HOST_RUN_LEASE_INVALID")
        return lease

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HostRunLeaseStore:
    """在项目状态目录中原子保存当前宿主运行租约。"""

    def __init__(self, project_root: Path) -> None:
        self.path = project_root.resolve() / ".ae-state" / "host-runtime" / "active-lease.json"

    def save(self, lease: HostRunLease) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            lease.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".active-lease-",
            suffix=".json",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def load(self) -> HostRunLease | None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise HostRunLeaseError("HOST_RUN_LEASE_CORRUPT") from exc
        if not isinstance(raw, Mapping):
            raise HostRunLeaseError("HOST_RUN_LEASE_INVALID")
        return HostRunLease.from_dict(raw)

    def clear(self) -> None:
        """关闭当前宿主执行义务，避免异常退出留下假活跃 lease。"""

        try:
            self.path.unlink()
        except FileNotFoundError:
            return


def evaluate_stop(
    lease: HostRunLease | None,
    *,
    host_session_id: str | None,
) -> StopGuardDecision:
    """只阻止同一宿主会话放弃明确要求连续执行的 Action。"""

    if lease is None or not host_session_id or lease.host_session_id != host_session_id:
        return StopGuardDecision.ALLOW
    if (
        lease.disposition == "CONTINUE"
        and lease.continuation_required
        and not lease.yield_allowed
    ):
        return StopGuardDecision.BLOCK
    return StopGuardDecision.ALLOW


def host_session_id_from_environ(
    platform: HostPlatform | Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    """按已识别宿主选择会话 ID，避免嵌套 CLI 继承外层身份。"""

    # Preserve the former ``host_session_id_from_environ(environ)`` call form.
    if isinstance(platform, Mapping):
        environ = platform
        platform = None
    env = os.environ if environ is None else environ
    names: tuple[str, ...]
    if platform is HostPlatform.CLAUDE_CODE:
        names = (
            "CLAUDE_CODE_SESSION_ID",
            "CLAUDE_SESSION_ID",
        )
    elif platform is HostPlatform.CODEX:
        names = ("CODEX_THREAD_ID",)
    else:
        names = (
            "CODEX_THREAD_ID",
            "CLAUDE_CODE_SESSION_ID",
            "CLAUDE_SESSION_ID",
        )
    for name in names:
        value = env.get(name)
        if value:
            return value
    return None


__all__ = [
    "HostRunLease",
    "HostRunLeaseError",
    "HostRunLeaseStore",
    "StopGuardDecision",
    "evaluate_stop",
    "fencing_token_for",
    "host_session_id_from_environ",
]
