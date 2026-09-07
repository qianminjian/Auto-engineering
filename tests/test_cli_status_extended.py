"""Extended contract tests for cli/status.py.

The old checkpoint-oriented cases remain as negative compatibility tests: a
checkpoint-only directory must not be presented as the current loop state.
Current-state reads are covered by EventStore projection tests in
``tests/test_cli_status.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from auto_engineering.cli import main
from auto_engineering.cli.status import _collect_status_json

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ============================================================
# Group 1: checkpoint-only state must not be exposed
# ============================================================


def test_collect_status_json_ignores_checkpoint_dict(tmp_path: Path) -> None:
    """checkpoint 中的 raw dict 不能冒充 EventStore 当前状态。"""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    db_path = cp_dir / "test.db"
    store = SQLiteCheckpointStore(str(db_path))

    # plain dict: 无 channels / 无 thread_id → deserialize_state 返回原始 dict
    state_dict: dict = {
        "round": 5,
        "current_stage": "developer",
        "critic_verdict": "APPROVE",
        "majors_in_a_row": 3,
        "total_majors": 7,
    }
    store.save(state=state_dict, round=5, step=1)

    data = _collect_status_json(tmp_path)
    # EventStore 不存在 → 始终返回空状态。
    assert data["thread_id"] == ""
    assert data["round"] == 0
    assert data["stage"] == ""
    assert data["verdict"] == ""
    assert data["majors_in_a_row"] == 0
    assert data["total_majors"] == 0


# ============================================================
# Group 2: checkpoint object must not be exposed
# ============================================================


def test_collect_status_json_ignores_checkpoint_engine_state(tmp_path: Path) -> None:
    """EngineState checkpoint 也不能绕过 EventStore 当前事实源。"""
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    store = SQLiteCheckpointStore(str(cp_dir / "test.db"))
    state = EngineState(
        thread_id="engine-thread-1",
        current_stage="critic",
        round=4,
        critic_verdict="APPROVE",
        majors_in_a_row=1,
        total_majors=2,
    )
    store.save(state=state, round=4, step=1)

    data = _collect_status_json(tmp_path)
    assert data["thread_id"] == ""
    assert data["stage"] == ""
    assert data["round"] == 0
    assert data["verdict"] == ""
    assert data["majors_in_a_row"] == 0
    assert data["total_majors"] == 0


def test_collect_status_json_ignores_checkpoint_envelope(tmp_path: Path) -> None:
    """CheckpointEnvelope 不能提供当前 round。"""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    db_path = cp_dir / "test.db"
    store = SQLiteCheckpointStore[CheckpointEnvelope](str(db_path))
    env = CheckpointEnvelope(round=3, step=1, status="running")
    store.save(env, round=3, step=1)

    data = _collect_status_json(tmp_path)
    assert data["round"] == 0
    assert data["thread_id"] == ""
    assert data["stage"] == ""
    assert data["verdict"] == ""
    assert data["majors_in_a_row"] == 0
    assert data["total_majors"] == 0


def test_collect_status_json_state_object_default_fallback(tmp_path: Path) -> None:
    """_collect_status_json when state is an object without expected attrs → defaults."""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    db_path = cp_dir / "test.db"
    store = SQLiteCheckpointStore[CheckpointEnvelope](str(db_path))
    env = CheckpointEnvelope(round=1, step=0, status="running")
    store.save(env, round=1, step=0)

    data = _collect_status_json(tmp_path)
    # All fields remain defaults without an EventStore projection.
    assert data["thread_id"] == ""
    assert data["round"] == 0
    assert data["verdict"] == ""
    assert data["majors_in_a_row"] == 0


# ============================================================
# Group 3: checkpoint databases are not status sources
# ============================================================


def test_collect_status_json_ignores_multiple_checkpoint_dbs(tmp_path: Path) -> None:
    """多个旧 checkpoint DB 也不能参与当前状态选择。"""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()

    # db1: round=2 (lower)
    store1 = SQLiteCheckpointStore[CheckpointEnvelope](str(cp_dir / "db1.db"))
    env1 = CheckpointEnvelope(round=2, step=1, status="running")
    store1.save(env1, round=2, step=1)

    # db2: round=10 (higher)
    store2 = SQLiteCheckpointStore[CheckpointEnvelope](str(cp_dir / "db2.db"))
    env2 = CheckpointEnvelope(round=10, step=1, status="running")
    store2.save(env2, round=10, step=1)

    data = _collect_status_json(tmp_path)
    assert data["round"] == 0


def test_collect_status_json_skips_event_store_database(tmp_path: Path) -> None:
    """统一 status 不应把新协议 EventStore 当作旧 checkpoint DB 读取。"""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    with SQLiteEventStore(cp_dir / "events.db"):
        pass
    with SQLiteCheckpointStore[CheckpointEnvelope](str(cp_dir / "checkpoints.db")) as store:
        store.save(CheckpointEnvelope(round=4, step=1, status="running"), round=4, step=1)

    data = _collect_status_json(tmp_path)

    assert data["round"] == 0


# ============================================================
# Group 4: _collect_status_json — corrupted + valid mixed
# ============================================================


def test_collect_status_json_ignores_corrupted_plus_valid_checkpoint_db(tmp_path: Path) -> None:
    """旧 checkpoint 的损坏或有效都不改变当前状态。"""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()

    # corrupted file
    (cp_dir / "corrupt.db").write_bytes(b"NOT A SQLITE FILE")

    # valid db with round=7
    store = SQLiteCheckpointStore[CheckpointEnvelope](str(cp_dir / "valid.db"))
    env = CheckpointEnvelope(round=7, step=1, status="running")
    store.save(env, round=7, step=1)

    data = _collect_status_json(tmp_path)
    assert data["round"] == 0


def test_collect_status_json_reads_checkpoint_from_read_only_state_dir(
    tmp_path: Path,
) -> None:
    """status 在宿主只读沙箱中不得以 WAL 写初始化打开 checkpoint."""
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    db_path = cp_dir / "readonly.db"
    state = EngineState(thread_id="readonly-thread", round=3)
    with SQLiteCheckpointStore[EngineState](str(db_path)) as store:
        store.save(state, round=3)

    db_path.chmod(0o444)
    cp_dir.chmod(0o555)
    try:
        data = _collect_status_json(tmp_path)
    finally:
        cp_dir.chmod(0o755)
        db_path.chmod(0o644)

    assert data["thread_id"] == ""
    assert data["round"] == 0


def test_collect_status_json_falls_back_when_temp_directory_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """临时目录不可用时也不能回退读取 checkpoint。"""
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.checkpoint import store as store_module

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    db_path = cp_dir / "readonly.db"
    with SQLiteCheckpointStore[EngineState](str(db_path)) as store:
        store.save(EngineState(thread_id="immutable-thread", round=4), round=4)

    def _no_temp_directory(*args, **kwargs):
        raise FileNotFoundError("no writable temporary directory")

    monkeypatch.setattr(
        store_module.tempfile,
        "TemporaryDirectory",
        _no_temp_directory,
    )

    data = _collect_status_json(tmp_path)

    assert data["thread_id"] == ""
    assert data["round"] == 0


# ============================================================
# Group 5: checkpoint history must not be exposed
# ============================================================


def test_collect_status_json_ignores_checkpoint_history(tmp_path: Path) -> None:
    """旧 checkpoint history 不能出现在当前 status。"""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.convergence import RoundHistory
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    db_path = cp_dir / "test.db"
    store = SQLiteCheckpointStore[CheckpointEnvelope](str(db_path))
    env = CheckpointEnvelope(round=1, step=1, status="running")
    history = [RoundHistory(round_id=42)]
    store.save(env, round=1, history=history)

    data = _collect_status_json(tmp_path)
    assert data["recent_history"] == []


def test_collect_status_json_ignores_checkpoint_history_semantics(tmp_path: Path) -> None:
    """checkpoint history 的语义字段不能污染当前 status。"""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.convergence import RoundHistory
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    db_path = cp_dir / "test.db"
    store = SQLiteCheckpointStore[CheckpointEnvelope](str(db_path))
    env = CheckpointEnvelope(round=1, step=1, status="running")
    history = [RoundHistory(round_id=1, semantic_satisfied=True)]
    store.save(env, round=1, history=history)

    data = _collect_status_json(tmp_path)
    assert data["recent_history"] == []


# ============================================================
# Group 6: _collect_status_json — no checkpoint dir
# ============================================================


def test_collect_status_json_no_checkpoint_dir_returns_defaults(tmp_path: Path) -> None:
    """_collect_status_json with no .ae-state → 7-field defaults."""
    data = _collect_status_json(tmp_path)
    assert data["thread_id"] == ""
    assert data["round"] == 0
    assert data["stage"] == ""
    assert data["verdict"] == ""
    assert data["majors_in_a_row"] == 0
    assert data["total_majors"] == 0
    assert data["recent_history"] == []


# ============================================================
# Group 7: register_status_command
# ============================================================


def test_register_status_command_registers_on_group() -> None:
    """register_status_command adds 'status' command to a Click group."""
    import click

    from auto_engineering.cli.status import register_status_command

    @click.group()
    def test_group() -> None:
        pass

    register_status_command(test_group)
    commands = list(test_group.commands)
    assert "status" in commands


# ============================================================
# Group 8: Text mode with checkpoint-only state
# ============================================================


def test_status_text_mode_with_checkpoints(runner: CliRunner, tmp_cwd: Path) -> None:
    """Status text mode with .ae-state present and populated."""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_cwd / ".ae-state"
    cp_dir.mkdir()
    store = SQLiteCheckpointStore[CheckpointEnvelope](str(cp_dir / "test.db"))
    env = CheckpointEnvelope(round=1, step=1, status="running")
    store.save(env, round=1, step=1)

    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "v2.0 Checkpoints" not in result.output


def test_status_text_mode_with_multiple_checkpoints(runner: CliRunner, tmp_cwd: Path) -> None:
    """Status text mode does not count checkpoint databases."""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_cwd / ".ae-state"
    cp_dir.mkdir()
    store1 = SQLiteCheckpointStore[CheckpointEnvelope](str(cp_dir / "db1.db"))
    env1 = CheckpointEnvelope(round=1, step=1, status="running")
    store1.save(env1, round=1, step=1)
    store2 = SQLiteCheckpointStore[CheckpointEnvelope](str(cp_dir / "db2.db"))
    env2 = CheckpointEnvelope(round=2, step=1, status="running")
    store2.save(env2, round=2, step=1)

    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "Checkpoints" not in result.output


# ============================================================
# Group 9: Edge cases
# ============================================================


def test_status_json_round_equal_in_different_dbs(tmp_path: Path) -> None:
    """同 round 的旧 checkpoint 仍不参与当前状态。"""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    store1 = SQLiteCheckpointStore[CheckpointEnvelope](str(cp_dir / "a.db"))
    env1 = CheckpointEnvelope(round=5, step=1, status="running")
    store1.save(env1, round=5, step=1)
    store2 = SQLiteCheckpointStore[CheckpointEnvelope](str(cp_dir / "b.db"))
    env2 = CheckpointEnvelope(round=5, step=1, status="running")
    store2.save(env2, round=5, step=1)

    data = _collect_status_json(tmp_path)
    assert data["round"] == 0


def test_status_json_empty_checkpoint_dir(tmp_path: Path) -> None:
    """_collect_status_json with empty .ae-state dir → defaults."""
    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir()
    # no .db files

    data = _collect_status_json(tmp_path)
    assert data["round"] == 0
    assert data["recent_history"] == []


def test_status_text_mode_no_project_env_warning(tmp_cwd: Path) -> None:
    """Status text mode without ae.toml → still completes with basic output."""
    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0


def test_status_text_mode_env_resolve_exception(tmp_cwd: Path) -> None:
    """Status text mode handles ProjectEnvironment._from_detection exception gracefully."""
    from unittest.mock import patch

    from auto_engineering.config.environment import ProjectEnvironment

    runner = CliRunner()
    with patch.object(
        ProjectEnvironment, "_from_detection", side_effect=RuntimeError("simulated error")
    ):
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "读取项目环境失败" in result.output


def test_status_text_mode_corrupted_db_counting(tmp_cwd: Path) -> None:
    """Status text mode ignores corrupted checkpoint databases."""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_cwd / ".ae-state"
    cp_dir.mkdir()
    # corrupted db (will trigger exception in SQLiteCheckpointStore constructor)
    (cp_dir / "corrupt.db").write_bytes(b"NOT A VALID SQLITE DATABASE")
    # valid db
    store = SQLiteCheckpointStore[CheckpointEnvelope](str(cp_dir / "valid.db"))
    env = CheckpointEnvelope(round=1, step=1, status="running")
    store.save(env, round=1, step=1)

    runner = CliRunner()
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
