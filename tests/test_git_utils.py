"""Smoke tests for utils/git.py — run_git + capture_head + run_git_diff."""

from __future__ import annotations

from pathlib import Path

from auto_engineering.utils.git import capture_head, run_git, run_git_diff


class TestRunGit:
    """run_git: 同步跑 git 命令，返回 (rc, stdout)."""

    def test_run_git_version(self) -> None:
        """git --version should succeed in any git repo."""
        rc, stdout = run_git(".", "--version")
        assert rc == 0
        assert "git version" in stdout

    def test_run_git_status_succeeds(self) -> None:
        """git status in the repo root should succeed."""
        rc, _stdout = run_git(".", "status", "--porcelain")
        assert rc == 0

    def test_run_git_invalid_path_returns_nonzero(self) -> None:
        """Running git in a nonexistent directory returns non-zero rc
        (git itself returns 128 for fatal errors; rc=255 is only for Python-level
        exceptions like TimeoutExpired/FileNotFoundError)."""
        rc, stdout = run_git("/nonexistent/path/12345", "status")
        assert rc != 0
        assert stdout == ""


class TestCaptureHead:
    """capture_head: 捕获当前 HEAD commit hash."""

    def test_capture_head_returns_hash(self) -> None:
        """Should return a 40-char hex hash when in a git repo."""
        result = capture_head(".")
        assert result is not None
        assert len(result) == 40
        assert all(c in "0123456789abcdef" for c in result)

    def test_capture_head_none_arg_defaults_to_cwd(self) -> None:
        """capture_head(None) defaults to current directory."""
        result = capture_head(None)
        assert result is not None
        assert len(result) == 40

    def test_capture_head_nonexistent_dir_returns_none(self) -> None:
        """Nonexistent directory returns None."""
        result = capture_head("/nonexistent/path/xyz")
        assert result is None


class TestRunGitDiff:
    """run_git_diff: git diff --numstat 封装."""

    def test_run_git_diff_with_head(self) -> None:
        """git diff --numstat HEAD should succeed (may be empty output)."""
        rc, _stdout = run_git_diff(Path("."), ["HEAD"])
        assert rc == 0

    def test_run_git_diff_cached(self) -> None:
        """git diff --numstat --cached should succeed."""
        rc, _stdout = run_git_diff(Path("."), ["--cached"])
        assert rc == 0
