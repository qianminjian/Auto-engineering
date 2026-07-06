"""GuardrailFacade — Guardrail 检查协作策略 (v5.4 审计 P1-1).

从 Orchestrator 提取 Guardrail 相关职责:
    - PRE Guardrail 检查 (_step_2d)
    - POST Guardrail 检查 (_step_2f)
Orchestrator 委托调用, 减少 Orchestrator 方法数.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auto_engineering.loop.guardrail import GuardrailChain, handle_guardrail_result

if TYPE_CHECKING:
    from auto_engineering.engine.state import EngineState

_logger = logging.getLogger("ae.loop.guardrail_facade")


class GuardrailFacade:
    """Guardrail 检查协作策略 (v5.4 审计 P1-1).

    封装 PRE/POST guardrail 检查逻辑,
    Orchestrator 通过委托调用, 不再直接持有 guardrail 检查方法.
    """

    def __init__(
        self,
        chain: GuardrailChain | None = None,
        project_root: Path | None = None,
    ) -> None:
        self._chain = chain
        self._project_root = project_root or Path.cwd()
        self._retry_counters: dict[str, int] = {}

    def check_pre(
        self, current_stage: str, state: "EngineState"
    ) -> str:
        """PRE Guardrail 检查. 返回 'pass' / 'stop' / 'retry'.

        None chain → 视为 pass (向后兼容).
        """
        if self._chain is None:
            return "pass"
        result = self._chain.check(
            "pre", current_stage, state, self._project_root
        )
        return handle_guardrail_result(
            result, current_stage, state, self._retry_counters
        )

    def check_post(
        self, current_stage: str, state: "EngineState"
    ) -> str:
        """POST Guardrail 检查. 返回 'pass' / 'stop' / 'retry'."""
        if self._chain is None:
            return "pass"
        result = self._chain.check(
            "post", current_stage, state, self._project_root
        )
        return handle_guardrail_result(
            result, current_stage, state, self._retry_counters
        )


__all__ = ["GuardrailFacade"]
