"""Inbound Result 的 PII 策略 canonical service。"""

from __future__ import annotations

import logging
from typing import Protocol

from auto_engineering.config.runtime_config import RuntimeConfig
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.actions import ErrorResponse
from auto_engineering.pii.redactor import PIIRedactor

_logger = logging.getLogger("ae.loop.result_inbound_policy")


class InboundPiiTarget(Protocol):
    """PII 策略所需的最小 Orchestrator 视图。"""

    _pii_enabled: bool
    _pii_redactor: PIIRedactor | None
    _runtime_config: RuntimeConfig
    _state: EngineState | None


def apply_inbound_pii_policy(target: InboundPiiTarget, result: dict) -> dict | ErrorResponse:
    """T109d L3: inbound result JSON PII scan/redact/block."""
    if not target._pii_enabled or not target._pii_redactor:
        return result
    inbound = target._runtime_config.pii_inbound
    if inbound == "redact":
        redacted = target._pii_redactor.redact_dict(result)
        # redact_dict(dict) → dict (list 分支不可能，因 result 类型为 dict)
        if isinstance(redacted, dict):
            return redacted
        return result
    findings = target._pii_redactor.scan_dict(result)
    if findings:
        # P2-35: summarize by category for actionable diagnosis
        by_cat: dict[str, int] = {}
        for f in findings:
            cat = getattr(f, "category", "unknown")
            by_cat[cat] = by_cat.get(cat, 0) + 1
        cat_summary = ", ".join(f"{c}:{n}" for c, n in sorted(by_cat.items())[:3])
        _logger.warning(
            "PII detected in inbound result: %d matches (%s)", len(findings), cat_summary)
        if inbound == "block":
            s = target._state
            return ErrorResponse(
                error_code="PII_BLOCKED_INBOUND",
                message=(
                    f"PII detected in inbound result: "
                    f"{len(findings)} matches ({cat_summary}). "
                    f"审查 result JSON 中的 PII 字段后重试"),
                current_state=s.to_dict() if s else None)
    return result

def _apply_result_to_state(self, result: dict) -> None:
    """只准备 Architect 的瞬时 Candidate；持久结果由 Handler 事件提交。"""
