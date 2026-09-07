"""ae status 命令 — v5.0 §B13.2 /status stdout JSON 契约.

实现 7 字段 JSON 输出 + 文本模式兼容:
    thread_id / round / stage / verdict /
    majors_in_a_row / total_majors / recent_history (≤5 条 RoundHistory)

设计:
- `_collect_status_json(cwd)` 是核心函数，只从 `.ae-state/events.db` 读取 EventStore 投影
- Click 命令 `status` 包装 `_collect_status_json` + 输出格式化
- checkpoint 只通过显式迁移入口消费，不参与当前状态展示

引用: design/v5.6-Design-Loop.md §B13.2 stdout JSON 契约
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import click

from auto_engineering.config.environment import ProjectEnvironment

_logger = logging.getLogger("ae.cli.status")

if TYPE_CHECKING:
    from auto_engineering.host.runtime_driver import HostRunLease


def _collect_status_json(cwd: Path) -> dict:
    """收集 status JSON 7 字段契约 (v5.0 §B13.2).

    无 EventStore 时返回 7 字段默认 (recent_history = [])；损坏的 EventStore
    返回带 recovery_required 的结构化状态，绝不回退到 checkpoint。
    """
    # 默认值
    payload: dict = {
        "thread_id": "",
        "round": 0,
        "stage": "",
        "verdict": "",
        "majors_in_a_row": 0,
        "total_majors": 0,
        "recent_history": [],
    }

    cp_dir = cwd / ".ae-state"
    if not cp_dir.exists():
        return payload

    # v5.8：EventStore 是唯一当前事实源。没有事件库时返回空状态；不能
    # 为了维持旧字段而读取 checkpoint，避免把历史快照伪装成当前运行状态。
    event_payload = _collect_event_store_status(cwd)
    if event_payload is not None:
        return event_payload
    return payload


def _collect_event_store_status(cwd: Path) -> dict | None:
    """读取 active EventStore projection；损坏时返回结构化恢复状态。"""
    cp_dir = cwd / ".ae-state"
    event_db = cp_dir / "events.db"
    if not event_db.exists():
        return None
    try:
        from auto_engineering.loop.event_store import SQLiteEventStore

        thread_id, lease = _event_thread_context(cwd)
        if not thread_id:
            return None
        with SQLiteEventStore(event_db) as events:
            state = events.load_projection(thread_id)
            stream = events.load_stream(thread_id)
        if state is None:
            return None
        payload = {
            "thread_id": state.thread_id,
            "round": state.round,
            "stage": state.current_stage,
            "verdict": state.critic_verdict,
            "majors_in_a_row": state.majors_in_a_row,
            "total_majors": state.total_majors,
            "recent_history": [],
        }
        loop_completed = any(
            event.event_type.value == "LoopCompleted" for event in stream
        )
        if loop_completed or (
            lease is not None and lease.disposition == "TERMINAL"
        ):
            payload["stage"] = "done"
        from auto_engineering.engine.batch_state import BatchState
        from auto_engineering.loop.status_projection import reconciliation_status

        batch_state = None
        if state.batch_state_json:
            batch_state = BatchState.from_json(
                state.batch_state_json,
                design_doc=None,
                batch_plan=[dict(item) for item in state.batch_plan],
            )
        reconciliation = reconciliation_status(state, batch_state)
        if reconciliation is not None:
            payload["plan_reconciliation"] = reconciliation
        from auto_engineering.metrics.event_projection import project_event_metrics

        usage_records = []
        usage_path = cp_dir / "usage-ledger.db"
        if usage_path.exists():
            from auto_engineering.metrics.usage_ledger import UsageLedger

            usage_ledger = UsageLedger(usage_path)
            try:
                usage_records = usage_ledger.list_records(thread_id)
            finally:
                usage_ledger.close()
        payload["event_metrics"] = project_event_metrics(stream, usage_records)
        return payload
    except (OSError, sqlite3.Error, ValueError, TypeError):
        _logger.warning("EventStore status 读取失败；拒绝回退 checkpoint", exc_info=True)
        return {
            "thread_id": "",
            "round": 0,
            "stage": "",
            "verdict": "",
            "majors_in_a_row": 0,
            "total_majors": 0,
            "recent_history": [],
            "error_code": "EVENT_STORE_UNAVAILABLE",
            "recovery_required": True,
        }


def _event_thread_context(cwd: Path) -> tuple[str | None, HostRunLease | None]:
    """读取 EventStore 所属 thread 的租约定位信息，不读取 checkpoint 状态。"""

    cp_dir = cwd / ".ae-state"
    thread_id: str | None = None
    try:
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

        with SQLiteCheckpointStore[object](
            str(cp_dir / "checkpoints.db"), read_only=True
        ) as store:
            thread_id = store.active_project_thread()
    except (OSError, sqlite3.Error, ValueError, TypeError):
        _logger.debug("项目占用租约读取失败", exc_info=True)
    lease = None
    if not thread_id:
        from auto_engineering.host.runtime_driver import HostRunLeaseStore

        lease = HostRunLeaseStore(cwd).load()
        thread_id = lease.thread_id if lease is not None else None
    if not thread_id and (cp_dir / "events.db").exists():
        from auto_engineering.loop.event_store import SQLiteEventStore

        with SQLiteEventStore(cp_dir / "events.db") as events:
            thread_id = events.latest_thread_for_event("LoopCompleted")
    return thread_id, lease


# ============================================================
# Click 命令
# ============================================================


def register_status_command(main_group: click.Group) -> None:
    """注册 ae status 命令到 main group.

    Args:
        main_group: ae 主 click group (auto_engineering.cli.main)
    """

    @main_group.command()
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["text", "json"]),
        default="text",
        help="输出格式 (默认 text)",
    )
    @click.option(
        "--verbose", "-v",
        is_flag=True,
        help="显示进度树 (ProgressTree 层次化板块进度)",
    )
    @click.option(
        "--project-root",
        type=click.Path(exists=True),
        default=None,
        help="项目根目录 (默认 cwd)",
    )
    def status(output_format: str, verbose: bool, project_root: str | None):
        """查看当前项目进度.

        --format json: 输出 7 字段 JSON (v5.0 §B13.2)
        --verbose: 显示 ProgressTree 层次化板块进度
        """
        cwd = Path(project_root).resolve() if project_root else Path.cwd()

        if output_format == "json":
            payload = _collect_status_json(cwd)
            if verbose:
                payload["progress_tree"] = _load_progress_summary(cwd)
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        # 文本模式 (只读, 不写入 .ae-answers.yml)
        click.echo(f"当前目录: {cwd}")

        try:
            answers_file = cwd / ".ae-answers.yml"
            if answers_file.exists():
                env = ProjectEnvironment._from_answers_file(answers_file)
            else:
                env = ProjectEnvironment._from_detection(cwd)
            click.echo(f"  项目名称: {env.project_name}")
            click.echo(f"  项目类型: {env.project_type or '未知'}")
            click.echo(f"  包管理器: {env.package_manager or '未知'}")
            click.echo(f"  测试框架: {env.test_runner or '未知'}")
            click.echo(f"  TypeScript: {'是' if env.use_typescript else '否'}")
            click.echo(f"  Lefthook: {'是' if env.use_lefthook else '否'}")
            click.echo(f"  CI: {env.ci_platform or '无'}")
            click.echo(f"  Git: {'是' if env.has_git else '否'}")
            undetectable = env.get_undetectable_fields(cwd)
            if undetectable:
                click.echo(f"  ⚠ 不可自动判定: {', '.join(undetectable)}", err=True)
        except Exception as e:
            _logger.warning("读取项目环境失败", exc_info=True)
            click.echo(f"  读取项目环境失败: {e} — 可运行 ae doctor 检查环境")

        # ── verbose: 显示进度树 ──
        if verbose:
            _display_progress_tree(cwd)



def _load_progress_summary(cwd: Path) -> dict:
    """从 EventStore 投影读取 progress_tree 摘要。"""
    cp_dir = cwd / ".ae-state"
    event_db = cp_dir / "events.db"
    if not event_db.exists():
        return {"completion_pct": 0.0, "total_tasks": 0, "done_tasks": 0, "node_count": 0}
    try:
        from auto_engineering.loop.event_store import SQLiteEventStore

        thread_id, _lease = _event_thread_context(cwd)
        if not thread_id:
            return {"completion_pct": 0.0, "total_tasks": 0, "done_tasks": 0, "node_count": 0}
        with SQLiteEventStore(event_db) as events:
            state = events.load_projection(thread_id)
        if state is None:
            return {"completion_pct": 0.0, "total_tasks": 0, "done_tasks": 0, "node_count": 0}
        pt_json = state.progress_tree_json
    except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError):
        _logger.debug("EventStore progress 读取失败", exc_info=True)
        return {"completion_pct": 0.0, "total_tasks": 0, "done_tasks": 0, "node_count": 0}
    try:
        from auto_engineering.engine.progress_tree import ProgressTree
        tree = ProgressTree.from_dict(json.loads(pt_json)) if pt_json else None
        if tree:
            return tree.summary()
    except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
        pass
    return {"completion_pct": 0.0, "total_tasks": 0, "done_tasks": 0, "node_count": 0}


def _display_progress_tree(cwd: Path) -> None:
    """显示进度树 (Phase 40 T180, 合并自 progress.py)."""
    try:
        from auto_engineering.cli.progress import _load_progress_tree
        tree = _load_progress_tree(cwd)
        if tree:
            click.echo(tree.display())
        else:
            click.echo("  (暂无进度数据)")
    except (ImportError, ValueError, TypeError, OSError) as e:
        _logger.debug("进度树加载失败: %s", e)
        click.echo("  (进度树暂不可用)")
