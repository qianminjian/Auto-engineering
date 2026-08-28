"""ActionBuilder — 构建 per-tick action JSON (P0-1: 从 TickOrchestrator 提取).

封装 10 个 stage action builder + dispatch + PII outbound 过滤.
TickOrchestrator 委托调用, 不再内联 stage action 构造逻辑.
"""
from __future__ import annotations

import json
import logging
import shlex
import time
from collections.abc import Callable
from copy import copy, deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auto_engineering.config.constants import _SPAWN_CONFIG
from auto_engineering.config.feature_flags import feature_status_for_action
from auto_engineering.config.runtime_config import RuntimeConfig, get_default_config
from auto_engineering.host.runtime_identity import ExecutionIdentity
from auto_engineering.host.spawn_contract import WorkerInvocationSpec
from auto_engineering.loop.actions import business_result_contract
from auto_engineering.loop.design_authority import DesignAuthorityPolicy
from auto_engineering.loop.design_decision_ledger import DesignDecisionLedger
from auto_engineering.loop.effects import (
    EffectExecutor,
    EffectIntent,
    EffectReceipt,
    WriteContentAddressedArtifact,
    WriteJsonArtifact,
)
from auto_engineering.loop.engineering_model import EngineeringModel
from auto_engineering.prompts.architect_context import build_architect_research_context
from auto_engineering.prompts.compiler import (
    CORE_OWNED_OUTPUT_FIELDS,
    compile_prompt_bundle,
)
from auto_engineering.prompts.contracts import default_prompt_contracts
from auto_engineering.prompts.registry import default_registry

# 严格 spawn Action 只描述原生执行事实；证明与 Result 由 Assembler 独占生成。
_SPAWN_INSTRUCTION = (
    "Execute exactly {count} native worker{parallel} from spawn.invocations[] "
    "with requested effort={effort}.\n"
    "Execute every project tool and launch every worker with working directory "
    "{project_root}; never use the plugin or prompt-artifact directory as cwd.\n"
    "{multi_instruction}"
    "Write only native facts to action.host_execution.work_files.outcomes "
    "using the exact wrapper "
    "{{\"outcomes\":[{{worker_id,native_worker_handle,status,payload,summary,"
    "actual_model,isolation_evidence}}]}}. Write only expected_format business fields to "
    "Use the model identifier reported by the native worker API for actual_model; if "
    "that API exposes no model identifier, write actual_model='unreported' exactly, "
    "never null and never infer a model name. "
    "Copy each host_execution.workers[] expected_isolation_evidence exactly into its "
    "outcome; do not copy spawn.invocations[].isolation and do not invent evidence. "
    "action.host_execution.work_files.coordinator_result. Do not write receipt, "
    "attestation, proof, spawned, "
    "spawn_proof_token, or protocol identity fields.\n"
    "Execute action.host_execution.operations.finalize.argv, validate.argv and "
    "submit.argv in order; replace only __AE_BUNDLED_RUNNER__ with the fixed bundled "
    "runner and never rebuild, reorder or copy their path arguments. "
    "Never reuse files from another Action. "
    "The Assembler is the "
    "only proof and Result writer.\n"
    "After tick returns the next Action, discard every prior Action object, work-file "
    "path, worker handle and command argument. Do not print full diffs, prior outcomes "
    "or historical Action JSON during recovery; consume only the structured error and "
    "the active Action.\n"
    "If native spawn reports capacity exhaustion, first wait for known workers to finish "
    "and reclaim their handles when the host supports it, then retry once. If capacity is "
    "still unavailable, report HOST_AGENT_CAPACITY without fabricating a worker result."
    " If any native worker times out or fails, record that native failure in outcomes, "
    "write an empty coordinator payload, and call the same Finalizer; never fabricate "
    "business fields or success evidence."
    " After recording every completed outcome, immediately close or reclaim that native "
    "worker handle before advancing to another Action."
)
_SPAWN_MULTI_INSTRUCTION = (
    "Use each invocation's prompt_ref, prompt_sha256, isolation and receipt_path; "
    "workers return native outcomes only and never write shared state.\n"
)
_SPAWN_SINGLE_INSTRUCTION = (
    "Use spawn.invocations[0] as the only execution contract.\n"
)
# Non-spawn stages (developer, gap_scan inline) use this:
_INLINE_INSTRUCTION = (
    "Do the work for stage '{stage}' per expected_format. "
    "Write result JSON with stage='{stage}'."
)
_CORE_OWNED_RESULT_FIELDS = CORE_OWNED_OUTPUT_FIELDS
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
@dataclass(frozen=True, slots=True)
class ActionBuildContext:
    """一次 Action 构建所需的不可变依赖快照。"""

    state: EngineState
    design_doc: DesignDoc | None = None
    batch_state: BatchState | None = None
    plan: Plan | None = None
    dev_snapshot: dict[str, object] | None = None
    progress_tree: ProgressTree | None = None
    pause_at_stages: frozenset[str] = frozenset()
    passed_checkpoints: frozenset[str] = frozenset()
    last_batch_id: str | None = None


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
        runtime_config: RuntimeConfig | None = None,
        effect_sink: Callable[[EffectReceipt], None] | None = None,
        effect_intent_sink: Callable[[EffectIntent], None] | None = None,
    ) -> None:
        self.project_root = project_root
        self._pii_enabled = pii_enabled
        self._pii_redactor = pii_redactor
        self._pii_outbound = pii_outbound
        self._runtime_config = (
            runtime_config if runtime_config is not None else get_default_config()
        )
        self._effect_sink = effect_sink
        self._effect_intent_sink = effect_intent_sink
        self._bound_context: ActionBuildContext | None = None
        self._design_authority_projection: dict[str, Any] = (
            DesignDecisionLedger(()).effective_projection(())
        )

    # ── public API ──
    def build_action(
        self,
        state: EngineState,
        *,
        design_authority_projection: dict[str, Any] | None = None,
        design_doc: DesignDoc | None = None,
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
        context = ActionBuildContext(
            state=state,
            design_doc=design_doc,
            batch_state=batch_state,
            plan=plan,
            dev_snapshot=dev_snapshot,
            progress_tree=progress_tree,
            pause_at_stages=frozenset(pause_at_stages or ()),
            passed_checkpoints=frozenset(passed_checkpoints or ()),
            last_batch_id=last_batch_id,
        )
        # Per-call PII overrides (local copies — do NOT mutate instance state
        # to avoid cross-tick leakage, P1-12)
        _pi_enabled = pii_enabled if pii_enabled is not None else self._pii_enabled
        _pi_redactor = pii_redactor if pii_redactor is not None else self._pii_redactor
        _pi_outbound = pii_outbound if pii_outbound is not None else self._pii_outbound
        invocation = copy(self)
        invocation._bound_context = context
        invocation._design_authority_projection = (
            deepcopy(design_authority_projection)
            if design_authority_projection is not None
            else DesignDecisionLedger(()).effective_projection(())
        )
        return invocation._build_with_context(
            feedback=feedback,
            pre_gate=pre_gate,
            pii_enabled=_pi_enabled,
            pii_redactor=_pi_redactor,
            pii_outbound=_pi_outbound,
        )

    def _build_with_context(
        self,
        *,
        feedback: str | None,
        pre_gate: dict | None,
        pii_enabled: bool,
        pii_redactor: PIIRedactor | None,
        pii_outbound: str,
    ) -> dict:
        state = self._state
        stage = state.current_stage

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
            "project_setup": self._build_action_project_setup,
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

        action = self._apply_pii_outbound(
            action,
            pii_enabled,
            pii_redactor,
            pii_outbound,
        )
        return action

    def _build_action_project_setup(self, base: dict) -> dict:
        """项目能力不足时让宿主完成搭建；Core 不生成脚手架。"""
        missing_capabilities = list(self._state.missing_project_capabilities)
        capability_hints = [
            "仅处理以下缺失能力：" + "、".join(missing_capabilities) + "。"
        ]
        if "eslint_flat_config" in missing_capabilities:
            capability_hints.append("为 ESLint 9 创建 flat config。")
        if "eslint_effective_config" in missing_capabilities:
            capability_hints.append(
                "配置至少一组实际生效的推荐规则，禁止用空配置绕过 lint。"
            )
        if "jsdom_dependency" in missing_capabilities:
            capability_hints.append("补齐测试环境的直接 jsdom 开发依赖。")
        expected_format = {
            "result_type": "project_setup_completed",
            "artifacts": ["创建或确认的项目入口文件与源码目录"],
        }
        return {
            **base,
            "action": "project_setup_required",
            "stage": "project_setup",
            "reason_code": "insufficient_project_evidence",
            "missing_capabilities": missing_capabilities,
            "constraints": {
                "must_follow_design": self._design_doc is not None,
                "must_not_assume_framework": True,
                "git_is_optional_evidence_provider": True,
                "must_not_run_git_init_or_stage_without_user_authorization": True,
            },
            "instruction": (
                f"所有项目工具以 {self.project_root.resolve()} 为工作目录；不得在插件目录执行。"
                "根据需求与设计文档建立缺失的项目工程能力。完成后提交 "
                "result_type='project_setup_completed' 和 artifacts；stage 等消息身份由 Core 写入；"
                "Core 将重新探测文件，不采信文字声明。"
                + "".join(capability_hints)
                + "Git 仅是可选证据源，未经用户授权不得执行 git init/add/commit。"
            ),
            "expected_format": expected_format,
            "result_contract": business_result_contract(
                "project_setup",
                expected_format,
            ),
        }

    @property
    def _context(self) -> ActionBuildContext:
        if self._bound_context is None:
            raise RuntimeError("ActionBuilder 缺少 invocation context")
        return self._bound_context

    @property
    def _state(self) -> EngineState:
        return self._context.state

    @property
    def _design_doc(self) -> DesignDoc | None:
        return self._context.design_doc

    def _engineering_model(self) -> EngineeringModel | None:
        if (
            self._design_doc is None
            or not self._state.design_doc_digest.startswith("sha256:")
        ):
            return None
        return EngineeringModel.from_design_doc(
            self._design_doc,
            design_digest=self._state.design_doc_digest,
        )

    def _engineering_sections(
        self,
        references: list[str] | None = None,
    ) -> list[dict[str, str | None]]:
        model = self._engineering_model()
        if model is None:
            return []
        if references is None:
            return model.action_sections()
        selected_ids = {
            section.section_id for section in model.select_sections(references)
        }
        return [
            section
            for section in model.action_sections()
            if section["section_id"] in selected_ids
        ]

    def _last_batch_design_references(self) -> list[str]:
        if self._batch_state is None:
            return []
        batch = next(
            (
                item
                for item in self._batch_state.batch_plan
                if item.get("batch_id") == self._last_batch_id
            ),
            None,
        )
        if batch is None:
            return []
        return [
            str(reference)
            for reference in batch.get("design_sections", [])
            if isinstance(reference, str)
        ]

    @property
    def _batch_state(self) -> BatchState | None:
        return self._context.batch_state

    @property
    def _plan(self) -> Plan | None:
        return self._context.plan

    @property
    def _dev_snapshot(self) -> dict[str, object] | None:
        return self._context.dev_snapshot

    @property
    def _progress_tree(self) -> ProgressTree | None:
        return self._context.progress_tree

    @property
    def _pause_at_stages(self) -> frozenset[str]:
        return self._context.pause_at_stages

    @property
    def _passed_checkpoints(self) -> frozenset[str]:
        return self._context.passed_checkpoints

    @property
    def _last_batch_id(self) -> str | None:
        return self._context.last_batch_id

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
        from auto_engineering.loop.prompt_logger import write_action_prompt_log

        write_action_prompt_log(project_root, action)

    def progress_summary(
        self,
        state: EngineState,
        *,
        batch_state: BatchState | None = None,
    ) -> str:
        """以显式输入生成进度摘要，不依赖上一次 build_action 调用。"""

        invocation = copy(self)
        invocation._bound_context = ActionBuildContext(
            state=state,
            batch_state=batch_state,
        )
        return invocation._progress_summary()

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
        "instruction", "subagent_prompt", "expected_format", "result_contract",
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
        base = {
            "tick": self._state.tick + 1,
            "stage": self._state.current_stage,
            "thread_id": self._state.thread_id,
            # Host tools may change cwd. Protocol execution must not inherit it.
            "project_root": str(self.project_root.resolve()),
            "gate_summary": self._state.gate_results,
            "feedback": feedback,
            "requirement": self._state.requirement,
            "feature_status": feature_status_for_action(
                self._runtime_config.environ,
            ),
            "progress_summary": (
                self._progress_tree.summary() if self._progress_tree else None
            ),
        }
        summary = self._gap_scan_summary()
        if summary is not None:
            base["gap_scan_summary"] = summary
        return base

    def _gap_scan_summary(self) -> dict[str, object] | None:
        """把已接受的 Gap Scan 结论作为有界前台事实投影到相邻 Action。"""
        if self._state.current_stage not in {"gap_review", "research", "architect"}:
            return None
        raw = self._state.gap_report_json
        if not raw:
            return None
        report = json.loads(raw)
        if not report.get("design_doc_digest"):
            return None
        gaps = report.get("gaps", [])
        if self._state.current_stage == "gap_review":
            outcome = "user_decision_required"
        elif self._state.current_stage == "research":
            outcome = "research_in_progress"
        elif gaps:
            outcome = "gaps_resolved"
        else:
            outcome = "no_gaps_auto_continue"
        return {
            "design_doc_digest": report.get("design_doc_digest", ""),
            "scanned_sections": report.get("scanned_sections", 0),
            "gap_count": len(gaps),
            "has_blocking": bool(report.get("has_blocking", False)),
            "outcome": outcome,
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
        authority = DesignAuthorityPolicy.default().to_dict()
        ledger = deepcopy(self._design_authority_projection)
        result["design_authority"] = authority
        result["design_decision_ledger"] = ledger
        result["execution_identity"] = ExecutionIdentity.coordinator(
            stage=action,
        ).to_dict()
        compiled_prompt = False
        contract = default_prompt_contracts().get(action)
        if contract is not None:
            context = dict(context or {})
            if "design_authority" in contract.optional_context:
                context.setdefault("design_authority", authority)
            if "design_decision_ledger" in contract.optional_context:
                context.setdefault("design_decision_ledger", ledger)
        spawn_template = _SPAWN_CONFIG.get(action)
        if spawn_template is not None:
            spawn = deepcopy(spawn_template)
            audit_files = (
                context.get("audit_scope", {}).get("files", [])
                if isinstance(context, dict)
                and isinstance(context.get("audit_scope"), dict)
                else []
            )
            compact_system_audit = (
                action == "system_deep_audit"
                and isinstance(audit_files, list)
                and len(audit_files) <= 20
            )
            if compact_system_audit:
                spawn.update({"count": 1, "parallel": False, "effort": "high"})
                result["audit_execution_profile"] = {
                    "profile": "compact",
                    "audited_file_count": len(audit_files),
                    "dimension_count": 5,
                }
            elif action == "system_deep_audit":
                result["audit_execution_profile"] = {
                    "profile": "specialist",
                    "audited_file_count": len(audit_files),
                    "dimension_count": 5,
                }
            result["spawn"] = spawn
            result["spawn"]["contract_version"] = "1.0"
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
                project_root=shlex.quote(str(self.project_root.resolve())),
            )

            # DS-15: read prompt from file
            full_prompt = self._load_prompt(action)
            worker_expected_format = dict(expected_format or {})
            coordinator_expected_format = dict(worker_expected_format)

            if is_multi:
                contract = default_prompt_contracts()[action]
                bundle = compile_prompt_bundle(
                    contract=contract,
                    role_prompt=full_prompt,
                    context=dict(context or {}),
                    expected_format=worker_expected_format,
                )
                result["subagent_prompt"] = bundle.coordinator_prompt
                result.setdefault("extensions", {})[
                    "context_manifest"
                ] = bundle.context_manifest
                agents: list[dict] = []
                for worker in bundle.worker_prompts:
                    receipt_token = uuid.uuid4().hex
                    self._write_spawn_proof_file(receipt_token, action)
                    agents.append({
                        "index": worker.index,
                        "role": worker.role,
                        "prompt_ref": self._write_prompt_artifact(
                            worker.prompt, worker.prompt_hash
                        ),
                        "prompt_hash": worker.prompt_hash,
                        "receipt_token": receipt_token,
                        "receipt_path": (
                            f".ae-state/spawn-proofs/{receipt_token}.json"
                        ),
                        "requested_effort": spawn.get("effort", "high"),
                        "execution_identity": worker.execution_identity,
                    })
                result["spawn"]["agents"] = agents
                result["spawn"]["invocations"] = [
                    WorkerInvocationSpec(
                        worker_id=f"{action}-{worker['index']}",
                        role=str(worker["role"]),
                        prompt_ref=str(worker["prompt_ref"]),
                        prompt_sha256=str(worker["prompt_hash"]),
                        requested_effort=str(worker["requested_effort"]),
                        isolation="fresh_context",
                        capabilities={
                            "may_drive_loop": False,
                            "may_spawn_workers": False,
                        },
                        receipt_path=str(worker["receipt_path"]),
                    ).to_dict()
                    for worker in agents
                ]
                compiled_prompt = True
            else:
                single_contract = default_prompt_contracts().get(action)
                if compact_system_audit and single_contract is not None:
                    from auto_engineering.prompts.contracts import (
                        ExecutionMode,
                        StagePromptContract,
                    )

                    role_sections = full_prompt.split("\n***\n")
                    compact_role_prompt = (
                        "你是小型项目五维系统审计 Worker。必须在同一个隔离上下文中完成："
                        "架构合理性、代码质量、工程化规范、虚化实现、团队与设计覆盖。"
                        "逐维执行下列清单，最后合并去重并直接按输出契约返回；不得遗漏维度。\n\n"
                        + "\n\n".join(role_sections[1:])
                    )
                    compact_contract = StagePromptContract(
                        stage=single_contract.stage,
                        execution_mode=ExecutionMode.SINGLE_WORKER,
                        required_context=single_contract.required_context,
                        worker_roles=("system_audit_compact",),
                        optional_context=single_contract.optional_context,
                        artifact_kinds=single_contract.artifact_kinds,
                        max_context_bytes=single_contract.max_context_bytes,
                    )
                    bundle = compile_prompt_bundle(
                        contract=compact_contract,
                        role_prompt=compact_role_prompt,
                        context=dict(context or {}),
                        expected_format=worker_expected_format,
                    )
                    result["subagent_prompt"] = bundle.worker_prompts[0].prompt
                    result["worker_execution_identity"] = (
                        bundle.worker_prompts[0].execution_identity
                    )
                    worker = bundle.worker_prompts[0]
                    receipt_token = uuid.uuid4().hex
                    self._write_spawn_proof_file(receipt_token, action)
                    prompt_ref = self._write_prompt_artifact(
                        worker.prompt, worker.prompt_hash,
                    )
                    result["spawn"]["invocations"] = [
                        WorkerInvocationSpec(
                            worker_id=f"{action}-0",
                            role=worker.role,
                            prompt_ref=prompt_ref,
                            prompt_sha256=worker.prompt_hash,
                            requested_effort=str(spawn.get("effort", "high")),
                            isolation="fresh_context",
                            capabilities={
                                "may_drive_loop": False,
                                "may_spawn_workers": False,
                            },
                            receipt_path=(
                                f".ae-state/spawn-proofs/{receipt_token}.json"
                            ),
                        ).to_dict()
                    ]
                    result.setdefault("extensions", {})[
                        "context_manifest"
                    ] = bundle.context_manifest
                    compiled_prompt = True
                elif single_contract is not None and action in {
                    "architect", "developer", "critic", "component_verifier",
                    "system_verifier",
                }:
                    prompt_context = dict(context or {})
                    prompt_context.setdefault("requirement", base.get("requirement"))
                    prompt_context.setdefault("feedback", base.get("feedback"))
                    bundle = compile_prompt_bundle(
                        contract=single_contract,
                        role_prompt=full_prompt,
                        context=prompt_context,
                        expected_format=worker_expected_format,
                    )
                    result["subagent_prompt"] = bundle.worker_prompts[0].prompt
                    result["worker_execution_identity"] = (
                        bundle.worker_prompts[0].execution_identity
                    )
                    worker = bundle.worker_prompts[0]
                    receipt_token = uuid.uuid4().hex
                    self._write_spawn_proof_file(receipt_token, action)
                    prompt_ref = self._write_prompt_artifact(
                        worker.prompt, worker.prompt_hash,
                    )
                    result["spawn"]["invocations"] = [
                        WorkerInvocationSpec(
                            worker_id=f"{action}-0",
                            role=worker.role,
                            prompt_ref=prompt_ref,
                            prompt_sha256=worker.prompt_hash,
                            requested_effort=str(spawn.get("effort", "high")),
                            isolation="fresh_context",
                            capabilities={
                                "may_drive_loop": False,
                                "may_spawn_workers": False,
                            },
                            receipt_path=(
                                f".ae-state/spawn-proofs/{receipt_token}.json"
                            ),
                        ).to_dict()
                    ]
                    result.setdefault("extensions", {})[
                        "context_manifest"
                    ] = bundle.context_manifest
                    compiled_prompt = True
                else:
                    result["subagent_prompt"] = full_prompt
                    prompt_hash = __import__("hashlib").sha256(
                        full_prompt.encode("utf-8")
                    ).hexdigest()
                    receipt_token = uuid.uuid4().hex
                    self._write_spawn_proof_file(receipt_token, action)
                    result["spawn"]["invocations"] = [
                        WorkerInvocationSpec(
                            worker_id=f"{action}-0",
                            role=action,
                            prompt_ref=self._write_prompt_artifact(
                                full_prompt, prompt_hash,
                            ),
                            prompt_sha256=prompt_hash,
                            requested_effort=str(spawn.get("effort", "high")),
                            isolation="fresh_context",
                            capabilities={
                                "may_drive_loop": False,
                                "may_spawn_workers": False,
                            },
                            receipt_path=(
                                f".ae-state/spawn-proofs/{receipt_token}.json"
                            ),
                        ).to_dict()
                    ]

            # T141: spawned field in expected_format (for Team Lead, NOT subagent)
            if expected_format is not None:
                expected_format = coordinator_expected_format
        else:
            # Non-spawn stage — inline instruction
            if action not in ("developer",):  # developer has custom instruction
                result["instruction"] = _INLINE_INSTRUCTION.format(stage=action)
        if context and not compiled_prompt:
            result["context"] = context
            # P1 优化 (2026-07-26 提示词分析): 把任务上下文直接拼进 subagent_prompt 头部，
            # 让 subagent 第一时间看到聚焦对象（哪个组件/板块/文件），减少推断成本。
            # （F8 已注入 action.context，本优化进一步拼进 subagent 实际收到的 prompt。）
            if result.get("subagent_prompt") and not compiled_prompt:
                ctx_lines = []
                for k, v in context.items():
                    if not v:
                        continue
                    sv = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                    ctx_lines.append(f"  - {k}: {sv}")
                if ctx_lines:
                    preamble = (
                        "## 本次任务上下文（编排器注入，优先聚焦）\n"
                        + "\n".join(ctx_lines) + "\n\n")
                    result["subagent_prompt"] = preamble + result["subagent_prompt"]
        if expected_format is not None:
            result["expected_format"] = {
                key: value
                for key, value in expected_format.items()
                if key not in _CORE_OWNED_RESULT_FIELDS
            }
            result_contract = business_result_contract(
                action,
                result["expected_format"],
            )
            if result_contract is not None:
                result["result_contract"] = result_contract
        result.update(extra)
        return result

    def _write_prompt_artifact(self, prompt: str, prompt_hash: str) -> str:
        """内容寻址保存 Worker prompt，避免全部正文进入 Coordinator Action。"""
        receipt = self._execute_effect(
            WriteContentAddressedArtifact(
                kind="prompt",
                content=prompt,
                sha256=prompt_hash,
            )
        )
        return receipt.relative_path

    def _execute_effect(self, intent: EffectIntent) -> EffectReceipt:
        if self._effect_intent_sink is not None:
            self._effect_intent_sink(intent)
        receipt = EffectExecutor(self.project_root).execute(intent)
        if self._effect_sink is not None:
            self._effect_sink(receipt)
        return receipt

    # ── DS-15 helpers ──

    def _load_prompt(self, stage: str) -> str:
        """Read prompts/roles/<stage>.md, preferring the PromptRegistry combination.

        P2 优化 (2026-07-26 提示词分析): 优先用 PromptRegistry 的组合 prompt——
        它剥离 frontmatter（否则 frontmatter 文本会原样发给 subagent）并注入 frontmatter
        声明的共享 fragments（如 critic 的 severity_rubric / letter_vs_spirit）。此前直接读
        原始文件，frontmatter 当正文发出、声明的 fragments 未注入。registry 失败回退读原文件。
        """
        # 优先: PromptRegistry 组合 prompt（fragments 注入 + frontmatter 剥离）
        try:
            combined = default_registry().get(stage)
            if combined:
                return combined
        except Exception:
            _logger.warning("PromptRegistry get failed for stage=%s, fallback to raw file",
                            stage, exc_info=True)
        # 回退: 读原始文件
        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "roles" / f"{stage}.md"
        if prompt_path.is_file():
            try:
                return prompt_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                _logger.warning("Failed to read prompt file %s: %s", prompt_path, e)
        return ""

    def _write_spawn_proof_file(self, proof_token: str, stage: str) -> None:
        """DS-15: pre-write spawn proof file so subagent can append to it.

        Engine writes the initial file with status='pending'.  Subagent
        appends stage + timestamp after completing its work.
        """
        payload = {
            "token": proof_token,
            "stage": stage,
            "status": "pending",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._execute_effect(WriteJsonArtifact(
            relative_path=f"spawn-proofs/{proof_token}.json",
            payload=payload,
        ))
        self._execute_effect(WriteJsonArtifact(
            relative_path=f"spawn-challenges/{proof_token}.json",
            payload=payload,
        ))

    def bind_spawn_proofs(self, action: dict) -> None:
        """在 Action 获得协议身份后，把所有 proof 绑定到该 Action。"""
        token_roles = [(action.get("spawn_proof_token"), "total", None)]
        spawn = action.get("spawn")
        if isinstance(spawn, dict):
            agents = spawn.get("agents", [])
            if isinstance(agents, list):
                token_roles.extend(
                    (
                        agent.get("receipt_token"),
                        "worker",
                        agent.get("requested_effort"),
                    )
                    for agent in agents
                    if isinstance(agent, dict)
                )
        for token, proof_role, requested_effort in token_roles:
            if not isinstance(token, str) or not token:
                continue
            proof_file = (
                self.project_root / ".ae-state" / "spawn-proofs"
                / f"{token}.json"
            )
            challenge_file = (
                self.project_root / ".ae-state" / "spawn-challenges"
                / f"{token}.json"
            )
            try:
                payload = json.loads(proof_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"SPAWN_PROOF_BIND_FAILED: {token}") from exc
            payload.update({
                "token": token,
                "thread_id": action["thread_id"],
                "action_message_id": action["message_id"],
                "stage": action["stage"],
                "proof_role": proof_role,
            })
            if requested_effort is not None:
                payload["requested_effort"] = requested_effort
            self._execute_effect(WriteJsonArtifact(
                relative_path=f"spawn-proofs/{token}.json",
                payload=payload,
            ))
            try:
                challenge_payload = json.loads(
                    challenge_file.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"SPAWN_CHALLENGE_BIND_FAILED: {token}") from exc
            challenge_payload.update({
                "token": token,
                "thread_id": action["thread_id"],
                "action_message_id": action["message_id"],
                "stage": action["stage"],
                "proof_role": proof_role,
            })
            if requested_effort is not None:
                challenge_payload["requested_effort"] = requested_effort
            self._execute_effect(WriteJsonArtifact(
                relative_path=f"spawn-challenges/{token}.json",
                payload=challenge_payload,
            ))

    # ── stage builders ──

    def _build_action_gap_scan(self, base: dict) -> dict:
        engineering_model = self._engineering_model()
        design_sections = (
            engineering_model.action_sections()
            if engineering_model is not None
            else []
        )
        host_design_sections = (
            engineering_model.host_sections()
            if engineering_model is not None
            else []
        )
        action = self._build_stage_action(base, "gap_scan", context={
            "design_doc_path": (
                self._design_doc.path if self._design_doc else None),
            "project_root": str(self.project_root),
            "requirement": self._state.requirement,
            "project_profile_summary": self._project_profile_summary(),
            "design_authority": DesignAuthorityPolicy.default().to_dict(),
            "design_doc_digest": self._state.design_doc_digest,
            "design_sections": design_sections,
            "host_design_sections": host_design_sections,
        }, expected_format={
            "gaps": (
                "[{id, design_section_ref, grade, clarity, summary, depends_on, "
                "evidence, problem_statement, impact, dependencies, "
                "recommendation:{resolution,reason,confidence}, "
                "options:[{resolution,meaning,enabled,disabled_reason?}], "
                "blocking_rule}]"
            ),
            "section_findings": (
                "[{section_ref, verdict:clear|gap, evidence:[非空证据]}]；"
                "section_ref 必须逐项覆盖 host_design_sections"
            ),
        })
        return self._compile_inline_action(action, "gap_scan")

    def _build_action_gap_review(self, base: dict) -> dict:
        report = json.loads(self._state.gap_report_json or '{"gaps": []}')
        is_rereview = bool(self._state.research_archive)
        gaps = report.get("gaps", [])
        unresolved = [
            gap for gap in gaps
            if gap.get("resolution") not in {"fill", "defer"}
        ]
        current_gap = unresolved[0] if unresolved else {}
        current_index = next(
            (
                index for index, gap in enumerate(gaps)
                if gap.get("id") == current_gap.get("id")
            ),
            len(gaps),
        )
        auto_decision = None
        recommendation = current_gap.get("recommendation")
        if (
            self._state.gap_decision_policy == "remaining_recommendations"
            and isinstance(recommendation, dict)
            and recommendation.get("resolution")
        ):
            auto_decision = {
                "gap_id": current_gap.get("id"),
                "resolution": recommendation["resolution"],
                "decision_source": "thread_policy",
                "policy": "remaining_recommendations",
            }
        return self._build_stage_action(base, "gap_review",
            mode="wizard",
            current_gap_index=current_index,
            total_gaps=len(gaps),
            current_gap=current_gap,
            decisions_so_far=list(self._state.pending_gap_decisions),
            has_blocking=report.get("has_blocking", False),
            is_rereview=is_rereview,
            research_findings=dict(self._state.research_archive),
            auto_decision=auto_decision,
            instruction=(
                "Gap Review 单项向导：当前只处理 current_gap，不展示或询问其他缺口。"
                "依次向用户说明问题、设计依据、影响、Loop 推荐及理由、合法选项；"
                "只提交一个 decision，禁止代用户选择或填默认值。"
                "Fill 必须包含可写入设计的 fill_content；Research 必须说明查证目标；"
                "architectural blocking gap 禁止纯 Defer。复审时呈现该 gap 的研究发现。"),
            expected_format={
                "decision": {
                    "gap_id": "必须等于 action.current_gap.id",
                    "resolution": "Fill|Research|Defer|Defer+Research",
                    "user_note": "用户原始判断",
                    "fill_content": "Fill 时必填",
                    "decision_source": "user",
                    "apply_to_remaining": "可选 recommendations；仅当前线程后续 Gap",
                },
            })

    def _build_action_research(self, base: dict) -> dict:
        report = json.loads(self._state.gap_report_json or '{"gaps": []}')
        by_id = {g["id"]: g for g in report.get("gaps", [])}
        current_id = (
            self._state.pending_research_ids[0]
            if self._state.pending_research_ids else None)
        gap = by_id.get(current_id, {}) if current_id else {}
        research_gap = {
            "id": gap.get("id"),
            "design_section_ref": gap.get("design_section_ref"),
            "grade": gap.get("grade"),
            "summary": gap.get("summary"),
        }
        knowledge_sources = {
            "tier_order": [
                "tier0", "tier1_ref_code", "tier2_doc_kb", "tier3_web"],
            "memory_constraint": (
                "grep 定位 → 50-200 行 Read → 丢弃; 禁止批量/并行扫描"),
        }
        action = self._build_stage_action(base, "research",
            context={
                "gap": research_gap,
                "knowledge_sources": knowledge_sources,
                "requirement": self._state.requirement,
                "design_authority": DesignAuthorityPolicy.default().to_dict(),
            },
            required_capabilities=["web_search"],
            gap=research_gap,
            knowledge_sources=knowledge_sources,
            expected_format={
                "findings": "string",
                "sources": "[{tier, ref, note}]",
                "source_tier": "tier0|tier1|tier2|tier3",
                "confidence": "high|medium|low",
                "recommended_design": "string (可注入 supplement)",
                "search_status": "used|unavailable|failed|not_needed",
                "search_error": "string|null",
            })
        return self._compile_inline_action(action, "research")

    def _compile_inline_action(self, action: dict, stage: str) -> dict:
        """用中央角色和契约替换 inline stage 的重复硬编码指令。"""

        bundle = compile_prompt_bundle(
            contract=default_prompt_contracts()[stage],
            role_prompt=self._load_prompt(stage),
            context=action["context"],
            expected_format=action["expected_format"],
        )
        action["instruction"] = bundle.coordinator_prompt
        action["instruction"] = (
            "Execute every project tool with working directory "
            f"{shlex.quote(str(self.project_root.resolve()))}; never use the plugin "
            "or prompt-artifact directory as cwd.\n\n"
            + action["instruction"]
        )
        return action

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

    def _valid_plate_keys(self) -> list[str]:
        """Architect 可选择的稳定组件路由键，顺序遵循设计文档。"""
        if self._design_doc is None:
            return []
        return [
            component.name
            for plate in self._design_doc.plates
            for component in plate.components
        ]

    def _batch_id_policy(self) -> dict[str, object]:
        """Return the deterministic batch ID allocation facts for Architect."""
        baseline = self._state.architecture_baseline or {}
        raw_batches = [
            *list(baseline.get("batch_plan", [])),
            *list(self._state.batch_plan),
        ]
        reserved = sorted({
            batch_id
            for item in raw_batches
            if isinstance(item, dict)
            and isinstance((batch_id := item.get("batch_id")), str)
            and batch_id
        })
        numeric_ids = [
            int(batch_id[1:])
            for batch_id in reserved
            if batch_id.startswith("B") and batch_id[1:].isdigit()
        ]
        next_numeric_id = max(numeric_ids, default=0) + 1
        return {
            "reserved_batch_ids": reserved,
            "next_numeric_id": next_numeric_id,
            "allocation_rule": (
                f"从 B{next_numeric_id} 起连续分配，禁止复用 reserved_batch_ids"
            ),
        }

    def _project_profile_summary(self, *, verifier: bool = False) -> dict:
        """Return the bounded, role-facing subset of the normalized profile.

        Evidence digests, provider diagnostics and schema internals intentionally
        stay in engine state; repeating them in every prompt wastes context and
        invites workers to reinterpret the resolver's decision.
        """
        profile = self._state.project_profile or {}
        commands = profile.get("commands", {})
        if verifier and isinstance(commands, dict):
            commands = {
                name: command
                for name, command in commands.items()
                if name in {"lint", "type_check", "test", "build"}
            }
        return {
            "profile_id": self._state.project_profile_id,
            "project": profile.get("project", {}),
            "paths": profile.get("paths", {}),
            "commands": commands if isinstance(commands, dict) else {},
        }

    def _build_action_architect(self, base: dict) -> dict:
        # DS-15: subagent reads design doc + project structure itself.
        # Only pass refine_request if present (cross-tick data).
        extra: dict = {}
        reconciliation = self._state.state_reconciliation or {}
        is_reconcile = (
            reconciliation.get("status") == "selected"
            and reconciliation.get("choice") == "reconcile"
        )
        if is_reconcile:
            baseline = self._state.architecture_baseline or {}
            extra["feedback"] = {
                "mode": "PLAN_RECONCILE",
                "reconcile_request": {
                    "source_revision": baseline.get("revision", 1),
                    "old_batch_plan": list(self._state.batch_plan),
                    "gate_results": dict(self._state.gate_results),
                    "intent": reconciliation.get("intent", {}),
                    "allowed_statuses": [
                        "verified_completed",
                        "still_pending",
                        "superseded",
                        "unverifiable",
                    ],
                },
            }
        elif self._state.refine_request_json:
            extra["feedback"] = {
                "mode": "PLAN_REFINE",
                "refine_request": json.loads(self._state.refine_request_json),
            }
        incoming_feedback = base.get("feedback")
        if isinstance(incoming_feedback, str) and incoming_feedback.startswith(
            "RESULT_REPAIR："
        ):
            if isinstance(extra.get("feedback"), dict):
                extra["feedback"]["validation_error"] = incoming_feedback
            else:
                extra["feedback"] = {
                    "mode": "RESULT_REPAIR",
                    "validation_error": incoming_feedback,
                }
        research_context = build_architect_research_context(
            self._state.design_supplements_json, self._state.research_archive
        )
        if research_context:
            extra["research_and_design_context"] = research_context
        extra["design_authority"] = DesignAuthorityPolicy.default().to_dict()
        is_refine = bool(self._state.refine_request_json) and not is_reconcile
        batch_id_policy = self._batch_id_policy()
        extra["batch_id_policy"] = batch_id_policy
        if is_refine:
            baseline = self._state.architecture_baseline or {}
            refine_request = json.loads(self._state.refine_request_json or "{}")
            required_source_refs = [
                gap["source_ref"]
                for gap in refine_request.get("gaps", [])
                if isinstance(gap, dict)
                and isinstance(gap.get("source_ref"), str)
                and gap["source_ref"]
            ]
            extra["repair_contract"] = {
                "active_revision": self._state.plan_refine_count,
                "inherited_obligations": list(baseline.get("obligations", [])),
                "required_source_refs": required_source_refs,
                "mapping_policy": (
                    "逐项映射 required_source_refs：每项必须建立 obligation，"
                    "同时绑定 implementation target 与 test/contract_test target"
                ),
                "valid_plate_keys": self._valid_plate_keys(),
                "batch_id_policy": batch_id_policy,
                "batch_template": {
                    "batch_id": "B<n>",
                    "batch_title": "string",
                    "plate_keys": ["valid_plate_key"],
                    "design_sections": ["string"],
                    "tasks": ["task_template"],
                    "depends_on": [],
                },
                "task_template": {
                    "id": "B<n>-T<n>",
                    "description": "string",
                    "kind": "implementation|test|contract_test",
                    "module_ref": "string",
                    "file_targets": ["path"],
                },
            }
        expected_plan = ({
            "result_type": "plan_reconciliation",
            "source_revision": "integer (等于 reconcile_request.source_revision)",
            "classifications": (
                "[{task_id,status,evidence_ref?或reason?}]（旧任务逐项且仅一次）"
            ),
            "new_batch_plan": (
                "[{batch_id,batch_title,plate_keys:[valid_plate_key],"
                "design_sections:[string],tasks:[...],depends_on}]"
            ),
        } if is_reconcile else {
            "plan_patch": (
                "{add_batches:[{batch_id, batch_title, "
                "plate_keys:[valid_plate_key], design_sections:[string], "
                "tasks:[...], depends_on}], "
                "obligation_updates?:[{source_ref, "
                "add_implementation_targets?:[task_id], "
                "add_verification_targets?:[test_task_id], "
                "add_contract_refs?:[name]}]}"
                "（只新增 revision 唯一 batch；batch_id 必须服从 batch_id_policy）"
            )
        } if is_refine else {
            "batch_plan": (
                "[{batch_id, batch_title, plate_keys:[valid_plate_key], "
                "design_sections:[string], "
                "tasks:[{id, description, module_ref, file_targets}], "
                "depends_on}] (min 1 batch)"
            )
        })
        return self._build_stage_action(base, "architect", context={
            "requirement": self._state.requirement,
            "design_doc_path": (
                self._design_doc.path if self._design_doc else None
            ),
            "valid_plate_keys": self._valid_plate_keys(),
            "engineering_sections": self._engineering_sections(),
            "batch_id_policy": batch_id_policy,
            "project_profile_summary": self._project_profile_summary(),
            **({"plan_revision": self._state.plan_refine_count} if is_refine else {}),
            "feedback": extra.get("feedback", base.get("feedback")),
            "research_and_design_context": research_context,
            "design_authority": extra["design_authority"],
        }, expected_format={
            "design_change_requests": (
                "仅当 advisory 必须改变 binding design 时，只输出 1 项："
                "[{source:research|agent_assumption,source_ref,"
                "requested_authority:binding,change_summary,affected_design_refs:[string]}]；"
                "该分支不同时输出 plan/batch_plan/plan_patch"
            ),
            "plan": "string (markdown, min 50 chars)",
            **expected_plan,
            "file_list": "[string] (min 1 file)",
            "contracts": (
                "{name:{kind,path?,method?,request?,response?,status_codes?}}"
                "（每个值必须为 object，可为空）"
            ),
            "obligations": (
                (
                    "逐项映射 repair_contract.required_source_refs；每项必须同时绑定"
                    "实现任务与 test/contract_test 任务。[] 仅表示没有新增义务；"
                    "历史 obligation 自动继承；只提交新 source_ref 的义务，"
                    "已有 source_ref 的目标增量写入 plan_patch.obligation_updates"
                ) if is_refine else (
                    "[{id,source_ref,summary,implementation_targets:[task_id],"
                    "verification_targets:[test_task_id],contract_refs:[name]}]；"
                    "research_and_design_context 非空时必须逐 source_ref 覆盖"
                )
            ),
            "decision_impacts": (
                "[{decision_id,impact:preserve|approved_change,"
                "approved_change_id?}]（ledger 有 binding decision 时逐项提交）"
            ),
        }, valid_plate_keys=self._valid_plate_keys(), **extra)

    def _build_action_developer(self, base: dict) -> dict:
        raw_tasks = (
            self._batch_state.current_batch_tasks(self._plan)
            if self._batch_state and self._plan
            else (self._plan.get_tasks_by_stage("developer")
                  if self._plan else [])
        )
        component = (
            self._batch_state.current_component_name()
            if self._batch_state else None)
        batch_id = (
            self._batch_state.current_batch_id()
            if self._batch_state else None)
        design_references = (
            list(self._batch_state.current_batch().get("design_sections", []))
            if self._batch_state else []
        )
        task_dicts = [
            {"id": t.id, "description": t.description,
             "expected_output": t.expected_output,
             "file_targets": list(t.target_files),
             "depends_on": t.depends_on}
            for t in raw_tasks
        ]
        action = self._build_stage_action(base, "developer",
            context={
                "requirement": self._state.requirement,
                "feedback": base.get("feedback") or self._state.open_findings,
                "batch_id": batch_id,
                "component": component,
                "tasks": task_dicts,
                "engineering_sections": self._engineering_sections(
                    design_references
                ) if design_references else [],
                "task_guidance": (
                    "按列出的 task 逐项执行"
                    if task_dicts else
                    "无 task 明细；不得虚构任务，先依据 plan 和设计文档确认范围"
                ),
                "project_profile_summary": self._project_profile_summary(),
                "git_authorized": False,
            },
            expected_format={
                "stage": "developer",
                "batch_id": "string",
                "files_changed": "[string]",
                "commit_hash": "string (仅实际获授权提交时填写，否则为空)",
                "test_results": "{passed:int, failed:0, total:int}",
                "red_evidence": (
                    "[{task_id, command, failure_summary, description}]"
                ),
            },
            component=component, batch_id=batch_id, tasks=task_dicts,
            plan=(
                (self._state.architecture_baseline or {}).get("plan_summary", "")
                or self._state.plan
            ))
        return action

    def _build_action_critic(self, base: dict) -> dict:
        # DS-15: subagent reads changed files itself via Read/Grep.
        # Pass only the snapshot reference for Team Lead to relay.
        snap = self._dev_snapshot or {}
        baseline = self._state.architecture_baseline or {}
        batch_state = self._batch_state
        assurance_enabled = (
            len(self._state.file_list) <= 20
            and batch_state is not None
            and sum(len(plate.components) for plate in batch_state.plates) == 1
            and not batch_state.has_more_batches_for(
                batch_state.current_component()
            )
        )
        context = {
            "files_changed": (
                self._state.batch_changed_files
                or snap.get("files_changed", self._state.files_changed)
            ),
            "test_results": snap.get("test_results", self._state.test_results),
            "commit_hash": snap.get("commit_hash", self._state.commit_hash),
            "requirement": self._state.requirement,
            "design_scope": baseline.get("plan_summary", self._state.plan),
            "architecture_baseline_ref": baseline.get("baseline_id", ""),
            "plan_revision": baseline.get("revision", 0),
            "obligation_ids": [
                item.get("id") for item in baseline.get("obligations", [])
                if isinstance(item, dict) and item.get("id")
            ],
            "contract_refs": sorted(
                baseline.get("contracts", {})
                if isinstance(baseline.get("contracts", {}), dict)
                else {}
            ),
            "gate_results": dict(self._state.gate_results or {}),
            "open_findings": list(self._state.open_findings),
            "engineering_sections": self._engineering_sections(
                self._last_batch_design_references()
            ) if self._last_batch_design_references() else [],
        }
        expected_format = {
            "stage": "critic",
            "verdict": "APPROVE | MAJOR",
            "findings": (
                "[{finding_id?, kind: implementation_defect|plan_gap|"
                "contract_gap|project_capability, file, line, severity, issue, "
                "suggestion, design_ref?, task_ref?, contract_ref?}]"
            ),
            "strengths": "[{description:string, location?:string}]",
            "critic_feedback": "string",
            "assessment": "Ready to merge | With fixes | Needs rework",
        }
        if assurance_enabled:
            assert batch_state is not None
            component = batch_state.current_component()
            context["assurance_scope"] = {
                "mode": "leaf_small_project",
                "component": component.name,
                "design_section": component.design_section,
                "design_doc_path": self._state.design_doc_path,
                "implementation_files": list(self._state.file_list),
                "project_profile_summary": self._project_profile_summary(
                    verifier=True
                ),
                "required_audit_dimensions": [
                    "architecture",
                    "code_quality",
                    "engineering",
                    "virtualization",
                    "team_design_coverage",
                ],
            }
            expected_format["assurance_bundle"] = (
                "{component_verification:{component,coverage_map:[{design_item,"
                "status:IMPLEMENTED|MISSING|DIVERGED,file,line,note}],missing_count,"
                "diverged_count,recheck_log:[]},system_audit:{dimensions:[architecture,"
                "code_quality,engineering,virtualization,team_design_coverage],findings:"
                "[{severity,authority_class,dimension,file,line,description,evidence,"
                "suggested_fix}],p0_count,p1_count,p2_count,total_audited_files,"
                "design_docs_stale,design_doc_suggestions,missing_count,diverged_count}}"
            )
        return self._build_stage_action(
            base,
            "critic",
            context=context,
            expected_format=expected_format,
        )

    def _build_action_component_verifier(self, base: dict) -> dict:
        # 2026-07-25 审计修复: batch_state 为 None 时原代码 AttributeError 崩溃,
        # 按 Fix C 同模式优雅 skip (mypy union-attr 预存错误一并修复)。
        if self._batch_state is None:
            return {**base, "action": "skip",
                    "reason": "no batch state for component_verifier",
                    "stage": "component_verifier",
                    "next_transition": "plate_deep_audit"}
        comp = self._batch_state.current_component()
        component_batches = self._batch_state.batches_for(comp)
        plate_keys = list(dict.fromkeys(
            key
            for batch in component_batches
            for key in batch.get("plate_keys", [comp.name])
            if isinstance(key, str)
        ))
        routed_components = [comp]
        if self._design_doc is not None and isinstance(plate_keys, list):
            by_name = {
                item.name: item
                for plate in self._design_doc.plates
                for item in plate.components
            }
            routed_components = [
                by_name[key]
                for key in plate_keys
                if isinstance(key, str) and key in by_name
            ] or [comp]
        # Fix B: collect implementation_files from batch_plan file_targets
        impl_files: list[str] = []
        for b in component_batches:
            for t in b.get("tasks", []):
                for ft in t.get("file_targets", []):
                    if ft not in impl_files:
                        impl_files.append(ft)
        # Fix C: when design_spec is empty and no impl files, skip verification.
        # DS-14 (T151): 原 `and not impl_files` 逻辑保留 — design_spec 由 T150
        # (fence code block→DesignItem) 保证非空。双空时才 skip，避免过度跳过。
        design_spec = "\n\n".join(
            summary
            for routed in routed_components
            if (summary := routed.design_spec_summary())
        )
        if not design_spec and not impl_files:
            return {**base, "action": "skip", "reason": "no design items or implementation files for component",
                    "stage": "component_verifier",
                    "next_transition": "plate_deep_audit"}
        joined_design_section = ", ".join(
            item.design_section for item in routed_components if item.design_section
        )
        if joined_design_section == comp.name:
            joined_design_section = ""
        # DS-15: subagent reads design doc + impl files itself.
        # F8 修复 (2026-07-26 真跑): 注入 component/design_section/design_spec/
        # implementation_files 到 context —— 此前 context 为空，verifier subagent 不知
        # 验哪个组件，须 Team Lead 手动查 batch_state 补上下文（驱动摩擦大）。
        return self._build_stage_action(base, "component_verifier", context={
            "component": comp.name,
            "plate_keys": [item.name for item in routed_components],
            "design_sections": [item.design_section for item in routed_components],
            "engineering_sections": self._engineering_sections(
                [item.design_section for item in routed_components]
            ),
            "design_section": joined_design_section,
            "design_spec": design_spec,
            "implementation_files": impl_files,
            "project_profile_summary": self._project_profile_summary(verifier=True),
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
        }, plate_keys=[item.name for item in routed_components],
           recheck=dict(_VERIFIER_RECHECK))

    def _build_action_plate_deep_audit(self, base: dict) -> dict:
        # DS-15: subagent reads plate components + contracts itself.
        # F8 修复 (2026-07-26 真跑): 注入 plate/components 到 context，让审计 subagent
        # 知道审哪个板块（此前 context 为空，须 Team Lead 手动补板块名）。
        ctx: dict = {}
        if self._batch_state is not None:
            try:
                plate = self._batch_state.current_plate()
                ctx = {
                    "plate": plate.name,
                    "components": [c.name for c in plate.components],
                }
            except (AssertionError, IndexError):
                ctx = {}
        return self._build_stage_action(base, "plate_deep_audit", context=ctx or None, expected_format={
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
            "design_doc_path": self._state.design_doc_path,
            "file_list": list(self._state.file_list),
            "component_coverage": self._state.coverage_map or [],
            "engineering_sections": self._engineering_sections(),
            "project_profile_summary": self._project_profile_summary(verifier=True),
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
            "coverage_map": self._state.coverage_map or [],
            "audit_scope": {
                "project_root": str(self.project_root),
                "files": list(self._state.file_list),
            },
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


__all__ = ["ActionBuildContext", "ActionBuilder"]
