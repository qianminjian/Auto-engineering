"""CLI dev_loop — v5.6 Tick 模式 + v7.6 Standalone 模式.

从 cli.py 拆分 (Plan P1-B, 原 cli.py §218-451).
v5.5 Orchestrator 已退役 (T133b).
"""

from __future__ import annotations

import logging
from pathlib import Path

from auto_engineering.config.runtime_config import get_default_config
from auto_engineering.engine.state import EngineState

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


def _build_injectables(root: Path, environ_or_config: "RuntimeConfig | dict[str, str] | None" = None) -> dict:
    """Build injectable modules shared by --init and --tick paths.

    Returns dict with keys: context_offloader, tracer, audit_logger.
    tracer is None unless AE_OTLP_ENDPOINT is set (avoids importing opentelemetry
    when not needed).

    Args:
        environ_or_config: Optional RuntimeConfig (P0-6) or legacy environ dict.
            Defaults to process-wide RuntimeConfig sentinel.
    """
    from auto_engineering.config.runtime_config import RuntimeConfig, get_default_config
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
        from auto_engineering.observability.tracing import setup_tracing
        tracer = setup_tracing(service_name="auto-engineering", otlp_endpoint=otlp_endpoint)

    audit_logger = None
    if cfg.audit_log_enabled:
        from auto_engineering.observability.audit_log import AuditLogger
        audit_logger = AuditLogger(root / ".ae-state" / "audit")

    return {
        "context_offloader": context_offloader,
        "tracer": tracer,
        "audit_logger": audit_logger,
    }


def run_tick_init(
    requirement: str, design_doc_path: str | None, root: Path, max_rounds: int,
    debug: bool = False, debug_dir: str | None = None,
    pause_at_stage: str | None = None,
    escalate: bool = False,
) -> None:
    """ae dev-loop --init: 初始化 tick loop, 输出第一个 action JSON (stdout 契约)."""
    import hashlib
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(_ensure_checkpoint_db_path(root))
    try:
        inj = _build_injectables(root)
        orch = TickOrchestrator(root, checkpoint_store=store,
                                context_offloader=inj["context_offloader"],
                                tracer=inj["tracer"],
                                audit_logger=inj["audit_logger"],
                                debug=debug, debug_dir=debug_dir,
                                escalate=escalate)
        if pause_at_stage:
            stages = [s.strip() for s in pause_at_stage.split(",") if s.strip()]
            orch.set_pause_at_stages(stages)
        action = orch.init(
            requirement, design_doc_path=design_doc_path, max_rounds=max_rounds)

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
        click.echo(feature_status_oneline(), err=True)
        for w in feature_warnings():
            click.echo(f"  [WARN] {w}", err=True)

        click.echo(json.dumps(action, ensure_ascii=False))
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


def run_tick_status(root: Path) -> None:
    """ae dev-loop --status: restore → 输出当前 tick 状态摘要 JSON."""
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(_ensure_checkpoint_db_path(root))
    try:
        orch = TickOrchestrator.restore(root, store)
        s = orch._state
        summary = {
            "thread_id": s.thread_id,
            "current_stage": s.current_stage,
            "expected_stage": s.expected_stage,
            "tick": s.tick,
            "round": s.round,
            "verdict": s.critic_verdict,
            "total_majors": s.total_majors,
            "plan_refine_count": s.plan_refine_count,
        }
        click.echo(json.dumps(summary, ensure_ascii=False))
    finally:
        store.close()


def run_tick_resume(checkpoint_id: str, root: Path) -> None:
    """ae dev-loop --resume <id>: 从指定 checkpoint 恢复 → 输出当前 action JSON."""
    import json

    import click

    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    store: SQLiteCheckpointStore[EngineState] = SQLiteCheckpointStore(_ensure_checkpoint_db_path(root))
    try:
        orch = TickOrchestrator.restore(root, store, checkpoint_id=checkpoint_id)
        action = orch.build_action()
        click.echo(json.dumps(action, ensure_ascii=False))
    finally:
        store.close()




def run_standalone(
    requirement: str,
    design_doc: str | None,
    project_root: Path,
    max_rounds: int,
    max_tokens: int,
    llm_provider: str,
    resume_id: str | None,
    debug: bool = False,
    debug_dir: str | None = None,
) -> None:
    """Standalone 模式 (Driver B): 进程内 StandaloneDriver 调 LLM.

    不依赖 Claude Code Agent — 自带 Anthropic API key.
    """
    import asyncio
    import json

    from auto_engineering.loop.standalone_driver import (
        StandaloneDriver, _resolve_model, _resolve_provider,
    )
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator
    from auto_engineering.runtime.runtime import AgentRuntime

    from auto_engineering.agents.base import BaseAgent
    from auto_engineering.prompts.registry import default_registry
    from auto_engineering.tools.bash_tools import RunBashTool
    from auto_engineering.tools.file_tools import (
        EditFileTool,
        ListDirTool,
        ReadFileTool,
        SearchCodeTool,
        WriteFileTool,
    )
    from auto_engineering.tools.run_tests_tool import RunTestsTool

    inj = _build_injectables(project_root)
    orch = TickOrchestrator(project_root, debug=debug, debug_dir=debug_dir,
                            context_offloader=inj["context_offloader"],
                            audit_logger=inj["audit_logger"],
                            tracer=inj["tracer"])
    runtime = AgentRuntime()
    prompts = default_registry()

    # 通用工具集 (所有 role 共享)
    base_tools = [
        ReadFileTool(project_root=project_root),
        WriteFileTool(project_root=project_root),
        EditFileTool(project_root=project_root),
        ListDirTool(project_root=project_root),
        SearchCodeTool(project_root=project_root),
        RunBashTool(project_root=project_root),
        RunTestsTool(project_root=project_root),
    ]

    # v7.8: 按 role 分配工具 — architect 只需探索工具, 不写代码
    architect_tools = [
        ReadFileTool(project_root=project_root),
        ListDirTool(project_root=project_root),
        SearchCodeTool(project_root=project_root),
    ]
    critic_tools = [
        ReadFileTool(project_root=project_root),
        ListDirTool(project_root=project_root),
        SearchCodeTool(project_root=project_root),
        RunBashTool(project_root=project_root),  # git diff
    ]

    for role in ("architect", "developer", "critic"):
        # T59: multi-provider — resolve provider+model per role via env vars
        provider = _resolve_provider(role)
        model = _resolve_model(role)
        system_prompt = prompts.get(role)
        # v7.8: DeepSeek 常产纯 tool_use 无文本, 软上限 = max_calls//2 易误杀
        # developer: 30 (warn=15), critic: 15 (warn=7), architect: 15 (warn=7)
        max_calls = {"architect": 15, "developer": 30, "critic": 15}.get(role, 10)
        tools = {"architect": architect_tools, "developer": base_tools, "critic": critic_tools}.get(role, base_tools)
        agent = BaseAgent(
            llm=provider,
            system_prompt=system_prompt,
            role=role,
            tools=list(tools),
            model=model,
            max_tool_calls=max_calls,
        )
        runtime.register(role, lambda a=agent: a)

    driver = StandaloneDriver(
        orchestrator=orch,
        agent_runtime=runtime,
        project_root=project_root,
        max_rounds=max_rounds,
        max_tokens=max_tokens,
        design_doc_path=design_doc,
    )

    # T69a: Activate metrics collector when AE_METRICS=1
    if get_default_config().metrics_enabled:
        import hashlib
        from auto_engineering.metrics.collector import (
            MetricsCollector,
            set_collector,
        )
        collector = MetricsCollector(project_root)
        collector.set_driver_mode("standalone")
        set_collector(collector)
        req_hash = hashlib.sha256(requirement.encode()).hexdigest()[:12]
        collector.begin_requirement(
            orch._state.thread_id, req_hash,
            requirement_category=_infer_category(requirement),
        )

    summary = None  # guard against NameError in finally block
    try:
        if resume_id:
            summary = asyncio.run(driver.resume(resume_id))
        else:
            summary = driver.run(requirement)
    except Exception:
        # Standalone driver 顶层兜底: 任何未处理异常统一日志 + 干净退出
        _logger.exception("Standalone driver 运行失败")
        raise SystemExit(1)
    finally:
        # T69a: End metrics requirement
        if get_default_config().metrics_enabled:
            from auto_engineering.metrics.collector import get_collector
            mc = get_collector()
            if mc is not None:
                mc.end_requirement(
                    summary.verdict if summary is not None else "ERROR",
                    total_ticks=summary.total_ticks if summary is not None else 0,
                )
        driver.close() if hasattr(driver, "close") else None

    output = {
        "status": "completed" if (summary is not None and summary.success) else "failed",
        "total_ticks": summary.total_ticks if summary is not None else 0,
        "final_stage": summary.final_stage if summary is not None else "error",
        "verdict": summary.verdict if summary is not None else "ERROR",
        "error_message": summary.error_message if summary is not None else "unhandled exception",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
