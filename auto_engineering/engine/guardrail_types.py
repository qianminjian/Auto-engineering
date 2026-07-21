"""Guardrail shared types re-export shim.

GuardrailResult + Guardrail ABC + Action are defined in shared/guardrail.py
so that both low-level modules (pii/) and higher-level modules (engine/, loop/)
can depend on them without reverse dependency issues.

This module re-exports for backward compatibility. New code should import from
auto_engineering.shared.guardrail directly.
"""

from auto_engineering.shared.guardrail import (
    Action,
    Guardrail,
    GuardrailResult,
)

__all__ = ["Action", "Guardrail", "GuardrailResult"]
