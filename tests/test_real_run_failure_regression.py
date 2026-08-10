"""T303：Claude Code 146-Tick 真跑事故的最小可复现轨迹。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.gates.base import SubprocessResult
from auto_engineering.gates.contract import ContractGate
from auto_engineering.gates.test_gate import TestGate as _TestGate
from auto_engineering.loop.actions import validate_result_format
from auto_engineering.loop.guardrails.stateful import aggregate_files_sha
from auto_engineering.loop.tick_gate_runner import TickGateRunner

FIXTURE = (
    Path(__file__).parent / "fixtures" / "golden" / "long_session_plan_patch.json"
)


def _batch(batch_id: str) -> dict:
    return {
        "batch_id": batch_id,
        "component": batch_id,
        "tasks": [{"id": f"{batch_id}-T1", "description": "x", "file_targets": []}],
    }


def test_plan_patch_preserves_completed_batches_and_activates_b27() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    completed = {
        f"B{i}" for i in range(
            fixture["completed_batch_range"][0],
            fixture["completed_batch_range"][1] + 1,
        )
    }
    base = [_batch(f"B{i}") for i in range(1, 27)]
    state = BatchState.from_batch_plan(base)

    patched = state.apply_plan_patch(
        base_revision=fixture["base_revision"],
        active_revision=fixture["base_revision"],
        add_batches=[_batch(f"B{i}") for i in range(27, 33)],
        completed_batch_ids=completed,
    )

    assert patched.current_batch_id() == fixture["expected_active_batch"]
    assert completed.isdisjoint({patched.current_batch_id()})


def test_progress_tree_rejects_done_tasks_above_new_total() -> None:
    tree = ProgressTree.from_batch_plan([_batch("B1")], "incident")
    component = next(node for node in tree.nodes.values() if node.level == "component")
    component.done_tasks = 85

    try:
        tree.sync_from_batch_plan([_batch("B1")])
    except ValueError as exc:
        assert "done_tasks" in str(exc)
    else:
        raise AssertionError("非法进度投影必须被拒绝")


def test_vitest_zero_tests_nonzero_exit_fails(monkeypatch, tmp_path: Path) -> None:
    import auto_engineering.gates.test_gate as test_gate_module

    monkeypatch.setattr(
        test_gate_module,
        "run_gate_command",
        lambda *_args, **_kwargs: SubprocessResult(
            returncode=5,
            stdout="collected 0 items",
            stderr="",
        ),
    )

    verdict = _TestGate(test_runner_bin="vitest").run(tmp_path)

    assert verdict.passed is False
    assert verdict.skipped is False


def test_nonempty_project_rejects_empty_gate_snapshot(tmp_path: Path) -> None:
    (tmp_path / "src.ts").write_text("export const value = 1;\n", encoding="utf-8")
    runner = TickGateRunner(
        tmp_path,
        gate_runner=lambda *_args, **_kwargs: {
            "gate_summary": {"test": {"passed": True, "message": "ok"}}
        },
    )

    try:
        runner.run([])
    except ValueError as exc:
        assert "快照" in str(exc)
    else:
        raise AssertionError("非空项目不得接受空文件快照")


def test_gate_rejects_file_changes_during_verification(tmp_path: Path) -> None:
    source = tmp_path / "src.ts"
    source.write_text("before\n", encoding="utf-8")

    def mutate_during_gate(*_args, **_kwargs):
        source.write_text("after\n", encoding="utf-8")
        return {"gate_summary": {"test": {"passed": True, "message": "ok"}}}

    runner = TickGateRunner(tmp_path, gate_runner=mutate_during_gate)

    try:
        runner.run(["src.ts"])
    except ValueError as exc:
        assert "变化" in str(exc)
    else:
        raise AssertionError("验证期间文件变化必须被拒绝")


def test_snapshot_rejects_path_escape(tmp_path: Path) -> None:
    try:
        aggregate_files_sha(["../outside.txt"], tmp_path)
    except ValueError as exc:
        assert "路径" in str(exc)
    else:
        raise AssertionError("快照路径不得逃逸项目根")


def test_gate_result_declares_selected_files(tmp_path: Path) -> None:
    (tmp_path / "src.ts").write_text("stable\n", encoding="utf-8")
    runner = TickGateRunner(
        tmp_path,
        gate_runner=lambda *_args, **_kwargs: {
            "gate_summary": {"test": {"passed": True, "message": "ok"}}
        },
    )

    results, _duration = runner.run(["src.ts"])

    assert results["test"]["selected_files"] == ["src.ts"]
    assert results["test"]["files_snapshot_sha"] != (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_tick_gate_runner_injects_engine_contracts(tmp_path: Path) -> None:
    source = tmp_path / "src.ts"
    source.write_text("export const route = '/voice';\n", encoding="utf-8")
    runner = TickGateRunner(tmp_path)
    runner._gates = [ContractGate()]

    results, _duration = runner.run(
        ["src.ts"], contracts={"voice": {"path": "/voice"}}
    )

    assert results["contract"]["passed"] is False
    assert results["contract"]["advisory"] is True
    assert results["contract"]["status"] == "advisory"


def test_architect_plan_patch_contract_accepts_additions_only() -> None:
    result = {
        "stage": "architect",
        "plan": "x" * 50,
        "file_list": ["fix.py"],
        "plan_patch": {
            "base_revision": 3,
            "add_batches": [_batch("B27")],
        },
    }

    assert validate_result_format(result, "architect") == []


def test_architect_plan_patch_rejects_reopen_completed() -> None:
    result = {
        "stage": "architect",
        "plan": "x" * 50,
        "file_list": ["fix.py"],
        "plan_patch": {
            "base_revision": 3,
            "add_batches": [_batch("B27")],
            "reopen_completed": ["B1"],
        },
    }

    assert any(
        "不得重新打开" in error
        for error in validate_result_format(result, "architect")
    )


def test_plan_patch_rejects_revision_and_batch_conflicts() -> None:
    state = BatchState.from_batch_plan([_batch("B1")])
    try:
        state.apply_plan_patch(
            base_revision=2,
            active_revision=3,
            add_batches=[_batch("B2")],
            completed_batch_ids={"B1"},
        )
    except ValueError as exc:
        assert "PLAN_REVISION_CONFLICT" in str(exc)
    else:
        raise AssertionError("过期 plan revision 必须被拒绝")

    conflicting = _batch("B1")
    conflicting["component"] = "changed"
    try:
        state.apply_plan_patch(
            base_revision=3,
            active_revision=3,
            add_batches=[conflicting],
            completed_batch_ids=set(),
        )
    except ValueError as exc:
        assert "PLAN_BATCH_CONFLICT" in str(exc)
    else:
        raise AssertionError("同 ID 不同 payload 必须被拒绝")
