"""Phase 80 T409：Stage Result 预校验脱离兼容 façade。"""

from __future__ import annotations

from auto_engineering.loop.design_decision_ledger import DesignDecisionLedger
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


def test_critic_refine_requires_finding_to_implementation_and_test_mapping() -> None:
    error = StageResultPrevalidator().validate(
        "architect",
        design_doc=None,
        result={
            "plan": "x" * 60,
            "plan_patch": {
                "add_batches": [{
                    "batch_id": "B2",
                    "tasks": [
                        {"id": "B2-T1", "kind": "implementation"},
                        {"id": "B2-T2", "kind": "test"},
                    ],
                }],
            },
            "contracts": {},
            "obligations": [],
        },
        requirement="修复 Critic findings",
        research_archive={},
        active_revision=1,
        current_baseline={"batch_plan": [], "obligations": []},
        refine_request={
            "source": "critic",
            "gaps": [{"source_ref": "F-001"}],
        },
    )

    assert error == "Critic finding 缺少修复义务映射: F-001"


def test_critic_refine_accepts_complete_finding_mapping() -> None:
    result = {
        "plan": "x" * 60,
        "plan_patch": {
            "add_batches": [{
                "batch_id": "B2",
                "tasks": [
                    {"id": "B2-T1", "kind": "implementation"},
                    {"id": "B2-T2", "kind": "test"},
                ],
            }],
        },
        "contracts": {},
        "obligations": [{
            "id": "O-F-001",
            "source_ref": "F-001",
            "summary": "修复 Critic finding",
            "implementation_targets": ["B2-T1"],
            "verification_targets": ["B2-T2"],
            "contract_refs": [],
        }],
    }

    error = StageResultPrevalidator().validate(
        "architect",
        design_doc=None,
        result=result,
        requirement="修复 Critic findings",
        research_archive={},
        active_revision=1,
        current_baseline={"batch_plan": [], "obligations": []},
        refine_request={
            "source": "critic",
            "gaps": [{"source_ref": "F-001"}],
        },
    )

    assert error is None


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


def test_partial_design_authority_rejects_research_promotion(tmp_path) -> None:
    state_dir = tmp_path / ".ae-state"
    state_dir.mkdir()
    (state_dir / "design-decision-ledger.json").write_text(
        __import__("json").dumps(DesignDecisionLedger(()).to_dict()),
        encoding="utf-8",
    )

    error = StageResultPrevalidator().validate(
        "architect",
        design_doc=None,
        result={
            "plan": "x" * 60,
            "batch_plan": [{
                "batch_id": "B1",
                "component": "Core",
                "tasks": [{"id": "B1-T1", "description": "增加 BFF"}],
            }],
            "file_list": ["server/bff.py"],
            "contracts": {},
            "obligations": [{"source_ref": "gap-1"}],
        },
        requirement="按原设计实现",
        research_archive={"gap-1": {"recommended_design": "增加 BFF"}},
        active_revision=0,
        current_baseline=None,
        project_root=tmp_path,
    )

    assert error == "DESIGN_CHANGE_APPROVAL_REQUIRED: gap-1"
