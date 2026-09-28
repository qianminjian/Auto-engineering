"""恢复、预校验和章节规范化的失败闭环边界。"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.loop.section_findings import (
    SectionFindingValidationError,
    normalize_section_findings,
    section_has_explicit_design_contract,
)
from auto_engineering.loop.stage_result_prevalidator import StageResultPrevalidator


def test_section_findings_rejects_malformed_sections_and_findings() -> None:
    with pytest.raises(SectionFindingValidationError):
        normalize_section_findings(
            sections=["bad", {"section_id": "s1"}, {"section_id": "s1", "design_section": "§1"}],
            findings=[],
            gaps=[],
            design_doc_digest="sha256:x",
        )
    with pytest.raises(SectionFindingValidationError):
        normalize_section_findings(
            sections=[{"section_id": "s1", "design_section": "§1"}],
            findings=None,
            gaps=[],
            design_doc_digest="sha256:x",
        )
    with pytest.raises(SectionFindingValidationError):
        normalize_section_findings(
            sections=[{"section_id": "s1", "design_section": "§1"}],
            findings=[None, {"section_id": "s1", "verdict": "clear", "evidence": []}],
            gaps=[],
            design_doc_digest="sha256:x",
        )


def test_section_findings_reports_missing_and_duplicate_section_identity() -> None:
    with pytest.raises(SectionFindingValidationError, match="REF_MISSING"):
        normalize_section_findings(
            sections=[{"section_id": "s1"}],
            findings=[],
            gaps=[],
            design_doc_digest="sha256:x",
        )


def test_section_contract_probe_returns_false_for_other_section(tmp_path: Path) -> None:
    design_path = tmp_path / "design.md"
    design_path.write_text("## 1 产品\n### 1.1 明确契约\n必须实现。\n", encoding="utf-8")
    document = DesignDoc.parse(design_path)
    assert section_has_explicit_design_contract(document, "§不存在") is False
    with pytest.raises(SectionFindingValidationError, match="REF_DUPLICATE"):
        normalize_section_findings(
            sections=[
                {"section_id": "s1", "design_section": "§1"},
                {"section_id": "s2", "design_section": "§1"},
            ],
            findings=[],
            gaps=[],
            design_doc_digest="sha256:x",
        )


def test_stage_prevalidator_returns_stable_ledger_and_plan_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import auto_engineering.loop.stage_result_prevalidator as module

    class BrokenLedger:
        enforcement_status = "full"

        def validate_gap(self, _gap: object) -> None:
            raise module.DesignDecisionError("gap-invalid")

        def validate_impacts(self, *_args: object, **_kwargs: object) -> None:
            raise module.DesignDecisionError("impact-invalid")

    monkeypatch.setattr(module.DesignDecisionLedger, "from_project", lambda _: BrokenLedger())
    assert StageResultPrevalidator().validate(
        "gap_scan",
        design_doc=None,
        result={"gaps": [{"id": "g1"}]},
        requirement="r",
        research_archive={},
        active_revision=0,
        current_baseline=None,
        project_root=tmp_path,
    ) == "gap-invalid"
    assert StageResultPrevalidator().validate(
        "architect",
        design_doc=None,
        result={"decision_impacts": []},
        requirement="r",
        research_archive={},
        active_revision=0,
        current_baseline=None,
        project_root=tmp_path,
    ) == "impact-invalid"
    assert StageResultPrevalidator().validate(
        "architect",
        design_doc=None,
        result={"result_type": "plan_reconciliation"},
        requirement="r",
        research_archive={},
        active_revision=0,
        current_baseline=None,
    ) == "PLAN_RECONCILE 缺少 project_root"

    reconcile_error = StageResultPrevalidator().validate(
        "architect",
        design_doc=None,
        result={
            "result_type": "plan_reconciliation",
            "source_revision": 99,
            "classifications": [],
            "new_batch_plan": [],
        },
        requirement="r",
        research_archive={},
        active_revision=0,
        current_baseline={"revision": 1},
        project_root=tmp_path,
        old_batch_plan=[],
    )
    assert reconcile_error is not None


def test_stage_prevalidator_converts_engineering_model_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import auto_engineering.loop.stage_result_prevalidator as module

    design_path = tmp_path / "design.md"
    design_path.write_text("## 1 产品\n### 1.1 明确契约\n必须实现。\n", encoding="utf-8")
    design_doc = DesignDoc.parse(design_path)
    monkeypatch.setattr(module, "dry_run_architect_plan", lambda *args, **kwargs: None)

    def broken_model(*args: object, **kwargs: object) -> object:
        raise module.EngineeringModelError("model-invalid")

    monkeypatch.setattr(module.EngineeringModel, "from_design_doc", broken_model)
    assert StageResultPrevalidator().validate(
        "architect",
        design_doc=design_doc,
        result={"plan": "valid plan"},
        requirement="r",
        research_archive={},
        active_revision=0,
        current_baseline=None,
    ) == "model-invalid"


def test_state_reconciliation_rejects_replay_identity_and_selection_edges(
    tmp_path: Path,
) -> None:
    from auto_engineering.loop.state_reconciliation import (
        StateReconciliationError,
        StateReconciliationService,
    )
    from tests.test_reinitialize_trajectory import _result, _seed

    events, _, gate = _seed(tmp_path)
    service = StateReconciliationService(events)
    result = _result(gate)
    service.select(result)
    service.validate(result)
    conflict = dict(result)
    conflict["gate_resolution"] = {"gate_id": "state_reconciliation", "resolution": "reconcile"}
    with pytest.raises(StateReconciliationError, match="不同选择"):
        service.select(conflict)
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    events2, _, gate2 = _seed(empty_root)
    events2.load_projection = lambda _thread: None  # type: ignore[method-assign]
    with pytest.raises(StateReconciliationError, match="active gate"):
        StateReconciliationService(events2).select(_result(gate2))
