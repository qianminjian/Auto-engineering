"""CLI 必须以 Core 响应决定宿主候选 Result 的最终状态。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.cli.dev_loop import (
    _project_result_repair_action,
    _record_outcome_acceptance,
)
from auto_engineering.host.outcome_journal import OutcomeJournal


def _prepared(tmp_path: Path) -> Path:
    result = {
        "message_type": "result",
        "message_id": "result-1",
        "causation_id": "action-1",
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    OutcomeJournal(tmp_path).prepare("action-1", result, fingerprint="fp-1")
    return path


def test_next_action_marks_candidate_accepted(tmp_path: Path) -> None:
    result_path = _prepared(tmp_path)

    rejected = _record_outcome_acceptance(
        root=tmp_path,
        submitted_result_file=result_path,
        core_response={"action": "developer", "message_id": "action-2"},
    )

    record = OutcomeJournal(tmp_path).load("action-1")
    assert record is not None
    assert record["status"] == "accepted"
    assert rejected is False


def test_protocol_error_marks_candidate_rejected_for_same_action_repair(
    tmp_path: Path,
) -> None:
    result_path = _prepared(tmp_path)

    rejected = _record_outcome_acceptance(
        root=tmp_path,
        submitted_result_file=result_path,
        core_response={
            "action": "error",
            "error_code": "RESULT_FIELD_MISSING",
            "violations": ["scan_coverage"],
        },
    )

    record = OutcomeJournal(tmp_path).load("action-1")
    assert record is not None
    assert record["status"] == "rejected"
    assert record["repairable"] is True
    assert record["action_message_id"] == "action-1"
    assert rejected is True


def test_repair_projection_keeps_active_action_and_continue_control() -> None:
    active = {
        "message_id": "action-1",
        "stage": "gap_scan",
        "extensions": {"ae": {"execution_control": {
            "disposition": "CONTINUE",
            "continuation_required": True,
        }}},
    }

    projected = _project_result_repair_action(
        active,
        {"action": "error", "error_code": "RESULT_FIELD_MISSING"},
    )

    assert projected["message_id"] == "action-1"
    assert projected["stage"] == "gap_scan"
    assert projected["extensions"] == active["extensions"]
    assert projected["result_rejection"]["repair_required"] is True


def test_architect_design_item_repair_exposes_exact_machine_fix() -> None:
    projected = _project_result_repair_action(
        {"message_id": "action-1", "stage": "architect"},
        {
            "action": "error",
            "error_code": "ARCHITECT_PLAN_INVALID",
            "message": (
                "Architect 计划无法初始化执行树: "
                "BATCH_DESIGN_ITEM_SCOPE_INVALID；有效 design_item_refs: A1.1-1"
            ),
        },
    )

    assert "不需要用户输入或重新启动 Worker" in projected["instruction"]
    assert "逐字复制" in projected["instruction"]


def test_architect_obligation_conflict_repair_uses_plan_patch_updates() -> None:
    projected = _project_result_repair_action(
        {"message_id": "action-1", "stage": "architect"},
        {
            "action": "error",
            "error_code": "ARCHITECT_PLAN_INVALID",
            "message": (
                "Architect 计划无法初始化执行树: "
                "OBLIGATION_UPDATE_REQUIRED: GAP-1"
            ),
        },
    )

    instruction = projected["instruction"]
    assert "plan_patch.obligation_updates" in instruction
    assert "不得在 obligations 中重写已有 source_ref" in instruction


def test_architect_tdd_order_repair_explains_same_batch_topology() -> None:
    projected = _project_result_repair_action(
        {"message_id": "action-1", "stage": "architect"},
        {
            "action": "error",
            "error_code": "ARCHITECT_PLAN_INVALID",
            "message": (
                "Architect 计划无法初始化执行树: "
                "ARCHITECT_TEST_IMPLEMENTATION_ORDER_INVALID: 测试任务对应实现位于未来 batch"
            ),
        },
    )

    instruction = projected["instruction"]
    assert "同一 batch" in instruction
    assert "depends_on 指向测试 task" in instruction
    assert "不得重新 spawn" in instruction


def test_architect_coverage_repair_exposes_identity_diff_and_forbids_respawn() -> None:
    projected = _project_result_repair_action(
        {"message_id": "action-1", "stage": "architect"},
        {
            "action": "error",
            "error_code": "HOST_EVIDENCE_INVALID",
            "message": "宿主语义产物无法组装为合法 Result",
            "violations": [
                "ARCHITECT_RESULT_COVERAGE_LOSS",
                "ARCHITECT_RESULT_SOURCE_BATCHES:B1,B2",
                "ARCHITECT_RESULT_CANDIDATE_BATCHES:B1,B3",
                "ARCHITECT_RESULT_SOURCE_TASKS:B1-T1,B2-T1",
                "ARCHITECT_RESULT_CANDIDATE_TASKS:B1-T1,B3-T1",
                "ARCHITECT_RESULT_MISSING_BATCHES:B2",
                "ARCHITECT_RESULT_EXTRA_BATCHES:B3",
                "ARCHITECT_RESULT_MISSING_TASKS:B2-T1",
                "ARCHITECT_RESULT_EXTRA_TASKS:B3-T1",
            ],
        },
    )

    instruction = projected["instruction"]
    assert "Worker outcome 中的 batch_id 和 task.id 是唯一权威身份" in instruction
    assert "ARCHITECT_RESULT_MISSING_BATCHES:B2" in instruction
    assert "ARCHITECT_RESULT_EXTRA_TASKS:B3-T1" in instruction
    assert "不得重新 spawn" in instruction
