"""宿主 Action 输出边界的结构化错误投影。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def prepare_action_for_cli(
    action: dict,
    root: Path,
    *,
    prepare_action: Callable[..., dict[str, Any]],
    compact_view: bool | None = None,
    include_failure_journal: bool = True,
) -> dict[str, Any]:
    """把宿主租约错误转换为结构化 Action，禁止 CLI 冒出 traceback。"""

    try:
        if compact_view is None and include_failure_journal:
            return prepare_action(action, root)
        return prepare_action(action, root, compact_view=compact_view,
                              include_failure_journal=include_failure_journal)
    except ValueError as exc:
        from auto_engineering.host.runtime_driver import HostRunLeaseError

        if not isinstance(exc, HostRunLeaseError):
            raise
        from auto_engineering.loop.action_responses import ActionError
        from auto_engineering.loop.protocol import action_envelope

        thread_id = action.get("thread_id")
        tick = action.get("tick")
        stage = action.get("stage")
        if not isinstance(thread_id, str) or not thread_id:
            raise
        if not isinstance(tick, int) or isinstance(tick, bool):
            raise
        return action_envelope(
            ActionError(
                error_code=str(exc),
                message="宿主会话身份不可用，未创建运行租约；当前 Action 保留未执行。",
                suggestion=(
                    "请从真实 Claude Code/Codex 会话重新执行恢复操作；"
                    "不要手工伪造 host_session_id。"
                ),
            ).to_dict(),
            thread_id=thread_id,
            tick=tick,
            stage=stage if isinstance(stage, str) else None,
            causation_id=(
                action.get("causation_id")
                if isinstance(action.get("causation_id"), str) else None
            ),
        )
