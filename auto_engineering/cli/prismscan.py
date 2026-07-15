"""PrismScan V5.1 CLI — ae prismscan discover-extract | check-result."""

from __future__ import annotations

import json

import click

from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator


@click.group(name="prismscan")
def prismscan_group():
    """PrismScan V5.1 — 代码库反向工程管道."""
    pass


@prismscan_group.command(name="discover-extract")
@click.option("--project-root", type=click.Path(exists=True), default=".",
              help="项目根目录 (默认 cwd)")
@click.option("--format", "output_format", type=click.Choice(["json", "text"]),
              default="json", help="输出格式")
def discover_extract(project_root: str, output_format: str):
    """运行 discover + extract 确定性阶段, 输出 action JSON."""
    orch = PrismScanOrchestrator(project_root=project_root)
    result = orch.run_discover_extract()

    if output_format == "text":
        if result.get("action") == "error":
            click.echo(f"Error: {result.get('error_code')} — {result.get('message')}",
                       err=True)
            raise SystemExit(1)

        ps = result.get("context", {}).get("project_shape", {})
        click.echo(f"action: {result['action']}")
        click.echo(f"project: {ps.get('project_name', '?')}")
        click.echo(f"stage: {result['stage']}")
        click.echo(f"thread_id: {result.get('thread_id', '?')}")
        click.echo(f"languages: {ps.get('languages', [])}")
        click.echo(f"build_system: {ps.get('build_system', '?')}")
        click.echo(f"modules: {len(ps.get('modules', []))}")
        click.echo(f"total_files: {ps.get('total_files', 0)}")
        click.echo(f"data_file: {result.get('data_file', '?')}")
    else:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("action") == "error":
        raise SystemExit(1)


@prismscan_group.command(name="check-result")
@click.argument("result_file", type=click.Path(exists=True))
@click.option("--project-root", type=click.Path(exists=True), default=".",
              help="项目根目录 (默认 cwd)")
def check_result(result_file: str, project_root: str):
    """校验 Agent 产出的 AnalysisResult JSON."""
    orch = PrismScanOrchestrator(project_root=project_root)
    result = orch.check_result(result_file)

    is_error = result.get("action") == "error"
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if is_error:
        raise SystemExit(1)


def register_prismscan_command(main_group: click.Group) -> None:
    """将 prismscan 子命令注册到主 CLI group."""
    main_group.add_command(prismscan_group)
