"""P2-B-3 (deep audit) — tools/git_tools.py 直接测试.

3 个类 (GitStatusTool / GitCommitTool / GitDiffTool) 之前没有直接
测试文件, 仅通过 dev-loop / test_tools_integration 间接覆盖.
每个工具都用真实 git subprocess (tmp_path repo), 验证返回 ToolResult
的 success / content / error 字段.

测试原则 (per pytest-memory-management.md): 单文件 pytest --no-cov --timeout=60.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auto_engineering.tools.git_tools import (
    GitCommitTool,
    GitDiffTool,
    GitStatusTool,
)
from tests.conftest import run_async


def _init_git_repo(path: Path) -> None:
    """初始化一个 git repo + 一次 commit (HEAD 存在, status 干净)."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        check=True,
    )
    (path / "README.md").write_text("init")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=path, check=True
    )


# ============================================================
# I. GitStatusTool
# ============================================================


class TestGitStatusTool:
    """git status 工具."""

    def test_clean_repo_returns_clean(self, tmp_path: Path) -> None:
        """干净 repo → success, content='(clean)'."""
        _init_git_repo(tmp_path)
        result = run_async(GitStatusTool().execute(cwd=str(tmp_path)))
        assert result.success is True
        assert result.content == "(clean)"

    def test_modified_file_shows_in_status(self, tmp_path: Path) -> None:
        """修改文件 → status 含 M README.md."""
        _init_git_repo(tmp_path)
        (tmp_path / "README.md").write_text("modified")
        result = run_async(GitStatusTool().execute(cwd=str(tmp_path)))
        assert result.success is True
        assert "M README.md" in result.content

    def test_new_untracked_file(self, tmp_path: Path) -> None:
        """新未跟踪文件 → status 含 ?? new.txt."""
        _init_git_repo(tmp_path)
        (tmp_path / "new.txt").write_text("new")
        result = run_async(GitStatusTool().execute(cwd=str(tmp_path)))
        assert result.success is True
        assert "?? new.txt" in result.content

    def test_invalid_cwd_returns_error(self, tmp_path: Path) -> None:
        """无效 cwd (非 git 目录) → success=False, error 含 stderr."""
        result = run_async(GitStatusTool().execute(cwd=str(tmp_path)))
        assert result.success is False
        assert result.error  # 非空


# ============================================================
# II. GitCommitTool
# ============================================================


class TestGitCommitTool:
    """git add -A + git commit 工具."""

    def test_empty_message_rejected(self, tmp_path: Path) -> None:
        """空 message → 拒绝, 不调用 git."""
        _init_git_repo(tmp_path)
        result = run_async(GitCommitTool().execute(cwd=str(tmp_path), message=""))
        assert result.success is False
        assert "empty" in result.error.lower()

    def test_commit_staged_changes(self, tmp_path: Path) -> None:
        """修改 + commit → 成功, 新的 commit 出现."""
        _init_git_repo(tmp_path)
        (tmp_path / "README.md").write_text("updated content")
        result = run_async(
            GitCommitTool().execute(cwd=str(tmp_path), message="update readme")
        )
        assert result.success is True
        # 验证 commit 真的发生了
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "update readme" in log.stdout

    def test_commit_includes_new_files(self, tmp_path: Path) -> None:
        """commit 自动 add -A 包含新文件."""
        _init_git_repo(tmp_path)
        (tmp_path / "brand_new.txt").write_text("new file")
        result = run_async(
            GitCommitTool().execute(cwd=str(tmp_path), message="add new file")
        )
        assert result.success is True
        # 验证新文件被 tracked
        ls_files = subprocess.run(
            ["git", "ls-files"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "brand_new.txt" in ls_files.stdout

    def test_commit_nothing_to_commit(self, tmp_path: Path) -> None:
        """无任何修改 → git commit 返回非零 → ToolResult 失败.

        v2.5 实测: 'nothing to commit' 信息走到 stdout, GitCommitTool 的
        error 字段只回显 'git commit failed: ' 前缀. 验证 success=False
        + error 含 'commit failed' 前缀即可.
        """
        _init_git_repo(tmp_path)
        result = run_async(
            GitCommitTool().execute(cwd=str(tmp_path), message="empty commit")
        )
        assert result.success is False
        assert "commit failed" in result.error.lower()


# ============================================================
# III. GitDiffTool
# ============================================================


class TestGitDiffTool:
    """git diff 工具."""

    def test_clean_repo_no_diff(self, tmp_path: Path) -> None:
        """干净 repo → diff 为空, content='(no changes)'."""
        _init_git_repo(tmp_path)
        result = run_async(GitDiffTool().execute(cwd=str(tmp_path)))
        assert result.success is True
        assert result.content == "(no changes)"

    def test_unstaged_diff_shows_modification(self, tmp_path: Path) -> None:
        """未 stage 修改 → diff 显示 + 行."""
        _init_git_repo(tmp_path)
        (tmp_path / "README.md").write_text("line1\nline2 added\n")
        result = run_async(GitDiffTool().execute(cwd=str(tmp_path)))
        assert result.success is True
        assert "line2 added" in result.content

    def test_staged_diff(self, tmp_path: Path) -> None:
        """staged diff 显示已 stage 的修改."""
        _init_git_repo(tmp_path)
        (tmp_path / "README.md").write_text("staged content")
        subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
        result = run_async(GitDiffTool().execute(cwd=str(tmp_path), staged=True))
        assert result.success is True
        assert "staged content" in result.content

    def test_diff_against_target(self, tmp_path: Path) -> None:
        """diff against HEAD~1 显示上一 commit 之后的改动."""
        _init_git_repo(tmp_path)
        # 第一次 commit (init)
        (tmp_path / "README.md").write_text("v1 content")
        subprocess.run(
            ["git", "commit", "-q", "-am", "v1"], cwd=tmp_path, check=True
        )
        # 第二次 commit
        (tmp_path / "README.md").write_text("v2 content")
        subprocess.run(
            ["git", "commit", "-q", "-am", "v2"], cwd=tmp_path, check=True
        )
        # 修改 working tree
        (tmp_path / "README.md").write_text("v3 uncommitted")
        result = run_async(
            GitDiffTool().execute(cwd=str(tmp_path), target="HEAD~1")
        )
        assert result.success is True
        # HEAD~1..HEAD = v1..v2 + uncommitted 改动, 应含 v3
        assert "v3 uncommitted" in result.content or "v2 content" in result.content
