"""v5.6 TickOrchestrator — 离散调用编排器 (C.5, Tick-Based Discrete Invocation).

设计参考: design/v5.6-Design-Loop.md §C.5 (line 2960-3632).

核心契约:
  - 每 tick Python 输出一个 action dict (stdout JSON) 告诉 Agent 下一步做什么
  - Agent 执行后写 stage-result.json, Python 读回校验
  - Python 绝不自调 LLM — Agent 在 tick 之间做 LLM 工作
  - gate_runner/guardrail/checkpoint_store 可注入 (单元测试 stub, 防挂死)

与保留 Orchestrator 的关系: TickOrchestrator = production 离散路径;
Orchestrator (orchestrator.py) = v5.5 连续 while 调试路径 (ae dev-loop "req").
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.design_doc import DesignDoc, Supplement
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.state import EngineState
from auto_engineering.engine.verification_layers import (
    VerificationLayers,
    determine_verification_layers,
)
from auto_engineering.gates.deep_audit import recount_findings
from auto_engineering.loop.actions import ActionDone, ActionError, ErrorResponse
from auto_engineering.loop.checkpoint.manager import CheckpointManager
from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
from auto_engineering.loop.convergence import ConvergenceConfig, ConvergenceJudge
from auto_engineering.loop.guardrail import GuardrailChain
from auto_engineering.loop.plan import Plan
from auto_engineering.loop.refine import build_refine_request
from auto_engineering.loop.stage_router import (
    StageRouter,
    clear_stage_fields,
    update_majors_count,
)
from auto_engineering.loop.task_factory import tasks_from_batch_plan
from auto_engineering.prompts.registry import default_registry

# Gate runner type: (gate_names, project_root) → {name: GateVerdict}
GateRunner = Callable[..., dict]

_DEFAULT_P1_THRESHOLD = 6  # 冷启动默认
_MAX_PER_SOURCE = 2
_MAX_GLOBAL = 4
_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

# DS-9 (B6.6a): Haiku verifier 负判定 (MISSING/DIVERGED) → Sonnet 窄范围复核指令。
# 仅负判定触发 (trigger=on_negative), scope 收窄到负判定条目 (成本 O(负判定数))。
_VERIFIER_RECHECK = {
    "enabled": True,
    "model": "claude-sonnet-4-6",
    "trigger": "on_negative",
    "scope": "narrow",
}

# DS-10 / C.2.6: Python 编排开销预算 (t_orchestration = t_total − t_gate − t_guard_sub).
# 超预算只告警不中断 — 延迟是可观测性指标, 不是正确性门控. P95 判定离线聚合 (Phase 5).
ORCH_BUDGET_MS = 2000

_logger = logging.getLogger("ae.loop.tick_orchestrator")


def _now_iso() -> str:
    return datetime.now(UTC).strftime(_ISO_FMT)


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
    ) -> None:
        self.project_root = project_root or Path.cwd()
        self._gate_runner = gate_runner
        self._guardrail = guardrail
        self._checkpoint_store = checkpoint_store

        self._state: EngineState | None = None
        self._router: StageRouter | None = None
        self._judge: ConvergenceJudge | None = None
        self._gates: list | None = None
        self._plan: Plan | None = None
        self._checkpoint_mgr: CheckpointManager | None = None
        self._init_manifest: dict | None = None
        self._design_doc: DesignDoc | None = None
        self._batch_state: BatchState | None = None
        self._progress_tree: ProgressTree | None = None
        self._verification_layers: VerificationLayers | None = None
        self._round_history: list = []  # T1: 在 TickOrchestrator, 非 EngineState 字段
        self._last_batch_id: str | None = None  # 跨 stage 传 batch_id (组件完成后无 current)
        self._dev_snapshot: dict[str, Any] | None = None  # developer 产出快照 (供 critic 上下文)
        # DS-10 延迟打点累加器 (每 tick 起始清零, tick() 内累加子进程墙钟)
        self._t_gate_ms: float = 0.0
        self._t_guard_sub_ms: float = 0.0

    # ── 公共入口 ──

    def init(
        self,
        requirement: str,
        design_doc_path: str | None = None,
        max_rounds: int = 5,
    ) -> dict:
        """初始化 loop。有设计文档时解析层次并进入 gap_scan; 否则直接 architect."""
        manifest_path = self.project_root / ".ae-state" / "init-manifest.json"
        if manifest_path.exists():
            self._init_manifest = json.loads(manifest_path.read_text())

        if design_doc_path:
            self._design_doc = DesignDoc.parse(design_doc_path)

        self._state = EngineState(
            requirement=requirement,
            thread_id=str(uuid4()),
            prompt_registry_hash=default_registry().registry_hash(),  # B12.5 版本锁
        )
        if design_doc_path:
            # 持久化路径 — 跨进程 restore 据此重 parse 设计文档 (T9a)
            self._state.design_doc_path = design_doc_path
        self._router = StageRouter()
        self._judge = ConvergenceJudge(ConvergenceConfig(max_iterations=max_rounds))
        self._gates = self._load_default_gates()
        self._checkpoint_mgr = CheckpointManager(self._checkpoint_store)

        if self._guardrail is None:
            self._guardrail = GuardrailChain.default()

        if self._design_doc:
            self._state.current_stage = "gap_scan"
            self._state.expected_stage = "gap_scan"
        else:
            self._state.current_stage = "architect"
            self._state.expected_stage = "architect"
        self._state.tick = 0
        self._save_checkpoint()
        return self._build_action()

    @classmethod
    def restore(
        cls,
        project_root: Path,
        checkpoint_store: SQLiteCheckpointStore,
        *,
        checkpoint_id: str | None = None,
        gate_runner: GateRunner | None = None,
        guardrail: GuardrailChain | None = None,
        max_rounds: int = 5,
    ) -> TickOrchestrator:
        """跨进程恢复 (§A.1: 每 tick 独立进程, 从 SQLite 重建全部 in-memory 状态).

        新进程 self._state=None → tick() 立即崩. restore() 从 checkpoint 重建
        _state/_design_doc/_batch_state/_progress_tree/_plan, 游标不归零。

        无 checkpoint_id → load_latest; 无 checkpoint → raise CheckpointNotFoundError.
        max_rounds: EngineState 未持久化该字段 → restore 用默认 5 (与 init 一致);
        精确恢复需扩 schema (本步不扩)。
        """
        from auto_engineering.loop.checkpoint.records import CheckpointNotFoundError

        self = cls(
            project_root,
            gate_runner=gate_runner,
            guardrail=guardrail,
            checkpoint_store=checkpoint_store,
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
        self._gates = self._load_default_gates()
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
        """处理一个 tick + DS-10 延迟打点 (C.2.6).

        墙钟切分: t_total (本方法) / t_gate (_run_developer_gates) /
        t_guard_sub (guardrail.check). t_orchestration = t_total − t_gate − t_guard_sub,
        写入 action_history; 超预算只告警不中断.
        """
        t_start = time.perf_counter()
        self._t_gate_ms = 0.0
        self._t_guard_sub_ms = 0.0
        tick_no = self._state.tick if self._state else 0
        action = self._tick_body(result_file)
        self._record_tick_latency(t_start, tick_no)
        return action

    def tick_dict(self, result: dict) -> dict:
        """处理一个 tick — 直接接受 result dict (Driver B standalone 模式).

        与 tick() 相同流程, 但跳过文件读取步骤, 直接验证并处理 result dict.
        """
        t_start = time.perf_counter()
        self._t_gate_ms = 0.0
        self._t_guard_sub_ms = 0.0
        tick_no = self._state.tick if self._state else 0
        action = self._tick_body_dict(result)
        self._record_tick_latency(t_start, tick_no)
        return action

    def _tick_body(self, result_file: Path) -> dict:
        """tick 核心逻辑: 验证 → Guardrail → Gate → 路由 → Checkpoint → action."""
        result = self._read_and_validate(result_file)
        return self._tick_process_result(result)

    def _tick_body_dict(self, result: dict) -> dict:
        """tick 核心逻辑 (dict 版本): 验证 → Guardrail → Gate → 路由 → Checkpoint → action."""
        validated = self._validate_result_dict(result)
        return self._tick_process_result(validated)

    def _tick_process_result(self, result: dict | ErrorResponse) -> dict:
        """tick 公共处理逻辑: Guardrail → Gate → 路由 → action."""
        if isinstance(result, ErrorResponse):
            return result.to_dict()

        self._apply_result_to_state(result)

        # 挂运行时非持久句柄供 Guardrail (G7 REDGuard 读 batch_state/_plan, B3 line 657).
        # asdict 只序列化 dataclass 字段 → 不泄漏进 checkpoint.
        self._state.batch_state = self._batch_state  # type: ignore[attr-defined]
        self._state._plan = self._plan  # type: ignore[attr-defined]

        t_g = time.perf_counter()
        gr = self._guardrail.check("post", self._state.current_stage,
                                   self._state, self.project_root)
        self._t_guard_sub_ms += (time.perf_counter() - t_g) * 1000

        if gr.action != "pass":
            # G8 FreshGate: 代码在 Gate 后又变更 → 陈旧证据 → 强制重跑 Gate
            # (S-4 rerun_gates 语义). 适用 developer + critic 两阶段 (§B3.2).
            # FreshGate 不清实现/不返错, 放行至 Gate 重跑刷新快照.
            # 非 FreshGate 的 guardrail → 返回错误.
            if getattr(gr, "guardrail_name", "") == "FreshGate":
                if self._state.current_stage != "developer":
                    self._run_developer_gates()
            else:
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
                        f"expected={self._state.current_stage!r}",
                current_state=self._state.to_dict())

        from auto_engineering.loop.actions import validate_result_format
        errors = validate_result_format(result, self._state.current_stage)
        if errors:
            return ErrorResponse(
                error_code="RESULT_VALIDATION_ERROR",
                message="; ".join(errors),
                current_state=self._state.to_dict())

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
        batches = self._state.batch_plan
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
        return self._build_action()

    # ── _after_developer ──

    def _after_developer(self) -> dict:
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
            return self._build_action()

        self._snapshot_developer_output()
        self._advance_stage("critic")
        return self._build_action()

    def _snapshot_developer_output(self) -> None:
        """保存 developer 产出快照 (advance_stage 会 clear_stage_fields)."""
        self._dev_snapshot = {
            "files_changed": self._state.files_changed,
            "commit_hash": self._state.commit_hash,
            "test_results": self._state.test_results,
        }

    # ── _after_critic ──

    def _after_critic(self, result: dict) -> dict:
        verdict = result.get("verdict", "")
        update_majors_count(self._state, verdict)

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
            return self._build_action(
                feedback=json.dumps(result.get("findings", [])))

        if verdict == "APPROVE":
            comp = self._batch_state.current_component()
            if self._batch_state.has_more_batches_for(comp):
                self._advance_stage("developer")
                return self._build_action()
            self._advance_stage("component_verifier")
            return self._build_action()

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
            return self._build_action()

        if self._verification_layers == VerificationLayers.LEAF:
            self._advance_stage("system_deep_audit")
        else:
            self._advance_stage("plate_deep_audit")
        return self._build_action()

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
            return self._build_action()

        if self._verification_layers == VerificationLayers.PLATE:
            self._advance_stage("system_deep_audit")
        else:
            self._advance_stage("system_verifier")
        action = self._build_action()
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
        action = self._build_action()
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
        return self._build_action()

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
        if pending_research:
            self._advance_stage("research")
        else:
            self._advance_stage("architect")
        return self._build_action()

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
            return self._build_action()
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
        return self._build_action()

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
                confidence=confidence, created_at=_now_iso())
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
            return ActionDone(verdict="REFINE_LIMIT", reason=reason).to_dict()

        self._state.plan_refine_by_source[source] = src_count + 1
        self._state.plan_refine_count += 1

        self._state.refine_request_json = json.dumps(
            self._build_refine_request(source))
        clear_stage_fields(self._state, self._state.current_stage)
        self._advance_stage("architect")
        return self._build_action()

    def _safe_design_section(self) -> str | None:
        """当前 component 的 design_section.

        组件级阶段 (architect/developer 批内) current component 有效; 系统级 refine
        (system_verifier/system_deep_audit) 在 batch 全部完成后触发, 无单一 current
        component → 返回 None (缺口细节由 audit_findings 承载, 不依赖单组件游标).
        """
        if self._batch_state is None or self._batch_state.is_plate_complete():
            return None
        return self._batch_state.current_design_section()

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

        if verdict.should_stop:
            self._save_checkpoint()
            return ActionDone(
                verdict=verdict.level_name, reason=verdict.reason,
                verdict_level=verdict.level).to_dict()

        self._save_checkpoint()
        return ActionDone(
            verdict="UNEXPECTED",
            reason="ConvergenceJudge returned CONTINUE after full cycle").to_dict()

    # ── _build_action ──

    def _build_action(self, feedback: str | None = None) -> dict:
        stage = self._state.current_stage
        base: dict = {
            "tick": self._state.tick + 1,
            "stage": stage,
            "thread_id": self._state.thread_id,
            "gate_summary": self._state.gate_results,
            "feedback": feedback,
            "requirement": self._state.requirement,
            "progress_summary": (
                self._progress_tree.summary() if self._progress_tree else None
            ),
        }

        if stage == "gap_scan":
            return {**base, "action": "gap_scan", "context": {
                "design_doc_path": (
                    self._design_doc.path if self._design_doc else None),
                "plates": [
                    {"id": p.design_section, "name": p.name,
                     "components": [c.design_section or c.name
                                    for c in p.components]}
                    for p in (self._design_doc.plates if self._design_doc else [])
                ],
                "project_root": str(self.project_root),
            }, "expected_format": {
                "gaps": ("[{id, design_section_ref, grade, clarity, "
                         "summary, depends_on}]"),
                "scanned_sections": "int",
                "has_blocking": "bool",
            }}

        elif stage == "gap_review":
            report = json.loads(self._state.gap_report_json or '{"gaps": []}')
            is_rereview = bool(self._state.research_archive)
            return {**base, "action": "gap_review",
                    "gaps": report.get("gaps", []),
                    "has_blocking": report.get("has_blocking", False),
                    "is_rereview": is_rereview,
                    "research_findings": dict(self._state.research_archive),
                    "instruction": (
                        "初审: 对每个 gap 用 AskUserQuestion 收集 Fill(用户补充) / "
                        "Research(检索) / Defer(留给architect) / Defer+Research. "
                        "has_blocking 的 architectural gap 禁止 Defer. "
                        "复审(is_rereview=true, research_findings 非空): 呈现 findings, "
                        "让用户据研究发现做补充设计 — Fill(写入细化内容→Supplement) "
                        "或 Defer(留给 architect in-loop 细化)."),
                    "expected_format": {
                        "decisions": "[{gap_id, resolution, user_note, fill_content?}]",
                    }}

        elif stage == "research":
            report = json.loads(self._state.gap_report_json or '{"gaps": []}')
            by_id = {g["id"]: g for g in report.get("gaps", [])}
            current_id = (
                self._state.pending_research_ids[0]
                if self._state.pending_research_ids else None)
            gap = by_id.get(current_id, {}) if current_id else {}
            return {**base, "action": "research",
                    "gap": {
                        "id": gap.get("id"),
                        "design_section_ref": gap.get("design_section_ref"),
                        "grade": gap.get("grade"),
                        "summary": gap.get("summary"),
                    },
                    "knowledge_sources": {
                        "tier_order": [
                            "tier0", "tier1_ref_code", "tier2_doc_kb", "tier3_web"],
                        "memory_constraint": (
                            "grep 定位 → 50-200 行 Read → 丢弃; 禁止批量/并行扫描"),
                    },
                    "expected_format": {
                        "findings": "string",
                        "sources": "[{tier, ref, note}]",
                        "source_tier": "tier0|tier1|tier2|tier3",
                        "confidence": "high|medium|low",
                        "recommended_design": "string (可注入 supplement)",
                    }}

        elif stage == "architect":
            action = {**base, "action": "architect", "context": {
                "requirement": self._state.requirement,
                "design_section": self._safe_design_section(),
                "project_root": str(self.project_root),
                "init_manifest": self._init_manifest,
                "design_supplements": (
                    json.loads(self._state.design_supplements_json)
                    if self._state.design_supplements_json else {}),
                "research_archive": self._state.research_archive,
            }, "expected_format": {
                "plan": "string (markdown, min 50 chars)",
                "batch_plan": (
                    "[{batch_id, design_section, component, "
                    "tasks:[{id, description, module_ref, file_targets}], "
                    "depends_on}] (min 1 batch)"),
                "file_list": "[string] (min 1 file)",
                "contracts": "object (may be empty)",
            }}
            # PLAN-REFINE 回路: RefineRequest 经 feedback 承载 (§B6.10 line 1178-1182)
            if self._state.refine_request_json:
                action["feedback"] = {
                    "mode": "PLAN_REFINE",
                    "refine_request": json.loads(self._state.refine_request_json),
                }
            return action

        elif stage == "developer":
            tasks = (
                self._batch_state.current_batch_tasks(self._plan)
                if self._batch_state and self._plan
                else (self._plan.get_tasks_by_stage("developer")
                      if self._plan else [])
            )
            return {**base, "action": "developer",
                    "component": (
                        self._batch_state.current_component_name()
                        if self._batch_state else None),
                    "batch_id": (
                        self._batch_state.current_batch_id()
                        if self._batch_state else None),
                    "tasks": [
                        {"id": t.id, "description": t.description,
                         "expected_output": t.expected_output,
                         "file_targets": list(t.target_files),
                         "depends_on": t.depends_on}
                        for t in tasks
                    ],
                    "plan": self._state.plan}

        elif stage == "critic":
            snap = self._dev_snapshot or {}
            return {**base, "action": "critic", "context": {
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
            }, "expected_format": {
                "stage": "critic",
                "verdict": "APPROVE | MAJOR",
                "findings": "[{file, line, severity, issue, suggestion}]",
                "critic_feedback": "string",
            }}

        elif stage == "component_verifier":
            comp = self._batch_state.current_component()
            return {**base, "action": "component_verifier", "context": {
                "component": comp.name,
                "design_section": comp.design_section,
                "design_spec": comp.design_spec_summary(),
                "implementation_files": getattr(comp, "implementation_files", []),
                "contracts": getattr(comp, "contracts", {}),
            }, "recheck": dict(_VERIFIER_RECHECK), "expected_format": {
                "stage": "component_verifier",
                "coverage_map": (
                    "[{design_item, status(IMPLEMENTED|MISSING|DIVERGED), "
                    "file, line, note}]"),
                "missing_count": "int",
                "diverged_count": "int",
                "recheck_log": (
                    "[{design_item, haiku_status, sonnet_verdict, final_status}] "
                    "(仅负判定经 Sonnet 复核后填, 无负判定则空)"),
            }}

        elif stage == "plate_deep_audit":
            plate = self._batch_state.current_plate()
            return {**base, "action": "plate_deep_audit", "context": {
                "plate": plate.name,
                "components": plate.components_summary(),
                "cross_component_contracts": plate.cross_component_contracts(),
                "project_root": str(self.project_root),
            }, "expected_format": {
                "stage": "plate_deep_audit",
                "findings": (
                    "[{severity, dimension, agent_source, file, line, "
                    "description, suggested_fix}]"),
                "p0_count": "int", "p1_count": "int", "p2_count": "int",
                "cross_component_issues": "[{contract_id, status, detail}]",
                "total_audited_files": "int",
            }}

        elif stage == "system_verifier":
            return {**base, "action": "system_verifier", "context": {
                "design_doc": (
                    self._design_doc.path if self._design_doc else None),
                "design_sections": (
                    self._design_doc.sections_summary()
                    if self._design_doc else []),
                "project_root": str(self.project_root),
            }, "recheck": dict(_VERIFIER_RECHECK), "expected_format": {
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
            }}

        elif stage == "system_deep_audit":
            return {**base, "action": "system_deep_audit", "context": {
                "project_root": str(self.project_root),
                "audit_dimensions": [
                    "架构合理性", "代码质量", "工程化规范",
                    "代码逻辑虚化度", "团队协作友好度", "设计覆盖度"],
                "p1_threshold": self._get_p1_threshold(),
                "coverage_map_from_verifier": self._state.coverage_map,
            }, "expected_format": {
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
            }}

        else:
            return {**base, "action": "error",
                    "error_code": "UNKNOWN_STAGE",
                    "message": f"Unknown stage: {stage}"}

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
                        f"expected={self._state.current_stage!r}",
                current_state=self._state.to_dict())

        from auto_engineering.loop.actions import validate_result_format
        errors = validate_result_format(result, self._state.current_stage)
        if errors:
            return ErrorResponse(
                error_code="RESULT_VALIDATION_ERROR",
                message="; ".join(errors),
                current_state=self._state.to_dict())

        return result

    def _apply_result_to_state(self, result: dict) -> None:
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
        elif stage == "critic":
            self._state.critic_verdict = result.get("verdict", "")
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
        clear_stage_fields(self._state, self._state.current_stage)
        self._state.current_stage = next_stage
        self._state.expected_stage = next_stage
        self._state.round += 1
        self._state.tick += 1
        self._state.guardrail_retry_counters[next_stage] = 0
        self._save_checkpoint()

    def _run_developer_gates(self) -> None:
        from auto_engineering.gates.registry import DEFAULT_GATES
        gates = self._gates or DEFAULT_GATES
        gate_names = tuple(g.name for g in gates)

        t_g = time.perf_counter()
        if self._gate_runner:
            results = self._gate_runner(gate_names, self.project_root)
        else:
            from auto_engineering.cli.gate_check import run_gates
            results = run_gates(gate_names, self.project_root)
        self._t_gate_ms += (time.perf_counter() - t_g) * 1000

        # S-3 生产者契约 (喂给 G8 FreshGate): 每个 Gate 结果附 files_snapshot_sha
        # (运行时 files_changed 内容聚合 sha256) + ran_at. 不产出则 FreshGate 恒 pass 静默失效.
        from auto_engineering.loop.guardrail import _aggregate_sha
        snapshot_sha = _aggregate_sha(
            self._state.files_changed, self.project_root)
        ran_at = datetime.now(UTC).isoformat()
        self._state.gate_results = {
            name: {
                "passed": (
                    v.get("passed")
                    if isinstance(v, dict)
                    else getattr(v, "passed", None)
                ),
                "message": (
                    v.get("message", "")
                    if isinstance(v, dict)
                    else getattr(v, "message", "") or ""
                ),
                "files_snapshot_sha": snapshot_sha,
                "ran_at": ran_at,
            }
            for name, v in results.items()
        }

    def _load_default_gates(self) -> list:
        from auto_engineering.gates.registry import DEFAULT_GATES
        return DEFAULT_GATES

    def _handle_guardrail_result(self, gr) -> dict:
        action = getattr(gr, "action", "block")
        return ActionError(
            error_code=f"GUARDRAIL_{action.upper()}",
            message=getattr(gr, "message", "")).to_dict()

    def _get_p1_threshold(self) -> int:
        return _DEFAULT_P1_THRESHOLD

    def _write_audit_history(self, p0: int, p1: int, p2: int,
                             triggered: bool) -> None:
        pass  # 后续 Phase: 写入 ThresholdLearner 历史

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

    def _resolve_batch_id(self) -> str | None:
        """返回当前 batch_id, 组件完成时回退到 _last_batch_id."""
        if self._batch_state is None:
            return None
        if not self._batch_state.is_component_complete():
            return self._batch_state.current_batch_id()
        return self._last_batch_id

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
    "_DEFAULT_P1_THRESHOLD",
    "_MAX_GLOBAL",
    "_MAX_PER_SOURCE",
    "TickOrchestrator",
]
