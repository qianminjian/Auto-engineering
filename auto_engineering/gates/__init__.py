"""Gate 系统 — 8 道 Gate (v5.5).

DEFAULT_GATES (7 道): safety → lint → type_check → audit → contract → test → build
按需 Gate (1 道): deep_audit (仅 critic APPROVE 时触发)

v5.5 P1-1: _tools 提取到独立模块, 消除循环引用.
"""

from __future__ import annotations

from .audit import AuditGate
from .base import Gate, GateVerdict, SubprocessResult, run_gate_command
from .build import BuildGate
from .contract import ContractGate
from .deep_audit import DeepAuditFinding, DeepAuditGate, DeepAuditReport
from .lint import LintGate
from .safety import SafetyGate
from .test_gate import TestGate
from .type_check import TypeCheckGate

__all__ = [
    "AuditGate",
    "DEFAULT_GATES",
    "BuildGate",
    "ContractGate",
    "DeepAuditFinding",
    "DeepAuditGate",
    "DeepAuditReport",
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
    if name == "DEFAULT_GATES":
        from auto_engineering.gates.registry import get_default_gates

        return get_default_gates()
    if name == "Verdict":
        import warnings

        warnings.warn(
            "Verdict 是 GateVerdict 的废弃别名, 将在 v6.0 移除. 请使用 GateVerdict.",
            DeprecationWarning,
            stacklevel=2,
        )
        return GateVerdict
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
