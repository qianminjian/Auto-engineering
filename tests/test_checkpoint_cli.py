"""Tests for ae checkpoint CLI commands — Phase 1.1.

覆盖: ae checkpoint list / show / resume
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def valid_project_with_checkpoint(tmp_path: Path, monkeypatch):
    """Project root 含 .git + .ae-answers.yml + ANTHROPIC_API_KEY + 1 checkpoint."""
    from auto_engineering.engine.checkpoint import Checkpoint, CheckpointStore
    from auto_engineering.engine.state import LoopState

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
    monkeypatch.chdir(tmp_path)

    # 创建 1 个 checkpoint
    cp_dir = tmp_path / ".ae-checkpoints"
    cp_dir.mkdir()
    store = CheckpointStore(str(cp_dir / "test.db"))
    state = LoopState(requirement="implement x", verdict="APPROVE")
    cp = Checkpoint.create(thread_id="thread-1", state=state)
    store.save_checkpoint(cp)
    cp.increment_step()
    store.save_checkpoint(cp)
    store.close()

    return tmp_path


class TestCheckpointList:
    """ae checkpoint list."""

    def test_list_empty(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
        monkeypatch.chdir(tmp_path)

        from auto_engineering.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "list"])
        assert result.exit_code == 0
        # 接受两种输出:no checkpoint dir 或 no checkpoints
        out = result.output.lower()
        assert "no checkpoint" in out or "no checkpoints" in out or "(empty)" in out

    def test_list_with_checkpoints(self, valid_project_with_checkpoint):
        from auto_engineering.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "list"])
        assert result.exit_code == 0
        assert "thread-1" in result.output
        assert "test.db" in result.output or "test" in result.output


class TestCheckpointShow:
    """ae checkpoint show <id>."""

    def test_show_existing(self, valid_project_with_checkpoint):
        from auto_engineering.cli import main
        from auto_engineering.engine.checkpoint import CheckpointStore

        cp_dir = valid_project_with_checkpoint / ".ae-checkpoints"
        store = CheckpointStore(str(cp_dir / "test.db"))
        checkpoints = store.list_all()
        cp_id = checkpoints[0]["id"]
        store.close()

        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "show", cp_id])
        assert result.exit_code == 0
        assert cp_id in result.output
        assert "thread-1" in result.output

    def test_show_nonexistent(self, valid_project_with_checkpoint):
        from auto_engineering.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "show", "nonexistent-id"])
        assert result.exit_code != 0


class TestCheckpointResume:
    """ae checkpoint resume <id>."""

    def test_resume_nonexistent(self, valid_project_with_checkpoint):
        from auto_engineering.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "resume", "nonexistent-id"])
        assert result.exit_code != 0
