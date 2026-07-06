"""CheckpointManager — 协作策略类, 从 Orchestrator 提取 checkpoint 持久化职责.

v5.4 审计 P0-1: Orchestrator 承担 7+ 种职责 (God Class).
提取 checkpoint save/restore 为 CheckpointManager, Orchestrator 委托调用.
"""

from __future__ import annotations

import logging
from typing import Any

from auto_engineering.loop.checkpoint.records import CheckpointNotFoundError
from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore

_logger = logging.getLogger("ae.loop.checkpoint.manager")


class CheckpointManager:
    """Checkpoint 持久化协作策略 (v5.4 审计 P0-1).

    封装 SQLiteCheckpointStore 的 save/restore 逻辑,
    Orchestrator 通过委托调用, 不再直接操作 store.
    """

    def __init__(self, store: SQLiteCheckpointStore | None = None) -> None:
        self._store = store

    @property
    def store(self) -> SQLiteCheckpointStore | None:
        return self._store

    def save(
        self,
        state: Any,
        round_id: int,
        step: int = 0,
        history: list | None = None,
        tag: str | None = None,
    ) -> str | None:
        """保存 Checkpoint (v5.0 §B7.4).

        行为契约:
            - store 为 None → 跳过 (返回 None), 不影响主流程
            - IO 异常 → 静默吞掉 (不阻塞主循环, 警告 log)

        Returns:
            checkpoint_id (str) — 成功时; None — store 未配置或 state 为 None.
        """
        if self._store is None:
            return None
        if state is None:
            return None
        try:
            return self._store.save(
                state=state,
                round=round_id,
                step=step,
                history=list(history or []),
                tag=tag,
            )
        except Exception:
            _logger.warning(
                "checkpoint save 失败 (round=%s, step=%s): %s",
                round_id, step, exc_info=True,
            )
            return None

    def list_metas(self) -> list:
        """列出所有 checkpoint 元数据."""
        if self._store is None:
            return []
        return self._store.list_all()

    def load(self, checkpoint_id: str):
        """按 ID 加载完整 checkpoint."""
        if self._store is None:
            raise CheckpointNotFoundError("store 未配置")
        return self._store.load(checkpoint_id)

    def count(self) -> int:
        """checkpoint 总数."""
        if self._store is None:
            return 0
        return self._store.count()


__all__ = ["CheckpointManager"]
