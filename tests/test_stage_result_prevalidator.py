"""Phase 80 T409：Stage Result 预校验脱离兼容 façade。"""

from __future__ import annotations

from auto_engineering.loop.stage_result_prevalidator import StageResultPrevalidator


def test_non_architect_result_has_no_architecture_validation() -> None:
    assert StageResultPrevalidator().validate(
        "developer",
        design_doc=None,
        result={"stage": "developer"},
        requirement="实现协议",
        research_archive={},
        active_revision=0,
        current_baseline=None,
    ) is None


def test_architect_refine_rejects_missing_plan_patch() -> None:
    error = StageResultPrevalidator().validate(
        "architect",
        design_doc=None,
        result={"stage": "architect", "plan": "", "batch_plan": []},
        requirement="实现协议",
        research_archive={},
        active_revision=1,
        current_baseline=None,
    )

    assert error == "PLAN_REFINE 必须提交 plan_patch，禁止重发完整 batch_plan"


def test_plan_reconcile_candidate_uses_distinct_validator(tmp_path) -> None:
    error = StageResultPrevalidator().validate(
        "architect",
        design_doc=None,
        result={
            "stage": "architect",
            "result_type": "plan_reconciliation",
            "source_revision": 2,
            "classifications": [
                {"task_id": "B1-T1", "status": "still_pending", "reason": "仍有效"}
            ],
            "new_batch_plan": [],
        },
        requirement="实现协议",
        research_archive={},
        active_revision=0,
        current_baseline={"revision": 2},
        project_root=tmp_path,
        old_batch_plan=[{"batch_id": "B1", "tasks": [{"id": "B1-T1"}]}],
        reconciliation_evidence={},
    )

    assert error is None
