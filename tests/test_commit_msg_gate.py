"""T16n — CommitMsgGate Angular 格式校验.

覆盖: 格式校验 / 类型白名单 / subject 长度 / 空列表处理 / git log 读取.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from auto_engineering.gates.commit_msg_gate import CommitMsgGate

_ANGULAR_TYPES = {
    "feat", "fix", "docs", "style", "refactor", "test",
    "chore", "perf", "ci", "revert", "security", "hotfix",
}


class TestCommitMsgGateFormat:
    """格式校验: Angular <type>(<scope>): <subject>."""

    def test_valid_simple_passes(self) -> None:
        gate = CommitMsgGate()
        verdict = gate.run_with_messages(["feat(git): precise staging"])
        assert verdict.passed is True

    def test_valid_no_scope_passes(self) -> None:
        gate = CommitMsgGate()
        verdict = gate.run_with_messages(["fix: crash on empty cwd"])
        assert verdict.passed is True

    def test_invalid_no_colon_fails(self) -> None:
        gate = CommitMsgGate()
        verdict = gate.run_with_messages(["feat(git) precise staging"])
        assert verdict.passed is False

    def test_invalid_unknown_type_fails(self) -> None:
        gate = CommitMsgGate()
        verdict = gate.run_with_messages(["unknown(git): something"])
        assert verdict.passed is False

    def test_subject_too_long_fails(self) -> None:
        gate = CommitMsgGate()
        msg = f"feat(git): {'x' * 51}"
        verdict = gate.run_with_messages([msg])
        assert verdict.passed is False

    def test_subject_exactly_50_chars_passes(self) -> None:
        gate = CommitMsgGate()
        msg = f"fix: {'y' * 45}"  # "fix: " (5) + 45 = 50
        verdict = gate.run_with_messages([msg])
        assert verdict.passed is True

    def test_all_valid_types_accepted(self) -> None:
        gate = CommitMsgGate()
        for t in sorted(_ANGULAR_TYPES):
            verdict = gate.run_with_messages([f"{t}: test"])
            assert verdict.passed is True, f"类型 {t} 应通过"

    def test_multiple_messages_all_valid(self) -> None:
        gate = CommitMsgGate()
        verdict = gate.run_with_messages([
            "feat(git): precise staging",
            "fix: crash on empty cwd",
            "docs: update changelog",
        ])
        assert verdict.passed is True

    def test_multiple_messages_one_invalid(self) -> None:
        gate = CommitMsgGate()
        verdict = gate.run_with_messages([
            "feat(git): precise staging",
            "bad commit message without format",
        ])
        assert verdict.passed is False


class TestCommitMsgGateBoundaries:
    """边界条件."""

    def test_empty_messages_passes(self) -> None:
        gate = CommitMsgGate()
        verdict = gate.run_with_messages([])
        assert verdict.passed is True

    def test_whitespace_only_message_fails(self) -> None:
        gate = CommitMsgGate()
        verdict = gate.run_with_messages(["   "])
        assert verdict.passed is False

    def test_scope_with_special_chars(self) -> None:
        gate = CommitMsgGate()
        verdict = gate.run_with_messages([
            "feat(api-v2): implement new endpoint"
        ])
        assert verdict.passed is True


class TestCommitMsgGateGitLog:
    """从 git log 读取 commit messages."""

    def test_run_reads_latest_commit(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=tmp_path, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, check=True,
        )
        (tmp_path / "f.txt").write_text("x")
        subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "feat(gate): angular commit check"],
            cwd=tmp_path, check=True,
        )

        gate = CommitMsgGate(max_commits=1)
        verdict = gate.run(tmp_path)
        assert verdict.passed is True

    def test_invalid_commit_detected_from_git(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=tmp_path, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, check=True,
        )
        (tmp_path / "f.txt").write_text("x")
        subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "bad format no angular"],
            cwd=tmp_path, check=True,
        )

        gate = CommitMsgGate(max_commits=1)
        verdict = gate.run(tmp_path)
        assert verdict.passed is False
