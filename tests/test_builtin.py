"""Tests for gates/builtin.py — Phase 2 T7.

TDD Red phase: 5 个内置 Guardrail.
    1. RequirementGuardrail  — requirement 非空
    2. PlanExistsGuardrail   — plan 文件存在
    3. GitCleanGuardrail     — git status 干净
    4. TestsPassGuardrail    — pytest 绿(用 mock 避免真实 pytest)
    5. GitDiffExistsGuardrail — 有 commit 可审查

Phase 1 gates/gates.py 4 个 Gate 升级为 Guardrail 4 态(P0-18 决策).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from auto_engineering.engine.graph import Stage
from auto_engineering.engine.state import LoopState
from auto_engineering.gates.builtin import (
    GitCleanGuardrail,
    GitDiffExistsGuardrail,
    PlanExistsGuardrail,
    RequirementGuardrail,
    TestsPassGuardrail,
)


def _stage() -> Stage:
    return Stage(name="x", agent_type="x", description_template="", expected_output="")


class TestRequirementGuardrail:
    """RequirementGuardrail: requirement 非空."""

    def test_empty_requirement_blocks(self):
        g = RequirementGuardrail()
        result = g.check(_stage(), LoopState(requirement=""))
        assert result.action == "block"
        assert "requirement" in result.reason.lower() or "空" in result.reason

    def test_whitespace_only_blocks(self):
        g = RequirementGuardrail()
        result = g.check(_stage(), LoopState(requirement="   \n\t  "))
        assert result.action == "block"

    def test_valid_requirement_passes(self):
        g = RequirementGuardrail()
        result = g.check(_stage(), LoopState(requirement="实现用户登录"))
        assert result.action == "pass"


class TestPlanExistsGuardrail:
    """PlanExistsGuardrail: plan 文件存在."""

    def test_default_path(self, tmp_path: Path):
        """默认 plan_path = design/dev-loop-plan.md(可覆盖)."""
        g = PlanExistsGuardrail(project_root=tmp_path)
        # tmp_path 下无 plan 文件 → block
        result = g.check(_stage(), LoopState())
        assert result.action == "block"

    def test_plan_exists_passes(self, tmp_path: Path):
        plan = tmp_path / "design" / "dev-loop-plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# plan")
        g = PlanExistsGuardrail(project_root=tmp_path)
        result = g.check(_stage(), LoopState())
        assert result.action == "pass"

    def test_custom_plan_path(self, tmp_path: Path):
        """可指定 plan_path(覆盖默认)."""
        custom = tmp_path / "my-plan.md"
        custom.write_text("# plan")
        g = PlanExistsGuardrail(project_root=tmp_path, plan_path=custom)
        result = g.check(_stage(), LoopState())
        assert result.action == "pass"


class TestGitCleanGuardrail:
    """GitCleanGuardrail: git status 干净."""

    def test_clean_repo_passes(self, tmp_path: Path):
        # 初始化 git repo + initial commit
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "--allow-empty",
                "-m",
                "init",
            ],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        g = GitCleanGuardrail(project_root=tmp_path)
        result = g.check(_stage(), LoopState())
        assert result.action == "pass"

    def test_dirty_repo_blocks(self, tmp_path: Path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "--allow-empty",
                "-m",
                "init",
            ],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        # 写入 untracked file
        (tmp_path / "dirty.txt").write_text("untracked")
        g = GitCleanGuardrail(project_root=tmp_path)
        result = g.check(_stage(), LoopState())
        assert result.action == "block"
        assert "dirty.txt" in result.reason

    def test_subprocess_timeout_returns_drop(self, tmp_path: Path):
        """git 命令超时 → drop(避免阻塞循环)."""
        g = GitCleanGuardrail(project_root=tmp_path, timeout=0.001)
        # 没初始化 git 的目录,git status 会立即失败,不超时
        # 用 timeout 触发 sub process timeout
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git"], timeout=0.001)
            result = g.check(_stage(), LoopState())
            assert result.action == "drop"


class TestTestsPassGuardrail:
    """TestsPassGuardrail: pytest 绿(用 mock 隔离真实 pytest)."""

    def test_passing_tests_passes(self, tmp_path: Path):
        g = TestsPassGuardrail(project_root=tmp_path, test_runner="pytest")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = g.check(_stage(), LoopState())
            assert result.action == "pass"

    def test_failing_tests_blocks(self, tmp_path: Path):
        g = TestsPassGuardrail(project_root=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="FAILED", stderr="")
            result = g.check(_stage(), LoopState())
            assert result.action == "block"

    def test_subprocess_timeout_drops(self, tmp_path: Path):
        g = TestsPassGuardrail(project_root=tmp_path, timeout=0.001)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["pytest"], timeout=0.001)
            result = g.check(_stage(), LoopState())
            assert result.action == "drop"


class TestGitDiffExistsGuardrail:
    """GitDiffExistsGuardrail: 有 commit 可审查."""

    def test_repo_with_commits_passes(self, tmp_path: Path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "--allow-empty",
                "-m",
                "c1",
            ],
            cwd=tmp_path,
            capture_output=True,
            check=True,
        )
        g = GitDiffExistsGuardrail(project_root=tmp_path)
        result = g.check(_stage(), LoopState())
        assert result.action == "pass"
        assert result.payload and "commit" in result.payload

    def test_empty_repo_blocks(self, tmp_path: Path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        # no commit yet
        g = GitDiffExistsGuardrail(project_root=tmp_path)
        result = g.check(_stage(), LoopState())
        assert result.action == "block"

    def test_not_a_git_repo_blocks(self, tmp_path: Path):
        g = GitDiffExistsGuardrail(project_root=tmp_path)
        result = g.check(_stage(), LoopState())
        assert result.action == "block"


class TestBuiltinGuardrailsExportable:
    """5 个 Guardrail 应能从 gates.builtin import."""

    def test_all_five_importable(self):
        from auto_engineering.gates import builtin

        assert hasattr(builtin, "RequirementGuardrail")
        assert hasattr(builtin, "PlanExistsGuardrail")
        assert hasattr(builtin, "GitCleanGuardrail")
        assert hasattr(builtin, "TestsPassGuardrail")
        assert hasattr(builtin, "GitDiffExistsGuardrail")
