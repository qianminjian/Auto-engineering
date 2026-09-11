"""Architect Worker 计划覆盖合同回归。"""

from __future__ import annotations

from auto_engineering.loop.architect_plan_coverage import (
    architect_plan_coverage_violations,
    architect_plan_manifest,
)


def _plan() -> list[dict]:
    return [
        {
            "batch_id": "B1",
            "component": "Core",
            "tasks": [{"id": "B1-T1", "description": "实现 B1"}],
        },
        {
            "batch_id": "B2",
            "component": "Core",
            "tasks": [{"id": "B2-T1", "description": "实现 B2"}],
        },
    ]


def test_architect_plan_manifest_is_stable_and_complete() -> None:
    manifest = architect_plan_manifest(_plan())

    assert manifest is not None
    assert manifest["schema_version"] == "1.0"
    assert manifest["batch_ids"] == ["B1", "B2"]
    assert manifest["task_ids"] == ["B1-T1", "B2-T1"]
    assert len(manifest["digest"]) == 64


def test_architect_coverage_rejects_coordinator_subset() -> None:
    violations = architect_plan_coverage_violations(
        worker_payloads=[{"batch_plan": _plan()}],
        coordinator_payload={"batch_plan": [_plan()[0]]},
    )

    assert violations[0] == "ARCHITECT_RESULT_COVERAGE_LOSS"
    assert "B2" in violations[3]
    assert "B2-T1" in violations[5]


def test_architect_coverage_accepts_equivalent_nested_projection() -> None:
    nested = [{
        "component": "Core",
        "batches": _plan(),
    }]

    assert architect_plan_coverage_violations(
        worker_payloads=[{"batch_plan": nested}],
        coordinator_payload={"batch_plan": _plan()},
    ) == ()


def test_architect_coverage_allows_non_identity_metadata_repair() -> None:
    repaired = [dict(item) for item in _plan()]
    repaired[0] = {
        **repaired[0],
        "description": "规范化后的 B1 路由",
    }

    assert architect_plan_coverage_violations(
        worker_payloads=[{"batch_plan": _plan()}],
        coordinator_payload={"batch_plan": repaired},
    ) == ()


def test_architect_coverage_reports_exact_missing_and_extra_identity() -> None:
    candidate = [
        {
            "batch_id": "B1",
            "component": "Core",
            "tasks": [{"id": "B1-T1", "description": "实现 B1"}],
        },
        {
            "batch_id": "B3",
            "component": "Core",
            "tasks": [{"id": "B3-T1", "description": "错误重建"}],
        },
    ]

    violations = architect_plan_coverage_violations(
        worker_payloads=[{"batch_plan": _plan()}],
        coordinator_payload={"batch_plan": candidate},
    )

    assert "ARCHITECT_RESULT_MISSING_BATCHES:B2" in violations
    assert "ARCHITECT_RESULT_EXTRA_BATCHES:B3" in violations
    assert "ARCHITECT_RESULT_MISSING_TASKS:B2-T1" in violations
    assert "ARCHITECT_RESULT_EXTRA_TASKS:B3-T1" in violations


def test_architect_coverage_reports_invalid_source_and_candidate_reasons() -> None:
    violations = architect_plan_coverage_violations(
        worker_payloads=[{"batch_plan": [{"batch_id": "B1"}]}],
        coordinator_payload={"batch_plan": "not-a-plan"},
    )

    assert violations[0] == "ARCHITECT_RESULT_COVERAGE_INVALID"
    assert any(
        item.startswith("ARCHITECT_RESULT_COVERAGE_CANDIDATE_REASON:")
        for item in violations
    )


def test_architect_coverage_rejects_missing_worker_plan() -> None:
    violations = architect_plan_coverage_violations(
        worker_payloads=[{"plan": "没有 canonical batch plan"}],
        coordinator_payload={"batch_plan": _plan()},
    )

    assert violations[0] == "ARCHITECT_RESULT_COVERAGE_INVALID"
    assert any(
        item.startswith("ARCHITECT_RESULT_COVERAGE_SOURCE_REASON:")
        for item in violations
    )
