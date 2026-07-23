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

import logging
from pathlib import Path

import click

from auto_engineering import __version__
from auto_engineering.cli.agent import register_agent_command
from auto_engineering.cli.checkpoint import register_checkpoint_commands
from auto_engineering.cli.dev_loop import (
    run_standalone,
    run_tick_init,
    run_tick_resume,
    run_tick_status,
    run_tick_step,
)
from auto_engineering.cli.doctor import register_doctor_command
from auto_engineering.cli.gate_check import register_gate_check_command
from auto_engineering.cli.helpers import (
    ErrorCategory,
    ProgressLogger,
    TokenTracker,
    classify_error,
)
from auto_engineering.cli.progress import register_progress_command
from auto_engineering.cli.status import (
    register_status_command,
)
from auto_engineering.runtime.cancellation import CancellationToken

__all__ = [
    "CancellationToken",
    "ErrorCategory",
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
    # P0-6: Construct RuntimeConfig once, set as process-wide default
    from auto_engineering.config.runtime_config import RuntimeConfig, set_default_config
    config = RuntimeConfig()
    set_default_config(config)

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # T76: Initialize OTLP tracing (NoOp when AE_OTLP_ENDPOINT not set)
    from auto_engineering.observability.tracing import setup_tracing
    setup_tracing(
        "auto-engineering",
        otlp_endpoint=config.otlp_endpoint,
    )


@main.command(epilog="""
示例:
  ae dev-loop --init "实现用户登录"                  初始化 tick loop
  ae dev-loop --tick --result result.json            提交本轮 tick 结果
  ae dev-loop --status                               查看当前进度
  ae dev-loop --standalone "实现支付功能"             独立运行 (自带 LLM key)
  ae dev-loop --resume <checkpoint-id>               从 checkpoint 恢复
""")
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
@click.option("--format", "log_format", type=click.Choice(["text", "json"]),
              default="text", help="输出格式 (与 ae status --format 统一)")
@click.option(
    "--llm-provider",
    type=click.Choice(["anthropic", "openai", "ollama", "glm", "qwen"]),
    default="anthropic",
    help="LLM 提供方 (anthropic/openai/ollama/glm/qwen)",
)
@click.option("--project-root", type=click.Path(exists=True), help="项目根目录 (默认 cwd)")
@click.option("--standalone", "standalone_flag", is_flag=True,
              help="Standalone 模式 (Driver B): 进程内 AgentRuntime 自带 key 调 LLM")
@click.option("--debug", "debug_flag", is_flag=True,
              help="启用调试模式: 调度轨迹/故障信息写入 _scratch/debug/")
@click.option("--debug-dir", "debug_dir_opt", type=click.Path(),
              help="调试输出目录 (默认 <project_root>/_scratch/debug/)")
@click.option("--pause-at-stage", "pause_at_stage",
              help="T64: 指定 stage 前暂停 (逗号分隔, 如 architect,critic)")
@click.option("--escalate", "escalate_flag", is_flag=True,
              help="T95: 触发 escalation gate — 将当前 batch 升级为人工决策")
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
    standalone_flag: bool = False,
    debug_flag: bool = False,
    debug_dir_opt: str | None = None,
    pause_at_stage: str | None = None,
    escalate_flag: bool = False,
):
    """单需求开发循环.

    v5.6 tick 模式 (§A.1 Python 永不调 LLM, 每次调用独立进程):
        ae dev-loop --init "req" [--design-doc <path>]   初始化, 输出第一个 action
        ae dev-loop --tick --result <file>               处理一个 tick, 输出下一 action
        ae dev-loop --status                             查询当前 tick 状态
        ae dev-loop --resume <id>                         从 checkpoint 恢复

    v7.6 standalone 模式 (Driver B, 进程内 AgentRuntime 自带 key 调 LLM):
        ae dev-loop --standalone "req"                    独立运行, 不依赖 Claude Code Agent

    v5.5 legacy 模式 (⚠️ 已弃用, 30 天后移除, 改用 --standalone):
        ae dev-loop "req"                                 旧路径 (仍可用但输出弃用 WARN)
    """
    root = Path(project_root).resolve() if project_root else Path.cwd()
    # P1-19: uv run --directory changes cwd to auto-eng source — detect and warn.
    _ae_src_indicator = root / "auto_engineering" / "loop" / "tick_orchestrator.py"
    if _ae_src_indicator.exists() and not project_root:
        click.echo(
            "⚠️  project-root 检测为 auto-engineering 源码目录。\n"
            "   如果目标项目在其他路径，请用 --project-root 显式指定。\n"
            "   示例: ae dev-loop --init '需求' --project-root /path/to/your/project",
            err=True,
        )

    # AE_DEBUG=1 环境变量也可激活 debug 模式
    from auto_engineering.config.runtime_config import get_default_config
    _debug = debug_flag or get_default_config().debug_enabled

    # ── v5.6 tick 模式分派 (先于 LLM preflight — Python 不需 API key) ──
    tick_modes = [init_flag, tick_flag, status_flag, bool(resume_id)]
    if sum(bool(m) for m in tick_modes) > 1:
        click.echo("错误: --init/--tick/--status/--resume 互斥, 仅可指定一个。"
                   "示例: ae dev-loop --init '你的需求'", err=True)
        raise SystemExit(1)

    # ── v7.6 standalone 模式互斥检查 ──
    if standalone_flag and sum(bool(m) for m in tick_modes) > 0:
        click.echo("错误: --standalone 与 --init/--tick/--status/--resume 互斥。"
                   "使用 --standalone 时直接提供需求参数: ae dev-loop --standalone '需求'", err=True)
        raise SystemExit(1)
    if init_flag:
        if not requirement:
            click.echo("错误: --init 需要 requirement 参数。"
                       "示例: ae dev-loop --init '实现用户登录功能'", err=True)
            raise SystemExit(1)
        run_tick_init(requirement, design_doc, root, max_rounds, debug=_debug,
                       debug_dir=debug_dir_opt, pause_at_stage=pause_at_stage,
                       escalate=escalate_flag)
        return
    if tick_flag:
        if not result_file:
            click.echo("错误: --tick 必须带 --result <file>。"
                       "示例: ae dev-loop --tick --result stage-result.json", err=True)
            raise SystemExit(1)
        run_tick_step(Path(result_file), root, debug=_debug,
                       debug_dir=debug_dir_opt)
        return
    if status_flag:
        run_tick_status(root)
        return
    if resume_id:
        run_tick_resume(resume_id, root)
        return

    # ── v7.6 standalone 模式 (Driver B) ──
    if standalone_flag:
        if not requirement:
            click.echo("错误: --standalone 需要 requirement 参数。"
                       "示例: ae dev-loop --standalone '实现用户登录功能'", err=True)
            raise SystemExit(1)
        run_standalone(requirement, design_doc, root, max_rounds, max_tokens,
                        llm_provider, resume_id, debug=_debug, debug_dir=debug_dir_opt)
        return

    # v5.5 legacy 路径 30 天过渡期 (T133b)
    # 裸参数 ae dev-loop "req" 仍可用但输出弃用 WARN, 引导改用 --standalone
    # 过渡期截止 2026-08-18, 届时物理删除此路径
    if requirement:
        click.echo(
            "⚠️  弃用警告: ae dev-loop 'req' 旧路径已弃用 (T133b), "
            "请改用: ae dev-loop --standalone 'requirement'\n"
            "    旧路径在 2026-08-18 前仍可用, 之后将移除.",
            err=True,
        )
        run_standalone(requirement, design_doc, root, max_rounds, max_tokens,
                        llm_provider, resume_id, debug=_debug, debug_dir=debug_dir_opt)
        return

    # 无参数且无 flag → 显示帮助
    click.echo(
        "用法: ae dev-loop --init/--tick/--status/--resume/--standalone\n"
        "试运行 ae dev-loop --help 查看完整文档.",
        err=True,
    )
    raise SystemExit(1)


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
