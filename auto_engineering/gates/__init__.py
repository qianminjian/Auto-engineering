"""v2.0 Phase 04 — 7 道 Gate (v2.0 production path).

v2.4 P0-FINAL: v2.0 builtin/guardrail 已移除.
v5.0 §B6.1: 新增 GateVerdict (Verdict 别名, 兼容 1 版本).
v5.0 §B6.1+§B6.2: 新增 DEFAULT_GATES 入口 + run_gates 按 stage 过滤.
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


# v5.0 §B6.1+§B6.2 — DEFAULT_GATES 7 道 Gate 实例列表
# 顺序: safety → lint → type_check → contract → test → coverage → build
# 每个 Gate 实例化时带合理默认参数 (lint 关闭 gitleaks 等)
# - SafetyGate(use_gitleaks=False): dev-loop 不强依赖 gitleaks 命令
# - LintGate() / TypeCheckGate() / ContractGate() / TestGate() / BuildGate(): 全默认
# - CoverageGate(): 永远 skip (BEACON 决策 25), 但保留注册
DEFAULT_GATES: list[Gate] = [
    SafetyGate(use_gitleaks=False),
    LintGate(),
    TypeCheckGate(),
    ContractGate(),
    TestGate(),
    CoverageGate(),
    BuildGate(),
]


__all__ = [
    "DEFAULT_GATES",
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
