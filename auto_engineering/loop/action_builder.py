"""ActionBuilder — 构建 per-tick action JSON (P0-1: 从 TickOrchestrator 提取).

封装 10 个 stage action builder + dispatch + PII outbound 过滤.
TickOrchestrator 委托调用, 不再内联 stage action 构造逻辑.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from auto_engineering.config.constants import DEFAULT_P1_THRESHOLD, _SPAWN_CONFIG
from auto_engineering.config.feature_flags import feature_status_for_action
from auto_engineering.prompts.registry import default_registry

# T139: Natural-language commands for spawn stages.
# Injected as top-level "instruction" in the action JSON — the first text the
# Agent reads when processing a tick.  No cross-referencing dev-loop.md needed.
_SPAWN_INSTRUCTION = (
    "你是 Loop 组长。现在需要 {subagent_type} subagent 来执行 {stage} 阶段。\n"
    "用 Agent tool spawn {count} 个 {subagent_type} subagent{parallel}（model: {model}）。\n"
    "把下面的 role_prompt + context + expected_format 交给它。\n"
    "收集它的输出，写入 result JSON 文件。\n"
    "🚨 你自己不要做 {stage} 的工作——spawn subagent 就是这个 tick 的工作。"
)

if TYPE_CHECKING:
    from auto_engineering.engine.batch_state import BatchState
    from auto_engineering.engine.design_doc import DesignDoc
    from auto_engineering.engine.models import Plan
    from auto_engineering.engine.progress_tree import ProgressTree
    from auto_engineering.engine.state import EngineState
    from auto_engineering.pii.redactor import PIIRedactor

_logger = logging.getLogger("ae.loop.action_builder")

# DS-9 (B6.6a): Haiku verifier 负判定 (MISSING/DIVERGED) → Sonnet 窄范围复核.
_VERIFIER_RECHECK = {
    "enabled": True,
    "model": "claude-sonnet-4-6",
    "trigger": "on_negative",
    "scope": "narrow",
}

_STAGE_CHECKPOINT_REVIEW_FEEDBACK = (
    "用户选择审查当前产出，请展示当前进度和已完成内容供审查。"
)

class ActionBuilder:
    """Build per-tick action JSON for each stage.

    Extracted from TickOrchestrator (P0-1: God Class — 2321 行, 60 方法).
    Encapsulates 10 stage action builders + dispatch + PII outbound filtering.

    Usage::

        builder = ActionBuilder(project_root, pii_enabled=True, pii_redactor=redactor)
        action = builder.build_action(
            state, design_doc=doc, batch_state=bs, plan=plan,
            progress_tree=pt, ...
        )
    """

    def __init__(
        self,
        project_root: Path,
        *,
        pii_enabled: bool = False,
        pii_redactor: PIIRedactor | None = None,
        pii_outbound: str = "redact",
    ) -> None:
        self.project_root = project_root
        self._pii_enabled = pii_enabled
        self._pii_redactor = pii_redactor
        self._pii_outbound = pii_outbound

    # ── public API ──

    def build_action(
        self,
        state: EngineState,
        *,
        design_doc: DesignDoc | None = None,
        init_manifest: dict | None = None,
        batch_state: BatchState | None = None,
        plan: Plan | None = None,
        dev_snapshot: dict[str, object] | None = None,
        progress_tree: ProgressTree | None = None,
        pause_at_stages: set[str] | None = None,
        passed_checkpoints: set[str] | None = None,
        last_batch_id: str | None = None,
        feedback: str | None = None,
        pre_gate: dict | None = None,
        pii_enabled: bool | None = None,
        pii_redactor: PIIRedactor | None = None,
        pii_outbound: str | None = None,
    ) -> dict:
        """Build the action dict for the current stage.

        P0-7: Each stage's action construction is extracted to a private method
        (_build_action_<stage>), making individual stages independently testable
        and the dispatcher ~25 lines instead of ~300.
        """
        # Stash deps for internal builder methods
        self._state = state
        self._design_doc = design_doc
        self._init_manifest = init_manifest
        self._batch_state = batch_state
        self._plan = plan
        self._dev_snapshot = dev_snapshot
        self._progress_tree = progress_tree
        self._pause_at_stages = pause_at_stages or set()
        self._passed_checkpoints = passed_checkpoints or set()
        self._last_batch_id = last_batch_id
        # Per-call PII overrides (local copies — do NOT mutate instance state
        # to avoid cross-tick leakage, P1-12)
        _pi_enabled = pii_enabled if pii_enabled is not None else self._pii_enabled
        _pi_redactor = pii_redactor if pii_redactor is not None else self._pii_redactor
        _pi_outbound = pii_outbound if pii_outbound is not None else self._pii_outbound

        stage = state.current_stage
        state.action_timestamp = time.time()

        if pre_gate:
            return {
                "action": "gate",
                "tick": state.tick + 1,
                "stage": stage,
                "thread_id": state.thread_id,
                "gate": pre_gate,
                "progress_summary": self._progress_summary(),
            }

        if stage in self._pause_at_stages and not self._checkpoint_passed(stage):
            return {
                "action": "gate",
                "tick": state.tick + 1,
                "stage": stage,
                "thread_id": state.thread_id,
                "gate": {
                    "id": f"checkpoint_{stage}",
                    "type": "stage_checkpoint",
                    "trigger": f"before_{stage}",
                    "question": (
                        f"即将进入 {stage} 阶段。"
                        f"当前进度：{self._progress_summary()}"
                    ),
                    "options": ["继续", "审查当前产出", "终止 loop"],
                    "default": "继续",
                    "timeout_ms": 0,
                },
                "progress_summary": self._progress_summary(),
            }

        base = self._build_action_base(feedback)

        _dispatch: dict[str, Callable[[dict], dict]] = {
            "gap_scan": self._build_action_gap_scan,
            "gap_review": self._build_action_gap_review,
            "research": self._build_action_research,
            "architect": self._build_action_architect,
            "developer": self._build_action_developer,
            "critic": self._build_action_critic,
            "component_verifier": self._build_action_component_verifier,
            "plate_deep_audit": self._build_action_plate_deep_audit,
            "system_verifier": self._build_action_system_verifier,
            "system_deep_audit": self._build_action_system_deep_audit,
        }

        builder = _dispatch.get(stage)
        if builder is not None:
            action = builder(base)
        else:
            action = {**base, "action": "error",
                      "error_code": "UNKNOWN_STAGE",
                      "message": f"Unknown stage: {stage}"}

        return self._apply_pii_outbound(action, _pi_enabled, _pi_redactor, _pi_outbound)

    # ── helpers ──

    def _checkpoint_passed(self, stage: str) -> bool:
        return stage in self._passed_checkpoints

    def _progress_summary(self) -> str:
        s = self._state
        if s is None:
            return "tick=0, stage=?"
        parts = [f"tick={s.tick}/{s.round}", f"stage={s.current_stage}"]
        if self._batch_state is not None:
            if self._batch_state.is_component_complete():
                parts.append("batch=complete")
            else:
                parts.append(f"batch={self._batch_state.current_batch_id()}")
        return ", ".join(parts)

    def _safe_design_section(self) -> str | None:
        if self._batch_state is None or self._batch_state.is_plate_complete():
            return None
        return self._batch_state.current_design_section()

    def _resolve_batch_id(self) -> str | None:
        if self._batch_state is None:
            return None
        if not self._batch_state.is_component_complete():
            return self._batch_state.current_batch_id()
        return self._last_batch_id

    # ── PII outbound ──

    def _apply_pii_outbound(self, action: dict, pii_enabled: bool, pii_redactor, pii_outbound: str) -> dict:
        """T109c L2: outbound action JSON PII 脱敏."""
        if not pii_enabled or not pii_redactor:
            return action
        if pii_outbound == "redact":
            return pii_redactor.redact_dict(action)
        elif pii_outbound in ("warn", "block"):
            findings = pii_redactor.scan_dict(action)
            if findings:
                _logger.warning(
                    "PII detected in outbound action: %d matches", len(findings))
                if pii_outbound == "block":
                    s = self._state
                    return {
                        "action": "error",
                        "tick": s.tick + 1 if s else 1,
                        "stage": s.current_stage if s else "",
                        "thread_id": s.thread_id if s else "",
                        "error_code": "PII_BLOCKED_OUTBOUND",
                        "message": (
                            f"PII detected in outbound action: "
                            f"{len(findings)} matches"),
                    }
        return action

    # ── base ──

    def _build_action_base(self, feedback: str | None = None) -> dict:
        return {
            "tick": self._state.tick + 1,
            "stage": self._state.current_stage,
            "thread_id": self._state.thread_id,
            "gate_summary": self._state.gate_results,
            "feedback": feedback,
            "requirement": self._state.requirement,
            "feature_status": feature_status_for_action(),
            "progress_summary": (
                self._progress_tree.summary() if self._progress_tree else None
            ),
        }

    # ── helper: data-driven stage action builder ──

    def _build_stage_action(
        self, base: dict, action: str, context: dict | None = None,
        expected_format: dict | None = None, **extra,
    ) -> dict:
        """Construct a stage action dict with auto-resolved spawn config.

        T138: When *action* is a spawn stage, inject:
        - ``instruction`` — natural-language command (top-level, Agent reads first)
        - ``role_prompt`` — full role prompt text from PromptRegistry
        - ``spawned`` in expected_format — G2 retry if not true
        """
        result: dict = {**base, "action": action}
        spawn = _SPAWN_CONFIG.get(action)
        if spawn is not None:
            result["spawn"] = spawn
            # T138: inject natural-language command + role prompt
            result["instruction"] = _SPAWN_INSTRUCTION.format(
                subagent_type=spawn["subagent_type"],
                count=spawn["count"],
                parallel=" 并行" if spawn.get("parallel") else "",
                model=spawn.get("model", "default"),
                stage=action,
            )
            try:
                _reg = default_registry()
                result["role_prompt"] = _reg.get(action)
            except Exception:
                result["role_prompt"] = ""
            # T141: spawned field in expected_format
            if expected_format is not None:
                expected_format = {
                    "spawned": "bool — MUST be true after spawning subagent",
                    **expected_format,
                }
        if context:
            result["context"] = context
        if expected_format is not None:
            result["expected_format"] = expected_format
        result.update(extra)
        return result

    # ── stage builders ──

    def _build_action_gap_scan(self, base: dict) -> dict:
        return self._build_stage_action(base, "gap_scan", context={
            "design_doc_path": (
                self._design_doc.path if self._design_doc else None),
            "plates": [
                {"id": p.design_section, "name": p.name,
                 "components": [c.design_section or c.name
                                for c in p.components]}
                for p in (self._design_doc.plates if self._design_doc else [])
            ],
            "project_root": str(self.project_root),
        }, expected_format={
            "gaps": ("[{id, design_section_ref, grade, clarity, "
                     "summary, depends_on}]"),
            "scanned_sections": "int",
            "has_blocking": "bool",
        })

    def _build_action_gap_review(self, base: dict) -> dict:
        report = json.loads(self._state.gap_report_json or '{"gaps": []}')
        is_rereview = bool(self._state.research_archive)
        return self._build_stage_action(base, "gap_review",
            gaps=report.get("gaps", []),
            has_blocking=report.get("has_blocking", False),
            is_rereview=is_rereview,
            research_findings=dict(self._state.research_archive),
            instruction=(
                "初审: 对每个 gap 用 AskUserQuestion 收集 Fill(用户补充) / "
                "Research(检索) / Defer(留给architect) / Defer+Research. "
                "has_blocking 的 architectural gap 禁止 Defer. "
                "复审(is_rereview=true, research_findings 非空): 呈现 findings, "
                "让用户据研究发现做补充设计 — Fill(写入细化内容→Supplement) "
                "或 Defer(留给 architect in-loop 细化)."),
            expected_format={
                "decisions": "[{gap_id, resolution, user_note, fill_content?}]",
            })

    def _build_action_research(self, base: dict) -> dict:
        report = json.loads(self._state.gap_report_json or '{"gaps": []}')
        by_id = {g["id"]: g for g in report.get("gaps", [])}
        current_id = (
            self._state.pending_research_ids[0]
            if self._state.pending_research_ids else None)
        gap = by_id.get(current_id, {}) if current_id else {}
        return self._build_stage_action(base, "research",
            gap={
                "id": gap.get("id"),
                "design_section_ref": gap.get("design_section_ref"),
                "grade": gap.get("grade"),
                "summary": gap.get("summary"),
            },
            knowledge_sources={
                "tier_order": [
                    "tier0", "tier1_ref_code", "tier2_doc_kb", "tier3_web"],
                "memory_constraint": (
                    "grep 定位 → 50-200 行 Read → 丢弃; 禁止批量/并行扫描"),
            },
            expected_format={
                "findings": "string",
                "sources": "[{tier, ref, note}]",
                "source_tier": "tier0|tier1|tier2|tier3",
                "confidence": "high|medium|low",
                "recommended_design": "string (可注入 supplement)",
            })

    def _build_action_architect(self, base: dict) -> dict:
        extra: dict = {}
        if self._state.refine_request_json:
            extra["feedback"] = {
                "mode": "PLAN_REFINE",
                "refine_request": json.loads(self._state.refine_request_json),
            }
        return self._build_stage_action(base, "architect", context={
            "requirement": self._state.requirement,
            "design_section": self._safe_design_section(),
            "project_root": str(self.project_root),
            "init_manifest": self._init_manifest,
            "design_supplements": (
                json.loads(self._state.design_supplements_json)
                if self._state.design_supplements_json else {}),
            "research_archive": self._state.research_archive,
        }, expected_format={
            "plan": "string (markdown, min 50 chars)",
            "batch_plan": (
                "[{batch_id, design_section, component, "
                "tasks:[{id, description, module_ref, file_targets}], "
                "depends_on}] (min 1 batch)"),
            "file_list": "[string] (min 1 file)",
            "contracts": "object (may be empty)",
        }, **extra)

    def _build_action_developer(self, base: dict) -> dict:
        tasks = (
            self._batch_state.current_batch_tasks(self._plan)
            if self._batch_state and self._plan
            else (self._plan.get_tasks_by_stage("developer")
                  if self._plan else [])
        )
        return self._build_stage_action(base, "developer",
            component=(
                self._batch_state.current_component_name()
                if self._batch_state else None),
            batch_id=(
                self._batch_state.current_batch_id()
                if self._batch_state else None),
            tasks=[
                {"id": t.id, "description": t.description,
                 "expected_output": t.expected_output,
                 "file_targets": list(t.target_files),
                 "depends_on": t.depends_on}
                for t in tasks
            ],
            plan=self._state.plan)

    def _build_action_critic(self, base: dict) -> dict:
        snap = self._dev_snapshot or {}
        return self._build_stage_action(base, "critic", context={
            "files_changed": snap.get("files_changed", self._state.files_changed),
            "test_results": snap.get("test_results", self._state.test_results),
            "commit_hash": snap.get("commit_hash", self._state.commit_hash),
            "component": (
                self._batch_state.current_component_name()
                if self._batch_state else None),
            "design_section": (
                self._batch_state.current_design_section()
                if self._batch_state else None),
            "batch_id": self._resolve_batch_id(),
        }, expected_format={
            "stage": "critic",
            "verdict": "APPROVE | MAJOR",
            "findings": "[{file, line, severity, issue, suggestion}]",
            "critic_feedback": "string",
        })

    def _build_action_component_verifier(self, base: dict) -> dict:
        comp = self._batch_state.current_component()
        return self._build_stage_action(base, "component_verifier", context={
            "component": comp.name,
            "design_section": comp.design_section,
            "design_spec": comp.design_spec_summary(),
            "implementation_files": getattr(comp, "implementation_files", []),
            "contracts": getattr(comp, "contracts", {}),
        }, expected_format={
            "stage": "component_verifier",
            "component": "string (组件名称, 必填)",
            "coverage_map": (
                "[{design_item, status(IMPLEMENTED|MISSING|DIVERGED), "
                "file, line, note}]"),
            "missing_count": "int",
            "diverged_count": "int",
            "recheck_log": (
                "[{design_item, haiku_status, sonnet_verdict, final_status}] "
                "(仅负判定经 Sonnet 复核后填, 无负判定则空)"),
        }, recheck=dict(_VERIFIER_RECHECK))

    def _build_action_plate_deep_audit(self, base: dict) -> dict:
        plate = self._batch_state.current_plate()
        return self._build_stage_action(base, "plate_deep_audit", context={
            "plate": plate.name,
            "components": plate.components_summary(),
            "cross_component_contracts": plate.cross_component_contracts(),
            "project_root": str(self.project_root),
        }, expected_format={
            "stage": "plate_deep_audit",
            "plate": "string (板块名称, 必填)",
            "findings": (
                "[{severity, dimension, agent_source, file, line, "
                "description, suggested_fix}]"),
            "p0_count": "int", "p1_count": "int", "p2_count": "int",
            "cross_component_issues": "[{contract_id, status, detail}]",
            "total_audited_files": "int",
        })

    def _build_action_system_verifier(self, base: dict) -> dict:
        return self._build_stage_action(base, "system_verifier", context={
            "design_doc": (
                self._design_doc.path if self._design_doc else None),
            "design_sections": (
                self._design_doc.sections_summary()
                if self._design_doc else []),
            "project_root": str(self.project_root),
        }, expected_format={
            "stage": "system_verifier",
            "full_coverage_map": (
                "[{design_section, design_item, status, "
                "implementation, note}]"),
            "total_design_items": "int",
            "covered_count": "int",
            "missing_count": "int",
            "diverged_count": "int",
            "recheck_log": (
                "[{design_item, haiku_status, sonnet_verdict, final_status}] "
                "(仅负判定经 Sonnet 复核后填, 无负判定则空)"),
        }, recheck=dict(_VERIFIER_RECHECK))

    def _build_action_system_deep_audit(self, base: dict) -> dict:
        return self._build_stage_action(base, "system_deep_audit", context={
            "project_root": str(self.project_root),
            "audit_dimensions": [
                "架构合理性", "代码质量", "工程化规范",
                "代码逻辑虚化度", "团队协作友好度", "设计覆盖度"],
            "p1_threshold": DEFAULT_P1_THRESHOLD,
            "coverage_map_from_verifier": self._state.coverage_map,
        }, expected_format={
            "stage": "system_deep_audit",
            "findings": (
                "[{severity, dimension, file, line, description, "
                "evidence, suggested_fix}]"),
            "p0_count": "int", "p1_count": "int", "p2_count": "int",
            "total_audited_files": "int",
            "design_docs_stale": "bool",
            "design_doc_suggestions": "string",
            "missing_count": "int",
            "diverged_count": "int",
        })


__all__ = ["ActionBuilder"]
