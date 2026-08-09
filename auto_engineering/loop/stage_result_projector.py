"""已验证 Stage Result 到 EngineState 的确定性投影。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.architecture_candidate import ArchitectureCandidateBuilder


class StageResultProjector:
    """集中维护 Result 字段所有权，不执行 Gate 或路由。"""

    def apply(
        self,
        state: EngineState,
        result: Mapping[str, Any],
        *,
        audit_key: Callable[[str], str] | None = None,
        audit_fingerprint: Callable[[str], str] | None = None,
    ) -> None:
        stage = result.get("stage", "")
        if stage == "gap_scan":
            state.gap_report_json = json.dumps({
                "gaps": result.get("gaps", []),
                "scanned_sections": result.get("scanned_sections", 0),
                "has_blocking": result.get("has_blocking", False),
            }, ensure_ascii=False)
        elif stage == "gap_review":
            state.pending_gap_decisions = result.get("decisions", [])
        elif stage == "architect":
            self._apply_architect(state, result)
        elif stage == "developer":
            self._apply_developer(state, result)
        elif stage == "critic":
            state.critic_verdict = result.get("verdict", "")
            state.findings = result.get("findings", [])
            state.critic_feedback = result.get("critic_feedback", "")
        elif stage == "component_verifier":
            state.coverage_map = result.get("coverage_map", [])
        elif stage == "system_verifier":
            state.coverage_map = result.get("full_coverage_map", [])
        elif (
            stage in {"plate_deep_audit", "system_deep_audit"}
            and audit_key is not None
            and audit_fingerprint is not None
        ):
            state.audit_revision_fingerprints[audit_key(stage)] = (
                audit_fingerprint(stage)
            )

    @staticmethod
    def _apply_architect(
        state: EngineState,
        result: Mapping[str, Any],
    ) -> None:
        state.plan = result.get("plan", "")
        plan_patch = result.get("plan_patch")
        if isinstance(plan_patch, Mapping):
            candidate = ArchitectureCandidateBuilder().build(
                result,
                active_revision=state.plan_refine_count,
                current_baseline=state.architecture_baseline,
            )
            state.batch_plan = plan_patch.get("add_batches", [])
            state._runtime_ctx["plan_patch_base_revision"] = plan_patch.get(
                "base_revision"
            )
            state._runtime_ctx["architecture_candidate"] = candidate
            state.contracts = candidate["contracts"]
            state._runtime_ctx["architect_obligations"] = candidate[
                "obligations"
            ]
        else:
            state.batch_plan = result.get("batch_plan", [])
            state._runtime_ctx.pop("plan_patch_base_revision", None)
            state._runtime_ctx.pop("architecture_candidate", None)
            state.contracts = result.get("contracts", {})
            state._runtime_ctx["architect_obligations"] = result.get(
                "obligations",
                [],
            )
        state.file_list = result.get("file_list", [])

    @staticmethod
    def _apply_developer(
        state: EngineState,
        result: Mapping[str, Any],
    ) -> None:
        state.files_changed = result.get("files_changed", [])
        state.batch_changed_files = list(dict.fromkeys([
            *state.batch_changed_files,
            *state.files_changed,
        ]))
        state.commit_hash = result.get("commit_hash", "")
        state.test_results = result.get("test_results", {})
        state.red_evidence = result.get("red_evidence", [])


__all__ = ["StageResultProjector"]
