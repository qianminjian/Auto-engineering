"""T16n — CommitMsgGate: Angular commit message 格式校验.

校验 <type>(<scope>): <subject> 格式:
  - type: 12 种白名单 (angular 规范)
  - scope: 可选, 括号包裹
  - subject: ≤ 50 字符
  - applies_to_stages: developer only

参考: engineering-practices.md §2.1 Angular 规范.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from auto_engineering.gates.base import Gate, GateVerdict

__all__ = ["CommitMsgGate"]

_VALID_TYPES = (
    "feat|fix|docs|style|refactor|test|"
    "chore|perf|ci|revert|security|hotfix"
)
_ANGULAR_RE = re.compile(
    rf"^({_VALID_TYPES})(\([^)]*\))?: .{{1,50}}$"
)


class CommitMsgGate(Gate):
    """Gate: Angular commit message 格式校验.

    Args:
        max_commits: 校验最近 N 条 commit (默认 5, 环内通常 1).
    """

    name = "commit_msg"
    applies_to_stages = ("developer",)

    def __init__(self, max_commits: int = 5):
        self.max_commits = max_commits

    def run_with_messages(self, messages: list[str]) -> GateVerdict:
        """直接校验给定 messages (测试/注入路径).

        空列表 → pass (无可校验).
        """
        if not messages:
            return GateVerdict.ok("no commits to check", gate_name=self.name)

        invalid: list[str] = []
        for i, msg in enumerate(messages):
            msg = msg.strip()
            if not _ANGULAR_RE.match(msg):
                invalid.append(f"#{i+1}: {msg[:80]}")

        if invalid:
            return GateVerdict.failed(
                f"Angular 格式校验失败 ({len(invalid)}/{len(messages)}):\n"
                + "\n".join(invalid),
                gate_name=self.name,
            )
        return GateVerdict.ok(
            f"Angular 格式通过 ({len(messages)} commits)",
            gate_name=self.name,
        )

    def _read_git_log(self, project_root: Path) -> list[str]:
        """读取最近 max_commits 条 commit messages."""
        try:
            proc = subprocess.run(
                ["git", "log", f"-{self.max_commits}", "--format=%s"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode != 0:
                return []
            return [m for m in proc.stdout.strip().split("\n") if m.strip()]
        except (OSError, subprocess.SubprocessError):
            return []

    def run(self, project_root: Path) -> GateVerdict:
        """从 git log 读取最近 max_commits 条并校验."""
        project_root = Path(project_root)
        if verdict := self._validate_project_root(project_root):
            return verdict

        messages = self._read_git_log(project_root)
        if not messages:
            return GateVerdict.ok("no commits to check", gate_name=self.name)

        invalid: list[str] = []
        for msg in messages:
            if not _ANGULAR_RE.match(msg.strip()):
                invalid.append(msg[:80])

        if invalid:
            return GateVerdict.failed(
                f"Angular 格式校验失败 ({len(invalid)}/{len(messages)}):\n"
                + "\n".join(f"  - {m}" for m in invalid),
                gate_name=self.name,
            )
        return GateVerdict.ok(
            f"Angular 格式通过 ({len(messages)} commits)",
            gate_name=self.name,
        )
