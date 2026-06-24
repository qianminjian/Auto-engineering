"""CLI 入口 — Click 命令注册.

命令:
    ae init <project>         项目环境初始化
    ae dev-loop <requirement> 单需求开发循环
    ae status                 查看当前进度
"""

import click

from auto_engineering import __version__


@click.group()
@click.version_option(version=__version__, prog_name="ae")
def main():
    """Auto-Engineering — 团队级 Loop 工程 + 多 Agent 协作."""
    pass


@main.command()
@click.argument("project", required=False)
@click.option("--type", "project_type", help="项目类型 (app-service/library/cli-tool/skill/hook/mcp-server/spec-doc/monorepo)")
@click.option("--defaults", is_flag=True, help="非交互模式，全部使用默认值")
@click.option("--force", is_flag=True, help="允许覆盖非空目录")
@click.option("--from-answers", "answers_file", type=click.Path(exists=True), help="从 .ae-answers.yml 重放")
@click.option("--package-manager", help="包管理器 (npm/pnpm/yarn/bun/uv/poetry)")
@click.option("--ci", "ci_platform", help="CI 平台 (github/gitlab/none)")
@click.option("--test-runner", help="测试框架")
@click.option("--no-typescript", "use_typescript", flag_value=False, default=None, help="不使用 TypeScript")
@click.option("--no-lefthook", "use_lefthook", flag_value=False, default=None, help="不安装 Lefthook")
@click.option("--pretend", is_flag=True, help="模拟执行，不产生文件")
@click.option("--skip-tasks", is_flag=True, help="跳过钩子任务执行")
@click.option("--no-cleanup", "cleanup_on_error", flag_value=False, default=True, help="出错时不清理目标目录")
@click.option("--quiet", is_flag=True, help="静默模式")
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
):
    """项目环境初始化."""
    from pathlib import Path
    from auto_engineering.init import InitWorker

    dst_path = Path(project) if project else Path.cwd()

    if answers_file:
        from auto_engineering.init import AnswersMap
        answers = AnswersMap.from_answers_file(Path(answers_file))
        click.echo(f"从 {answers_file} 恢复答案")
        if not project_type:
            try:
                project_type = answers.get("project_type") or ""
            except KeyError:
                pass
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
        raise SystemExit(1)


@main.command()
@click.argument("requirement")
@click.option("--max-steps", type=int, default=3, help="最大迭代步数")
@click.option("--multi", is_flag=True, help="多 Agent 并行模式（未来）")
def dev_loop(requirement: str, max_steps: int, multi: bool):
    """单需求开发循环 (Architect → Developer → Critic)."""
    from pathlib import Path
    from auto_engineering.config.environment import preflight

    # 入口前置校验 — 缺 API key/非 git 仓库/磁盘不足/Python 版本低 直接退出
    try:
        preflight(Path.cwd())
    except SystemExit:
        raise

    if multi:
        click.echo("多 Agent 并行模式尚未实现。")
        return

    click.echo(f"需求: {requirement}")
    click.echo(f"最大步数: {max_steps}")
    click.echo("dev-loop 核心引擎尚未实现。")


@main.command()
def status():
    """查看当前项目进度."""
    from pathlib import Path
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
    except Exception as e:
        click.echo(f"  读取项目环境失败: {e}")


if __name__ == "__main__":
    main()
