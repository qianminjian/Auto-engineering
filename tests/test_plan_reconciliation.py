from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.action_builder import ActionBuilder
from auto_engineering.loop.plan_reconciliation import (
    PlanReconciliationError,
    PlanReconciliationValidator,
)
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _old_plan() -> list[dict]:
    return [
        {
            "batch_id": "B1",
            "tasks": [
                {"id": "B1-T1", "description": "类型定义", "file_targets": ["src/types.ts"]},
                {"id": "B1-T2", "description": "API 实现", "file_targets": ["src/api.ts"]},
            ],
        }
    ]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_verified_completion_requires_current_gate_bound_files(tmp_path: Path) -> None:
    source = tmp_path / "src" / "types.ts"
    source.parent.mkdir()
    source.write_text("export type Id = string;\n", encoding="utf-8")
    candidate = {
        "source_revision": 2,
        "classifications": [
            {"task_id": "B1-T1", "status": "verified_completed", "evidence_ref": "ev-1"},
            {"task_id": "B1-T2", "status": "still_pending", "reason": "仍属于当前设计"},
        ],
        "new_batch_plan": [],
    }
    evidence = {
        "ev-1": {
            "task_id": "B1-T1",
            "gate_passed": True,
            "files": {"src/types.ts": _digest(source)},
        }
    }

    result = PlanReconciliationValidator(tmp_path).validate(
        old_batch_plan=_old_plan(),
        candidate=candidate,
        evidence=evidence,
    )

    assert result.verified_completed == ("B1-T1",)
    assert result.still_pending == ("B1-T2",)
    assert result.current_revision == 3


def test_old_tasks_must_be_classified_exactly_once(tmp_path: Path) -> None:
    candidate = {
        "source_revision": 2,
        "classifications": [
            {"task_id": "B1-T1", "status": "superseded", "reason": "设计已删除"},
        ],
        "new_batch_plan": [],
    }

    with pytest.raises(PlanReconciliationError, match="分类集合"):
        PlanReconciliationValidator(tmp_path).validate(
            old_batch_plan=_old_plan(), candidate=candidate, evidence={}
        )


def test_stale_or_agent_claim_only_evidence_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "src" / "types.ts"
    source.parent.mkdir()
    source.write_text("changed\n", encoding="utf-8")
    candidate = {
        "source_revision": 2,
        "classifications": [
            {"task_id": "B1-T1", "status": "verified_completed", "evidence_ref": "ev-1"},
            {"task_id": "B1-T2", "status": "unverifiable", "reason": "没有证据"},
        ],
        "new_batch_plan": [],
    }
    evidence = {
        "ev-1": {
            "task_id": "B1-T1",
            "gate_passed": True,
            "files": {"src/types.ts": "0" * 64},
        }
    }

    with pytest.raises(PlanReconciliationError, match="文件证据"):
        PlanReconciliationValidator(tmp_path).validate(
            old_batch_plan=_old_plan(), candidate=candidate, evidence=evidence
        )


def test_new_tasks_cannot_reuse_superseded_task_ids(tmp_path: Path) -> None:
    candidate = {
        "source_revision": 2,
        "classifications": [
            {"task_id": "B1-T1", "status": "superseded", "reason": "目标已变化"},
            {"task_id": "B1-T2", "status": "still_pending", "reason": "仍有效"},
        ],
        "new_batch_plan": [
            {"batch_id": "B2", "tasks": [{"id": "B1-T1", "description": "新实现"}]}
        ],
    }

    with pytest.raises(PlanReconciliationError, match="复用"):
        PlanReconciliationValidator(tmp_path).validate(
            old_batch_plan=_old_plan(), candidate=candidate, evidence={}
        )


def test_selected_reconcile_builds_distinct_architect_contract(tmp_path: Path) -> None:
    state = EngineState(
        thread_id="thread-old",
        current_stage="architect",
        batch_plan=_old_plan(),
        architecture_baseline={"revision": 2},
        state_reconciliation={
            "status": "selected",
            "choice": "reconcile",
            "intent": {"design_doc_path": "design/current.md"},
        },
    )

    action = ActionBuilder(tmp_path).build_action(state)

    assert action["feedback"]["mode"] == "PLAN_RECONCILE"
    assert action["feedback"]["reconcile_request"]["source_revision"] == 2
    assert "classifications" in action["expected_format"]
    assert "new_batch_plan" in action["expected_format"]
    assert "plan_patch" not in action["expected_format"]


def test_reconcile_gate_routes_to_architect_without_plan_refine(tmp_path: Path) -> None:
    orchestrator = TickOrchestrator(tmp_path)
    orchestrator._state = EngineState(
        thread_id="thread-old",
        current_stage="developer",
        batch_plan=_old_plan(),
        architecture_baseline={"revision": 2},
        state_reconciliation={
            "status": "waiting_user",
            "gate_message_id": "gate-message",
            "intent": {"design_doc_path": "design/current.md"},
        },
    )

    action = orchestrator._tick_process_result({
        "gate_resolution": {
            "gate_id": "state_reconciliation",
            "resolution": "reconcile",
        }
    })

    assert action["action"] == "architect"
    assert action["feedback"]["mode"] == "PLAN_RECONCILE"
    assert orchestrator._state.current_stage == "architect"
    assert orchestrator._state.refine_request_json is None
