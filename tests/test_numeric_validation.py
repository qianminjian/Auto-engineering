"""生产边界的数值必须是有限、非负数。"""

from __future__ import annotations

import math

import pytest

from auto_engineering.host.invocation import (
    ActionExecutionContractError,
    ActionExecutionReceipt,
)
from scripts.product_acceptance import ProductAcceptanceError, _number


def _receipt_with(value: float) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "thread_id": "thread-1",
        "action_message_id": "action-1",
        "build_id": "build-1",
        "host_context_id": "context-1",
        "backend": "codex",
        "status": "completed",
        "exit_code": 0,
        "work_file_digests": {},
        "usage": {
            "input_tokens": value,
            "cached_input_tokens": 0,
            "output_tokens": 1,
        },
    }


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_action_receipt_rejects_non_finite_usage(value: float) -> None:
    with pytest.raises(ActionExecutionContractError, match="ACTION_EXECUTION_USAGE_INVALID"):
        ActionExecutionReceipt.from_dict(_receipt_with(value))


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_product_acceptance_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ProductAcceptanceError, match="USAGE_NUMERIC_EVIDENCE_MISSING"):
        _number(value, "USAGE_NUMERIC_EVIDENCE_MISSING")
