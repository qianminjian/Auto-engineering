"""Tests for ae checkpoint CLI commands — Phase 1.1.

覆盖: ae checkpoint list / show / resume

v2.3 P0-B: v1.0 CLI 命令已切到 SQLiteCheckpointStore (v2.0 schema).
test fixture 现在用 SQLiteCheckpointStore 造数据, 断言对应 v2.0 字段 (round / schema_version).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def valid_project_with_checkpoint(tmp_path: Path, monkeypatch):
    """Project root 含 .git + .ae-answers.yml + ANTHROPIC_API_KEY + 1 v2.0 checkpoint.

    v2.3 P0-B: fixture 用 SQLiteCheckpointStore 造数据 (v2.0 schema),
    与 v1.0 CLI 命令 (list/show/resume) 切换后的 backend 一致.
    """
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
    monkeypatch.chdir(tmp_path)

    # 创建 1 个 v2.0 checkpoint (用 CheckpointEnvelope)
    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    db_file = cp_dir / "test.db"
    store = SQLiteCheckpointStore(str(db_file))
    envelope = CheckpointEnvelope(round=1, step=2, status="running")
    store.save(envelope, round=1, step=2, history=[])
    store.save(envelope, round=1, step=3, history=[])
    store.clear()  # 简化: 只留 1 条
    store.save(envelope, round=1, step=2, history=[])

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
        # v2.3 P0-B: v1.0 CLI 用 v2.0 schema, 输出列: ID/ROUND/STEP/SCHEMA/DB/CREATED
        assert "ROUND" in result.output
        assert "SCHEMA" in result.output
        assert "test.db" in result.output or "test" in result.output


class TestCheckpointShow:
    """ae checkpoint show <id>."""

    def test_show_existing(self, valid_project_with_checkpoint):
        from auto_engineering.cli import main
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        cp_dir = valid_project_with_checkpoint / ".ae-state"
        store = SQLiteCheckpointStore(str(cp_dir / "test.db"))
        metas = store.list_all()
        assert len(metas) > 0
        cp_id = metas[0].id

        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "show", cp_id])
        assert result.exit_code == 0, f"output: {result.output}"
        assert cp_id in result.output
        assert "Round" in result.output
        assert "Schema" in result.output

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
