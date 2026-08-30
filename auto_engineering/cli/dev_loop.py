"""CLI dev_loop — v5.6 离散 Tick 模式。

从 cli.py 拆分 (Plan P1-B, 原 cli.py §218-451).
v5.5 Orchestrator 已退役 (T133b).
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from auto_engineering.config.runtime_config import RuntimeConfig, get_default_config
from auto_engineering.engine.state import EngineState

if TYPE_CHECKING:
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import EffectReceipt, SQLiteEventStore
    from auto_engineering.loop.events import LoopEvent

_logger = logging.getLogger(__name__)
_STATE_GITIGNORE = "*\n!.gitignore\n"


class _ActiveThreadStore(Protocol):
    def active_project_thread(self) -> str | None: ...
    def load_active_protocol_action(self, thread_id: str) -> dict | None: ...
    def record_protocol_action(self, action: dict) -> None: ...


class _ActiveThreadEvents(Protocol):
    def load_projection(self, thread_id: str) -> EngineState | None: ...
    def load_action_snapshot(self, thread_id: str) -> dict | None: ...
    def next_sequence(self, thread_id: str) -> int: ...
    def commit_tick(
        self,
        *,
        events: Iterable[LoopEvent],
        state: EngineState,
        action: Mapping[str, Any],
        result_causation_id: str | None = None,
        result_hash: str | None = None,
        effect_receipts: Iterable[EffectReceipt] = (),
    ) -> None: ...

# ============================================================
# v5.6 Tick 模式 CLI 处理器 (§A.1 Python 永不调 LLM — 不需 API key)
# 每次调用是独立进程, 从 .ae-state/checkpoints.db 恢复/持久化状态。
# ============================================================

def _ensure_state_dir(root: Path) -> Path:
    """创建 Core 状态目录并阻止宿主把内部事实重复注入工作区 diff。"""

    state_dir = root / ".ae-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    ignore_file = state_dir / ".gitignore"
    if not ignore_file.exists():
        try:
            with ignore_file.open("x", encoding="utf-8") as handle:
                handle.write(_STATE_GITIGNORE)
        except FileExistsError:
            pass
    return state_dir


def _ensure_checkpoint_db_path(root: Path) -> Path:
    """.ae-state/checkpoints.db — 跨 tick 持久化 store (目录不存在则创建)."""
    state_dir = _ensure_state_dir(root)
    return state_dir / "checkpoints.db"


def _ensure_event_db_path(root: Path) -> Path:
    """新协议内核的事实库；checkpoint DB 仅保留兼容与项目占用元数据。"""
    state_dir = _ensure_state_dir(root)
    return state_dir / "events.db"


def _root_bound_path(path: Path, root: Path) -> Path:
    """Resolve relative protocol artifacts against the explicit project root.

    Host tools are free to change their working directory between calls.  A
    relative Result/outcome path therefore belongs to the Action project, not
    to the ambient shell process.
    """

    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _cleanup_completed_action_work_files(
    *,
    root: Path,
    result_file: Path,
    completed_action: Mapping[str, object] | None,
    next_action: Mapping[str, object],
) -> None:
    """删除已提交 Action 的临时交接文件，保留 journal 与未知文件。"""

    if completed_action is None:
        return
    message_id = completed_action.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        return
    if next_action.get("message_id") == message_id:
        return
    action_key = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:24]
    work_dir = (
        root.resolve()
        / ".ae-state"
        / "host-runtime"
        / "work"
        / action_key
    )
    if result_file.parent != work_dir:
        return
    for name in ("outcomes.json", "coordinator-result.json", "result.json"):
        with suppress(FileNotFoundError):
            (work_dir / name).unlink()
    # 严格 Worker 的私有产出不与 Action work_dir 同目录，按当前 Action
    # invocation 精确清理，避免下次运行误读旧 artifact 或无限积累。
    try:
        from auto_engineering.host.spawn_contract import SpawnPlan

        plan = SpawnPlan.from_action(completed_action)
        for invocation in plan.invocations:
            if invocation.outcome_path is None:
                continue
            private_path = _root_bound_path(Path(invocation.outcome_path), root)
            if private_path.is_relative_to(root):
                with suppress(FileNotFoundError):
                    private_path.unlink()
    except Exception:
        # 清理不是状态提交的一部分；旧/损坏 Action 保留未知文件供审计。
        _logger.debug("worker private artifact cleanup skipped", exc_info=True)
    # 未知文件不是本协议的清理目标；保留目录供审计。
    with suppress(OSError):
        work_dir.rmdir()


def _map_action_for_host(action: dict) -> dict:
    """已识别宿主必须经过 Adapter 2.0 能力映射；未知 shell 保持核心协议。"""
    from auto_engineering.host import HostPlatform, detect_host
    from auto_engineering.loop.execution_control import project_execution_control

    # Canonical Action 保持不可变；宿主投影仍需修复完整 Gate 分类落地前生成的旧快照，
    # 否则旧人工 Gate 会被误判为 CONTINUE 并送入执行请求编译。
    action = project_execution_control(action)

    if not isinstance(action.get("message_id"), str):
        return action
    detection = detect_host()
    if detection.platform is HostPlatform.UNKNOWN:
        return action
    from auto_engineering.host.adapters import adapter_for

    adapter = adapter_for(detection.platform)
    profile = adapter.probe(
        detected=detection.capabilities,
        authorized=detection.capabilities,
    )
    return adapter.map_action(action, profile=profile).payload


def _prepare_action_for_host(
    action: dict,
    root: Path,
    *,
    compact_view: bool | None = None,
) -> dict:
    """映射 Action，并为当前原生宿主会话原子记录执行义务。"""

    mapped = _map_action_for_host(action)
    host_execution = mapped.get("host_execution")
    if isinstance(action.get("spawn"), Mapping) and isinstance(
        host_execution, dict
    ):
        from auto_engineering.host.execution_assembler import (
            HostEvidenceValidationError,
            HostExecutionAssembler,
        )

        work_files = host_execution.get("work_files")
        result_ref = (
            work_files.get("result")
            if isinstance(work_files, Mapping)
            else None
        )
        outcomes_ref = (
            work_files.get("outcomes")
            if isinstance(work_files, Mapping)
            else None
        )
        coordinator_ref = (
            work_files.get("coordinator_result")
            if isinstance(work_files, Mapping)
            else None
        )
        if all(
            isinstance(value, str) and value
            for value in (result_ref, outcomes_ref, coordinator_ref)
        ):
            raw_workers = host_execution.get("workers")
            rejection = action.get("result_rejection")
            is_result_repair = (
                isinstance(rejection, Mapping)
                and rejection.get("repair_required") is True
            )
            semantic_context_refs = [
                str(worker["prompt_ref"])
                for worker in raw_workers
                if isinstance(worker, Mapping)
                and isinstance(worker.get("prompt_ref"), str)
            ] if isinstance(raw_workers, list) else []
            try:
                committed = HostExecutionAssembler(root).restore_committed_result_to_file(
                    action=action,
                    result_path=Path(str(result_ref)),
                    outcomes_path=Path(str(outcomes_ref)),
                )
            except HostEvidenceValidationError as exc:
                import click

                raise click.ClickException(str(exc)) from exc
            if committed is not None:
                # Core Action 快照保持不变；宿主投影只暴露唯一合法恢复动作。
                mapped.pop("spawn", None)
                host_execution.pop("workers", None)
                host_execution.pop("native_worker_tools", None)
                host_execution["recovery"] = {
                    "schema_version": "1.0",
                    "status": "worker_outcomes_committed",
                    "spawn_permitted": False,
                    "required_operation": "validate_then_submit_or_repair",
                    "result_ref": result_ref,
                    "outcomes_ref": outcomes_ref,
                    "coordinator_result_ref": coordinator_ref,
                    "semantic_context_refs": semantic_context_refs,
                }
                mapped["instruction"] = (
                    "当前 Action 已有 Core 绑定的 Worker outcomes。"
                    "禁止启动 Worker；先验证并提交已固化 Result。"
                    "若业务预检失败，只修复 coordinator payload，"
                    "并使用已恢复 outcomes 重新 finalize。"
                )
            else:
                # Worker 已完成、原生事实已落盘，但进程可能在 Finalizer 提交前
                # 中断。此时重新 spawn 会重复付费且改变事实；只投影 finalize 恢复。
                import json

                outcomes_path = _root_bound_path(Path(str(outcomes_ref)), root)
                coordinator_path = _root_bound_path(
                    Path(str(coordinator_ref)), root
                )
                native_ready = False
                try:
                    raw_outcomes = json.loads(
                        outcomes_path.read_text(encoding="utf-8")
                    )
                    raw_coordinator = json.loads(
                        coordinator_path.read_text(encoding="utf-8")
                    )
                    outcome_items = (
                        raw_outcomes.get("outcomes")
                        if isinstance(raw_outcomes, dict)
                        else None
                    )
                    invocations = action["spawn"]["invocations"]
                    expected_workers = {
                        item["worker_id"] for item in invocations
                        if isinstance(item, Mapping)
                        and isinstance(item.get("worker_id"), str)
                    }
                    actual_workers = {
                        item["worker_id"] for item in outcome_items
                        if isinstance(item, Mapping)
                        and isinstance(item.get("worker_id"), str)
                    } if isinstance(outcome_items, list) else set()
                    native_ready = (
                        isinstance(raw_coordinator, dict)
                        and isinstance(outcome_items, list)
                        and bool(expected_workers)
                        and actual_workers == expected_workers
                        and all(
                            isinstance(item, Mapping)
                            and item.get("status") == "completed"
                            for item in outcome_items
                        )
                    )
                except (KeyError, OSError, json.JSONDecodeError, TypeError):
                    native_ready = False
                if native_ready and not is_result_repair:
                    mapped.pop("spawn", None)
                    host_execution.pop("workers", None)
                    host_execution.pop("native_worker_tools", None)
                    host_execution["recovery"] = {
                        "schema_version": "1.0",
                        "status": "native_outcomes_ready",
                        "spawn_permitted": False,
                        "required_operation": "finalize_current_native_outcomes",
                        "result_ref": result_ref,
                        "outcomes_ref": outcomes_ref,
                        "coordinator_result_ref": coordinator_ref,
                        "semantic_context_refs": semantic_context_refs,
                    }
                    mapped["instruction"] = (
                        "当前 Action 的原生 Worker outcomes 与 Coordinator payload "
                        "已经完整落盘但尚未提交。禁止重新启动 Worker；立即使用当前 "
                        "outcomes 和 coordinator_result 调用 Finalizer，再 validate/tick。"
                    )
    from auto_engineering.host import HostPlatform, detect_host
    from auto_engineering.host.runtime_driver import (
        HostRunLease,
        HostRunLeaseError,
        HostRunLeaseStore,
        host_session_id_from_environ,
    )

    detection = detect_host()
    session_id = host_session_id_from_environ(detection.platform)
    extensions = mapped.get("extensions")
    ae = extensions.get("ae") if isinstance(extensions, Mapping) else None
    control = ae.get("execution_control") if isinstance(ae, Mapping) else None
    requires_continuous_lease = (
        isinstance(control, Mapping)
        and control.get("disposition") == "CONTINUE"
    )
    if (
        detection.platform is not HostPlatform.UNKNOWN
        and session_id is None
        and requires_continuous_lease
        and isinstance(mapped.get("message_id"), str)
    ):
        raise HostRunLeaseError("HOST_SESSION_ID_UNAVAILABLE")
    if (
        detection.platform is not HostPlatform.UNKNOWN
        and session_id is not None
        and requires_continuous_lease
        and isinstance(mapped.get("message_id"), str)
    ):
        lease = HostRunLease.from_action(
            mapped,
            platform=detection.platform.value,
            host_session_id=session_id,
        )
        HostRunLeaseStore(root).save(lease)
    use_compact = (
        os.environ.get("AE_HOST_ACTION_VIEW", "").strip().lower() == "compact"
        if compact_view is None
        else compact_view
    )
    if use_compact:
        return _compact_host_action(mapped, root)
    return mapped


def _compact_host_action(action: Mapping[str, Any], root: Path) -> dict[str, Any]:
    """为产品宿主生成有界控制视图；Canonical Action 保持不变。"""

    compact_keys = (
        "schema_version",
        "message_type",
        "message_id",
        "correlation_id",
        "causation_id",
        "thread_id",
        "tick",
        "stage",
        "action",
        "project_root",
        "extensions",
        "host_execution",
        "spawn",
        "expected_format",
        "result_contract",
        "valid_plate_keys",
        "gate",
        "current_gap",
        "current_gap_index",
        "total_gaps",
        "auto_decision",
        "mode",
        "has_blocking",
        "gap_scan_summary",
        "audit_execution_profile",
        "required_capabilities",
        "missing_capabilities",
        "constraints",
        "resource",
        "retry_stage",
        "reason_code",
        "retry_attempt",
        "retry_limit",
        "reason",
        "result_rejection",
        "next_transition",
        "current_session_id",
        "capsule",
        "claim_token",
        "expires_at",
        "verdict",
        "verdict_level",
        "verdict_reason",
        "error_code",
        "message",
        "suggestion",
        "next_operation",
    )
    compact = {
        key: action[key]
        for key in compact_keys
        if key in action
    }
    extensions = action.get("extensions")
    if isinstance(extensions, Mapping):
        raw_ae = extensions.get("ae")
        if isinstance(raw_ae, Mapping):
            ae = {
                key: raw_ae[key]
                for key in ("execution_control", "runtime_revision", "runtime")
                if key in raw_ae
            }
            compact["extensions"] = {"ae": ae}
        else:
            compact.pop("extensions", None)
    host_execution = action.get("host_execution")
    if isinstance(host_execution, Mapping):
        projected_host = {
            key: host_execution[key]
            for key in (
                "schema_version",
                "platform",
                "action_message_id",
                "work_files",
                "recovery",
                "native_worker_tools",
            )
            if key in host_execution
        }
        workers = host_execution.get("workers")
        if isinstance(workers, list):
            projected_host["workers"] = [
                {
                    key: worker[key]
                    for key in (
                        "worker_id",
                        "prompt_ref",
                        "prompt_sha256",
                        "native_launch_prompt",
                        "expected_isolation_evidence",
                    )
                    if key in worker
                }
                for worker in workers
                if isinstance(worker, Mapping)
            ]
        compact["host_execution"] = projected_host
    compact["view"] = "compact"
    instruction = action.get("instruction")
    if isinstance(instruction, str) and instruction:
        encoded = instruction.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        relative = Path(".ae-state/effects/prompt") / f"coordinator-{digest}.txt"
        prompt_path = (root.resolve() / relative).resolve()
        if not prompt_path.is_relative_to(root.resolve()):
            raise ValueError("HOST_PROMPT_PATH_ESCAPE")
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        if prompt_path.exists():
            if prompt_path.read_bytes() != encoded:
                raise ValueError("HOST_PROMPT_CONTENT_ADDRESS_CONFLICT")
        else:
            try:
                with prompt_path.open("xb") as handle:
                    handle.write(encoded)
            except FileExistsError:
                if prompt_path.read_bytes() != encoded:
                    raise ValueError(
                        "HOST_PROMPT_CONTENT_ADDRESS_CONFLICT"
                    ) from None
        compact["coordinator_prompt_ref"] = {
            "path": relative.as_posix(),
            "sha256": digest,
            "size_bytes": len(encoded),
            "media_type": "text/plain; charset=utf-8",
        }
    return compact

def _active_thread(store: object) -> str | None:
    """兼容旧 Store façade；真实 SQLite store 提供原子项目占用查询。"""
    getter = getattr(store, "active_project_thread", None)
    return getter() if callable(getter) else None


def _resume_operation(thread_id: str) -> dict[str, object]:
    """生成唯一的 active Action 恢复操作，禁止宿主推导命令。"""

    return {
        "operation": "resume_active_action",
        "thread_id": thread_id,
        "argv": ["dev-loop", "--resume", thread_id],
    }


def active_resume_operation(root: Path) -> dict[str, object] | None:
    """只读查询当前项目占用；不编译 Action，不推进 Tick。"""

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(
        _ensure_checkpoint_db_path(root)
    )
    try:
        thread_id = _active_thread(store)
        return _resume_operation(thread_id) if thread_id is not None else None
    finally:
        store.close()


def _resolve_active_thread_start(
    *,
    root: Path,
    design_doc_path: str,
    store: _ActiveThreadStore,
    events: _ActiveThreadEvents,
) -> dict | None:
    """显式设计文档启动时，在恢复旧 Action 前完成只读一致性决策。"""
    thread_id = _active_thread(store)
    if thread_id is None:
        return None

    from auto_engineering.loop.invocation_intent import InvocationIntent
    from auto_engineering.loop.protocol import action_envelope
    from auto_engineering.loop.state_compatibility import (
        CompatibilityStatus,
        StateCompatibilityInspector,
    )
    from auto_engineering.project_profile import (
        AeConfigProvider,
        LegacyInitProvider,
        LocalProbeProvider,
        ProjectProfileResolver,
    )

    state = events.load_projection(thread_id)
    if state is None:
        return action_envelope(
            {
                "action": "error",
                "error_code": "STATE_CORRUPT",
                "message": "活动 thread 缺少可重放状态投影",
            },
            thread_id=thread_id,
            tick=0,
            stage=None,
        )
    active_action = (
        events.load_action_snapshot(thread_id)
        or store.load_active_protocol_action(thread_id)
    )
    intent = InvocationIntent.from_design_doc(root, design_doc_path)
    resolution = ProjectProfileResolver((
        AeConfigProvider(),
        LocalProbeProvider(),
        LegacyInitProvider(),
    )).resolve(root)
    report = StateCompatibilityInspector(root).inspect(
        intent=intent,
        state=state,
        profile_resolution=resolution,
        active_action=active_action,
    )
    if report.status is CompatibilityStatus.COMPATIBLE:
        return active_action
    if report.status is CompatibilityStatus.CORRUPT:
        return action_envelope(
            {
                "action": "error",
                "error_code": "STATE_CORRUPT",
                "message": "旧状态缺少设计基线，不能自动恢复",
            },
            thread_id=thread_id,
            tick=state.tick + 1,
            stage=state.current_stage,
        )

    message_id = str(uuid5(
        NAMESPACE_URL,
        f"state-reconciliation:{thread_id}:{intent.design_doc_digest}",
    ))
    action = action_envelope(
        {
            "action": "gate",
            "gate": {
                "id": "state_reconciliation",
                "type": "decision",
                "prompt": "检测到旧开发状态与当前项目不一致，请选择处理方式。",
                "options": [
                    {"id": "reinitialize", "label": "重新初始化"},
                    {"id": "reconcile", "label": "修复状态并继续"},
                ],
                "reason_codes": list(report.reason_codes),
                "missing_anchors": list(report.missing_anchors),
            },
        },
        thread_id=thread_id,
        tick=state.tick + 1,
        stage=state.current_stage,
        message_id=message_id,
    )
    existing_reconciliation = state.state_reconciliation or {}
    if existing_reconciliation.get("gate_message_id") != message_id:
        from auto_engineering.loop.events import LoopEvent, LoopEventType
        from auto_engineering.loop.reducers import default_reducer_registry

        event = LoopEvent.create(
            thread_id=thread_id,
            sequence=events.next_sequence(thread_id),
            event_type=LoopEventType.STATE_CONFLICT_DETECTED,
            payload={
                "changes": {
                    "state_reconciliation": {
                        "status": "waiting_user",
                        "gate_message_id": message_id,
                        "reason_codes": list(report.reason_codes),
                        "missing_anchors": list(report.missing_anchors),
                        "intent": {
                            "mode": intent.mode,
                            "design_doc_path": intent.design_doc_path,
                            "design_doc_digest": intent.design_doc_digest,
                            "scope": intent.scope,
                        },
                    }
                }
            },
            correlation_id=thread_id,
            causation_id=message_id,
        )
        projected = default_reducer_registry().reduce(state, event)
        events.commit_tick(events=[event], state=projected, action=action)
    store.record_protocol_action(action)
    return action


CATEGORY_SIMPLE = "simple_function"
CATEGORY_MEDIUM = "medium_crud"
CATEGORY_COMPLEX = "complex_multi_module"
_REQUIREMENT_CATEGORIES = (CATEGORY_SIMPLE, CATEGORY_MEDIUM, CATEGORY_COMPLEX)


def _infer_category(requirement: str) -> str:
    """Heuristic category inference for baseline stratification.

    Maps requirement text to one of the known complexity categories.
    Returns one of CATEGORY_SIMPLE / CATEGORY_MEDIUM / CATEGORY_COMPLEX.

    Design ref: v5.6-Design-Loop.md F.2.3 — by_category baselines.
    """
    req_lower = requirement.lower()
    simple_keywords = ["simple", "fix", "typo", "comment", "format", "rename", "remove unused"]
    complex_keywords = [
        "complex", "multi", "module", "refactor", "redesign", "architecture",
        "pipeline", "orchestrat", "migration", "database schema", "auth",
        "payment", "transaction", "security audit",
    ]
    if any(kw in req_lower for kw in complex_keywords):
        return CATEGORY_COMPLEX
    if any(kw in req_lower for kw in simple_keywords):
        return CATEGORY_SIMPLE
    return CATEGORY_MEDIUM


def _build_injectables(
    root: Path,
    environ_or_config: RuntimeConfig | dict[str, str] | None = None,
    injectables: dict | None = None,
) -> dict:
    """Build injectable modules shared by --init and --tick paths.

    Returns dict with keys: context_offloader, tracer, audit_logger.
    tracer is None unless AE_OTLP_ENDPOINT is set (avoids importing opentelemetry
    when not needed).

    Args:
        environ_or_config: Optional RuntimeConfig (P0-6) or legacy environ dict.
            Defaults to process-wide RuntimeConfig sentinel.
        injectables: P2-12 — pre-built injectables to override defaults
            (e.g. stub ContextOffloader for testing). Keys not provided
            in injectables fall back to the standard factory logic.
    """
    from auto_engineering.context.offloading import ContextOffloader

    if environ_or_config is None:
        cfg = get_default_config()
    elif isinstance(environ_or_config, RuntimeConfig):
        cfg = environ_or_config
    else:
        # Legacy path: plain dict (backward compat for tests)
        cfg = RuntimeConfig(environ=dict(environ_or_config))

    context_offloader = ContextOffloader(root / ".ae-state" / "offload")

    tracer = None
    otlp_endpoint = cfg.otlp_endpoint
    if otlp_endpoint:
        # Phase 43 T207: 启动前探测 collector 连通性，不可达时 stderr 引导
        import socket as _socket
        from urllib.parse import urlparse as _urlparse
        try:
            _parsed = _urlparse(otlp_endpoint)
            _host = _parsed.hostname or "localhost"
            _port = _parsed.port or 4317
            with _socket.create_connection((_host, _port), timeout=2):
                pass
        except (TimeoutError, OSError, ValueError):
            _logger.warning(
                "OTLP collector %s 不可达 — tracing 已降级为 NoOp", otlp_endpoint
            )
            _logger.warning(
                "  运行 ae doctor --setup-observability 启动 collector"
            )
        from auto_engineering.observability.tracing import setup_tracing
        tracer = setup_tracing(service_name="auto-engineering", otlp_endpoint=otlp_endpoint)

    audit_logger = None
    if cfg.audit_log_enabled:
        from auto_engineering.observability.audit_log import AuditLogger
        audit_log_dir = cfg.audit_log_dir or str(root / ".ae-state" / "audit")
        audit_logger = AuditLogger(Path(audit_log_dir))

    # Core 使用结构化摘要，不持有宿主模型凭据。
    from auto_engineering.context.summarization import SessionSummarizer
    session_summarizer = SessionSummarizer(llm_provider=None)

    result = {
        "context_offloader": context_offloader,
        "session_summarizer": session_summarizer,
        "tracer": tracer,
        "audit_logger": audit_logger,
    }

    # P2-12: merge caller-supplied injectables over defaults
    if injectables:
        result.update(injectables)

    return result


def _check_config_gate(
    root: Path,
    *,
    policy: str | None = None,
    interactive: bool | None = None,
) -> bool:
    """确保项目存在有效 ae.toml；交互向导或非交互标准 Profile 后继续。"""
    import os as _os

    import click as _click

    toml_path = root / "ae.toml"
    if toml_path.exists():
        from auto_engineering.config.ae_config import AeConfig
        existing = AeConfig(root)
        if existing.load_error is not None:
            raise _click.ClickException(
                f"CONFIG_INVALID: ae.toml 解析失败: {existing.load_error}"
            )
        for warning in existing.migration_warnings:
            _click.echo(f"⚠  CONFIG_DEPRECATED: {warning}", err=True)
        if existing.is_configured:
            return True

    from auto_engineering.config.ae_config import AeConfig
    from auto_engineering.config.feature_flags import FEATURE_MANIFEST, get_feature_status

    status = get_feature_status()
    active = [k for k, v in status.items() if v.get("active")]
    config = AeConfig(root)
    source_counts = {"env": 0, "file": 0, "default": 0}
    for feature in FEATURE_MANIFEST:
        source_counts[config.source_for(feature.key)] += 1
    selected_policy = (
        policy
        or _os.environ.get("AE_CONFIG_POLICY", "").strip()
        or ("defaults" if _os.environ.get("AE_SKIP_CONFIG_CHECK") == "1" else "")
    )
    if interactive is None:
        import sys
        interactive = sys.stdin.isatty()

    _click.echo("", err=True)
    state = "未配置" if not toml_path.exists() else "未包含有效配置"
    _click.echo(f"⚠  ae.toml {state}", err=True)
    _click.echo(
        "[配置来源] "
        f"env={source_counts['env']} file={source_counts['file']} "
        f"default={source_counts['default']}",
        err=True,
    )
    _click.echo("", err=True)
    _click.echo(f"当前生效的功能 (仅内置默认值, {len(active)}/{len(FEATURE_MANIFEST)} active):", err=True)
    for f in FEATURE_MANIFEST:
        if f.key in active:
            _click.echo(f"  ✓ {f.description}", err=True)
    _click.echo("", err=True)
    _click.echo("以下功能未启用，开发过程将缺少:", err=True)
    missing = ["无审计日志 → 无法回溯 LLM 调用", "无度量采集 → 无 AI Coding 信号数据",
               "无 DebugTracer → 故障时缺少诊断信息", "无 Token 采集 → 无用量数据"]
    for m in missing:
        _click.echo(f"  - {m}", err=True)
    _click.echo("", err=True)
    if selected_policy:
        if selected_policy in {"defaults", "create"}:
            from auto_engineering.cli.doctor import _init_config
            if toml_path.exists():
                raise _click.ClickException(
                    "CONFIG_REQUIRED: 现有 ae.toml 未包含有效配置，请运行 "
                    "ae doctor --wizard 修复"
                )
            if not _init_config(root):
                raise _click.ClickException("CONFIG_CREATE_FAILED: ae.toml 创建失败")
            _click.echo(
                f"[配置] policy={selected_policy}，已写入 standard profile",
                err=True,
            )
            return True
        if selected_policy == "require":
            raise _click.ClickException(
                "CONFIG_POLICY_REQUIRED: policy=require 且 ae.toml 不存在"
            )
        raise _click.ClickException(
            f"CONFIG_POLICY_INVALID: {selected_policy}"
        )

    if not interactive:
        from auto_engineering.cli.doctor import _init_config
        if toml_path.exists() or not _init_config(root):
            raise _click.ClickException(
                "CONFIG_REQUIRED: ae.toml 无有效配置，请运行 ae doctor --wizard"
            )
        _click.echo("[配置] 非交互宿主已写入 standard profile", err=True)
        return True

    _click.echo("→ 首次启动必须完成配置，正在启动向导...", err=True)
    from auto_engineering.cli.doctor import _run_wizard
    if not _run_wizard(root):
        raise _click.ClickException("CONFIG_REQUIRED: 配置未保存，启动已取消")
    return True


def _activate_project_config(root: Path) -> None:
    """在配置闸门可能创建 ae.toml 后刷新本进程的不可变配置快照。"""
    from auto_engineering.config.runtime_config import (
        RuntimeConfig,
        set_default_config,
    )

    set_default_config(RuntimeConfig.from_project(root))


def run_tick_init(
    requirement: str, design_doc_path: str | None, root: Path, max_rounds: int,
    debug: bool = False, debug_dir: str | None = None,
    pause_at_stage: str | None = None,
    escalate: bool = False,
    config_policy: str | None = None,
) -> None:
    """ae dev-loop --init: 初始化 tick loop, 输出第一个 action JSON (stdout 契约)."""
    import click

    if requirement.lower().endswith((".md", ".markdown")) and (root / requirement).is_file():
        raise click.ClickException("DESIGN_DOC_REQUIRED: 请将设计文档路径通过 --design-doc 传入，"
                                   f"requirement 请改为自然语言需求（--design-doc {requirement}）")
    # Phase 45: 配置闸门
    if not _check_config_gate(root, policy=config_policy):
        return
    _activate_project_config(root)

    import hashlib
    import json

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(_ensure_checkpoint_db_path(root))
    events = SQLiteEventStore(_ensure_event_db_path(root))
    reserved_thread_id = str(uuid4())
    try:
        if design_doc_path:
            existing_action = _resolve_active_thread_start(
                root=root,
                design_doc_path=design_doc_path,
                store=store,
                events=events,
            )
            if existing_action is not None:
                click.echo(json.dumps(_prepare_action_for_host(existing_action, root), ensure_ascii=False))
                return
        existing_thread_id = store.reserve_project_thread(reserved_thread_id)
        if existing_thread_id is not None:
            raise click.ClickException(
                "PROJECT_THREAD_ACTIVE: 项目已有未完成 thread；"
                f"请运行 scripts/ae-run dev-loop --resume {existing_thread_id}"
            )
        inj = _build_injectables(root)
        orch = TickOrchestrator(root, checkpoint_store=store, event_store=events,
                                context_offloader=inj["context_offloader"],
                                session_summarizer=inj.get("session_summarizer"),
                                tracer=inj["tracer"],
                                audit_logger=inj["audit_logger"],
                                debug=debug, debug_dir=debug_dir,
                                escalate=escalate)
        if pause_at_stage:
            stages = [s.strip() for s in pause_at_stage.split(",") if s.strip()]
            orch.set_pause_at_stages(stages)
        action = orch.init(
            requirement,
            design_doc_path=design_doc_path,
            max_rounds=max_rounds,
            thread_id=reserved_thread_id,
        )

        # T69a: Activate metrics collector when AE_METRICS=1
        if get_default_config().metrics_enabled:
            from auto_engineering.metrics.collector import (
                MetricsCollector,
                set_collector,
            )
            collector = MetricsCollector(root)
            set_collector(collector)
            thread_id = action.get("thread_id", "")
            req_hash = hashlib.sha256(requirement.encode()).hexdigest()[:12]
            collector.begin_requirement(
                thread_id, req_hash,
                requirement_category=_infer_category(requirement),
            )

        # T114 5.3: one-line feature status on stderr
        from auto_engineering.config.feature_flags import feature_status_oneline, feature_warnings
        cfg = get_default_config()
        click.echo(feature_status_oneline(cfg.environ), err=True)
        # Phase 45 T216: 配置来源
        toml_path = root / "ae.toml"
        if toml_path.exists():
            from auto_engineering.config.feature_flags import FEATURE_MANIFEST
            active_count = sum(1 for f in FEATURE_MANIFEST if cfg.is_active(f.key))
            click.echo(
                f"  (配置来源: ae.toml, {active_count}/{len(FEATURE_MANIFEST)} active)",
                err=True)
        else:
            click.echo("  (配置来源: 内置默认值)", err=True)
        for w in feature_warnings(cfg.environ):
            click.echo(f"  [WARN] {w}", err=True)

        click.echo(json.dumps(_prepare_action_for_host(action, root), ensure_ascii=False))
    except Exception:
        store.release_project_thread(reserved_thread_id)
        raise
    finally:
        events.close()
        store.close()


def run_tick_step(result_file: Path, root: Path,
                   debug: bool = False, debug_dir: str | None = None) -> None:
    """ae dev-loop --tick --result <file>: restore → tick → 下一 action JSON."""
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    result_file = _root_bound_path(result_file, root)
    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(_ensure_checkpoint_db_path(root))
    events = SQLiteEventStore(_ensure_event_db_path(root))
    try:
        reconciled_action = _process_state_reconciliation_result(
            result_file=result_file,
            root=root,
            store=store,
            events=events,
            debug=debug,
            debug_dir=debug_dir,
        )
        if reconciled_action is not None:
            click.echo(json.dumps(_prepare_action_for_host(reconciled_action, root), ensure_ascii=False))
            return
        inj = _build_injectables(root)
        active_thread = _active_thread(store)
        completed_action = (
            events.load_action_snapshot(active_thread)
            if active_thread is not None
            else None
        )
        if completed_action is None and active_thread is not None:
            completed_action = store.load_active_protocol_action(active_thread)
        use_events = (
            active_thread is not None
            and events.load_projection(active_thread) is not None
        )
        orch = TickOrchestrator.restore(root, store, debug=debug, debug_dir=debug_dir,
                                        event_store=events if use_events else None,
                                        thread_id=active_thread,
                                        context_offloader=inj["context_offloader"],
                                        session_summarizer=inj.get("session_summarizer"),
                                        tracer=inj["tracer"],
                                        audit_logger=inj["audit_logger"])

        # T69a: Restore metrics collector from disk for cross-process continuity
        if get_default_config().metrics_enabled:
            from auto_engineering.metrics.collector import (
                MetricsCollector,
                set_collector,
            )
            collector = MetricsCollector(root)
            set_collector(collector)
            collector.resume_events(orch._state.thread_id)

        try:
            action = orch.tick(result_file)
        except Exception as exc:
            # 已知的事件投影一致性故障必须以协议错误返回，让宿主停止当前
            # action 并保留可恢复 checkpoint；未知异常仍 fail-closed 抛出。
            from auto_engineering.loop.event_store import StateProjectionMismatchError

            if not isinstance(exc, StateProjectionMismatchError):
                raise
            from auto_engineering.loop.actions import ActionError
            from auto_engineering.loop.protocol import action_envelope

            channels = ", ".join(exc.channels) or "unknown"
            _logger.error("事件投影一致性校验失败；channels=%s", channels)
            state = orch._state
            action = action_envelope(
                ActionError(
                    error_code="STATE_PROJECTION_MISMATCH",
                    message=f"事件投影与当前状态不一致；冲突通道：{channels}",
                    suggestion="请保留 .ae-state 并在升级或修复引擎后重新执行恢复命令。",
                ).to_dict(),
                thread_id=state.thread_id,
                tick=state.tick,
                stage=state.current_stage,
            )
            click.echo(json.dumps(_prepare_action_for_host(action, root), ensure_ascii=False))
            return
        candidate_rejected = _record_outcome_acceptance(
            root=root,
            submitted_result_file=result_file,
            core_response=action,
        )
        if (
            candidate_rejected
            and orch._active_action is not None
            and action.get("action") == "error"
        ):
            action = _project_result_repair_action(orch._active_action, action)
        _cleanup_completed_action_work_files(
            root=root,
            result_file=result_file,
            completed_action=completed_action,
            next_action=action,
        )
        if (
            action.get("action") == "done"
            and orch._state is not None
        ):
            store.release_project_thread(orch._state.thread_id)
            # 终态必须在事件流中留下机器事实，供产品证据门禁核验。
            # append_new 具备严格序列分配；幂等检查避免宿主重复提交时重复记录。
            if not any(
                event.event_type.value == "LoopCompleted"
                for event in events.load_stream(orch._state.thread_id)
            ):
                from auto_engineering.loop.events import LoopEventType

                events.append_new(
                    thread_id=orch._state.thread_id,
                    event_type=LoopEventType.LOOP_COMPLETED,
                    payload={
                        "action": "done",
                        "verdict": action.get("verdict"),
                        "tick": action.get("tick", orch._state.tick),
                    },
                    correlation_id=orch._state.thread_id,
                    causation_id=action.get("message_id"),
                )

        # T69a: Flush metrics events after tick, end requirement if terminal
        if get_default_config().metrics_enabled:
            from auto_engineering.metrics.collector import get_collector
            mc = get_collector()
            if mc is not None:
                if action.get("action") == "done":
                    verdict = action.get("verdict", "UNKNOWN")
                    total_ticks = action.get("tick", orch._state.tick if orch._state else 0)
                    mc.end_requirement(verdict, total_ticks=total_ticks)
                else:
                    mc._flush()

        click.echo(json.dumps(_prepare_action_for_host(action, root), ensure_ascii=False))
    finally:
        events.close()
        store.close()


def _record_outcome_acceptance(
    *,
    root: Path,
    submitted_result_file: Path,
    core_response: Mapping[str, Any],
) -> bool:
    """用 Core 响应完成宿主候选 Result 事务；无 journal 时保持兼容。"""

    import json

    from auto_engineering.host.outcome_journal import (
        OutcomeJournal,
        OutcomeJournalTransitionError,
    )

    try:
        submitted = json.loads(submitted_result_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(submitted, Mapping):
        return False
    journal = OutcomeJournal(root)
    try:
        return journal.complete_from_core(submitted, core_response)
    except OutcomeJournalTransitionError as exc:
        raise RuntimeError(f"OUTCOME_ACCEPTANCE_RECORD_FAILED:{exc}") from exc


def _project_result_repair_action(
    active_action: Mapping[str, Any],
    core_response: Mapping[str, Any],
) -> dict[str, Any]:
    """保持 Core active Action 身份，只附加本次候选拒绝事实。"""

    projected = dict(active_action)
    projected["result_rejection"] = {
        "error_code": core_response.get("error_code", "RESULT_REJECTED"),
        "message": core_response.get("message", "Result 未被 Core 接受"),
        "violations": core_response.get("violations", []),
        "repair_required": True,
    }
    original_instruction = active_action.get("instruction")
    repair_instruction = (
        "上一次候选 Result 未被 Core 接受。保持当前 Action 身份，"
        "根据 result_rejection 修复语义产物后重新 finalize；"
        "不得重做已完成的 Worker 工作。"
    )
    projected["instruction"] = (
        f"{original_instruction}\n\n## Result 修复\n\n{repair_instruction}"
        if isinstance(original_instruction, str) and original_instruction
        else repair_instruction
    )
    return projected


def _process_state_reconciliation_result(
    *,
    result_file: Path,
    root: Path,
    store: SQLiteCheckpointStore[EngineState],
    events: SQLiteEventStore,
    debug: bool = False,
    debug_dir: str | None = None,
) -> dict | None:
    """处理协调 Gate Result；非协调 Result 返回 None 交回常规 Tick。"""
    import json

    try:
        result = json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(result, dict):
        return None
    resolution = result.get("gate_resolution")
    if not isinstance(resolution, dict) or resolution.get("gate_id") != "state_reconciliation":
        return None
    if resolution.get("resolution") == "reconcile":
        return None

    from auto_engineering.loop.protocol import payload_digest
    from auto_engineering.loop.state_reconciliation import StateReconciliationService
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    thread_id = result.get("thread_id")
    causation_id = result.get("causation_id")
    if isinstance(thread_id, str) and isinstance(causation_id, str):
        replay = store.load_protocol_result(thread_id, causation_id)
        if replay is not None:
            previous_hash, response = replay
            if previous_hash != payload_digest(result):
                raise ValueError("RESULT_CONFLICT: 相同协调 Gate 已提交不同选择")
            return response

    old_state = events.load_projection(str(thread_id))
    if old_state is None:
        raise ValueError("STATE_CORRUPT: 协调 Result 对应的旧 thread 不存在")
    outcome = StateReconciliationService(events).select(result)
    if outcome.choice != "reinitialize":
        return dict(outcome.response)

    old_thread_id = old_state.thread_id
    if isinstance(causation_id, str):
        store.record_protocol_result(
            old_thread_id,
            causation_id,
            payload_digest(result),
            dict(outcome.response),
        )
    store.release_project_thread(old_thread_id)
    new_thread_id = str(uuid4())
    existing = store.reserve_project_thread(new_thread_id)
    if existing is not None:
        raise ValueError(f"PROJECT_THREAD_ACTIVE: {existing}")
    try:
        inj = _build_injectables(root)
        orch = TickOrchestrator(
            root,
            checkpoint_store=store,
            event_store=events,
            context_offloader=inj["context_offloader"],
            session_summarizer=inj.get("session_summarizer"),
            tracer=inj["tracer"],
            audit_logger=inj["audit_logger"],
            debug=debug,
            debug_dir=debug_dir,
        )
        design_doc_path = outcome.intent.get("design_doc_path")
        if not isinstance(design_doc_path, str) or not design_doc_path:
            raise ValueError("STATE_RECONCILIATION_INTENT_INVALID")
        action = orch.init(
            old_state.requirement,
            design_doc_path=design_doc_path,
            thread_id=new_thread_id,
        )
        if isinstance(causation_id, str):
            store.record_protocol_result(
                old_thread_id,
                causation_id,
                payload_digest(result),
                action,
            )
        return action
    except BaseException:
        store.release_project_thread(new_thread_id)
        raise


def run_tick_validate(result_file: Path, root: Path) -> None:
    """预校验 Result；不推进状态，也不生成新的协议记录。"""
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    result_file = _root_bound_path(result_file, root)
    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(
        _ensure_checkpoint_db_path(root)
    )
    events = SQLiteEventStore(_ensure_event_db_path(root))
    try:
        active_thread = _active_thread(store)
        use_events = active_thread is not None and events.load_projection(active_thread) is not None
        orch = TickOrchestrator.restore(
            root,
            store,
            event_store=events if use_events else None,
            thread_id=active_thread,
        )
        result = orch.validate_result_file(result_file)
        if result.get("action") == "error":
            candidate_rejected = _record_outcome_acceptance(
                root=root,
                submitted_result_file=result_file,
                core_response=result,
            )
            if candidate_rejected and orch._active_action is not None:
                repair = _project_result_repair_action(
                    orch._active_action, result
                )
                click.echo(json.dumps(
                    _prepare_action_for_host(repair, root),
                    ensure_ascii=False,
                ))
                return
            click.echo(json.dumps(result, ensure_ascii=False))
            raise SystemExit(1)
        click.echo(json.dumps(result, ensure_ascii=False))
    finally:
        events.close()
        store.close()


def run_tick_finalize(
    outcomes_file: Path | None,
    coordinator_result_file: Path,
    root: Path,
    *,
    output_result_file: Path | None = None,
) -> None:
    """从宿主原生 outcome 原子生成可直接提交 Tick 的完整 Result。"""

    import json

    import click

    from auto_engineering.host.execution_assembler import (
        HostEvidenceValidationError,
        HostExecutionAssembler,
        NativeWorkerOutcome,
        WorkerOutcomeCollectionError,
    )
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore

    supplied_outcomes_file = (
        _root_bound_path(outcomes_file, root)
        if outcomes_file is not None else None
    )
    supplied_coordinator_file = _root_bound_path(coordinator_result_file, root)
    supplied_output_file = (
        _root_bound_path(output_result_file, root)
        if output_result_file is not None else None
    )

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(
        _ensure_checkpoint_db_path(root)
    )
    events = SQLiteEventStore(_ensure_event_db_path(root))
    try:
        thread_id = _active_thread(store)
        if thread_id is None:
            raise click.ClickException("PROJECT_THREAD_NOT_ACTIVE")
        action = events.load_action_snapshot(thread_id)
        if action is None:
            action = store.load_active_protocol_action(thread_id)
        if action is None:
            raise click.ClickException("ACTIVE_ACTION_MISSING")
        mapped_action = _map_action_for_host(action)
        outcomes_path = supplied_outcomes_file
        coordinator_path = supplied_coordinator_file
        result_path = supplied_output_file
        host_execution = mapped_action.get("host_execution")
        work_files = (
            host_execution.get("work_files")
            if isinstance(host_execution, Mapping)
            else None
        )
        if isinstance(work_files, Mapping):
            current_coordinator_ref = work_files.get("coordinator_result")
            current_outcomes_ref = work_files.get("outcomes")
            current_result_ref = work_files.get("result")
            if isinstance(current_coordinator_ref, str):
                current_coordinator = _root_bound_path(
                    Path(current_coordinator_ref), root
                )
                # Result 始终属于当前 Action 的隔离工作目录。即使 Coordinator
                # 文件缺失（正是 Worker 无产出的故障场景），也要准备 canonical
                # result 路径，避免 Finalizer 只在 stdout 返回失败而没有交接文件。
                if result_path is None and isinstance(current_result_ref, str):
                    result_path = _root_bound_path(Path(current_result_ref), root)
                # 兼容旧调用者自定义文件；但当前 Action 的隔离工作文件已经存在时，
                # 它是唯一事实源，陈旧的上一 Action 参数不得再次进入 Assembler。
                if (
                    coordinator_path != current_coordinator
                    and current_coordinator.is_file()
                ):
                    coordinator_path = current_coordinator
                    if isinstance(current_result_ref, str):
                        result_path = _root_bound_path(
                            Path(current_result_ref), root
                        )
                    if (
                        supplied_outcomes_file is not None
                        and isinstance(current_outcomes_ref, str)
                    ):
                        outcomes_path = _root_bound_path(
                            Path(current_outcomes_ref), root
                        )
        input_error: str | None = None
        raw_outcomes: object = []
        coordinator_payload: object = {}
        try:
            raw_outcomes = (
                json.loads(outcomes_path.read_text(encoding="utf-8"))
                if outcomes_path is not None
                else []
            )
        except (OSError, json.JSONDecodeError) as exc:
            input_error = f"Worker outcomes 不可读取或不是合法 JSON: {exc.__class__.__name__}"
        try:
            coordinator_payload = json.loads(
                coordinator_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            input_error = (
                input_error
                or f"Coordinator payload 不可读取或不是合法 JSON: {exc.__class__.__name__}"
            )
        outcome_items = (
            raw_outcomes.get("outcomes")
            if isinstance(raw_outcomes, dict)
            else raw_outcomes
        )
        if not isinstance(outcome_items, list):
            input_error = input_error or "Worker outcomes 顶层必须是 JSON object 或数组"
        if not isinstance(coordinator_payload, dict):
            input_error = input_error or "Coordinator payload 顶层必须是 JSON object"
        is_spawn_action = isinstance(mapped_action.get("spawn"), Mapping)
        if input_error is None and is_spawn_action and not outcome_items:
            # 新版 Worker 先写自己的 outcome_path，Coordinator 只负责合并。
            # 只有在共享 outcomes 缺失/为空时才触发采集，兼容旧宿主已写入
            # 共享文件的路径，同时让真实宿主不再依赖 Coordinator 手工捏造事实。
            try:
                if outcomes_path is None:
                    raise WorkerOutcomeCollectionError(
                        "HOST_WORKER_OUTPUT_MISSING", "unknown", "outcomes_path_missing"
                    )
                collected_outcomes = HostExecutionAssembler(root).collect_worker_outcomes_from_artifacts(
                    action=mapped_action,
                    outcomes_path=outcomes_path,
                )
                outcome_items = [item.to_dict() for item in collected_outcomes]
            except WorkerOutcomeCollectionError as exc:
                input_error = str(exc)
        if input_error is None and is_spawn_action and not outcome_items:
            input_error = "Worker outcomes 为空"
        outcomes: list[NativeWorkerOutcome] = []
        if input_error is None:
            try:
                outcomes = [NativeWorkerOutcome(**item) for item in outcome_items]
            except (TypeError, ValueError) as exc:
                input_error = (
                    "Worker outcome 字段不完整或类型错误: "
                    f"{exc.__class__.__name__}"
                )
        if input_error is not None:
            # Spawn Action 的空/损坏交接文件代表 Worker 失败，而不是 CLI
            # 参数错误。生成带明确 unreported 哨兵的失败事务，让 Core 按
            # 失败预算自动重试；inline Action 仍保持严格输入错误。
            if isinstance(mapped_action.get("spawn"), Mapping):
                assembler = HostExecutionAssembler(root)
                result = assembler.finalize_missing_worker_output(
                    action=mapped_action,
                    reason_code=(
                        "HOST_WORKER_OUTPUT_MISSING"
                        if not outcomes
                        else "HOST_WORKER_OUTPUT_INVALID"
                    ),
                    detail=input_error,
                    result_path=result_path,
                )
                click.echo(json.dumps(result, ensure_ascii=False))
                return
            raise click.ClickException("HOST_OUTCOME_INPUT_INVALID")
        assert isinstance(coordinator_payload, dict)
        try:
            assembler = HostExecutionAssembler(root)
            if result_path is None:
                result = assembler.finalize(
                    action=mapped_action,
                    outcomes=outcomes,
                    coordinator_payload=coordinator_payload,
                )
            else:
                result = assembler.finalize_to_file(
                    action=mapped_action,
                    outcomes=outcomes,
                    coordinator_payload=coordinator_payload,
                    result_path=result_path,
                )
        except HostEvidenceValidationError as exc:
            from auto_engineering.host.outcome_journal import OutcomeJournal

            action_message_id = mapped_action.get("message_id")
            if not isinstance(action_message_id, str) or not action_message_id:
                raise click.ClickException(str(exc)) from exc
            OutcomeJournal(root).reject_assembly(
                action_message_id,
                coordinator_payload=coordinator_payload,
                error_code="HOST_EVIDENCE_INVALID",
                violations=exc.violations,
            )
            repair_action = _project_result_repair_action(
                mapped_action,
                {
                    "error_code": "HOST_EVIDENCE_INVALID",
                    "message": "宿主语义产物无法组装为合法 Result",
                    "violations": list(exc.violations),
                },
            )
            click.echo(json.dumps(
                _prepare_action_for_host(repair_action, root),
                ensure_ascii=False,
            ))
            return
        click.echo(json.dumps(result, ensure_ascii=False))
    finally:
        events.close()
        store.close()


def _status_action_summary(action: Mapping[str, Any]) -> dict[str, Any]:
    """投影当前 Action 的宿主所需字段，不泄漏 Canonical 私有 context。"""
    host_execution = action.get("host_execution")
    work_files = action.get("work_files")
    if not isinstance(work_files, Mapping) and isinstance(host_execution, Mapping):
        work_files = host_execution.get("work_files")
    summary: dict[str, Any] = {}
    for key in (
        "message_id", "action", "stage", "current_gap_index", "total_gaps",
        "current_gap", "expected_format",
    ):
        value = action.get(key)
        if isinstance(value, Mapping):
            summary[key] = dict(value)
        elif value is not None:
            summary[key] = value
    if isinstance(work_files, Mapping):
        summary["work_files"] = dict(work_files)
    return summary


def run_tick_status(root: Path, verbose: bool = False) -> None:
    """ae dev-loop --status: restore → 输出当前 tick 状态摘要 JSON."""
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(_ensure_checkpoint_db_path(root))
    events = SQLiteEventStore(_ensure_event_db_path(root))
    try:
        active_thread = _active_thread(store)
        lease = None
        if active_thread is None:
            from auto_engineering.host.runtime_driver import HostRunLeaseStore

            lease = HostRunLeaseStore(root).load()
            if lease is not None and events.load_projection(lease.thread_id) is not None:
                active_thread = lease.thread_id
        use_events = active_thread is not None and events.load_projection(active_thread) is not None
        orch = TickOrchestrator.restore(
            root,
            store,
            event_store=events if use_events else None,
            thread_id=active_thread,
        )
        s = orch._state
        summary: dict = {
            "thread_id": s.thread_id,
            "current_stage": s.current_stage,
            "expected_stage": s.expected_stage,
            "tick": s.tick,
            "round": s.round,
            "verdict": s.critic_verdict,
            "total_majors": s.total_majors,
            "plan_refine_count": s.plan_refine_count,
        }
        if active_thread is not None and (
            lease is None or lease.disposition != "TERMINAL"
        ):
            summary["next_operation"] = _resume_operation(active_thread)
        if lease is not None and lease.disposition == "TERMINAL":
            summary["current_stage"] = "done"
            summary["expected_stage"] = "done"
        elif active_thread is not None:
            # status 必须是纯读取；build_action() 可能提交新的 Action 事件，
            # 在查询阶段会制造 action_timestamp 投影冲突。只读取 EventStore
            # 已持久化的 Canonical Action，缺失时再读取兼容 checkpoint 快照。
            active_action = events.load_action_snapshot(active_thread)
            checkpoint_action = store.load_active_protocol_action(active_thread)
            if (
                isinstance(checkpoint_action, Mapping)
                and not isinstance(
                    active_action.get("host_execution")
                    if isinstance(active_action, Mapping)
                    else None,
                    Mapping,
                )
            ):
                # 旧 EventStore 快照可能只保存 Canonical 字段；宿主 work_files
                # 仍从同一 active Action 的 checkpoint 投影读取，不能返回半份合同。
                active_action = checkpoint_action
            if active_action is None:
                active_action = checkpoint_action
            if isinstance(active_action, Mapping):
                summary["active_action"] = _status_action_summary(
                    _map_action_for_host(dict(active_action))
                )
            else:
                summary["active_action_error"] = "ACTIVE_ACTION_UNAVAILABLE"
        from auto_engineering.loop.status_projection import reconciliation_status

        reconciliation = reconciliation_status(s, orch._batch_state)
        if reconciliation is not None:
            summary["plan_reconciliation"] = reconciliation
        if verbose and orch._batch_state is not None:
            bs = orch._batch_state
            batches, comp = [], None
            try:
                comp = bs.current_component()
                for b in bs.batches_for(comp):
                    batches.append({
                        "batch_id": b.get("batch_id", ""),
                        "component": b.get("component", ""),
                        "task_count": len(b.get("tasks", [])),
                    })
            except Exception:
                _logger.debug("batch summary build failed", exc_info=True)
                pass
            summary["batch_progress"] = {
                "current_component": comp.name if comp else "?",
                "current_batch_idx": bs.current_batch_idx,
                "total_batches": len(bs.batches_for(comp)) if comp else 0,
                "batches": batches,
                "total_components_seen": len(getattr(bs, "_seen_components", [])),
            }
        click.echo(json.dumps(summary, ensure_ascii=False))
    finally:
        events.close()
        store.close()


def run_tick_resume(checkpoint_id: str, root: Path) -> None:
    """ae dev-loop --resume <id>: 从指定 checkpoint 恢复 → 输出当前 action JSON.

    DS-14 (T160, 2026-07-23): 支持 thread_id 作为回退查询。
    用户常把 action JSON 中的 thread_id 当作 checkpoint_id 传入，
    导致 CheckpointNotFoundError。当 checkpoint_id 未直接命中时，
    在 checkpoints 表中搜索 state_json 包含该 ID 的记录。
    """
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(_ensure_checkpoint_db_path(root))
    events = SQLiteEventStore(_ensure_event_db_path(root))
    try:
        event_action = events.load_action_snapshot(checkpoint_id)
        if event_action is not None:
            click.echo(json.dumps(_prepare_action_for_host(event_action, root), ensure_ascii=False))
            return
        try:
            orch = TickOrchestrator.restore(root, store, checkpoint_id=checkpoint_id)
        except Exception:
            # T160: checkpoint_id 未直接命中 → 尝试作为 thread_id 搜索
            resolved = _resolve_checkpoint_by_thread_id(checkpoint_id, store)
            if resolved is None:
                raise
            _logger = __import__("logging").getLogger("ae.cli")
            _logger.info("resume: '%s' 未直接命中 checkpoint，通过 thread_id 回退到 %s",
                         checkpoint_id, resolved)
            orch = TickOrchestrator.restore(root, store, checkpoint_id=resolved)
        action = orch.build_action()
        click.echo(json.dumps(_prepare_action_for_host(action, root), ensure_ascii=False))
    finally:
        events.close()
        store.close()


def run_action_supervisor(root: Path) -> None:
    """以一次用户启动自动驱动 active thread 到等待或终态。"""
    import json

    import click

    from auto_engineering.config.runtime_config import RuntimeConfig
    from auto_engineering.host import HostPlatform, detect_host
    from auto_engineering.host.backends import (
        ClaudeInvocationBackend,
        CodexInvocationBackend,
    )
    from auto_engineering.host.invocation import (
        ActionExecutionContractError,
        HostInvocationBackend,
    )
    from auto_engineering.host.request_compiler import (
        compile_action_execution_request,
    )
    from auto_engineering.host.runtime_driver import HostRunLeaseStore
    from auto_engineering.host.supervisor import (
        ActionReceiptJournal,
        ActionScopedProductDriver,
        LoopStopReportJournal,
        MachineOperationExecutor,
        ProductEvidenceArtifactJournal,
    )
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore

    root = root.resolve()
    runtime_config = RuntimeConfig.from_project(root)
    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(
        _ensure_checkpoint_db_path(root)
    )
    events = SQLiteEventStore(_ensure_event_db_path(root))
    try:
        thread_id = _active_thread(store)
        if thread_id is None:
            raise click.ClickException("PROJECT_THREAD_NOT_ACTIVE")
        canonical = events.load_action_snapshot(thread_id)
        if canonical is None:
            canonical = store.load_active_protocol_action(thread_id)
        if canonical is None:
            raise click.ClickException("ACTIVE_ACTION_MISSING")
        try:
            action = _prepare_action_for_host(canonical, root, compact_view=False)
        except Exception as exc:
            # 初始 Action 投影失败也必须留下机器可读的停止事实，不能让前台只看到
            # Supervisor 进程退出而没有 ERROR Action 或可诊断报告。
            message = str(exc)
            error_code = (
                "OUTCOME_JOURNAL_CONFLICT"
                if "OUTCOME_JOURNAL_CONFLICT" in message
                else "HOST_ACTION_PREPARATION_FAILED"
            )
            failure_action = _project_host_failure_action(
                canonical,
                error_code=error_code,
                message=message or error_code,
            )
            stop_report = LoopStopReportJournal(root).record(
                thread_id=thread_id,
                final_action=failure_action,
            )
            click.echo(f"Loop 停止报告已生成: {stop_report}", err=True)
            raise
    finally:
        events.close()
        store.close()

    lease_store = HostRunLeaseStore(root)
    receipt_journal = ActionReceiptJournal(root)
    detection = detect_host()
    def report_context_progress(elapsed_seconds: float) -> None:
        click.echo(
            f"[宿主心跳] 当前 Action context 已运行 {int(elapsed_seconds)} 秒",
            err=True,
        )

    try:
        if detection.platform is HostPlatform.CODEX:
            backend: HostInvocationBackend = CodexInvocationBackend(
                progress_callback=report_context_progress,
            )
        elif detection.platform is HostPlatform.CLAUDE_CODE:
            backend = ClaudeInvocationBackend(
                spent_budget_usd=receipt_journal.total_cost_usd(thread_id),
                progress_callback=report_context_progress,
            )
        else:
            raise click.ClickException("HOST_ACTION_CONTEXT_UNAVAILABLE: HOST_UNKNOWN")
    except Exception:
        # _prepare_action_for_host 已建立 CONTINUE lease；入口能力/构造失败时也必须
        # 回收它，否则下一次宿主会被一个从未执行的旧 Action 锁死。
        lease_store.clear()
        raise
    bundled_runner = Path(__file__).resolve().parents[2] / "scripts" / "ae-run"
    # Action 子进程必须只使用已安装运行时；清除开发会话注入的 Python 路径，
    # 防止真跑时误加载当前源码目录或宿主虚拟环境。
    child_environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
    }
    child_environment["AE_HOST_ACTION_VIEW"] = "full"
    operation_executor = MachineOperationExecutor(
        project_root=root,
        bundled_runner=bundled_runner,
        environ=child_environment,
    )
    click.echo(
        f"[宿主监督] 已接管 Action {action.get('message_id', 'unknown')} "
        f"(stage={action.get('stage', 'unknown')})",
        err=True,
    )
    def record_receipt(request: Any, receipt: Any) -> None:
        receipt_journal.record(request, receipt)

    def compile_request(mapped_action: Mapping[str, Any]):
        compact = _compact_host_action(mapped_action, root)
        allowed_tools = ["read", "shell", "native_subagents"]
        if mapped_action.get("stage") in {"project_setup", "developer"}:
            allowed_tools.append("edit")
        return compile_action_execution_request(
            mapped_action,
            compact_envelope=compact,
            project_root=root,
            allowed_tools=allowed_tools,
        )

    def submit_failure(
        mapped_action: Mapping[str, Any],
        receipt: Any,
    ) -> dict[str, Any]:
        host_execution = mapped_action.get("host_execution")
        operations = (
            host_execution.get("operations")
            if isinstance(host_execution, Mapping)
            else None
        )
        work_files = (
            host_execution.get("work_files")
            if isinstance(host_execution, Mapping)
            else None
        )
        result_ref = (
            work_files.get("result")
            if isinstance(work_files, Mapping)
            else None
        )
        if not isinstance(operations, Mapping) or not isinstance(result_ref, str):
            raise click.ClickException("HOST_FAILURE_SUBMISSION_CONTRACT_MISSING")
        failure_code = _host_context_failure_code(
            receipt.status,
            receipt.error_code,
        )
        result_payload: dict[str, Any] = {
            "schema_version": "1.1",
            "message_type": "result",
            "message_id": f"failure-{receipt.host_context_id}",
            "thread_id": mapped_action.get("thread_id"),
            "tick": mapped_action.get("tick"),
            "stage": mapped_action.get("stage"),
            "causation_id": mapped_action.get("message_id"),
            "correlation_id": mapped_action.get("correlation_id"),
            "extensions": {},
            "spawned": False,
            "spawn_error_code": failure_code,
            "spawn_error": receipt.error_code or failure_code,
        }
        result_path = _root_bound_path(Path(result_ref), root)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            result_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        temporary = result_path.with_suffix(result_path.suffix + ".failure.tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, result_path)
        return operation_executor.validate_and_submit(operations)

    try:
        result = ActionScopedProductDriver(
            backend,
            compile_request=compile_request,
            execute_operations=operation_executor.run,
            submit_failure=submit_failure,
            receipt_sink=record_receipt,
            max_elapsed_seconds=runtime_config.host_max_elapsed_seconds,
            max_total_cost_usd=runtime_config.host_max_cost_usd,
            max_total_output_tokens=runtime_config.host_max_output_tokens,
        ).run(action)
    except ActionExecutionContractError as exc:
        error_code = str(exc).partition(":")[0] or type(exc).__name__
        failure_action = _project_host_failure_action(
            action,
            error_code=error_code,
            message=error_code,
        )
        stop_report = LoopStopReportJournal(root).record(
            thread_id=thread_id,
            final_action=failure_action,
        )
        click.echo(f"Loop 停止报告已生成: {stop_report}", err=True)
        raise
    except Exception as exc:
        # 未预期的宿主/协议异常也必须在边界被归一化。否则 CLI 会直接冒出
        # Python traceback，且没有稳定 Stop Report，下一次恢复只能猜测现场。
        failure_action = _project_host_failure_action(
            action,
            error_code="HOST_SUPERVISOR_PROTOCOL_ERROR",
            message="HOST_SUPERVISOR_PROTOCOL_ERROR",
        )
        stop_report = LoopStopReportJournal(root).record(
            thread_id=thread_id,
            final_action=failure_action,
        )
        click.echo(f"Loop 停止报告已生成: {stop_report}", err=True)
        raise ActionExecutionContractError(
            "HOST_SUPERVISOR_PROTOCOL_ERROR"
        ) from exc
    finally:
        # 只要本次 supervise 已结束，旧 CONTINUE lease 就不能继续阻断宿主。
        # 下一次返回的 CONTINUE Action 会在 _prepare_action_for_host 中重新建立。
        lease_store.clear()
    stop_report = LoopStopReportJournal(root).record(
        thread_id=thread_id,
        final_action=result.final_action,
    )
    click.echo(f"Loop 停止报告已生成: {stop_report}", err=True)
    if result.final_action.get("action") == "done":
        terminal_events = SQLiteEventStore(_ensure_event_db_path(root))
        try:
            event_types = tuple(
                event.event_type.value
                for event in terminal_events.load_stream(thread_id)
            )
        finally:
            terminal_events.close()
        artifact = ProductEvidenceArtifactJournal(
            root,
            runtime_root=Path(__file__).resolve().parents[2],
        ).record_terminal(
            host=detection.platform.value,
            thread_id=thread_id,
            final_action=result.final_action,
            event_types=event_types,
        )
        click.echo(f"产品证据已生成: {artifact}", err=True)
    click.echo(json.dumps(result.final_action, ensure_ascii=False))


def _project_host_failure_action(
    action: Mapping[str, Any],
    *,
    error_code: str,
    message: str,
) -> dict[str, Any]:
    """把宿主边界异常投影为可持久化、可诊断的 ERROR Action。"""

    extensions = dict(action.get("extensions") or {})
    ae_extension = dict(extensions.get("ae") or {})
    ae_extension["execution_control"] = {
        "schema_version": "1.0",
        "disposition": "ERROR",
        "continuation_required": False,
        "yield_allowed": True,
        "allowed_stop_reasons": ["fatal_error"],
        "reason_code": error_code,
    }
    extensions["ae"] = ae_extension
    return {
        **dict(action),
        "action": "error",
        "error_code": error_code,
        "message": message,
        "extensions": extensions,
    }


def _host_context_failure_code(status: str, error_code: str | None) -> str:
    """把宿主实现细节归一化为 Core 可判定的控制结果。"""
    if status == "timed_out":
        return "HOST_ACTION_CONTEXT_TIMEOUT"
    if error_code in {
        "HOST_CODEX_USAGE_LIMIT",
        "HOST_CLAUDE_BUDGET_EXHAUSTED",
    }:
        return "HOST_ACTION_CONTEXT_RESOURCE_EXHAUSTED"
    return "HOST_ACTION_CONTEXT_FAILED"


def _resolve_checkpoint_by_thread_id(
    candidate: str, store: SQLiteCheckpointStore[EngineState]
) -> str | None:
    """按 thread_id 反查 checkpoint id (T160 resume 回退).

    2026-07-26 审计修复 (P1-10): 原实现 getattr(store, "_db") 访问私有属性,
    内部属性改名即静默返回 None → 误导性 CheckpointNotFoundError。
    改走公开 API SQLiteCheckpointStore.find_by_thread_id()。
    """
    try:
        return store.find_by_thread_id(candidate)
    except (OSError, ValueError, KeyError, TypeError) as e:
        _logger = __import__("logging").getLogger("ae.cli")
        _logger.debug("thread_id fallback lookup failed: %s", e)
        return None
