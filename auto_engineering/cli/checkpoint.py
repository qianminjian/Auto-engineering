"""CLI checkpoint 命令 — list / show / resume / v2 / migrate.

从 cli/__init__.py 拆分 (Plan P1-B, 原 cli.py §702-1030).
"""

from __future__ import annotations

from pathlib import Path

import click


# ============================================================
# Phase 1.1 + v2.3 P0-B: ae checkpoint list / show / resume
# ============================================================


def register_checkpoint_commands(main: click.Group) -> None:
    """向 main Click Group 注册所有 checkpoint 命令."""

    @main.group()
    def checkpoint():
        """Checkpoint 管理(list / show / resume)."""

    @checkpoint.command("list")
    def checkpoint_list_cmd():
        """列出所有 checkpoint (v2.3 P0-B: 切到 SQLiteCheckpointStore).

        历史: v2.0 用 engine.checkpoint.CheckpointStore (v2.5 P0-FINAL 已删除, BEACON 决策 27).
        v2.0/v2.3: 用 loop.checkpoint.SQLiteCheckpointStore (与 v2.0 子命令共用).
        """
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        cwd = Path.cwd()
        cp_dir = cwd / ".ae-checkpoints"
        if not cp_dir.exists():
            click.echo("(no checkpoint directory)")
            return

        all_checkpoints: list[dict] = []
        for db_file in sorted(cp_dir.glob("*.db")):
            try:
                store = SQLiteCheckpointStore(str(db_file))
            except Exception as e:
                click.echo(f"[warn] skip {db_file.name}: {e}", err=True)
                continue
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
                click.echo(f"[warn] read {db_file.name} failed: {e}", err=True)
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
        from auto_engineering.loop.checkpoint import (
            CheckpointNotFoundError,
            SQLiteCheckpointStore,
        )

        cwd = Path.cwd()
        cp_dir = cwd / ".ae-checkpoints"
        if not cp_dir.exists():
            click.echo(f"(no checkpoint directory: {cp_dir})", err=True)
            raise SystemExit(1)

        for db_file in sorted(cp_dir.glob("*.db")):
            try:
                store = SQLiteCheckpointStore(str(db_file))
                cp = store.load(checkpoint_id)
            except CheckpointNotFoundError:
                continue
            except Exception as e:
                click.echo(f"[warn] error reading {db_file.name}: {e}", err=True)
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

        click.echo(f"Checkpoint '{checkpoint_id}' not found", err=True)
        raise SystemExit(1)

    @checkpoint.command("resume")
    @click.argument("checkpoint_id")
    def checkpoint_resume_cmd(checkpoint_id: str):
        """从 checkpoint 恢复 (v2.3 P0-B: 切到 SQLiteCheckpointStore).

        历史: v2.0 用 engine.checkpoint.CheckpointStore.load_checkpoint
        (v2.5 P0-FINAL 已删除, BEACON 决策 27).
        v2.0/v2.3: 用 loop.checkpoint.SQLiteCheckpointStore.load.
        (实际恢复请使用 `ae dev-loop` — 它会自动检测中断并提示 resume.)
        """
        from auto_engineering.loop.checkpoint import (
            CheckpointNotFoundError,
            SQLiteCheckpointStore,
        )

        cwd = Path.cwd()
        cp_dir = cwd / ".ae-checkpoints"
        if not cp_dir.exists():
            click.echo(f"(no checkpoint directory: {cp_dir})", err=True)
            raise SystemExit(1)

        for db_file in sorted(cp_dir.glob("*.db")):
            try:
                store = SQLiteCheckpointStore(str(db_file))
                store.load(checkpoint_id)  # 验证存在
            except CheckpointNotFoundError:
                continue
            except Exception as e:
                click.echo(f"[warn] error reading {db_file.name}: {e}", err=True)
                continue
            click.echo(f"Resume from checkpoint '{checkpoint_id}'")
            click.echo(
                "(实际恢复请使用 `ae dev-loop` — 它会自动检测中断并提示 resume)"
            )
            click.echo(
                f'使用: ae dev-loop --resume-checkpoint {checkpoint_id} "your requirement"'
            )
            return

        click.echo(f"Checkpoint '{checkpoint_id}' not found", err=True)
        raise SystemExit(1)

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
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        cwd = Path.cwd()
        cp_dir = cwd / ".ae-checkpoints"
        if not cp_dir.exists():
            click.echo("(no checkpoint directory)")
            return

        all_checkpoints: list[dict] = []
        for db_file in sorted(cp_dir.glob("*.db")):
            try:
                store = SQLiteCheckpointStore(str(db_file))
            except Exception as e:
                click.echo(f"[warn] skip {db_file.name}: {e}", err=True)
                continue
            try:
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
            finally:
                pass

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
        from auto_engineering.loop.checkpoint import CheckpointNotFoundError, SQLiteCheckpointStore

        cwd = Path.cwd()
        cp_dir = cwd / ".ae-checkpoints"
        if not cp_dir.exists():
            click.echo(f"(no checkpoint directory: {cp_dir})", err=True)
            raise SystemExit(1)

        for db_file in sorted(cp_dir.glob("*.db")):
            store = SQLiteCheckpointStore(str(db_file))
            try:
                cp = store.load(checkpoint_id)
            except CheckpointNotFoundError:
                continue
            except Exception as e:
                click.echo(f"[warn] error reading {db_file.name}: {e}", err=True)
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

        click.echo(f"v2.0 Checkpoint '{checkpoint_id}' not found", err=True)
        raise SystemExit(1)

    @checkpoint_v2.command("delete")
    @click.argument("checkpoint_id")
    def checkpoint_v2_delete_cmd(checkpoint_id: str) -> None:
        """删除 v2.0 Checkpoint."""
        from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

        cwd = Path.cwd()
        cp_dir = cwd / ".ae-checkpoints"
        if not cp_dir.exists():
            click.echo(f"(no checkpoint directory: {cp_dir})", err=True)
            raise SystemExit(1)

        for db_file in sorted(cp_dir.glob("*.db")):
            store = SQLiteCheckpointStore(str(db_file))
            if store.delete(checkpoint_id):
                click.echo(f"Deleted v2.0 checkpoint '{checkpoint_id}' from {db_file.name}")
                return
        click.echo(f"v2.0 Checkpoint '{checkpoint_id}' not found", err=True)
        raise SystemExit(1)

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
        from auto_engineering.checkpoint.migrate import migrate_v1_to_v2

        try:
            cp_id = migrate_v1_to_v2(Path(src_json), Path(dst_sqlite))
        except Exception as e:
            click.echo(f"[迁移失败] {e}", err=True)
            raise SystemExit(1) from e
        click.echo(f"Migrated v2.0 → v2.0: checkpoint_id={cp_id}")
