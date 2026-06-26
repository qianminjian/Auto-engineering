"""v2.3 Phase I: Checkpoint v1.1 (JSON) → v2.0 (SQLite) 迁移测试.

设计来源: P1.5 审计 — v1.1 engine/checkpoint.py JSON 与 v2.0 loop/checkpoint.py SQLite 双轨独立.
目标: 提供 `ae checkpoint migrate v1-to-v2 --src <json> --dst <sqlite>` 单向迁移能力.

测试原则 (Phase A 教训):
- 严禁虚化 (mock), 必须真实集成 SQLiteCheckpointStore
- 单文件 pytest --timeout=60 跑 (避免内存爆炸)
- v1.1 JSON 模拟实际 checkpoint.load_checkpoint() 输出的结构 (LoopState.to_dict() + status)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner


# ============================================================
# I.1 load_v1_checkpoint
# ============================================================


def test_load_v1_checkpoint_parses_json(tmp_path: Path) -> None:
    """load_v1_checkpoint 能读 v1.1 JSON 文件并返回 dict."""
    from auto_engineering.checkpoint.migrate import load_v1_checkpoint

    v1_data = {
        "status": "running",
        "loop_state": {"round": 2, "step": 3, "requirement": "test"},
        "history": [],
    }
    src = tmp_path / "v1.json"
    src.write_text(json.dumps(v1_data))

    loaded = load_v1_checkpoint(src)
    assert loaded["status"] == "running"
    assert loaded["loop_state"]["round"] == 2
    assert loaded["loop_state"]["requirement"] == "test"
    assert loaded["history"] == []


def test_load_v1_checkpoint_handles_missing_optional_fields(tmp_path: Path) -> None:
    """load_v1_checkpoint 容忍缺失可选字段 (loop_state/history 缺失)."""
    from auto_engineering.checkpoint.migrate import load_v1_checkpoint

    v1_data = {"status": "drained"}
    src = tmp_path / "v1.json"
    src.write_text(json.dumps(v1_data))

    loaded = load_v1_checkpoint(src)
    assert loaded["status"] == "drained"
    # 缺失字段返回空 dict/list, 不抛异常
    assert "loop_state" not in loaded or loaded["loop_state"] == {}
    assert "history" not in loaded or loaded["history"] == []


# ============================================================
# I.2 migrate_v1_to_v2: LoopState 转换
# ============================================================


def test_migrate_v1_to_v2_converts_loop_state(tmp_path: Path) -> None:
    """migrate_v1_to_v2 把 v1.1 loop_state 转换为 v2.0 LoopState (round/step/status)."""
    from auto_engineering.checkpoint.migrate import migrate_v1_to_v2

    v1_data = {
        "status": "drained",
        "loop_state": {"round": 5, "step": 7, "requirement": "test req"},
        "history": [],
    }
    src = tmp_path / "v1.json"
    src.write_text(json.dumps(v1_data))
    dst = tmp_path / "v2.sqlite"

    cp_id = migrate_v1_to_v2(src, dst)

    # cp_id 非空 UUID-like
    assert isinstance(cp_id, str)
    assert len(cp_id) > 0

    # 验证 SQLite 存了正确的 LoopState
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    store = SQLiteCheckpointStore(str(dst))
    metas = store.list_all()
    assert len(metas) == 1
    assert metas[0].id == cp_id
    assert metas[0].round == 5
    assert metas[0].step == 7

    loaded = store.load(cp_id)
    # state 字段是 LoopState 实例 (deserialize_loop_state 重建)
    from auto_engineering.loop.state import LoopState

    assert isinstance(loaded.state, LoopState)
    assert loaded.state.round == 5
    assert loaded.state.step == 7
    assert loaded.state.status == "drained"


def test_migrate_v1_to_v2_converts_history(tmp_path: Path) -> None:
    """migrate_v1_to_v2 把 v1.1 history 转换为 v2.0 RoundHistory 列表."""
    from auto_engineering.checkpoint.migrate import migrate_v1_to_v2

    v1_data = {
        "status": "running",
        "loop_state": {"round": 3, "step": 0},
        "history": [
            {
                "round_id": 1,
                "files_changed": 5,
                "lines_added": 100,
                "lines_removed": 0,
                "gate_results": {"safety": True, "lint": False},
                "semantic_satisfied": None,
            },
            {
                "round_id": 2,
                "files_changed": 3,
                "lines_added": 50,
                "lines_removed": 10,
                "gate_results": {"safety": True, "lint": True},
                "semantic_satisfied": True,
            },
        ],
    }
    src = tmp_path / "v1.json"
    src.write_text(json.dumps(v1_data))
    dst = tmp_path / "v2.sqlite"

    cp_id = migrate_v1_to_v2(src, dst)

    # 验证 history 被保存
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    store = SQLiteCheckpointStore(str(dst))
    loaded = store.load(cp_id)
    assert len(loaded.history) == 2

    # 第 1 轮: round_id=1, files_changed=5
    h1 = loaded.history[0]
    assert h1["round_id"] == 1
    assert h1["files_changed"] == 5
    assert h1["lines_added"] == 100
    assert h1["lines_removed"] == 0
    assert h1["gate_results"] == {"safety": True, "lint": False}
    assert h1["semantic_satisfied"] is None

    # 第 2 轮: semantic_satisfied=True
    h2 = loaded.history[1]
    assert h2["round_id"] == 2
    assert h2["semantic_satisfied"] is True


def test_migrate_v1_to_v2_saves_to_sqlite(tmp_path: Path) -> None:
    """migrate_v1_to_v2 真存到 SQLite 文件 (不 mock)."""
    from auto_engineering.checkpoint.migrate import migrate_v1_to_v2

    v1_data = {"status": "running", "loop_state": {"round": 1, "step": 0}, "history": []}
    src = tmp_path / "v1.json"
    src.write_text(json.dumps(v1_data))
    dst = tmp_path / "v2.sqlite"

    cp_id = migrate_v1_to_v2(src, dst)

    # 文件存在
    assert dst.exists()
    assert dst.stat().st_size > 0

    # 直接打开 sqlite3 验证行数
    conn = sqlite3.connect(str(dst))
    try:
        row = conn.execute("SELECT id, round, step FROM checkpoints").fetchone()
        assert row is not None
        assert row[0] == cp_id
        assert row[1] == 1
        assert row[2] == 0
    finally:
        conn.close()


# ============================================================
# I.3 migrate_v1_to_v2: 完整 round-trip
# ============================================================


def test_migrate_round_trip_loadable(tmp_path: Path) -> None:
    """迁移后, store.load(cp_id) 能读回原数据 (round-trip OK)."""
    from auto_engineering.checkpoint.migrate import migrate_v1_to_v2
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    v1_data = {
        "status": "interrupted",
        "loop_state": {"round": 4, "step": 2, "requirement": "build X"},
        "history": [
            {
                "round_id": 1,
                "files_changed": 2,
                "lines_added": 20,
                "lines_removed": 5,
                "gate_results": {"safety": True},
                "semantic_satisfied": False,
            }
        ],
    }
    src = tmp_path / "v1.json"
    src.write_text(json.dumps(v1_data))
    dst = tmp_path / "v2.sqlite"

    cp_id = migrate_v1_to_v2(src, dst)

    # 重新打开 store (验证持久化)
    new_store = SQLiteCheckpointStore(str(dst))
    cp = new_store.load(cp_id)
    assert cp.id == cp_id
    assert cp.round == 4
    assert cp.step == 2
    from auto_engineering.loop.state import LoopState

    assert isinstance(cp.state, LoopState)
    assert cp.state.status == "interrupted"
    assert len(cp.history) == 1
    assert cp.history[0]["files_changed"] == 2


# ============================================================
# I.4 CLI: ae checkpoint migrate v1-to-v2
# ============================================================


def test_cli_checkpoint_v2_migrate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI ae checkpoint v2 migrate 子命令能调用 migrate_v1_to_v2 并输出 checkpoint_id."""
    from auto_engineering.cli import main

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
    monkeypatch.chdir(tmp_path)

    # 准备 v1.1 JSON
    v1_data = {
        "status": "running",
        "loop_state": {"round": 2, "step": 1, "requirement": "x"},
        "history": [
            {
                "round_id": 1,
                "files_changed": 1,
                "lines_added": 10,
                "lines_removed": 0,
                "gate_results": {"safety": True},
                "semantic_satisfied": None,
            }
        ],
    }
    src = tmp_path / "v1.json"
    src.write_text(json.dumps(v1_data))
    dst = tmp_path / "v2.sqlite"

    runner = CliRunner()
    result = runner.invoke(main, ["checkpoint", "v2", "migrate", str(src), str(dst)])
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert "Migrated" in result.output

    # 验证 SQLite 真的存了
    assert dst.exists()
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    store = SQLiteCheckpointStore(str(dst))
    metas = store.list_all()
    assert len(metas) == 1
    assert metas[0].round == 2