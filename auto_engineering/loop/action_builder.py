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

# DS-15: spawn instruction. For multi-agent stages (count>1), each agent gets
# its own prompt from spawn.agents[]. Team Lead spawns all N, collects outputs,
# merges into one result JSON.
_SPAWN_INSTRUCTION = (
    "Spawn {count} agent{parallel} with effort={effort}.\n"
    "{multi_instruction}"
    "Collect all outputs → merge into one result per expected_format → "
    "write result: {{\"stage\":\"{stage}\",\"spawned\":true, ...merged}}.\n"
    "Proof: .ae-state/spawn-proofs/{proof_token}.json (tell each subagent to append stage+timestamp).\n"
    "On failure: {{\"stage\":\"{stage}\",\"spawned\":false,\"spawn_error\":\"<reason>\"}}."
)
_SPAWN_MULTI_INSTRUCTION = (
    "Each agent has its own prompt in spawn.agents[] — give agent[i] spawn.agents[i].prompt.\n"
)
_SPAWN_SINGLE_INSTRUCTION = (
    "Use subagent_prompt below.\n"
)
# Non-spawn stages (developer, gap_scan inline) use this:
_INLINE_INSTRUCTION = (
    "Do the work for stage '{stage}' per expected_format. "
    "Write result JSON with stage='{stage}'."
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
    "trigger": "on_negative",
    "scope": "narrow",
}

_STAGE_CHECKPOINT_REVIEW_FEEDBACK = (
    "用户选择审查当前产出，请展示当前进度和已完成内容供审查。"
)

_STAGE_CHECKPOINT_OPTIONS = ["继续", "审查当前产出", "终止 loop"]  # P1-23: SSOT

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
                    "options": _STAGE_CHECKPOINT_OPTIONS,
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

        action = self._apply_pii_outbound(action, _pi_enabled, _pi_redactor, _pi_outbound)
        return action

    @staticmethod
    def log_prompt(project_root: Path, action: dict) -> None:
        """Write the complete LLM prompt to _scratch/prompt-log/ for debugging.

        Produces two files per tick:
        - tick-NNNN-stage-action.json  — raw action JSON (machine-readable)
        - tick-NNNN-stage-prompt.md    — complete prompt as LLM sees it (human-readable)

        DS-15: subagent_prompt is a single self-contained string read from
        prompts/roles/<stage>.md.  No context assembly, no output schema injection.
        expected_format is for Team Lead only, not subagent.
        """
        try:
            log_dir = project_root / "_scratch" / "prompt-log"
            log_dir.mkdir(parents=True, exist_ok=True)
            tick = action.get("tick", 0)
            stage = action.get("stage", action.get("action", "unknown"))

            # 1. Raw JSON
            json_file = log_dir / f"tick-{tick:04d}-{stage}-action.json"
            with open(str(json_file), "w", encoding="utf-8") as f:
                json.dump(action, f, indent=2, ensure_ascii=False)

            # 2. Human-readable prompt
            md_file = log_dir / f"tick-{tick:04d}-{stage}-prompt.md"
            inst = action.get("instruction", "")
            sp = action.get("subagent_prompt", "")
            ef = action.get("expected_format", {})
            spawn = action.get("spawn", {})
            is_spawn = bool(spawn)

            lines = []
            lines.append(f"# Tick {tick} — {stage}")
            lines.append("")
            lines.append(f"- action: `{action.get('action', '?')}`")
            lines.append(f"- spawn stage: {is_spawn}")
            if is_spawn:
                lines.append(f"- spawn count: {spawn.get('count', 1)}")
                lines.append(f"- spawn parallel: {spawn.get('parallel', False)}")
                lines.append(f"- proof token: `{action.get('spawn_proof_token', 'N/A')}`")
                lines.append(f"- effort: `{spawn.get('effort', 'high')}`")
            lines.append("")

            # ── Part 1: Instruction (Team Lead sees this first) ──
            lines.append("---")
            lines.append("## Part 1 — Instruction（Team Lead 收到的命令）")
            lines.append("")
            if inst:
                lines.append("```")
                lines.append(inst)
                lines.append("```")
            else:
                lines.append("*(no instruction — inline stage)*")
            lines.append("")

            # ── Part 2: Subagent Prompt(s) ──
            agents = spawn.get("agents", [])
            if is_spawn:
                lines.append("---")
                if agents:
                    # Multi-agent: show merge instructions + per-agent prompts
                    lines.append("## Part 2a — Merge Instructions（Team Lead 合并指引）")
                    lines.append(f"*(length: {len(sp)} chars)*")
                    lines.append("")
                    lines.append("```")
                    lines.append(sp.strip() if sp else "(empty)")
                    lines.append("```")
                    lines.append("")
                    lines.append(f"## Part 2b — Agent Prompts（{len(agents)} 个 agent，各收到独立 prompt）")
                    lines.append("")
                    for ag in agents:
                        ap = ag.get("prompt", "")
                        lines.append(f"### Agent [{ag['index']}] — {len(ap)} chars")
                        lines.append("")
                        lines.append("```markdown")
                        lines.append(ap.strip())
                        lines.append("```")
                        lines.append("")
                elif sp:
                    # Single agent
                    lines.append("## Part 2 — Subagent Prompt（传给 subagent 的完整文本）")
                    lines.append(f"*(length: {len(sp)} chars)*")
                    lines.append("")
                    lines.append("```")
                    lines.append(sp.strip())
                    lines.append("```")
                    lines.append("")

            # ── Part 3: Expected Format (Team Lead reference, NOT subagent) ──
            if ef:
                lines.append("---")
                lines.append("## Part 3 — Expected Format（Team Lead 写 result 时的字段约束）")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(ef, indent=2, ensure_ascii=False))
                lines.append("```")
                lines.append("")

            # ── Part 4: Gate Summary ──
            gs = action.get("gate_summary", {})
            if gs:
                lines.append("---")
                lines.append("## Part 4 — Gate Results")
                lines.append("")
                for gname, gv in sorted(gs.items()):
                    if isinstance(gv, dict):
                        passed = "✓" if gv.get("passed") else "✗"
                        msg = gv.get("message", "")[:120]
                        lines.append(f"- {gname}: {passed} — {msg}")
                lines.append("")

            with open(str(md_file), "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

        except Exception:
            pass  # best-effort logging, never crash the loop

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

    # DS-15: engine-generated fields that should NOT be PII-scanned.
    # These are assembled from prompt templates and internal state — they never
    # contain real user PII.  Scanning them causes false positives (e.g. spawn
    # proof tokens matching api_key patterns → ***REDACTED*** → broken mechanism).
    _PII_SKIP_FIELDS: frozenset[str] = frozenset({
        "instruction", "subagent_prompt", "expected_format",
        "spawn", "spawn_proof_token", "gate_summary", "feature_status",
        "progress_summary", "feedback",
    })

    def _apply_pii_outbound(self, action: dict, pii_enabled: bool, pii_redactor, pii_outbound: str) -> dict:
        """T109c L2: outbound action JSON PII 脱敏.

        DS-15: 只扫描用户数据字段 (requirement 等)，跳过引擎生成字段。
        redact_dict/scan_dict 递归全量扫描会破坏 spawn proof token 等
        引擎注入的文本。
        """
        if not pii_enabled or not pii_redactor:
            return action
        # Collect user-data fields (everything NOT in _PII_SKIP_FIELDS)
        user_fields = {k: v for k, v in action.items()
                       if k not in self._PII_SKIP_FIELDS and isinstance(v, str)}
        if pii_outbound == "redact":
            for k in user_fields:
                action[k] = pii_redactor.scan_text(action[k])
            return action
        elif pii_outbound in ("warn", "block"):
            findings: list[dict] = []
            for k, v in user_fields.items():
                findings.extend(pii_redactor.scan_dict({k: v}))
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
        """Construct a stage action dict.

        DS-15: subagent prompt is read from prompts/roles/<stage>.md verbatim.
        No context injection, no expected_format for subagent.  Team Lead
        extracts fields from subagent output and maps to result JSON per
        expected_format.

        Spawn proof: engine pre-writes the proof file, instruction references
        the path.  Token is never embedded in instruction text → PII-safe.
        """
        result: dict = {**base, "action": action}
        spawn = _SPAWN_CONFIG.get(action)
        if spawn is not None:
            result["spawn"] = spawn
            # DS-15: spawn proof — pre-write file, reference path in instruction
            import uuid
            proof_token = uuid.uuid4().hex
            result["spawn_proof_token"] = proof_token
            self._write_spawn_proof_file(proof_token, action)

            count = spawn["count"]
            is_multi = count > 1
            multi_inst = _SPAWN_MULTI_INSTRUCTION if is_multi else _SPAWN_SINGLE_INSTRUCTION

            result["instruction"] = _SPAWN_INSTRUCTION.format(
                count=count,
                parallel=" (parallel)" if spawn.get("parallel") else "",
                multi_instruction=multi_inst,
                stage=action,
                effort=spawn.get("effort", "high"),
                proof_token=proof_token,
            )

            # DS-15: read prompt from file
            full_prompt = self._load_prompt(action)

            if is_multi:
                # Split by "***" into N+1 sections.
                # Section 0 = merge instructions (Phase 1+3), Sections 1..N = agent prompts
                sections = full_prompt.split("\n***\n")
                if len(sections) >= count + 1:
                    merge_prompt = sections[0].strip()
                    agent_prompts = [s.strip() for s in sections[1:count+1]]
                else:
                    # Fallback: single prompt replicated to all agents
                    merge_prompt = full_prompt
                    agent_prompts = [full_prompt] * count

                result["subagent_prompt"] = merge_prompt  # merge instructions for Team Lead
                result["spawn"]["agents"] = [
                    {"index": i, "prompt": p}
                    for i, p in enumerate(agent_prompts)
                ]
            else:
                result["subagent_prompt"] = full_prompt

            # T141: spawned field in expected_format (for Team Lead, NOT subagent)
            if expected_format is not None:
                expected_format = {
                    "spawned": "bool — MUST be true after spawning subagent",
                    **expected_format,
                }
        else:
            # Non-spawn stage — inline instruction
            if action not in ("developer",):  # developer has custom instruction
                result["instruction"] = _INLINE_INSTRUCTION.format(stage=action)
        if context:
            result["context"] = context
        if expected_format is not None:
            result["expected_format"] = expected_format
        result.update(extra)
        return result

    # ── DS-15 helpers ──

    def _load_prompt(self, stage: str) -> str:
        """Read prompts/roles/<stage>.md and return its content.

        Falls back to PromptRegistry if the file doesn't exist (for
        backward-compat during migration).
        """
        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "roles" / f"{stage}.md"
        if prompt_path.is_file():
            try:
                return prompt_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                _logger.warning("Failed to read prompt file %s: %s", prompt_path, e)
                return ""
        # Fallback: PromptRegistry (old path, remove after migration)
        try:
            _reg = default_registry()
            return _reg.get(stage) or ""
        except Exception:
            _logger.warning("PromptRegistry fallback failed for stage=%s", stage, exc_info=True)
            return ""

    def _write_spawn_proof_file(self, proof_token: str, stage: str) -> None:
        """DS-15: pre-write spawn proof file so subagent can append to it.

        Engine writes the initial file with status='pending'.  Subagent
        appends stage + timestamp after completing its work.
        """
        import os
        proof_dir = self.project_root / ".ae-state" / "spawn-proofs"
        proof_dir.mkdir(parents=True, exist_ok=True)
        proof_file = proof_dir / f"{proof_token}.json"
        payload = {
            "token": proof_token,
            "stage": stage,
            "status": "pending",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        proof_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # ── stage builders ──

    def _build_action_gap_scan(self, base: dict) -> dict:
        # DS-15: gap_scan prompt is self-contained — subagent uses Read to explore design doc.
        return self._build_stage_action(base, "gap_scan", context={
            "design_doc_path": (
                self._design_doc.path if self._design_doc else None),
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

    def _build_component_map(self) -> dict[str, str]:
        """Build design_section → component_name mapping from design doc.

        Used by architect to resolve section references (e.g. "§6.1" → "VoiceClonePage（主容器）").
        """
        if not self._design_doc:
            return {}
        cmap: dict[str, str] = {}
        for plate in self._design_doc.plates:
            for comp in plate.components:
                if comp.design_section:
                    cmap[comp.design_section] = comp.name
        return cmap

    def _build_action_architect(self, base: dict) -> dict:
        # DS-15: subagent reads design doc + project structure itself.
        # Only pass refine_request if present (cross-tick data).
        extra: dict = {}
        if self._state.refine_request_json:
            extra["feedback"] = {
                "mode": "PLAN_REFINE",
                "refine_request": json.loads(self._state.refine_request_json),
            }
        return self._build_stage_action(base, "architect", expected_format={
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
        # DS-15: subagent reads changed files itself via Read/Grep.
        # Pass only the snapshot reference for Team Lead to relay.
        snap = self._dev_snapshot or {}
        return self._build_stage_action(base, "critic", context={
            "files_changed": snap.get("files_changed", self._state.files_changed),
            "test_results": snap.get("test_results", self._state.test_results),
            "commit_hash": snap.get("commit_hash", self._state.commit_hash),
        }, expected_format={
            "stage": "critic",
            "verdict": "APPROVE | MAJOR",
            "findings": "[{file, line, severity, issue, suggestion}]",
            "critic_feedback": "string",
        })

    def _build_action_component_verifier(self, base: dict) -> dict:
        comp = self._batch_state.current_component()
        # Fix B: collect implementation_files from batch_plan file_targets
        impl_files: list[str] = []
        for b in self._batch_state.batches_for(comp):
            for t in b.get("tasks", []):
                for ft in t.get("file_targets", []):
                    if ft not in impl_files:
                        impl_files.append(ft)
        # Fix C: when design_spec is empty and no impl files, skip verification.
        # DS-14 (T151): 原 `and not impl_files` 逻辑保留 — design_spec 由 T150
        # (fence code block→DesignItem) 保证非空。双空时才 skip，避免过度跳过。
        design_spec = comp.design_spec_summary()
        if not design_spec and not impl_files:
            return {**base, "action": "skip", "reason": "no design items or implementation files for component",
                    "stage": "component_verifier"}
        # DS-15: subagent reads design doc + impl files itself.
        return self._build_stage_action(base, "component_verifier", expected_format={
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
        # DS-15: subagent reads plate components + contracts itself.
        return self._build_stage_action(base, "plate_deep_audit", expected_format={
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
        # DS-15: subagent reads design doc itself.
        return self._build_stage_action(base, "system_verifier", expected_format={
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
        # DS-15: subagent reads project + coverage_map itself.
        return self._build_stage_action(base, "system_deep_audit", expected_format={
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
