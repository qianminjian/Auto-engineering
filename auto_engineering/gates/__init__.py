"""v2.0 Phase 04 — 6 道 Gate (v2.0 production path).

v2.4 P0-FINAL: v2.0 builtin/guardrail 已移除.
v5.0 §B6.1: 新增 GateVerdict.
v5.4 P2-2: Verdict → GateVerdict 统一, Verdict 保留为废弃别名.
v5.0 §B6.1+§B6.2: 新增 DEFAULT_GATES 入口 + run_gates 按 stage 过滤.
v5.4 Q2: CoverageGate 已删除 — 覆盖率检查由 CI 独立负责.
"""

from __future__ import annotations

from .audit import AuditGate
from .base import Gate, GateVerdict, SubprocessResult, run_gate_command
from .build import BuildGate
from .contract import ContractGate
from .lint import LintGate
from .safety import SafetyGate
from .test_gate import TestGate
from .type_check import TypeCheckGate

# v5.4 P1-11: DEFAULT_GATES 已迁移到 gates/registry.py (单一数据源).
# gates/registry.py 的 _build_default_gates() 是唯一的 Gate 构造工厂.
from auto_engineering.gates.registry import DEFAULT_GATES as _default_gates

DEFAULT_GATES: list[Gate] = _default_gates


__all__ = [
    "AuditGate",
    "DEFAULT_GATES",
    "BuildGate",
    "ContractGate",
    "Gate",
    "GateVerdict",
    "LintGate",
    "SafetyGate",
    "SubprocessResult",
    "TestGate",
    "TypeCheckGate",
    "run_gate_command",
]


def __getattr__(name: str) -> object:
    if name == "Verdict":
        import warnings

        warnings.warn(
            "Verdict 是 GateVerdict 的废弃别名, 将在 v6.0 移除. 请使用 GateVerdict.",
            DeprecationWarning,
            stacklevel=2,
        )
        return GateVerdict
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
