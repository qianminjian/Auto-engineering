"""Unified entry point for all guardrail classes.

Import from here for all guardrail needs:
    from auto_engineering.loop.guardrails import (
        Guardrail, GuardrailResult, Action,
        RequirementValid, PlanExists, GitDiffExists, TestsPass, GitClean,
        NoDeferredBlockingGap, FileAccessGuardrail, AuditTimingGuardrail,
        REDGuardrail, FreshGuardrail, RegressionGuardrail,
        GuardrailChain, MAX_RETRY_PER_STAGE,
    )

Lazy imports are used for classes defined in loop/guardrail.py to avoid a
circular import (loop/guardrail.py → loop/guardrails/stateful.py → package init).
"""

from auto_engineering.engine.guardrail_types import (
    Action,
    Guardrail,
    GuardrailResult,
)
from auto_engineering.loop.guardrails.stateful import (
    FreshGuardrail,
    REDGuardrail,
    RegressionGuardrail,
)

__all__ = [
    "Action",
    "AuditTimingGuardrail",
    "FileAccessGuardrail",
    "FreshGuardrail",
    "GitClean",
    "GitDiffExists",
    "Guardrail",
    "GuardrailChain",
    "GuardrailResult",
    "MAX_RETRY_PER_STAGE",
    "NoDeferredBlockingGap",
    "PlanExists",
    "REDGuardrail",
    "RegressionGuardrail",
    "RequirementValid",
    "TestsPass",
]

# Lazy-imported names (defined in loop/guardrail.py which imports from
# loop/guardrails/stateful.py — can't eagerly import here without a cycle).
_LAZY_NAMES = frozenset({
    "AuditTimingGuardrail",
    "FileAccessGuardrail",
    "GitClean",
    "GitDiffExists",
    "GuardrailChain",
    "MAX_RETRY_PER_STAGE",
    "NoDeferredBlockingGap",
    "PlanExists",
    "RequirementValid",
    "TestsPass",
})


def __getattr__(name: str):
    if name in _LAZY_NAMES:
        from auto_engineering.loop import guardrail as _guardrail_mod
        return getattr(_guardrail_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
