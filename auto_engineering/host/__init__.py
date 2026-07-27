"""宿主 Agent 平台检测与能力契约。

本模块只描述宿主边界，不依赖循环引擎、Plugin manifest 或宿主 SDK。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class HostPlatform(StrEnum):
    """Auto-Engineering 可识别的宿主平台。"""

    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    CODEBUDDY = "codebuddy"
    UNKNOWN = "unknown"

    @property
    def display_name(self) -> str:
        return {
            HostPlatform.CLAUDE_CODE: "Claude Code",
            HostPlatform.CODEX: "Codex",
            HostPlatform.CODEBUDDY: "CodeBuddy",
            HostPlatform.UNKNOWN: "Unknown",
        }[self]


class GitOperation(StrEnum):
    """需要分别授权的 Git 外部副作用。"""

    COMMIT = "commit"
    PUSH = "push"
    CREATE_PR = "create_pr"


@dataclass(frozen=True)
class GitAuthorization:
    """Git 能力与当前用户授权的交集；默认拒绝所有写操作。"""

    capability: bool
    authorized: frozenset[GitOperation] = frozenset()

    def allows(self, operation: GitOperation) -> bool:
        """仅当宿主具备能力且用户明确授权该操作时允许。"""
        return self.capability and operation in self.authorized


@dataclass(frozen=True)
class HostCapabilities:
    """宿主提供的能力；能力存在不等于用户已经授权使用。"""

    skills: bool = False
    commands: bool = False
    hooks: frozenset[str] = frozenset()
    subagents: bool = False
    parallel_subagents: bool = False
    interactive_questions: bool = False
    transcript_usage: bool = False
    git_mutation: bool = False


@dataclass(frozen=True)
class HostDetection:
    """一次宿主探测结果及其证据信号。"""

    platform: HostPlatform
    signal: str

    @property
    def capabilities(self) -> HostCapabilities:
        return capabilities_for(self.platform)


class HostAdapter(Protocol):
    """所有宿主适配器必须暴露的最小静态契约。"""

    platform: HostPlatform
    capabilities: HostCapabilities


_COMMON_HOOKS = frozenset({"session_start", "pre_tool", "post_tool", "stop"})

_CAPABILITIES = {
    HostPlatform.CLAUDE_CODE: HostCapabilities(
        skills=True,
        commands=True,
        hooks=_COMMON_HOOKS,
        subagents=True,
        parallel_subagents=True,
        interactive_questions=True,
        transcript_usage=True,
        git_mutation=True,
    ),
    HostPlatform.CODEX: HostCapabilities(
        skills=True,
        hooks=_COMMON_HOOKS,
        subagents=True,
        parallel_subagents=True,
        git_mutation=True,
    ),
    HostPlatform.CODEBUDDY: HostCapabilities(
        skills=True,
        commands=True,
        hooks=_COMMON_HOOKS,
        subagents=True,
        parallel_subagents=True,
        interactive_questions=True,
        git_mutation=True,
    ),
    HostPlatform.UNKNOWN: HostCapabilities(),
}


def capabilities_for(platform: HostPlatform) -> HostCapabilities:
    """返回平台的显式能力矩阵。"""
    return _CAPABILITIES[platform]


def detect_host(environ: Mapping[str, str] | None = None) -> HostDetection:
    """从进程环境识别宿主，兼容变量不得覆盖原生平台信号。"""
    env = environ if environ is not None else os.environ

    if env.get("CODEBUDDY_PLUGIN_ROOT"):
        return HostDetection(HostPlatform.CODEBUDDY, "CODEBUDDY_PLUGIN_ROOT")
    if env.get("CODEX_THREAD_ID"):
        return HostDetection(HostPlatform.CODEX, "CODEX_THREAD_ID")
    if env.get("CODEX_SANDBOX"):
        return HostDetection(HostPlatform.CODEX, "CODEX_SANDBOX")
    if env.get("CLAUDE_CODE"):
        return HostDetection(HostPlatform.CLAUDE_CODE, "CLAUDE_CODE")
    if env.get("CLAUDE_CODE_ENTRYPOINT"):
        return HostDetection(HostPlatform.CLAUDE_CODE, "CLAUDE_CODE_ENTRYPOINT")
    if "claude" in env.get("ANTHROPIC_CLI", "").lower():
        return HostDetection(
            HostPlatform.CLAUDE_CODE,
            "ANTHROPIC_CLI (claude substring)",
        )
    return HostDetection(HostPlatform.UNKNOWN, "no host signal")


__all__ = [
    "GitAuthorization",
    "GitOperation",
    "HostAdapter",
    "HostCapabilities",
    "HostDetection",
    "HostPlatform",
    "capabilities_for",
    "detect_host",
]
