"""Stage Result 的阶段专属无副作用预校验。"""

from __future__ import annotations

from pathlib import Path

from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.loop.architect_validation import dry_run_architect_plan
from auto_engineering.loop.design_decision_ledger import (
    DesignDecisionError,
    DesignDecisionLedger,
)
from auto_engineering.loop.plan_reconciliation import (
    PlanReconciliationError,
    PlanReconciliationValidator,
)


class StageResultPrevalidator:
    def validate(
        self,
        stage: str,
        *,
        design_doc: DesignDoc | None,
        result: dict,
        requirement: str,
        research_archive: dict[str, dict],
        active_revision: int,
        current_baseline: dict | None,
        project_root: Path | None = None,
        old_batch_plan: list[dict] | None = None,
        reconciliation_evidence: dict[str, dict] | None = None,
        approved_changes: dict[str, dict] | None = None,
    ) -> str | None:
        if stage == "gap_scan" and project_root is not None:
            try:
                ledger = DesignDecisionLedger.from_project(project_root)
                for gap in result.get("gaps", []):
                    if isinstance(gap, dict):
                        ledger.validate_gap(gap)
            except DesignDecisionError as exc:
                return str(exc)
            return None
        if stage != "architect":
            return None
        if project_root is not None:
            try:
                ledger = DesignDecisionLedger.from_project(project_root)
                if ledger.enforcement_status == "full":
                    ledger.validate_impacts(
                        result.get("decision_impacts", []),
                        approved_changes=approved_changes or {},
                    )
                else:
                    ledger.validate_advisory_promotions(
                        obligations=result.get("obligations", []),
                        research_archive=research_archive,
                        approved_changes=approved_changes or {},
                    )
            except DesignDecisionError as exc:
                return str(exc)
        if result.get("result_type") == "plan_reconciliation":
            if project_root is None:
                return "PLAN_RECONCILE 缺少 project_root"
            try:
                PlanReconciliationValidator(project_root).validate(
                    old_batch_plan=old_batch_plan or [],
                    candidate=result,
                    evidence=reconciliation_evidence or {},
                )
            except PlanReconciliationError as exc:
                return str(exc)
            return None
        return dry_run_architect_plan(
            design_doc,
            result,
            requirement,
            research_archive,
            active_revision=active_revision,
            current_baseline=current_baseline,
        )


__all__ = ["StageResultPrevalidator"]
