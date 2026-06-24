"""Guardrail — 中间件式 4 态质量检查.

参考:
    - CrewAI GuardrailResult(success, result, error)
    - AutoGen InterventionHandler Protocol + DropMessage sentinel
    - v1.0-AUDIT-SUPPLEMENT.md P0-18: Gate 升级为 Guardrail(4 态)

设计要点:
    - Guardrail 是中间件,不是硬编码在 loop 中(可插拔)
    - 4 态:pass / block / drop / retry(对应 errors.py 已有的
      GuardrailBlockedError / OutputDropped / GuardrailRetrySignal)
    - GuardrailChain.run() 短路语义:首个非 pass handler 决定结果

Phase 2 范围:
    - 定义 GuardrailResult / DropOutput / GuardrailHandler Protocol / GuardrailChain
    - 不实现:run() 与 LoopEngine.run() 集成(Phase 3+ 接)
    - 5 个内置 Guardrail 在 gates/builtin.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from auto_engineering.engine.graph import Stage
from auto_engineering.engine.state import LoopState


@dataclass
class GuardrailResult:
    """Guardrail 检查结果.

    action 语义:
        pass   — 通过,继续下一个 Guardrail(最终 pass)
        block  — 阻塞当前 Stage(抛 GuardrailBlockedError)
        drop   — 静默丢弃当前 Stage 输出(抛 OutputDropped)
        retry  — 重试当前 Stage(抛 GuardrailRetrySignal)

    字段:
        action  — 4 态之一
        reason  — 失败原因(block/drop/retry 时填写,便于排查)
        payload — 可选,block/drop/retry 时携带的数据(供上层处理)
    """

    action: str  # "pass" | "block" | "drop" | "retry"
    reason: str = ""
    payload: Any = None


class DropOutput:
    """AutoGen DropMessage 风格 sentinel.

    Guardrail 检查通过 GuardrailResult.action="drop" 表达静默丢弃,
    本类仅作为语义占位(供 Phase 3+ 显式使用,例如 Guardrail 直接返回 DropOutput 实例).
    """


class GuardrailHandler(Protocol):
    """Guardrail 处理器 Protocol. 实现 check() 的对象都是 Guardrail.

    Phase 1 的 Gate 是类继承基类(Gate.check());Phase 2 改为 Protocol(duck typing),
    更轻量且兼容已有 Gate 实现(无需修改 Gate 基类).
    """

    def check(self, stage: Stage, state: LoopState) -> GuardrailResult: ...


@dataclass
class GuardrailChain:
    """Guardrail 链. 顺序执行所有 handler,首个非 pass 决定最终结果.

    短路语义:
        pass   → 继续下一个
        非 pass → 立即返回该 handler 的结果(后续 handler 不调用)

    用法:
        chain = GuardrailChain([
            RequirementGuardrail(),
            PlanExistsGuardrail(),
        ])
        result = chain.run(stage, state)
        if result.action == "block":
            raise GuardrailBlockedError(result.reason)
        # ... drop / retry 类似
    """

    handlers: list[GuardrailHandler] = field(default_factory=list)

    def add(self, handler: GuardrailHandler) -> None:
        """运行时添加 handler. 支持 plugin 式扩展."""
        self.handlers.append(handler)

    def run(self, stage: Stage, state: LoopState) -> GuardrailResult:
        """执行链上所有 handler,返回首个非 pass 结果或最终 pass."""
        for handler in self.handlers:
            result = handler.check(stage, state)
            if result.action != "pass":
                return result
        return GuardrailResult(action="pass")
