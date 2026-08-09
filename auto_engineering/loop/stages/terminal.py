"""Stage 决策到协议终态 Action 的纯解析器。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auto_engineering.loop.actions import ActionDone, ActionError


def resolve_terminal_action(
    action_context: Mapping[str, Any],
    *,
    terminal_action: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """将 Handler 的结构化终态描述归一为公开协议 Action。"""

    error = action_context.get("error")
    if isinstance(error, Mapping):
        return ActionError(
            error_code=str(error.get("error_code", "STAGE_ERROR")),
            message=str(error.get("message", "Stage 转换失败")),
        ).to_dict()
    terminal = terminal_action or action_context.get("terminal_action")
    if isinstance(terminal, Mapping):
        return ActionDone(
            verdict=str(terminal.get("verdict", "DONE")),
            reason=str(terminal.get("reason", "")),
        ).to_dict()
    return None


__all__ = ["resolve_terminal_action"]
