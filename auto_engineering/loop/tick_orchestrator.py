"""v5.6 TickOrchestrator — 离散调用编排器 (C.5, Tick-Based Discrete Invocation).

设计参考: design/v5.6-Design-Loop.md §C.5 (line 2960-3632).

术语:
  tick  — 一次完整的离散调用周期: read result → validate → guardrail → gate
          → verification → build action → persist EventStore transaction → output JSON.
          每次 tick 是独立 Python 进程 (Tick-Based Discrete Invocation).
  step  — tick 内的一个 stage 转换 (e.g. architect→developer→critic).
          一个 tick 恰好跨越一个 step; 收敛判定在每个 tick 结束时执行.

核心契约:
  - 每 tick Python 输出一个 action dict (stdout JSON) 告诉 Agent 下一步做什么
  - Agent 执行后写 stage-result.json, Python 读回校验
  - Python 绝不自调 LLM — Agent 在 tick 之间做 LLM 工作
  - gate_runner/guardrail 可注入 (单元测试 stub, 防挂死)
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from collections.abc import Mapping
from copy import copy, deepcopy
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable
from uuid import uuid4

from auto_engineering.build_identity import current_build_identity
from auto_engineering.config.constants import (
    _SPAWN_CONFIG,
    DEFAULT_P1_THRESHOLD,
    STAGE_TO_ROLE,
)
from auto_engineering.config.runtime_config import RuntimeConfig, get_default_config
from auto_engineering.context.offloading import StageContextOffload
from auto_engineering.context.summarization import SessionSummary
from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import DesignDoc, Supplement
from auto_engineering.engine.models import Plan
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.state import EngineState
from auto_engineering.engine.verification_layers import (
    VerificationLayers,
    determine_verification_layers,
)
from auto_engineering.host.adapters import usage_collector_for
from auto_engineering.host.execution_assembler import collect_host_evidence_violations
from auto_engineering.host.outcome_journal import OutcomeJournal
from auto_engineering.host.spawn_contract import SpawnContractError, SpawnPlan
from auto_engineering.host.worker_attestation import (
    WorkerAttestationError,
    validate_attestations,
)
from auto_engineering.loop.action_builder import (
    _STAGE_CHECKPOINT_OPTIONS,
    _STAGE_CHECKPOINT_REVIEW_FEEDBACK,
    ActionBuilder,
)
from auto_engineering.loop.action_compiler import (
    ActionCompiler,
    ActionIdentity,
)
from auto_engineering.loop.actions import (
    ActionDone,
    ActionError,
    ErrorResponse,
    build_terminal_acceptance_summary,
    result_contract_warnings,
    validate_result_format,
)
from auto_engineering.loop.architect_result import (
    ArchitectResultPreparer,
    is_same_action_repair,
)
from auto_engineering.loop.architecture_activation import ArchitectureActivationService
from auto_engineering.loop.artifacts import (
    ArtifactError,
    ArtifactStore,
    validate_worker_receipt,
)
from auto_engineering.loop.audit_revision import AuditRevisionService
from auto_engineering.loop.context_authority import informational_drift
from auto_engineering.loop.context_budget import (
    BudgetDecision,
    ContextUsage,
    evaluate_budget,
)
from auto_engineering.loop.debug_tracer import DebugTracer, now_iso
from auto_engineering.loop.design_authority import (
    DesignAuthorityError,
    DesignChangeRequest,
)
from auto_engineering.loop.design_decision_ledger import DesignDecisionLedger
from auto_engineering.loop.design_preflight import (
    build_design_structure_preflight_gate,
    prepare_design_ledger,
    resolve_design_structure_preflight_gate,
)
from auto_engineering.loop.developer_gate_service import (
    DeveloperGateService,
    StageGateDispatcher,
)
from auto_engineering.loop.effects import (
    EffectExecutor,
    EffectIntent,
    EffectReceipt,
    WriteJsonArtifact,
)
from auto_engineering.loop.escalation_handler import (
    EscalationContext,
    EscalationHandler,
)
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import EVENT_SCHEMA_VERSION, LoopEvent, LoopEventType
from auto_engineering.loop.guardrail import GuardrailChain
from auto_engineering.loop.kernel import TickKernel
from auto_engineering.loop.loop_budget import LoopUsage, evaluate_loop_budget
from auto_engineering.loop.project_setup_service import ProjectSetupService
from auto_engineering.loop.protocol import (
    SCHEMA_VERSION,
    ProtocolErrorCode,
    ProtocolValidationError,
    action_envelope,
    payload_digest,
    validate_action_envelope,
    validate_result_envelope,
)
from auto_engineering.loop.reducers import default_reducer_registry
from auto_engineering.loop.refine import build_refine_request
from auto_engineering.loop.result_inbound_policy import (
    apply_inbound_pii_policy as _apply_inbound_pii_policy_impl,
)
from auto_engineering.loop.result_validators import (
    normalize_result_section_findings as _normalize_result_section_findings_impl,
)
from auto_engineering.loop.result_validators import (
    validate_component_verifier_scope as _validate_component_verifier_scope_impl,
)
from auto_engineering.loop.result_validators import (
    validate_critic_scope as _validate_critic_scope_impl,
)
from auto_engineering.loop.result_validators import (
    validate_execution_scope as _validate_execution_scope_impl,
)
from auto_engineering.loop.result_validators import (
    validate_gap_analysis as _validate_gap_analysis_impl,
)
from auto_engineering.loop.result_validators import (
    validate_gap_review_decisions as _validate_gap_review_decisions_impl,
)
from auto_engineering.loop.result_validators import (
    validate_global_evidence_scope as _validate_global_evidence_scope_impl,
)
from auto_engineering.loop.runtime_revision import (
    CompatibilityDecision,
    RuntimeRevision,
    evaluate_compatibility,
    incompatible_fields,
)
from auto_engineering.loop.session_handoff import SessionHandoff
from auto_engineering.loop.stage_offload import StageOffloadService
from auto_engineering.loop.stage_result_prevalidator import StageResultPrevalidator
from auto_engineering.loop.stages.base import (
    StageName,
    TransitionContext,
    TransitionDecision,
)
from auto_engineering.loop.stages.design import (
    ArchitectHandler,
    CriticHandler,
    PlanRefineHandler,
)
from auto_engineering.loop.stages.developer import DeveloperHandler
from auto_engineering.loop.stages.gap import (
    GapReviewHandler,
    GapScanHandler,
    ResearchHandler,
)
from auto_engineering.loop.stages.registry import StageHandlerRegistry
from auto_engineering.loop.stages.terminal import resolve_terminal_action
from auto_engineering.loop.stages.verification import (
    ComponentVerifierHandler,
    PlateDeepAuditHandler,
    SystemDeepAuditHandler,
    SystemVerifierHandler,
)
from auto_engineering.loop.state_lifecycle import clear_stage_fields
from auto_engineering.loop.task_factory import tasks_from_batch_plan
from auto_engineering.loop.tick_evidence import (
    record_tick_latency as _record_tick_latency_impl,
)
from auto_engineering.loop.tick_gate_runner import TickGateRunner
from auto_engineering.loop.tick_project_setup import TickProjectSetupMixin
from auto_engineering.loop.transition_context_factory import TransitionContextFactory
from auto_engineering.loop.transition_effects import TransitionEffectExecutor
from auto_engineering.metrics.collector import get_collector
from auto_engineering.metrics.enrichment import compute_metrics_signals
from auto_engineering.observability.audit_log import AuditLogger
from auto_engineering.observability.tracing import _TracerLike
from auto_engineering.pii.redactor import PIIRedactor
from auto_engineering.project_profile import (
    AeConfigProvider,
    LegacyInitProvider,
    LocalProbeProvider,
    ProjectProfileError,
    ProjectProfileResolution,
    ProjectProfileResolver,
    ResolutionStatus,
)
from auto_engineering.prompts.compiler import PromptContextError
from auto_engineering.prompts.registry import default_registry


class GateRunner(Protocol):
    """Typed protocol for gate runner (replaces Callable[..., dict])."""
    def __call__(self, gate_names: tuple[str, ...], project_root: Path,
                 files_changed: list[str] | None = None) -> dict[str, dict]: ...

_MAX_PER_SOURCE = 2
_MAX_GLOBAL = 4
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

# ── System-Initiated Escalation: 项目语言探测 ──

# _LANGUAGE_INDICATORS + _detect_project_language → loop/escalation_handler.py (P1-9)

# _VERIFIER_RECHECK — 已提取到 ActionBuilder (P0-1)

# DS-10 / C.2.6: Python 编排开销预算 (t_orchestration = t_total − t_gate − t_guard_sub).
# 超预算只告警不中断 — 延迟是可观测性指标, 不是正确性门控. P95 判定离线聚合 (Phase 5).
ORCH_BUDGET_MS = 2000

_logger = logging.getLogger("ae.loop.tick_orchestrator")


# ── Protocol types (P1-10: replace Any with typed contracts) ──


@runtime_checkable
class TickContextOffloader(Protocol):
    """Context offloading — 将 stage context 写入文件.

    Implementation: auto_engineering.context.offloading.ContextOffloader.
    The real signature is offload(stage, messages, summary, key_decisions,
    files_changed, gate_results) -> StageContextOffload; this Protocol
    only documents the structural interface for isinstance checks.
    """
    def offload(self, stage: str, messages: list[dict], summary: str,
                key_decisions: list[str], files_changed: list[str],
                gate_results: dict) -> StageContextOffload: ...


@runtime_checkable
class TickSessionSummarizer(Protocol):
    """Cross-tick session summarization (T54).

    Generates a host-neutral structured summary from state metadata.
    Standalone 已于 Phase 40 移除；引擎调用 summarize_structured()（结构化模式）。
    """
    def should_summarize(self, current_tick: int, threshold: int = 5) -> bool: ...
    def summarize_structured(
        self, *, tick: int, test_results: dict | None = None,
        files_changed: list[str] | None = None, commit_hash: str = "",
        gate_results: dict | None = None,
        critic_verdict: str = "",
        total_majors: int = 0,
        batch_progress: str = "",
        previous_summary: SessionSummary | None = None,
    ) -> SessionSummary: ...
    def inject_into_prompt(self, summary: SessionSummary) -> str: ...


@runtime_checkable
class _UsageCollectorLike(Protocol):
    """Host Adapter 提供的标准化 usage collector。"""
    def collect(self) -> dict[str, Any]: ...


class TickOrchestrator(TickProjectSetupMixin):
    """Discrete-tick orchestrator with layered verification (C.5).

    Injectables (all optional, for hang-free unit testing):
        gate_runner:    替换 run_gates (同步, 可快速 stub)
        guardrail:      替换 GuardrailChain (stub 跳过子进程)
    """
    def __init__(
        self,
        project_root: Path | None = None,
        *,
        gate_runner: GateRunner | None = None,
        guardrail: GuardrailChain | None = None,
        event_store: SQLiteEventStore | None = None,
        context_offloader: TickContextOffloader | None = None,
        session_summarizer: TickSessionSummarizer | None = None,
        tracer: _TracerLike | None = None,  # T135c: typed Protocol
        audit_logger: AuditLogger | None = None,
        runtime_config: RuntimeConfig | None = None,
        pii_redactor: PIIRedactor | None = None,
        usage_collector: _UsageCollectorLike | None = None,
        escalate: bool = False,
        debug: bool = False,
        debug_dir: str | None = None,
    ) -> None:
        self.project_root = project_root or Path.cwd()
        self._audit_logger = audit_logger
        self._escalate = escalate
        self._guardrail = guardrail
        self._event_store = event_store
        self._context_offloader = context_offloader
        self._session_summarizer = session_summarizer
        self._cached_session_summary: Any = None  # T54: 跨 tick 滚动摘要缓存
        self._tracer = tracer
        self._debug_enabled = debug
        self._debug_dir = debug_dir

        # P0-6: centralized config — injectable, defaults to process-wide sentinel
        self._runtime_config = runtime_config if runtime_config is not None else get_default_config()

        # T109: PII 四层文件桥接防护 (可注入, 默认自动创建)
        self._pii_enabled = self._runtime_config.pii_enabled
        self._pii_redactor: PIIRedactor | None = (
            pii_redactor if pii_redactor is not None
            else (PIIRedactor() if self._pii_enabled else None)
        )

        # T110: M5 Token JSONL 采集 (可注入, 默认自动创建)
        self._usage_collector = (
            usage_collector
            if usage_collector is not None
            else usage_collector_for(self.project_root)
        )

        self._state: EngineState | None = None
        self._design_ledger = DesignDecisionLedger(())
        self._plan: Plan | None = None
        self._project_profile_resolver = ProjectProfileResolver((
            AeConfigProvider(),
            LocalProbeProvider(),
            LegacyInitProvider(),
        ))
        self._project_profile_resolution: ProjectProfileResolution | None = None
        self._project_setup_service = ProjectSetupService(self)
        self._design_doc: DesignDoc | None = None
        self._batch_state: BatchState | None = None
        self._progress_tree: ProgressTree | None = None
        self._verification_layers: VerificationLayers | None = None
        self._last_batch_id: str | None = None  # 跨 stage 传 batch_id (组件完成后无 current)
        self._dev_snapshot: dict[str, Any] | None = None  # developer 产出快照 (供 critic 上下文)
        # DS-10 延迟打点累加器 (每 tick 起始清零, tick() 内累加子进程墙钟)
        self._t_gate_ms: float = 0.0
        self._t_guard_sub_ms: float = 0.0
        # DebugTracer (可选, --debug 或 AE_DEBUG=1 时激活)
        self._debug_tracer: DebugTracer | None = None
        self._last_guardrail: dict | None = None  # 当前 Tick 的调试快照
        # T64: Stage Checkpoint Gate (DecisionGate 形态 3)
        self._pause_at_stages: set[str] = set()
        self._passed_checkpoints: set[str] = set()
        # Protocol v1.1: 当前待处理 Action 与已完成 Result 的进程内幂等索引。
        # 跨进程状态与阶段 Gate 事实统一由 EventStore 承载。
        self._active_action: dict[str, Any] | None = None
        self._result_replays: dict[str, tuple[str, dict[str, Any]]] = {}
        self._current_result_message_id: str | None = None
        self._current_result_causation_id: str | None = None
        self._current_result_hash: str | None = None
        self._pending_domain_events: list[LoopEvent] = []
        self._pending_effect_receipts: list[EffectReceipt] = []
        self._pending_effect_intents: list[EffectIntent] = []
        self._session_handoff = SessionHandoff()
        self._stage_handlers = StageHandlerRegistry(
            [
                GapScanHandler(),
                GapReviewHandler(),
                ResearchHandler(),
                ArchitectHandler(),
                DeveloperHandler(),
                CriticHandler(),
                PlanRefineHandler(),
                ComponentVerifierHandler(),
                PlateDeepAuditHandler(),
                SystemVerifierHandler(),
                SystemDeepAuditHandler(),
            ]
        )
        self._action_builder = ActionBuilder(
            self.project_root,
            pii_enabled=self._pii_enabled,
            pii_redactor=self._pii_redactor,
            pii_outbound=self._runtime_config.pii_outbound,
            runtime_config=self._runtime_config,
        )
        # P0-1: TickGateRunner delegate — gate selection, execution, metrics, tracing
        self._tick_gate_runner = TickGateRunner(
            self.project_root,
            project_profile=None,
            gate_runner=gate_runner,
            tracer=tracer,
            audit_logger=audit_logger,
        )

    # ── P1-9 EscalationHandler delegate ──
    _escalation: EscalationHandler | None = None

    @property
    def escalation(self) -> EscalationHandler:
        """Lazily-created EscalationHandler — reads current mutable state (P1-9)."""
        if self._escalation is None or self._escalation._ctx is None:
            self._escalation = EscalationHandler(EscalationContext(
                state=self._state,
                batch_state=self._batch_state,
                build_action=self.build_action,
                persist_state=self._persist_state,
                queue_domain_event=self._queue_domain_event,
            ))
        return self._escalation

    # ── T113 L2: Injectable access with visible None ──
    def _require(self, attr_name: str, reason: str = "") -> object:
        """Get injectable with debug-level log when None.

        Replaces silent ``if self._x is not None`` checks with a unified
        accessor that makes the None visible at DEBUG level.  Does NOT
        change behavior — still degrades gracefully.
        """
        val = getattr(self, attr_name, None)
        if val is None:
            _logger.debug("Injectable '%s' is None — feature disabled. %s",
                          attr_name, reason)
        return val

    def status_snapshot(self, *, verbose: bool = False) -> dict[str, Any]:
        """返回 CLI 可消费的只读状态投影，不暴露可变内部对象。"""
        if self._state is None:
            raise RuntimeError("LOOP_STATE_UNAVAILABLE")
        state = self._state
        summary: dict[str, Any] = {
            "thread_id": state.thread_id,
            "current_stage": state.current_stage,
            "expected_stage": state.expected_stage,
            "tick": state.tick,
            "verdict": state.critic_verdict,
            "total_majors": state.total_majors,
            "plan_refine_count": state.plan_refine_count,
        }
        if isinstance(self._active_action, Mapping):
            summary["active_action"] = deepcopy(dict(self._active_action))
        from auto_engineering.loop.status_projection import reconciliation_status

        reconciliation = reconciliation_status(state, self._batch_state)
        if reconciliation is not None:
            summary["plan_reconciliation"] = reconciliation
        if verbose and self._batch_state is not None:
            batch_state = self._batch_state
            batches: list[dict[str, Any]] = []
            component = None
            try:
                component = batch_state.current_component()
                for batch in batch_state.batches_for(component):
                    batches.append({
                        "batch_id": batch.get("batch_id", ""),
                        "component": batch.get("component", ""),
                        "task_count": len(batch.get("tasks", [])),
                    })
            except Exception:
                _logger.debug("batch summary build failed", exc_info=True)
            summary["batch_progress"] = {
                "current_component": component.name if component else "?",
                "current_batch_idx": batch_state.current_batch_idx,
                "total_batches": len(batch_state.batches_for(component))
                if component else 0,
                "batches": batches,
                "total_components_seen": len(
                    getattr(batch_state, "_seen_components", [])
                ),
            }
        return summary

    def state_snapshot(self) -> EngineState:
        """返回当前领域状态的隔离副本，供宿主编排协议使用。"""
        if self._state is None:
            raise RuntimeError("LOOP_STATE_UNAVAILABLE")
        return deepcopy(self._state)

    def active_action_snapshot(self) -> dict[str, Any] | None:
        """返回当前 Action 的隔离副本；宿主不得修改 Core 内部 Action。"""
        if not isinstance(self._active_action, Mapping):
            return None
        return deepcopy(dict(self._active_action))

    # ── T64: Stage Checkpoint Gate ──
    def set_pause_at_stages(self, stages: list[str]) -> None:
        """Set stages to pause at (T64 --pause-at-stage).

        Unknown stage names are warned but not rejected — typos would
        silently prevent the checkpoint from ever triggering.
        """
        known = set(STAGE_TO_ROLE.keys())
        for s in stages:
            if s not in known:
                _logger.warning(
                    "pause-at-stage: '%s' is not a known stage. "
                    "Known: %s. This checkpoint will never trigger.",
                    s, ", ".join(sorted(known)),
                )
        self._pause_at_stages = set(stages)

    # _checkpoint_passed / _progress_summary — 已提取到 ActionBuilder (P0-1)

    # ── 公共入口 ──
    def _resolve_design_doc_path(self, path: str | Path) -> Path:
        """按项目根解析设计文档，避免跨 cwd 恢复时丢失文档。

        协议仍保存宿主提供的相对路径以保持兼容；所有实际读取统一经过
        project_root 解析。绝对路径保持原样，便于跨 Tick 恢复。
        """
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.project_root / candidate

    def init(
        self,
        requirement: str,
        design_doc_path: str | None = None,
        thread_id: str | None = None,
    ) -> dict:
        """初始化 loop。有设计文档时解析层次并进入 gap_scan; 否则直接 architect.

        ProjectProfile 不完整时发出 project_setup_required，由宿主补齐后重新探测。
        """
        if design_doc_path:
            resolved_design_doc = self._resolve_design_doc_path(design_doc_path)
            self._design_doc = DesignDoc.parse(resolved_design_doc)
            self._design_ledger = prepare_design_ledger(
                self.project_root, resolved_design_doc, self._design_doc
            )
        if self._pii_enabled and self._pii_redactor:
            findings = self._pii_redactor.scan_dict({"requirement": requirement})
            if findings:
                _logger.warning("PII detected in requirement: %d matches", len(findings))

        self._state = EngineState(
            requirement=requirement,
            thread_id=thread_id or str(uuid4()),
            prompt_registry_hash=default_registry().registry_hash(),  # B12.5 版本锁
            execution_session_id=str(uuid4()),
            session_started_at=datetime.now().astimezone().isoformat(),
        )
        self._state.project_setup_baseline_files = self._project_setup_files()
        self._state.active_runtime_revision = self._current_runtime_revision().to_dict()
        if design_doc_path:
            # 持久化路径 — 跨进程 restore 据此重 parse 设计文档 (T9a)
            self._state.design_doc_path = design_doc_path
            self._state.design_doc_digest = (
                "sha256:" + hashlib.sha256(resolved_design_doc.read_bytes()).hexdigest()
            )

        # DebugTracer 激活 (--debug 或 AE_DEBUG=1)
        if self._debug_enabled:
            debug_path = Path(self._debug_dir) if self._debug_dir else (
                self.project_root / "_scratch" / "debug")
            self._state.debug_enabled = True
            self._state.debug_dir = str(debug_path)
            self._debug_tracer = DebugTracer(debug_path)

        if self._guardrail is None:
            self._guardrail = GuardrailChain.default()

        try:
            self._project_profile_resolution = self._project_profile_resolver.resolve(
                self.project_root,
                design_doc_path=design_doc_path,
                require_test_command=False,
            )
        except ProjectProfileError as exc:
            self._state.current_stage = "project_setup"
            self._state.expected_stage = "project_setup"
            self._state.missing_project_capabilities = ["project_profile_conflict"]
            self._queue_domain_event(
                LoopEventType.PROJECT_PROFILE_CONFLICT,
                {"error_code": exc.code.value, "message": str(exc)},
            )
            self._persist_state()
            return self.build_action()
        setup_required = self._project_profile_resolution.status is ResolutionStatus.SETUP_REQUIRED
        if setup_required:
            self._state.current_stage = "project_setup"
            self._state.expected_stage = "project_setup"
            self._state.missing_project_capabilities = list(
                self._project_profile_resolution.missing_capabilities
            )
            self._state.tick = 0
            self._queue_domain_event(
                LoopEventType.PROJECT_SETUP_REQUIRED,
                {"missing_capabilities": list(self._project_profile_resolution.missing_capabilities)},
            )
            if not self._escalate:
                self._persist_state()
                return self.build_action()
        else:
            self._apply_project_profile_resolution(self._project_profile_resolution)
            self._queue_domain_event(
                LoopEventType.PROJECT_PROFILE_RESOLVED,
                {"profile_id": self._state.project_profile_id},
            )

        # T95 Agent-Initiated Escalation: --escalate flag → 启动时立即暂停
        if self._escalate:
            if self._design_doc:
                self._state.current_stage = "gap_scan"
                self._state.expected_stage = "gap_scan"
            else:
                self._state.current_stage = "architect"
                self._state.expected_stage = "architect"
            self._state.tick = 1
            self._persist_state()
            return self.build_action(pre_gate=self.escalation.build_agent_escalation_gate(None))

        if self._design_doc:
            self._state.current_stage = "gap_scan"
            self._state.expected_stage = "gap_scan"
        else:
            self._state.current_stage = "architect"
            self._state.expected_stage = "architect"
        self._state.tick = 0
        self._persist_state()
        return self.build_action()

    @classmethod
    def restore_from_event_store(
        cls,
        project_root: Path,
        *,
        event_store: SQLiteEventStore,
        thread_id: str | None = None,
        gate_runner: GateRunner | None = None,
        guardrail: GuardrailChain | None = None,
        context_offloader: TickContextOffloader | None = None,
        session_summarizer: TickSessionSummarizer | None = None,
        tracer: Any | None = None,
        audit_logger: AuditLogger | None = None,
        runtime_config: RuntimeConfig | None = None,
        debug: bool = False,
        debug_dir: str | None = None,
    ) -> TickOrchestrator:
        """从 EventStore 恢复 Canonical Projection 与 active Action。"""

        if event_store is None:
            raise RuntimeError("EVENT_STORE_REQUIRED")
        resolved_thread_id = thread_id or event_store.current_thread()
        if resolved_thread_id is None:
            raise RuntimeError("无 active EventStore thread 可恢复")
        state = event_store.load_projection(resolved_thread_id)
        if state is None:
            raise RuntimeError(
                f"EventStore 无状态投影 (thread_id={resolved_thread_id})"
            )
        active_action = event_store.load_action_snapshot(resolved_thread_id)
        return cls._restore_loaded_state(
            project_root,
            state=state,
            active_action=active_action,
            event_store=event_store,
            gate_runner=gate_runner,
            guardrail=guardrail,
            context_offloader=context_offloader,
            session_summarizer=session_summarizer,
            tracer=tracer,
            audit_logger=audit_logger,
            runtime_config=runtime_config,
            debug=debug,
            debug_dir=debug_dir,
        )

    @classmethod
    def _restore_loaded_state(
        cls,
        project_root: Path,
        *,
        state: EngineState | dict[str, Any],
        active_action: dict[str, Any] | None,
        gate_runner: GateRunner | None = None,
        guardrail: GuardrailChain | None = None,
        context_offloader: TickContextOffloader | None = None,
        session_summarizer: TickSessionSummarizer | None = None,
        tracer: Any | None = None,
        audit_logger: AuditLogger | None = None,
        runtime_config: RuntimeConfig | None = None,
        debug: bool = False,
        debug_dir: str | None = None,
        event_store: SQLiteEventStore | None = None,
    ) -> TickOrchestrator:
        """跨进程恢复 (§A.1: 每 tick 独立进程, 从 SQLite 重建全部 in-memory 状态)."""
        self = cls(
            project_root,
            gate_runner=gate_runner,
            guardrail=guardrail,
            event_store=event_store,
            context_offloader=context_offloader,
            session_summarizer=session_summarizer,
            tracer=tracer,
            audit_logger=audit_logger,
            runtime_config=runtime_config,
            debug=debug,
            debug_dir=debug_dir,
        )

        self._active_action = (
            dict(active_action) if isinstance(active_action, Mapping) else None
        )
        if isinstance(state, dict):  # 防御: deserialize 未命中 EngineState 分派
            state = EngineState.from_dict(state)
        resolved_thread_id = state.thread_id
        self._state = state
        self._dev_snapshot = (
            dict(state.developer_snapshot)
            if state.developer_snapshot is not None
            else None
        )

        if self._guardrail is None:
            self._guardrail = GuardrailChain.default()

        # 持久化 Profile 只作审计快照；恢复必须重新读取当前本地证据。
        previous_profile_id = state.project_profile_id
        resolution = self._project_profile_resolver.resolve(
            project_root,
            design_doc_path=state.design_doc_path,
            require_test_command=False,
        )
        if (
            resolution.status is not ResolutionStatus.RESOLVED
            and state.current_stage != "project_setup"
        ):
            raise RuntimeError(
                "PROJECT_PROFILE_REVALIDATION_REQUIRED: 当前项目证据不足，"
                "不能继续使用持久化投影中的陈旧 Profile"
            )
        self._project_profile_resolution = resolution
        self._apply_project_profile_resolution(resolution)
        if previous_profile_id != self._state.project_profile_id:
            self._queue_domain_event(
                LoopEventType.PROJECT_PROFILE_CHANGED,
                {
                    "previous_profile_id": previous_profile_id,
                    "profile_id": self._state.project_profile_id,
                },
            )

        # design_doc: design-doc 模式每 tick 重 parse (确定性无漂移)
        if state.design_doc_path:
            resolved_design_doc = self._resolve_design_doc_path(state.design_doc_path)
            self._design_doc = DesignDoc.parse(resolved_design_doc)
            self._design_ledger = DesignDecisionLedger.ensure_intake(
                self.project_root,
                resolved_design_doc,
            )

        # batch_state: 自包含 (内嵌 batch_plan seed), plates 由 design_doc/seed 重建
        if state.batch_state_json:
            self._batch_state = BatchState.from_json(
                state.batch_state_json, self._design_doc)

        # progress_tree
        if state.progress_tree_json:
            self._progress_tree = ProgressTree.from_dict(
                json.loads(state.progress_tree_json))
        if state.session_summary:
            self._cached_session_summary = SessionSummary.from_dict(
                state.session_summary
            )

        # plan + verification_layers — batch_plan 从 _batch_state 取 (#6 已被清空)
        batch_plan = (
            self._batch_state.batch_plan if self._batch_state
            else state.batch_plan)
        if batch_plan:
            self._plan = tasks_from_batch_plan(batch_plan, state.requirement)
            self._verification_layers = determine_verification_layers(
                self._design_doc, batch_plan)

        # DebugTracer: 从持久化状态重建 (跨进程恢复)
        if state.debug_enabled and state.debug_dir:
            self._debug_tracer = DebugTracer(Path(state.debug_dir))

        current_revision = self._current_runtime_revision()
        issued_revision = self._issued_runtime_revision(current_revision)
        compatibility = evaluate_compatibility(
            issued=issued_revision,
            current=current_revision,
            has_active_action=self._active_action is not None,
        )
        if compatibility is CompatibilityDecision.INCOMPATIBLE:
            differences = incompatible_fields(
                issued=issued_revision,
                current=current_revision,
            )
            raise RuntimeError(
                "RUNTIME_REVISION_INCOMPATIBLE: EventStore projection 与 active "
                f"ActionSnapshot 已恢复；thread_id={resolved_thread_id}, "
                f"action_message_id={(self._active_action or {}).get('message_id')}, "
                f"differences={json.dumps(differences, ensure_ascii=False, sort_keys=True)}"
            )
        if compatibility is CompatibilityDecision.MIGRATION_REQUIRED:
            raise RuntimeError(
                "RUNTIME_MIGRATION_REQUIRED: Event/Projection 版本需要确定性迁移器"
            )
        self._state.active_runtime_revision = issued_revision.to_dict()
        if compatibility is CompatibilityDecision.ACTIVATE_AFTER_ACTION:
            self._state.pending_runtime_revision = current_revision.to_dict()
            self._queue_domain_event(
                LoopEventType.RUNTIME_REVISION_DETECTED,
                {
                    "active": issued_revision.to_dict(),
                    "pending": current_revision.to_dict(),
                    "activation": "after_active_action",
                },
            )
        else:
            self._state.active_runtime_revision = current_revision.to_dict()
            self._state.pending_runtime_revision = None

        return self

    def tick(self, result_file: Path) -> dict:
        """File-bridge entry point (Driver A). Reads result JSON, delegates to tick_dict()."""
        try:
            return self.tick_dict(json.loads(result_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            return ErrorResponse("RESULT_PARSE_ERROR", f"无法解析 result 文件: {e}",
                                self._state.to_dict() if self._state else None).to_dict()

    def validate_result_file(self, result_file: Path) -> dict:
        """无副作用预校验 Result，不推进 Tick、不写 protocol action/result。"""
        if self._state is None:
            return ErrorResponse("NO_STATE", "请先调用 --init 初始化").to_dict()
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
            result = self._bind_active_auto_decision(result)
            envelope = validate_result_envelope(result)
        except (json.JSONDecodeError, OSError) as exc:
            return ErrorResponse(
                "RESULT_PARSE_ERROR", f"无法解析 result 文件: {exc}"
            ).to_dict()
        except ProtocolValidationError as exc:
            return ErrorResponse(exc.code, str(exc)).to_dict()
        if not self._result_binds_active_action(envelope):
            return ErrorResponse(
                ProtocolErrorCode.ACTION_NOT_ACTIVE,
                "Result 指向的 Action 不是当前 active action",
            ).to_dict()
        validated = self._validate_result_dict(result)
        if isinstance(validated, ErrorResponse):
            return validated.to_dict()
        return {
            "action": "validation_passed",
            "stage": self._state.current_stage,
            "thread_id": self._state.thread_id,
            "causation_id": envelope.causation_id,
        }
    def tick_dict(self, result: dict) -> dict:
        """处理一个 tick — 直接接受 result dict (Driver B standalone 模式).

        与 tick() 相同流程, 但跳过文件读取步骤, 直接验证并处理 result dict.
        """
        # P1-8: _state=None 时尽早失败，避免深层空指针
        if self._state is None:
            return ErrorResponse(
                "NO_STATE",
                "TickOrchestrator._state is None — 请先调用 --init 初始化",
            ).to_dict()

        t_start = time.perf_counter()
        self._t_gate_ms = 0.0
        self._t_guard_sub_ms = 0.0
        tick_no = self._state.tick
        stage_in = self._state.current_stage

        try:
            result = self._bind_active_auto_decision(result)
        except ProtocolValidationError as exc:
            self._record_tick_latency(t_start, tick_no)
            return self._protocol_error(exc.code, str(exc))

        native_result = True
        result_causation: str | None = None
        result_hash: str | None = None
        if native_result:
            try:
                envelope = validate_result_envelope(result)
            except ProtocolValidationError as exc:
                self._record_tick_latency(t_start, tick_no)
                return self._protocol_error(exc.code, str(exc))
            result_causation = envelope.causation_id
            result_hash = payload_digest(result)
            replay = self._result_replays.get(result_causation or "")
            if (
                replay is None
                and result_causation
                and self._event_store is not None
            ):
                replay = self._event_store.load_protocol_result(
                    self._state.thread_id,
                    result_causation,
                )
            if replay is not None:
                previous_hash, previous_action = replay
                if previous_hash == result_hash:
                    return previous_action
                return self._protocol_error(
                    ProtocolErrorCode.RESULT_CONFLICT,
                    "同一 causation_id 已提交不同 Result payload",
                    causation_id=result_causation,
                )
            if not self._result_binds_active_action(envelope):
                OutcomeJournal(self.project_root).record_stale_result(
                    result, reason=ProtocolErrorCode.ACTION_NOT_ACTIVE
                )
                self._record_tick_latency(t_start, tick_no)
                return self._protocol_error(
                    ProtocolErrorCode.ACTION_NOT_ACTIVE,
                    "Result 指向的 Action 不是当前 active action",
                    causation_id=result_causation,
                )
            self._current_result_message_id = envelope.message_id
            self._current_result_causation_id = result_causation
            self._current_result_hash = result_hash

        # T75: OTLP tracing span per tick
        tick_span = None
        if self._tracer is None:
            _logger.debug("Injectable '_tracer' is None — OTLP tracing disabled")
        else:
            tick_span = self._tracer.start_span(
                f"tick.{stage_in}", attributes={"tick": tick_no, "stage": stage_in})

        if result.get("stage") == "session_claimed":
            errors = validate_result_format(result, "session_claimed")
            if errors:
                action = ErrorResponse(
                    "RESULT_VALIDATION_ERROR",
                    "; ".join(errors),
                    self._state.to_dict(),
                ).to_dict()
            else:
                try:
                    action = self._session_handoff.claim(result)
                    self._state.execution_session_id = result["session_id"]
                    self._state.session_start_tick = self._state.tick
                    self._state.session_started_at = datetime.now().astimezone().isoformat()
                    self._state.session_input_units = 0
                    self._active_action = action
                    self._persist_state()
                except (KeyError, ValueError) as exc:
                    error_code = getattr(exc, "error_code", "SESSION_CLAIM_INVALID")
                    action = ErrorResponse(
                        error_code,
                        str(exc),
                        self._state.to_dict(),
                    ).to_dict()
        else:
            action = self._tick_body_dict(result)
        if "schema_version" not in action:
            action = {
                **action,
                "thread_id": self._state.thread_id,
                "tick": action.get("tick", self._state.tick + 1),
                "stage": action.get("stage", self._state.current_stage),
            }
            revision = RuntimeRevision.from_dict(
                self._state.active_runtime_revision
                or self._current_runtime_revision().to_dict()
            )
            action = dict(ActionCompiler().compile(
                payload=action,
                identity=ActionIdentity(
                    message_id=str(uuid4()),
                    correlation_id=self._state.thread_id,
                    causation_id=self._current_result_message_id,
                ),
                runtime_revision=revision,
                issued_at=datetime.now().astimezone().isoformat(),
                effects=(),
            ).payload)
        result_accepted = action.get("action") not in {"error", "resource_wait"}
        if native_result and result_causation and result_hash and result_accepted:
            self._result_replays[result_causation] = (result_hash, action)
        self._current_result_message_id = None
        self._current_result_causation_id = None
        self._current_result_hash = None
        duration_ms = int((time.perf_counter() - t_start) * 1000)

        if tick_span is not None:
            tick_span.set_attribute("duration_ms", duration_ms)
            tick_span.set_attribute("action", action.get("action", ""))
            tick_span.end()
        self._record_tick_latency(t_start, tick_no)

        # DebugTracer 记录可重建的 per-tick 快照
        t_total_ms = (time.perf_counter() - t_start) * 1000
        timing_ms = {
            "t_total": round(t_total_ms, 2),
            "t_gate": round(self._t_gate_ms, 2),
            "t_guard_sub": round(self._t_guard_sub_ms, 2),
            "t_orchestration": round(
                t_total_ms - self._t_gate_ms - self._t_guard_sub_ms, 2),
        }
        state_snapshot = self._state.to_dict() if self._state else {}
        guardrail_snapshot = self._last_guardrail or {}
        gate_snapshot = self._state.gate_results if self._state else {}
        if self._require("_debug_tracer", "debug tracing disabled") is not None:
            self._debug_tracer.record_tick(
                tick_num=tick_no + 1,
                stage_in=stage_in,
                action=action,
                state_snapshot=state_snapshot,
                guardrail_results=guardrail_snapshot,
                gate_results=gate_snapshot,
                timing_ms=timing_ms,
            )
            # 检查 terminal verdict → finalize
            action_type = action.get("action", "")
            verdict = action.get("verdict", "")
            if action_type == "done" or verdict in (
                "GOAL_ACHIEVED", "REFINE_LIMIT", "STAGNANT", "TERMINATED", "SUPERSEDED",
            ):
                self._debug_tracer.finalize(
                    verdict=verdict or "UNKNOWN",
                    total_ticks=tick_no + 1,
                )

        return action

    def _protocol_error(
        self,
        code: ProtocolErrorCode,
        message: str,
        *,
        causation_id: str | None = None,
    ) -> dict[str, Any]:
        """构建不替换 active action 的结构化协议错误。"""

        state = self._state
        suggestions = {
            ProtocolErrorCode.ACTION_NOT_ACTIVE: (
                "不要继续提交旧 Result；读取当前 active Action，按其 operations 先 finalize，"
                "再 validate，最后 tick。"
            ),
            ProtocolErrorCode.RESULT_CONFLICT: (
                "同一 Action 只允许一个不可变 Result；保留当前 journal 并恢复 active Action。"
            ),
        }
        payload = ErrorResponse(
            error_code=code.value,
            message=message,
            current_state=state.to_dict() if state else None,
            suggestion=suggestions.get(code),
        ).to_dict()
        return action_envelope(
            payload,
            thread_id=state.thread_id if state else "unknown",
            tick=(state.tick + 1) if state else 0,
            stage=state.current_stage if state else None,
            causation_id=causation_id,
        )

    def _resource_wait_action(
        self,
        *,
        resource: str,
        reason_code: str,
        message: str,
        suggestion: str,
    ) -> dict[str, Any]:
        """构建可恢复的等待 Action，并显式绑定仍在执行中的 Action。"""

        active_message_id = str((self._active_action or {}).get("message_id", ""))
        return {
            "action": "resource_wait",
            "stage": self._state.current_stage,
            "resource": resource,
            "retry_stage": self._state.current_stage,
            "reason_code": reason_code,
            "message": message,
            "suggestion": suggestion,
            "active_action_message_id": active_message_id,
        }

    def _tick_body_dict(self, result: dict) -> dict:
        """tick 核心逻辑 (dict 版本): Gate resolution → 验证 → Guardrail → Gate → 路由 → action."""
        if self._state.current_stage == "project_setup":
            # WAIT_RESOURCE 是宿主让出控制权的边界。失败 Result 在此只表示
            # “仍未修复”，不应再次进入格式校验、猜错误码或消费失败预算；
            # 只有 project_setup_completed 才有资格尝试恢复原 Setup Action。
            if (
                isinstance(self._active_action, Mapping)
                and self._active_action.get("action") == "resource_wait"
                and result.get("result_type") == "project_setup_failed"
            ):
                return deepcopy(dict(self._active_action))
            validated = self._validate_result_dict(result)
            if isinstance(validated, ErrorResponse):
                return validated.to_dict()
            if result.get("result_type") == "project_setup_failed":
                return self._record_project_setup_failure(result)
            return self._complete_project_setup()

        # T95: Agent mid-loop escalation — Agent 在 result 中置 escalate=true
        if result.get("escalate") is True:
            return self.build_action(pre_gate=self.escalation.build_agent_escalation_gate({
                "question": result.get("escalation_question", ""),
                "options": result.get("escalation_options"),
                "default": result.get("escalation_default"),
            }))

        if (
            self._state.current_stage in _SPAWN_CONFIG
            and result.get("spawned") is False
            and result.get("spawn_error_code") == "HOST_AGENT_CAPACITY"
        ):
            return self._resource_wait_action(
                resource="agent_slot",
                reason_code="HOST_AGENT_CAPACITY",
                message="宿主 Agent 容量暂时不足；保留当前 Action，等待资源后重试。",
                suggestion="回收已完成的 Agent；容量释放后重新执行当前 Action。",
            )
        if (
            self._state.current_stage in _SPAWN_CONFIG
            and result.get("spawned") is False
            and result.get("spawn_error_code") == "HOST_WORKER_OWNER_LOST"
        ):
            return self._resource_wait_action(
                resource="worker_ownership",
                reason_code="HOST_WORKER_OWNER_LOST",
                message="宿主无法确认旧 Worker 所有权；保留当前 Action，禁止并发重跑。",
                suggestion="先确认旧 Worker 已终止；确认后再按同一 active Action 恢复。",
            )
        if (
            self._state.current_stage in _SPAWN_CONFIG
            and result.get("spawned") is False
            and result.get("spawn_error_code") == "HOST_WORKER_TIMEOUT"
        ):
            retry_attempt = result.get("spawn_retry_attempt", 1)
            if not isinstance(retry_attempt, int) or isinstance(retry_attempt, bool):
                return ErrorResponse(
                    error_code="HOST_WORKER_RETRY_ATTEMPT_INVALID",
                    message="Worker 超时 Result 的 spawn_retry_attempt 无效。",
                    current_state=self._state.to_dict(),
                ).to_dict()
            if retry_attempt >= 2:
                return ErrorResponse(
                    error_code="HOST_WORKER_TIMEOUT_EXHAUSTED",
                    message="宿主 Worker 连续两次执行超时；已停止自动重启以避免无限 token 消耗。",
                    current_state=self._state.to_dict(),
                    suggestion="保留当前 Action；待宿主模型服务恢复后重新启动 Loop。",
                ).to_dict()
            return {
                **self._resource_wait_action(
                    resource="worker_completion",
                    reason_code="HOST_WORKER_TIMEOUT",
                    message="宿主 Worker 执行超时；保留当前 Action，等待资源后有界重试。",
                    suggestion="按同一 active Action 重新启动隔离 Worker；不得伪造业务结果。",
                ),
                "retry_attempt": retry_attempt,
                "retry_limit": 1,
            }
        if self._state.current_stage in _SPAWN_CONFIG and result.get("spawned") is False:
            active_message_id = str((self._active_action or {}).get("message_id", ""))
            if result.get("spawn_error_code") == "HOST_WORKER_FAILED":
                retry_attempt = result.get("spawn_retry_attempt", 1)
                if (
                    not isinstance(retry_attempt, int)
                    or isinstance(retry_attempt, bool)
                    or retry_attempt < 1
                ):
                    return ErrorResponse(
                        error_code="HOST_WORKER_RETRY_ATTEMPT_INVALID",
                        message="HOST_WORKER_FAILED 必须包含正整数 spawn_retry_attempt",
                        current_state=self._state.to_dict(),
                    ).to_dict()
                if retry_attempt >= 2:
                    return ErrorResponse(
                        error_code="HOST_WORKER_FAILURE_EXHAUSTED",
                        message="宿主 Worker 连续两次合同失败；已停止自动重试以避免重复执行。",
                        current_state=self._state.to_dict(),
                        suggestion="修复宿主调用合同后，保留当前 Action 并从同一事实恢复。",
                    ).to_dict()
                return {
                    **self._resource_wait_action(
                        resource="worker_completion",
                        reason_code="HOST_WORKER_FAILED",
                        message="宿主 Worker 合同执行失败；保留当前 Action，修复后自动重试。",
                        suggestion="使用当前 Action 的原生启动合同，不得伪造业务结果。",
                    ),
                    "retry_attempt": retry_attempt,
                    "retry_limit": 1,
                }
            spawn_error = str(result.get("spawn_error") or "")
            if (
                result.get("spawn_error_code") == "HOST_CAPABILITY_UNAVAILABLE"
                and "spawn_agent" in spawn_error
            ):
                return ErrorResponse(
                    error_code="WORKER_ROLE_VIOLATION",
                    message=(
                        "Worker 错误检查了 Coordinator 专属派生能力；"
                        f"active Action={active_message_id} 保持不变。"
                    ),
                    current_state=self._state.to_dict(),
                    suggestion=(
                        "不得给 Worker 开放递归派生能力；Coordinator 应按 "
                        "spawn.invocations[] 重新启动隔离 Worker。"
                    ),
                ).to_dict()
            return ErrorResponse(
                error_code="HOST_WORKER_FAILED",
                message=(
                    f"宿主 Worker 未完成；active Action={active_message_id} 保持不变。"
                ),
                current_state=self._state.to_dict(),
                suggestion=(
                    "保留原始宿主错误证据，修复宿主调用后重新执行原 active Action；"
                    "不得生成新 Action 或伪造 Worker 结果。"
                ),
            ).to_dict()

        # T64: handle gate_resolution before validation (no stage field)
        gate_resolution = result.get("gate_resolution")
        if gate_resolution and isinstance(gate_resolution, dict):
            return self._tick_process_result(result)

        validated = self._validate_result_dict(result)
        return self._tick_process_result(validated)

    def _tick_process_result(self, result: dict | ErrorResponse) -> dict:
        """tick 公共处理逻辑: Gate resolution → Guardrail → Gate → 路由 → action."""
        if isinstance(result, ErrorResponse):
            if is_same_action_repair(
                error_code=result.error_code,
                current_stage=self._state.current_stage,
            ):
                # Architect 的业务结果已经由 Worker 产出；确定性校验失败只
                # 说明 Coordinator payload 需要修复。不得把拒绝转换成新
                # Action，否则会丢失同一 Action 的 outcome/generation/fence
                # 身份并诱发重复 Worker。公开 CLI 会在该 error 上投影
                # repair_current_action，复用当前 active Action 的工作文件。
                return ErrorResponse(
                    result.error_code,
                    result.message,
                    self._state.to_dict(),
                    suggestion=(
                        "保持当前 Architect Action 不变；只修复 Coordinator 计划，"
                        "复用已固化 Worker outcome 后重新 finalize、validate、submit。"
                    ),
                ).to_dict()
            if self._require("_debug_tracer", "debug tracing disabled") is not None:
                self._debug_tracer.record_error(
                    tick=self._state.tick,
                    category=result.error_code,
                    detail={"message": result.message},
                )
            return result.to_dict()

        change_requests = result.get("design_change_requests")
        if isinstance(change_requests, list) and change_requests:
            try:
                if len(change_requests) != 1 or not isinstance(change_requests[0], dict):
                    raise DesignAuthorityError("DESIGN_CHANGE_REQUEST_COUNT_INVALID")
                request = DesignChangeRequest.from_dict(change_requests[0])
                if any(
                    (
                        item.get("decision_id") == request.request_id
                        and item.get("proposed_change_sha256")
                        == request.proposed_change_sha256
                    )
                    or item.get("authority_scope_key")
                    == request.authority_scope_key
                    for item in self._approved_design_changes().values()
                ):
                    return self.build_action(feedback=(
                        f"设计变更 {request.request_id} 已经批准；"
                        "禁止重复申请，请直接生成覆盖该决定的可执行计划与义务"
                    ))
                if (
                    request.source == "research"
                    and request.source_ref not in self._state.research_archive
                ):
                    try:
                        supplements = json.loads(
                            self._state.design_supplements_json or "{}"
                        )
                    except json.JSONDecodeError:
                        supplements = {}
                    supplement = (
                        supplements.get(request.source_ref)
                        if isinstance(supplements, dict)
                        else None
                    )
                    if (
                        isinstance(supplement, dict)
                        and supplement.get("source") in {"user", "thread_policy"}
                    ):
                        return self.build_action(feedback=(
                            f"设计补充 {request.source_ref} 已经批准为 binding；"
                            "禁止重复申请变更，请直接生成覆盖该补充的可执行计划与义务"
                        ))
                    raise DesignAuthorityError("DESIGN_CHANGE_SOURCE_UNKNOWN")
            except DesignAuthorityError as exc:
                return ErrorResponse(
                    error_code="DESIGN_CHANGE_REQUEST_INVALID",
                    message=str(exc),
                    current_state=self._state.to_dict(),
                ).to_dict()
            return self.build_action(pre_gate=request.to_gate())

        # T64+T95: handle gate_resolution — dispatch by gate type
        gate_resolution = result.get("gate_resolution")
        if gate_resolution and isinstance(gate_resolution, dict):
            gate_id = gate_resolution.get("gate_id", "")
            resolution = gate_resolution.get("resolution", "")

            if gate_id.startswith("design_change:"):
                decision_id = gate_id.removeprefix("design_change:")
                active_gate = (self._active_action or {}).get("gate", {})
                change = active_gate.get("change", {}) if isinstance(active_gate, dict) else {}
                if (
                    not decision_id
                    or active_gate.get("id") != gate_id
                    or change.get("request_id") != decision_id
                ):
                    return ErrorResponse(
                        error_code="INVALID_GATE_RESOLUTION",
                        message="设计变更 Gate 不是当前 active Action",
                    ).to_dict()
                if resolution == "保留原设计":
                    return self.build_action(
                        feedback=(
                            f"设计变更 {decision_id} 已被用户拒绝；"
                            "必须保留原设计并重新生成可执行计划"
                        )
                    )
                if resolution != "批准变更":
                    return ErrorResponse(
                        error_code="INVALID_GATE_RESOLUTION",
                        message="设计变更 Gate 只接受‘批准变更’或‘保留原设计’",
                    ).to_dict()
                approval_id = self._current_result_message_id
                causation_id = self._current_result_causation_id
                if not approval_id or not causation_id:
                    return ErrorResponse(
                        error_code="DESIGN_APPROVAL_CAUSATION_MISSING",
                        message="设计变更批准缺少 Core 协议因果身份",
                    ).to_dict()
                self._queue_domain_event(
                    LoopEventType.GATE_RESOLVED,
                    {
                        "gate_id": gate_id,
                        "resolution": resolution,
                        "approval_id": approval_id,
                        "decision_id": decision_id,
                        "status": "approved",
                        "source_ref": change.get("source_ref"),
                        "proposed_change_sha256": change.get(
                            "proposed_change_sha256"
                        ),
                        "authority_scope_key": change.get(
                            "authority_scope_key"
                        ),
                    },
                )
                return self.build_action(
                    feedback=f"设计变更 {decision_id} 已由用户显式批准"
                )

            # T95 Agent-Initiated Escalation
            if gate_id == "agent_escalation":
                return self.escalation.resolve_agent_escalation(gate_resolution)

            if gate_id == "state_reconciliation":
                if resolution != "reconcile":
                    return ErrorResponse(
                        error_code="INVALID_GATE_RESOLUTION",
                        message="state_reconciliation 仅由 CLI 处理 reinitialize，当前选择无效",
                    ).to_dict()
                reconciliation = self._state.state_reconciliation
                if not isinstance(reconciliation, dict):
                    return ErrorResponse(
                        error_code="STATE_RECONCILIATION_MISSING",
                        message="状态协调投影缺失",
                    ).to_dict()
                selected = {
                    **reconciliation,
                    "status": "selected",
                    "choice": "reconcile",
                }
                self._state.state_reconciliation = selected
                self._queue_domain_event(
                    LoopEventType.STATE_RECONCILIATION_SELECTED,
                    {"changes": {"state_reconciliation": selected}},
                )
                previous_stage = self._state.current_stage
                self._state.current_stage = "architect"
                self._state.expected_stage = "architect"
                self._queue_domain_event(
                    LoopEventType.STAGE_ADVANCED,
                    {"from": previous_stage, "to": "architect"},
                )
                return self.build_action()

            if gate_id == "design_structure_preflight":
                return resolve_design_structure_preflight_gate(self._active_action, gate_resolution, self._state)
            if gate_id.startswith("checkpoint_"):
                if resolution == "终止 loop":
                    return {
                        "action": "done",
                        "verdict": "TERMINATED",
                        "message": f"用户通过 {gate_id} 终止 loop",
                        "stage": self._state.current_stage,
                        "tick": self._state.tick + 1,
                        "thread_id": self._state.thread_id,
                        "acceptance_summary": build_terminal_acceptance_summary(
                            self._state, verdict="TERMINATED",
                        ),
                    }
                if resolution == "继续":
                    self._passed_checkpoints.add(self._state.current_stage)
                    return self.build_action()
                if resolution == "审查当前产出":
                    self._passed_checkpoints.add(self._state.current_stage)
                    return self.build_action(feedback=_STAGE_CHECKPOINT_REVIEW_FEEDBACK)
                return ErrorResponse(
                    error_code="INVALID_GATE_RESOLUTION",
                    message=f"未知的 gate resolution: {resolution!r}，有效值: {' / '.join(_STAGE_CHECKPOINT_OPTIONS)}",
                ).to_dict()

            # T94 PrePlannedGate — architect 在 batch_plan 中声明的 gate.
            # 接受 gate options 中的任意 resolution, 作为 feedback 传递给下一 stage.
            if resolution == "终止 loop":
                return {
                    "action": "done",
                    "verdict": "TERMINATED",
                    "message": f"用户通过 {gate_id} 终止 loop",
                    "stage": self._state.current_stage,
                    "tick": self._state.tick + 1,
                    "thread_id": self._state.thread_id,
                    "acceptance_summary": build_terminal_acceptance_summary(
                        self._state, verdict="TERMINATED",
                    ),
                }
            detail = gate_resolution.get("resolution_detail", {})
            note = detail.get("note", "")
            feedback = f"Gate '{gate_id}' resolved: {resolution}"
            if note:
                feedback += f" — {note}"
            self._persist_state()
            return self.build_action(feedback=feedback)

        self._apply_result_to_state(result)

        # 挂运行时非持久句柄供 Guardrail (G7 REDGuardrail 读 batch_state/_plan, B3 line 657).
        # asdict 只序列化 dataclass 字段 → 不泄漏进持久化投影。
        self._state._runtime_ctx["batch_state"] = self._batch_state
        self._state._runtime_ctx["plan"] = self._plan
        guardrail_state = self._guardrail_state(result)

        t_g = time.perf_counter()
        gr = self._guardrail.check("post", self._state.current_stage,
                                   guardrail_state, self.project_root)
        self._t_guard_sub_ms += (time.perf_counter() - t_g) * 1000

        # 存储供 DebugTracer 使用
        self._last_guardrail = {
            "action": gr.action,
            "message": gr.message,
            "guardrail_name": getattr(gr, "guardrail_name", ""),
        }

        if gr.action != "pass":
            # G8 FreshGuardrail: 代码在 Gate 后又变更 → 陈旧证据 → 强制重跑 Gate
            # (S-4 rerun_gates 语义). 适用 developer + critic 两阶段 (§B3.2).
            # FreshGuardrail 不清实现/不返错, 放行至 Gate 重跑刷新快照.
            # 非 FreshGuardrail 的 guardrail → 返回错误.
            if getattr(gr, "guardrail_name", "") == "FreshGuardrail":
                StageGateDispatcher().dispatch(
                    self._state.current_stage,
                    lambda: self._run_developer_gates(state=guardrail_state),
                    force=True,
                )
            else:
                if self._require("_debug_tracer", "debug tracing disabled") is not None:
                    self._debug_tracer.record_error(
                        tick=self._state.tick,
                        category=f"GUARDRAIL_{gr.action.upper()}",
                        detail={
                            "guardrail": getattr(gr, "guardrail_name", ""),
                            "message": gr.message,
                            "stage": self._state.current_stage,
                        },
                    )
                return self._handle_guardrail_result(gr)

        StageGateDispatcher().dispatch(
            self._state.current_stage,
            lambda: self._run_developer_gates(state=guardrail_state),
        )

        return self._after_tick(result)

    def _queue_domain_event(self, event_type: LoopEventType, payload: dict[str, Any]) -> None:
        """暂存领域事实，由下一次 EventStore Tick 事务统一分配序列。"""
        if self._state is None:
            return
        self._pending_domain_events.append(
            LoopEvent.create(
                thread_id=self._state.thread_id, sequence=0,
                event_type=event_type, payload=payload,
                correlation_id=self._state.thread_id,
                causation_id=self._current_result_message_id,
            )
        )

    def _result_binds_active_action(self, envelope: Any) -> bool:
        """检查 Result 是否绑定当前 Action 的全部协议身份。"""
        active = self._active_action
        if not isinstance(active, Mapping):
            return False
        return (
            envelope.thread_id == self._state.thread_id
            and envelope.causation_id == active.get("message_id")
            and envelope.correlation_id == active.get(
                "correlation_id", self._state.thread_id,
            )
            and envelope.tick == active.get("tick", self._state.tick)
        )

    def _validate_result_dict(self, result: dict) -> dict | ErrorResponse:
        """验证 result dict (不读文件, Driver B standalone 用)."""
        if not isinstance(result, dict):
            return ErrorResponse(
                error_code="RESULT_TYPE_ERROR",
                message="result 必须是 JSON object",
                current_state=self._state.to_dict() if self._state else None)

        result_stage = result.get("stage", "")
        if result_stage != self._state.current_stage:
            return ErrorResponse(
                error_code="STAGE_MISMATCH",
                message=f"stage 不匹配: result={result_stage!r}, "
                        f"expected={self._state.current_stage!r} "
                        f"(stage 是角色名如 'developer'/'architect', 不是 batch_id 如 'B4')",
                current_state=self._state.to_dict())


        active_gate = (
            self._active_action.get("gate")
            if isinstance(self._active_action, dict)
            else None
        )
        if isinstance(active_gate, dict):
            gate_resolution = result.get("gate_resolution")
            if not isinstance(gate_resolution, dict):
                return ErrorResponse(
                    error_code="GATE_RESOLUTION_REQUIRED",
                    message="当前 active Action 是 Gate，必须提交 gate_resolution",
                    current_state=self._state.to_dict(),
                )
            if gate_resolution.get("gate_id") != active_gate.get("id"):
                return ErrorResponse(
                    error_code="INVALID_GATE_RESOLUTION",
                    message="gate_resolution 未绑定当前 active Gate",
                    current_state=self._state.to_dict(),
                )
            return result

        if self._state.current_stage in _SPAWN_CONFIG and result.get("spawned") is False:
            spawn_error_code = result.get("spawn_error_code")
            spawn_error = result.get("spawn_error")
            if spawn_error_code not in {
                "HOST_AGENT_CAPACITY",
                "HOST_CAPABILITY_UNAVAILABLE",
                "HOST_WORKER_OWNER_LOST",
                "HOST_WORKER_TIMEOUT",
                "HOST_WORKER_FAILED",
            }:
                return ErrorResponse(
                    error_code="SPAWN_FAILURE_CODE_INVALID",
                    message="spawned=false 必须包含受支持的宿主失败码",
                    current_state=self._state.to_dict(),
                )
            if not isinstance(spawn_error, str) or not spawn_error.strip():
                return ErrorResponse(
                    error_code="SPAWN_FAILURE_DETAIL_REQUIRED",
                    message="spawned=false 必须包含非空 spawn_error",
                    current_state=self._state.to_dict(),
                )
            retry_attempt = result.get("spawn_retry_attempt")
            if spawn_error_code == "HOST_WORKER_TIMEOUT" and (
                not isinstance(retry_attempt, int)
                or isinstance(retry_attempt, bool)
                or retry_attempt < 1
            ):
                return ErrorResponse(
                    error_code="HOST_WORKER_RETRY_ATTEMPT_INVALID",
                    message="HOST_WORKER_TIMEOUT 必须包含正整数 spawn_retry_attempt",
                    current_state=self._state.to_dict(),
                )
            return result

        errors = validate_result_format(result, self._state.current_stage)
        if errors:
            return ErrorResponse(
                error_code="RESULT_VALIDATION_ERROR",
                message="; ".join(errors),
                current_state=self._state.to_dict())

        if self._batch_state is not None and "batch_id" in result:
            expected_batch_id = self._batch_state.current_batch_id()
            if result.get("batch_id") != expected_batch_id:
                return ErrorResponse(
                    error_code="DEVELOPER_BATCH_ID_MISMATCH",
                    message=(
                        "Result 的 batch_id 未绑定当前 active batch: "
                        f"result={result.get('batch_id')!r}, "
                        f"expected={expected_batch_id!r}"
                    ),
                    current_state=self._state.to_dict(),
                )

        if scope_error := self._validate_execution_scope(result):
            return scope_error

        if scope_error := self._validate_critic_scope(result):
            return scope_error

        if scope_error := self._validate_global_evidence_scope(result):
            return scope_error

        active_spawn = (
            self._active_action.get("spawn")
            if isinstance(self._active_action, Mapping)
            else None
        )
        if isinstance(active_spawn, Mapping) and "agents" in active_spawn:
            return ErrorResponse(
                "WORKER_INVOCATION_CONTRACT_REQUIRED",
                "当前 Action 含已废弃的 spawn.agents，必须重新签发严格 invocations",
                self._state.to_dict(),
            )

        if section_error := self._normalize_result_section_findings(result):
            return section_error

        if scope_error := self._validate_component_verifier_scope(result):
            return scope_error

        if gap_error := self._validate_gap_analysis(result):
            return gap_error

        if gap_error := self._validate_gap_review_decisions(result):
            return gap_error

        contract_warnings = result_contract_warnings(
            result, self._state.current_stage
        )
        if contract_warnings:
            extensions = result.setdefault("extensions", {})
            if isinstance(extensions, dict):
                extensions["contract_warnings"] = contract_warnings
            _logger.warning(
                "result_contract_warning stage=%s fields=%s",
                self._state.current_stage,
                ",".join(w["field"] for w in contract_warnings),
            )

        # T142: spawn stages — enforce subagent execution via G2 retry.
        # Checks "spawned" field in result: must be True for spawn stages.
        # P1-4: side-channel proof verification — checks that subagent wrote
        # a proof file to .ae-state/spawn-proofs/{token}.json.
        stage = self._state.current_stage
        if stage in _SPAWN_CONFIG:
            spawned = result.get("spawned")
            if spawned is not True:
                return ErrorResponse(
                    error_code="SPAWN_REQUIRED",
                    message=(
                        f"Stage '{stage}' requires spawning an agent. "
                        f"Read action.spawn.invocations[] — execute each worker, "
                        f"collect attestations and set "
                        f"'\"spawned\": true' in the result. "
                        f"Re-run this tick with actual agent spawn."
                    ),
                    current_state=self._state.to_dict(),
                )

            active_spawn_for_preflight = (
                self._active_action.get("spawn")
                if self._active_action is not None else None
            )
            if (
                isinstance(active_spawn_for_preflight, dict)
                and "invocations" in active_spawn_for_preflight
                and self._active_action is not None
            ):
                violations = collect_host_evidence_violations(
                    project_root=self.project_root,
                    action=self._active_action,
                    result=result,
                    receipt_limit=self._runtime_config.max_worker_receipt_bytes,
                    summary_limit=self._runtime_config.max_receipt_summary_bytes,
                )
                if violations:
                    return ErrorResponse(
                        error_code="HOST_EVIDENCE_INVALID",
                        message=(
                            "严格宿主证据未完成："
                            + "; ".join(violations)
                            + "。请由宿主使用 --finalize-result 原子终结当前真实 "
                            "Worker outcome；若 Worker 已完成，禁止重新 spawn。"
                        ),
                        current_state=self._state.to_dict(),
                    )

            # DS-15: verify spawn proof file was completed (engine pre-writes it,
            # subagent must update status to "completed")
            proof_token = result.get("spawn_proof_token")
            expected_token = (
                self._active_action.get("spawn_proof_token")
                if self._active_action is not None else None
            )
            if (
                not isinstance(proof_token, str)
                or not isinstance(expected_token, str)
                or proof_token != expected_token
            ):
                return ErrorResponse(
                    error_code="SPAWN_PROOF_TOKEN_MISMATCH",
                    message=(
                        f"Stage '{stage}' 的 spawn_proof_token 缺失、失效或不属于"
                        "当前 active Action"
                    ),
                    current_state=self._state.to_dict(),
                )
            if proof_token:
                proof_file = (
                    self.project_root / ".ae-state" / "spawn-proofs"
                    / f"{proof_token}.json"
                )
                challenge_file = (
                    self.project_root / ".ae-state" / "spawn-challenges"
                    / f"{proof_token}.json"
                )
                proof_ok = False
                if proof_file.exists():
                    try:
                        proof_data = json.loads(proof_file.read_text(encoding="utf-8"))
                        # 当前 Action 必须同时具备不可变 challenge 与完成 proof；
                        # 缺少 challenge 时 fail-closed，不从 proof 猜测身份。
                        challenge_data = json.loads(
                            challenge_file.read_text(encoding="utf-8")
                        )
                        proof_ok = (
                            proof_data.get("status") == "completed"
                            and proof_data.get("token") == proof_token
                            and proof_data.get("stage", stage) == stage
                            and challenge_data.get("token") == proof_token
                            and challenge_data.get("stage") == stage
                            and challenge_data.get("thread_id") == self._state.thread_id
                            and self._active_action is not None
                            and challenge_data.get("action_message_id")
                            == self._active_action.get("message_id")
                        )
                    except (json.JSONDecodeError, OSError) as e:
                        _logger.warning(
                            "Spawn proof file corrupted for stage=%s token=%s: %s",
                            stage, proof_token, e)
                if not proof_ok:
                    # F7 修复 (2026-07-26 真跑): 防伪从「仅告警」升级为「拦截」。
                    # spawned=true 但 proof 未 completed = subagent 可能未真实执行
                    # （伪造 spawned 字段）→ 返回 ErrorResponse 触发 G2 重 spawn，不放行。
                    _logger.warning(
                        "Spawn proof incomplete for stage=%s token=%s — "
                        "spawned=true but proof file status != 'completed'. "
                        "Subagent may not have executed (possible forged spawned field).",
                        stage, proof_token,
                    )
                    if self._require("_debug_tracer", "debug tracing disabled") is not None:
                        self._debug_tracer.record_error(
                            tick=self._state.tick,
                            category="SPAWN_PROOF_MISSING",
                            detail={
                                "stage": stage,
                                "token": proof_token,
                                "message": "spawned=true but proof file incomplete",
                            },
                        )
                    return ErrorResponse(
                        error_code="SPAWN_PROOF_INCOMPLETE",
                        message=(
                            f"Stage '{stage}' spawned=true 但 spawn proof 未 completed "
                            f"(token={proof_token})——subagent 可能未真实执行。请重新 spawn "
                            f"subagent，并确保它用单个 JSON 覆写 proof 文件为 "
                            f'{{"status":"completed",...}}（不要追加第二段，追加会损坏文件）。'
                        ),
                        current_state=self._state.to_dict(),
                    )

            active_spawn = (
                self._active_action.get("spawn")
                if self._active_action is not None else None
            )
            if (
                isinstance(active_spawn, dict)
                and "invocations" in active_spawn
            ):
                try:
                    plan = SpawnPlan.from_action(self._active_action or {})
                    raw_attestations = result.get("worker_attestations")
                    if not isinstance(raw_attestations, list):
                        raise WorkerAttestationError("ATTESTATION_COUNT_MISMATCH")
                    validate_attestations(
                        action_message_id=str(
                            (self._active_action or {}).get("message_id", "")
                        ),
                        invocations=plan.invocations,
                        attestations=raw_attestations,
                    )
                    strict_missing_receipts: list[str] = []
                    for invocation in plan.invocations:
                        receipt_file = self.project_root / invocation.receipt_path
                        try:
                            receipt = json.loads(
                                receipt_file.read_text(encoding="utf-8")
                            )
                            validate_worker_receipt(
                                receipt,
                                expected_stage=stage,
                                store=ArtifactStore(
                                    self.project_root / ".ae-state" / "artifacts"
                                ),
                                receipt_limit=(
                                    self._runtime_config.max_worker_receipt_bytes
                                ),
                                summary_limit=(
                                    self._runtime_config.max_receipt_summary_bytes
                                ),
                                expected_effort=invocation.requested_effort,
                            )
                        except (OSError, json.JSONDecodeError, ArtifactError):
                            strict_missing_receipts.append(invocation.worker_id)
                    if strict_missing_receipts:
                        return ErrorResponse(
                            error_code="WORKER_RECEIPT_MISSING",
                            message="未收齐严格 Worker receipt: " + ", ".join(
                                strict_missing_receipts
                            ),
                            current_state=self._state.to_dict(),
                        )
                except (SpawnContractError, WorkerAttestationError) as exc:
                    return ErrorResponse(
                        error_code="WORKER_ATTESTATION_INVALID",
                        message=str(exc),
                        current_state=self._state.to_dict(),
                    )

            self._bind_spawn_result_receipt(proof_token, result, challenge_data)

        # 设计冲突是一个独立的 Core 协议结果，不是尚未完成的
        # 可执行计划。上方已完成宿主证据验证；具体请求由
        # _tick_process_result 解析并发出用户 Gate，不进入 plan dry-run。
        if result.get("design_change_requests"):
            return result

        dry_run_error = StageResultPrevalidator().validate(
            stage,
            design_doc=self._design_doc,
            result=result,
            requirement=self._state.requirement,
            research_archive=self._state.research_archive,
            active_revision=(
                self._state.plan_refine_count
                if self._state.refine_request_json
                else 0
            ),
            current_baseline=self._state.architecture_baseline,
            project_root=self.project_root,
            old_batch_plan=[dict(item) for item in self._state.batch_plan],
            reconciliation_evidence=self._state.task_verification_evidence,
            approved_changes=(
                DesignDecisionLedger.project_approved_changes(
                    self._event_store.load_stream(self._state.thread_id)
                )
                if self._event_store is not None else {}
            ),
            refine_request=(
                json.loads(self._state.refine_request_json)
                if self._state.refine_request_json
                else None
            ),
        )
        if dry_run_error:
            return ErrorResponse(
                error_code={
                    "gap_scan": "DESIGN_SCOPE_PROMOTION",
                }.get(stage, "ARCHITECT_PLAN_INVALID"),
                message=f"Architect 计划无法初始化执行树: {dry_run_error}",
                current_state=self._state.to_dict(),
            )

        if result.get("result_type") == "plan_reconciliation":
            from auto_engineering.loop.plan_reconciliation import (
                PlanReconciliationValidator,
            )

            self._state._runtime_ctx["plan_reconciliation_candidate"] = (
                PlanReconciliationValidator(self.project_root).validate(
                    old_batch_plan=[dict(item) for item in self._state.batch_plan],
                    candidate=result,
                    evidence=self._state.task_verification_evidence,
                )
            )

        return result

    def _bind_active_auto_decision(self, result: dict) -> dict:
        """在 Tick 信任边界绑定 Core 生成的自动 Gap 决策。

        Finalizer 是正常产品路径，但恢复时宿主可能直接提交旧 Result。active Action
        仍是唯一权威，不能让提交者通过漏字段或改字段改变线程策略。
        """

        active_action = self._active_action or {}
        auto_decision = active_action.get("auto_decision")
        if (
            self._state.current_stage != "gap_review"
            or not isinstance(auto_decision, dict)
        ):
            return result
        bound = dict(result)
        raw_decision = bound.get("decision")
        decision = dict(raw_decision) if isinstance(raw_decision, dict) else {}
        for key in ("gap_id", "resolution", "decision_source", "policy"):
            if key in auto_decision:
                decision[key] = auto_decision[key]
        bound["decision"] = decision
        return bound

    def _bind_spawn_result_receipt(
        self,
        token: str,
        result: dict[str, Any],
        challenge: dict[str, Any],
    ) -> None:
        """Core 生成确定性 acceptance receipt，绑定 challenge 与 Result 内容。"""
        canonical = json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        payload = {
            "schema_version": "1.0",
            "token": token,
            "thread_id": challenge.get("thread_id"),
            "action_message_id": challenge.get("action_message_id"),
            "stage": challenge.get("stage"),
            "result_sha256": hashlib.sha256(canonical).hexdigest(),
        }
        # Result schema preflight 可在正式接受前重复运行；同一 active Action 的
        # acceptance candidate 以最后一次通过校验的规范化内容为准。
        intent = WriteJsonArtifact(
            relative_path=f"spawn-receipts/{token}.accepted.json",
            payload=payload,
        )
        self._pending_effect_intents.append(intent)
        receipt = EffectExecutor(self.project_root).preview(intent)
        self._pending_effect_receipts.append(receipt)

    def _record_tick_latency(self, t_start: float, tick_no: int) -> None:
        return _record_tick_latency_impl(
            self, t_start, tick_no, budget_ms=ORCH_BUDGET_MS,
        )

    # ── 核心路由 dispatch ──

    def _after_tick(self, result: dict) -> dict:
        stage = self._state.current_stage
        if stage in self._stage_handlers.stages:
            decision = self._build_stage_decision(result)
            return self._apply_stage_decision(decision)
        return ActionError(error_code="UNKNOWN_STAGE",
                           message=f"Unknown stage: {stage}").to_dict()

    def _build_stage_decision(self, result: Mapping[str, Any]) -> TransitionDecision:
        """让 Handler 同时服务 guardrail 预览和正式提交，避免重复投影语义。"""
        stage = self._state.current_stage
        stage_handler = self._stage_handlers.get(stage)
        event_sequence = (
            self._event_store.next_sequence(self._state.thread_id)
            if self._event_store is not None
            else self._state.tick
        )
        return stage_handler.apply(
            self._state.to_dict(),
            result,
            TransitionContext(
                thread_id=self._state.thread_id,
                tick=self._state.tick,
                event_sequence=event_sequence,
                extensions=self._transition_extensions(stage),
            ),
        )

    def _guardrail_state(self, result: Mapping[str, Any]) -> EngineState:
        """以 Handler 事件预览 Guardrail 输入，不提前改变真实状态。"""
        state = self._state
        if state is None:
            raise RuntimeError("EngineState 尚未初始化")
        stage = cast(StageName, state.current_stage)
        if stage not in self._stage_handlers.stages:
            return state
        candidate = deepcopy(state)
        # Guardrail 预览必须具备与当前运行时相同的持久化投影输入。正式提交前
        # 的 ARCHITECTURE_PLAN_ACTIVATED 副作用尚未执行，因此不能让严格的
        # BATCH_COMPLETED Reducer 误把正常开发结果判成投影缺失。
        if self._batch_state is not None and candidate.batch_state_json is None:
            candidate.batch_state_json = self._batch_state.to_json()
        if self._progress_tree is not None and candidate.progress_tree_json is None:
            candidate.progress_tree_json = json.dumps(
                self._progress_tree.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        decision = self._build_stage_decision(result)
        registry = default_reducer_registry()
        for event in decision.events:
            if event.event_type is not LoopEventType.STAGE_ADVANCED:
                candidate = registry.reduce(candidate, event)
        candidate._runtime_ctx["batch_state"] = self._batch_state
        candidate._runtime_ctx["plan"] = self._plan
        candidate._runtime_ctx["active_action"] = self._active_action
        return candidate

    def _transition_extensions(self, stage: str) -> dict[str, object]:
        """装配当前 Tick 的 transition 扩展，并委托唯一工厂。"""
        extensions = TransitionContextFactory().build(
            stage,
            batch_state=self._batch_state,
            progress_tree=self._progress_tree,
            verification_layers=self._verification_layers,
            max_repair_cycles=self._runtime_config.max_repair_cycles,
            p1_threshold=self._get_p1_threshold(),
            gate_results=self._state.gate_results,
        )
        if stage in {"plate_deep_audit", "system_deep_audit"}:
            extensions.update({
                "audit_revision_key": self._audit_revision_key(stage),
                "audit_revision_fingerprint": self._audit_revision_fingerprint(stage),
            })
        prepared = self._state._runtime_ctx.get("architect_prepared")
        if isinstance(prepared, Mapping):
            extensions["architect_prepared"] = prepared
        return extensions

    def _apply_stage_decision(self, decision: TransitionDecision) -> dict:
        """应用纯 Handler 决策；副作用集中保留在 Kernel façade。"""

        action_context = decision.action_context
        transition_effects = TransitionEffectExecutor(
            self._batch_state,
            self._activate_architecture_plan,
            self._record_critic_gate_progress,
            self._progress_tree,
            self._collect_token_usage,
            self._record_completed_batch,
            self._snapshot_developer_output,
            self._persist_state,
            self._offload_stage,
            self._apply_supplement_effect,
            self._pause_stage,
            self._mark_fuzzy_section,
        )
        transition_effects.apply_before_transition(decision.lifecycle_effects)
        reducer_registry = default_reducer_registry()
        cursor_fact_applied = False
        # Reducer 只接受 EventStore 可重放的序列化投影。Handler 读取的是
        # 当前 Tick 的内存投影，因此正式应用 cursor fact 前必须先同步一次；
        # 仅在 _guardrail_state() 中补齐会让预览通过、正式提交却中断。
        self._populate_serialized_state()
        for event in decision.events:
            # Stage 推进由当前 EventStore 事实链负责；其余 Projection 变化统一走纯 Reducer。
            if event.event_type is not LoopEventType.STAGE_ADVANCED:
                self._state = reducer_registry.reduce(self._state, event)
            if event.event_type in {
                LoopEventType.BATCH_COMPLETED,
                LoopEventType.COMPONENT_COMPLETED,
                LoopEventType.PLATE_COMPLETED,
                LoopEventType.WORK_REOPENED,
                LoopEventType.WORK_REPAIR_COMPLETED,
            }:
                cursor_fact_applied = True
        if cursor_fact_applied:
            if self._state.batch_state_json is None:
                raise ValueError("BATCH_PROJECTION_MISSING")
            self._batch_state = BatchState.from_json(
                self._state.batch_state_json,
                self._design_doc,
            )
            if self._state.progress_tree_json is None:
                raise ValueError("PROGRESS_PROJECTION_MISSING")
            self._progress_tree = ProgressTree.from_dict(
                json.loads(self._state.progress_tree_json)
            )
        transition_effects.apply_pre_progress(decision.events)
        transition_effects.apply_after_reducers(decision.lifecycle_effects)
        if self._event_store is not None:
            self._pending_domain_events.extend(decision.events)
        transition_effects.apply_verification_progress(
            decision.lifecycle_effects.verification_progress
        )
        transition_effects.apply_post_progress(decision.events)
        if decision.refine_source is not None:
            return self._handle_plan_refine(decision.refine_source)
        if not cursor_fact_applied:
            # 只读兼容没有稳定身份 payload 的旧在途决策；新写入必须由
            # BATCH_COMPLETED Reducer 更新投影。
            transition_effects.apply_developer_progress(
                decision.lifecycle_effects.developer_progress
            )
        transition_effects.apply_after_progress(decision.lifecycle_effects)
        terminal_action = resolve_terminal_action(
            action_context,
            terminal_action=decision.terminal_action,
        )
        if terminal_action is not None:
            return terminal_action
        convergence = decision.convergence
        if isinstance(convergence, dict):
            counts = decision.audit_counts or (0, 0, 0)
            if isinstance(counts, (list, tuple)) and len(counts) == 3:
                self._write_audit_history(
                    int(counts[0]),
                    int(counts[1]),
                    int(counts[2]),
                    False,
                )
            if decision.display_progress:
                self._display_progress()
            return self._resolve_completion(**convergence)
        if decision.advance_stage:
            self._advance_stage(decision.next_stage)
        feedback = action_context.get("feedback")
        if isinstance(feedback, (list, dict)):
            action = self.build_action(feedback=json.dumps(feedback))
        else:
            pre_gate = action_context.get("pre_gate")
            action = self.build_action(
                pre_gate=pre_gate if isinstance(pre_gate, dict) else None
            ) if pre_gate is not None else self.build_action()
        if decision.display_progress:
            self._display_progress()
        return action

    def _record_completed_batch(self, batch_id: str) -> None:
        self._last_batch_id = batch_id

    def _apply_supplement_effect(self, supplement: Mapping[str, Any]) -> None:
        self._inject_supplement(**dict(supplement))

    def _pause_stage(self, stage: str) -> None:
        self._pause_at_stages.add(stage)

    def _mark_fuzzy_section(self, section: str) -> None:
        if self._progress_tree is None:
            return
        node = self._progress_tree.find_by_design_section(section)
        if node is not None:
            node.design_status = "fuzzy"

    def _activate_architecture_plan(self) -> None:
        """兼容入口：委托独立 ArchitectureActivationService。"""
        emitted: list[LoopEvent] = []

        def emit(event_type: LoopEventType, payload: dict) -> None:
            event = LoopEvent.create(
                thread_id=self._state.thread_id,
                sequence=0,
                event_type=event_type,
                payload=payload,
                correlation_id=self._state.thread_id,
                causation_id=self._current_result_message_id,
            )
            emitted.append(event)
            self._queue_domain_event(event_type, payload)

        result = ArchitectureActivationService(self.project_root).activate(
            state=self._state,
            design_doc=self._design_doc,
            batch_state=self._batch_state,
            progress_tree=self._progress_tree,
            verification_layers=self._verification_layers,
            emit=emit,
        )
        registry = default_reducer_registry()
        for event in emitted:
            self._state = registry.reduce(self._state, event)
        self._batch_state = result.batch_state
        self._plan = result.plan
        self._verification_layers = result.verification_layers
        self._progress_tree = result.progress_tree
        self._state._runtime_ctx.pop("architect_prepared", None)
        self._state._runtime_ctx.pop("plan_reconciliation_candidate", None)
        self._state._runtime_ctx.pop("architecture_candidate", None)
        self._state._runtime_ctx.pop("plan_patch_base_revision", None)
        self._state._runtime_ctx.pop("architect_obligations", None)

    def _snapshot_developer_output(self) -> None:
        """同步进程内上下文；持久快照由 ResultEvidenceRecorded 投影。"""
        snapshot = {
            "files_changed": self._state.files_changed,
            "commit_hash": self._state.commit_hash,
            "test_results": self._state.test_results,
        }
        self._dev_snapshot = snapshot

    def _offload_stage(self, stage: str) -> None:
        """兼容入口：委托独立 StageOffloadService。"""
        if self._context_offloader is None:
            _logger.debug("Injectable '_context_offloader' is None — stage context will not be persisted")
            return
        self._cached_session_summary = StageOffloadService(
            offloader=self._context_offloader,
            summarizer=self._session_summarizer,
        ).offload(
            stage,
            state=self._state,
            batch_state=self._batch_state,
            cached_summary=self._cached_session_summary,
        )

    def _record_critic_gate_progress(self, verdict: str) -> None:
        """更新 Critic gate 的展示进度；协议决策由 Handler 负责。"""
        if (
            self._progress_tree
            and self._batch_state is not None
            and not self._batch_state.is_plate_complete()
        ):
            comp = self._batch_state.current_component()
            node = self._progress_tree.find_by_design_section(comp.design_section)
            if node:
                node.gate_run_count += 1
                if verdict == "APPROVE":
                    node.gate_pass_count += 1

    def _inject_supplement(self, gap: dict, content: str, source: str,
                           source_tier: str | None, confidence: str,
                           created_at: str | None = None) -> None:
        """将细化产出注入 DesignDoc.supplements，并标记节点 stable。"""
        if self._design_doc is not None:
            self._design_doc.supplements[gap["id"]] = Supplement(
                gap_id=gap["id"],
                design_section_ref=gap.get("design_section_ref", ""),
                content=content, source=source, source_tier=source_tier,
                confidence=confidence, created_at=created_at or now_iso())
        if self._progress_tree:
            node = self._progress_tree.find_by_design_section(
                gap.get("design_section_ref", ""))
            if node:
                node.design_status = "stable"

    # ── plan_refine 回路 ──

    def _handle_plan_refine(self, source: str) -> dict:
        refine_request = self._build_refine_request(source)
        if not refine_request.get("gaps"):
            return ErrorResponse(
                error_code="REFINE_INPUT_EMPTY",
                message=(
                    f"回源 '{source}' 请求重规划，但 Core 未生成任何 refine gap；"
                    "已保持当前阶段，禁止进入无法完成的 Architect Action"
                ),
                current_state=self._state.to_dict(),
            ).to_dict()
        src_count = self._state.plan_refine_by_source.get(source, 0)
        if (src_count >= _MAX_PER_SOURCE
                or self._state.plan_refine_count >= _MAX_GLOBAL):
            self._persist_state()
            if src_count >= _MAX_PER_SOURCE:
                reason = (f"REFINE_LIMIT: {source} 分源 "
                          f"{src_count}/{_MAX_PER_SOURCE} 未解决")
            else:
                reason = (f"REFINE_LIMIT: 全局 "
                          f"{self._state.plan_refine_count}/{_MAX_GLOBAL}")
            reason += (" — 建议: 拆分需求为多个 Phase 分别处理, "
                       "或在 design_doc 中标注设计项为延后")
            return ActionDone(
                verdict="REFINE_LIMIT",
                reason=reason,
                acceptance_summary=build_terminal_acceptance_summary(
                    self._state, verdict="REFINE_LIMIT",
                ),
            ).to_dict()

        self._state.plan_refine_by_source[source] = src_count + 1
        self._state.plan_refine_count += 1

        self._state.refine_request_json = json.dumps(refine_request)
        clear_stage_fields(self._state, self._state.current_stage)
        self._advance_stage("architect")
        return self.build_action()

    # _safe_design_section — 已提取到 ActionBuilder (P0-1)

    def _refine_scope(self, source: str) -> tuple[str | None, str | None]:
        """(scope_plate, scope_component) 按源层级 (§B6.10 line 1158-1159).

        component_verifier=组件级 (板块+组件); plate_deep_audit=板块级 (仅板块);
        system_verifier/system_deep_audit=全局 (None/None).
        """
        bs = self._batch_state
        if bs is None:
            return None, None
        if source == "component_verifier":
            return bs.current_plate().name, bs.current_component_name()
        if source == "plate_deep_audit":
            return bs.current_plate().name, None
        return None, None  # system 级 → 全局

    def _build_refine_request(self, source: str) -> dict:
        """归一 coverage_map/audit_findings → RefineRequest dict (§B6.10, T20)."""
        scope_plate, scope_component = self._refine_scope(source)
        req = build_refine_request(
            source=source,
            trigger_tick=self._state.tick,
            scope_plate=scope_plate,
            scope_component=scope_component,
            coverage_map=self._state.coverage_map,
            audit_findings=self._state.audit_findings,
            critic_findings=(
                self._state.open_findings if source == "critic" else None
            ),
        )
        return asdict(req)

    # ── 完成判定 ──

    def _resolve_completion(
        self, design_coverage_ok: bool = False, system_deep_audit_ok: bool = False
    ) -> dict:
        """只依据本 Tick 已提交的验证事实决定是否完成。"""
        if not (design_coverage_ok and system_deep_audit_ok):
            return ErrorResponse(
                error_code="COMPLETION_EVIDENCE_INCOMPLETE",
                message="完成判定缺少设计覆盖或系统深审计事实",
                current_state=self._state.to_dict(),
            ).to_dict()
        verdict = "GOAL_ACHIEVED"

        # T83: Compute metrics signals only on convergence (done verdict).
        # Previously in _build_action() on every tick — moved here so signals
        # reflect terminal state and trend analysis is only triggered at loop end.
        mc = get_collector()
        if mc is not None:
            history = mc.load_history(limit=10)
            baseline = mc.load_baseline()
            enrichment = compute_metrics_signals(
                mc, history=history, baseline=baseline,
                project_root=str(self.project_root),
            )

        if verdict == "GOAL_ACHIEVED":
            self._persist_state()
            action = ActionDone(
                verdict=verdict, reason="设计覆盖与系统深审计均已通过",
                verdict_level=1,
                acceptance_summary=build_terminal_acceptance_summary(
                    self._state,
                    verdict=verdict,
                    design_coverage_ok=design_coverage_ok,
                    system_deep_audit_ok=system_deep_audit_ok,
                ),
            ).to_dict()
            if mc is not None:
                # P0-2: DiagnosticRuleDiscoverer — trigger on requirement completion.
                # 2026-07-25 审计修复(两层):
                #   ① 原调用只传 requirement 文本, 签名要求 verdict + total_ticks
                #      → 每次必抛 TypeError 被静默吞噬;
                #   ② 原接线嵌套在 `and enrichment` 内 — 冷启动/信号管线无历史
                #      数据时 enrichment={}, 整块跳过, 永不触发。需求完成事件应
                #      独立于信号富集是否存在 (BEACON #69 T111)。
                try:
                    mc.end_requirement(
                        verdict=verdict,
                        total_ticks=self._state.tick,
                    )
                    _logger.debug("end_requirement triggered for DiagnosticRuleDiscoverer")
                except Exception:
                    _logger.warning("end_requirement failed (non-fatal)", exc_info=True)
            if mc is not None and enrichment:
                action["metrics"] = enrichment
                # P0-3: RatchetController 接线 — 收敛时执行棘轮判定
                action["ratchet"] = self._run_ratchet(mc, enrichment)
            action = self._commit_terminal_action(action)
            return action

        self._persist_state()
        return ErrorResponse(
            error_code="COMPLETION_EVIDENCE_INCOMPLETE",
            message="完成判定缺少设计覆盖或系统深审计事实",
            current_state=self._state.to_dict(),
        ).to_dict()

    def _commit_terminal_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """终态没有下一轮 build_action，必须显式提交当前 Tick 事实。"""
        if self._event_store is None:
            return action
        revision = RuntimeRevision.from_dict(
            self._state.active_runtime_revision
            or self._current_runtime_revision().to_dict()
        )
        compiled = ActionCompiler().compile(
            payload={
                **action,
                "thread_id": self._state.thread_id,
                "tick": self._state.tick + 1,
                "stage": self._state.current_stage,
            },
            identity=ActionIdentity(
                message_id=str(uuid4()),
                correlation_id=self._state.thread_id,
                causation_id=self._current_result_message_id,
            ),
            runtime_revision=revision,
            issued_at=datetime.now().astimezone().isoformat(),
            effects=(),
        )
        action = dict(compiled.payload)
        self._commit_event_action(action)
        return action

    # ── P1-2: RatchetController 接线 ──

    def _run_ratchet(self, mc, enrichment: dict) -> dict | None:
        """收敛时执行棘轮 keep/revert/stop 判定 + 配置版本化闭环.

        对比 baseline (before) 与当前 enrichment (after) 的 M1-M5 度量,
        返回 RatchetDecision 或 None (度量未启用/无基线时).
        """
        from auto_engineering.metrics.ratchet_runner import run_ratchet

        return run_ratchet(self.project_root, mc, enrichment)

    # P1-9: Escalation handler → loop/escalation_handler.py

    @property
    def action_builder(self) -> ActionBuilder:
        """Read-only access to the ActionBuilder delegate."""
        return self._action_builder

    def _design_authority_events(self) -> list[LoopEvent]:
        """合并已提交事实与当前 Tick candidate 事实。"""

        events: list[LoopEvent] = []
        if self._event_store is not None:
            events.extend(self._event_store.load_stream(self._state.thread_id))
        events.extend(self._pending_domain_events)
        return events

    def _approved_design_changes(self) -> dict[str, dict[str, Any]]:
        return DesignDecisionLedger.project_approved_changes(
            self._design_authority_events()
        )

    def build_action(
        self,
        feedback: str | None = None,
        pre_gate: dict | None = None,
        *,
        project_setup_recovery: bool = False,
    ) -> dict:
        """Build the action dict for the current stage — delegates to ActionBuilder."""
        if pre_gate is None:
            pre_gate = build_design_structure_preflight_gate(self._state.current_stage, self._design_doc)
        if self._event_store is None:
            self._pending_effect_receipts.clear()
            self._pending_effect_intents.clear()
        self._state.action_timestamp = time.time()
        try:
            plan = self.action_builder.build_plan(
                self._state,
                design_authority_projection=self._design_ledger.effective_projection(
                    self._design_authority_events()
                ),
                design_doc=self._design_doc,
                batch_state=self._batch_state,
                plan=self._plan,
                dev_snapshot=self._dev_snapshot,
                progress_tree=self._progress_tree,
                pause_at_stages=self._pause_at_stages,
                passed_checkpoints=self._passed_checkpoints,
                last_batch_id=self._last_batch_id,
                feedback=feedback,
                pre_gate=pre_gate,
                project_setup_recovery=project_setup_recovery,
                pii_enabled=self._pii_enabled,
                pii_redactor=self._pii_redactor,
                pii_outbound=self._runtime_config.pii_outbound,
                artifact_namespace=uuid4().hex,
        )
        except PromptContextError as exc:
            if not str(exc).startswith("PROMPT_CONTEXT_TOO_LARGE"):
                raise
            _logger.error(
                "Prompt context exceeded stage hard limit: stage=%s",
                self._state.current_stage,
            )
            return action_envelope(
                ActionError(
                    error_code="ACTION_CONTEXT_TOO_LARGE",
                    message="当前 Stage 上下文超过单次请求硬限制，已拒绝生成未完整的 Action",
                    suggestion=(
                        "仅保留当前任务、直接依赖和最新失败定位；完整日志请通过 Artifact 引用读取"
                    ),
                ).to_dict(),
                thread_id=self._state.thread_id,
                tick=self._state.tick + 1,
                stage=self._state.current_stage,
                causation_id=self._current_result_message_id,
            )
        action = plan.payload
        if (
            action.get("action") == "resource_wait"
            and isinstance(self._active_action, Mapping)
            and self._active_action.get("message_id")
        ):
            action["active_action_message_id"] = self._active_action["message_id"]
        # Fix C: auto-skip component_verifier when no design data
        if action.get("action") == "skip" and action.get("stage") == "component_verifier":
            _logger.info("Auto-skip component_verifier: %s", action.get("reason", ""))
            self._advance_stage("plate_deep_audit")
            return self.build_action()
        # T54: inject session summary for developer when tick > threshold
        if (action.get("action") == "developer"
                and self._session_summarizer is not None
                and self._session_summarizer.should_summarize(self._state.tick)):
            s = self._state
            # Collect batch progress for richer summary
            batch_files: list[str] = []
            if self._batch_state is not None:
                try:
                    comp = self._batch_state.current_component()
                    for b in self._batch_state.batches_for(comp):
                        for t in b.get("tasks", []):
                            for ft in t.get("file_targets", []):
                                if ft not in batch_files:
                                    batch_files.append(ft)
                except Exception:
                    _logger.debug("batch_files 收集跳过", exc_info=True)
            all_files = list(dict.fromkeys(
                list(s.files_changed or []) + batch_files))

            summary = self._session_summarizer.summarize_structured(
                tick=s.tick,
                test_results=s.test_results or {},
                files_changed=all_files,
                commit_hash=s.commit_hash or "",
                gate_results=dict(s.gate_results or {}),
                critic_verdict=s.critic_verdict or "",
                total_majors=s.total_majors,
                previous_summary=getattr(self, "_cached_session_summary", None),
            )
            injected = self._session_summarizer.inject_into_prompt(summary)
            if injected:
                action["session_summary"] = injected
                self._cached_session_summary = summary
                self._state.session_summary = summary.to_dict()
                # build_action 发生在 stage checkpoint 之后；立即持久化，确保
                # 下一次独立 --tick 进程能恢复刚注入的滚动摘要。
            self._persist_state()
        # v5.8: 先编译候选工作 Action，再以确定性预算决定是否改发 rollover。
        if (
            self._current_result_message_id is not None
            and self._state.pending_runtime_revision is not None
        ):
            activated = dict(self._state.pending_runtime_revision)
            self._state.active_runtime_revision = activated
            self._state.pending_runtime_revision = None
            self._queue_domain_event(
                LoopEventType.RUNTIME_REVISION_ACTIVATED,
                {"runtime_revision": activated},
            )
        revision = RuntimeRevision.from_dict(
            self._state.active_runtime_revision
            or self._current_runtime_revision().to_dict()
        )
        draft = ActionCompiler().compile(
            payload=action,
            identity=ActionIdentity(
                message_id=str(uuid4()),
                correlation_id=self._state.thread_id,
                causation_id=self._current_result_message_id,
            ),
            runtime_revision=revision,
            issued_at=datetime.now().astimezone().isoformat(),
            effects=tuple(self._pending_effect_intents),
        )
        action = dict(draft.payload)
        binding_intents: list[EffectIntent] = []
        binding_receipts: list[EffectReceipt] = []
        binding_builder = copy(self.action_builder)
        binding_builder._effect_intent_sink = binding_intents.append
        binding_builder._effect_sink = binding_receipts.append
        binding_builder.bind_spawn_proofs(action)
        plan = plan.with_effects(
            intents=tuple(binding_intents),
            receipts=tuple(binding_receipts),
        )
        action["extensions"]["policy_snapshot"] = {
            **asdict(self._runtime_config.loop_budget_policy),
            "max_worker_receipt_bytes": (
                self._runtime_config.max_worker_receipt_bytes
            ),
            "max_receipt_summary_bytes": (
                self._runtime_config.max_receipt_summary_bytes
            ),
        }
        action = self._apply_loop_budget(action)
        action = self._apply_context_budget(action)
        if self._state.session_summary:
            drift = informational_drift(
                projection={
                    "stage": self._state.current_stage,
                    "tick": self._state.tick,
                    "active_batch_id": self._last_batch_id,
                    "plan_revision": self._state.plan_refine_count,
                },
                informational=self._state.session_summary,
                source="session_summary",
            )
            if drift:
                action.setdefault("extensions", {})["informational_drift"] = drift
        validate_action_envelope(action)
        if action.get("action") != "error":
            self._pending_effect_intents.extend(plan.effect_intents)
            self._pending_effect_receipts.extend(plan.preview_receipts)
            if self._event_store is not None:
                self._commit_event_action(action)
            else:
                # 无持久化 EventStore 的内存测试 façade 仍需显式
                # 执行已规划 effect；这不是新运行事实源，只是兼容运行时。
                self._execute_pending_effects()
            self._active_action = action
        self.action_builder.log_prompt(self.project_root, action)
        return action

    def _execute_pending_effects(self) -> None:
        """执行当前 Action 的 effect intents，并替换为真实 receipts。"""

        if not self._pending_effect_intents:
            return
        executor = EffectExecutor(self.project_root)
        executed: list[EffectReceipt] = []
        try:
            executed = [
                executor.execute(intent) for intent in self._pending_effect_intents
            ]
        except BaseException:
            executor.discard(executed)
            raise
        self._pending_effect_receipts = list({
            receipt.relative_path: receipt for receipt in executed
        }.values())

    def _current_runtime_revision(self) -> RuntimeRevision:
        """由当前 Prompt 与确定性策略构建 Action 级运行时修订。"""

        policy_payload = {
            "loop_budget": asdict(self._runtime_config.loop_budget_policy),
            "context_budget": asdict(self._runtime_config.context_budget_policy),
        }
        policy_revision = hashlib.sha256(
            json.dumps(
                policy_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return RuntimeRevision(
            protocol_version=SCHEMA_VERSION,
            event_schema_version=EVENT_SCHEMA_VERSION,
            projection_schema_version="1.0",
            action_contract_version="1.1",
            prompt_revision=default_registry().registry_hash(),
            policy_revision=policy_revision,
            engine_build_id=current_build_identity(),
        )

    def _issued_runtime_revision(
        self,
        current: RuntimeRevision,
    ) -> RuntimeRevision:
        """读取当前 active Action 修订；无活动修订时使用当前运行时修订。"""

        if self._active_action is not None:
            raw = (
                self._active_action.get("extensions", {})
                .get("ae", {})
                .get("runtime_revision")
            )
            if isinstance(raw, dict):
                return RuntimeRevision.from_dict(raw)
        if self._state.active_runtime_revision is not None:
            return RuntimeRevision.from_dict(self._state.active_runtime_revision)
        return current

    def _apply_loop_budget(self, candidate: dict[str, Any]) -> dict[str, Any]:
        if candidate.get("action") in {"done", "error", "session_rollover", "gate"}:
            return candidate
        state = self._state
        if state is None:
            return candidate
        candidate_stage = str(candidate.get("action", ""))
        if candidate_stage in {"plate_deep_audit", "system_deep_audit"}:
            revision_key = self._audit_revision_key(candidate_stage)
            revision = self._audit_revision_fingerprint(candidate_stage)
            if state.audit_revision_fingerprints.get(revision_key) == revision:
                return action_envelope(
                    ActionError(
                        "AUDIT_REVISION_UNCHANGED",
                        "代码与审计范围修订未变化，已阻止重复 Deep Audit",
                    ).to_dict(),
                    thread_id=state.thread_id,
                    tick=state.tick + 1,
                    stage=state.current_stage,
                    causation_id=self._current_result_message_id,
                )
        spawn = candidate.get("spawn")
        requested_workers = (
            int(spawn.get("count", 0)) if isinstance(spawn, dict) else 0
        )
        completed_workers = 0
        for item in state.action_history:
            if isinstance(item, dict):
                completed_workers += int(item.get(
                    "spawn_count",
                    _SPAWN_CONFIG.get(item.get("stage"), {}).get("count", 0),
                ))
        outcome = evaluate_loop_budget(
            self._runtime_config.loop_budget_policy,
            LoopUsage(
                repair_cycles=state.plan_refine_count,
                requested_workers=requested_workers,
                completed_workers=completed_workers,
                plate_audits=sum(
                    item.get("stage") == "plate_deep_audit"
                    for item in state.action_history if isinstance(item, dict)
                ),
                system_audits=sum(
                    item.get("stage") == "system_deep_audit"
                    for item in state.action_history if isinstance(item, dict)
                ),
                next_stage=str(candidate.get("action", "")),
            ),
        )
        if outcome.allowed:
            return candidate
        return action_envelope(
            ActionError(
                outcome.error_code or "LOOP_BUDGET_EXCEEDED",
                "循环或 Agent 已达到策略硬上限，已停止继续扩张",
            ).to_dict(),
            thread_id=state.thread_id,
            tick=state.tick + 1,
            stage=state.current_stage,
            causation_id=self._current_result_message_id,
        )

    def _audit_revision_key(self, stage: str) -> str:
        return AuditRevisionService.key(stage, self._batch_state)

    def _audit_revision_fingerprint(self, stage: str) -> str:
        return AuditRevisionService(self.project_root).fingerprint(
            stage,
            self._state,
            self._batch_state,
        )

    def _apply_context_budget(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """仅执行单 Action payload 门禁；正常上下文压缩由宿主管理。"""
        if candidate.get("action") in {"done", "error", "session_rollover"}:
            return candidate
        state = self._state
        if state is None or not state.execution_session_id:
            return candidate
        prompt_bytes = len(json.dumps(
            candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8"))
        outcome = evaluate_budget(
            self._runtime_config.context_budget_policy,
            ContextUsage(
                ticks=0,
                wall_seconds=0,
                input_units=None,
                prompt_bytes=prompt_bytes,
                estimated=False,
            ),
        )
        if outcome.decision is BudgetDecision.CONTINUE:
            return candidate
        if outcome.decision is BudgetDecision.REJECT:
            return action_envelope(
                ActionError(
                    outcome.error_code or "ACTION_CONTEXT_TOO_LARGE",
                    "候选 Action 超过单请求上下文硬限制，已拒绝且未截断",
                ).to_dict(),
                thread_id=state.thread_id,
                tick=state.tick + 1,
                stage=state.current_stage,
                causation_id=self._current_result_message_id,
            )

        return candidate

    # ── T110b: Token 采集 ──

    def _collect_token_usage(self) -> None:
        """T110b: 从 JSONL 转录文件增量采集本 tick 的 token 消耗."""
        if self._usage_collector is None:
            return
        try:
            usage = self._usage_collector.collect()
            if usage.get("input_tokens") or usage.get("output_tokens"):
                provider = usage.get("provider")
                usage_source = usage.get("usage_source") or "unsupported"
                usage["provider"] = provider
                usage["usage_source"] = usage_source
                self._state.tick_token_usage = usage
                self._state.session_input_units += int(
                    usage.get("input_tokens", 0)
                )
                if self._runtime_config.token_tracking_enabled:
                    active_action = self._active_action or {}
                    payload_bytes = len(json.dumps(
                        active_action,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8"))
                    manifest = (
                        active_action.get("extensions", {})
                        .get("context_manifest", {})
                    )
                    # Usage is a semantic EventStore fact, committed with this
                    # Tick. No second usage database may participate in Loop
                    # recovery or status.
                    self._queue_domain_event(
                        LoopEventType.USAGE_RECORDED,
                        {
                            "usage": {
                                "session_id": (
                                    self._state.execution_session_id
                                    or self._state.thread_id
                                ),
                                "tick": self._state.tick,
                                "stage": self._state.current_stage or "unknown",
                                "worker": self._state.current_stage or "main",
                                "input_units": usage.get("input_tokens"),
                                "cache_read_units": usage.get("cache_read_tokens"),
                                "cache_write_units": usage.get("cache_write_tokens"),
                                "output_units": usage.get("output_tokens"),
                                "provider": provider or "unknown",
                                "model": usage.get("model") or "unknown",
                                "usage_source": usage_source,
                                "estimated": bool(usage.get("estimated", False)),
                                "core_payload_bytes": payload_bytes,
                                "inline_unique_bytes": manifest.get(
                                    "total_inline_bytes"
                                ),
                                "duplicate_block_bytes": manifest.get(
                                    "duplicate_block_bytes"
                                ),
                                "host_context_window_units": usage.get(
                                    "host_context_window_units"
                                ),
                                "estimator_version": usage.get(
                                    "estimator_version", ""
                                ),
                                "action_message_id": (
                                    active_action.get("message_id")
                                    if isinstance(active_action, dict)
                                    else None
                                ),
                            }
                        },
                    )
                _logger.debug(
                    "Token collect: tick=%d input=%d output=%d model=%s",
                    self._state.tick, usage["input_tokens"],
                    usage["output_tokens"], usage.get("model", ""))
        except (OSError, ValueError, KeyError, TypeError):
            _logger.debug("Token collect failed", exc_info=True)

    # ── Result 验证 ──

    def _normalize_result_section_findings(
        self, result: dict,
    ) -> ErrorResponse | None:
        return _normalize_result_section_findings_impl(self, result)

    def _validate_gap_analysis(self, result: dict) -> ErrorResponse | None:
        return _validate_gap_analysis_impl(self, result)

    def _validate_component_verifier_scope(self, result: dict) -> ErrorResponse | None:
        return _validate_component_verifier_scope_impl(self, result)

    def _validate_execution_scope(self, result: dict) -> ErrorResponse | None:
        return _validate_execution_scope_impl(self, result)

    def _validate_critic_scope(self, result: dict) -> ErrorResponse | None:
        return _validate_critic_scope_impl(self, result)

    def _validate_global_evidence_scope(self, result: dict) -> ErrorResponse | None:
        return _validate_global_evidence_scope_impl(self, result)

    def _validate_gap_review_decisions(self, result: dict) -> ErrorResponse | None:
        return _validate_gap_review_decisions_impl(self, result)

    def _scan_inbound_for_pii(self, result: dict) -> dict | ErrorResponse:
        return _apply_inbound_pii_policy_impl(self, result)

    def _apply_result_to_state(self, result: dict) -> None:
        """只准备 Architect 的瞬时 Candidate；持久结果由 Handler 事件提交。"""
        if result.get("stage") == "architect":
            extensions = result.get("extensions")
            raw_coverage = (
                extensions.get("architect_plan_coverage")
                if isinstance(extensions, Mapping)
                else None
            )
            if isinstance(raw_coverage, Mapping):
                self._state._runtime_ctx["architect_plan_coverage"] = deepcopy(
                    dict(raw_coverage)
                )
            else:
                self._state._runtime_ctx.pop("architect_plan_coverage", None)
            preparation = ArchitectResultPreparer().prepare(self._state, result)
            prepared = {
                "evidence_changes": preparation.evidence_changes,
                "plan_reconciliation_changes": (
                    preparation.plan_reconciliation_changes
                ),
                "superseded_tasks": list(preparation.superseded_tasks),
            }
            self._state._runtime_ctx["architect_prepared"] = prepared
            if preparation.plan_reconciliation_changes is not None or result.get("plan_patch") is not None:
                self._state._runtime_ctx["architecture_candidate"] = (
                    preparation.candidate
                )
            else:
                self._state._runtime_ctx.pop("architecture_candidate", None)
            if preparation.plan_patch_base_revision is None:
                self._state._runtime_ctx.pop("plan_patch_base_revision", None)
            else:
                self._state._runtime_ctx[
                    "plan_patch_base_revision"
                ] = preparation.plan_patch_base_revision
            self._state._runtime_ctx["architect_obligations"] = list(
                preparation.candidate.get("obligations", [])
            )
            return

    # ── 辅助 ──

    def _advance_stage(self, next_stage: str | None) -> None:
        if next_stage is None:
            return
        previous_stage = self._state.current_stage
        clear_stage_fields(self._state, self._state.current_stage)
        self._state.current_stage = next_stage
        self._state.expected_stage = next_stage
        self._state.tick += 1
        self._state.guardrail_retry_counters[next_stage] = 0
        has_transition_fact = any(
            event.event_type is LoopEventType.STAGE_ADVANCED
            and event.to_dict()["payload"].get("from") == previous_stage
            and event.to_dict()["payload"].get("to") == next_stage
            for event in self._pending_domain_events
        )
        if self._event_store is not None and not has_transition_fact:
            self._queue_domain_event(
                LoopEventType.STAGE_ADVANCED,
                {"from": previous_stage, "to": next_stage},
            )
        if self._event_store is not None:
            self._persist_state()

    def _run_developer_gates(self, *, state: EngineState | None = None) -> None:
        """兼容入口：委托独立 DeveloperGateService。"""
        gate_state = state or self._state
        self._t_gate_ms += DeveloperGateService(self._tick_gate_runner).run(
            state=gate_state,
            batch_state=self._batch_state,
            developer_snapshot=self._dev_snapshot,
        )
        if gate_state is not self._state:
            # Gate 只拥有 telemetry / evidence 事实；业务 Result 仍由 Handler
            # 的 ResultEvidenceRecorded 事件提交，避免恢复旧 Projector 旁路。
            self._state.gate_results = gate_state.gate_results
            self._state.task_verification_evidence = (
                gate_state.task_verification_evidence
            )

    def _handle_guardrail_result(self, gr) -> dict:
        action = getattr(gr, "action", "block")
        message = getattr(gr, "message", "") or f"Guardrail {action} with no message"
        return ActionError(
            error_code=f"GUARDRAIL_{action.upper()}",
            message=message).to_dict()

    def _get_p1_threshold(self) -> int:
        """Return P1 threshold for deep audit pass/fail decisions.

        T131 Bayesian wiring: ThresholdLearner is always attempted (P1-11 fix).
        The learner handles cold start gracefully — returns default value (10)
        when no data has been accumulated yet. Falls back to DEFAULT_P1_THRESHOLD
        on import/IO errors.
        """
        try:
            from auto_engineering.metrics.threshold_learner import ThresholdLearner
            learner = ThresholdLearner(self.project_root / ".ae-state" / "metrics")
            learned = learner.compute_max_iter()
            if learned != 10:  # 10 is the cold-start default — no real data yet
                return max(2, min(8, learned // 2))
        except (ImportError, FileNotFoundError, ValueError, TypeError, OSError):
            _logger.debug("self-learned threshold fallback to default %s", DEFAULT_P1_THRESHOLD, exc_info=True)
        return DEFAULT_P1_THRESHOLD

    def _write_audit_history(self, p0: int, p1: int, p2: int,
                             triggered: bool) -> None:
        """Record audit findings to state for cross-tick tracking."""
        if not any([p0, p1, p2]):
            return
        self._state.audit_findings_count = {"p0": p0, "p1": p1, "p2": p2}
        _logger.info(
            "audit findings recorded: P0=%d P1=%d P2=%d triggered=%s",
            p0, p1, p2, triggered)

    def _persist_state(self) -> None:
        """准备当前投影，随后由单 Tick EventStore 事务提交。"""
        if self._event_store is None:
            return
        self._populate_serialized_state()

    def _commit_event_action(self, action: dict[str, Any]) -> None:
        """将当前状态与出站 Action 作为一个 EventStore Tick 原子提交。"""

        if self._event_store is None or self._state is None:
            return
        sequence = self._event_store.next_sequence(self._state.thread_id)
        previous = self._event_store.load_projection(self._state.thread_id)
        # EventStore 事务不能回滚 Python 内存对象；在编译/提交前保存所有可变派生状态，
        # 避免失败重试携带半推进的 batch、进度、历史或 active Action。
        state_snapshot = deepcopy(self._state)
        batch_state_snapshot = deepcopy(self._batch_state)
        progress_tree_snapshot = deepcopy(self._progress_tree)
        active_action_snapshot = deepcopy(self._active_action)
        result_causation_id = (
            self._active_action.get("message_id")
            if self._active_action is not None
            else None
        )
        try:
            candidate = TickKernel().compile_commit(
                next_sequence=sequence,
                previous_state=previous,
                current_state=self._state,
                action=action,
                pending_events=tuple(self._pending_domain_events),
                result_message_id=self._current_result_message_id,
                result_causation_id=result_causation_id,
            )
            self._execute_pending_effects()
            self._event_store.commit_tick(
                events=candidate.events,
                state=self._state,
                action=action,
                result_causation_id=self._current_result_causation_id,
                result_hash=self._current_result_hash,
                effect_receipts=tuple({
                    receipt.relative_path: receipt
                    for receipt in self._pending_effect_receipts
                }.values()),
            )
            self._pending_domain_events.clear()
            self._pending_effect_receipts.clear()
            self._pending_effect_intents.clear()
        except BaseException:
            # EventStore 回滚后，命名 JSON 产物也必须回滚；内容寻址 prompt
            # 由 EffectExecutor 保留，供后续相同 Action 安全复用。
            try:
                EffectExecutor(self.project_root).discard(
                    tuple(self._pending_effect_receipts)
                )
            except Exception:
                _logger.debug("uncommitted effect cleanup failed", exc_info=True)
            restored = self._event_store.load_projection(self._state.thread_id)
            if restored is not None:
                self._state = restored
            else:
                self._state = state_snapshot
            self._batch_state = batch_state_snapshot
            self._progress_tree = progress_tree_snapshot
            self._active_action = active_action_snapshot
            # 这些对象对应本次未提交 Tick；必须清空，避免下一次重试重复写入。
            self._pending_domain_events.clear()
            self._pending_effect_receipts.clear()
            self._pending_effect_intents.clear()
            raise

    def _populate_serialized_state(self) -> None:
        """save 前把 in-memory 派生状态序列化回 EngineState (A3 写侧, T9b).

        跨进程 restore 从这些字段重建 _batch_state/_progress_tree — 不 populate
        则游标每 tick 归零. batch_state_json 每 save 必写 (to_json 仅 4 int, 廉价);
        progress_tree_json 兜底 (_display_progress 非每 tick 展示 → 保证一致).
        """
        if self._state is None:
            return
        if self._batch_state is not None:
            self._state.batch_state_json = self._batch_state.to_json()
        if self._progress_tree is not None:
            self._state.progress_tree_json = json.dumps(
                self._progress_tree.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        if self._cached_session_summary is not None:
            self._state.session_summary = (
                self._cached_session_summary.to_dict()
            )

    # _resolve_batch_id — 已提取到 ActionBuilder (P0-1)

    def _display_progress(self) -> None:
        """自动展示进度树 (同 tick 去重). 走 stderr, 不污染 stdout action JSON 契约."""
        if not self._progress_tree:
            return
        if self._progress_tree.last_displayed_tick == self._state.tick:
            return
        self._progress_tree.last_displayed_tick = self._state.tick
        self._progress_tree.updated_at = datetime.now().isoformat()
        self._state.progress_tree_json = json.dumps(
            self._progress_tree.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {self._progress_tree.display()}",
              file=sys.stderr, flush=True)
__all__ = [
    "ORCH_BUDGET_MS",
    "TickOrchestrator",
]
