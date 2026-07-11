"""CLI checkpoint 命令 — list / show / resume / v2 / migrate.

从 cli/__init__.py 拆分 (Plan P1-B, 原 cli.py §702-1030).
"""

from __future__ import annotations

import json as _json
import logging
import sqlite3
from pathlib import Path

import click

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.checkpoint import CheckpointNotFoundError, SQLiteCheckpointStore
from auto_engineering.loop.checkpoint.migration import migrate_v1_to_v2

_logger = logging.getLogger("ae.cli.checkpoint")


def _get_checkpoint_dir() -> Path:
    """返回 .ae-state/ 目录路径 (相对于 cwd). 不自动创建."""
    return Path.cwd() / ".ae-state"


def _cli_error(msg: str) -> None:
    """Echo error to stderr + log + SystemExit(1). P2-14: 集中退出码. 无 except 场景 (无 exc_info)."""
    _logger.warning("%s", msg)
    click.echo(f"[error] {msg}", err=True)
    raise SystemExit(1)


def _cli_fatal(msg: str) -> None:
    """Log error + echo to stderr + SystemExit(1). P1-12: 消除 8 处重复 try-except-log 模式."""
    _logger.error("%s", msg, exc_info=True)
    click.echo(f"[error] {msg}", err=True)
    raise SystemExit(1)


def _cli_warn(msg: str) -> None:
    """Log warning + echo to stderr (non-fatal). P1-12: 消除 8 处重复 try-except-log 模式."""
    _logger.warning("%s", msg, exc_info=True)
    click.echo(f"[warn] {msg}", err=True)


def _iter_checkpoint_stores(cp_dir: Path):
    """遍历 .ae-state/ 下所有 SQLite DB, yield (store, db_file).

    v5.4 审计 P2-10: 提取 5 处重复的 "for db_file in sorted(cp_dir.glob('*.db'))" 模式.
    """
    for db_file in sorted(cp_dir.glob("*.db")):
        try:
            store = SQLiteCheckpointStore(str(db_file))
            yield store, db_file
        except (OSError, sqlite3.Error, ValueError) as e:
            _cli_warn(f"skip {db_file.name}: {e}")


# ============================================================
# Phase 1.1 + v2.3 P0-B: ae checkpoint list / show / resume
# ============================================================


def register_checkpoint_commands(main: click.Group) -> None:
    """向 main Click Group 注册所有 checkpoint 命令."""

    @main.group()
    def checkpoint():
        """Checkpoint 管理(list / show / resume)."""

    @checkpoint.command("save")
    @click.option("--round", type=int, required=True, help="当前轮次 (对应 EngineState, 必填)")
    @click.option("--step", type=int, default=0, help="当前 step (默认 0)")
    @click.option("--tag", type=str, default=None, help="可选标签 (如 'interrupted')")
    @click.option("--state-file", type=click.Path(exists=True), default=None, help="JSON 文件路径 (含 EngineState 序列化数据)")
    @click.option("--checkpoint-id", type=str, default=None, help="显式指定 checkpoint_id (默认自动 UUID)")
    def checkpoint_save_cmd(round: int, step: int, tag: str | None, state_file: str | None, checkpoint_id: str | None):
        """保存 checkpoint (供 stop hook / 手动触发).

        默认从 stdin 读取 JSON state, --state-file 指定则从文件读取.
        保存到当前目录 .ae-state/ae-checkpoints.db.
        """
        state_data: dict = {}
        if state_file:
            with open(state_file) as f:
                state_data = _json.load(f)
        else:
            try:
                state_data = _json.loads(click.get_text_stream("stdin").read())
            except (ValueError, OSError):
                _logger.warning("stdin JSON 解析失败, 回退空 state", exc_info=True)
                state_data = {}

        if not state_data and not isinstance(state_data, dict):
            _cli_error("无法解析 state JSON (stdin 或 --state-file)")

        try:
            state = EngineState.from_dict(state_data)
        except Exception as e:
            _cli_fatal(f"无法解析 EngineState: {e}")

        cp_dir = _get_checkpoint_dir()
        cp_dir.mkdir(exist_ok=True)
        db_path = cp_dir / "ae-checkpoints.db"

        try:
            store = SQLiteCheckpointStore(str(db_path))
            cp_id = store.save(
                state=state if isinstance(state, EngineState) else state_data,  # type: ignore[arg-type]
                round=round,
                step=step,
                tag=tag or "manual",
                checkpoint_id=checkpoint_id,
            )
        except Exception as e:
            _cli_fatal(f"save checkpoint failed: {e}")

        click.echo(f"Checkpoint saved: {cp_id}")
        click.echo(f"  round={round}, step={step}, tag={tag or 'manual'}, db={db_path}")

    @checkpoint.command("list")
    def checkpoint_list_cmd():
        """列出所有 checkpoint (v2.3 P0-B: 切到 SQLiteCheckpointStore).

        历史: v2.0 用 engine.checkpoint.CheckpointStore (v2.5 P0-FINAL 已删除, BEACON 决策 27).
        v2.0/v2.3: 用 loop.checkpoint.SQLiteCheckpointStore (与 v2.0 子命令共用).
        """
        cp_dir = _get_checkpoint_dir()
        if not cp_dir.exists():
            click.echo("(no checkpoint directory)")
            return

        all_checkpoints: list[dict] = []
        for store, db_file in _iter_checkpoint_stores(cp_dir):
            try:
                for meta in store.list_all():
                    all_checkpoints.append(
                        {
                            "id": meta.id,
                            "round": meta.round,
                            "step": meta.step,
                            "schema_version": meta.schema_version,
                            "created_at": meta.created_at.isoformat(),
                            "db_file": db_file.name,
                        }
                    )
            except Exception as e:
                _cli_warn(f"read {db_file.name} failed: {e}")
                continue

        if not all_checkpoints:
            click.echo("(no checkpoints)")
            return

        click.echo(
            f"{'ID':<36} {'ROUND':>5} {'STEP':>4}  {'SCHEMA':>6}  {'DB':<20} CREATED"
        )
        click.echo("-" * 100)
        for cp in all_checkpoints:
            click.echo(
                f"{cp['id'][:34]:<36} {cp['round']:>5} {cp['step']:>4}  "
                f"{cp['schema_version']:>6}  {cp['db_file'][:18]:<20} {cp['created_at']}"
            )

    @checkpoint.command("show")
    @click.argument("checkpoint_id")
    def checkpoint_show_cmd(checkpoint_id: str):
        """查看 checkpoint 详情 (v2.3 P0-B: 切到 SQLiteCheckpointStore).

        历史: v2.0 用 engine.checkpoint.CheckpointStore.load_checkpoint
        (v2.5 P0-FINAL 已删除, BEACON 决策 27).
        v2.0/v2.3: 用 loop.checkpoint.SQLiteCheckpointStore.load.
        """
        cp_dir = _get_checkpoint_dir()
        if not cp_dir.exists():
            _cli_error(f"no checkpoint directory: {cp_dir}")

        for store, db_file in _iter_checkpoint_stores(cp_dir):
            try:
                cp = store.load(checkpoint_id)
            except CheckpointNotFoundError:
                continue
            except Exception as e:
                _cli_warn(f"error reading {db_file.name}: {e}")
                continue
            click.echo(f"ID:            {cp.id}")
            click.echo(f"Round:         {cp.round}")
            click.echo(f"Step:          {cp.step}")
            click.echo(f"Schema:        {cp.schema_version}")
            click.echo(f"Parent:        {cp.parent_id or '(none)'}")
            click.echo(f"Tag:           {cp.tag or '(none)'}")
            click.echo(f"Created At:    {cp.created_at.isoformat()}")
            click.echo("State:")
            if isinstance(cp.state, dict):
                for k, v in cp.state.items():
                    val_str = str(v)[:120] if v else "(empty)"
                    click.echo(f"  {k}: {val_str}")
            else:
                click.echo(f"  {cp.state!r:.200}")
            click.echo(f"History ({len(cp.history)} entries):")
            for i, h in enumerate(cp.history[:5]):
                click.echo(f"  [{i}] {str(h)[:120]}")
            if len(cp.history) > 5:
                click.echo(f"  ... ({len(cp.history) - 5} more)")
            return

        _cli_error(f"Checkpoint '{checkpoint_id}' not found")

    @checkpoint.command("validate")
    @click.argument("checkpoint_id")
    def checkpoint_validate_cmd(checkpoint_id: str):
        """验证 checkpoint 是否存在 (不执行恢复).

        用途: 检查 checkpoint 是否可恢复, 输出 checkpoint 详情.
        实际恢复: 使用 `ae dev-loop` — 它会自动检测中断并提示 resume.
        """
        cp_dir = _get_checkpoint_dir()
        if not cp_dir.exists():
            _cli_error(f"no checkpoint directory: {cp_dir}")

        for store, db_file in _iter_checkpoint_stores(cp_dir):
            try:
                store.load(checkpoint_id)  # 验证存在
            except CheckpointNotFoundError:
                continue
            except Exception as e:
                _cli_warn(f"error reading {db_file.name}: {e}")
                continue
            click.echo(f"Checkpoint '{checkpoint_id}' is valid")
            click.echo(
                "实际恢复请使用 `ae dev-loop` — 它会自动检测中断并提示 resume"
            )
            return

        _cli_error(f"Checkpoint '{checkpoint_id}' not found")

    # ============================================================
    # v2.0 Phase 04: ae checkpoint v2 list/show (SQLite v2.0 store)
    # ============================================================

    @checkpoint.group("v2")
    def checkpoint_v2():
        """v2.0 Checkpoint 操作(SQLite 持久化)."""

    @checkpoint_v2.command("list")
    @click.option("--round", type=int, default=None, help="按 round 过滤")
    def checkpoint_v2_list_cmd(round: int | None) -> None:
        """列出 v2.0 Checkpoint (按 round ASC, created_at ASC)."""
        cp_dir = _get_checkpoint_dir()
        if not cp_dir.exists():
            click.echo("(no checkpoint directory)")
            return

        all_checkpoints: list[dict] = []
        for store, db_file in _iter_checkpoint_stores(cp_dir):
            for meta in store.list_all():
                if round is not None and meta.round != round:
                    continue
                all_checkpoints.append(
                    {
                        "id": meta.id,
                        "round": meta.round,
                        "step": meta.step,
                        "created_at": meta.created_at.isoformat(),
                        "schema_version": meta.schema_version,
                        "tag": meta.tag,
                        "db_file": db_file.name,
                    }
                )

        if not all_checkpoints:
            click.echo("(no v2 checkpoints)")
            return

        click.echo(
            f"{'ID':<36} {'ROUND':>5} {'STEP':>4}  {'SCHEMA':>6}  {'DB':<20} TAG"
        )
        click.echo("-" * 90)
        for cp in all_checkpoints:
            click.echo(
                f"{cp['id'][:34]:<36} {cp['round']:>5} {cp['step']:>4}  "
                f"{cp['schema_version']:>6}  {cp['db_file'][:18]:<20} {cp['tag'] or ''}"
            )

    @checkpoint_v2.command("show")
    @click.argument("checkpoint_id")
    def checkpoint_v2_show_cmd(checkpoint_id: str) -> None:
        """查看 v2.0 Checkpoint 详情."""
        cp_dir = _get_checkpoint_dir()
        if not cp_dir.exists():
            _cli_error(f"no checkpoint directory: {cp_dir}")

        for store, db_file in _iter_checkpoint_stores(cp_dir):
            try:
                cp = store.load(checkpoint_id)
            except CheckpointNotFoundError:
                continue
            except Exception as e:
                _cli_warn(f"error reading {db_file.name}: {e}")
                continue
            click.echo(f"ID:            {cp.id}")
            click.echo(f"Round:         {cp.round}")
            click.echo(f"Step:          {cp.step}")
            click.echo(f"Schema:        {cp.schema_version}")
            click.echo(f"Parent:        {cp.parent_id or '(none)'}")
            click.echo(f"Tag:           {cp.tag or '(none)'}")
            click.echo(f"Created At:    {cp.created_at.isoformat()}")
            click.echo("State:")
            if isinstance(cp.state, dict):
                for k, v in cp.state.items():
                    val_str = str(v)[:120] if v else "(empty)"
                    click.echo(f"  {k}: {val_str}")
            else:
                click.echo(f"  {cp.state!r:.200}")
            click.echo(f"History ({len(cp.history)} entries):")
            for i, h in enumerate(cp.history[:5]):
                click.echo(f"  [{i}] {str(h)[:120]}")
            if len(cp.history) > 5:
                click.echo(f"  ... ({len(cp.history) - 5} more)")
            return

        _cli_error(f"v2.0 Checkpoint '{checkpoint_id}' not found")

    @checkpoint_v2.command("delete")
    @click.argument("checkpoint_id")
    def checkpoint_v2_delete_cmd(checkpoint_id: str) -> None:
        """删除 v2.0 Checkpoint."""

        cp_dir = _get_checkpoint_dir()
        if not cp_dir.exists():
            _cli_error(f"no checkpoint directory: {cp_dir}")

        for store, db_file in _iter_checkpoint_stores(cp_dir):
            if store.delete(checkpoint_id):
                click.echo(f"Deleted v2.0 checkpoint '{checkpoint_id}' from {db_file.name}")
                return
        _cli_error(f"v2.0 Checkpoint '{checkpoint_id}' not found")

    # ============================================================
    # v2.3 Phase I (P1.5): ae checkpoint v2 migrate
    # ============================================================

    @checkpoint_v2.command("migrate")
    @click.argument("src_json", type=click.Path(exists=True))
    @click.argument("dst_sqlite", type=click.Path())
    def checkpoint_v2_migrate_cmd(src_json: str, dst_sqlite: str) -> None:
        """迁移 v2.0 JSON checkpoint → v2.0 SQLite.

        用法:
            ae checkpoint v2 migrate <src.json> <dst.sqlite>

        迁移方向: v2.0 → v2.0 (单向, 不可逆).
        """
        try:
            cp_id = migrate_v1_to_v2(Path(src_json), Path(dst_sqlite))
        except Exception as e:
            _cli_fatal(f"迁移失败: {e}")
        click.echo(f"Migrated v2.0 → v2.0: checkpoint_id={cp_id}")
