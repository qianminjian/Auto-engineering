"""原生 Worker Guard 的宿主 CLI Wire 适配。"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path

from auto_engineering.host import HostPlatform, native_launch_guard


def _codex_block(message: str) -> dict[str, object]:
    return {
        "systemMessage": message,
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        },
    }


def main() -> int:
    payload = json.load(sys.stdin)
    if not isinstance(payload, Mapping):
        return 0
    raw_platform = payload.get("platform")
    platform = HostPlatform(raw_platform) if isinstance(raw_platform, str) else None
    cwd = payload.get("cwd")
    if platform is None or not isinstance(cwd, str) or not cwd:
        return 0
    try:
        native_launch_guard.guard_active_native_tool_call(
            payload,
            project_root=Path(cwd).resolve(),
            platform=platform,
        )
    except native_launch_guard.NativeLaunchGuardError as exc:
        message = native_launch_guard.guard_system_message(exc.code)
        if platform is HostPlatform.CODEX:
            print(json.dumps(_codex_block(message), ensure_ascii=False))
        else:
            print(json.dumps({
                "decision": "block",
                "reason_code": exc.code,
                "reason": message,
                "systemMessage": message,
                "permissionDecision": "deny",
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": message,
                },
            }, ensure_ascii=False))
        return 0
    if platform is HostPlatform.CODEX:
        print(json.dumps(
            {"systemMessage": "Auto-Engineering Hook 已安全跳过"},
            ensure_ascii=False,
        ))
    else:
        print(json.dumps({
            "decision": "approve",
            "permissionDecision": "allow",
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            },
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
