"""宿主进程退出后的事实桥接，不负责发起或推进任何 Loop 工作。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from auto_engineering.host.runtime_driver import HostRunLeaseStore
from auto_engineering.host.stop_report import handle_claude_session_end


def _last_json_object(path: Path) -> dict[str, object] | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _termination_reason_from_value(value: object) -> str | None:
    """从宿主流中识别有限的结构化终止原因，不信任自由文本。"""

    if not isinstance(value, Mapping):
        return None
    for key in ("terminal_reason", "stop_reason"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    error_code = value.get("error_code")
    if isinstance(error_code, str) and error_code:
        return error_code
    item = value.get("item")
    if isinstance(item, Mapping):
        nested = _termination_reason_from_value(item)
        if nested is not None:
            return nested
    text = value.get("text")
    if isinstance(text, str) and text.startswith("{"):
        try:
            nested = json.loads(text)
        except json.JSONDecodeError:
            return None
        return _termination_reason_from_value(nested)
    return None


def _stream_termination_reason(path: Path) -> str | None:
    """按宿主输出的时间逆序读取最近终止信号。"""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    for line in reversed(lines):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        reason = _termination_reason_from_value(value)
        if reason is not None:
            return reason
    return None


def _termination_reason(result: Mapping[str, object] | None) -> str:
    if result is not None:
        reason = _termination_reason_from_value(result)
        if reason is not None:
            return reason
    return "process_exit"


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--host-output", type=Path, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument(
        "--reason-code",
        default="HOST_RUNTIME_PROTOCOL_ERROR",
        help="有限的宿主停止原因码；默认使用通用协议错误",
    )
    args = parser.parse_args(argv)
    if args.exit_code < 0:
        parser.error("--exit-code 不能为负数")

    lease = HostRunLeaseStore(args.project_root).load()
    result = _last_json_object(args.host_output)
    stream_reason = _stream_termination_reason(args.host_output)
    if lease is not None and result is not None:
        result_session = result.get("session_id")
        if (
            isinstance(result_session, str)
            and result_session
            and result_session != lease.host_session_id
        ):
            print("HOST_SESSION_ID_MISMATCH", file=sys.stderr)
            return 2
    if lease is None:
        json.dump(
            {"systemMessage": "Auto-Engineering 未发现活动宿主租约"},
            stdout,
            ensure_ascii=False,
        )
        stdout.write("\n")
        return 0

    response = handle_claude_session_end(args.project_root, {
        "hook_event_name": "StopFailure" if args.exit_code else "SessionEnd",
        "cwd": str(args.project_root),
        "session_id": lease.host_session_id,
        "reason": stream_reason or _termination_reason(result),
    }, reason_code=args.reason_code)
    json.dump(response, stdout, ensure_ascii=False)
    stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
