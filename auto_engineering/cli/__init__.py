"""CLI 入口 — Click 命令注册.

从 cli.py 拆分 (Plan P1-B): helpers.py + dev_loop.py + checkpoint.py + __init__.py.

命令 (Loop-only, Init Engineering 拆分独立项目, 见 design/BEACON.md 决策 30):
    ae dev-loop <requirement> 单需求开发循环 (默认 v2.0 Orchestrator)
    ae status                 查看当前进度
    ae checkpoint list|show|resume    Checkpoint 管理
    ae checkpoint v2 list|show|delete|migrate   v2.0 Checkpoint 操作

    [已移除] ae init <project>  — Init Engineering 是独立项目, 按
    @design/v5.6-Design-Loop.md §IL.1-IL.6 接口契约实现 Init 侧
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from auto_engineering import __version__
from auto_engineering.cli.agent import register_agent_command
from auto_engineering.cli.checkpoint import register_checkpoint_commands
from auto_engineering.cli.dev_loop import (
    OrchestratorRunResult,
    _run_tick_init,
    _run_tick_resume,
    _run_tick_status,
    _run_tick_step,
    _run_v2_orchestrator,
)
from auto_engineering.cli.doctor import register_doctor_command
from auto_engineering.cli.gate_check import register_gate_check_command

# 私有符号 (模块内部使用, _ 前缀按 Python 约定不公开)
# v5.5 audit P0-11: __all__ 排除私有符号, from cli import * 不会导出
from auto_engineering.cli.helpers import (
    _CATEGORY_FRIENDLY_PREFIX,
    ErrorCategory,
    ProgressLogger,
    TokenTracker,
    _install_sigint_handler,
    _log_engine_version,
    classify_error,
)
from auto_engineering.cli.progress import register_progress_command
from auto_engineering.cli.status import (
    register_status_command,
)
from auto_engineering.errors import AEError, ErrorCode

# Re-export 公开符号, 保持 from auto_engineering.cli import ... 兼容
from auto_engineering.runtime.cancellation import CancellationToken

__all__ = [
    "CancellationToken",
    "ErrorCategory",
    "OrchestratorRunResult",
    "ProgressLogger",
    "TokenTracker",
    "classify_error",
    "dev_loop",
    "main",
    "register_agent_command",
    "register_checkpoint_commands",
    "register_doctor_command",
    "register_gate_check_command",
    "register_progress_command",
    "register_status_command",
]


# ============================================================
# Click 命令
# ============================================================


@click.group()
@click.version_option(version=__version__, prog_name="ae")
def main():
    """Auto-Engineering — 团队级 Loop 工程 + 多 Agent 协作.

    Init 工程 (项目脚手架) 已拆分独立项目, 见 design/BEACON.md.
    """
    import logging
    import os

    log_level = os.environ.get("AE_LOG_LEVEL", "INFO").strip().upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@main.command()
@click.argument("requirement", required=False)
@click.option("--init", "init_flag", is_flag=True,
              help="v5.6: 初始化 tick loop, 输出第一个 action JSON")
@click.option("--tick", "tick_flag", is_flag=True,
              help="v5.6: 处理一个 tick (需 --result)")
@click.option("--result", "result_file", type=click.Path(exists=True),
              help="--tick 的 stage-result.json 路径")
@click.option("--status", "status_flag", is_flag=True,
              help="v5.6: 查询当前 tick 状态")
@click.option("--resume", "resume_id", help="v5.6: 从指定 checkpoint 恢复")
@click.option("--design-doc", "design_doc", type=click.Path(exists=True),
              help="--init 的设计文档路径 (design-doc 模式)")
@click.option("--max-rounds", type=int, default=3, help="最大 Round 数")
@click.option("--max-tokens", type=int, default=0, help="Token 预算上限 (0 = 无限制)")
@click.option("--format", "log_format", type=click.Choice(["text", "json"]), default="text", help="输出格式 (与 ae status --format 统一)")
@click.option(
    "--llm-provider",
    type=click.Choice(["anthropic"]),
    default="anthropic",
    help="LLM 提供方 (仅 anthropic 已实装)",
)
@click.option("--project-root", type=click.Path(exists=True), help="项目根目录 (默认 cwd)")
def dev_loop(
    requirement: str | None,
    init_flag: bool,
    tick_flag: bool,
    result_file: str | None,
    status_flag: bool,
    resume_id: str | None,
    design_doc: str | None,
    max_rounds: int,
    max_tokens: int,
    log_format: str,
    llm_provider: str,
    project_root: str,
):
    """单需求开发循环.

    v5.6 tick 模式 (§A.1 Python 永不调 LLM, 每次调用独立进程):
        ae dev-loop --init "req" [--design-doc <path>]   初始化, 输出第一个 action
        ae dev-loop --tick --result <file>               处理一个 tick, 输出下一 action
        ae dev-loop --status                             查询当前 tick 状态
        ae dev-loop --resume <id>                         从 checkpoint 恢复

    v5.5 legacy 模式 (连续 while, 调 LLM):
        ae dev-loop "req"                                 单需求连续调试
    """
    root = Path(project_root).resolve() if project_root else Path.cwd()

    # ── v5.6 tick 模式分派 (先于 LLM preflight — Python 不需 API key) ──
    tick_modes = [init_flag, tick_flag, status_flag, bool(resume_id)]
    if sum(bool(m) for m in tick_modes) > 1:
        click.echo("错误: --init/--tick/--status/--resume 互斥, 仅可指定一个", err=True)
        raise SystemExit(1)
    if init_flag:
        if not requirement:
            click.echo("错误: --init 需要 requirement 参数", err=True)
            raise SystemExit(1)
        _run_tick_init(requirement, design_doc, root, max_rounds)
        return
    if tick_flag:
        if not result_file:
            click.echo("错误: --tick 必须带 --result <file>", err=True)
            raise SystemExit(1)
        _run_tick_step(Path(result_file), root)
        return
    if status_flag:
        _run_tick_status(root)
        return
    if resume_id:
        _run_tick_resume(resume_id, root)
        return

    # ── v5.5 legacy 模式 (需 requirement + LLM) ──
    if not requirement:
        click.echo(
            "错误: requirement 参数必填 (或用 --init/--tick/--status/--resume)", err=True)
        raise SystemExit(1)

    if llm_provider != "anthropic":
        click.echo(f"[未实现] --llm-provider={llm_provider} 暂未实装。", err=True)
        raise SystemExit(6)

    root = Path(project_root).resolve() if project_root else Path.cwd()

    from auto_engineering.config.environment import preflight

    try:
        preflight(root)
    except SystemExit:
        raise

    from auto_engineering.utils.plugin_mode import is_llm_available

    if not is_llm_available():
        msg = (
            "环境变量 ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN 未设置。"
            "Plugin mode (Claude Code agent 内) 应零配置, 由 Claude Code OAuth 自动注入。"
            "CLI 调试模式需手动 export ANTHROPIC_API_KEY=sk-ant-..."
        )
        category, exit_code = classify_error(
            AEError(ErrorCode.CONFIG_MISSING_API_KEY, msg)
        )
        click.echo(f"{_CATEGORY_FRIENDLY_PREFIX[category]} {msg}", err=True)
        raise SystemExit(exit_code) from None

    cancellation = CancellationToken()
    _install_sigint_handler(cancellation)

    progress = ProgressLogger(log_format=log_format)
    click.echo(f"Starting dev-loop: {requirement}")
    _log_engine_version("v5.5")

    tracker = TokenTracker(max_tokens=max_tokens)
    try:
        result = _run_v2_orchestrator(
            requirement=requirement,
            project_root=root,
            max_rounds=max_rounds,
            progress=progress,
            cancellation=cancellation,
            token_tracker=tracker,
        )
    except AEError as e:
        category, exit_code = classify_error(e)
        prefix = _CATEGORY_FRIENDLY_PREFIX[category]
        if log_format == "json":
            import uuid

            error_payload = {
                "status": "failed",
                "thread_id": uuid.uuid4().hex,
                "rounds": 0,
                "verdict": {"level": -1, "level_name": "ERROR", "reason": str(e.message)},
                "duration_sec": 0.0,
                "gate_summary": {},
                "error": {"code": str(e.code.value), "category": category.value, "message": str(e.message)},
            }
            click.echo(json.dumps(error_payload, ensure_ascii=False, indent=2))
        else:
            click.echo(f"{prefix} {e.message}", err=True)
            if e.code == ErrorCode.TASK_CANCELLED:
                click.echo("Loop drained. Resume with: ae checkpoint resume <id>", err=True)
        raise SystemExit(exit_code) from None

    if log_format == "json":
        # v5.0 §B13.2: 6 字段 JSON 契约
        click.echo(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))
    else:
        click.echo(
            f"\n✓ dev-loop complete: status={result.status}, "
            f"steps={result.total_steps}, checkpoint={result.checkpoint_id}"
        )

    # v5.0 exit codes: 0=completed (QUALITY_PASS level=3),
    # 2=failed (verdict.level=4 HARD_LIMIT, Bug 3 prismscan / Issue #13),
    # 130=SIGINT (AEError raised above)
    if result.status == "failed":
        # Bug 3 prismscan 修复: verdict.level=4 (HARD_LIMIT, critic 异常升级) →
        # status="failed" → CLI exit 非 0. 旧行为 exit 0 是 0 代码改动退出的根因.
        click.echo(
            f"✗ dev-loop failed (verdict.level=4 HARD_LIMIT): "
            f"{result.verdict.get('reason', 'unknown')}",
            err=True,
        )
        raise SystemExit(2)
    if result.status == "completed":
        return  # exit 0
    # max_rounds / 其他 → exit 0 (达到上限非异常, v2.0 行为兼容)
    return


# 注册 checkpoint 命令 (从 cli/checkpoint.py 注入)
register_checkpoint_commands(main)
# 注册 doctor 命令 (从 cli/doctor.py 注入)
register_doctor_command(main)
# 注册 gate-check 命令 (从 cli/gate_check.py 注入)
register_gate_check_command(main)
# 注册 agent 命令 (从 cli/agent.py 注入)
register_agent_command(main)
# 注册 status 命令 (从 cli/status.py 注入, P0-2 修复 v5.0 §B13.2)
register_status_command(main)
# 注册 progress 命令 (从 cli/progress.py 注入, T9b B9 ProgressTree 看板)
register_progress_command(main)


if __name__ == "__main__":
    main()
