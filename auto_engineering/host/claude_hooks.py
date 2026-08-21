"""Claude Code Stop Hook 到共享 Host Runtime 门禁的适配。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TextIO

from auto_engineering.host.runtime_driver import (
    HostRunLeaseError,
    HostRunLeaseStore,
    StopGuardDecision,
    evaluate_stop,
)


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    try:
        payload = json.load(stdin)
        if not isinstance(payload, dict):
            raise ValueError("Hook 输入必须是 JSON object")
        event_name = payload.get("hook_event_name")
        cwd = payload.get("cwd")
        if event_name != "Stop" or not isinstance(cwd, str) or not cwd:
            return 0
        session_id = payload.get("session_id")
        normalized_session = session_id if isinstance(session_id, str) else None
        try:
            lease = HostRunLeaseStore(Path(cwd)).load()
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
