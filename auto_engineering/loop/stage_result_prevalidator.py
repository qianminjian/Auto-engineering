"""Stage Result 的阶段专属无副作用预校验。"""

from __future__ import annotations

from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.loop.architect_validation import dry_run_architect_plan


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
    ) -> str | None:
        if stage != "architect":
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
