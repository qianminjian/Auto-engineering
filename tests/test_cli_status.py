"""ae status CLI 测试 (v5.0 §B13.2 /status stdout JSON 契约).

RED marker 测试 — 验证 status 命令输出 7 字段 JSON 契约 + 边界场景.

测试覆盖:
- 状态查询字段契约和只读语义
- 命令注册 (uv run ae status --format json)
- 边界场景: 缺失 EventStore、损坏 EventStore
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
        "tick",
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
    """thread_id 应为字符串 (无 EventStore 时为空串)."""
    result = runner.invoke(main, ["status", "--format", "json"])
    data = json.loads(result.output)
    assert isinstance(data["thread_id"], str), f"thread_id 应为 str, 实际 {type(data['thread_id'])}"


def test_status_tick_in_range(runner: CliRunner, tmp_cwd: Path) -> None:
    """tick 应为非负整数 (无 EventStore 时为 0)."""
    result = runner.invoke(main, ["status", "--format", "json"])
    data = json.loads(result.output)
    assert isinstance(data["tick"], int), f"tick 应为 int, 实际 {type(data['tick'])}"
    assert data["tick"] >= 0, f"tick 应 ≥ 0, 实际 {data['tick']}"


def test_status_stage_in_valid_values(runner: CliRunner, tmp_cwd: Path) -> None:
    """stage 应为合法 enum 值或空串 (无 EventStore 时为空)."""
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




def test_status_command_registered_in_cli_main(runner: CliRunner, tmp_cwd: Path) -> None:
    """ae status 命令必须注册到 main group."""
    result = runner.invoke(main, ["--help"])
    assert "status" in result.output, "ae status 命令未注册"


def test_status_handles_missing_event_store(runner: CliRunner, tmp_cwd: Path) -> None:
    """缺失 .ae-state 目录: 输出 7 字段默认 JSON (无 error)."""
    # tmp_cwd 不创建 .ae-state
    result = runner.invoke(main, ["status", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    # 7 字段应全在 (默认值)
    expected_keys = {
        "thread_id", "tick", "stage", "verdict",
        "majors_in_a_row", "total_majors", "recent_history",
    }
    assert set(data.keys()) == expected_keys
    # recent_history 应为空列表
    assert data["recent_history"] == []
    assert data["tick"] == 0


def test_status_handles_corrupted_event_store(runner: CliRunner, tmp_cwd: Path) -> None:
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
        "thread_id", "tick", "stage", "verdict",
        "majors_in_a_row", "total_majors", "recent_history",
    }
    assert set(data.keys()) == expected_keys
    # 没有有效 EventStore → 默认值
    assert data["recent_history"] == []
    assert data["tick"] == 0


def test_status_reports_corrupted_event_store_without_legacy_fallback(
    tmp_cwd: Path,
) -> None:
    """EventStore 损坏时必须报告恢复要求，不能展示旧状态。"""

    state_dir = tmp_cwd / ".ae-state"
    state_dir.mkdir(exist_ok=True)
    (state_dir / "events.db").write_bytes(b"NOT A SQLITE FILE")
    payload = _collect_status_json(tmp_cwd)
    assert payload["error_code"] == "EVENT_STORE_UNAVAILABLE"
    assert payload["recovery_required"] is True
    assert payload["thread_id"] == ""


def test_status_json_reads_event_store_projection(tmp_cwd: Path) -> None:
    """当前 status 必须读取事件投影，而不是只验证空状态路径。"""
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.events import LoopEvent, LoopEventType

    thread_id = "event-status-thread"
    state = EngineState(
        thread_id=thread_id,
        requirement="事件状态",
        current_stage="developer",
        total_majors=2,
    )
    event = LoopEvent.create(
        thread_id=thread_id,
        sequence=0,
        event_type=LoopEventType.LOOP_INITIALIZED,
        payload={"state": state.to_dict()},
        correlation_id=thread_id,
    )
    ae_state = tmp_cwd / ".ae-state"
    ae_state.mkdir(exist_ok=True)
    with SQLiteEventStore(ae_state / "events.db") as events:
        events.commit_tick(
            events=[event],
            state=state,
            action={"thread_id": thread_id, "message_id": "event-status-action"},
        )

    payload = _collect_status_json(tmp_cwd)
    assert payload["thread_id"] == thread_id
    assert payload["stage"] == "developer"
    assert payload["tick"] == 0
    assert payload["total_majors"] == 2


def test_status_prefers_older_unfinished_thread_over_newer_terminal_thread(
    tmp_cwd: Path,
) -> None:
    """终态新 thread 不能掩盖仍需恢复的旧 thread。"""
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.events import LoopEvent, LoopEventType

    state_dir = tmp_cwd / ".ae-state"
    state_dir.mkdir(exist_ok=True)
    with SQLiteEventStore(state_dir / "events.db") as events:
        unfinished = EngineState(
            thread_id="unfinished-thread",
            current_stage="developer",
        )
        events.commit_tick(
            events=[LoopEvent.create(
                thread_id=unfinished.thread_id,
                sequence=0,
                event_type=LoopEventType.LOOP_INITIALIZED,
                payload={"state": unfinished.to_dict()},
                correlation_id=unfinished.thread_id,
            )],
            state=unfinished,
            action={"thread_id": unfinished.thread_id, "message_id": "action-old"},
        )
        finished = EngineState(
            thread_id="finished-thread",
            current_stage="critic",
        )
        events.commit_tick(
            events=[LoopEvent.create(
                thread_id=finished.thread_id,
                sequence=0,
                event_type=LoopEventType.LOOP_INITIALIZED,
                payload={"state": finished.to_dict()},
                correlation_id=finished.thread_id,
            )],
            state=finished,
            action={"thread_id": finished.thread_id, "message_id": "action-new"},
        )
        events.append([LoopEvent.create(
            thread_id=finished.thread_id,
            sequence=1,
            event_type=LoopEventType.LOOP_COMPLETED,
            payload={"status": "TERMINAL"},
            correlation_id=finished.thread_id,
        )])

    payload = _collect_status_json(tmp_cwd)
    assert payload["thread_id"] == "unfinished-thread"
    assert payload["stage"] == "developer"


def test_status_projects_terminal_event_and_usage_from_event_store(tmp_cwd: Path) -> None:
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.events import LoopEvent, LoopEventType

    thread_id = "terminal-status-thread"
    state = EngineState(thread_id=thread_id, current_stage="critic")
    state_dir = tmp_cwd / ".ae-state"
    state_dir.mkdir(exist_ok=True)
    with SQLiteEventStore(state_dir / "events.db") as events:
        events.commit_tick(
            events=[LoopEvent.create(
                thread_id=thread_id,
                sequence=0,
                event_type=LoopEventType.LOOP_INITIALIZED,
                payload={"state": state.to_dict()},
                correlation_id=thread_id,
            )],
            state=state,
            action={"thread_id": thread_id, "message_id": "terminal-action"},
        )
        events.append([LoopEvent.create(
                thread_id=thread_id,
                sequence=1,
                event_type=LoopEventType.LOOP_COMPLETED,
                payload={"status": "TERMINAL"},
                correlation_id=thread_id,
        )])
        events.append([LoopEvent.create(
                thread_id=thread_id,
                sequence=2,
                event_type=LoopEventType.USAGE_RECORDED,
                payload={"usage": {
                    "session_id": "session-1", "tick": 1, "stage": "critic",
                    "worker": "coordinator", "input_units": 10,
                    "cache_read_units": 0, "cache_write_units": 0, "output_units": 5,
                    "provider": "test", "model": "test-model",
                    "usage_source": "test", "estimated": False,
                }},
                correlation_id=thread_id,
        )])

    payload = _collect_status_json(tmp_cwd)
    assert payload["stage"] == "done"
    assert "event_metrics" in payload
    assert payload["event_metrics"]["usage"]["input_units"] == 10


def test_status_verbose_reads_progress_tree_from_event_projection(tmp_cwd: Path) -> None:
    from auto_engineering.engine.progress_tree import ProgressTree
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.events import LoopEvent, LoopEventType

    state = EngineState(thread_id="progress-thread", current_stage="developer")
    state.progress_tree_json = json.dumps(
        ProgressTree(
            system_id="system-1",
            system_name="系统",
            design_doc_path=None,
        ).to_dict()
    )
    state_dir = tmp_cwd / ".ae-state"
    state_dir.mkdir(exist_ok=True)
    with SQLiteEventStore(state_dir / "events.db") as events:
        events.commit_tick(
            events=[LoopEvent.create(
                thread_id=state.thread_id,
                sequence=0,
                event_type=LoopEventType.LOOP_INITIALIZED,
                payload={"state": state.to_dict()},
                correlation_id=state.thread_id,
            )],
            state=state,
            action={"thread_id": state.thread_id, "message_id": "progress-action"},
        )

    from auto_engineering.cli.status import _load_progress_summary

    summary = _load_progress_summary(tmp_cwd)
    assert summary["total_tasks"] == 0
    assert summary["completion_pct"] == 0.0


def test_status_verbose_handles_invalid_progress_projection(tmp_cwd: Path) -> None:
    from auto_engineering.cli.status import _load_progress_summary

    state_dir = tmp_cwd / ".ae-state"
    state_dir.mkdir()
    (state_dir / "events.db").write_bytes(b"invalid")

    summary = _load_progress_summary(tmp_cwd)
    assert summary["node_count"] == 0


def test_status_text_mode_reports_environment_detection_failure(
    runner: CliRunner,
    tmp_cwd: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "auto_engineering.cli.status.ProjectEnvironment._from_detection",
        classmethod(lambda cls, root: (_ for _ in ()).throw(RuntimeError("probe failed"))),
    )

    result = runner.invoke(main, ["status"])

    assert result.exit_code == 0
    assert "读取项目环境失败" in result.output


# ============================================================
# 文本模式 (兼容老行为)
# ============================================================


def test_status_text_mode_without_event_store(runner: CliRunner, tmp_cwd: Path) -> None:
    """默认 text 模式 (无 EventStore) 不应崩溃."""
    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    # 应至少输出 "当前目录"
    assert "当前目录" in result.output or "项目" in result.output


def test_status_verbose_reads_only_event_store_progress(
    runner: CliRunner,
    tmp_cwd: Path,
) -> None:
    result = runner.invoke(main, ["status", "--verbose"])

    assert result.exit_code == 0
    assert "暂无进度数据" in result.output


def test_status_json_verbose_includes_event_store_progress_shape(
    runner: CliRunner,
    tmp_cwd: Path,
) -> None:
    result = runner.invoke(main, ["status", "--format", "json", "--verbose"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["progress_tree"]["node_count"] == 0
