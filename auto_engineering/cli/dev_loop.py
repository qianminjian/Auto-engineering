"""CLI dev_loop — v5.6 离散 Tick 模式。

从 cli.py 拆分 (Plan P1-B, 原 cli.py §218-451).
v5.5 Orchestrator 已退役 (T133b).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from auto_engineering.cli.action_status import (
    status_action_summary as _status_action_summary,
)
from auto_engineering.cli.active_action_source import (
    active_thread as _active_thread_impl,
)
from auto_engineering.cli.active_action_source import (
    load_active_action as _load_active_action_impl,
)
from auto_engineering.cli.compact_action_view import (
    compact_host_action as _compact_host_action_impl,
)
from auto_engineering.cli.host_action_binding import (
    map_bound_action_for_host as _map_bound_action_for_host_impl,
)
from auto_engineering.cli.host_action_runtime import (
    bind_worker_execution_identity as _bind_worker_execution_identity_impl,
)
from auto_engineering.cli.host_action_runtime import (
    map_action_for_host as _map_action_for_host_impl,
)
from auto_engineering.cli.host_action_runtime import (
    prepare_action_for_host as _prepare_action_for_host_impl,
)
from auto_engineering.cli.host_action_runtime import (
    resume_host_platform as _resume_host_platform_impl,
)
from auto_engineering.cli.host_action_runtime import (
    resume_platform_scope as _resume_platform_scope,
)
from auto_engineering.cli.host_action_runtime import (
    root_bound_path as _root_bound_path_impl,
)
from auto_engineering.cli.legacy_action_recovery import (
    host_mapping_error_action as _host_mapping_error_action_impl,
)
from auto_engineering.cli.legacy_action_recovery import (
    persist_legacy_action_recovery_gate as _persist_legacy_action_recovery_gate,
)
from auto_engineering.cli.legacy_action_recovery import (
    persisted_reconciliation_gate_status as _persisted_reconciliation_gate_status,
)
from auto_engineering.cli.result_recovery_projection import (
    process_state_reconciliation_result as _process_state_reconciliation_result_impl,
)
from auto_engineering.cli.result_recovery_projection import (
    project_host_attestation_repair_action as _project_host_attestation_repair_action_impl,
)
from auto_engineering.cli.result_recovery_projection import (
    project_result_repair_action as _project_result_repair_action_impl,
)
from auto_engineering.cli.result_recovery_projection import (
    project_submitted_worker_failure_recovery as _project_submitted_worker_failure_recovery_impl,
)
from auto_engineering.cli.result_recovery_projection import (
    record_outcome_acceptance as _record_outcome_acceptance_impl,
)
from auto_engineering.config.runtime_config import RuntimeConfig, get_default_config
from auto_engineering.engine.state import EngineState

if TYPE_CHECKING:
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import EffectReceipt, SQLiteEventStore
    from auto_engineering.loop.events import LoopEvent

_logger = logging.getLogger(__name__)
_STATE_GITIGNORE = "*\n!.gitignore\n"


def _write_json_atomically(path: Path, payload: object) -> None:
    """以同目录临时文件替换 Coordinator 产物，避免半写 JSON 被采集。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


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
# 每次调用是独立进程；新运行从 .ae-state/events.db 恢复，checkpoint 仅作显式迁移输入。
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
    return _root_bound_path_impl(path, root)


def _cleanup_completed_action_work_files(
    *,
    root: Path,
    result_file: Path,
    completed_action: Mapping[str, object] | None,
    next_action: Mapping[str, object],
    commit_confirmed: bool = True,
) -> None:
    """仅在 Core 确认提交后删除 Action 临时交接文件。"""

    if not commit_confirmed or completed_action is None:
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
    # 私有 Worker 产出按当前 Action/generation 精确清理；旧/未知文件保留审计。
    private_paths: set[Path] = set()
    try:
        mapped = _map_bound_action_for_host(
            dict(completed_action), root, include_failure_journal=False
        )
        host_execution = mapped.get("host_execution")
        workers = (
            host_execution.get("workers")
            if isinstance(host_execution, Mapping)
            else None
        )
        if isinstance(workers, list):
            private_paths.update(
                _root_bound_path(Path(str(worker["outcome_path"])), root)
                for worker in workers
                if isinstance(worker, Mapping)
                and isinstance(worker.get("outcome_path"), str)
            )
    except Exception:
        _logger.debug("generation-bound worker artifact cleanup skipped", exc_info=True)
    try:
        from auto_engineering.host.spawn_contract import SpawnPlan

        plan = SpawnPlan.from_action(completed_action)
        for invocation in plan.invocations:
            private_paths.add(_root_bound_path(Path(invocation.outcome_path), root))
    except Exception:
        # 清理失败不影响状态提交；旧/损坏 Action 保留未知文件供审计。
        _logger.debug("worker private artifact cleanup skipped", exc_info=True)
    for private_path in private_paths:
        if private_path.is_relative_to(root):
            with suppress(FileNotFoundError):
                private_path.unlink()
    with suppress(OSError):
        work_dir.rmdir()

def _map_action_for_host(action: dict) -> dict:
    return _map_action_for_host_impl(action)


def _bind_worker_execution_identity(
    action: dict,
    root: Path,
    *,
    include_failure_journal: bool = True,
) -> dict:
    return _bind_worker_execution_identity_impl(
        action,
        root,
        include_failure_journal=include_failure_journal,
    )


def _map_bound_action_for_host(
    action: dict,
    root: Path,
    *,
    include_failure_journal: bool = True,
) -> dict:
    return _map_bound_action_for_host_impl(
        action,
        root,
        include_failure_journal=include_failure_journal,
        bind_worker_execution_identity_fn=_bind_worker_execution_identity,
        map_action_fn=_map_action_for_host,
    )


def _prepare_action_for_host(
    action: dict,
    root: Path,
    *,
    compact_view: bool | None = None,
    include_failure_journal: bool = True,
) -> dict:
    return _prepare_action_for_host_impl(
        action,
        root,
        compact_view=compact_view,
        include_failure_journal=include_failure_journal,
        bind_worker_execution_identity_fn=_bind_worker_execution_identity,
        map_action_fn=_map_action_for_host,
        project_host_attestation_repair_action=_project_host_attestation_repair_action,
        compact_action=_compact_host_action,
    )


def _compact_host_action(action: Mapping[str, Any], root: Path) -> dict[str, Any]:
    return _compact_host_action_impl(action, root)

def _active_thread(store: object) -> str | None:
    return _active_thread_impl(store)


def _load_active_action(
    thread_id: str,
    store: _ActiveThreadStore,
    events: _ActiveThreadEvents,
) -> dict | None:
    return _load_active_action_impl(thread_id, store, events)


def _state_source_conflict_action(thread_id: str) -> dict[str, Any]:
    """把状态源分叉投影成宿主可处理的协议错误。"""

    from auto_engineering.loop.actions import ActionError
    from auto_engineering.loop.protocol import action_envelope

    return action_envelope(
        ActionError(
            error_code="STATE_SOURCE_CONFLICT",
            message="事件与兼容 checkpoint 指向不同的活动 Action，已停止继续执行。",
            suggestion="保留 .ae-state，核对事件日志后使用正确的恢复操作；不要手工拼接两份状态。",
        ).to_dict(),
        thread_id=thread_id,
        tick=0,
        stage=None,
    )


def _state_reconciliation_result_contract() -> dict[str, Any]:
    """返回状态协调 Gate 的唯一宿主 Result 合同。"""

    return {
        "schema_version": "1.0",
        "required": ["gate_resolution"],
        "properties": {"gate_resolution": {"type": "object"}},
        "additionalProperties": False,
    }


def _state_reconciliation_expected_format() -> dict[str, Any]:
    """返回供宿主/模型直接照抄的状态协调字段形状。"""

    return {
        "gate_resolution": {
            "gate_id": "state_reconciliation",
            "resolution": "reinitialize | reconcile",
        },
    }


def _design_source_error_action(
    thread_id: str, error: ValueError,
) -> dict[str, Any]:
    """把设计账本漂移投影成稳定协议错误，阻止恢复路径抛 traceback。"""

    from auto_engineering.loop.actions import ActionError
    from auto_engineering.loop.protocol import action_envelope

    return action_envelope(
        ActionError(
            error_code=str(error) or "DESIGN_LEDGER_INVALID",
            message="当前状态绑定的设计来源已变化，已停止继续执行。",
            suggestion="请确认设计文档和状态版本后重新初始化，或通过显式迁移边界恢复。",
        ).to_dict(),
        thread_id=thread_id,
        tick=0,
        stage=None,
    )


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
    active_action = _load_active_action(thread_id, store, events)
    intent = InvocationIntent.from_design_doc(root, design_doc_path)
    resolution = ProjectProfileResolver((
        AeConfigProvider(),
        LocalProbeProvider(),
        LegacyInitProvider(),
    )).resolve(
        root,
        design_doc_path=design_doc_path,
        require_test_command=False,
    )
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
            "project_root": str(root.resolve()),
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
            "instruction": (
                "这是用户决策 Gate。必须原样展示 gate.options，等待用户选择后，"
                "仅提交 gate_resolution 对象；禁止提交顶层 decision、gate_id 或 decision 字段。"
                "gate_resolution.gate_id 必须为 state_reconciliation，"
                "resolution 必须使用选项 id；Result 的 causation_id 必须绑定当前 Gate message_id。"
            ),
            "expected_format": _state_reconciliation_expected_format(),
            "result_contract": _state_reconciliation_result_contract(),
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


def _activate_project_config(root: Path) -> None:
    """刷新本进程配置快照；缺失或仅含 ProjectProfile 时使用默认值。"""
    from auto_engineering.config.runtime_config import (
        RuntimeConfig,
        set_default_config,
    )

    set_default_config(RuntimeConfig.from_project(root))


def run_tick_init(
    requirement: str, design_doc_path: str | None, root: Path, max_rounds: int | None,
    debug: bool = False, debug_dir: str | None = None,
    pause_at_stage: str | None = None,
    escalate: bool = False,
) -> None:
    """ae dev-loop --init: 初始化 tick loop, 输出第一个 action JSON (stdout 契约)."""
    import click

    if requirement.lower().endswith((".md", ".markdown")) and (root / requirement).is_file():
        raise click.ClickException("DESIGN_DOC_REQUIRED: 请将设计文档路径通过 --design-doc 传入，"
                                   f"requirement 请改为自然语言需求（--design-doc {requirement}）")
    # RuntimeConfig 读取可选的 ae.toml 覆盖；缺失时直接使用 FeatureManifest 默认值。
    # ProjectProfile 的 [project] 与运行时 Feature 配置共享文件但职责独立，不能互相阻断。
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
            try:
                existing_action = _resolve_active_thread_start(
                    root=root,
                    design_doc_path=design_doc_path,
                    store=store,
                    events=events,
                )
            except ValueError as exc:
                if str(exc) != "STATE_SOURCE_CONFLICT":
                    raise
                click.echo(
                    json.dumps(
                        _state_source_conflict_action(
                            _active_thread(store) or reserved_thread_id
                        ),
                        ensure_ascii=False,
                    )
                )
                return
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
    from auto_engineering.loop.design_decision_ledger import DesignDecisionError
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
        try:
            completed_action = (
                _load_active_action(active_thread, store, events)
                if active_thread is not None
                else None
            )
        except ValueError as exc:
            if str(exc) != "STATE_SOURCE_CONFLICT" or active_thread is None:
                raise
            click.echo(
                json.dumps(
                    _state_source_conflict_action(active_thread),
                    ensure_ascii=False,
                )
            )
            return
        # 宿主先提交 Worker 失败而漏掉 attestation 回写时，先检查当前 Action
        # 的私有业务 artifact。合法产物意味着“回写缺失”，不是 Worker 失败；
        # 在 Core tick 前投影修复 Action，避免错误消耗失败预算或重启 Worker。
        if completed_action is not None:
            try:
                submitted_candidate = json.loads(
                    result_file.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                submitted_candidate = None
            if isinstance(submitted_candidate, Mapping):
                attestation_recovery = _project_submitted_worker_failure_recovery(
                    action=completed_action,
                    submitted_result=submitted_candidate,
                    root=root,
                )
                if attestation_recovery is not None:
                    click.echo(
                        json.dumps(attestation_recovery, ensure_ascii=False)
                    )
                    return
        # 新运行始终通过 EventStore 恢复；事件投影缺失必须让 restore 明确失败，
        # 不能退回 checkpoint 形成第二套事实源。
        if active_thread is None:
            raise click.ClickException(
                "EVENT_THREAD_NOT_FOUND: 没有可恢复的 EventStore 活动 thread；"
                "历史 checkpoint 必须先通过 --import-checkpoint 显式导入"
            )
        try:
            orch = TickOrchestrator.restore_from_event_store(
                root, store, debug=debug, debug_dir=debug_dir,
                event_store=events,
                thread_id=active_thread,
                context_offloader=inj["context_offloader"],
                session_summarizer=inj.get("session_summarizer"),
                tracer=inj["tracer"],
                audit_logger=inj["audit_logger"],
            )
        except DesignDecisionError as exc:
            click.echo(json.dumps(
                _prepare_action_for_host(
                    _design_source_error_action(active_thread, exc), root
                ),
                ensure_ascii=False,
            ))
            return

        # T69a: Restore metrics collector from disk for cross-process continuity
        if get_default_config().metrics_enabled:
            from auto_engineering.metrics.collector import (
                MetricsCollector,
                set_collector,
            )
            collector = MetricsCollector(root)
            set_collector(collector)
            collector.resume_events(orch.state_snapshot().thread_id)

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
            state = orch.state_snapshot()
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
        active_action = orch.active_action_snapshot()
        persisted_rejection = False
        if active_action is not None and action.get("action") == "error":
            # ``--validate-result`` 与 ``--tick`` 可能连续消费同一 Result。
            # 前者已经把候选记录为 rejected，后者仍必须返回同一 Action 的
            # repair 投影；不能因 journal 不再是 prepared 就把结构化错误
            # 降级成宿主无法继续执行的裸 error。
            from auto_engineering.host.outcome_journal import OutcomeJournal

            journal_record = OutcomeJournal(root).load(
                str(active_action.get("message_id", ""))
            )
            persisted_rejection = (
                isinstance(journal_record, Mapping)
                and journal_record.get("status") == "rejected"
            )
        if (
            active_action is not None
            and action.get("action") == "error"
            and (
                candidate_rejected
                or persisted_rejection
                or (
                    action.get("error_code") == "ARCHITECT_PLAN_INVALID"
                    and active_action.get("stage") == "architect"
                )
            )
        ):
            action = _project_result_repair_action(
                active_action, action
            )
        _cleanup_completed_action_work_files(
            root=root,
            result_file=result_file,
            completed_action=completed_action,
            next_action=action,
            commit_confirmed=(
                action.get("action") != "error" and not candidate_rejected
            ),
        )
        if (
            action.get("action") == "done"
        ):
            state = orch.state_snapshot()
            store.release_project_thread(state.thread_id)
            # 终态必须在事件流中留下机器事实，供产品证据门禁核验。
            # append_new 具备严格序列分配；幂等检查避免宿主重复提交时重复记录。
            if not any(
                event.event_type.value == "LoopCompleted"
                for event in events.load_stream(state.thread_id)
            ):
                from auto_engineering.loop.events import LoopEventType

                events.append_new(
                    thread_id=state.thread_id,
                    event_type=LoopEventType.LOOP_COMPLETED,
                    payload={
                        "action": "done",
                        "verdict": action.get("verdict"),
                        "tick": action.get("tick", state.tick),
                    },
                    correlation_id=state.thread_id,
                    causation_id=action.get("message_id"),
                )

        # T69a: Flush metrics events after tick, end requirement if terminal
        if get_default_config().metrics_enabled:
            from auto_engineering.metrics.collector import get_collector
            mc = get_collector()
            if mc is not None:
                if action.get("action") == "done":
                    verdict = action.get("verdict", "UNKNOWN")
                    total_ticks = action.get("tick", orch.state_snapshot().tick)
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
    return _record_outcome_acceptance_impl(
        root=root,
        submitted_result_file=submitted_result_file,
        core_response=core_response,
    )


def _project_result_repair_action(
    active_action: Mapping[str, Any],
    core_response: Mapping[str, Any],
) -> dict[str, Any]:
    return _project_result_repair_action_impl(
        active_action,
        core_response,
        state_reconciliation_expected_format=_state_reconciliation_expected_format,
        state_reconciliation_result_contract=_state_reconciliation_result_contract,
    )


def _project_host_attestation_repair_action(
    mapped_action: Mapping[str, Any],
    *,
    worker_id: str,
    detail: str,
) -> dict[str, Any]:
    return _project_host_attestation_repair_action_impl(
        mapped_action,
        worker_id=worker_id,
        detail=detail,
        project_result_repair_action_fn=_project_result_repair_action,
    )


def _project_submitted_worker_failure_recovery(
    *,
    action: Mapping[str, Any] | None,
    submitted_result: Mapping[str, Any],
    root: Path,
) -> dict[str, Any] | None:
    return _project_submitted_worker_failure_recovery_impl(
        action=action,
        submitted_result=submitted_result,
        root=root,
        map_bound_action_fn=_map_bound_action_for_host,
        root_bound_path_fn=_root_bound_path,
        project_host_attestation_repair_action_fn=(
            _project_host_attestation_repair_action
        ),
    )


def _process_state_reconciliation_result(
    *,
    result_file: Path,
    root: Path,
    store: SQLiteCheckpointStore[EngineState],
    events: SQLiteEventStore,
    debug: bool = False,
    debug_dir: str | None = None,
) -> dict | None:
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    return _process_state_reconciliation_result_impl(
        result_file=result_file,
        root=root,
        store=store,
        events=events,
        debug=debug,
        debug_dir=debug_dir,
        build_injectables_fn=_build_injectables,
        tick_orchestrator_cls=TickOrchestrator,
    )


def run_tick_validate(result_file: Path, root: Path) -> None:
    """预校验 Result；不推进状态，也不生成新的协议记录。"""
    import json

    import click

    from auto_engineering.cli.result_recovery_projection import validate_state_reconciliation_result_file
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.design_decision_ledger import DesignDecisionError
    from auto_engineering.loop.event_store import SQLiteEventStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    result_file = _root_bound_path(result_file, root)
    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(
        _ensure_checkpoint_db_path(root)
    )
    events = SQLiteEventStore(_ensure_event_db_path(root))
    try:
        active_thread = _active_thread(store)
        # EventStore 是唯一运行事实源；checkpoint 只在显式 import 入口消费。
        if active_thread is None:
            raise click.ClickException(
                "EVENT_THREAD_NOT_FOUND: 没有可恢复的 EventStore 活动 thread；"
                "历史 checkpoint 必须先通过 --import-checkpoint 显式导入"
            )
        reconciliation_validation = validate_state_reconciliation_result_file(
            result_file=result_file, active_thread=active_thread, events=events)
        if reconciliation_validation is not None:
            click.echo(json.dumps(reconciliation_validation, ensure_ascii=False))
            if reconciliation_validation.get("action") == "error":
                raise SystemExit(1)
            return
        try:
            orch = TickOrchestrator.restore_from_event_store(
                root,
                store,
                event_store=events,
                thread_id=active_thread,
            )
        except DesignDecisionError as exc:
            click.echo(json.dumps(
                _design_source_error_action(active_thread, exc),
                ensure_ascii=False,
            ))
            return
        result = orch.validate_result_file(result_file)
        if result.get("action") == "error":
            candidate_rejected = _record_outcome_acceptance(
                root=root,
                submitted_result_file=result_file,
                core_response=result,
            )
            active_action = orch.active_action_snapshot()
            if candidate_rejected and active_action is not None:
                repair = _project_result_repair_action(
                    active_action, result
                )
                click.echo(json.dumps(
                    _prepare_action_for_host(
                        repair, root, include_failure_journal=False
                    ),
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
        try:
            action = _load_active_action(thread_id, store, events)
        except ValueError as exc:
            if str(exc) != "STATE_SOURCE_CONFLICT":
                raise
            click.echo(
                json.dumps(
                    _state_source_conflict_action(thread_id),
                    ensure_ascii=False,
                )
            )
            return
        if action is None:
            raise click.ClickException("ACTIVE_ACTION_MISSING")
        mapped_action = _map_bound_action_for_host(
            action, root, include_failure_journal=False
        )
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
                # 所有 Action 都只认当前 canonical work_files。即使文件尚未
                # 创建，也不能以“兼容旧调用者”为由回退到宿主传入的旧路径；
                # 缺文件必须进入当前 Action 的有界失败/输入错误分支。
                coordinator_path = current_coordinator
                if isinstance(current_result_ref, str):
                    result_path = _root_bound_path(Path(current_result_ref), root)
                if (
                    isinstance(mapped_action.get("spawn"), Mapping)
                    and isinstance(current_outcomes_ref, str)
                ):
                    outcomes_path = _root_bound_path(
                        Path(current_outcomes_ref), root
                    )
            # Worker 的私有 outcome_path 与 Action 共享 outcomes 是两个不同边界。
            # 宿主误把前者传给 Finalizer 时，仍必须以 active Action 的 canonical
            # work_files 为唯一事实源，不能读取私有业务文件冒充已交接的宿主事实。
            if isinstance(mapped_action.get("spawn"), Mapping):
                if isinstance(current_outcomes_ref, str):
                    outcomes_path = _root_bound_path(
                        Path(current_outcomes_ref), root
                    )
                if isinstance(current_result_ref, str):
                    result_path = _root_bound_path(
                        Path(current_result_ref), root
                    )
        input_error: str | None = None
        outcomes_error: str | None = None
        coordinator_error: str | None = None
        collection_error_code: str | None = None
        collection_error_worker_id: str | None = None
        raw_outcomes: object = []
        coordinator_payload: object = {}
        try:
            raw_outcomes = (
                json.loads(outcomes_path.read_text(encoding="utf-8"))
                if outcomes_path is not None
                else []
            )
        except (OSError, json.JSONDecodeError) as exc:
            outcomes_error = (
                "Worker outcomes 不可读取或不是合法 JSON: "
                f"{exc.__class__.__name__}"
            )
        try:
            coordinator_payload = json.loads(
                coordinator_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            coordinator_error = (
                "Coordinator payload 不可读取或不是合法 JSON: "
                f"{exc.__class__.__name__}"
            )
        outcome_items = (
            raw_outcomes.get("outcomes")
            if isinstance(raw_outcomes, dict)
            else raw_outcomes
        )
        is_spawn_action = isinstance(mapped_action.get("spawn"), Mapping)
        if not isinstance(outcome_items, list):
            outcomes_error = outcomes_error or (
                "Worker outcomes 顶层必须是 JSON object 或数组"
            )
        if not isinstance(coordinator_payload, dict):
            coordinator_error = coordinator_error or (
                "Coordinator payload 顶层必须是 JSON object"
            )
        if is_spawn_action and (
            not isinstance(outcome_items, list) or not outcome_items
        ):
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
                outcomes_error = None
            except WorkerOutcomeCollectionError as exc:
                collection_error_code = exc.code
                collection_error_worker_id = exc.worker_id
                outcomes_error = str(exc)

        # 单 Worker 的 Coordinator 可能在宿主上下文退出前尚未来得及写文件。
        # 只在已收集到一个合法 completed WorkerArtifact 时从其业务 payload
        # 恢复 Coordinator 输入；多 Worker 仍必须由 Coordinator 显式合并。
        if (
            is_spawn_action
            and outcomes_error is None
            and isinstance(outcome_items, list)
            and len(outcome_items) == 1
            and isinstance(outcome_items[0], Mapping)
            and outcome_items[0].get("status") == "completed"
            and coordinator_error is not None
        ):
            recovered_payload = outcome_items[0].get("payload")
            if isinstance(recovered_payload, dict):
                coordinator_payload = dict(recovered_payload)
                coordinator_error = None
                if coordinator_path is not None:
                    _write_json_atomically(coordinator_path, coordinator_payload)

        if not is_spawn_action:
            input_error = coordinator_error or outcomes_error
        else:
            input_error = outcomes_error or coordinator_error
            if input_error is None and not outcome_items:
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
            if (
                is_spawn_action
                and collection_error_code == "HOST_WORKER_ATTESTATION_MISSING"
                and collection_error_worker_id is not None
            ):
                # 私有业务产物已经存在；这不是 Worker 的失败事实。保留
                # active Action 并进入宿主事实修复态，防止 Core 推进失败
                # 代际后重新 spawn，丢失仍可复用的原生 Worker 结果。
                repair = _project_host_attestation_repair_action(
                    mapped_action,
                    worker_id=collection_error_worker_id,
                    detail=outcomes_error or "private_business_artifact_only",
                )
                output = (
                    _compact_host_action(repair, root)
                    if os.environ.get("AE_HOST_ACTION_VIEW", "").strip().lower()
                    == "compact"
                    else repair
                )
                click.echo(json.dumps(output, ensure_ascii=False))
                return
            # Spawn Action 的空/损坏交接文件代表 Worker 失败，而不是 CLI
            # 参数错误。生成带明确 unreported 哨兵的失败事务，让 Core 按
            # 失败预算自动重试；inline Action 仍保持严格输入错误。
            if isinstance(mapped_action.get("spawn"), Mapping):
                assembler = HostExecutionAssembler(root)
                failure_detail = input_error
                failure_code = (
                    collection_error_code
                    or (
                        "HOST_WORKER_OUTPUT_MISSING"
                        if not outcomes
                        else "HOST_WORKER_OUTPUT_INVALID"
                    )
                )
                if failure_code == "HOST_WORKER_OUTPUT_MISSING":
                    # 缺失/空交接是同一个可重试事实；不能因为首次是
                    # FileNotFound、第二次是空 JSON 而生成不同 fingerprint，
                    # 否则失败预算会永远从 1 开始。
                    failure_detail = "Worker 未产生可验证的私有 outcome"
                result = assembler.finalize_missing_worker_output(
                    action=mapped_action,
                    reason_code=failure_code,
                    detail=failure_detail,
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
                outcomes=[item.to_dict() for item in outcomes],
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
                _prepare_action_for_host(
                    repair_action, root, include_failure_journal=False
                ),
                ensure_ascii=False,
            ))
            return
        click.echo(json.dumps(result, ensure_ascii=False))
    finally:
        events.close()
        store.close()


def run_record_worker_outcome(
    *,
    root: Path,
    worker_id: str,
    native_worker_handle: str | None,
    native_result_file: Path | None,
    native_result_stdin: bool,
    worker_status: str,
    actual_model: str,
    isolation_evidence: str | None,
) -> None:
    """接收宿主原生 Worker 事实并原子写入当前 Action 的共享 outcomes。"""

    import click

    from auto_engineering.host.execution_assembler import (
        HostEvidenceValidationError,
        HostExecutionAssembler,
    )
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(
        _ensure_checkpoint_db_path(root)
    )
    events = SQLiteEventStore(_ensure_event_db_path(root))
    try:
        thread_id = _active_thread(store)
        if thread_id is None:
            raise click.ClickException("PROJECT_THREAD_NOT_ACTIVE")
        try:
            action = _load_active_action(thread_id, store, events)
        except ValueError as exc:
            if str(exc) != "STATE_SOURCE_CONFLICT":
                raise
            click.echo(json.dumps(
                _state_source_conflict_action(thread_id), ensure_ascii=False
            ))
            return
        if action is None:
            raise click.ClickException("ACTIVE_ACTION_MISSING")
        mapped_action = _map_bound_action_for_host(
            action, root, include_failure_journal=False
        )
        assembler = HostExecutionAssembler(root)
        bound_native_result_file = (
            _root_bound_path(native_result_file, root)
            if native_result_file is not None else None
        )
        try:
            if native_result_stdin and bound_native_result_file is not None:
                # stdin 是宿主原生工具返回 envelope 的传输通道；不把它作为
                # shell 参数解析，也不在这里重编码，避免真实回包丢失或漂移。
                raw_envelope = b"" if sys.stdin.isatty() else sys.stdin.buffer.read()
                if raw_envelope.strip():
                    assembler.stage_native_result(
                        action=mapped_action,
                        worker_id=worker_id,
                        native_result_file=bound_native_result_file,
                        raw_envelope=raw_envelope,
                    )
            outcome = assembler.record_worker_outcome(
                action=mapped_action,
                worker_id=worker_id,
                native_worker_handle=native_worker_handle,
                native_result_file=bound_native_result_file,
                status=worker_status,
                actual_model=actual_model,
                isolation_evidence=isolation_evidence,
            )
        except HostEvidenceValidationError as exc:
            invalid_business_artifact = any(
                violation.startswith("WORKER_BUSINESS_ARTIFACT_INVALID:")
                for violation in exc.violations
            )
            if invalid_business_artifact:
                try:
                    failure = assembler.record_invalid_worker_failure(
                        action=mapped_action,
                        worker_id=worker_id,
                        native_worker_handle=native_worker_handle,
                        actual_model=actual_model,
                        isolation_evidence=isolation_evidence,
                        detail=" | ".join(exc.violations),
                        native_output_available=bound_native_result_file is not None,
                    )
                except HostEvidenceValidationError:
                    # 只有业务私有文件非法可以转换为失败事实；代际、路径、
                    # 原生句柄和共享 outcomes 冲突仍然必须停在宿主边界。
                    pass
                else:
                    click.echo(json.dumps({
                        "status": "worker_outcome_recorded",
                        "worker_id": worker_id,
                        "outcome": failure,
                        "failure_code": "HOST_WORKER_OUTPUT_INVALID",
                    }, ensure_ascii=False))
                    return
            missing_native_handle = any(
                violation.startswith("NATIVE_WORKER_HANDLE_MISSING:")
                for violation in exc.violations
            )
            click.echo(json.dumps({
                "status": "error",
                "error_code": (
                    "HOST_WORKER_ATTESTATION_MISSING"
                    if missing_native_handle
                    else "HOST_EVIDENCE_INVALID"
                ),
                "message": (
                    "缺少原生 Worker 句柄，已停止；未写入共享 outcomes。"
                    if missing_native_handle
                    else "宿主 Worker 事实未通过校验，已停止；未写入共享 outcomes。"
                ),
                "worker_id": worker_id,
                "stop_reason": (
                    "native_worker_handle_missing"
                    if missing_native_handle
                    else "host_evidence_invalid"
                ),
                "violations": list(exc.violations),
            }, ensure_ascii=False))
            raise click.exceptions.Exit(1) from exc
        click.echo(json.dumps({
            "status": "worker_outcome_recorded",
            "worker_id": worker_id,
            "outcome": outcome,
        }, ensure_ascii=False))
    finally:
        events.close()
        store.close()


def run_record_worker_observation(
    *,
    root: Path,
    worker_id: str,
    native_status: str,
    wait_attempt: int,
    owner_known: bool,
    native_worker_handle: str | None,
    observed_at: str | None,
) -> None:
    """原子记录当前 Action 的宿主等待/所有权观察事实。

    这是 Host Runtime 诊断面写入，不是 Result、Event 或重试请求；只有后续
    原生宿主事实满足既有 outcome 合同，宿主才可以进入 Finalizer 链。
    """

    from datetime import UTC, datetime

    import click

    from auto_engineering.host.worker_observation import (
        WorkerObservationContract,
        WorkerObservationContractError,
        WorkerObservationRecord,
    )
    from auto_engineering.host.worker_observation_store import WorkerObservationStore
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(
        _ensure_checkpoint_db_path(root)
    )
    events = SQLiteEventStore(_ensure_event_db_path(root))
    try:
        thread_id = _active_thread(store)
        if thread_id is None:
            raise click.ClickException("PROJECT_THREAD_NOT_ACTIVE")
        try:
            action = _load_active_action(thread_id, store, events)
        except ValueError as exc:
            if str(exc) != "STATE_SOURCE_CONFLICT":
                raise
            click.echo(json.dumps(
                _state_source_conflict_action(thread_id), ensure_ascii=False
            ))
            return
        if action is None:
            raise click.ClickException("ACTIVE_ACTION_MISSING")
        mapped_action = _map_bound_action_for_host(
            action, root, include_failure_journal=False
        )
        host_execution = mapped_action.get("host_execution")
        if not isinstance(host_execution, Mapping):
            raise click.ClickException("WORKER_OBSERVATION_ACTION_NOT_SPAWN")
        try:
            WorkerObservationContract.from_dict(
                host_execution["worker_observation"]
            )
        except (KeyError, WorkerObservationContractError) as exc:
            raise click.ClickException(
                "WORKER_OBSERVATION_CONTRACT_INVALID"
            ) from exc
        workers = host_execution.get("workers")
        worker = next(
            (
                item for item in workers
                if isinstance(item, Mapping)
                and item.get("worker_id") == worker_id
            ),
            None,
        ) if isinstance(workers, list) else None
        if not isinstance(worker, Mapping):
            raise click.ClickException("WORKER_OBSERVATION_WORKER_NOT_FOUND")
        action_message_id = mapped_action.get("message_id")
        generation = worker.get("execution_generation")
        fencing_token = worker.get("fencing_token")
        if (
            not isinstance(action_message_id, str)
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or not isinstance(fencing_token, str)
        ):
            raise click.ClickException("WORKER_OBSERVATION_IDENTITY_INVALID")
        record = WorkerObservationRecord(
            schema_version="1.0",
            action_message_id=action_message_id,
            worker_id=worker_id,
            execution_generation=generation,
            fencing_token=fencing_token,
            observed_at=(
                observed_at
                if observed_at is not None
                else datetime.now(UTC).isoformat()
            ),
            native_status=native_status,
            wait_attempt=wait_attempt,
            owner_known=owner_known,
            native_worker_handle=native_worker_handle,
        )
        path = WorkerObservationStore(root).save(record)
        click.echo(json.dumps({
            "status": "worker_observation_recorded",
            "action_message_id": action_message_id,
            "worker_id": worker_id,
            "native_status": native_status,
            "wait_attempt": wait_attempt,
            "owner_known": owner_known,
            "observation_path": str(path.relative_to(root.resolve())),
        }, ensure_ascii=False))
    finally:
        events.close()
        store.close()


def _host_mapping_error_action(
    action: Mapping[str, Any], error: ValueError,
) -> dict[str, Any]:
    """把旧/非法宿主映射转换为稳定错误 Action。"""
    return _host_mapping_error_action_impl(
        action,
        error,
        expected_format=_state_reconciliation_expected_format(),
        result_contract=_state_reconciliation_result_contract(),
    )


def run_tick_status(root: Path, verbose: bool = False) -> None:
    """ae dev-loop --status: restore → 输出当前 tick 状态摘要 JSON."""
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.design_decision_ledger import DesignDecisionError
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
        if active_thread is None:
            active_thread = events.latest_thread_for_event("LoopCompleted")
        # status 也必须从 EventStore 读取，不能因为事件缺失而展示 checkpoint 快照。
        if active_thread is None:
            raise click.ClickException(
                "EVENT_THREAD_NOT_FOUND: 没有可查看的 EventStore 活动 thread；"
                "历史 checkpoint 必须先通过 --import-checkpoint 显式导入"
            )
        try:
            orch = TickOrchestrator.restore_from_event_store(
                root,
                store,
                event_store=events,
                thread_id=active_thread,
            )
        except DesignDecisionError as exc:
            # 历史状态绑定的设计源可能已变更；status 仍必须可用，
            # 但不能伪造可继续运行的投影或消费旧 Action。
            persisted_action = _load_active_action(active_thread, store, events)
            if isinstance(persisted_action, Mapping):
                summary = _persisted_reconciliation_gate_status(
                    persisted_action,
                    events.load_projection(active_thread),
                    status_action=_status_action_summary(persisted_action),
                    next_operation=_resume_operation(active_thread),
                )
                if summary is not None:
                    click.echo(json.dumps(summary, ensure_ascii=False))
                    return
            summary = {
                "thread_id": active_thread,
                "current_stage": "unknown",
                "expected_stage": "unknown",
                "tick": 0,
                "round": 0,
                "verdict": "",
                "total_majors": 0,
                "plan_refine_count": 0,
                "active_action_error": str(exc) or "DESIGN_LEDGER_INVALID",
                "recovery_required": True,
            }
            click.echo(json.dumps(summary, ensure_ascii=False))
            return
        summary = orch.status_snapshot(verbose=verbose)
        loop_completed = any(
            event.event_type.value == "LoopCompleted"
            for event in events.load_stream(active_thread)
        )
        if active_thread is not None and (
            not loop_completed
            and (lease is None or lease.disposition != "TERMINAL")
        ):
            summary["next_operation"] = _resume_operation(active_thread)
        if loop_completed or (
            lease is not None and lease.disposition == "TERMINAL"
        ):
            summary["current_stage"] = "done"
            summary["expected_stage"] = "done"
        elif active_thread is not None:
            # status 必须是纯读取；build_action() 可能提交新的 Action 事件，
            # 在查询阶段会制造 action_timestamp 投影冲突。只读取 EventStore
            # 只读取 EventStore 持久化的 Canonical Action；缺失时不读取 checkpoint 快照。
            try:
                active_action = _load_active_action(active_thread, store, events)
            except ValueError as exc:
                if str(exc) != "STATE_SOURCE_CONFLICT":
                    raise
                summary["active_action_error"] = "STATE_SOURCE_CONFLICT"
                summary["recovery_required"] = True
                click.echo(json.dumps(summary, ensure_ascii=False))
                return
            if isinstance(active_action, Mapping):
                try:
                    mapped_active_action = _map_bound_action_for_host(
                        dict(active_action), root, include_failure_journal=False
                    )
                except ValueError as exc:
                    # 旧在途 Action 不能进入当前严格 Host 合同，但 status
                    # 必须仍可用，以便用户看到稳定的迁移/恢复信号。
                    summary.pop("active_action", None)
                    summary["active_action_error"] = str(exc) or "ACTION_INVALID"
                    summary["recovery_required"] = True
                    click.echo(json.dumps(summary, ensure_ascii=False))
                    return
                summary["active_action"] = _status_action_summary(
                    mapped_active_action
                )
            else:
                summary["active_action_error"] = "ACTIVE_ACTION_UNAVAILABLE"
        click.echo(json.dumps(summary, ensure_ascii=False))
    finally:
        events.close()
        store.close()


def run_tick_import_checkpoint(checkpoint_id: str, root: Path) -> None:
    """显式把旧 checkpoint 导入 EventStore，并输出唯一活动 Action。"""
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(
        _ensure_checkpoint_db_path(root)
    )
    events = SQLiteEventStore(_ensure_event_db_path(root))
    try:
        try:
            checkpoint = store.load(checkpoint_id)
        except Exception as exc:
            raise click.ClickException(
                f"CHECKPOINT_IMPORT_FAILED: {exc}"
            ) from exc
        action = store.load_active_protocol_action(checkpoint.state.thread_id)
        try:
            store.import_to_event_store(events, checkpoint.id)
        except (OSError, ValueError, TypeError) as exc:
            raise click.ClickException(
                f"CHECKPOINT_IMPORT_FAILED: {exc}"
            ) from exc
        if action is None:
            raise click.ClickException(
                "CHECKPOINT_IMPORT_ACTION_MISSING: 导入后请使用新的 --init 重新生成 Action"
            )
        try:
            prepared = _prepare_action_for_host(action, root)
        except ValueError as exc:
            prepared = _host_mapping_error_action(action, exc)
        click.echo(json.dumps(prepared, ensure_ascii=False))
    finally:
        events.close()
        store.close()


def run_tick_resume(thread_id: str, root: Path) -> None:
    """ae dev-loop --resume <thread_id>: 从 EventStore 恢复当前 Action。"""
    import json

    import click

    from auto_engineering.loop.event_store import SQLiteEventStore

    events = SQLiteEventStore(_ensure_event_db_path(root))
    try:
        action = events.load_action_snapshot(thread_id)
        if action is None:
            raise click.ClickException(
                "EVENT_ACTION_NOT_FOUND: EventStore 没有该 thread 的活动 Action；"
                "历史 checkpoint 必须先通过 --import-checkpoint 显式导入"
            )
        resume_platform = _resume_host_platform_impl(root, action)
        try:
            with _resume_platform_scope(resume_platform):
                prepared = _prepare_action_for_host(action, root)
        except ValueError as exc:
            if str(exc) == "SPAWN_LEGACY_FIELD_REJECTED":
                state = events.load_projection(thread_id)
                if state is not None:
                    prepared = _persist_legacy_action_recovery_gate(
                        action,
                        state,
                        events,
                        root,
                        expected_format=_state_reconciliation_expected_format(),
                        result_contract=_state_reconciliation_result_contract(),
                    )
                else:
                    prepared = _host_mapping_error_action(action, exc)
            else:
                prepared = _host_mapping_error_action(action, exc)
        click.echo(json.dumps(prepared, ensure_ascii=False))
    finally:
        events.close()
