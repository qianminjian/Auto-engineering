"""CLI dev_loop — v5.6 离散 Tick 模式。

从 cli.py 拆分 (Plan P1-B, 原 cli.py §218-451).
v5.5 Orchestrator 已退役 (T133b).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from auto_engineering.config.runtime_config import RuntimeConfig, get_default_config
from auto_engineering.engine.state import EngineState

if TYPE_CHECKING:
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

_logger = logging.getLogger(__name__)


# ============================================================
# v5.6 Tick 模式 CLI 处理器 (§A.1 Python 永不调 LLM — 不需 API key)
# 每次调用是独立进程, 从 .ae-state/checkpoints.db 恢复/持久化状态。
# ============================================================


def _ensure_checkpoint_db_path(root: Path) -> Path:
    """.ae-state/checkpoints.db — 跨 tick 持久化 store (目录不存在则创建)."""
    state_dir = root / ".ae-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "checkpoints.db"


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


def run_tick_init(
    requirement: str, design_doc_path: str | None, root: Path, max_rounds: int,
    debug: bool = False, debug_dir: str | None = None,
    pause_at_stage: str | None = None,
    escalate: bool = False,
    config_policy: str | None = None,
) -> None:
    """ae dev-loop --init: 初始化 tick loop, 输出第一个 action JSON (stdout 契约)."""
    import click

    # Phase 45: 配置闸门
    if not _check_config_gate(root, policy=config_policy):
        return

    import hashlib
    import json

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(_ensure_checkpoint_db_path(root))
    reserved_thread_id = str(uuid4())
    try:
        existing_thread_id = store.reserve_project_thread(reserved_thread_id)
        if existing_thread_id is not None:
            raise click.ClickException(
                "PROJECT_THREAD_ACTIVE: 项目已有未完成 thread；"
                f"请运行 scripts/ae-run dev-loop --resume {existing_thread_id}"
            )
        inj = _build_injectables(root)
        orch = TickOrchestrator(root, checkpoint_store=store,
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

        click.echo(json.dumps(action, ensure_ascii=False))
    except Exception:
        store.release_project_thread(reserved_thread_id)
        raise
    finally:
        store.close()


def run_tick_step(result_file: Path, root: Path,
                   debug: bool = False, debug_dir: str | None = None) -> None:
    """ae dev-loop --tick --result <file>: restore → tick → 下一 action JSON."""
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(_ensure_checkpoint_db_path(root))
    try:
        inj = _build_injectables(root)
        orch = TickOrchestrator.restore(root, store, debug=debug, debug_dir=debug_dir,
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

        action = orch.tick(result_file)
        if (
            action.get("action") == "done"
            and orch._state is not None
        ):
            store.release_project_thread(orch._state.thread_id)

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

        click.echo(json.dumps(action, ensure_ascii=False))
    finally:
        store.close()


def run_tick_validate(result_file: Path, root: Path) -> None:
    """预校验 Result；不推进状态，也不生成新的协议记录。"""
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(
        _ensure_checkpoint_db_path(root)
    )
    try:
        orch = TickOrchestrator.restore(root, store)
        result = orch.validate_result_file(result_file)
        click.echo(json.dumps(result, ensure_ascii=False))
        if result.get("action") == "error":
            raise SystemExit(1)
    finally:
        store.close()


def run_tick_status(root: Path, verbose: bool = False) -> None:
    """ae dev-loop --status: restore → 输出当前 tick 状态摘要 JSON."""
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(_ensure_checkpoint_db_path(root))
    try:
        orch = TickOrchestrator.restore(root, store)
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
        if verbose and orch._batch_state is not None:
            bs = orch._batch_state
            batches = []
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
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(_ensure_checkpoint_db_path(root))
    try:
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
        click.echo(json.dumps(action, ensure_ascii=False))
    finally:
        store.close()


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
