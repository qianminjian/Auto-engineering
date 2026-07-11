"""Checkpoint 迁移 — Envelope schema_version 迁移 + v1.1 JSON → v2.0 SQLite 遗产迁移.

与 store.py::DB_SCHEMA_VERSION (int, SQLite 表 schema 版本) 不同,
本文件的 ENVELOPE_SCHEMA_VERSION 是 CheckpointEnvelope 数据格式版本 (str).
二者独立演化: 表结构变更不必然触发 envelope 格式变更, 反之亦然.

v5.4 审计 P1-6: 合并 checkpoint_migration/migrate.py 到本文件,
消除顶层 checkpoint_migration/ 独立目录.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from auto_engineering.loop.checkpoint import SQLiteCheckpointStore
from auto_engineering.loop.checkpoint._serialization import LastValueChannel
from auto_engineering.loop.convergence import RoundHistory
from auto_engineering.loop.state import CheckpointEnvelope

# CheckpointEnvelope 数据格式版本 (str, 语义化版本)
ENVELOPE_SCHEMA_VERSION = "1.0"

# 1.0 格式必需字段 → 类型映射
_REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "round": int,
    "step": int,
    "status": str,
    "tasks": dict,
    "task_results": dict,
    "gate_results": dict,
    "signals": list,
    "metrics": dict,
    "channels": dict,
    "channel_versions": dict,
    "schema_version": str,
}

# 0.9 → 1.0 迁移: 缺失字段 → 默认值
_MIGRATE_0_9_DEFAULTS: dict[str, Any] = {
    "step": 0,
    "task_results": {},
    "gate_results": {},
    "signals": [],
    "metrics": {"values": {}},
    "channel_versions": {},
}


def _parse_version(version: str) -> tuple[int, ...]:
    """解析语义化版本字符串为整数元组, 用于可比对.

    NOTE: 这里是严格解析 (每段必须为整数), 与 utils.parse_version 的容错版
    不同。migration 场景需要严格校验 schema_version 格式正确性 —
    格式异常的数据不应静默降级, 而应拒绝迁移 (抛出 ValueError)。
    容错版 parse_version 适用于用户输入 / 配置文件的宽松场景。
    """
    try:
        return tuple(int(p) for p in version.split("."))
    except (ValueError, AttributeError):
        raise ValueError(
            f"Invalid schema_version format: {version!r}. "
            f"Expected semantic version (e.g. '1.0', '0.9')."
        ) from None


def migrate_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """迁移 CheckpointEnvelope dict 到当前 ENVELOPE_SCHEMA_VERSION.

    迁移路径:
      - schema_version == "1.0" (当前) → 直接返回, 不修改
      - schema_version == "0.9" → 添加 1.0 新增字段 (默认值)
      - schema_version < "0.9" → 拒绝 (raise ValueError)
      - 无 schema_version → 按 0.9 处理 (向前兼容)

    Args:
        envelope: CheckpointEnvelope 的 dict 表示 (state_json 反序列化后).

    Returns:
        迁移后的 dict (schema_version 已更新为 ENVELOPE_SCHEMA_VERSION).

    Raises:
        ValueError: schema_version 格式非法或版本过低 (<0.9).
        TypeError: envelope 不是 dict.
    """
    if not isinstance(envelope, dict):
        raise TypeError(
            f"migrate_envelope expects dict, got {type(envelope).__name__}"
        )

    # 获取当前版本
    raw_version = envelope.get("schema_version")

    if raw_version is None:
        # 无版本 → 按 0.9 处理
        current = _parse_version("0.9")
    else:
        if not isinstance(raw_version, str):
            raise ValueError(
                f"schema_version must be str, got {type(raw_version).__name__}: "
                f"{raw_version!r}"
            )
        current = _parse_version(raw_version)

    target = _parse_version(ENVELOPE_SCHEMA_VERSION)

    if current == target:
        # 已是最新, 不修改
        return envelope

    if current > target:
        # 未来版本 → 拒绝 (不支持降级)
        raise ValueError(
            f"Envelope schema_version {raw_version} is newer than current "
            f"{ENVELOPE_SCHEMA_VERSION}. Downgrade not supported. "
            f"Please upgrade Auto-Engineering."
        )

    # 0.9 → 1.0 迁移
    if current == _parse_version("0.9"):
        return _migrate_0_9_to_1_0(envelope)

    # < 0.9 → 拒绝
    raise ValueError(
        f"Envelope schema_version {raw_version or '0.9 (inferred)'} "
        f"is too old (<0.9). Please re-run 'ae init' to create a fresh "
        f"project environment."
    )


def _migrate_0_9_to_1_0(envelope: dict[str, Any]) -> dict[str, Any]:
    """0.9 → 1.0: 添加 1.0 新增字段 (默认值)."""
    migrated = dict(envelope)  # 浅拷贝, 保留原有所有字段
    for field, default in _MIGRATE_0_9_DEFAULTS.items():
        if field not in migrated:
            migrated[field] = default
    migrated["schema_version"] = ENVELOPE_SCHEMA_VERSION
    return migrated


def validate_envelope(envelope: dict[str, Any]) -> bool:
    """验证 CheckpointEnvelope dict 是否符合当前 ENVELOPE_SCHEMA_VERSION 格式.

    检查项:
      1. envelope 是 dict
      2. schema_version 匹配 ENVELOPE_SCHEMA_VERSION
      3. 所有必需字段存在且类型正确

    Args:
        envelope: CheckpointEnvelope 的 dict 表示.

    Returns:
        True = 格式有效, False = 格式无效.
    """
    if not isinstance(envelope, dict):
        return False

    # 版本检查
    if envelope.get("schema_version") != ENVELOPE_SCHEMA_VERSION:
        return False

    # 字段存在 + 类型检查
    for field, expected_type in _REQUIRED_FIELDS.items():
        if field not in envelope:
            return False
        if not isinstance(envelope[field], expected_type):
            return False

    return True


# ============================================================
# v1.1 JSON → v2.0 SQLite 遗产数据迁移
# ============================================================
# v2.5 状态: 源 engine/checkpoint.py 已 v2.5 P0-FINAL 删除 (BEACON 决策 27).
# 本段保留作为**遗产数据迁移工具** — 用户磁盘上 v1.1 时代产生的 JSON
# checkpoint 可通过本工具一次性迁到 v2.0 SQLite. 不再产生新 v1.1 JSON.
#
# 迁移策略:
#   - CheckpointEnvelope: 提取 v1.1 loop_state.round/step/status + 其他字段注入
#     metrics/tasks/channels (尽力兼容, 未知字段写入 channels 作为 LastValueChannel 留存)
#   - history: 逐项转换为 v2.0 RoundHistory
#
# v2.3 P0-A: 旧名 LoopState (v2.0 Pydantic) 重命名为 CheckpointEnvelope.
# 当前运行时 (v5.x) 使用 engine.state.EngineState (dataclass, 18 字段).
# CheckpointEnvelope 仅作迁移中间格式 — v1.1 JSON → CheckpointEnvelope → SQLite.
# 详见 BEACON.md 决策 23.
# ============================================================


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


def _v1_loop_state_to_v2(v1_data: dict[str, Any]) -> CheckpointEnvelope:
    """v1.1 loop_state (engine.state.LoopState dataclass) → v2.0 CheckpointEnvelope.

    v1.1 loop_state 是 dataclass LoopState.to_dict() 输出 (含 requirement/plan/file_list/...).
    v2.0 CheckpointEnvelope 是 Pydantic model (含 round/step/status/tasks/task_results/channels/metrics).

    字段映射:
        - round/step/status: 直接映射 (标准字段)
        - 其他 v1.1 字段 (requirement/plan/file_list/...): 写入 CheckpointEnvelope.channels
          (LastValueChannel), 保留供后续读出 (无信息丢失)

    Args:
        v1_data: v1.1 checkpoint dict (含 loop_state 子键)

    Returns:
        CheckpointEnvelope (v2.0 Pydantic 实例)
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

    return CheckpointEnvelope(
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
    但 v1.1 迁移场景下保留原始 bool 值 — v2.0-D 之后内部才转 Verdict).

    Args:
        v1_history: v1.1 history 列表

    Returns:
        list[RoundHistory] (v2.0 dataclass)
    """
    result: list[RoundHistory] = []
    for idx, h in enumerate(v1_history):
        if not isinstance(h, dict):
            continue
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

    v2.5 P0-FINAL 后仅作遗产数据迁移工具 (源 engine/checkpoint.py 已退役,
    BEACON 决策 27). 不再产生新 v1.1 JSON.

    步骤:
        1. 读 v1.1 JSON (load_v1_checkpoint)
        2. 构造 v2.0 CheckpointEnvelope (尽力兼容字段)
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

    # 1. 构造 v2.0 CheckpointEnvelope
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


__all__ = [
    "ENVELOPE_SCHEMA_VERSION",
    "load_v1_checkpoint",
    "migrate_envelope",
    "migrate_v1_to_v2",
    "validate_envelope",
]
