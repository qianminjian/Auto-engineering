"""Claude Code 与 Codex 的宿主边界适配器。"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

from auto_engineering.host import (
    HostCapabilities,
    HostEvent,
    HostPlatform,
    UsageSource,
    capabilities_for,
    usage_source_for,
)
from auto_engineering.host.codex_hooks import normalize_codex_event

_EVENT_NAMES = {
    "SessionStart": "session_start",
    "PreToolUse": "pre_tool",
    "PostToolUse": "post_tool",
    "Stop": "stop",
}


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


class CodexHostAdapter:
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


class ClaudeCodeHostAdapter:
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
