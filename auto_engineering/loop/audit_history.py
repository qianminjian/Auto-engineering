"""v5.5 — JSONL 审计历史日志.

设计来源: design/v5.0-Design-Loop.md §B6.5c

append-only JSONL 审计历史存储:
- 路径: <project_root>/.ae-state/audit-history.jsonl
- 每行一个 JSON 对象: {timestamp, p0_count, p1_count, p2_count, p1_threshold, total_files, plan_refine_triggered}
- 提供 read_history() 读取全部记录, append_entry() 追加一行
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["AuditHistory"]


class AuditHistory:
    """append-only JSONL 审计历史日志存储.

    Args:
        project_root: 项目根目录路径.
    """

    def __init__(self, project_root: Path):
        self._path = Path(project_root) / ".ae-state" / "audit-history.jsonl"

    def append_entry(
        self,
        p0: int,
        p1: int,
        p2: int,
        threshold: int,
        total_files: int,
        plan_refine_triggered: bool,
    ) -> None:
        """追加一条审计记录到 JSONL 文件.

        Args:
            p0: P0 发现数量.
            p1: P1 发现数量.
            p2: P2 发现数量.
            threshold: 当前 P1 阈值.
            total_files: 审计文件总数.
            plan_refine_triggered: 是否触发了 plan refine.
        """
        os.makedirs(self._path.parent, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "p0_count": p0,
            "p1_count": p1,
            "p2_count": p2,
            "p1_threshold": threshold,
            "total_files": total_files,
            "plan_refine_triggered": plan_refine_triggered,
        }
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def read_history(self) -> list[dict]:
        """读取全部审计历史记录.

        Returns:
            list[dict]: 所有记录, 按写入顺序排列.
            文件不存在或为空时返回空列表.
        """
        if not self._path.exists():
            return []
        entries: list[dict] = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
