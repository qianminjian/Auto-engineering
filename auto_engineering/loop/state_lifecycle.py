"""EngineState 生命周期操作。

Stage 路由由 ``loop.stages`` 的 Handler Registry 唯一负责；本模块只承载
跨阶段重试和推进都需要的状态清理，不再提供第二张 Stage 状态机。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from auto_engineering.loop.task_factory import ROLE_FIELD_DEFAULTS, ROLE_FIELD_MAP

if TYPE_CHECKING:
    from auto_engineering.engine.state import EngineState

__all__ = ["clear_stage_fields"]


def clear_stage_fields(state: EngineState, stage: str) -> None:
    """清空指定 Stage 的产出字段，避免重试读取旧结果。"""

    for field_name in ROLE_FIELD_MAP.get(stage, []):
        if field_name in ROLE_FIELD_DEFAULTS:
            setattr(state, field_name, ROLE_FIELD_DEFAULTS[field_name])
