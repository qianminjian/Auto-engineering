"""CLI 入口 — Click 命令注册.

从 cli.py 拆分 (Plan P1-B): helpers.py + dev_loop.py + checkpoint.py + __init__.py.

入口 (BEACON 决策 #97, Phase 40):
    /ae:dev-loop Skill  → commands/dev-loop.md driving loop → ae dev-loop --init/--tick/--result/--resume (内部协议)
    ae doctor           首次环境诊断 (Python/uv/git/sqlite3/API key)
    ae status           跨会话进度查询

内部协议 (Skill driving loop 调用, 不直接对用户暴露):
    ae dev-loop --init <req> [--design-doc <path>]   初始化 tick loop
    ae dev-loop --tick --result <file>               提交 tick 结果
    ae dev-loop --status [--verbose] [--format json] 查询进度
    ae dev-loop --resume <id>                        从 checkpoint 恢复
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

from auto_engineering import __version__
from auto_engineering.cli.dev_loop import (
    run_tick_init,
    run_tick_resume,
    run_tick_status,
    run_tick_step,
)
from auto_engineering.cli.doctor import register_doctor_command
from auto_engineering.cli.helpers import (
    ErrorCategory,
    ProgressLogger,
    TokenTracker,
    classify_error,
)
from auto_engineering.cli.status import (
    register_status_command,
)
from auto_engineering.utils.cancellation import CancellationToken

__all__ = [
    "CancellationToken",
    "ErrorCategory",
    "ProgressLogger",
    "TokenTracker",
    "classify_error",
    "dev_loop",
    "main",
    "register_doctor_command",
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
    # BEACON #99: from_project 合并 ae.toml（env > ae.toml > default SSOT 优先级）
    from auto_engineering.config.runtime_config import RuntimeConfig, set_default_config
    config = RuntimeConfig.from_project(Path.cwd())
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
内部协议 (Skill driving loop 调用):
  ae dev-loop --init "需求" [--design-doc <path>]   初始化 tick loop
  ae dev-loop --tick --result result.json            提交本轮 tick 结果
  ae dev-loop --status [--verbose] [--format json]   查看当前进度
  ae dev-loop --resume <checkpoint-id>               从 checkpoint 恢复

辅助命令:
  ae doctor                                          环境预检
  ae status [--verbose]                              查看进度
""")
@click.argument("requirement", required=False)
@click.option("--init", "init_flag", is_flag=True,
              help="[内部协议] 初始化 tick loop, 输出第一个 action JSON")
@click.option("--tick", "tick_flag", is_flag=True,
              help="[内部协议] 处理一个 tick (需 --result)")
@click.option("--result", "result_file", type=click.Path(exists=True),
              help="[内部协议] --tick 的 stage-result.json 路径")
@click.option("--status", "status_flag", is_flag=True,
              help="[内部协议] 查询当前 tick 状态")
@click.option("--verbose", "-v", "verbose_flag", is_flag=True,
              help="--status 时输出 batch 级进度明细")
@click.option("--resume", "resume_id", help="[内部协议] 从指定 checkpoint 恢复")
@click.option("--design-doc", "design_doc", type=click.Path(exists=True),
              help="[内部协议] --init 的设计文档路径 (design-doc 模式)")
@click.option("--max-rounds", type=int, default=3, help="最大 Round 数")
@click.option("--project-root", type=click.Path(exists=True), help="项目根目录 (默认 cwd)")
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
    project_root: str | None = None,
    debug_flag: bool = False,
    debug_dir_opt: str | None = None,
    pause_at_stage: str | None = None,
    escalate_flag: bool = False,
    verbose_flag: bool = False,
):
    """内部协议 — `commands/dev-loop.md` Skill driving loop 调用.

    /ae:dev-loop Skill 为唯一启动入口。本命令的 --init/--tick/--result/--status/--resume
    flag 是 Skill 内部调用协议，不直接对用户暴露。

    辅助命令: ae doctor (环境诊断), ae status (进度查询)
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

    # ── 内部协议: tick 模式分派 ──
    tick_modes = [init_flag, tick_flag, status_flag, bool(resume_id)]
    if sum(bool(m) for m in tick_modes) > 1:
        click.echo("错误: --init/--tick/--status/--resume 互斥, 仅可指定一个。", err=True)
        raise SystemExit(1)

    if init_flag:
        if not requirement:
            click.echo("错误: --init 需要 requirement 参数。", err=True)
            raise SystemExit(1)
        run_tick_init(requirement, design_doc, root, max_rounds, debug=_debug,
                       debug_dir=debug_dir_opt, pause_at_stage=pause_at_stage,
                       escalate=escalate_flag)
        return
    if tick_flag:
        if not result_file:
            click.echo("错误: --tick 必须带 --result <file>。", err=True)
            raise SystemExit(1)
        run_tick_step(Path(result_file), root, debug=_debug,
                       debug_dir=debug_dir_opt)
        return
    if status_flag:
        run_tick_status(root, verbose=verbose_flag)
        return
    if resume_id:
        run_tick_resume(resume_id, root)
        return

    # 无参数且无 flag → 显示帮助
    click.echo(
        "ae dev-loop 是 /ae:dev-loop Skill 的内部协议。\n"
        "请使用 /ae:dev-loop Skill 启动开发循环。\n"
        "辅助命令: ae doctor (环境诊断), ae status (进度查询)",
        err=True,
    )
    raise SystemExit(1)


# 注册 doctor 命令 (从 cli/doctor.py 注入) — 首次环境诊断
register_doctor_command(main)
# 注册 status 命令 (从 cli/status.py 注入) — 跨会话进度查询
register_status_command(main)


if __name__ == "__main__":
    main()
