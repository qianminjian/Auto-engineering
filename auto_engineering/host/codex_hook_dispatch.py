"""Codex Hook 主入口；事件解析和 Worker 证据采集保持在各自模块。"""

from __future__ import annotations

import json
import sys
from typing import TextIO

from auto_engineering.host import HostPlatform


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    """验证 Hook；同一会话仍有 CONTINUE Action 时拒绝误停。"""

    from auto_engineering.host import codex_hooks

    response_written = False
    try:
        payload = json.load(stdin)
        if not isinstance(payload, dict):
            raise ValueError("Hook 输入必须是 JSON object")
        event = codex_hooks.normalize_codex_event(payload)
        if event.event == "post_tool":
            message = codex_hooks._capture_codex_post_tool(payload)
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
                message = guard_system_message(exc.code)
                json.dump(
                    {
                        "systemMessage": message,
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": message,
                        },
                    },
                    stdout,
                    ensure_ascii=False,
                )
                stdout.write("\n")
                response_written = True
                return 0
        if event.event == "pre_tool" and not response_written:
            json.dump({"systemMessage": "Auto-Engineering Hook 已安全跳过"}, stdout, ensure_ascii=False)
            stdout.write("\n")
            response_written = True
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
                        "continue": False,
                        "stopReason": "AE_HOST_RUN_LEASE_CORRUPT",
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
                        "continue": False,
                        "stopReason": "AE_CONTINUATION_REQUIRED",
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
