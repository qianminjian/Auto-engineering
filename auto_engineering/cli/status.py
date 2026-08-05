"""ae status 命令 — v5.0 §B13.2 /status stdout JSON 契约.

实现 7 字段 JSON 输出 + 文本模式兼容:
    thread_id / round / stage / verdict /
    majors_in_a_row / total_majors / recent_history (≤5 条 RoundHistory)

设计:
- `_collect_status_json(cwd)` 是核心函数, 从 .ae-state/*.db 读最新 CheckpointEnvelope
- Click 命令 `status` 包装 `_collect_status_json` + 输出格式化
- 边界: 缺失 checkpoint → 默认 7 字段; corrupted db → 跳过该 db 继续找下一个

引用: design/v5.6-Design-Loop.md §B13.2 stdout JSON 契约
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import click

from auto_engineering.config.environment import ProjectEnvironment
from auto_engineering.engine.state import EngineState

_logger = logging.getLogger("ae.cli.status")


def _is_checkpoint_database(db_file: Path) -> bool:
    """判断 SQLite 文件是否包含旧 checkpoint 表，跳过 EventStore 数据库。"""
    try:
        uri = f"file:{db_file.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            has_table = bool(
                connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name='checkpoints'"
                ).fetchone()
            )
            return has_table or db_file.name != "events.db"
    except (OSError, sqlite3.Error):
        # 只读目录可能无法读取 WAL 中的 sqlite_master；文件职责仍可确定。
        return db_file.name != "events.db"


def _collect_status_json(cwd: Path) -> dict:
    """收集 status JSON 7 字段契约 (v5.0 §B13.2).

    无 checkpoint 时返回 7 字段默认 (recent_history = []).
    corrupted db → 跳过, 找下一个 db.
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

    # v5.8：EventStore 是新协议事实源。只有存在真实 events.db 且项目租约
    # 指向可投影线程时才添加扩展字段，保持无状态/旧 checkpoint 的 7 字段契约。
    event_payload = _collect_event_store_status(cwd)
    if event_payload is not None:
        return event_payload

    from auto_engineering.loop.checkpoint import Checkpoint, SQLiteCheckpointStore

    # 找到 latest checkpoint (跨所有 db)
    latest_ckpt = None
    for db_file in cp_dir.glob("*.db"):
        if not _is_checkpoint_database(db_file):
            continue
        try:
            store: SQLiteCheckpointStore[EngineState]
            with SQLiteCheckpointStore(str(db_file), read_only=True) as store:
                ckpt: Checkpoint[EngineState] | None = store.load_latest()
            if ckpt is not None and (latest_ckpt is None or ckpt.round > latest_ckpt.round):
                latest_ckpt = ckpt
        except (OSError, sqlite3.Error):
            _logger.warning("checkpoint db 读取失败, 跳过: %s", db_file, exc_info=True)
            continue

    if latest_ckpt is None:
        return payload

    state = latest_ckpt.state
    # 提取 state 字段 (兼容 dict / Pydantic BaseModel / dataclass)
    # 注: 源字段是 EngineState.critic_verdict; 对外 JSON key 仍为 "verdict" (§B13.2 不变).
    if isinstance(state, dict):
        payload["thread_id"] = state.get("thread_id", "")
        payload["round"] = state.get("round", 0)
        payload["stage"] = state.get("current_stage", "")
        payload["verdict"] = state.get("critic_verdict", "")
        payload["majors_in_a_row"] = state.get("majors_in_a_row", 0)
        payload["total_majors"] = state.get("total_majors", 0)
    else:
        payload["thread_id"] = getattr(state, "thread_id", "") or ""
        payload["round"] = getattr(state, "round", 0)
        payload["stage"] = getattr(state, "current_stage", "") or ""
        payload["verdict"] = getattr(state, "critic_verdict", "") or ""
        payload["majors_in_a_row"] = getattr(state, "majors_in_a_row", 0)
        payload["total_majors"] = getattr(state, "total_majors", 0)

    # recent_history: 最近 5 条 RoundHistory (按 round_id DESC)
    history = latest_ckpt.history or []
    sorted_hist = sorted(history, key=lambda h: getattr(h, "round_id", 0), reverse=True)[:5]
    payload["recent_history"] = [
        {
            "round_id": getattr(h, "round_id", 0),
            "files_changed": getattr(h, "files_changed", 0),
            "lines_added": getattr(h, "lines_added", 0),
            "lines_removed": getattr(h, "lines_removed", 0),
            "semantic_satisfied": getattr(h, "semantic_satisfied", None),
            "tasks_run": list(getattr(h, "tasks_run", []) or []),
            "task_outcomes": dict(getattr(h, "task_outcomes", {}) or {}),
        }
        for h in sorted_hist
    ]
    return payload


def _collect_event_store_status(cwd: Path) -> dict | None:
    """读取 active EventStore projection；损坏或无租约时返回 None。"""
    cp_dir = cwd / ".ae-state"
    event_db = cp_dir / "events.db"
    if not event_db.exists():
        return None
    try:
        from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
        from auto_engineering.loop.event_store import SQLiteEventStore

        store: SQLiteCheckpointStore[EngineState]
        with SQLiteCheckpointStore(str(cp_dir / "checkpoints.db"), read_only=True) as store:
            thread_id = store.active_project_thread()
        if not thread_id:
            return None
        with SQLiteEventStore(event_db) as events:
            state = events.load_projection(thread_id)
            action = events.load_action_snapshot(thread_id)
        if state is None:
            return None
        return {
            "thread_id": state.thread_id,
            "round": state.round,
            "stage": state.current_stage,
            "verdict": state.critic_verdict,
            "majors_in_a_row": state.majors_in_a_row,
            "total_majors": state.total_majors,
            "recent_history": [],
            "source": "event_store",
            "tick": state.tick,
            "action": action.get("action") if action else None,
            "expected_stage": state.expected_stage,
        }
    except (OSError, sqlite3.Error, ValueError, TypeError):
        _logger.warning("EventStore status 读取失败，回退旧 checkpoint", exc_info=True)
        return None


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

        cp_dir = cwd / ".ae-state"
        if cp_dir.exists():
            from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

            total_v2 = 0
            for db_file in cp_dir.glob("*.db"):
                try:
                    # 2026-07-25 审计修复 (P1-6): with 确保 _file_conn/WAL 句柄关闭
                    store: SQLiteCheckpointStore[EngineState]
                    with SQLiteCheckpointStore(str(db_file), read_only=True) as store:
                        total_v2 += store.count()
                except (OSError, sqlite3.Error):
                    _logger.warning("checkpoint count 失败, 跳过: %s", db_file, exc_info=True)
                    continue
            if total_v2 > 0 and not verbose:
                click.echo(f"  v2.0 Checkpoints: {total_v2} (使用 --verbose 查看进度树)")


def _load_progress_summary(cwd: Path) -> dict:
    """从最新 checkpoint 读取 progress_tree 摘要 (Phase 40 T180)."""
    from auto_engineering.loop.checkpoint import Checkpoint, SQLiteCheckpointStore
    cp_dir = cwd / ".ae-state"
    if not cp_dir.exists():
        return {"completion_pct": 0.0, "total_tasks": 0, "done_tasks": 0, "node_count": 0}
    latest_ckpt = None
    for db_file in cp_dir.glob("*.db"):
        try:
            # 2026-07-25 审计修复 (P1-6): with 确保 _file_conn/WAL 句柄关闭
            store: SQLiteCheckpointStore[EngineState]
            with SQLiteCheckpointStore(str(db_file), read_only=True) as store:
                ckpt: Checkpoint[EngineState] | None = store.load_latest()
                if ckpt is not None and (latest_ckpt is None or ckpt.round > latest_ckpt.round):
                    latest_ckpt = ckpt
        except (OSError, sqlite3.Error):
            continue
    if latest_ckpt is None:
        return {"completion_pct": 0.0, "total_tasks": 0, "done_tasks": 0, "node_count": 0}
    try:
        from auto_engineering.engine.progress_tree import ProgressTree
        # 2026-07-25 审计修复: ProgressTree 无 from_json (仅 from_dict)。原调用
        # 必抛 AttributeError 被下方 except 静默吞噬 → 进度摘要恒为默认值
        # (Phase 40 T180 失效)。
        pt_json = getattr(latest_ckpt.state, "progress_tree_json", None)
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
