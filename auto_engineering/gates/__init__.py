"""v2.0 Phase 04 — 7 道 Gate (v2.0 production path).

v2.4 P0-FINAL: v2.0 builtin/guardrail 已移除.
v5.0 §B6.1: 新增 GateVerdict (Verdict 别名, 兼容 1 版本).
"""

from __future__ import annotations

from .base import Gate, GateResult, GateVerdict, Verdict
from .build import BuildGate
from .contract import ContractGate
from .coverage import CoverageGate
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
    "Gate",
    "GateResult",
    "GateVerdict",
    "LintGate",
    "SafetyGate",
    "TestGate",
    "TypeCheckGate",
    "Verdict",
]
