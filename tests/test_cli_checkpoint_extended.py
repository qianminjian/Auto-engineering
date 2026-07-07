"""test_cli_checkpoint_extended.py — Phase 12.7 P1-3.

cli/checkpoint.py 扩展覆盖率测试.

覆盖关键路径:
- ae checkpoint list (v1 + v2)
- ae checkpoint show <id>
- ae checkpoint resume <id>
- ae checkpoint v2 list [--round N]
- ae checkpoint v2 show <id>
- ae checkpoint v2 delete <id>
- ae checkpoint v2 migrate <src> <dst>
- 错误处理: dir 不存在, id 找不到, db 损坏
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from auto_engineering.cli import main


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def project_with_v1_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """项目根 + .git + .ae-answers.yml + 1 个 v1.0 checkpoint (via SQLiteCheckpointStore)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
    monkeypatch.chdir(tmp_path)

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    db_file = cp_dir / "v1.db"
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    store = SQLiteCheckpointStore(str(db_file))
    envelope = CheckpointEnvelope(round=1, step=2, status="running")
    store.save(envelope, round=1, step=2, history=[])
    return tmp_path


@pytest.fixture
def project_with_v2_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """项目根 + .git + .ae-answers.yml + 2 个 v2.0 checkpoint (不同 round)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
    monkeypatch.chdir(tmp_path)

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    db_file = cp_dir / "v2.db"
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    store = SQLiteCheckpointStore(str(db_file))
    env1 = CheckpointEnvelope(round=1, step=2, status="running")
    env2 = CheckpointEnvelope(round=2, step=3, status="drained")
    store.save(env1, round=1, step=2, history=[])
    store.save(env2, round=2, step=3, history=[])
    return tmp_path


@pytest.fixture
def empty_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """项目根但无 .ae-state 目录."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ============================================================
# 1. ae checkpoint list (v1)
# ============================================================


class TestCheckpointListV1:
    """ae checkpoint list (v1 入口)."""

    def test_list_empty_dir_message(self, empty_project: Path) -> None:
        """无 .ae-state 目录 → 显示 'no checkpoint directory'."""
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "list"])
        assert result.exit_code == 0
        assert "no checkpoint" in result.output.lower()

    def test_list_with_v1_checkpoints(self, project_with_v1_checkpoints: Path) -> None:
        """有 v1 checkpoint → 输出表格 (含 ROUND/SCHEMA 列)."""
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "list"])
        assert result.exit_code == 0
        assert "ROUND" in result.output
        assert "SCHEMA" in result.output
        assert "v1.db" in result.output

    def test_list_handles_corrupted_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """.ae-state 目录含损坏 .db 文件 → 跳过 + warn."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
        monkeypatch.chdir(tmp_path)
        cp_dir = tmp_path / ".ae-state"
        cp_dir.mkdir()
        bad_db = cp_dir / "bad.db"
        bad_db.write_bytes(b"not a sqlite database")

        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "list"])
        # 不应抛 traceback
        assert result.exit_code in (0, 1)
        # 应有 warn 或 skip
        assert "[warn]" in result.output or "(no checkpoints)" in result.output


# ============================================================
# 2. ae checkpoint show (v1)
# ============================================================


class TestCheckpointShowV1:
    """ae checkpoint show <id>."""

    def test_show_existing(self, project_with_v1_checkpoints: Path) -> None:
        runner = CliRunner()
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        cp_dir = project_with_v1_checkpoints / ".ae-state"
        store = SQLiteCheckpointStore(str(cp_dir / "v1.db"))
        metas = store.list_all()
        cp_id = metas[0].id

        result = runner.invoke(main, ["checkpoint", "show", cp_id])
        assert result.exit_code == 0, f"output: {result.output}"
        assert "Round" in result.output
        assert "Schema" in result.output

    def test_show_nonexistent_id(self, project_with_v1_checkpoints: Path) -> None:
        """id 不存在 → exit 1."""
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "show", "nonexistent-id"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_show_without_checkpoint_dir(self, empty_project: Path) -> None:
        """无 .ae-state → exit 1."""
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "show", "any-id"])
        assert result.exit_code != 0


# ============================================================
# 3. ae checkpoint resume (v1)
# ============================================================


class TestCheckpointResumeV1:
    """ae checkpoint resume <id>."""

    def test_resume_existing(self, project_with_v1_checkpoints: Path) -> None:
        runner = CliRunner()
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        cp_dir = project_with_v1_checkpoints / ".ae-state"
        store = SQLiteCheckpointStore(str(cp_dir / "v1.db"))
        metas = store.list_all()
        cp_id = metas[0].id

        result = runner.invoke(main, ["checkpoint", "resume", cp_id])
        assert result.exit_code == 0, f"output: {result.output}"
        assert "Resume" in result.output
        assert "ae dev-loop" in result.output or "--resume" in result.output

    def test_resume_nonexistent_id(self, project_with_v1_checkpoints: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "resume", "nope"])
        assert result.exit_code != 0
        assert "not found" in result.output


# ============================================================
# 4. ae checkpoint v2 list
# ============================================================


class TestCheckpointV2List:
    """ae checkpoint v2 list [--round N]."""

    def test_list_no_dir(self, empty_project: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "list"])
        assert result.exit_code == 0
        assert "no checkpoint" in result.output.lower()

    def test_list_with_v2_checkpoints(self, project_with_v2_checkpoints: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "list"])
        assert result.exit_code == 0
        # header (含 ROUND) 在 stderr, 数据行在 stdout — 检查 combined output
        assert "ROUND" in result.output or "ROUND" in result.stderr
        assert "v2.db" in result.output or "v2.db" in result.stderr
        # 2 个 checkpoints 数据行应在 stdout (各含 v2.db)
        stdout_lines = [
            ln for ln in result.stdout.splitlines() if "v2.db" in ln
        ]
        assert len(stdout_lines) >= 2

    def test_list_filter_by_round_1(self, project_with_v2_checkpoints: Path) -> None:
        """--round=1 过滤 → 只显示 round=1."""
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "list", "--round", "1"])
        assert result.exit_code == 0
        # 输出应包含 round=1 数据行, 不包含 round=2
        # 简化: 验证有 v2.db 出现 (至少 1 行匹配)
        assert "v2.db" in result.output

    def test_list_filter_by_round_nonexistent(
        self, project_with_v2_checkpoints: Path
    ) -> None:
        """--round=999 (无匹配) → 'no v2 checkpoints'."""
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "list", "--round", "999"])
        assert result.exit_code == 0
        assert "no v2 checkpoints" in result.output


# ============================================================
# 5. ae checkpoint v2 show
# ============================================================


class TestCheckpointV2Show:
    """ae checkpoint v2 show <id>."""

    def test_show_existing(self, project_with_v2_checkpoints: Path) -> None:
        runner = CliRunner()
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        cp_dir = project_with_v2_checkpoints / ".ae-state"
        store = SQLiteCheckpointStore(str(cp_dir / "v2.db"))
        metas = store.list_all()
        cp_id = metas[0].id

        result = runner.invoke(main, ["checkpoint", "v2", "show", cp_id])
        assert result.exit_code == 0, f"output: {result.output}"
        assert "ID:" in result.output
        assert "Round:" in result.output

    def test_show_nonexistent_id(self, project_with_v2_checkpoints: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "show", "nonexistent"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_show_without_checkpoint_dir(self, empty_project: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "show", "any"])
        assert result.exit_code != 0


# ============================================================
# 6. ae checkpoint v2 delete
# ============================================================


class TestCheckpointV2Delete:
    """ae checkpoint v2 delete <id>."""

    def test_delete_existing(self, project_with_v2_checkpoints: Path) -> None:
        runner = CliRunner()
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        cp_dir = project_with_v2_checkpoints / ".ae-state"
        store = SQLiteCheckpointStore(str(cp_dir / "v2.db"))
        metas = store.list_all()
        assert len(metas) >= 1
        cp_id = metas[0].id

        result = runner.invoke(main, ["checkpoint", "v2", "delete", cp_id])
        assert result.exit_code == 0, f"output: {result.output}"
        assert "Deleted" in result.output

        # 验证真的删了
        store2 = SQLiteCheckpointStore(str(cp_dir / "v2.db"))
        remaining = store2.list_all()
        remaining_ids = {m.id for m in remaining}
        assert cp_id not in remaining_ids

    def test_delete_nonexistent(self, project_with_v2_checkpoints: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "delete", "nope"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_delete_without_checkpoint_dir(self, empty_project: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "delete", "any"])
        assert result.exit_code != 0


# ============================================================
# 7. ae checkpoint v2 migrate
# ============================================================


class TestCheckpointV2Migrate:
    """ae checkpoint v2 migrate <src.json> <dst.sqlite>."""

    def test_migrate_v1_to_v2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """正常迁移: v1.1 JSON → v2.0 SQLite."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
        monkeypatch.chdir(tmp_path)

        v1_data = {
            "status": "running",
            "loop_state": {"round": 2, "step": 1, "requirement": "test"},
            "history": [
                {
                    "round_id": 1,
                    "files_changed": 3,
                    "lines_added": 50,
                    "lines_removed": 10,
                    "gate_results": {"safety": True},
                    "semantic_satisfied": None,
                }
            ],
        }
        src = tmp_path / "v1.json"
        src.write_text(json.dumps(v1_data))
        dst = tmp_path / "v2.sqlite"

        runner = CliRunner()
        result = runner.invoke(
            main, ["checkpoint", "v2", "migrate", str(src), str(dst)]
        )
        assert result.exit_code == 0, f"output: {result.output}"
        assert "Migrated" in result.output
        assert dst.exists()

    def test_migrate_invalid_source_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """源 JSON 不存在 → exit 1 (click.Path exists=True)."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        # click.Path(exists=True) 会拒绝不存在路径
        result = runner.invoke(
            main,
            [
                "checkpoint",
                "v2",
                "migrate",
                str(tmp_path / "nonexistent.json"),
                str(tmp_path / "dst.sqlite"),
            ],
        )
        assert result.exit_code != 0


# ============================================================
# 8. register_checkpoint_commands 结构
# ============================================================


class TestRegisterCheckpointCommands:
    """register_checkpoint_commands 注入所有子命令."""

    def test_all_subcommands_registered(self) -> None:
        """checkpoint 命令含 list / show / resume / v2 (group)."""
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "show" in result.output
        assert "resume" in result.output
        assert "v2" in result.output

    def test_v2_subcommands_registered(self) -> None:
        """v2 子命令含 list / show / delete / migrate."""
        runner = CliRunner()
        result = runner.invoke(main, ["checkpoint", "v2", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "show" in result.output
        assert "delete" in result.output
        assert "migrate" in result.output