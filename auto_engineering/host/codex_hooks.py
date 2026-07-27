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
    """验证并归一化一个 stdin 事件；合法事件零输出继续执行。"""
    try:
        payload = json.load(stdin)
        if not isinstance(payload, dict):
            raise ValueError("Hook 输入必须是 JSON object")
        normalize_codex_event(payload)
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
