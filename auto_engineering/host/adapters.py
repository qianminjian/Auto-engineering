"""Claude Code 与 Codex 的宿主边界适配器。"""

from __future__ import annotations

import hashlib
import json
import os
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


def _native_worker_launch_prompt(
    *,
    project_root: str,
    prompt_ref: str,
    prompt_sha256: str,
    required_isolation_evidence: str,
) -> str:
    """生成不含 Worker 正文的有界原生启动合同。"""

    contract = {
        "schema_version": "1.0",
        "project_root": project_root,
        "prompt_ref": prompt_ref,
        "prompt_sha256": prompt_sha256,
        "may_drive_loop": False,
        "may_spawn_workers": False,
        "required_isolation_evidence": required_isolation_evidence,
    }
    return (
        "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\n"
        "切换到 project_root；只读取 prompt_ref 指定文件，先校验 SHA-256，"
        "匹配后严格执行正文。不得驱动 Auto-Engineering Loop，不得创建子代理。"
        "最终只返回输出契约要求的结构化字段和短摘要；不得返回完整 diff、日志或报告正文，"
        "大型正文写入任务指定 Artifact。\n"
        + json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


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
        raw_project_root = action.get("project_root")
        project_root = (
            raw_project_root
            if isinstance(raw_project_root, str) and raw_project_root
            else None
        )
        work_files = {
            "outcomes": f"{work_root}/outcomes.json",
            "coordinator_result": f"{work_root}/coordinator-result.json",
            "result": f"{work_root}/result.json",
        }
        host_execution: dict[str, object] = {
            "schema_version": "1.0",
            "platform": self.platform.value,
            "action_message_id": message_id,
            "work_files": work_files,
        }
        if project_root is not None:
            finalize_argv = [
                "__AE_BUNDLED_RUNNER__", "dev-loop", "--finalize-result",
                (
                    work_files["outcomes"]
                    if isinstance(action.get("spawn"), Mapping)
                    else work_files["coordinator_result"]
                ),
            ]
            if isinstance(action.get("spawn"), Mapping):
                finalize_argv.extend([
                    "--coordinator-result", work_files["coordinator_result"],
                ])
            finalize_argv.extend([
                "--output-result", work_files["result"],
                "--project-root", project_root,
            ])
            host_execution["operations"] = {
                "finalize": {"argv": finalize_argv},
                "validate": {"argv": [
                    "__AE_BUNDLED_RUNNER__", "dev-loop", "--validate-result",
                    work_files["result"], "--project-root", project_root,
                ]},
                "submit": {"argv": [
                    "__AE_BUNDLED_RUNNER__", "dev-loop", "--tick", "--result",
                    work_files["result"], "--project-root", project_root,
                ]},
            }
        spawn = action.get("spawn")
        rejection = action.get("result_rejection")
        is_result_repair = (
            isinstance(rejection, Mapping)
            and rejection.get("repair_required") is True
        )
        if (
            not is_result_repair
            and isinstance(spawn, Mapping)
            and isinstance(spawn.get("invocations"), list)
        ):
            from auto_engineering.host.spawn_contract import SpawnPlan
            from auto_engineering.host.worker_attestation import attestation_template

            if project_root is None:
                raise ValueError("HOST_ACTION_PROJECT_ROOT_MISSING")

            plan = SpawnPlan.from_action(action)
            stage = str(action.get("stage") or "")
            expected_isolation = {
                HostPlatform.CODEX: "fork_turns=none",
                HostPlatform.CLAUDE_CODE: "fresh_context",
            }[self.platform]
            host_execution["workers"] = [
                {
                    "worker_id": invocation.worker_id,
                    "native_worker_handle": None,
                    "prompt_ref": invocation.prompt_ref,
                    "prompt_sha256": invocation.prompt_sha256,
                    "native_launch_prompt": _native_worker_launch_prompt(
                        project_root=project_root,
                        prompt_ref=invocation.prompt_ref,
                        prompt_sha256=invocation.prompt_sha256,
                        required_isolation_evidence=expected_isolation,
                    ),
                    "expected_isolation_evidence": expected_isolation,
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
        elif (
            is_result_repair
            and isinstance(spawn, Mapping)
            and isinstance(spawn.get("invocations"), list)
        ):
            # Core 已拒绝同一 Action 的候选 Result；修复上下文只重做
            # Coordinator，Worker 事实由 outcome journal 恢复，不再暴露 spawn。
            semantic_context_refs = [
                str(item["prompt_ref"])
                for item in spawn["invocations"]
                if isinstance(item, Mapping)
                and isinstance(item.get("prompt_ref"), str)
            ]
            host_execution["recovery"] = {
                "schema_version": "1.0",
                "status": "result_repair_worker_reuse",
                "spawn_permitted": False,
                "required_operation": "repair_coordinator_then_finalize",
                "result_ref": work_files["result"],
                "outcomes_ref": work_files["outcomes"],
                "coordinator_result_ref": work_files["coordinator_result"],
                "semantic_context_refs": semantic_context_refs,
            }
            mapped_payload["instruction"] = (
                "当前是 Result repair：只修复 Coordinator 业务产物；"
                "不得重新启动 Worker，必须复用 outcomes_ref 中的权威 Worker outcomes，"
                "完成后再调用 Finalizer、validate 和 submit。"
            )
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
    """解析已安装插件自带的 ``bin/ae-run``，不回退到开发环境。"""
    root = plugin_root.resolve()
    bundled_cli = root / "bin" / "ae-run"
    if bundled_cli.is_file() and os.access(bundled_cli, os.X_OK):
        return (str(bundled_cli),)

    raise FileNotFoundError(
        "AE_CLI_NOT_FOUND: 未找到已安装插件的 bin/ae-run",
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
