"""CLI 入口 — Click 命令注册.

<<<<<<< HEAD
从 cli.py 拆分 (Plan P1-B): helpers.py + dev_loop.py + checkpoint.py + __init__.py.

命令 (Loop-only, Init Engineering 拆分独立项目, 见 design/BEACON.md 决策 30):
    ae dev-loop <requirement> 单需求开发循环 (默认 v2.0 Orchestrator)
    ae status                 查看当前进度
    ae checkpoint list|show|resume    Checkpoint 管理
    ae checkpoint v2 list|show|delete|migrate   v2.0 Checkpoint 操作

    [已移除] ae init <project>  — Init Engineering 是独立项目, 按
    @design/v5.0-Design-Loop.md §IL.1-IL.6 接口契约实现 Init 侧
=======
命令:
    ae init <project>         项目环境初始化
    ae init --analyze <path> 存量项目：代码分析 + 自动初始化
    ae init-config            查看/编辑初始化配置
>>>>>>> 6e8508c2e41dc1e1925c0424bd148ca847783bb1
"""

from __future__ import annotations

from pathlib import Path

import click

from auto_engineering import __version__
<<<<<<< HEAD
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
from auto_engineering.cli.doctor import register_doctor_command  # noqa: F401
from auto_engineering.cli.gate_check import register_gate_check_command  # noqa: F401
from auto_engineering.cli.agent import register_agent_command  # noqa: F401
from auto_engineering.cli.status import (  # noqa: F401
    _collect_status_json,
    register_status_command,
)


# ============================================================
# Click 命令
# ============================================================
=======
>>>>>>> 6e8508c2e41dc1e1925c0424bd148ca847783bb1


@click.group()
@click.version_option(version=__version__, prog_name="ae")
def main():
<<<<<<< HEAD
    """Auto-Engineering — 团队级 Loop 工程 + 多 Agent 协作.

    Init 工程 (项目脚手架) 已拆分独立项目, 见 design/BEACON.md.
    """
=======
    """Init-Engineering — Agent Skill 模式项目环境初始化工具."""
>>>>>>> 6e8508c2e41dc1e1925c0424bd148ca847783bb1
    pass


@main.command()
<<<<<<< HEAD
def init() -> None:
    """[已禁用] 项目脚手架初始化 — Init Engineering 拆分独立项目.

    本项目仅 Loop Engineering. 项目脚手架请使用独立 Init Engineering 项目
    (按 v5.0-Design-Loop.md §IL.1-IL.6 接口契约实现 Init 侧).
    """
    click.echo(
        "✗ ae init 不可用: Init Engineering 已拆分独立项目.\n"
        "  本项目仅 Loop Engineering. 项目脚手架请使用独立 Init 项目.\n"
        "  见 design/v5.0-Design-Loop.md §IL.1-IL.6 接口契约.",
        err=True,
=======
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
@click.option(
    "--analyze", "analyze_only", is_flag=True, help="存量项目：只分析项目类型，不初始化"
)
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
    analyze_only: bool,
):
    """项目环境初始化."""
    from auto_engineering.init import InitWorker
    from auto_engineering.init.detector import ProjectDetector

    dst_path = Path(project) if project else Path.cwd()

    # --analyze 模式：只运行代码分析，不初始化
    if analyze_only:
        detector = ProjectDetector(dst_path)
        candidates = detector.list_candidates()
        detected = detector.detect()
        click.echo(f"分析目录: {dst_path}")
        if candidates:
            click.echo(f"检测到的项目类型候选: {', '.join(candidates)}")
            if detected:
                click.echo(f"✓ 自动检测结果: {detected}")
            else:
                click.echo("⚠ 多个候选，无法自动确定类型")
        else:
            click.echo("⚠ 未检测到已知项目类型（空目录或未知类型）")
        return

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
>>>>>>> 6e8508c2e41dc1e1925c0424bd148ca847783bb1
    )
    raise SystemExit(1)


@main.command()
<<<<<<< HEAD
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
        if log_format == "json":
            import json
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
        import json

        click.echo(json.dumps(result.to_json_dict(), ensure_ascii=False, indent=2))
    else:
        click.echo(
            f"\n✓ dev-loop complete: status={result.status}, "
            f"steps={result.total_steps}, checkpoint={result.checkpoint_id}"
        )

    # v5.0 exit codes: 0=completed, 2=gate_unrecoverable (max_rounds 走 0, 失败/取消已 raise 走分类码)
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
=======
def status():
    """查看当前项目环境配置."""
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
>>>>>>> 6e8508c2e41dc1e1925c0424bd148ca847783bb1


if __name__ == "__main__":
    main()
