"""质量门 — Guardrail 体系(Phase 2 升级).

Phase 2 决策(P0-18): Gate 升级为 Guardrail(4 态:pass/block/drop/retry).
    - Gate (2 态 passed/failed) → GuardrailResult (4 态)
    - Gate 基类(Gate.check) → GuardrailHandler Protocol (duck typing)
    - gates/gates.py 4 个具体 Gate 实现 → gates/builtin.py 5 个 Guardrail

向后兼容:
    - Gate / GateResult 类保留(其他代码可能 import)
    - PlanExistsGate / GitCleanGate / TestsPassGate / GitDiffExistsGate 已删除(无外部使用)

核心 API:
    GuardrailResult        — 4 态结果 (pass/block/drop/retry)
    DropOutput             — AutoGen DropMessage 风格 sentinel
    GuardrailHandler       — Protocol,实现 check() 即是 Guardrail
    GuardrailChain         — 多 Guardrail 链式执行,首个非 pass 短路

内置 Guardrail(gates/builtin):
    RequirementGuardrail    — requirement 非空
    PlanExistsGuardrail     — plan 文件存在
    GitCleanGuardrail       — git status 干净
    TestsPassGuardrail      — pytest 绿
    GitDiffExistsGuardrail  — 有 commit 可审查
"""

from __future__ import annotations

# Gate 基类(向后兼容,Phase 1 遗留)
from .base import Gate, GateResult
from .builtin import (
    GitCleanGuardrail,
    GitDiffExistsGuardrail,
    PlanExistsGuardrail,
    RequirementGuardrail,
    TestsPassGuardrail,
)

# Guardrail 体系(Phase 2 新)
from .guardrail import (
    DropOutput,
    GuardrailChain,
    GuardrailHandler,
    GuardrailResult,
)

__all__ = [
    "DropOutput",
    "Gate",
    "GateResult",
    "GitCleanGuardrail",
    "GitDiffExistsGuardrail",
    "GuardrailChain",
    "GuardrailHandler",
    "GuardrailResult",
    "PlanExistsGuardrail",
    "RequirementGuardrail",
    "TestsPassGuardrail",
]
