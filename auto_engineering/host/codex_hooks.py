"""Codex Hook stdin 事件到平台无关 HostEvent 的适配。"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

from auto_engineering.host import HostEvent, HostPlatform

_EVENT_NAMES = {
    "SessionStart": "session_start",
    "PreToolUse": "pre_tool",
    "PostToolUse": "post_tool",
    "Stop": "stop",
}


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


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    """验证 Hook；同一会话仍有 CONTINUE Action 时拒绝误停。"""
    try:
        payload = json.load(stdin)
        if not isinstance(payload, dict):
            raise ValueError("Hook 输入必须是 JSON object")
        event = normalize_codex_event(payload)
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
