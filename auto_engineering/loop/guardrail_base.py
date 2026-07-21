"""Re-export shim — Guardrail types moved to engine/guardrail_types.py (P0-2, 2026-07-21).

Break pii → loop → pii cycle: pii/guardrail.py now imports Guardrail/GuardrailResult
directly from engine/guardrail_types.py. All other consumers continue importing from
loop/guardrail_base.py via this shim for backward compatibility.
"""

from auto_engineering.engine.guardrail_types import (
    Action,
    Guardrail,
    GuardrailResult,
)

__all__ = ["Action", "Guardrail", "GuardrailResult"]
