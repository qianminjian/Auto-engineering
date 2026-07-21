"""Shared guardrail types — GuardrailResult + Guardrail ABC + Action literal.

These pure interface types live in shared/ so that both low-level modules (pii/)
and higher-level modules (engine/, loop/) can depend on them without reverse
dependency issues.

The Guardrail ABC references EngineState only via TYPE_CHECKING — there is no
runtime dependency on the engine layer.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from auto_engineering.engine.state import EngineState

# v5.1 P0-1: Guardrail 3 态动作 (drop 已删除, 仅保留 pass/block/retry)
Action = Literal["pass", "block", "retry"]


@dataclass
class GuardrailResult:
    """Guardrail 检查结果 (§B1.8).

    Fields:
        action: "pass" | "block" | "retry"
                - pass:  通过,继续
                - block: 严重错误,终止主循环
                - retry: 可恢复,retry 计数 + 1
        message: 用户可读消息 (失败原因)

    注: 默认 action="pass" — 大多数 Guardrail pass path 返回纯 pass。

    guardrail_name: 命中的 Guardrail 名 (Chain 在非 pass 时注入).
    """

    action: Action = "pass"
    message: str = ""
    guardrail_name: str = ""

    @property
    def passed(self) -> bool:
        """Convenience: True when action is 'pass'."""
        return self.action == "pass"


class Guardrail(ABC):
    """Guardrail 抽象基类 (§B2.3).

    类属性:
        name: 唯一名 (用于日志/错误)
        timing: "pre" (Stage 执行前) | "post" (Stage 执行后)
        applies_to_stages: 适用的 Stage 元组

    实例方法:
        check(stage, state, project_root=None) → GuardrailResult
    """

    name: str = ""
    timing: Literal["pre", "post"] = "pre"
    applies_to_stages: tuple[str, ...] = ()

    @abstractmethod
    def check(
        self,
        stage: str,
        state: EngineState,
        project_root: Path | None = None,
    ) -> GuardrailResult:
        """执行 Guardrail 检查."""
        ...
