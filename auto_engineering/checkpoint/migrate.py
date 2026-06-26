"""Checkpoint 迁移: v1.1 JSON (engine/checkpoint.py) → v2.0 SQLite (loop/checkpoint.py).

设计来源: P1.5 审计 — v1.1 与 v2.0 Checkpoint 双轨独立, 用户无法跨版本恢复.
借鉴 LangGraph checkpoint migration 工具思路 (单方向、显式触发、schema 兼容).

v1.1 JSON 格式 (来自 engine/checkpoint.py + engine/state.py):
    {
        "status": "running" | "drained" | ...,
        "loop_state": {<LoopState.to_dict() output>},
        "history": [
            {
                "round_id": int,
                "files_changed": int,
                "lines_added": int,
                "lines_removed": int,
                "gate_results": dict[str, bool],  # v1.1 格式: bool
                "semantic_satisfied": bool | None,
            }
        ]
    }

v2.0 SQLite Schema (loop/checkpoint.py): SQLiteCheckpointStore 表 checkpoints (含 state_json + history_json).

迁移策略:
    - LoopState: 提取 v1.1 loop_state.round/step/status + 其他字段注入 metrics/tasks/channels
      (尽力兼容, 未知字段写入 channels 作为 LastValueChannel 留存)
    - history: 逐项转换为 v2.0 RoundHistory (gate_results 字段保留为 dict[str, bool])
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
from auto_engineering.loop.convergence import RoundHistory
from auto_engineering.loop.state import LastValueChannel, LoopState


def load_v1_checkpoint(path: Path) -> dict[str, Any]:
    """读 v1.1 JSON Checkpoint 文件.

    v1.1 格式: {"status": str, "loop_state": dict, "history": list[dict], ...}
    容错: 缺失可选字段返回空 dict/list (不抛异常).

    Args:
        path: v1.1 JSON 文件路径

    Returns:
        dict (解析后的 v1.1 Checkpoint 数据)
    """
    return json.loads(path.read_text())


def _v1_loop_state_to_v2(v1_data: dict[str, Any]) -> LoopState:
    """v1.1 loop_state → v2.0 LoopState.

    v1.1 loop_state 是 dataclass LoopState.to_dict() 输出 (含 requirement/plan/file_list/...等).
    v2.0 LoopState 是 Pydantic model (含 round/step/status/tasks/task_results/channels/metrics).

    字段映射:
        - round/step/status: 直接映射 (v2.0 标准字段)
        - 其他 v1.1 字段 (requirement/plan/file_list/...): 写入 LoopState.channels
          (LastValueChannel), 保留供 v2.0 后续读出 (无信息丢失)

    Args:
        v1_data: v1.1 checkpoint dict (含 loop_state 子键)

    Returns:
        LoopState (v2.0 Pydantic 实例)
    """
    loop_state_v1 = v1_data.get("loop_state", {})

    # 标准字段
    round_v = int(loop_state_v1.get("round", 0))
    step_v = int(loop_state_v1.get("step", 0))
    status_v = str(v1_data.get("status", "running"))

    # 其他字段 → channels (LastValueChannel)
    standard_fields = {"round", "step", "status"}
    channels: dict[str, Any] = {}
    for k, v in loop_state_v1.items():
        if k in standard_fields:
            continue
        ch: LastValueChannel[Any] = LastValueChannel(name=k)
        ch.set(v)
        channels[k] = ch

    return LoopState(
        round=round_v,
        step=step_v,
        status=status_v,
        channels=channels,
    )


def _v1_history_to_v2(v1_history: list[dict[str, Any]]) -> list[RoundHistory]:
    """v1.1 history 列表 → v2.0 RoundHistory 列表.

    v1.1 history 项字段:
        - round_id, files_changed, lines_added, lines_removed
        - gate_results (dict[str, bool])
        - semantic_satisfied (bool | None)

    v2.0 RoundHistory dataclass 同名字段 (gate_results 改为 dict[str, Verdict],
    但 v1.1 迁移场景下保留原始 bool 值 — Phase 2.3-D 之后 v2 内部才转 Verdict).

    Args:
        v1_history: v1.1 history 列表

    Returns:
        list[RoundHistory] (v2.0 dataclass)
    """
    result: list[RoundHistory] = []
    for idx, h in enumerate(v1_history):
        if not isinstance(h, dict):
            continue
        # round_id 缺失时用 index+1 兜底
        round_id = int(h.get("round_id", idx + 1))
        result.append(
            RoundHistory(
                round_id=round_id,
                files_changed=int(h.get("files_changed", 0)),
                lines_added=int(h.get("lines_added", 0)),
                lines_removed=int(h.get("lines_removed", 0)),
                gate_results=dict(h.get("gate_results", {})),
                semantic_satisfied=h.get("semantic_satisfied"),
                tasks_run=list(h.get("tasks_run", [])),
                task_outcomes=dict(h.get("task_outcomes", {})),
            )
        )
    return result


def migrate_v1_to_v2(src_json: Path, dst_sqlite: Path) -> str:
    """迁移 v1.1 JSON Checkpoint → v2.0 SQLite Checkpoint.

    步骤:
        1. 读 v1.1 JSON (load_v1_checkpoint)
        2. 构造 v2.0 LoopState (尽力兼容字段)
        3. 构造 v2.0 RoundHistory 列表
        4. SQLiteCheckpointStore.save(state, round, step, history) 真存到 SQLite
        5. 返回 checkpoint_id

    Args:
        src_json: v1.1 JSON 文件路径
        dst_sqlite: v2.0 SQLite 数据库文件路径 (不存在则创建)

    Returns:
        checkpoint_id (str) — 可用于 store.load(cp_id) 验证

    Raises:
        FileNotFoundError: src_json 不存在
        json.JSONDecodeError: src_json 不是合法 JSON
        sqlite3.Error: SQLite 写入失败
    """
    v1_data = load_v1_checkpoint(src_json)

    # 1. 构造 v2.0 LoopState
    state = _v1_loop_state_to_v2(v1_data)

    # 2. 构造 v2.0 RoundHistory 列表
    history = _v1_history_to_v2(v1_data.get("history", []))

    # 3. SQLite 持久化
    store = SQLiteCheckpointStore(str(dst_sqlite))
    cp_id = store.save(
        state=state,
        round=state.round,
        step=state.step,
        history=history,
        tag="migrated-from-v1.1",
    )
    return cp_id


__all__ = ["load_v1_checkpoint", "migrate_v1_to_v2"]