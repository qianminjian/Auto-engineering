"""v5.6 TickOrchestrator — 离散调用编排器 (C.5, Tick-Based Discrete Invocation).

设计参考: design/v5.6-Design-Loop.md §C.5 (line 2960-3632).

术语:
  tick  — 一次完整的离散调用周期: read result → validate → guardrail → gate
          → convergence judge → build action → save checkpoint → output JSON.
          每次 tick 是独立 Python 进程 (Tick-Based Discrete Invocation).
  step  — tick 内的一个 stage 转换 (e.g. architect→developer→critic).
          一个 tick 恰好跨越一个 step; 收敛判定在每个 tick 结束时执行.
  round — StageRouter 内的累积 stage 轮次, 跨 tick 递增. 对应 EngineState.round.

核心契约:
  - 每 tick Python 输出一个 action dict (stdout JSON) 告诉 Agent 下一步做什么
  - Agent 执行后写 stage-result.json, Python 读回校验
  - Python 绝不自调 LLM — Agent 在 tick 之间做 LLM 工作
  - gate_runner/guardrail/checkpoint_store 可注入 (单元测试 stub, 防挂死)
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from auto_engineering.build_identity import current_build_identity
from auto_engineering.config.constants import _SPAWN_CONFIG, DEFAULT_P1_THRESHOLD, STAGE_TO_ROLE
from auto_engineering.config.runtime_config import RuntimeConfig, get_default_config
from auto_engineering.context.offloading import StageContextOffload
from auto_engineering.context.summarization import SessionSummary
from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import DesignDoc, Supplement
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.state import EngineState
from auto_engineering.engine.verification_layers import (
    VerificationLayers,
    determine_verification_layers,
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
    result_contract_warnings,
    validate_result_format,
)
from auto_engineering.loop.architecture_activation import ArchitectureActivationService
from auto_engineering.loop.artifacts import (
    ArtifactError,
    ArtifactStore,
    validate_worker_receipt,
)
from auto_engineering.loop.audit_revision import AuditRevisionService
from auto_engineering.loop.checkpoint.manager import CheckpointManager
from auto_engineering.loop.checkpoint.records import CheckpointNotFoundError
from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
from auto_engineering.loop.context_authority import informational_drift
from auto_engineering.loop.context_budget import (
    BudgetDecision,
    ContextUsage,
    evaluate_budget,
)
from auto_engineering.loop.convergence import ConvergenceConfig, ConvergenceJudge, RoundHistory
from auto_engineering.loop.debug_tracer import DebugTracer, now_iso
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
from auto_engineering.loop.plan import Plan
from auto_engineering.loop.protocol import (
    SCHEMA_VERSION,
    ProtocolErrorCode,
    ProtocolValidationError,
    action_envelope,
    payload_digest,
    validate_action_envelope,
    validate_result_envelope,
)
from auto_engineering.loop.protocol_compat import upgrade_legacy_result
from auto_engineering.loop.reducers import default_reducer_registry
from auto_engineering.loop.refine import build_refine_request
from auto_engineering.loop.runtime_revision import (
    CompatibilityDecision,
    RuntimeRevision,
    evaluate_compatibility,
)
from auto_engineering.loop.session_handoff import SessionHandoff
from auto_engineering.loop.stage_offload import StageOffloadService
from auto_engineering.loop.stage_result_prevalidator import StageResultPrevalidator
from auto_engineering.loop.stage_result_projector import StageResultProjector
from auto_engineering.loop.stage_router import (
    StageRouter,
    clear_stage_fields,
)
from auto_engineering.loop.stages.base import TransitionContext, TransitionDecision
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
from auto_engineering.loop.task_factory import tasks_from_batch_plan
from auto_engineering.loop.tick_gate_runner import TickGateRunner
from auto_engineering.loop.transition_context_factory import TransitionContextFactory
from auto_engineering.loop.transition_effects import TransitionEffectExecutor
from auto_engineering.metrics.collector import AIOrigin, get_collector
from auto_engineering.metrics.enrichment import compute_metrics_signals
from auto_engineering.metrics.transcript_parser import create_parser
from auto_engineering.metrics.usage_ledger import UsageLedger, UsageRecord
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
from auto_engineering.prompts.registry import default_registry


class _GateRunner(Protocol):
    """Typed protocol for gate runner (replaces Callable[..., dict])."""
    def __call__(self, gate_names: tuple[str, ...], project_root: Path,
                 files_changed: list[str] | None = None) -> dict[str, dict]: ...

GateRunner = _GateRunner  # backward-compat alias

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
class _TranscriptParserLike(Protocol):
    """SessionTranscriptParser structural interface (T135c)."""
    def collect(self) -> dict[str, Any]: ...


class TickOrchestrator:
    """Discrete-tick orchestrator with layered verification (C.5).

    Injectables (all optional, for hang-free unit testing):
        gate_runner:    替换 run_gates (同步, 可快速 stub)
        guardrail:      替换 GuardrailChain (stub 跳过子进程)
        checkpoint_store: 替换 SQLiteCheckpointStore (None → no-op save)
    """
    def __init__(
        self,
        project_root: Path | None = None,
        *,
        gate_runner: GateRunner | None = None,
        guardrail: GuardrailChain | None = None,
        checkpoint_store: SQLiteCheckpointStore | None = None,
        event_store: SQLiteEventStore | None = None,
        context_offloader: TickContextOffloader | None = None,
        session_summarizer: TickSessionSummarizer | None = None,
        tracer: _TracerLike | None = None,  # T135c: typed Protocol
        audit_logger: AuditLogger | None = None,
        runtime_config: RuntimeConfig | None = None,
        pii_redactor: PIIRedactor | None = None,
        transcript_parser: _TranscriptParserLike | None = None,  # T135c: typed Protocol
        escalate: bool = False,
        debug: bool = False,
        debug_dir: str | None = None,
    ) -> None:
        self.project_root = project_root or Path.cwd()
        self._audit_logger = audit_logger
        self._escalate = escalate
        self._guardrail = guardrail
        self._checkpoint_store = checkpoint_store
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
        self._transcript_parser = transcript_parser if transcript_parser is not None else create_parser(self.project_root)  # noqa: E501

        self._state: EngineState | None = None
        self._router: StageRouter | None = None
        self._judge: ConvergenceJudge | None = None
        self._plan: Plan | None = None
        self._checkpoint_mgr: CheckpointManager | None = None
        self._project_profile_resolver = ProjectProfileResolver((
            AeConfigProvider(),
            LocalProbeProvider(),
            LegacyInitProvider(),
        ))
        self._project_profile_resolution: ProjectProfileResolution | None = None
        self._design_doc: DesignDoc | None = None
        self._batch_state: BatchState | None = None
        self._progress_tree: ProgressTree | None = None
        self._verification_layers: VerificationLayers | None = None
        self._round_history: list = []  # T1: 在 TickOrchestrator, 非 EngineState 字段
        self._last_completed_stage: str = ""  # E2: 追踪上一完成 stage（延迟结果降级）
        self._last_batch_id: str | None = None  # 跨 stage 传 batch_id (组件完成后无 current)
        self._dev_snapshot: dict[str, Any] | None = None  # developer 产出快照 (供 critic 上下文)
        # DS-10 延迟打点累加器 (每 tick 起始清零, tick() 内累加子进程墙钟)
        self._t_gate_ms: float = 0.0
        self._t_guard_sub_ms: float = 0.0
        # DebugTracer (可选, --debug 或 AE_DEBUG=1 时激活)
        self._debug_tracer: DebugTracer | None = None
        self._last_guardrail: dict | None = None  # FUTURE: 并行 tick 时需 asyncio.Lock
        # T64: Stage Checkpoint Gate (DecisionGate 形态 3)
        self._pause_at_stages: set[str] = set()
        self._passed_checkpoints: set[str] = set()
        # Protocol v1.1: 当前待处理 Action 与已完成 Result 的进程内幂等索引。
        # SQLite 跨进程持久化由同阶段的 checkpoint store 兼容表承载。
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
            effect_sink=self._pending_effect_receipts.append,
            effect_intent_sink=self._pending_effect_intents.append,
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
                save_checkpoint=self._save_checkpoint,
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
        project_root 解析。绝对路径保持原样，便于旧 checkpoint 恢复。
        """
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.project_root / candidate

    def init(
        self,
        requirement: str,
        design_doc_path: str | None = None,
        max_rounds: int = 5,
        thread_id: str | None = None,
    ) -> dict:
        """初始化 loop。有设计文档时解析层次并进入 gap_scan; 否则直接 architect.

        ProjectProfile 不完整时发出 project_setup_required，由宿主补齐后重新探测。
        """
        if design_doc_path:
            self._design_doc = DesignDoc.parse(
                self._resolve_design_doc_path(design_doc_path))

        # T109b: L1 — requirement PII 扫描 (不阻断, 仅 WARN)
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
        self._state.active_runtime_revision = self._current_runtime_revision().to_dict()
        if design_doc_path:
            # 持久化路径 — 跨进程 restore 据此重 parse 设计文档 (T9a)
            self._state.design_doc_path = design_doc_path

        # DebugTracer 激活 (--debug 或 AE_DEBUG=1)
        if self._debug_enabled:
            debug_path = Path(self._debug_dir) if self._debug_dir else (
                self.project_root / "_scratch" / "debug")
            self._state.debug_enabled = True
            self._state.debug_dir = str(debug_path)
            self._debug_tracer = DebugTracer(debug_path)

        self._router = StageRouter()
        self._judge = ConvergenceJudge(ConvergenceConfig(max_iterations=max_rounds))
        self._checkpoint_mgr = CheckpointManager(self._checkpoint_store)

        if self._guardrail is None:
            self._guardrail = GuardrailChain.default()

        try:
            self._project_profile_resolution = self._project_profile_resolver.resolve(self.project_root)
        except ProjectProfileError as exc:
            self._state.current_stage = "project_setup"
            self._state.expected_stage = "project_setup"
            self._state.missing_project_capabilities = ["project_profile_conflict"]
            self._queue_domain_event(
                LoopEventType.PROJECT_PROFILE_CONFLICT,
                {"error_code": exc.code.value, "message": str(exc)},
            )
            self._save_checkpoint()
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
                self._save_checkpoint()
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
            self._save_checkpoint()
            return self.build_action(pre_gate=self.escalation.build_agent_escalation_gate(None))

        if self._design_doc:
            self._state.current_stage = "gap_scan"
            self._state.expected_stage = "gap_scan"
        else:
            self._state.current_stage = "architect"
            self._state.expected_stage = "architect"
        self._state.tick = 0
        self._save_checkpoint()
        return self.build_action()

    @classmethod
    def restore(
        cls,
        project_root: Path,
        checkpoint_store: SQLiteCheckpointStore,
        *,
        checkpoint_id: str | None = None,
        gate_runner: GateRunner | None = None,
        guardrail: GuardrailChain | None = None,
        context_offloader: TickContextOffloader | None = None,
        session_summarizer: TickSessionSummarizer | None = None,
        tracer: Any | None = None,
        audit_logger: AuditLogger | None = None,
        runtime_config: RuntimeConfig | None = None,
        max_rounds: int = 5,
        debug: bool = False,
        debug_dir: str | None = None,
        event_store: SQLiteEventStore | None = None,
        thread_id: str | None = None,
    ) -> TickOrchestrator:
        """跨进程恢复 (§A.1: 每 tick 独立进程, 从 SQLite 重建全部 in-memory 状态)."""
        self = cls(
            project_root,
            gate_runner=gate_runner,
            guardrail=guardrail,
            checkpoint_store=checkpoint_store,
            event_store=event_store,
            context_offloader=context_offloader,
            session_summarizer=session_summarizer,
            tracer=tracer,
            audit_logger=audit_logger,
            runtime_config=runtime_config,
            debug=debug,
            debug_dir=debug_dir,
        )

        ck = None
        if event_store is not None:
            resolved_thread_id = thread_id or checkpoint_store.active_project_thread()
            if resolved_thread_id is None:
                raise CheckpointNotFoundError("无 active EventStore thread 可恢复")
            state = event_store.load_projection(resolved_thread_id)
            if state is None:
                raise CheckpointNotFoundError(
                    f"EventStore 无状态投影 (thread_id={resolved_thread_id})"
                )
            from auto_engineering.loop.checkpoint.records import RoundHistory
            self._round_history = [
                RoundHistory(**item)
                for item in event_store.load_round_history(resolved_thread_id)
            ]
            self._active_action = event_store.load_action_snapshot(resolved_thread_id)
        else:
            ck = (checkpoint_store.load(checkpoint_id) if checkpoint_id
                  else checkpoint_store.load_latest())
            if ck is None:
                raise CheckpointNotFoundError(
                    f"无 checkpoint 可恢复 (project_root={project_root})")
            state = ck.state
            self._round_history = list(ck.history or [])
            self._active_action = checkpoint_store.load_active_protocol_action(
                state.thread_id if not isinstance(state, dict) else state["thread_id"]
            )
        if isinstance(state, dict):  # 防御: deserialize 未命中 EngineState 分派
            state = EngineState.from_dict(state)
        self._state = state
        self._dev_snapshot = (
            dict(state.developer_snapshot)
            if state.developer_snapshot is not None
            else None
        )

        # 协作组件 (无状态 / 从 store 重建)
        self._router = StageRouter()
        self._judge = ConvergenceJudge(ConvergenceConfig(max_iterations=max_rounds))
        self._checkpoint_mgr = CheckpointManager(checkpoint_store)
        if self._guardrail is None:
            self._guardrail = GuardrailChain.default()

        # 持久化 Profile 只作审计快照；恢复必须重新读取当前本地证据。
        previous_profile_id = state.project_profile_id
        resolution = self._project_profile_resolver.resolve(project_root)
        if (
            resolution.status is not ResolutionStatus.RESOLVED
            and state.current_stage != "project_setup"
        ):
            raise CheckpointNotFoundError(
                "PROJECT_PROFILE_REVALIDATION_REQUIRED: 当前项目证据不足，"
                "不能继续使用 checkpoint 中的陈旧 Profile"
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
            self._design_doc = DesignDoc.parse(
                self._resolve_design_doc_path(state.design_doc_path))

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
            raise CheckpointNotFoundError(
                "RUNTIME_REVISION_INCOMPATIBLE: active Action 协议无法由当前运行时消费"
            )
        if compatibility is CompatibilityDecision.MIGRATION_REQUIRED:
            raise CheckpointNotFoundError(
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
            result = upgrade_legacy_result(result, self._active_action)
            envelope = validate_result_envelope(result)
        except (json.JSONDecodeError, OSError) as exc:
            return ErrorResponse(
                "RESULT_PARSE_ERROR", f"无法解析 result 文件: {exc}"
            ).to_dict()
        except ProtocolValidationError as exc:
            return ErrorResponse(exc.code, str(exc)).to_dict()
        if (
            envelope.thread_id != self._state.thread_id
            or self._active_action is None
            or envelope.causation_id != self._active_action.get("message_id")
        ):
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
            result = upgrade_legacy_result(result, self._active_action)
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
            if (
                replay is None
                and result_causation
                and self._checkpoint_store is not None
            ):
                replay = self._checkpoint_store.load_protocol_result(
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
            if (
                envelope.thread_id != self._state.thread_id
                or self._active_action is None
                or result_causation != self._active_action.get("message_id")
            ):
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
                    if self._checkpoint_store is not None:
                        action = self._checkpoint_store.claim_session(
                            claim_token=result["claim_token"],
                            session_id=result["session_id"],
                            host=result["host"],
                        )
                    else:
                        action = self._session_handoff.claim(result)
                    self._state.execution_session_id = result["session_id"]
                    self._state.session_start_tick = self._state.tick
                    self._state.session_started_at = datetime.now().astimezone().isoformat()
                    self._state.session_input_units = 0
                    self._active_action = action
                    self._save_checkpoint()
                    if self._checkpoint_store is not None:
                        self._checkpoint_store.record_protocol_action(action)
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
            action = action_envelope(
                action,
                thread_id=self._state.thread_id,
                tick=action.get("tick", self._state.tick + 1),
                stage=action.get("stage", self._state.current_stage),
                causation_id=self._current_result_message_id,
            )
        result_accepted = action.get("action") not in {"error", "resource_wait"}
        if native_result and result_causation and result_hash and result_accepted:
            self._result_replays[result_causation] = (result_hash, action)
            if self._checkpoint_store is not None and self._event_store is None:
                self._checkpoint_store.record_protocol_result(
                    self._state.thread_id,
                    result_causation,
                    result_hash,
                    action,
                )
        self._current_result_message_id = None
        self._current_result_causation_id = None
        self._current_result_hash = None
        duration_ms = int((time.perf_counter() - t_start) * 1000)

        if tick_span is not None:
            tick_span.set_attribute("duration_ms", duration_ms)
            tick_span.set_attribute("action", action.get("action", ""))
            tick_span.end()
        self._record_tick_latency(t_start, tick_no)

        # T69a: Record tick completion event for metrics collector.
        # Only record successful ticks — error/retry submissions inflate M1.
        is_error = isinstance(action, dict) and action.get("action") == "error"
        mc = get_collector()
        if mc is not None and not is_error:
            verdict = ""
            if action.get("action") == "done":
                verdict = action.get("verdict", "")
            elif stage_in == "critic":
                # T80: 传递 critic MAJOR/APPROVE 供 M2 统计
                verdict = self._state.critic_verdict
            mc.record_tick_complete(
                tick_number=tick_no + 1,
                stage=stage_in,
                duration_ms=duration_ms,
                verdict=verdict,
                ai_origin=AIOrigin(
                    level="led",
                    agent_role=stage_in,
                    driver_type="agent",
                ),
            )

        # DebugTracer + Metrics: 记录 per-tick 快照
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
            # Metrics: bridge per-tick snapshots into metrics storage
            if mc is not None:
                mc.record_tick_snapshot(
                    tick_number=tick_no + 1,
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
                "GOAL_ACHIEVED", "HARD_LIMIT", "REFINE_LIMIT", "STAGNANT",
            ):
                self._debug_tracer.finalize(
                    verdict=verdict or "UNKNOWN",
                    total_ticks=tick_no + 1,
                )
                # T80: Record convergence with criteria_met for M2 calculation
                if mc is not None:
                    criteria_map = {
                        "GOAL_ACHIEVED": "critic_approved",
                        "HARD_LIMIT": "hard_limit",
                        "REFINE_LIMIT": "plan_refine",
                        "STAGNANT": "stagnant",
                        "TERMINATED": "terminated",
                    }
                    criteria_met = criteria_map.get(verdict, verdict.lower())
                    mc.record_convergence(
                        verdict=verdict or "UNKNOWN",
                        total_ticks=tick_no + 1,
                        criteria_met=criteria_met,
                        ai_origin=AIOrigin(
                            level="led",
                            agent_role=self._state.current_stage if self._state else "?",
                            driver_type="agent",
                        ),
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
        payload = ErrorResponse(
            error_code=code.value,
            message=message,
            current_state=state.to_dict() if state else None,
        ).to_dict()
        return action_envelope(
            payload,
            thread_id=state.thread_id if state else "unknown",
            tick=(state.tick + 1) if state else 0,
            stage=state.current_stage if state else None,
            causation_id=causation_id,
        )

    def _tick_body_dict(self, result: dict) -> dict:
        """tick 核心逻辑 (dict 版本): Gate resolution → 验证 → Guardrail → Gate → 路由 → action."""
        if self._state.current_stage == "project_setup":
            validated = self._validate_result_dict(result)
            if isinstance(validated, ErrorResponse):
                return validated.to_dict()
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
            return {
                "action": "resource_wait",
                "stage": self._state.current_stage,
                "resource": "agent_slot",
                "retry_stage": self._state.current_stage,
                "reason_code": "HOST_AGENT_CAPACITY",
                "message": "宿主 Agent 容量暂时不足；保留当前 Action，等待资源后重试。",
                "suggestion": "回收已完成的 Agent；容量释放后重新执行当前 Action。",
            }

        # T64: handle gate_resolution before validation (no stage field)
        gate_resolution = result.get("gate_resolution")
        if gate_resolution and isinstance(gate_resolution, dict):
            return self._tick_process_result(result)

        # E2: STAGE_MISMATCH 降级 — Agent 提交上一 stage 的延迟结果时，
        # 不再报错，接受结果并重建当前 stage 的 action。
        # 解决 T51c-T51f spawn 校验被 stage 不匹配错误短路的问题。
        result_stage = result.get("stage", "")
        if (result_stage
                and result_stage != self._state.current_stage
                and result_stage == self._last_completed_stage):
            _logger.warning(
                "E2 downgrade: Agent sent stale result for '%s' "
                "(orchestrator already at '%s'). Accepting + rebuilding action.",
                result_stage, self._state.current_stage,
            )
            self._apply_result_to_state(result)
            self._record_tick_latency(time.perf_counter(), self._state.tick)
            StageGateDispatcher().dispatch(
                self._state.current_stage,
                self._run_developer_gates,
            )
            return self.build_action()

        validated = self._validate_result_dict(result)
        return self._tick_process_result(validated)

    def _tick_process_result(self, result: dict | ErrorResponse) -> dict:
        """tick 公共处理逻辑: Gate resolution → Guardrail → Gate → 路由 → action."""
        if isinstance(result, ErrorResponse):
            if self._require("_debug_tracer", "debug tracing disabled") is not None:
                self._debug_tracer.record_error(
                    tick=self._state.tick,
                    category=result.error_code,
                    detail={"message": result.message},
                )
            return result.to_dict()

        # T64+T95: handle gate_resolution — dispatch by gate type
        gate_resolution = result.get("gate_resolution")
        if gate_resolution and isinstance(gate_resolution, dict):
            gate_id = gate_resolution.get("gate_id", "")
            resolution = gate_resolution.get("resolution", "")

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

            # Stage Checkpoint Gate (T64) — gate_id starts with "checkpoint_"
            if gate_id.startswith("checkpoint_"):
                if resolution == "终止 loop":
                    return {
                        "action": "done",
                        "verdict": "TERMINATED",
                        "message": f"用户通过 {gate_id} 终止 loop",
                        "stage": self._state.current_stage,
                        "tick": self._state.tick + 1,
                        "thread_id": self._state.thread_id,
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
                }
            detail = gate_resolution.get("resolution_detail", {})
            note = detail.get("note", "")
            feedback = f"Gate '{gate_id}' resolved: {resolution}"
            if note:
                feedback += f" — {note}"
            self._save_checkpoint()
            return self.build_action(feedback=feedback)

        self._apply_result_to_state(result)

        # 挂运行时非持久句柄供 Guardrail (G7 REDGuardrail 读 batch_state/_plan, B3 line 657).
        # asdict 只序列化 dataclass 字段 → 不泄漏进 checkpoint.
        self._state._runtime_ctx["batch_state"] = self._batch_state
        self._state._runtime_ctx["plan"] = self._plan

        t_g = time.perf_counter()
        gr = self._guardrail.check("post", self._state.current_stage,
                                   self._state, self.project_root)
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
                    self._run_developer_gates,
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
            self._run_developer_gates,
        )

        return self._after_tick(result)

    def _complete_project_setup(self) -> dict:
        """重新探测宿主搭建结果；未满足能力时保持原 active Action。"""
        resolution = self._project_profile_resolver.resolve(self.project_root)
        self._project_profile_resolution = resolution
        if resolution.status is not ResolutionStatus.RESOLVED:
            self._state.missing_project_capabilities = list(resolution.missing_capabilities)
            self._save_checkpoint()
            return ErrorResponse(
                "PROJECT_SETUP_UNVERIFIED",
                "项目搭建结果未通过本地证据验证",
                self._state.to_dict(),
            ).to_dict()
        self._apply_project_profile_resolution(resolution)
        self._queue_domain_event(
            LoopEventType.PROJECT_SETUP_COMPLETED,
            {"profile_id": self._state.project_profile_id},
        )
        previous_stage = self._state.current_stage
        self._state.current_stage = "gap_scan" if self._design_doc else "architect"
        self._state.expected_stage = self._state.current_stage
        self._queue_domain_event(
            LoopEventType.STAGE_ADVANCED,
            {"from": previous_stage, "to": self._state.current_stage},
        )
        self._state.tick += 1
        self._save_checkpoint()
        return self.build_action()

    def _apply_project_profile_resolution(self, resolution: ProjectProfileResolution) -> None:
        profile = resolution.profile
        if profile is None:
            return
        self._state.project_profile = profile.to_dict()
        self._state.project_profile_id = profile.profile_id
        self._state.missing_project_capabilities = list(resolution.missing_capabilities)
        self._tick_gate_runner.reload(profile)

    def _queue_domain_event(self, event_type: LoopEventType, payload: dict[str, Any]) -> None:
        """暂存领域事实，由下一次 EventStore Tick 事务统一分配序列。"""
        if self._state is None:
            return
        self._pending_domain_events.append(
            LoopEvent.create(
                thread_id=self._state.thread_id, sequence=0,
                event_type=event_type, payload=payload,
                correlation_id=self._state.thread_id,
            )
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

        errors = validate_result_format(result, self._state.current_stage)
        if errors:
            return ErrorResponse(
                error_code="RESULT_VALIDATION_ERROR",
                message="; ".join(errors),
                current_state=self._state.to_dict())

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
                        f"Read the action.instruction — spawn the agent with "
                        f"the action.subagent_prompt, collect its output, and set "
                        f"'\"spawned\": true' in the result. "
                        f"Re-run this tick with actual agent spawn."
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
                        # 新 Action 使用不可变 challenge；旧线程没有 challenge 时
                        # 只读兼容其 proof 内身份字段，不能用于新 Action 创建。
                        challenge_data = (
                            json.loads(challenge_file.read_text(encoding="utf-8"))
                            if challenge_file.exists()
                            else proof_data
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

                self._bind_spawn_result_receipt(
                    proof_token, result, challenge_data
                )

                active_spawn = (
                    self._active_action.get("spawn", {})
                    if self._active_action is not None else {}
                )
                active_agents = active_spawn.get("agents", [])
                if isinstance(active_agents, list) and len(active_agents) > 1:
                    missing_receipts: list[str] = []
                    for agent in active_agents:
                        if not isinstance(agent, dict):
                            continue
                        receipt_token = agent.get("receipt_token")
                        if not isinstance(receipt_token, str):
                            missing_receipts.append(
                                f"agent-{agent.get('index', '?')}:token-missing"
                            )
                            continue
                        receipt_file = (
                            self.project_root / ".ae-state" / "spawn-proofs"
                            / f"{receipt_token}.json"
                        )
                        try:
                            receipt = json.loads(
                                receipt_file.read_text(encoding="utf-8")
                            )
                            receipt_ok = validate_worker_receipt(
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
                                expected_effort=str(
                                    agent.get(
                                        "requested_effort",
                                        active_spawn.get("effort", "high"),
                                    )
                                ),
                            )
                        except (OSError, json.JSONDecodeError, ArtifactError):
                            receipt_ok = False
                        if not receipt_ok:
                            missing_receipts.append(receipt_token)
                    if missing_receipts:
                        return ErrorResponse(
                            error_code="WORKER_RECEIPT_MISSING",
                            message=(
                                f"Stage '{stage}' 未收齐 Worker receipt: "
                                + ", ".join(missing_receipts)
                            ),
                            current_state=self._state.to_dict(),
                        )

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
        )
        if dry_run_error:
            return ErrorResponse(
                error_code="ARCHITECT_PLAN_INVALID",
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
        receipt = EffectExecutor(self.project_root).execute(intent)
        self._pending_effect_receipts.append(receipt)

    def _record_tick_latency(self, t_start: float, tick_no: int) -> None:
        """DS-10: 写 tick 延迟记录到 action_history, 超编排预算只告警不中断.

        t_guard_sub 用 guardrail.check() 整段墙钟近似 (纯 Python guardrail 逻辑为
        µs 量级, 相对 git 子进程墙钟可忽略). 精确到子进程级留 Phase 5 观测按需细化.
        """
        if self._state is None:
            return
        t_total_ms = (time.perf_counter() - t_start) * 1000
        t_gate_ms = self._t_gate_ms
        t_guard_sub_ms = self._t_guard_sub_ms
        t_orch_ms = t_total_ms - t_gate_ms - t_guard_sub_ms
        self._state.action_history.append({
            "tick": tick_no,
            "stage": self._state.current_stage,
            "t_total_ms": round(t_total_ms, 2),
            "t_gate_ms": round(t_gate_ms, 2),
            "t_guard_sub_ms": round(t_guard_sub_ms, 2),
            "t_orchestration_ms": round(t_orch_ms, 2),
        })
        if t_orch_ms > ORCH_BUDGET_MS:
            _logger.warning(
                "[latency] tick %d 编排开销 %.0fms 超预算 %dms "
                "(total=%.0f gate=%.0f guard_sub=%.0f)",
                tick_no, t_orch_ms, ORCH_BUDGET_MS,
                t_total_ms, t_gate_ms, t_guard_sub_ms)

    # ── 核心路由 dispatch ──

    def _after_tick(self, result: dict) -> dict:
        stage = self._state.current_stage
        if stage in self._stage_handlers.stages:
            stage_handler = self._stage_handlers.get(stage)
            event_sequence = (
                self._event_store.next_sequence(self._state.thread_id)
                if self._event_store is not None
                else self._state.tick
            )
            decision = stage_handler.apply(
                self._state.to_dict(),
                result,
                TransitionContext(
                    thread_id=self._state.thread_id,
                    tick=self._state.tick,
                    event_sequence=event_sequence,
                    extensions=self._transition_extensions(stage),
                ),
            )
            return self._apply_stage_decision(decision)
        return ActionError(error_code="UNKNOWN_STAGE",
                           message=f"Unknown stage: {stage}").to_dict()

    def _transition_extensions(self, stage: str) -> dict[str, object]:
        """兼容入口：装配参数并委托 TransitionContextFactory。"""
        return TransitionContextFactory().build(
            stage,
            batch_state=self._batch_state,
            verification_layers=self._verification_layers,
            max_repair_cycles=self._runtime_config.max_repair_cycles,
            p1_threshold=self._get_p1_threshold(),
            gate_results=self._state.gate_results,
        )

    @staticmethod
    def _blocking_gate_results(
        gate_results: object,
    ) -> list[dict[str, object]]:
        """Legacy 测试入口；生产路径使用 TransitionContextFactory。"""
        return TransitionContextFactory.blocking_gate_results(gate_results)

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
            self._save_checkpoint,
            self._offload_stage,
            self._apply_supplement_effect,
            self._pause_stage,
            self._mark_fuzzy_section,
        )
        transition_effects.apply_before_transition(decision.lifecycle_effects)
        reducer_registry = default_reducer_registry()
        for event in decision.events:
            # Stage 推进还需执行 round/history/checkpoint 生命周期，暂由 façade
            # 的 _advance_stage 负责；其余 Projection 变化统一走纯 Reducer。
            if event.event_type is not LoopEventType.STAGE_ADVANCED:
                self._state = reducer_registry.reduce(self._state, event)
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
            return self._convergence_check(**convergence)
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
        result = ArchitectureActivationService(self.project_root).activate(
            state=self._state,
            design_doc=self._design_doc,
            batch_state=self._batch_state,
            progress_tree=self._progress_tree,
            verification_layers=self._verification_layers,
            emit=self._queue_domain_event,
        )
        self._batch_state = result.batch_state
        self._plan = result.plan
        self._verification_layers = result.verification_layers
        self._progress_tree = result.progress_tree

    def _snapshot_developer_output(self) -> None:
        """保存 developer 产出快照 (advance_stage 会 clear_stage_fields)."""
        snapshot = {
            "files_changed": self._state.files_changed,
            "commit_hash": self._state.commit_hash,
            "test_results": self._state.test_results,
        }
        self._dev_snapshot = snapshot
        self._state.developer_snapshot = snapshot

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
        if self._progress_tree:
            comp = self._batch_state.current_component()
            node = self._progress_tree.find_by_design_section(comp.design_section)
            if node:
                node.gate_run_count += 1
                if verdict == "APPROVE":
                    node.gate_pass_count += 1

    def _inject_supplement(self, gap: dict, content: str, source: str,
                           source_tier: str | None, confidence: str) -> None:
        """将细化产出注入 DesignDoc.supplements + 序列化到 EngineState + 标记节点 stable."""
        if self._design_doc is not None:
            self._design_doc.supplements[gap["id"]] = Supplement(
                gap_id=gap["id"],
                design_section_ref=gap.get("design_section_ref", ""),
                content=content, source=source, source_tier=source_tier,
                confidence=confidence, created_at=now_iso())
            self._state.design_supplements_json = json.dumps(
                {k: asdict(v) for k, v in self._design_doc.supplements.items()},
                ensure_ascii=False)
        if self._progress_tree:
            node = self._progress_tree.find_by_design_section(
                gap.get("design_section_ref", ""))
            if node:
                node.design_status = "stable"

    # ── plan_refine 回路 ──

    def _handle_plan_refine(self, source: str) -> dict:
        src_count = self._state.plan_refine_by_source.get(source, 0)
        if (src_count >= _MAX_PER_SOURCE
                or self._state.plan_refine_count >= _MAX_GLOBAL):
            self._save_checkpoint()
            if src_count >= _MAX_PER_SOURCE:
                reason = (f"REFINE_LIMIT: {source} 分源 "
                          f"{src_count}/{_MAX_PER_SOURCE} 未解决")
            else:
                reason = (f"REFINE_LIMIT: 全局 "
                          f"{self._state.plan_refine_count}/{_MAX_GLOBAL}")
            reason += (" — 建议: 拆分需求为多个 Phase 分别处理, "
                       "或在 design_doc 中标注设计项为延后")
            return ActionDone(verdict="REFINE_LIMIT", reason=reason).to_dict()

        self._state.plan_refine_by_source[source] = src_count + 1
        self._state.plan_refine_count += 1

        self._state.refine_request_json = json.dumps(
            self._build_refine_request(source))
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
        )
        return asdict(req)

    # ── 收敛判定 ──

    def _convergence_check(
        self, design_coverage_ok: bool = False, system_deep_audit_ok: bool = False
    ) -> dict:
        verdict = self._judge.evaluate(
            self._round_history,
            design_coverage_ok=design_coverage_ok,
            system_deep_audit_ok=system_deep_audit_ok)

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

        if verdict.should_stop:
            self._save_checkpoint()
            action = ActionDone(
                verdict=verdict.level_name, reason=verdict.reason,
                verdict_level=verdict.level).to_dict()
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
                        verdict=verdict.level_name,
                        total_ticks=self._state.tick,
                    )
                    _logger.debug("end_requirement triggered for DiagnosticRuleDiscoverer")
                except Exception:
                    _logger.warning("end_requirement failed (non-fatal)", exc_info=True)
            if mc is not None and enrichment:
                action["metrics"] = enrichment
                # P0-3: RatchetController 接线 — 收敛时执行棘轮判定
                action["ratchet"] = self._run_ratchet(mc, enrichment)
            return action

        self._save_checkpoint()
        action = ActionDone(
            verdict="UNEXPECTED",
            reason="ConvergenceJudge returned CONTINUE after full cycle").to_dict()
        if mc is not None and enrichment:
            action["metrics"] = enrichment
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

    def build_action(self, feedback: str | None = None, pre_gate: dict | None = None) -> dict:
        """Build the action dict for the current stage — delegates to ActionBuilder."""
        if self._event_store is None:
            self._pending_effect_receipts.clear()
            self._pending_effect_intents.clear()
        self._state.action_timestamp = time.time()
        action = self.action_builder.build_action(
            self._state,
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
            pii_enabled=self._pii_enabled,
            pii_redactor=self._pii_redactor,
            pii_outbound=self._runtime_config.pii_outbound,
        )
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
                self._save_checkpoint()
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
        self.action_builder.bind_spawn_proofs(action)
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
            if self._event_store is not None:
                self._commit_event_action(action)
            self._active_action = action
            if self._checkpoint_store is not None and self._event_store is None:
                self._checkpoint_store.record_protocol_action(action)
        self.action_builder.log_prompt(self.project_root, action)
        return action

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
            action_contract_version="1.0",
            prompt_revision=default_registry().registry_hash(),
            policy_revision=policy_revision,
            engine_build_id=current_build_identity(),
        )

    def _issued_runtime_revision(
        self,
        current: RuntimeRevision,
    ) -> RuntimeRevision:
        """读取 active Action 修订；旧线程只把 Prompt hash 转换为 legacy 修订。"""

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
        legacy_prompt = self._state.prompt_registry_hash or current.prompt_revision
        return RuntimeRevision(
            protocol_version=current.protocol_version,
            event_schema_version=current.event_schema_version,
            projection_schema_version=current.projection_schema_version,
            action_contract_version=current.action_contract_version,
            prompt_revision=legacy_prompt,
            policy_revision=current.policy_revision,
            engine_build_id=current.engine_build_id,
        )

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
                completed_workers += int(
                    _SPAWN_CONFIG.get(item.get("stage"), {}).get("count", 0)
                )
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
        if self._transcript_parser is None:
            return
        try:
            usage = self._transcript_parser.collect()
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
                    ledger = UsageLedger(
                        self.project_root / ".ae-state" / "usage-ledger.db"
                    )
                    try:
                        ledger.append(UsageRecord(
                            thread_id=self._state.thread_id,
                            session_id=(
                                self._state.execution_session_id or "legacy-session"
                            ),
                            tick=self._state.tick,
                            stage=self._state.current_stage or "unknown",
                            worker=self._state.current_stage or "main",
                            input_units=usage.get("input_tokens"),
                            cache_read_units=usage.get("cache_read_tokens"),
                            cache_write_units=usage.get("cache_write_tokens"),
                            output_units=usage.get("output_tokens"),
                            provider=provider or "unknown",
                            model=usage.get("model") or "unknown",
                            usage_source=usage_source,
                            estimated=bool(usage.get("estimated", False)),
                            core_payload_bytes=payload_bytes,
                            inline_unique_bytes=manifest.get(
                                "total_inline_bytes"
                            ),
                            duplicate_block_bytes=manifest.get(
                                "duplicate_block_bytes"
                            ),
                            host_context_window_units=usage.get(
                                "host_context_window_units"
                            ),
                            estimator_version=usage.get(
                                "estimator_version", ""
                            ),
                        ))
                    finally:
                        ledger.close()
                _logger.debug(
                    "Token collect: tick=%d input=%d output=%d model=%s",
                    self._state.tick, usage["input_tokens"],
                    usage["output_tokens"], usage.get("model", ""))
                # 2026-07-25 审计修复: 记录到 collector, 打通 M5 数据流。
                # 原实现只写 state.tick_token_usage, 从未调用
                # record_token_usage() → token_events 恒空, M5 结构性为零。
                mc = get_collector()
                if mc is not None:
                    mc.record_token_usage(
                        input_tokens=usage["input_tokens"],
                        output_tokens=usage["output_tokens"],
                        model=usage.get("model", "unknown"),
                        provider=provider or "unsupported",
                        stage=self._state.current_stage or "",
                        ai_origin=AIOrigin(
                            level="led",
                            agent_role=self._state.current_stage or "",
                            driver_type="agent",
                        ),
                    )
        except (OSError, ValueError, KeyError, TypeError):
            _logger.debug("Token collect failed", exc_info=True)

    # ── read/validate/apply ──

    def _read_and_validate(self, result_file: Path) -> dict | ErrorResponse:
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            return ErrorResponse(
                error_code="RESULT_PARSE_ERROR",
                message=f"无法解析 result 文件: {e}",
                current_state=self._state.to_dict() if self._state else None)

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

        errors = validate_result_format(result, self._state.current_stage)
        if errors:
            return ErrorResponse(
                error_code="RESULT_VALIDATION_ERROR",
                message="; ".join(errors),
                current_state=self._state.to_dict())

        if gap_error := self._validate_gap_analysis(result):
            return gap_error

        if gap_error := self._validate_gap_review_decisions(result):
            return gap_error

        # T109d: L3 — inbound result JSON PII scan
        return self._scan_inbound_for_pii(result)

    def _validate_gap_analysis(self, result: dict) -> ErrorResponse | None:
        """Gap Scan 必须提供足以让用户判断的完整分析，不接受空洞摘要。"""
        if self._state.current_stage != "gap_scan":
            return None
        required = {
            "evidence", "problem_statement", "impact", "dependencies",
            "recommendation", "options", "blocking_rule",
        }
        gaps = result.get("gaps", [])
        for index, gap in enumerate(gaps):
            if not isinstance(gap, dict):
                return ErrorResponse(
                    "GAP_ANALYSIS_INCOMPLETE",
                    f"gaps[{index}] 必须是 object",
                    self._state.to_dict(),
                )
            missing = sorted(required - set(gap))
            recommendation = gap.get("recommendation")
            options = gap.get("options")
            invalid = (
                missing
                or not isinstance(gap.get("evidence"), list)
                or not gap.get("evidence")
                or not isinstance(gap.get("impact"), list)
                or not gap.get("impact")
                or not isinstance(recommendation, dict)
                or not {"resolution", "reason", "confidence"}.issubset(
                    recommendation or {}
                )
                or not isinstance(options, list)
                or not options
            )
            if invalid:
                gap_id = gap.get("id", f"index-{index}")
                return ErrorResponse(
                    "GAP_ANALYSIS_INCOMPLETE",
                    f"gap {gap_id!r} 缺少可审计的证据、影响、推荐或选项",
                    self._state.to_dict(),
                )
            if gap.get("grade") == "architectural" and any(
                isinstance(option, dict)
                and str(option.get("resolution", "")).lower() == "defer"
                and option.get("enabled", True)
                for option in options
            ):
                return ErrorResponse(
                    "GAP_ANALYSIS_BLOCKING_RULE_INVALID",
                    f"architectural gap {gap.get('id')!r} 不得启用纯 Defer",
                    self._state.to_dict(),
                )
        expected_blocking = any(
            isinstance(gap, dict) and gap.get("grade") == "architectural"
            for gap in gaps
        )
        if bool(result.get("has_blocking")) != expected_blocking:
            return ErrorResponse(
                "GAP_ANALYSIS_BLOCKING_FLAG_MISMATCH",
                "has_blocking 必须由 architectural gap 集合确定",
                self._state.to_dict(),
            )
        return None

    def _validate_gap_review_decisions(self, result: dict) -> ErrorResponse | None:
        """新 Action 接受当前单项决定；旧 active Action 兼容完整 decisions。"""
        if self._state.current_stage != "gap_review":
            return None
        report = json.loads(self._state.gap_report_json or '{"gaps": []}')
        unresolved = [
            str(gap.get("id"))
            for gap in report.get("gaps", [])
            if gap.get("id") is not None
            and gap.get("resolution") not in {"fill", "defer"}
        ]
        decision = result.get("decision")
        if isinstance(decision, dict):
            current_id = unresolved[0] if unresolved else None
            if decision.get("gap_id") != current_id:
                return ErrorResponse(
                    error_code="GAP_REVIEW_DECISION_OUT_OF_ORDER",
                    message=(
                        f"当前只能处理 gap {current_id!r}，不得跳项或重复提交"
                    ),
                    current_state=self._state.to_dict(),
                )
            if decision.get("decision_source") != "user":
                return ErrorResponse(
                    error_code="GAP_REVIEW_USER_DECISION_REQUIRED",
                    message="Gap Review 决策必须来自用户，禁止宿主代选",
                    current_state=self._state.to_dict(),
                )
            return None
        expected = set(unresolved)
        decisions = result.get("decisions", [])
        actual = [str(item.get("gap_id")) for item in decisions if isinstance(item, dict)]
        actual_set = set(actual)
        if len(actual) != len(actual_set) or not actual_set.issubset(expected):
            return ErrorResponse(
                error_code="GAP_REVIEW_DECISIONS_INVALID_SET",
                message="decisions 含重复或未知 gap_id，必须严格对应当前 action.gaps",
                current_state=self._state.to_dict(),
            )
        if actual_set != expected:
            missing = sorted(expected - actual_set)
            return ErrorResponse(
                error_code="GAP_REVIEW_DECISIONS_INCOMPLETE",
                message=f"decisions 未完整覆盖当前 gap: {', '.join(missing)}",
                current_state=self._state.to_dict(),
            )
        return None

    def _scan_inbound_for_pii(self, result: dict) -> dict | ErrorResponse:
        """T109d L3: inbound result JSON PII scan/redact/block."""
        if not self._pii_enabled or not self._pii_redactor:
            return result
        inbound = self._runtime_config.pii_inbound
        if inbound == "redact":
            redacted = self._pii_redactor.redact_dict(result)
            # redact_dict(dict) → dict (list 分支不可能，因 result 类型为 dict)
            if isinstance(redacted, dict):
                return redacted
            return result
        findings = self._pii_redactor.scan_dict(result)
        if findings:
            # P2-35: summarize by category for actionable diagnosis
            by_cat: dict[str, int] = {}
            for f in findings:
                cat = getattr(f, "category", "unknown")
                by_cat[cat] = by_cat.get(cat, 0) + 1
            cat_summary = ", ".join(f"{c}:{n}" for c, n in sorted(by_cat.items())[:3])
            _logger.warning(
                "PII detected in inbound result: %d matches (%s)", len(findings), cat_summary)
            if inbound == "block":
                s = self._state
                return ErrorResponse(
                    error_code="PII_BLOCKED_INBOUND",
                    message=(
                        f"PII detected in inbound result: "
                        f"{len(findings)} matches ({cat_summary}). "
                        f"审查 result JSON 中的 PII 字段后重试"),
                    current_state=s.to_dict() if s else None)
        return result

    def _apply_result_to_state(self, result: dict) -> None:
        """兼容入口：委托独立 StageResultProjector。"""
        StageResultProjector().apply(
            self._state,
            result,
            audit_key=self._audit_revision_key,
            audit_fingerprint=self._audit_revision_fingerprint,
        )

    # ── 辅助 ──

    def _advance_stage(self, next_stage: str | None) -> None:
        if next_stage is None:
            return
        previous_stage = self._state.current_stage
        self._last_completed_stage = previous_stage  # E2: 在推进前记录
        self._append_round_history()
        clear_stage_fields(self._state, self._state.current_stage)
        self._state.current_stage = next_stage
        self._state.expected_stage = next_stage
        self._state.round += 1
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
        self._save_checkpoint()

    def _append_round_history(self) -> None:
        """Append current tick as RoundHistory for convergence judge (P0-1 fix).

        Previously _round_history was initialized and saved to checkpoint but
        never populated — all 4 convergence levels (hard_limit, quality_gates,
        stagnation, semantic) were silently bypassed.  Each stage transition
        records a RoundHistory so the judge has real data.

        T105b: lines_added/lines_removed populated from git diff --numstat so
        stagnation detection can sense "small file big change" scenarios.
        """

        gate_results = getattr(self._state, "gate_results", {}) or {}
        files_changed = getattr(self._state, "files_changed", []) or []
        lines_added, lines_removed = self._compute_diff_stats(files_changed)
        self._round_history.append(RoundHistory(
            round_id=self._state.round,
            stage=self._state.current_stage,
            files_changed=len(files_changed),
            lines_added=lines_added,
            lines_removed=lines_removed,
            gate_results=gate_results,
        ))

    def _compute_diff_stats(self, files_changed: list, *, git_runner: Callable | None = None) -> tuple[int, int]:
        """Compute lines_added/lines_removed from git diff --numstat (T105b).

        Args:
            files_changed: list of changed file paths.
            git_runner: optional callable for git subprocess (injectable for testing).
                        Signature: (list[str]) -> subprocess.CompletedProcess.
                        Defaults to subprocess.run.
        """
        if not files_changed:
            return 0, 0
        try:
            runner = git_runner if git_runner is not None else subprocess.run
            result = runner(
                ["git", "-C", str(self.project_root), "diff", "--numstat"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return 0, 0
            added = 0
            removed = 0
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    # P2-32: binary files output "- \t - \t filename"
                    if parts[0] == "-" and parts[1] == "-":
                        continue
                    try:
                        if parts[0] != "-":
                            added += int(parts[0])
                        if parts[1] != "-":
                            removed += int(parts[1])
                    except ValueError:
                        _logger.debug("git diff numstat parse failed: %s", line, exc_info=True)
                        pass
            return added, removed
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0, 0

    def _run_developer_gates(self) -> None:
        """兼容入口：委托独立 DeveloperGateService。"""
        self._t_gate_ms += DeveloperGateService(self._tick_gate_runner).run(
            state=self._state,
            batch_state=self._batch_state,
            developer_snapshot=self._dev_snapshot,
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

    def _save_checkpoint(self) -> str | None:
        # v5.7 新线程由 EventStore 的单 Tick 事务持久化；旧 checkpoint 仅作兼容读取。
        if self._event_store is not None:
            self._populate_serialized_state()
            return None
        if self._checkpoint_mgr is None:
            return None
        self._populate_serialized_state()
        return self._checkpoint_mgr.save(
            self._state, self._state.round, step=self._state.tick,
            history=self._round_history)

    def _commit_event_action(self, action: dict[str, Any]) -> None:
        """将当前状态与出站 Action 作为一个 EventStore Tick 原子提交。"""

        if self._event_store is None or self._state is None:
            return
        sequence = self._event_store.next_sequence(self._state.thread_id)
        previous = self._event_store.load_projection(self._state.thread_id)
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
                round_history=tuple(asdict(item) for item in self._round_history),
            )
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
            restored = self._event_store.load_projection(self._state.thread_id)
            if restored is not None:
                self._state = restored
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
                self._progress_tree.to_dict(), ensure_ascii=False)
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
            self._progress_tree.to_dict(), ensure_ascii=False)
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {self._progress_tree.display()}",
              file=sys.stderr, flush=True)
__all__ = [
    "ORCH_BUDGET_MS",
    "TickOrchestrator",
]
