"""v2.0 Phase 04 — 7 道 Gate + 向后兼容层.

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2.

Phase 04 新增:
    - Gate.run(project_root) 接口 → Verdict
    - Verdict 数据类(passed / message / gate_name)
    - 7 道 Gate: safety / lint / type_check / contract / test / coverage / build

向后兼容(Phase 1 / Phase 2):
    - Gate 基类保留(check 接口保留供 Guardrail 体系使用)
    - GuardrailResult / DropOutput / GuardrailChain 不动
    - 5 个内置 Guardrail 不动
"""

from __future__ import annotations

# v1.1 Guardrail 体系(向后兼容)
from .base import Gate, GateResult, Verdict

# v2.0 Phase 04 — 7 道 Gate
from .build import BuildGate
from .builtin import (
    GitCleanGuardrail,
    GitDiffExistsGuardrail,
    PlanExistsGuardrail,
    RequirementGuardrail,
    TestsPassGuardrail,
)
from .contract import ContractGate
from .coverage import CoverageGate

# Guardrail 体系(向后兼容)
from .guardrail import (
    DropOutput,
    GuardrailChain,
    GuardrailHandler,
    GuardrailResult,
)
from .lint import LintGate
from .safety import SafetyGate
from .test import TestGate
from .type_check import TypeCheckGate

# v2.0 7 道 Gate 的注册表(便于 Orchestrator 调度)
V2_GATES: list[type[Gate]] = [
    SafetyGate,
    LintGate,
    TypeCheckGate,
    ContractGate,
    TestGate,
    CoverageGate,
    BuildGate,
]


__all__ = [
    "V2_GATES",
    "BuildGate",
    "ContractGate",
    "CoverageGate",
    # 向后兼容
    "DropOutput",
    "Gate",
    "GateResult",
    "GitCleanGuardrail",
    "GitDiffExistsGuardrail",
    "GuardrailChain",
    "GuardrailHandler",
    "GuardrailResult",
    "LintGate",
    "PlanExistsGuardrail",
    "RequirementGuardrail",
    # v2.0 7 道 Gate
    "SafetyGate",
    "TestGate",
    "TestsPassGuardrail",
    "TypeCheckGate",
    # v2.0 新接口
    "Verdict",
]