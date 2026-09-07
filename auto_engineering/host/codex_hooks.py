"""Codex Hook stdin 事件到平台无关 HostEvent 的适配。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import TextIO

from auto_engineering.host import HostEvent, HostPlatform

_EVENT_NAMES = {
    "SessionStart": "session_start",
    "PreToolUse": "pre_tool",
    "PostToolUse": "post_tool",
    "Stop": "stop",
}
_CODEX_SPAWN_TOOLS = {
    "collaboration.spawn_agent",
    "multi_agent_v1__spawn_agent",
}
_CODEX_WAIT_TOOLS = {
    "collaboration.wait_agent",
    "multi_agent_v1__wait_agent",
}
_RAW_RESPONSE_FIELDS = (
    "tool_response_raw",
    "tool_output_raw",
    "tool_result_raw",
    "tool_response",
    "tool_output",
    "tool_result",
)


def normalize_codex_event(raw: Mapping[str, object]) -> HostEvent:
    """把 Codex Hook wire event 归一化，不把 wire 字段泄漏到 Core。"""
    event_name = raw.get("hook_event_name")
    if not isinstance(event_name, str) or event_name not in _EVENT_NAMES:
        raise ValueError("缺少或不支持 hook_event_name")

    cwd = raw.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError("缺少 cwd")

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
        platform=HostPlatform.CODEX,
        tool=normalized_tool,
        file_path=file_path,
        project_root=Path(cwd).resolve(),
        raw=dict(raw),
    )


def _raw_tool_response(payload: Mapping[str, object]) -> bytes | None:
    """只接收宿主提供的原始文本，禁止把解析后的对象重新序列化。"""

    for field in _RAW_RESPONSE_FIELDS:
        value = payload.get(field)
        if isinstance(value, str):
            return value.encode("utf-8")
        if isinstance(value, bytes):
            return value
    return None


def _json_mapping(raw: bytes) -> Mapping[str, object] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, Mapping) else None


def _resolve_path(project_root: Path, relative_or_absolute: object) -> Path | None:
    if not isinstance(relative_or_absolute, str) or not relative_or_absolute:
        return None
    try:
        target = Path(relative_or_absolute)
        resolved = (target if target.is_absolute() else project_root / target).resolve()
    except (OSError, RuntimeError):
        return None
    if project_root.resolve() not in resolved.parents or resolved.name == "":
        return None
    return resolved


def _write_native_bytes(project_root: Path, native_path: object, raw: bytes) -> bool:
    target = _resolve_path(project_root, native_path)
    if target is None:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        os.replace(temporary, target)
    except OSError:
        with suppress(OSError):
            os.unlink(temporary)
        return False
    return True


def _worker_for_prompt(
    workers: list[Mapping[str, object]], tool_input: Mapping[str, object],
) -> Mapping[str, object] | None:
    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str):
        prompt = tool_input.get("message")
    if not isinstance(prompt, str):
        return None
    return next(
        (
            worker for worker in workers
            if worker.get("native_launch_prompt") == prompt
        ),
        None,
    )


def _target_ids(tool_input: Mapping[str, object]) -> list[str]:
    targets = tool_input.get("targets")
    if isinstance(targets, list):
        return [item for item in targets if isinstance(item, str) and item]
    for field in ("target", "agent_id", "thread_id"):
        value = tool_input.get(field)
        if isinstance(value, str) and value:
            return [value]
    return []


def _native_ids(raw: bytes) -> set[str]:
    value = _json_mapping(raw)
    if value is None:
        return set()
    ids: set[str] = set()
    for field in ("receiver_thread_ids", "agent_ids", "thread_ids"):
        candidates = value.get(field)
        if isinstance(candidates, list):
            ids.update(item for item in candidates if isinstance(item, str))
    states = value.get("agents_states")
    if isinstance(states, Mapping):
        ids.update(item for item in states if isinstance(item, str))
    status = value.get("status")
    if isinstance(status, Mapping):
        ids.update(item for item in status if isinstance(item, str))
    return ids


def _worker_for_target(
    workers: list[Mapping[str, object]], project_root: Path, target_id: str,
) -> Mapping[str, object] | None:
    for worker in workers:
        native_path = _resolve_path(project_root, worker.get("native_result_path"))
        if native_path is None or not native_path.is_file():
            continue
        try:
            raw = native_path.read_bytes()
        except OSError:
            continue
        if target_id in _native_ids(raw):
            return worker
        handle = worker.get("native_worker_handle")
        if handle == target_id:
            return worker
    return None


def _completed_body(raw: bytes, target_id: str) -> str | None:
    """提取当前 target 的完成正文，不返回 wait 外层包装。"""

    value = _json_mapping(raw)
    if value is None:
        return None
    for field in ("agents_states", "status"):
        states = value.get(field)
        if not isinstance(states, Mapping):
            continue
        state = states.get(target_id)
        if isinstance(state, Mapping):
            completed = state.get("completed")
            if isinstance(completed, str) and completed:
                return completed
            # Codex 的真实 collaboration.wait_agent 回包把 Worker 完成正文
            # 放在 agents_states[target].message 中；message 本身是宿主返回的
            # 原始 JSON 字符串。只接受可验证的 completed Worker envelope，
            # 返回原字符串，禁止重新序列化或从字段重建证据。
            message = state.get("message")
            if (
                isinstance(message, str)
                and message.strip()
                and message.strip().lower() != "completed"
            ):
                message_mapping = _json_mapping(message.encode("utf-8"))
                if (
                    message_mapping is not None
                    and message_mapping.get("status") in {
                        "completed", "failed", "cancelled", "timed_out",
                    }
                ):
                    return message
        if isinstance(state, str) and state:
            return state
    return None


def _capture_codex_post_tool(payload: Mapping[str, object]) -> str | None:
    """自动固化 Codex spawn/wait 的原始 Worker 证据。"""

    tool_name = payload.get("tool_name")
    if tool_name not in _CODEX_SPAWN_TOOLS | _CODEX_WAIT_TOOLS:
        return None
    cwd = payload.get("cwd")
    tool_input = payload.get("tool_input")
    if not isinstance(cwd, str) or not isinstance(tool_input, Mapping):
        return "Auto-Engineering 原生 Worker 证据未能固化：Hook 输入不完整"
    raw = _raw_tool_response(payload)
    if raw is None:
        return "Auto-Engineering 原生 Worker 证据未能固化：宿主未提供原始返回"
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        active_native_workers,
    )

    project_root = Path(cwd).resolve()
    try:
        workers = active_native_workers(
            project_root=project_root, platform=HostPlatform.CODEX,
        )
    except (NativeLaunchGuardError, OSError, TypeError, ValueError):
        return "Auto-Engineering 原生 Worker 证据未能固化：当前 Action 不可用"
    if not workers:
        return "Auto-Engineering Hook 已安全跳过"

    if tool_name in _CODEX_SPAWN_TOOLS:
        worker = _worker_for_prompt(workers, tool_input)
        if worker is None or not _write_native_bytes(
            project_root, worker.get("native_result_path"), raw,
        ):
            return "Auto-Engineering 原生 Worker 证据未能固化：spawn 无法绑定 Worker"
        return "Auto-Engineering 原生 Worker 启动事实已固化"

    targets = _target_ids(tool_input)
    if len(targets) != 1:
        return "Auto-Engineering 原生 Worker 证据未能固化：wait target 不唯一"
    target_id = targets[0]
    worker = _worker_for_target(workers, project_root, target_id)
    completed = _completed_body(raw, target_id)
    if completed is None:
        return "Auto-Engineering Hook 已记录 Worker 仍在运行"
    if worker is None or not _write_native_bytes(
        project_root, worker.get("native_result_path"), completed.encode("utf-8"),
    ):
        return "Auto-Engineering 原生 Worker 证据未能固化：wait 无法绑定 Worker"
    return "Auto-Engineering 原生 Worker 完成证据已固化"


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    """验证 Hook；同一会话仍有 CONTINUE Action 时拒绝误停。"""
    response_written = False
    try:
        payload = json.load(stdin)
        if not isinstance(payload, dict):
            raise ValueError("Hook 输入必须是 JSON object")
        event = normalize_codex_event(payload)
        if event.event == "post_tool":
            message = _capture_codex_post_tool(payload)
            if message is not None:
                json.dump({"systemMessage": message}, stdout, ensure_ascii=False)
                stdout.write("\n")
                response_written = True
        if event.event == "pre_tool":
            from auto_engineering.host.native_launch_guard import (
                NativeLaunchGuardError,
                guard_active_native_tool_call,
                guard_system_message,
            )

            try:
                guard_active_native_tool_call(
                    payload,
                    project_root=event.project_root,
                    platform=HostPlatform.CODEX,
                )
            except NativeLaunchGuardError as exc:
                json.dump(
                    {
                        "decision": "block",
                        "reason_code": exc.code,
                        "systemMessage": guard_system_message(exc.code),
                    },
                    stdout,
                    ensure_ascii=False,
                )
                stdout.write("\n")
                response_written = True
                return 0
        if event.event == "stop":
            from auto_engineering.host.runtime_driver import (
                HostRunLeaseError,
                HostRunLeaseStore,
                StopGuardDecision,
                evaluate_stop,
            )

            session_id = payload.get("session_id")
            normalized_session = session_id if isinstance(session_id, str) else None
            try:
                lease = HostRunLeaseStore(event.project_root).load()
            except HostRunLeaseError:
                json.dump(
                    {
                        "decision": "block",
                        "reason_code": "AE_HOST_RUN_LEASE_CORRUPT",
                        "systemMessage": "Auto-Engineering 运行租约损坏，已阻止不安全停止",
                    },
                    stdout,
                    ensure_ascii=False,
                )
                stdout.write("\n")
                response_written = True
                return 0
            if evaluate_stop(
                lease,
                host_session_id=normalized_session,
            ) is StopGuardDecision.BLOCK:
                assert lease is not None
                json.dump(
                    {
                        "decision": "block",
                        "reason_code": "AE_CONTINUATION_REQUIRED",
                        "action_message_id": lease.action_message_id,
                        "systemMessage": "Auto-Engineering 仍有必须继续执行的 Action",
                    },
                    stdout,
                    ensure_ascii=False,
                )
                stdout.write("\n")
                response_written = True
        if not response_written:
            json.dump(
                {"systemMessage": "Auto-Engineering Hook 已安全跳过"},
                stdout,
                ensure_ascii=False,
            )
            stdout.write("\n")
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        json.dump(
            {"systemMessage": "Auto-Engineering Hook 输入无效，已安全跳过"},
            stdout,
            ensure_ascii=False,
        )
        stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
