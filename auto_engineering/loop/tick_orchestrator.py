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

import json
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from auto_engineering.config.runtime_config import RuntimeConfig, get_default_config
from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import DesignDoc, Supplement
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.state import EngineState
from auto_engineering.engine.verification_layers import (
    VerificationLayers,
    determine_verification_layers,
)
from auto_engineering.gates.deep_audit import recount_findings
from auto_engineering.loop.actions import ActionDone, ActionError, ErrorResponse, validate_result_format
from auto_engineering.loop.checkpoint.manager import CheckpointManager
from auto_engineering.loop.checkpoint.records import CheckpointNotFoundError
from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
from auto_engineering.loop.convergence import ConvergenceConfig, ConvergenceJudge, RoundHistory
from auto_engineering.loop.debug_tracer import DebugTracer, now_iso
from auto_engineering.loop.action_builder import ActionBuilder
from auto_engineering.loop.tick_gate_runner import TickGateRunner
from auto_engineering.loop.guardrail import GuardrailChain
from auto_engineering.loop.plan import Plan, TaskDAG
from auto_engineering.loop.refine import build_refine_request
from auto_engineering.loop.standalone_driver import STAGE_TO_ROLE
from auto_engineering.loop.stage_router import (
    StageRouter,
    clear_stage_fields,
    update_majors_count,
)
from auto_engineering.loop.task_factory import tasks_from_batch_plan
from auto_engineering.observability.audit_log import AuditLogger
from auto_engineering.metrics.collector import AIOrigin, get_collector
from auto_engineering.metrics.enrichment import compute_metrics_signals
from auto_engineering.metrics.transcript_parser import create_parser
from auto_engineering.gates._tools import LANGUAGE_TOOLS
from auto_engineering.pii.redactor import PIIRedactor
from auto_engineering.prompts.registry import default_registry

# Gate runner type: (gate_names, project_root) → {name: GateVerdict}
GateRunner = Callable[..., dict]

_DEFAULT_P1_THRESHOLD = 6  # 冷启动默认
_MAX_PER_SOURCE = 2
_MAX_GLOBAL = 4
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

# ── System-Initiated Escalation: 项目语言探测 ──

_LANGUAGE_INDICATORS: list[tuple[str, str]] = [
    ("python", "pyproject.toml"),
    ("python", "setup.py"),
    ("python", "setup.cfg"),
    ("typescript", "package.json"),
    ("go", "go.mod"),
    ("rust", "Cargo.toml"),
]


def _detect_project_language(project_root: Path) -> str | None:
    """从常见配置文件探测项目语言。返回 language code 或 None。

    探测优先级按 _LANGUAGE_INDICATORS 顺序。package.json 需要二次确认——
    检查 tsconfig.json 或 devDependencies/dependencies 中是否有 typescript。
    """
    for lang, indicator in _LANGUAGE_INDICATORS:
        indicator_path = project_root / indicator
        if not indicator_path.exists():
            continue
        if lang == "typescript":
            if (project_root / "tsconfig.json").exists():
                return "typescript"
            try:
                pkg = json.loads(indicator_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return "typescript"  # 有 package.json 就假定 JS/TS
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "typescript" in deps:
                return "typescript"
            return "typescript"  # 有 package.json 就算 JS/TS 生态
        return lang
    return None

# _VERIFIER_RECHECK — 已提取到 ActionBuilder (P0-1)

# DS-10 / C.2.6: Python 编排开销预算 (t_orchestration = t_total − t_gate − t_guard_sub).
# 超预算只告警不中断 — 延迟是可观测性指标, 不是正确性门控. P95 判定离线聚合 (Phase 5).
ORCH_BUDGET_MS = 2000

_STAGE_CHECKPOINT_REVIEW_FEEDBACK = (
    "用户选择审查当前产出，请展示当前进度和已完成内容供审查。"
)

# T108a: Subagent spawn requirements per stage — injected into action JSON so the
# Agent sees the spawn instruction in the per-tick signal, not just in dev-loop.md.
# Key insight: normal conversation "spawn Plan agent" works reliably because the
# instruction and context are in the same message. The Tick loop broke this by
# separating "what to do" (action JSON) from "how to do it" (dev-loop.md spec).
# Fix: encode the spawn requirement into every per-tick action JSON.
_SPAWN_CONFIG: dict[str, dict] = {
    "architect": {
        "subagent_type": "Plan",
        "count": 1,
        "parallel": False,
        "model": "Sonnet",
        "instruction": (
            "Spawn a Plan agent with the action's context (requirement + design_doc) "
            "and expected_format. It MUST produce structured batch_plan JSON — not "
            "just bullet points. Each batch ≤5 files, tasks independently testable."
        ),
    },
    "critic": {
        "subagent_type": "code-reviewer",
        "count": 1,
        "parallel": False,
        "model": "Sonnet",
        "instruction": (
            "Spawn a code-reviewer agent. Feed it files_changed + test_results + "
            "gate_results from the action's context. It MUST produce structured "
            "findings (file:line + severity + issue + suggested_fix) and verdict "
            "(APPROVE if 0 P0 + ≤2 P1, otherwise MAJOR)."
        ),
    },
    "component_verifier": {
        "subagent_type": "general-purpose",
        "count": 1,
        "parallel": False,
        "model": "Haiku",
        "instruction": (
            "Spawn a general-purpose agent (Haiku model). Feed it the component "
            "design spec + implementation files from the action's context. Map "
            "each design item to IMPLEMENTED/MISSING/DIVERGED with file+line evidence."
        ),
    },
    "plate_deep_audit": {
        "subagent_type": "code-reviewer",
        "count": 3,
        "parallel": True,
        "model": "Sonnet",
        "instruction": (
            "SPAWN 3 CODE-REVIEWER SUBAGENTS IN PARALLEL. Each audits different "
            "dimensions of the plate's codebase (cross-component contracts, code "
            "quality, design compliance). Merge all findings and recount p0/p1/p2 "
            "counts. The expected_format requires findings array, p0/p1/p2 counts, "
            "cross_component_issues, and total_audited_files."
        ),
    },
    "system_verifier": {
        "subagent_type": "general-purpose",
        "count": 1,
        "parallel": False,
        "model": "Haiku",
        "instruction": (
            "Spawn a general-purpose agent (Haiku model). Feed it the full design "
            "spec + full codebase file list from the action's context. Produce a "
            "full_coverage_map for ALL design items (total_design_items, covered_count, "
            "missing_count, diverged_count)."
        ),
    },
    "system_deep_audit": {
        "subagent_type": "code-reviewer",
        "count": 3,
        "parallel": True,
        "model": "Sonnet",
        "instruction": (
            "SPAWN 3 CODE-REVIEWER SUBAGENTS IN PARALLEL. Each audits different "
            "dimensions of the FULL codebase: (1) architecture + engineering, "
            "(2) code quality + virtualization, (3) collaboration + design coverage. "
            "Merge all findings via recount_findings() and produce p0/p1/p2 counts, "
            "total_audited_files, design_docs_stale flag, and design_doc_suggestions."
        ),
    },
}

_logger = logging.getLogger("ae.loop.tick_orchestrator")


# ── Protocol types (P1-10: replace Any with typed contracts) ──


@runtime_checkable
class TickContextOffloader(Protocol):
    """Context offloading — 将 stage context 写入文件.

    Implementation: auto_engineering.context.offloading.ContextOffloader.
    """

    def offload(self, stage: str, context: dict) -> Path: ...


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
        context_offloader: TickContextOffloader | None = None,
        tracer: Any | None = None,
        audit_logger: AuditLogger | None = None,
        runtime_config: RuntimeConfig | None = None,
        pii_redactor: PIIRedactor | None = None,
        transcript_parser: Any | None = None,
        escalate: bool = False,
        debug: bool = False,
        debug_dir: str | None = None,
    ) -> None:
        self.project_root = project_root or Path.cwd()
        self._audit_logger = audit_logger
        self._escalate = escalate
        self._guardrail = guardrail
        self._checkpoint_store = checkpoint_store
        self._context_offloader = context_offloader
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
        self._transcript_parser = transcript_parser if transcript_parser is not None else create_parser(self.project_root)

        self._state: EngineState | None = None
        self._router: StageRouter | None = None
        self._judge: ConvergenceJudge | None = None
        self._plan: Plan | None = None
        self._checkpoint_mgr: CheckpointManager | None = None
        self._init_manifest: dict | None = None
        self._design_doc: DesignDoc | None = None
        self._batch_state: BatchState | None = None
        self._task_dag: TaskDAG | None = None  # P0-3: 拓扑排序 DAG
        self._progress_tree: ProgressTree | None = None
        self._verification_layers: VerificationLayers | None = None
        self._round_history: list = []  # T1: 在 TickOrchestrator, 非 EngineState 字段
        self._last_batch_id: str | None = None  # 跨 stage 传 batch_id (组件完成后无 current)
        self._dev_snapshot: dict[str, Any] | None = None  # developer 产出快照 (供 critic 上下文)
        # DS-10 延迟打点累加器 (每 tick 起始清零, tick() 内累加子进程墙钟)
        self._t_gate_ms: float = 0.0
        self._t_guard_sub_ms: float = 0.0
        # DebugTracer (可选, --debug 或 AE_DEBUG=1 时激活)
        self._debug_tracer: DebugTracer | None = None
        self._last_guardrail: dict | None = None
        # T64: Stage Checkpoint Gate (DecisionGate 形态 3)
        self._pause_at_stages: set[str] = set()
        self._passed_checkpoints: set[str] = set()
        self._action_builder = ActionBuilder(
            self.project_root,
            pii_enabled=self._pii_enabled,
            pii_redactor=self._pii_redactor,
            pii_outbound=self._runtime_config.pii_outbound,
        )
        # P0-1: TickGateRunner delegate — gate selection, execution, metrics, tracing
        self._tick_gate_runner = TickGateRunner(
            self.project_root,
            init_manifest=None,
            gate_runner=gate_runner,
            tracer=tracer,
            audit_logger=audit_logger,
        )

    # ── T113 L2: Injectable access with visible None ──

    def _require(self, attr_name: str, reason: str = "") -> Any:
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

    def init(
        self,
        requirement: str,
        design_doc_path: str | None = None,
        max_rounds: int = 5,
    ) -> dict:
        """初始化 loop。有设计文档时解析层次并进入 gap_scan; 否则直接 architect.

        System-Initiated Escalation: 当 init-manifest.json 缺失且项目非 Python 时,
        不静默降级到 Python 默认工具, 而是输出 action: "gate" 提示用户决策工具链配置.
        """
        manifest_path = self.project_root / ".ae-state" / "init-manifest.json"
        if manifest_path.exists():
            self._init_manifest = json.loads(manifest_path.read_text())

        if design_doc_path:
            self._design_doc = DesignDoc.parse(design_doc_path)

        # T109b: L1 — requirement PII 扫描 (不阻断, 仅 WARN)
        if self._pii_enabled and self._pii_redactor:
            findings = self._pii_redactor.scan_dict({"requirement": requirement})
            if findings:
                _logger.warning("PII detected in requirement: %d matches", len(findings))

        self._state = EngineState(
            requirement=requirement,
            thread_id=str(uuid4()),
            prompt_registry_hash=default_registry().registry_hash(),  # B12.5 版本锁
        )
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
        self._tick_gate_runner.reload(self._init_manifest)
        self._checkpoint_mgr = CheckpointManager(self._checkpoint_store)

        if self._guardrail is None:
            self._guardrail = GuardrailChain.default()

        # System-Initiated Escalation: manifest 缺失 + 明确非 Python → 人工决策.
        # detected is None (空目录/未知项目) 静默回退 Python 默认 (维持现有行为).
        if self._init_manifest is None:
            detected = _detect_project_language(self.project_root)
            if detected is not None and detected != "python":
                self._state.current_stage = "init"
                self._state.expected_stage = "init"
                self._state.tick = 0
                self._save_checkpoint()
                return self.build_action(pre_gate=self._build_init_manifest_gate(detected))

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
            return self.build_action(pre_gate=self._build_agent_escalation_gate(None))

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
        tracer: Any | None = None,
        audit_logger: AuditLogger | None = None,
        runtime_config: RuntimeConfig | None = None,
        max_rounds: int = 5,
        debug: bool = False,
        debug_dir: str | None = None,
    ) -> TickOrchestrator:
        """跨进程恢复 (§A.1: 每 tick 独立进程, 从 SQLite 重建全部 in-memory 状态).

        新进程 self._state=None → tick() 立即崩. restore() 从 checkpoint 重建
        _state/_design_doc/_batch_state/_progress_tree/_plan, 游标不归零。

        无 checkpoint_id → load_latest; 无 checkpoint → raise CheckpointNotFoundError.
        max_rounds: EngineState 未持久化该字段 → restore 用默认 5 (与 init 一致);
        精确恢复需扩 schema (本步不扩)。
        """
        self = cls(
            project_root,
            gate_runner=gate_runner,
            guardrail=guardrail,
            checkpoint_store=checkpoint_store,
            context_offloader=context_offloader,
            tracer=tracer,
            audit_logger=audit_logger,
            runtime_config=runtime_config,
            debug=debug,
            debug_dir=debug_dir,
        )

        ck = (checkpoint_store.load(checkpoint_id) if checkpoint_id
              else checkpoint_store.load_latest())
        if ck is None:
            raise CheckpointNotFoundError(
                f"无 checkpoint 可恢复 (project_root={project_root})")

        state = ck.state
        if isinstance(state, dict):  # 防御: deserialize 未命中 EngineState 分派
            state = EngineState.from_dict(state)
        self._state = state
        self._round_history = list(ck.history or [])

        # 协作组件 (无状态 / 从 store 重建)
        self._router = StageRouter()
        self._judge = ConvergenceJudge(ConvergenceConfig(max_iterations=max_rounds))
        self._tick_gate_runner.reload(self._init_manifest)
        self._checkpoint_mgr = CheckpointManager(checkpoint_store)
        if self._guardrail is None:
            self._guardrail = GuardrailChain.default()

        manifest_path = project_root / ".ae-state" / "init-manifest.json"
        if manifest_path.exists():
            self._init_manifest = json.loads(manifest_path.read_text())

        # design_doc: design-doc 模式每 tick 重 parse (确定性无漂移)
        if state.design_doc_path:
            self._design_doc = DesignDoc.parse(state.design_doc_path)

        # batch_state: 自包含 (内嵌 batch_plan seed), plates 由 design_doc/seed 重建
        if state.batch_state_json:
            self._batch_state = BatchState.from_json(
                state.batch_state_json, self._design_doc)

        # progress_tree
        if state.progress_tree_json:
            self._progress_tree = ProgressTree.from_dict(
                json.loads(state.progress_tree_json))

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

        # B12.5 版本锁: 运行中 prompt 文件被改 → hash 不符 → 警告 (非致命, §A.1 stderr)
        stored_hash = state.prompt_registry_hash
        if stored_hash:
            current_hash = default_registry().registry_hash()
            if stored_hash != current_hash:
                print(
                    f"[warn] prompt registry hash 不符 "
                    f"(checkpoint={stored_hash[:12]} 当前={current_hash[:12]}): "
                    f"loop 运行中 prompt 已变更, 同一 loop 不应换 prompt (B12.5)。",
                    file=sys.stderr,
                )

        return self

    def tick(self, result_file: Path) -> dict:
        """File-bridge entry point (Driver A). Reads result JSON, delegates to tick_dict()."""
        try:
            return self.tick_dict(json.loads(result_file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            return ErrorResponse("RESULT_PARSE_ERROR", f"无法解析 result 文件: {e}",
                                self._state.to_dict() if self._state else None).to_dict()

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

        # T75: OTLP tracing span per tick
        tick_span = None
        tracer = self._require("_tracer", "OTLP tracing disabled")
        if tracer is not None:
            tick_span = tracer.start_span(
                f"tick.{stage_in}", attributes={"tick": tick_no, "stage": stage_in})

        action = self._tick_body_dict(result)
        duration_ms = int((time.perf_counter() - t_start) * 1000)

        if tick_span is not None:
            tick_span.set_attribute("duration_ms", duration_ms)
            tick_span.set_attribute("action", action.get("action", ""))
            tick_span.end()
        self._record_tick_latency(t_start, tick_no)

        # T69a: Record tick completion event for metrics collector
        mc = get_collector()
        if mc is not None:
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
                tick_num=tick_no,
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

    def _tick_body_dict(self, result: dict) -> dict:
        """tick 核心逻辑 (dict 版本): Gate resolution → 验证 → Guardrail → Gate → 路由 → action."""
        # T95: Agent mid-loop escalation — Agent 在 result 中置 escalate=true
        if result.get("escalate") is True:
            return self.build_action(pre_gate=self._build_agent_escalation_gate({
                "question": result.get("escalation_question", ""),
                "options": result.get("escalation_options"),
                "default": result.get("escalation_default"),
            }))

        # T64: handle gate_resolution before validation (no stage field)
        gate_resolution = result.get("gate_resolution")
        if gate_resolution and isinstance(gate_resolution, dict):
            return self._tick_process_result(result)

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

            # System-Initiated Escalation: init_manifest_missing
            if gate_id == "init_manifest_missing":
                if resolution == "终止 loop":
                    return {
                        "action": "done",
                        "verdict": "TERMINATED",
                        "message": "用户终止 loop（拒绝配置 init-manifest）",
                        "stage": self._state.current_stage,
                        "tick": self._state.tick + 1,
                        "thread_id": self._state.thread_id,
                    }
                return self._resolve_init_manifest_escalation(gate_resolution)

            # T95 Agent-Initiated Escalation
            if gate_id == "agent_escalation":
                return self._resolve_agent_escalation(gate_resolution)

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
                    message=f"未知的 gate resolution: {resolution!r}，有效值: 继续 / 审查当前产出 / 终止 loop",
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
        self._state.batch_state = self._batch_state  # type: ignore[attr-defined]
        self._state._plan = self._plan  # type: ignore[attr-defined]

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
                if self._state.current_stage != "developer":
                    self._run_developer_gates()
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

        if self._state.current_stage == "developer":
            self._run_developer_gates()

        return self._after_tick(result)

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

        # T108c: spawn stages with empty findings → WARN (timing guardrail T112
        # provides the block layer; this is an early detection signal)
        stage = self._state.current_stage
        if stage in _SPAWN_CONFIG:
            findings = result.get("findings")
            if findings is None or (isinstance(findings, list) and len(findings) == 0):
                p0 = result.get("p0_count", 0)
                p1 = result.get("p1_count", 0)
                if not isinstance(p0, int) or not isinstance(p1, int) or (p0 == 0 and p1 == 0):
                    _logger.warning(
                        "[spawn-empty] stage=%s has spawn requirement but "
                        "findings=%s (empty), p0=%s, p1=%s — subagent may not "
                        "have been spawned. action.spawn=%s",
                        stage,
                        type(findings).__name__ if findings is not None else "None",
                        p0, p1,
                        _SPAWN_CONFIG.get(stage, {}).get("subagent_type", "?"))

        return result

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
        handlers: dict[str, Callable[[], dict]] = {
            "gap_scan": lambda: self._after_gap_scan(result),
            "gap_review": lambda: self._after_gap_review(result),
            "research": lambda: self._after_research(result),
            "architect": lambda: self._after_architect(),
            "developer": lambda: self._after_developer(),
            "critic": lambda: self._after_critic(result),
            "component_verifier": lambda: self._after_component_verifier(result),
            "plate_deep_audit": lambda: self._after_plate_deep_audit(result),
            "system_verifier": lambda: self._after_system_verifier(result),
            "system_deep_audit": lambda: self._after_system_deep_audit(result),
        }
        handler = handlers.get(stage)
        if handler:
            return handler()
        return ActionError(error_code="UNKNOWN_STAGE",
                           message=f"Unknown stage: {stage}").to_dict()

    # ── _after_architect ──

    def _after_architect(self) -> dict:
        batches = BatchState._flatten_batch_plan(self._state.batch_plan)
        if not batches:
            return ActionError(error_code="EMPTY_BATCH_PLAN",
                               message="architect 输出 batch_plan 为空").to_dict()

        if self._batch_state is None:
            self._batch_state = (
                BatchState.from_design_doc(self._design_doc, batches)
                if self._design_doc
                else BatchState.from_batch_plan(batches)
            )
        else:
            # plan_refine: 重建 BatchState (游标可能越界)
            self._batch_state = (
                BatchState.from_design_doc(self._design_doc, batches)
                if self._design_doc
                else BatchState.from_batch_plan(batches)
            )

        self._plan = tasks_from_batch_plan(batches, self._state.requirement)

        # P0-3: TaskDAG 拓扑排序 — 检测 depends_on 并构建 DAG 供 batch 调度
        tasks_with_deps = [t for t in self._plan.tasks if t.depends_on]
        if tasks_with_deps:
            dag = TaskDAG()
            for task in self._plan.tasks:
                dag.add_task(task)
            self._task_dag = dag
            _logger.info(
                "TaskDAG built: %d tasks, %d with depends_on",
                len(self._plan.tasks), len(tasks_with_deps),
            )
        else:
            self._task_dag = None

        if self._verification_layers is None:
            self._verification_layers = determine_verification_layers(
                self._design_doc, batches)

        if self._progress_tree is None:
            if self._design_doc:
                self._progress_tree = ProgressTree.from_design_doc(self._design_doc)
            else:
                self._progress_tree = ProgressTree.from_batch_plan(
                    batches, self._state.requirement)
        elif self._state.plan_refine_count > 0 and self._progress_tree:
            self._verification_layers = determine_verification_layers(
                self._design_doc, batches)
            if self._design_doc:
                self._progress_tree.sync_from_design_doc(self._design_doc)
            else:
                self._progress_tree.sync_from_batch_plan(batches)

        self._advance_stage("developer")
        self._offload_stage("architect")
        return self.build_action()

    # ── _after_developer ──

    def _after_developer(self) -> dict:
        self._collect_token_usage()  # T110b: 采集 Agent 本 tick 的 token 消耗

        comp = self._batch_state.current_component()
        # 缓存刚完成的 batch_id (advance_batch 后组件 complete → current_batch_id 不可用)
        prev_batch = self._batch_state.current_batch()
        self._last_batch_id = prev_batch.get("batch_id") if prev_batch else None

        self._batch_state.advance_batch()

        if self._progress_tree:
            node = self._progress_tree.find_by_design_section(comp.design_section)
            if node:
                prev_batches = self._batch_state.batches_for(comp)
                done_idx = self._batch_state.current_batch_idx - 1
                if 0 <= done_idx < len(prev_batches):
                    node.done_tasks += len(prev_batches[done_idx].get("tasks", []))
                node.current_task = None
                self._progress_tree.recalculate_parents(node.id)

        if self._batch_state.has_more_batches_for(comp):
            if self._progress_tree:
                node = self._progress_tree.find_by_design_section(comp.design_section)
                if node:
                    next_batch = self._batch_state.current_batch()
                    if next_batch.get("tasks"):
                        node.current_task = next_batch["tasks"][0]["description"]
            self._save_checkpoint()
            self._offload_stage("developer")
            # P1-5: T94 PrePlannedGate — 检查下一 batch 是否声明了 gate
            pending_gate = self._batch_state._get_pending_gate()
            if pending_gate:
                return self.build_action(pre_gate=pending_gate)
            return self.build_action()

        self._snapshot_developer_output()
        self._advance_stage("critic")
        self._offload_stage("developer")
        return self.build_action()

    def _snapshot_developer_output(self) -> None:
        """保存 developer 产出快照 (advance_stage 会 clear_stage_fields)."""
        self._dev_snapshot = {
            "files_changed": self._state.files_changed,
            "commit_hash": self._state.commit_hash,
            "test_results": self._state.test_results,
        }

    def _offload_stage(self, stage: str) -> None:
        """Persist stage context summary via ContextOffloader (T73).

        Note: messages are NOT available at the TickOrchestrator level —
        the orchestrator only sees action/result JSON, not Agent-level
        conversation history. load_full_context() will return [] by design.
        Offloading is summary-only; full context backtracking would require
        the Agent to include message history in its result file.

        (P1-2 fix: documented limitation instead of pretending full_context works.)
        """
        offloader = self._require("_context_offloader",
                                  "stage context will not be persisted")
        if offloader is None:
            return
        s = self._state
        summary = f"{stage} stage completed at tick {s.tick}/{s.round}"
        key_decisions: list[str] = []
        files_changed: list[str] = list(s.files_changed) if s.files_changed else []
        if stage == "architect":
            summary = f"Architect plan: {s.plan[:200] if s.plan else 'N/A'}"
            if s.batch_plan:
                key_decisions = [
                    f"batch_count={len(s.batch_plan)}",
                    f"files={', '.join(s.file_list or [])}",
                ]
        elif stage == "developer":
            tr = s.test_results or {}
            summary = f"Developer: {tr.get('passed', 0)}/{tr.get('total', 0)} tests passed"
        elif stage == "critic":
            summary = f"Critic verdict: {s.critic_verdict or 'N/A'}"
        offloader.offload(
            stage=stage,
            messages=[],
            summary=summary,
            key_decisions=key_decisions,
            files_changed=files_changed,
            gate_results=dict(s.gate_results or {}),
        )

    # ── _after_critic ──

    def _after_critic(self, result: dict) -> dict:
        self._collect_token_usage()  # T110b: 采集 Agent 本 tick 的 token 消耗

        verdict = result.get("verdict", "")
        update_majors_count(self._state, verdict)
        self._offload_stage("critic")

        if self._progress_tree:
            comp = self._batch_state.current_component()
            node = self._progress_tree.find_by_design_section(comp.design_section)
            if node:
                node.gate_run_count += 1
                if verdict == "APPROVE":
                    node.gate_pass_count += 1

        if verdict == "MAJOR":
            decision = self._router.next(
                "critic", "MAJOR",
                self._state.majors_in_a_row, self._state.total_majors)
            if decision.should_stop:
                return ActionDone(verdict="HARD_LIMIT",
                                  reason=decision.stop_reason).to_dict()
            # 回退 batch_idx (重做刚被 MAJOR 的 batch)
            if self._batch_state.current_batch_idx > 0:
                self._batch_state.current_batch_idx -= 1
            self._advance_stage("developer")
            return self.build_action(
                feedback=json.dumps(result.get("findings", [])))

        if verdict == "APPROVE":
            comp = self._batch_state.current_component()
            if self._batch_state.has_more_batches_for(comp):
                self._advance_stage("developer")
                return self.build_action()
            self._advance_stage("component_verifier")
            return self.build_action()

        return ActionError(error_code="INVALID_VERDICT",
                           message=f"非法 verdict: {verdict!r}").to_dict()

    # ── _after_component_verifier ──

    def _after_component_verifier(self, result: dict) -> dict:
        missing = result.get("missing_count", 0)
        diverged = result.get("diverged_count", 0)

        if self._progress_tree:
            comp = self._batch_state.current_component()
            node = self._progress_tree.find_by_design_section(comp.design_section)
            if node:
                node.verifier_status = "failed" if (missing > 0 or diverged > 0) else "pass"
                node.verifier_missing = missing
                node.verifier_diverged = diverged
                self._progress_tree.recalculate_parents(node.id)

        if missing > 0 or diverged > 0:
            self._state.audit_findings = result.get("coverage_map", [])
            return self._handle_plan_refine("component_verifier")

        self._batch_state.advance_component()
        if self._batch_state.has_more_components_in_plate():
            self._advance_stage("developer")
            return self.build_action()

        if self._verification_layers == VerificationLayers.LEAF:
            self._advance_stage("system_deep_audit")
        else:
            self._advance_stage("plate_deep_audit")
        return self.build_action()

    # ── _after_plate_deep_audit ──

    def _after_plate_deep_audit(self, result: dict) -> dict:
        # B6.7a: Agent 报的 count 仅参考 — Python 去重重算为路由权威计数
        deduped, p0, p1, p2 = recount_findings(result.get("findings", []))
        p1_threshold = self._get_p1_threshold()

        if self._progress_tree:
            plate = self._batch_state.current_plate()
            for comp in plate.components:
                node = self._progress_tree.find_by_design_section(comp.design_section)
                if node:
                    node.deep_audit_status = "failed" if (p0 > 0 or p1 > p1_threshold) else "pass"
                    node.deep_audit_p0 = p0
                    node.deep_audit_p1 = p1
                    node.deep_audit_p2 = p2
            self._progress_tree.recalculate_parents(
                f"sys/{self._batch_state.current_plate_idx}")

        if p0 > 0 or p1 > p1_threshold:
            self._state.audit_findings = deduped
            return self._handle_plan_refine("plate_deep_audit")

        self._batch_state.advance_plate()
        if self._batch_state.has_more_plates():
            self._advance_stage("developer")
            return self.build_action()

        if self._verification_layers == VerificationLayers.PLATE:
            self._advance_stage("system_deep_audit")
        else:
            self._advance_stage("system_verifier")
        action = self.build_action()
        self._display_progress()
        return action

    # ── _after_system_verifier ──

    def _after_system_verifier(self, result: dict) -> dict:
        self._state.coverage_map = result.get("full_coverage_map", [])
        missing = result.get("missing_count", 0)
        diverged = result.get("diverged_count", 0)

        if missing > 0 or diverged > 0:
            self._state.audit_findings = self._state.coverage_map
            return self._handle_plan_refine("system_verifier")

        self._advance_stage("system_deep_audit")
        action = self.build_action()
        self._display_progress()
        return action

    # ── _after_system_deep_audit ──

    def _after_system_deep_audit(self, result: dict) -> dict:
        # B6.7a: Agent 报的 count 仅参考 — Python 去重重算为路由权威计数
        deduped, p0, p1, p2 = recount_findings(result.get("findings", []))
        p1_threshold = self._get_p1_threshold()

        if result.get("design_docs_stale"):
            self._state.critic_feedback = (
                (self._state.critic_feedback or "") + "\n"
                + "[Design Doc Sync] " + result.get("design_doc_suggestions", ""))

        if p0 > 0 or p1 > p1_threshold:
            self._state.audit_findings = deduped
            return self._handle_plan_refine("system_deep_audit")

        self._write_audit_history(p0, p1, p2, False)
        self._display_progress()

        # 审计无 P0/P1 但设计覆盖有缺口 (MISSING/DIVERGED) → 回 architect 做
        # 补充设计 + 计划表调整 (对齐 component/system_verifier 同款回路,
        # 由 _handle_plan_refine 的 REFINE_LIMIT 提供防循环保护).
        missing = result.get("missing_count", 0)
        diverged = result.get("diverged_count", 0)
        if missing > 0 or diverged > 0:
            self._state.audit_findings = deduped
            return self._handle_plan_refine("system_deep_audit")

        return self._convergence_check(
            design_coverage_ok=True, system_deep_audit_ok=True)

    # ── Phase 0 handlers (Pre-flight Gap Analysis, 仅 --design-doc 模式) ──

    def _after_gap_scan(self, result: dict) -> dict:
        """T0.2/T0.3: gap_scan → gap_review (有 gap) / architect (无 gap)."""
        report = json.loads(self._state.gap_report_json or '{"gaps": []}')
        gaps = report.get("gaps", [])
        if self._progress_tree:
            for g in gaps:
                node = self._progress_tree.find_by_design_section(
                    g.get("design_section_ref", ""))
                if node:
                    node.design_status = "fuzzy"
        if gaps:
            self._advance_stage("gap_review")
        else:
            self._advance_stage("architect")
        return self.build_action()

    def _after_gap_review(self, result: dict) -> dict:
        """T0.4/T0.5: gap_review → research (有待研究) / architect (全 Fill/Defer).

        兼顾初审与 T0.7 复审: 复审时 (gap 已在 research_archive) 用户据 findings 做
        补充设计 — Fill→Supplement(消费存档), Defer→留 architect; 已研究 gap 不再入队
        (防重复研究/死循环). G6 NoDeferredBlockingGap (post/gap_review) 已在 tick()
        Guardrail 链拦截 architectural gap 被 Defer/Defer+Research (§B10.5), 到此处
        决策已满足阻塞约束.
        """
        decisions = self._state.pending_gap_decisions
        report = json.loads(self._state.gap_report_json or '{"gaps": []}')
        by_id = {g["id"]: g for g in report.get("gaps", [])}
        pending_research: list[str] = []
        for d in decisions:
            gap_id = d.get("gap_id")
            g = by_id.get(gap_id)
            if not g:
                continue
            resolution = d.get("resolution")
            already_researched = gap_id in self._state.research_archive
            g["resolution"] = resolution
            g["user_note"] = d.get("user_note")
            if resolution == "fill":
                self._inject_supplement(
                    g, d.get("fill_content", ""),
                    source="user", source_tier=None, confidence="high")
                self._state.research_archive.pop(gap_id, None)
            elif resolution in ("research", "defer_research"):
                if already_researched:
                    # 复审后仍想研究/延后 → 已有存档, 归 defer 留 architect (防重复研究)
                    g["resolution"] = "defer"
                else:
                    pending_research.append(g["id"])
            # defer → node fuzzy, architect in-loop 细化
        self._state.gap_report_json = json.dumps(report, ensure_ascii=False)
        self._state.pending_research_ids = pending_research
        # T107: has_blocking → auto-pause before architect via T64 Stage Checkpoint Gate
        if report.get("has_blocking"):
            self._pause_at_stages.add("architect")
        if pending_research:
            self._advance_stage("research")
        else:
            self._advance_stage("architect")
        return self.build_action()

    def _after_research(self, result: dict) -> dict:
        """T0.6/T0.7/T0.8: research → research (队列未空) / gap_review (复审) / architect.

        `research` resolution → 直接落 Supplement (node stable); `defer_research` → findings
        存档待复审. 队列清空后若有 defer_research 已存档未复审 → 回 gap_review 复审 (T0.7,
        用户据研究发现做补充设计); 否则 → architect (T0.8).
        """
        report = json.loads(self._state.gap_report_json or '{"gaps": []}')
        by_id = {g["id"]: g for g in report.get("gaps", [])}
        if not self._state.pending_research_ids:
            self._advance_stage("architect")
            return self.build_action()
        current_id = self._state.pending_research_ids.pop(0)
        g = by_id.get(current_id, {})
        if g.get("resolution") == "research":
            self._inject_supplement(
                g, result.get("recommended_design", ""),
                source="research_agent",
                source_tier=result.get("source_tier"),
                confidence=result.get("confidence", "medium"))
        else:  # defer_research: findings 存档, 待 gap_review 复审 (T0.7)
            self._state.research_archive[current_id] = result
        self._state.gap_report_json = json.dumps(report, ensure_ascii=False)

        if self._state.pending_research_ids:
            self._advance_stage("research")          # T0.6
        elif self._has_pending_rereview(report):
            self._advance_stage("gap_review")        # T0.7 复审 (补充设计)
        else:
            self._advance_stage("architect")         # T0.8
        return self.build_action()

    def _has_pending_rereview(self, report: dict) -> bool:
        """T0.7: 存在 defer_research gap 已研究存档但未复审 (resolution 仍 defer_research)."""
        return any(
            g.get("resolution") == "defer_research"
            and g["id"] in self._state.research_archive
            for g in report.get("gaps", []))

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
            if mc is not None and enrichment:
                action["metrics"] = enrichment
            return action

        self._save_checkpoint()
        action = ActionDone(
            verdict="UNEXPECTED",
            reason="ConvergenceJudge returned CONTINUE after full cycle").to_dict()
        if mc is not None and enrichment:
            action["metrics"] = enrichment
        return action

    # ── System-Initiated Escalation: init-manifest 缺失 gate ──

    @staticmethod
    def _build_init_manifest_gate(detected_language: str | None) -> dict:
        """构建 'init-manifest 缺失' 的 system escalation gate.

        detected_language=None 表示无法探测, 用户需从全部语言中选择.
        """

        if detected_language:
            default_tools = LANGUAGE_TOOLS.get(
                detected_language, LANGUAGE_TOOLS["python"])
            default_label = (
                f"{detected_language}: {default_tools[0]}/{default_tools[1]}/{default_tools[2]}")
            options = [
                default_label,
                "python: ruff/mypy/pytest",
                "自定义（在 resolution_detail 中指定）",
            ]
            question = (
                f"未找到 .ae-state/init-manifest.json。"
                f"检测到项目可能为 {detected_language} 项目。"
                f"请选择 Gate 工具链配置："
            )
        else:
            options = []
            for lang in ["python", "typescript", "go", "rust", "bash"]:
                tools = LANGUAGE_TOOLS[lang]
                options.append(f"{lang}: {tools[0]}/{tools[1]}/{tools[2]}")
            options.append("自定义（在 resolution_detail 中指定）")
            question = (
                "未找到 .ae-state/init-manifest.json, 且无法自动探测项目语言。"
                "请选择 Gate 工具链配置："
            )
            default_label = options[0]

        return {
            "id": "init_manifest_missing",
            "type": "system_escalation",
            "trigger": "missing_init_manifest",
            "question": question,
            "options": options,
            "default": default_label,
            "detected_language": detected_language,
            "timeout_ms": 0,
        }

    def _resolve_init_manifest_escalation(self, gate_resolution: dict) -> dict:
        """处理 init_manifest_missing 的 gate resolution — 创建 manifest 并继续."""
        resolution = gate_resolution.get("resolution", "")
        detail = gate_resolution.get("resolution_detail", {})

        # 解析 resolution: "typescript: eslint/tsc/vitest" 或 "自定义（...）"
        lang: str | None = None
        tools: tuple[str, str, str] | None = None

        if "自定义" in resolution:
            # 用户自定义 → 从 resolution_detail 取
            lang = detail.get("language", "python")
            tools = (
                detail.get("linter", LANGUAGE_TOOLS.get(lang, LANGUAGE_TOOLS["python"])[0]),
                detail.get("type_checker", LANGUAGE_TOOLS.get(lang, LANGUAGE_TOOLS["python"])[1]),
                detail.get("test_runner", LANGUAGE_TOOLS.get(lang, LANGUAGE_TOOLS["python"])[2]),
            )
        else:
            # 解析 "typescript: eslint/tsc/vitest" 格式
            for candidate in LANGUAGE_TOOLS:
                if resolution.startswith(candidate):
                    lang = candidate
                    tools = LANGUAGE_TOOLS[candidate]
                    break
            if lang is None:
                lang = "python"
                tools = LANGUAGE_TOOLS["python"]

        # 创建 .ae-state/ 目录和 init-manifest.json
        ae_state_dir = self.project_root / ".ae-state"
        ae_state_dir.mkdir(parents=True, exist_ok=True)

        manifest = {
            "schema_version": "1.0",
            "project_type": "app-service",
            "language": lang,
            "structure": {
                "source_root": "src/",
                "test_root": "tests/",
            },
            "conventions": {
                "linter": tools[0],
                "type_checker": tools[1],
                "test_runner": tools[2],
            },
            "created_at": datetime.now(UTC).strftime(_ISO_FMT),
        }
        manifest_path = ae_state_dir / "init-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

        _logger.info(
            "System escalation resolved: created init-manifest (language=%s, "
            "linter=%s, type_checker=%s, test_runner=%s)",
            lang, tools[0], tools[1], tools[2],
        )

        # 重新加载 manifest + 重建 gates
        self._init_manifest = manifest
        self._tick_gate_runner.reload(self._init_manifest)

        # 推进到正确的初始 stage
        if self._design_doc:
            self._state.current_stage = "gap_scan"
            self._state.expected_stage = "gap_scan"
        else:
            self._state.current_stage = "architect"
            self._state.expected_stage = "architect"
        self._state.tick = 0
        self._save_checkpoint()
        return self.build_action()

    # ── Agent-Initiated Escalation (T95) ──

    @staticmethod
    def _build_agent_escalation_gate(agent_context: dict | None) -> dict:
        """构建 Agent 发起的 escalation gate.

        agent_context=None → --init --escalate (无 Agent 上下文)
        agent_context 含 question/options → tick 中 Agent 提供具体决策点
        """
        if agent_context and agent_context.get("question"):
            question = agent_context["question"]
            options = agent_context.get("options") or [
                "批准继续", "回退重设计", "终止 loop"]
            default = agent_context.get("default") or options[0]
        else:
            question = "Agent 请求人工决策。请描述需要决策的事项，或选择操作："
            options = ["继续（批准当前方向）", "回退到上一阶段", "终止 loop"]
            default = options[0]

        return {
            "id": "agent_escalation",
            "type": "agent_escalation",
            "trigger": "agent_requested",
            "question": question,
            "options": options,
            "default": default,
            "timeout_ms": 0,
        }

    def _resolve_agent_escalation(self, gate_resolution: dict) -> dict:
        """处理 Agent escalation 的 resolution."""
        resolution = gate_resolution.get("resolution", "")
        detail = gate_resolution.get("resolution_detail", {})

        if resolution == "终止 loop":
            return {
                "action": "done",
                "verdict": "TERMINATED",
                "message": "用户通过 agent_escalation 终止 loop",
                "stage": self._state.current_stage,
                "tick": self._state.tick + 1,
                "thread_id": self._state.thread_id,
            }

        if "回退" in resolution:
            # 回到 architect 重新规划
            self._state.current_stage = "architect"
            self._state.expected_stage = "architect"
            self._state.round += 1
            self._save_checkpoint()
            note = detail.get("note", "")
            return self.build_action(
                feedback=f"Agent escalation: 用户选择回退重设计。{note}".rstrip())

        if "跳过" in resolution:
            if self._batch_state is not None:
                self._batch_state.advance_batch()
            self._save_checkpoint()
            return self.build_action()

        # 默认: "批准继续" / "继续（批准当前方向）"
        self._save_checkpoint()
        note = detail.get("note", "")
        return self.build_action(
            feedback=f"Agent escalation: 用户批准继续。{note}".rstrip() if note else "")

    @property
    def action_builder(self) -> ActionBuilder:
        """Read-only access to the ActionBuilder delegate."""
        return self._action_builder

    def build_action(self, feedback: str | None = None, pre_gate: dict | None = None) -> dict:
        """Build the action dict for the current stage — delegates to ActionBuilder."""
        return self.action_builder.build_action(
            self._state,
            design_doc=self._design_doc,
            init_manifest=self._init_manifest,
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

    # ── T110b: Token 采集 ──

    def _collect_token_usage(self) -> None:
        """T110b: 从 JSONL 转录文件增量采集本 tick 的 token 消耗."""
        if self._transcript_parser is None:
            return
        try:
            usage = self._transcript_parser.collect()
            if usage.get("input_tokens") or usage.get("output_tokens"):
                self._state.tick_token_usage = usage
                _logger.debug(
                    "Token collect: tick=%d input=%d output=%d model=%s",
                    self._state.tick, usage["input_tokens"],
                    usage["output_tokens"], usage.get("model", ""))
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

        # T109d: L3 — inbound result JSON PII scan
        return self._scan_inbound_for_pii(result)

    def _scan_inbound_for_pii(self, result: dict) -> dict | ErrorResponse:
        """T109d L3: inbound result JSON PII scan/redact/block."""
        if not self._pii_enabled or not self._pii_redactor:
            return result
        inbound = self._runtime_config.pii_inbound
        if inbound == "redact":
            return self._pii_redactor.redact_dict(result)
        findings = self._pii_redactor.scan_dict(result)
        if findings:
            _logger.warning(
                "PII detected in inbound result: %d matches", len(findings))
            if inbound == "block":
                s = self._state
                return ErrorResponse(
                    error_code="PII_BLOCKED_INBOUND",
                    message=(
                        f"PII detected in inbound result: "
                        f"{len(findings)} matches"),
                    current_state=s.to_dict() if s else None)
        return result

    def _apply_result_to_state(self, result: dict) -> None:
        """将本轮 agent result 写入 EngineState 对应字段.

        受影响字段 (按 stage):
          gap_scan          → gap_report_json
          gap_review        → pending_gap_decisions
          architect         → plan, batch_plan, file_list, contracts
          developer         → files_changed, commit_hash, test_results, red_evidence
          critic            → critic_verdict, findings, critic_feedback
          component_verifier → coverage_map
          plate_deep_audit  → deep_audit_result
          system_verifier   → system_verdict, design_gaps
          system_deep_audit → system_deep_audit_result

        Returns:
            None (mutates self._state in place). 调用者 (_after_tick) 在调用前
            不知道哪些字段会变更 — 此方法为唯一写入口, 集中管理状态变更。
        """
        stage = result.get("stage", "")
        if stage == "gap_scan":
            self._state.gap_report_json = json.dumps({
                "gaps": result.get("gaps", []),
                "scanned_sections": result.get("scanned_sections", 0),
                "has_blocking": result.get("has_blocking", False),
            }, ensure_ascii=False)
        elif stage == "gap_review":
            self._state.pending_gap_decisions = result.get("decisions", [])
        elif stage == "architect":
            self._state.plan = result.get("plan", "")
            self._state.batch_plan = result.get("batch_plan", [])
            self._state.file_list = result.get("file_list", [])
            self._state.contracts = result.get("contracts", {})
        elif stage == "developer":
            self._state.files_changed = result.get("files_changed", [])
            self._state.commit_hash = result.get("commit_hash", "")
            self._state.test_results = result.get("test_results", {})
            self._state.red_evidence = result.get("red_evidence", [])
        elif stage == "critic":
            verdict = result.get("verdict", "")
            if verdict not in ("", "APPROVE", "MAJOR"):
                return ActionError(error_code="INVALID_VERDICT",
                                   message=f"非法 critic verdict: {verdict!r}").to_dict()
            self._state.critic_verdict = verdict
            self._state.findings = result.get("findings", [])
            self._state.critic_feedback = result.get("critic_feedback", "")
        elif stage == "component_verifier":
            self._state.coverage_map = result.get("coverage_map", [])
        elif stage == "system_verifier":
            self._state.coverage_map = result.get("full_coverage_map", [])
        # research / plate_deep_audit / system_deep_audit: _after_* 中直接读 result

    # ── 辅助 ──

    def _advance_stage(self, next_stage: str | None) -> None:
        if next_stage is None:
            return
        self._append_round_history()
        clear_stage_fields(self._state, self._state.current_stage)
        self._state.current_stage = next_stage
        self._state.expected_stage = next_stage
        self._state.round += 1
        self._state.tick += 1
        self._state.guardrail_retry_counters[next_stage] = 0
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
                if len(parts) >= 2:
                    try:
                        if parts[0] != "-":
                            added += int(parts[0])
                        if parts[1] != "-":
                            removed += int(parts[1])
                    except ValueError:
                        pass
            return added, removed
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0, 0

    def _run_developer_gates(self) -> None:
        """Run all gates via TickGateRunner delegate (P0-1)."""
        results, duration_ms = self._tick_gate_runner.run(
            self._state.files_changed,
            stage=self._state.current_stage,
            tick=self._state.tick)
        self._state.gate_results = results
        self._t_gate_ms += duration_ms

    def _handle_guardrail_result(self, gr) -> dict:
        action = getattr(gr, "action", "block")
        return ActionError(
            error_code=f"GUARDRAIL_{action.upper()}",
            message=getattr(gr, "message", "")).to_dict()

    def _get_p1_threshold(self) -> int:
        """Return P1 threshold for deep audit pass/fail decisions.

        T131 Bayesian wiring: when AE_METRICS=1 and ThresholdLearner has ≥30
        observations, reads the learned max_refine_global posterior mean as the
        P1 threshold (clamped to [2, 8]).  Falls back to _DEFAULT_P1_THRESHOLD
        during cold start or when metrics are disabled.

        ThresholdLearner is @reserved (strategic reserve) — wiring activates
        automatically once the metrics pipeline accumulates sufficient data.
        """
        try:
            if get_default_config().metrics_enabled:
                from auto_engineering.metrics.threshold_learner import ThresholdLearner
                learner = ThresholdLearner(self.project_root / ".ae-state" / "metrics")
                learned = learner.compute_max_iter()
                if learned != 10:  # 10 is the cold-start default — no real data yet
                    return max(2, min(8, learned // 2))
        except Exception:
            _logger.debug("self-learned threshold fallback to default %s", _DEFAULT_P1_THRESHOLD, exc_info=True)
        return _DEFAULT_P1_THRESHOLD

    def _write_audit_history(self, p0: int, p1: int, p2: int,
                             triggered: bool) -> None:
        if not any([p0, p1, p2]):
            return
        _logger.debug(
            "audit history not persisted (not yet implemented): "
            "P0=%d P1=%d P2=%d triggered=%s", p0, p1, p2, triggered)

    def _save_checkpoint(self) -> str | None:
        if self._checkpoint_mgr is None:
            return None
        self._populate_serialized_state()
        return self._checkpoint_mgr.save(
            self._state, self._state.round, step=self._state.tick,
            history=self._round_history)

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
