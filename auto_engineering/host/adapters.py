"""Claude Code 与 Codex 的宿主边界适配器。"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

from auto_engineering.host import (
    HostCapabilities,
    HostEvent,
    HostExecutionReport,
    HostPlatform,
    MappedHostAction,
    UsageSource,
    capabilities_for,
    usage_source_for,
)
from auto_engineering.host.codex_hooks import normalize_codex_event
from auto_engineering.host.profile import HostProfile

_EVENT_NAMES = {
    "SessionStart": "session_start",
    "PreToolUse": "pre_tool",
    "PostToolUse": "post_tool",
    "Stop": "stop",
}

_CODEX_NATIVE_WORKER_TOOL_FAMILIES = [
    {
        "spawn": "collaboration.spawn_agent",
        "wait": "collaboration.wait_agent",
        "close": "collaboration.interrupt_agent",
    },
    {
        "spawn": "multi_agent_v1__spawn_agent",
        "wait": "multi_agent_v1__wait_agent",
        "close": "multi_agent_v1__close_agent",
    },
]


class _Adapter2Mixin:
    platform: ClassVar[HostPlatform]
    capabilities: ClassVar[HostCapabilities]

    def probe(
        self,
        *,
        detected: HostCapabilities,
        authorized: HostCapabilities,
    ) -> HostProfile:
        return HostProfile(self.platform, self.capabilities, detected, authorized)

    def profile(
        self,
        *,
        detected: HostCapabilities,
        authorized: HostCapabilities,
    ) -> HostProfile:
        return self.probe(detected=detected, authorized=authorized)

    def map_action(
        self,
        action: Mapping[str, object],
        *,
        profile: HostProfile,
    ) -> MappedHostAction:
        if profile.platform is not self.platform:
            raise ValueError("HOST_PROFILE_PLATFORM_MISMATCH")
        message_id = action.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise ValueError("HOST_ACTION_INVALID: 缺少 message_id")
        requirements = action.get("capability_requirements", {})
        if not isinstance(requirements, Mapping):
            raise ValueError("HOST_ACTION_INVALID: 能力需求必须为 object")
        effective = profile.effective
        mapped_payload = dict(action)
        action_key = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:24]
        work_root = f".ae-state/host-runtime/work/{action_key}"
        host_execution: dict[str, object] = {
            "schema_version": "1.0",
            "platform": self.platform.value,
            "action_message_id": message_id,
            "work_files": {
                "outcomes": f"{work_root}/outcomes.json",
                "coordinator_result": f"{work_root}/coordinator-result.json",
                "result": f"{work_root}/result.json",
            },
        }
        spawn = action.get("spawn")
        if isinstance(spawn, Mapping) and isinstance(spawn.get("invocations"), list):
            from auto_engineering.host.spawn_contract import SpawnPlan
            from auto_engineering.host.worker_attestation import attestation_template

            plan = SpawnPlan.from_action(action)
            stage = str(action.get("stage") or "")
            host_execution["workers"] = [
                {
                    "worker_id": invocation.worker_id,
                    "native_worker_handle": None,
                    "prompt_ref": invocation.prompt_ref,
                    "receipt_path": invocation.receipt_path,
                    "receipt": {
                        "status": "pending",
                        "stage": stage,
                        "worker": invocation.worker_id,
                        "requested_effort": invocation.requested_effort,
                        "actual_model": "unknown",
                    },
                    "attestation": attestation_template(
                        platform=self.platform,
                        action_message_id=message_id,
                        invocation=invocation,
                    ),
                }
                for invocation in plan.invocations
            ]
            if self.platform is HostPlatform.CODEX:
                host_execution["native_worker_tools"] = {
                    "selection": "first_complete_exposed_family",
                    "families": [
                        dict(family)
                        for family in _CODEX_NATIVE_WORKER_TOOL_FAMILIES
                    ],
                }
        mapped_payload["host_execution"] = host_execution
        if action.get("action") == "session_rollover":
            if not effective.session_handoff:
                raise ValueError("HOST_SESSION_HANDOFF_UNAVAILABLE")
            claim_token = action.get("claim_token")
            capsule = action.get("capsule")
            if not isinstance(claim_token, str) or not isinstance(capsule, Mapping):
                raise ValueError("HOST_ACTION_INVALID: rollover 契约不完整")
            mapped_payload["host_control"] = {
                "operation": "create_fresh_session",
                "load_capsule": dict(capsule),
                "submit_result": {
                    "stage": "session_claimed",
                    "claim_token": claim_token,
                },
                "fail_closed": True,
            }
        for name, required in requirements.items():
            if not required:
                continue
            capability_name = (
                "git_mutation" if name == "git_operations" else name
            )
            available = getattr(effective, capability_name, None)
            if available is not True:
                raise ValueError(
                    f"HOST_CAPABILITY_UNAVAILABLE: {name}"
                )
        return MappedHostAction(
            platform=self.platform,
            message_id=message_id,
            payload=mapped_payload,
        )

    def report_execution(
        self,
        raw: Mapping[str, object],
    ) -> HostExecutionReport:
        message_id = raw.get("message_id")
        status = raw.get("status")
        result = raw.get("result")
        if (
            not isinstance(message_id, str)
            or not message_id
            or status not in {"completed", "failed", "cancelled"}
            or not isinstance(result, Mapping)
        ):
            raise ValueError("HOST_EXECUTION_REPORT_INVALID")
        return HostExecutionReport(
            platform=self.platform,
            message_id=message_id,
            status=status,
            result=dict(result),
        )


def _resolve_cli(plugin_root: Path) -> tuple[str, ...]:
    """按共享 ae-run 的顺序解析 CLI，不启动任何进程。"""
    root = plugin_root.resolve()
    local_cli = root / ".venv" / "bin" / "ae"
    if local_cli.is_file() and os.access(local_cli, os.X_OK):
        return (str(local_cli),)

    uv = shutil.which("uv")
    if uv:
        return (uv, "run", "--project", str(root), "ae")

    ae = shutil.which("ae")
    if ae:
        return (ae,)

    raise FileNotFoundError(
        "AE_CLI_NOT_FOUND: 未找到项目虚拟环境、uv 或全局 ae 命令",
    )


def _normalize_claude_event(raw: Mapping[str, object]) -> HostEvent | None:
    event_name = raw.get("hook_event_name")
    cwd = raw.get("cwd")
    if (
        not isinstance(event_name, str)
        or event_name not in _EVENT_NAMES
        or not isinstance(cwd, str)
        or not cwd
    ):
        return None

    tool = raw.get("tool_name")
    normalized_tool = tool if isinstance(tool, str) and tool else None
    file_path: str | None = None
    tool_input = raw.get("tool_input")
    if isinstance(tool_input, Mapping):
        for key in ("file_path", "filepath", "path"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                file_path = value
                break

    return HostEvent(
        event=_EVENT_NAMES[event_name],
        platform=HostPlatform.CLAUDE_CODE,
        tool=normalized_tool,
        file_path=file_path,
        project_root=Path(cwd).resolve(),
        raw=dict(raw),
    )


class CodexHostAdapter(_Adapter2Mixin):
    """Codex 原生 Hook 与能力适配。"""

    platform: ClassVar[HostPlatform] = HostPlatform.CODEX
    capabilities: ClassVar[HostCapabilities] = capabilities_for(HostPlatform.CODEX)

    def normalize_event(self, raw: Mapping[str, object]) -> HostEvent | None:
        try:
            return normalize_codex_event(raw)
        except ValueError:
            return None

    def resolve_cli(self, plugin_root: Path) -> tuple[str, ...]:
        return _resolve_cli(plugin_root)

    def usage_source(self, project_root: Path) -> UsageSource | None:
        del project_root
        return usage_source_for(self.platform)


class ClaudeCodeHostAdapter(_Adapter2Mixin):
    """Claude Code 原生 Hook、CLI 与 transcript usage 适配。"""

    platform: ClassVar[HostPlatform] = HostPlatform.CLAUDE_CODE
    capabilities: ClassVar[HostCapabilities] = capabilities_for(
        HostPlatform.CLAUDE_CODE,
    )

    def normalize_event(self, raw: Mapping[str, object]) -> HostEvent | None:
        return _normalize_claude_event(raw)

    def resolve_cli(self, plugin_root: Path) -> tuple[str, ...]:
        return _resolve_cli(plugin_root)

    def usage_source(self, project_root: Path) -> UsageSource | None:
        del project_root
        return usage_source_for(self.platform)


_ADAPTERS: dict[
    HostPlatform,
    ClaudeCodeHostAdapter | CodexHostAdapter,
] = {
    HostPlatform.CLAUDE_CODE: ClaudeCodeHostAdapter(),
    HostPlatform.CODEX: CodexHostAdapter(),
}


def adapter_for(platform: HostPlatform) -> ClaudeCodeHostAdapter | CodexHostAdapter:
    """返回已实现的宿主适配器，不对未知平台做隐式降级。"""
    try:
        return _ADAPTERS[platform]
    except KeyError as error:
        raise ValueError(
            f"HOST_ADAPTER_UNAVAILABLE: {platform.value}",
        ) from error


__all__ = [
    "ClaudeCodeHostAdapter",
    "CodexHostAdapter",
    "adapter_for",
]
