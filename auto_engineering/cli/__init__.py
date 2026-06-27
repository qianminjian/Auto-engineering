"""CLI 入口 — Click 命令注册.

从 cli.py 拆分 (Plan P1-B): helpers.py + dev_loop.py + checkpoint.py + __init__.py.

命令:
    ae init <project>         项目环境初始化
    ae dev-loop <requirement> 单需求开发循环 (默认 v2.0 Orchestrator)
    ae status                 查看当前进度
    ae checkpoint list|show|resume    Checkpoint 管理
    ae checkpoint v2 list|show|delete|migrate   v2.0 Checkpoint 操作
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import click

from auto_engineering import __version__
from auto_engineering.errors import AEError, ErrorCode

# Re-export 所有 helpers + dev_loop 符号, 保持 from auto_engineering.cli import ... 兼容
from auto_engineering.cli.helpers import (  # noqa: F401
    CancellationToken,
    ErrorCategory,
    ProgressLogger,
    TokenTracker,
    _CATEGORY_FRIENDLY_PREFIX,
    _emit_stage_done,
    _install_sigint_handler,
    _log_engine_version,
    _log_stage_progress,
    classify_error,
)
from auto_engineering.cli.dev_loop import (  # noqa: F401
    OrchestratorRunResult,
    _build_v2_agent_runtime,
    _build_v2_semantic_evaluator,
    _run_v2_orchestrator,
)
from auto_engineering.cli.checkpoint import register_checkpoint_commands  # noqa: F401


# ============================================================
# Click 命令
# ============================================================


@click.group()
@click.version_option(version=__version__, prog_name="ae")
def main():
    """Auto-Engineering — 团队级 Loop 工程 + 多 Agent 协作."""
    pass


@main.command()
@click.argument("project", required=False)
@click.option(
    "--type",
    "project_type",
    help="项目类型 (app-service/library/cli-tool/skill/hook/mcp-server/spec-doc/monorepo)",
)
@click.option("--defaults", is_flag=True, help="非交互模式，全部使用默认值")
@click.option("--force", is_flag=True, help="允许覆盖非空目录")
@click.option(
    "--from-answers", "answers_file", type=click.Path(exists=True), help="从 .ae-answers.yml 重放"
)
@click.option("--package-manager", help="包管理器 (npm/pnpm/yarn/bun/uv/poetry)")
@click.option("--ci", "ci_platform", help="CI 平台 (github/gitlab/none)")
@click.option("--test-runner", help="测试框架")
@click.option(
    "--no-typescript", "use_typescript", flag_value=False, default=None, help="不使用 TypeScript"
)
@click.option(
    "--no-lefthook", "use_lefthook", flag_value=False, default=None, help="不安装 Lefthook"
)
@click.option("--pretend", is_flag=True, help="模拟执行，不产生文件")
@click.option("--skip-tasks", is_flag=True, help="跳过钩子任务执行")
@click.option(
    "--no-cleanup", "cleanup_on_error", flag_value=False, default=True, help="出错时不清理目标目录"
)
@click.option("--quiet", is_flag=True, help="静默模式")
@click.option("--incremental", is_flag=True, help="增量模式：只补充缺失文件，不覆盖已有文件")
def init(
    project: str | None,
    project_type: str | None,
    defaults: bool,
    force: bool,
    answers_file: str | None,
    package_manager: str | None,
    ci_platform: str | None,
    test_runner: str | None,
    use_typescript: bool | None,
    use_lefthook: bool | None,
    pretend: bool,
    skip_tasks: bool,
    cleanup_on_error: bool,
    quiet: bool,
    incremental: bool,
):
    """项目环境初始化."""
    from auto_engineering.init import InitWorker

    dst_path = Path(project) if project else Path.cwd()

    if answers_file:
        from auto_engineering.init import AnswersMap

        answers = AnswersMap.from_answers_file(Path(answers_file))
        click.echo(f"从 {answers_file} 恢复答案")
        if not project_type:
            with contextlib.suppress(KeyError):
                project_type = answers.get("project_type") or ""
    else:
        answers = None

    worker = InitWorker(
        dst_path=dst_path,
        project_type=project_type,
        package_manager=package_manager,
        ci_platform=ci_platform,
        test_runner=test_runner,
        use_typescript=use_typescript,
        use_lefthook=use_lefthook,
        defaults=defaults,
        force=force,
        pretend=pretend,
        skip_tasks=skip_tasks,
        cleanup_on_error=cleanup_on_error,
        quiet=quiet,
        incremental=incremental,
    )
    if answers:
        worker._previous_answers = answers

    try:
        result = worker.execute()
        if pretend:
            click.echo(f"[DRY RUN] 将生成到: {result.dst_path}")
        else:
            click.echo(f"✓ 项目已生成: {result.dst_path}")
    except Exception as e:
        click.echo(f"✗ 初始化失败: {e}", err=True)
        raise SystemExit(1) from e


@main.command()
@click.argument("requirement")
@click.option("--max-rounds", type=int, default=3, help="最大 Round 数")
@click.option("--max-tokens", type=int, default=0, help="Token 预算上限 (0 = 无限制)")
@click.option("--log-format", type=click.Choice(["text", "json"]), default="text", help="日志格式")
@click.option(
    "--llm-provider",
    type=click.Choice(["anthropic", "ollama", "openai"]),
    default="anthropic",
    help="LLM 提供方",
)
@click.option("--project-root", type=click.Path(exists=True), help="项目根目录 (默认 cwd)")
def dev_loop(
    requirement: str,
    max_rounds: int,
    max_tokens: int,
    log_format: str,
    llm_provider: str,
    project_root: str,
):
    """单需求开发循环 (v2.0 Orchestrator + Gates + 语义评估).

    需要 ANTHROPIC_API_KEY 环境变量.
    """
    if llm_provider != "anthropic":
        click.echo(f"[未实现] --llm-provider={llm_provider} 暂未实装。", err=True)
        raise SystemExit(6)

    root = Path(project_root).resolve() if project_root else Path.cwd()

    from auto_engineering.config.environment import load_ae_answers, preflight

    try:
        preflight(root)
    except SystemExit:
        raise

    from auto_engineering.config.settings import Settings

    try:
        Settings.from_env()
    except AEError as e:
        category, exit_code = classify_error(e)
        click.echo(f"{_CATEGORY_FRIENDLY_PREFIX[category]} {e.message}", err=True)
        raise SystemExit(exit_code) from None

    answers_data = load_ae_answers(root)
    _ = answers_data

    cancellation = CancellationToken()
    _install_sigint_handler(cancellation)

    progress = ProgressLogger(log_format=log_format)
    click.echo(f"Starting dev-loop: {requirement}")
    _log_engine_version("v2.0")

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
        click.echo(f"{prefix} {e.message}", err=True)
        if e.code == ErrorCode.TASK_CANCELLED:
            click.echo("Loop drained. Resume with: ae checkpoint resume <id>", err=True)
        raise SystemExit(exit_code) from None

    click.echo(
        f"\n✓ dev-loop complete: status={result.status}, "
        f"steps={result.total_steps}, checkpoint={result.checkpoint_id}"
    )


@main.command()
def status():
    """查看当前项目进度."""
    from auto_engineering.config.environment import ProjectEnvironment

    cwd = Path.cwd()
    click.echo(f"当前目录: {cwd}")

    try:
        env = ProjectEnvironment.resolve(cwd)
        click.echo(f"  项目名称: {env.project_name}")
        click.echo(f"  项目类型: {env.project_type or '未知'}")
        click.echo(f"  包管理器: {env.package_manager or '未知'}")
        click.echo(f"  测试框架: {env.test_runner or '未知'}")
        click.echo(f"  TypeScript: {'是' if env.use_typescript else '否'}")
        click.echo(f"  Lefthook: {'是' if env.use_lefthook else '否'}")
        click.echo(f"  CI: {env.ci_platform or '无'}")
        click.echo(f"  Git: {'是' if env.has_git else '否'}")
        undetectable = env._warn_undetectable(cwd)
        if undetectable:
            click.echo(f"  ⚠ 不可自动判定: {', '.join(undetectable)}", err=True)
    except Exception as e:
        click.echo(f"  读取项目环境失败: {e}")

    cp_dir = cwd / ".ae-checkpoints"
    if cp_dir.exists():
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        total_v2 = 0
        for db_file in cp_dir.glob("*.db"):
            try:
                store = SQLiteCheckpointStore(str(db_file))
                total_v2 += store.count()
            except Exception:
                continue
        if total_v2 > 0:
            click.echo(f"  v2.0 Checkpoints: {total_v2} (见 `ae checkpoint v2 list`)")


# 注册 checkpoint 命令 (从 cli/checkpoint.py 注入)
register_checkpoint_commands(main)


if __name__ == "__main__":
    main()
