"""ae progress 命令 — B9 ProgressTree 人视角进度看板 (T9b).

从 .ae-state/*.db 最新 checkpoint 读持久化 progress_tree_json → 反序列化 →
ProgressTree.display() (text) 或 .summary() (json).

与 ae status (机器视角 7 字段路由状态) 互补: progress 展示层次化板块进度
(system → plate → component), 从不参与路由。

引用: design/v5.6-Design-Loop.md §B9.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import click

from auto_engineering.engine.progress_tree import ProgressTree

_logger = logging.getLogger("ae.cli.progress")

_EMPTY_SUMMARY = {
    "completion_pct": 0.0,
    "total_tasks": 0,
    "done_tasks": 0,
    "node_count": 0,
}


def _load_progress_tree(cwd: Path) -> ProgressTree | None:
    """从最新 checkpoint 读 progress_tree_json → ProgressTree. 无则 None.

    跨所有 .ae-state/*.db 找 round 最大的 checkpoint (与 status.py 一致);
    corrupted db → 跳过继续找下一个; progress_tree_json 空/解析失败 → None.
    """
    cp_dir = cwd / ".ae-state"
    if not cp_dir.exists():
        return None

    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    latest_ckpt = None
    for db_file in cp_dir.glob("*.db"):
        try:
            store = SQLiteCheckpointStore(str(db_file))
            ckpt = store.load_latest()
            if ckpt is not None and (
                latest_ckpt is None or ckpt.round > latest_ckpt.round
            ):
                latest_ckpt = ckpt
        except Exception:
            _logger.warning("checkpoint db 读取失败, 跳过: %s", db_file, exc_info=True)
            continue

    if latest_ckpt is None:
        return None

    state = latest_ckpt.state
    if isinstance(state, dict):
        raw = state.get("progress_tree_json")
    else:
        raw = getattr(state, "progress_tree_json", None)
    if not raw:
        return None
    try:
        return ProgressTree.from_dict(json.loads(raw))
    except Exception:
        _logger.warning("progress_tree_json 解析失败", exc_info=True)
        return None


# ============================================================
# Click 命令
# ============================================================


def register_progress_command(main_group: click.Group) -> None:
    """注册 ae progress 命令到 main group."""

    @main_group.command()
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["text", "json"]),
        default="text",
        help="输出格式 (默认 text)",
    )
    @click.option("--plate", "plate_filter", default=None, help="仅展示指定板块")
    @click.option(
        "--all",
        "show_all",
        is_flag=True,
        help="展示已完成板块 (默认折叠 100%+pass 板块)",
    )
    @click.option(
        "--project-root",
        type=click.Path(exists=True),
        default=None,
        help="项目根目录 (默认 cwd)",
    )
    def progress(
        output_format: str,
        plate_filter: str | None,
        show_all: bool,
        project_root: str | None,
    ):
        """查看层次化进度看板 (system → plate → component).

        从最新 checkpoint 读持久化 ProgressTree:
            --format text (默认): 板块/组件树 + 完成率 + verifier 状态
            --format json: summary 4 字段 (completion_pct/total_tasks/done_tasks/node_count)
        """
        cwd = Path(project_root).resolve() if project_root else Path.cwd()
        tree = _load_progress_tree(cwd)

        if tree is None:
            if output_format == "json":
                click.echo(json.dumps(_EMPTY_SUMMARY, ensure_ascii=False, indent=2))
            else:
                click.echo("暂无进度数据 (尚未运行 ae dev-loop --init/--tick)")
            return

        if output_format == "json":
            click.echo(json.dumps(tree.summary(), ensure_ascii=False, indent=2))
            return

        click.echo(tree.display(plate_filter=plate_filter, active_only=not show_all))
