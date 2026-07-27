"""ae status CLI 测试 (v5.0 §B13.2 /status stdout JSON 契约).

RED marker 测试 — 验证 status 命令输出 7 字段 JSON 契约 + 边界场景.

测试覆盖:
- 7 字段契约 (thread_id / round / stage / verdict / majors_in_a_row / total_majors / recent_history)
- recent_history 最多 5 条 + 按 round_id DESC
- 命令注册 (uv run ae status --format json)
- 边界场景: 缺失 checkpoint, corrupted state_db
"""

from __future__ import annotations

import json
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
    """Click 测试 runner."""
    return CliRunner()


@pytest.fixture
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """临时目录作为 cwd (status 默认读 cwd/.ae-state)."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ============================================================
# 7 字段 JSON 契约
# ============================================================


def test_status_json_7_fields_required(runner: CliRunner, tmp_cwd: Path) -> None:
    """v5.0 §B13.2: ae status --format json 输出必须含 7 字段."""
    result = runner.invoke(main, ["status", "--format", "json"])
    assert result.exit_code == 0, f"status 命令非 0 退出: {result.output}"

    data = json.loads(result.output)
    expected_keys = {
        "thread_id",
        "round",
        "stage",
        "verdict",
        "majors_in_a_row",
        "total_majors",
        "recent_history",
    }
    assert set(data.keys()) == expected_keys, (
        f"status JSON 字段不匹配: 缺 {expected_keys - set(data.keys())}, "
        f"多 {set(data.keys()) - expected_keys}"
    )


def test_status_thread_id_format(runner: CliRunner, tmp_cwd: Path) -> None:
    """thread_id 应为字符串 (无 checkpoint 时为空串)."""
    result = runner.invoke(main, ["status", "--format", "json"])
    data = json.loads(result.output)
    assert isinstance(data["thread_id"], str), f"thread_id 应为 str, 实际 {type(data['thread_id'])}"


def test_status_round_in_range(runner: CliRunner, tmp_cwd: Path) -> None:
    """round 应为非负整数 (无 checkpoint 时为 0)."""
    result = runner.invoke(main, ["status", "--format", "json"])
    data = json.loads(result.output)
    assert isinstance(data["round"], int), f"round 应为 int, 实际 {type(data['round'])}"
    assert data["round"] >= 0, f"round 应 ≥ 0, 实际 {data['round']}"


def test_status_stage_in_valid_values(runner: CliRunner, tmp_cwd: Path) -> None:
    """stage 应为合法 enum 值或空串 (无 checkpoint 时为空)."""
    result = runner.invoke(main, ["status", "--format", "json"])
    data = json.loads(result.output)
    # v5.0 §B1.1: current_stage ∈ {"", "architect", "developer", "critic"}
    valid_stages = {"", "architect", "developer", "critic"}
    assert data["stage"] in valid_stages, f"stage 非法值: {data['stage']!r}"


def test_status_verdict_in_valid_values(runner: CliRunner, tmp_cwd: Path) -> None:
    """verdict 应为合法 enum 值或空串."""
    result = runner.invoke(main, ["status", "--format", "json"])
    data = json.loads(result.output)
    # v5.0 §B1.1: verdict ∈ {"", "APPROVE", "MAJOR"}
    valid_verdicts = {"", "APPROVE", "MAJOR"}
    assert data["verdict"] in valid_verdicts, f"verdict 非法值: {data['verdict']!r}"


def test_status_majors_in_a_row_non_negative(runner: CliRunner, tmp_cwd: Path) -> None:
    """majors_in_a_row 应为非负整数."""
    result = runner.invoke(main, ["status", "--format", "json"])
    data = json.loads(result.output)
    assert isinstance(data["majors_in_a_row"], int)
    assert data["majors_in_a_row"] >= 0


def test_status_total_majors_non_negative(runner: CliRunner, tmp_cwd: Path) -> None:
    """total_majors 应为非负整数."""
    result = runner.invoke(main, ["status", "--format", "json"])
    data = json.loads(result.output)
    assert isinstance(data["total_majors"], int)
    assert data["total_majors"] >= 0


# ============================================================
# recent_history 边界
# ============================================================


def test_status_recent_history_max_5(tmp_cwd: Path) -> None:
    """recent_history 最多 5 条 (v5.0 §B13.2 spec)."""
    # 构造含 8 条 history 的 checkpoint
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.convergence import RoundHistory
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_cwd / ".ae-state"
    cp_dir.mkdir()
    db_path = cp_dir / "test.db"
    env = CheckpointEnvelope(round=8, step=1, status="running")
    history = [
        RoundHistory(round_id=i, files_changed=i, lines_added=i * 2)
        for i in range(1, 9)  # 8 条
    ]
    with SQLiteCheckpointStore[CheckpointEnvelope](str(db_path)) as store:
        store.save(env, round=8, history=history)

    data = _collect_status_json(tmp_cwd)
    assert isinstance(data["recent_history"], list)
    assert len(data["recent_history"]) <= 5, (
        f"recent_history 应 ≤ 5, 实际 {len(data['recent_history'])}"
    )


def test_status_recent_history_round_id_desc(tmp_cwd: Path) -> None:
    """recent_history 应按 round_id DESC 排序."""
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
    from auto_engineering.loop.convergence import RoundHistory
    from auto_engineering.loop.state import CheckpointEnvelope

    cp_dir = tmp_cwd / ".ae-state"
    cp_dir.mkdir()
    db_path = cp_dir / "test.db"
    env = CheckpointEnvelope(round=3, step=1, status="running")
    history = [
        RoundHistory(round_id=1, files_changed=1),
        RoundHistory(round_id=2, files_changed=2),
        RoundHistory(round_id=3, files_changed=3),
    ]
    with SQLiteCheckpointStore[CheckpointEnvelope](str(db_path)) as store:
        store.save(env, round=3, history=history)

    data = _collect_status_json(tmp_cwd)
    round_ids = [h["round_id"] for h in data["recent_history"]]
    assert round_ids == sorted(round_ids, reverse=True), (
        f"recent_history 应按 round_id DESC, 实际 {round_ids}"
    )


# ============================================================
# 命令注册 + 边界
# ============================================================


def test_status_command_registered_in_cli_main(runner: CliRunner, tmp_cwd: Path) -> None:
    """ae status 命令必须注册到 main group."""
    result = runner.invoke(main, ["--help"])
    assert "status" in result.output, "ae status 命令未注册"


def test_status_handles_missing_checkpoint(runner: CliRunner, tmp_cwd: Path) -> None:
    """缺失 .ae-state 目录: 输出 7 字段默认 JSON (无 error)."""
    # tmp_cwd 不创建 .ae-state
    result = runner.invoke(main, ["status", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    # 7 字段应全在 (默认值)
    expected_keys = {
        "thread_id", "round", "stage", "verdict",
        "majors_in_a_row", "total_majors", "recent_history",
    }
    assert set(data.keys()) == expected_keys
    # recent_history 应为空列表
    assert data["recent_history"] == []
    assert data["round"] == 0


def test_status_handles_corrupted_state_db(runner: CliRunner, tmp_cwd: Path) -> None:
    """.ae-state/*.db 文件损坏: status 不崩溃, 输出默认 JSON."""
    cp_dir = tmp_cwd / ".ae-state"
    cp_dir.mkdir()
    # 写入非法 SQLite 内容
    (cp_dir / "corrupt.db").write_bytes(b"NOT A SQLITE FILE")

    result = runner.invoke(main, ["status", "--format", "json"])
    # 不应崩溃, exit 0
    assert result.exit_code == 0, f"corrupted db 导致崩溃: {result.output}"

    data = json.loads(result.output)
    expected_keys = {
        "thread_id", "round", "stage", "verdict",
        "majors_in_a_row", "total_majors", "recent_history",
    }
    assert set(data.keys()) == expected_keys
    # 没有有效 checkpoint → 默认值
    assert data["recent_history"] == []
    assert data["round"] == 0


# ============================================================
# 文本模式 (兼容老行为)
# ============================================================


def test_status_text_mode_no_checkpoint(runner: CliRunner, tmp_cwd: Path) -> None:
    """默认 text 模式 (无 checkpoint) 不应崩溃."""
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    # 应至少输出 "当前目录"
    assert "当前目录" in result.output or "项目" in result.output


# ============================================================
# P1-6 回归: SQLiteCheckpointStore 资源泄漏 (2026-07-25 独立审计)
# ============================================================


def _make_spy_store():
    """构造 spy store 工厂: 强引用抑制 __del__ 兜底, 使 close 断言稳定.

    历史 bug: status.py 循环内创建 store 从不 close(), 依赖 __del__ 析构
    兜底 — CPython 引用计数下 __del__ 会掩盖泄漏, 故测试用强引用抑制它,
    只有显式 close (with 语句) 才计入 closed。
    """
    import auto_engineering.loop.checkpoint as checkpoint_mod
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    created: list = []
    closed: list[bool] = []

    class _SpyStore(SQLiteCheckpointStore):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)  # 强引用 → __del__ 不触发

        def close(self) -> None:
            closed.append(True)
            super().close()

    return checkpoint_mod, SQLiteCheckpointStore, _SpyStore, created, closed


def test_load_progress_summary_closes_checkpoint_store(
    tmp_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-6 回归: _load_progress_summary 用后应显式关闭 store."""
    checkpoint_mod, real_store, spy_store, _created, closed = _make_spy_store()

    ae_state = tmp_cwd / ".ae-state"
    ae_state.mkdir(exist_ok=True)
    with real_store(str(ae_state / "thread.db")):
        pass  # 空 db, load_latest 返回 None

    monkeypatch.setattr(checkpoint_mod, "SQLiteCheckpointStore", spy_store)

    from auto_engineering.cli.status import _load_progress_summary
    _load_progress_summary(tmp_cwd)

    assert closed, (
        "_load_progress_summary 未显式关闭 SQLiteCheckpointStore"
        "(P1-6: 连接泄漏回归)"
    )


def test_status_command_closes_checkpoint_stores(
    runner: CliRunner, tmp_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-6 回归: status 命令 checkpoint 计数路径用后应显式关闭 store."""
    checkpoint_mod, real_store, spy_store, _created, closed = _make_spy_store()

    ae_state = tmp_cwd / ".ae-state"
    ae_state.mkdir(exist_ok=True)
    with real_store(str(ae_state / "thread.db")):
        pass

    monkeypatch.setattr(checkpoint_mod, "SQLiteCheckpointStore", spy_store)

    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0, result.output
    assert closed, (
        "status 命令 checkpoint 计数路径未显式关闭 SQLiteCheckpointStore"
        "(P1-6: 连接泄漏回归)"
    )


def test_collect_status_json_closes_checkpoint_stores(
    tmp_cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归: JSON 状态收集路径用后应显式关闭每个 checkpoint store."""
    checkpoint_mod, real_store, spy_store, _created, closed = _make_spy_store()

    ae_state = tmp_cwd / ".ae-state"
    ae_state.mkdir(exist_ok=True)
    with real_store(str(ae_state / "thread.db")):
        pass

    monkeypatch.setattr(checkpoint_mod, "SQLiteCheckpointStore", spy_store)

    _collect_status_json(tmp_cwd)

    assert closed, "_collect_status_json 未显式关闭 SQLiteCheckpointStore"


def test_load_progress_summary_parses_progress_tree_json(tmp_cwd: Path) -> None:
    """回归: _load_progress_summary 应解析 checkpoint 中的 progress_tree_json.

    历史 bug (2026-07-25 审计发现, mypy 揭示): 调用 ProgressTree.from_json
    (该方法不存在, 仅有 from_dict) → 必抛 AttributeError 被 except 静默吞噬
    → 进度摘要恒返回全零默认值 (Phase 40 T180 功能失效)。
    """
    import json

    from auto_engineering.engine.progress_tree import ProgressTree
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    tree = ProgressTree.from_batch_plan(
        [{
            "batch_id": "B1", "design_section": "B1", "component": "Foo",
            "tasks": [{"id": "T1", "description": "实现 foo",
                       "module_ref": "§B1", "file_targets": ["foo.py"]}],
        }],
        requirement="回归测试需求",
    )

    ae_state = tmp_cwd / ".ae-state"
    ae_state.mkdir(exist_ok=True)
    state = EngineState(requirement="回归测试需求", current_stage="developer")
    state.progress_tree_json = json.dumps(tree.to_dict(), ensure_ascii=False)
    with SQLiteCheckpointStore(str(ae_state / "thread.db")) as store:
        store.save(state, round=1, history=[], step=1)

    from auto_engineering.cli.status import _load_progress_summary
    summary = _load_progress_summary(tmp_cwd)

    assert summary["total_tasks"] > 0, (
        f"progress_tree 摘要应为非默认值 (from_json→from_dict 回归), "
        f"实际: {summary}"
    )
