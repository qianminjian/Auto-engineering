"""单一 Loop 运行时的架构回归约束。

这些断言针对生产入口，而不是历史迁移资料。旧 Supervisor、Round/Convergence
和 SQLite checkpoint 不能通过公共 CLI 或主编排器重新进入运行时。
"""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_retired_runtime_modules_are_absent() -> None:
    retired = (
        PROJECT_ROOT / "auto_engineering" / "loop" / "checkpoint",
        PROJECT_ROOT / "auto_engineering" / "loop" / "convergence.py",
        PROJECT_ROOT / "auto_engineering" / "loop" / "legacy_event_adapter.py",
        PROJECT_ROOT / "auto_engineering" / "cli" / "legacy_action_recovery.py",
    )
    assert all(not path.exists() for path in retired)


def _source(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_tick_orchestrator_has_one_event_store_driven_state_path() -> None:
    source = _source("auto_engineering/loop/tick_orchestrator.py")

    forbidden = (
        "CheckpointManager",
        "SQLiteCheckpointStore",
        "ConvergenceJudge",
        "ConvergenceConfig",
        "RoundHistory",
        "restore_from_checkpoint",
        "_round_history",
        "_checkpoint_store",
    )
    assert not [name for name in forbidden if name in source]


def test_public_cli_exposes_only_tick_and_event_store_recovery() -> None:
    source = _source("auto_engineering/cli/__init__.py")
    dev_loop_source = _source("auto_engineering/cli/dev_loop.py")

    assert "--max-rounds" not in source
    assert "--import-checkpoint" not in source
    assert "run_tick_import_checkpoint" not in source
    assert "restore_from_checkpoint" not in dev_loop_source
    assert "SQLiteCheckpointStore" not in dev_loop_source
    assert "events.append_new(" not in dev_loop_source


def test_event_store_does_not_embed_legacy_round_or_checkpoint_import_model() -> None:
    source = _source("auto_engineering/loop/event_store.py")

    assert "def load_round_history" not in source
    assert "def import_checkpoint" not in source
    assert "checkpoint_imports" not in source
    assert "def append_new" not in source


def test_production_does_not_bypass_single_tick_event_store_commit() -> None:
    """生产运行时不得重新接入 raw EventStore append 旁路。"""

    forbidden_calls = (
        "event_store.append(",
        "_event_store.append(",
    )
    violations: list[str] = []
    for path in (PROJECT_ROOT / "auto_engineering").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in forbidden_calls:
            if token in source:
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: {token}")
    assert violations == []


def test_loop_package_does_not_export_retired_runtime_models() -> None:
    source = _source("auto_engineering/loop/__init__.py")

    for name in (
        "Checkpoint",
        "SQLiteCheckpointStore",
        "CheckpointManager",
        "ConvergenceJudge",
        "RoundHistory",
    ):
        assert name not in source


def test_all_production_python_sources_have_no_retired_loop_imports() -> None:
    forbidden = (
        "auto_engineering.host.supervisor",
        "auto_engineering.loop.checkpoint",
        "CheckpointManager",
        "SQLiteCheckpointStore",
        "RoundHistory",
        "ConvergenceJudge",
        "ConvergenceConfig",
        "round_history",
        "round_number",
        "_round_counter",
        "HARD_LIMIT",
        "latest_thread_for_event",
        "LoopState",
        "_register_alias",
        "agent_type",
        "ruff_bin",
        "mypy_bin",
        "pytest_bin",
    )
    violations: list[str] = []
    for path in (PROJECT_ROOT / "auto_engineering").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: {token}")
    assert violations == []


def test_production_has_one_canonical_event_store_definition() -> None:
    definitions: list[tuple[str, str]] = []
    for path in (PROJECT_ROOT / "auto_engineering").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        definitions.extend(
            (
                str(path.relative_to(PROJECT_ROOT)),
                node.name,
            )
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and "EventStore" in node.name
        )
    assert definitions == [("auto_engineering/loop/event_store.py", "SQLiteEventStore")]


def test_engine_state_exposes_one_owned_write_api() -> None:
    source = _source("auto_engineering/engine/state.py")

    assert "def write_field(" in source
    assert "def set_channels(" not in source


def test_orchestrator_exposes_one_event_store_restore_api() -> None:
    source = _source("auto_engineering/loop/tick_orchestrator.py")

    assert "def restore_from_event_store(" in source
    assert "def restore(" not in source


def test_active_runtime_has_no_compatibility_alias_for_gate_runner() -> None:
    source = _source("auto_engineering/loop/tick_orchestrator.py")

    assert "backward-compat alias" not in source
    assert "GateRunner =" not in source


def test_host_continuation_boundary_cannot_become_a_second_loop() -> None:
    continuation = _source("auto_engineering/host/continuation_driver.py")
    adapter = _source("scripts/ae-host-run")

    for token in (
        "Supervisor",
        "SQLiteEventStore",
        "Checkpoint",
        "Convergence",
        "TickOrchestrator",
        "--tick",
        "--init",
    ):
        assert token not in continuation
    assert "auto_engineering.host.continuation_driver" in adapter
    assert "dev-loop --status" in adapter
    assert "dev-loop --tick" not in adapter


def test_loop_core_does_not_import_host_private_transcript_parser() -> None:
    source = _source("auto_engineering/loop/tick_orchestrator.py")

    assert "metrics.transcript_parser" not in source
    assert "usage_collector_for" in source


def test_host_watchdog_uses_canonical_event_store_reader() -> None:
    """Watchdog 不得复制 EventStore 的 SQLite schema/query。"""
    source = _source("scripts/ae-host-run")

    assert "from auto_engineering.loop.event_store import SQLiteEventStore" in source
    assert "event_store.semantic_signature()" in source
    assert "import sqlite3" not in source
    assert "loop_events" not in source
    assert "action_snapshots" not in source
    assert "protocol_result_replays" not in source
    assert "effect_receipts" not in source


def test_current_entry_docs_do_not_reintroduce_round_runtime_contract() -> None:
    """当前宿主入口只能描述 Tick，不得让退役 Round 重新成为操作语义。"""

    current_docs = (
        "commands/status.md",
        "commands/dev-loop.md",
        "commands/code-review.md",
        "docs/api-reference.md",
    )
    forbidden = ("HARD_LIMIT", "round_index", "轮次上限", "Rounds")
    violations = []
    for relative in current_docs:
        source = _source(relative)
        for token in forbidden:
            if token in source:
                violations.append(f"{relative}: {token}")
    assert violations == []


def test_api_reference_describes_thread_scoped_resume() -> None:
    """恢复必须明确绑定 thread，避免被误解为第二个循环驱动器。"""

    source = _source("docs/api-reference.md")
    assert "ae-run dev-loop --resume <thread-id>" in source
    assert "--resume\n" not in source
    assert "不创建 Worker，也不调用 Tick" in source
