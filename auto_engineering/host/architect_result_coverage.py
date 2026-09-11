"""Architect Result 的 Worker 计划覆盖校验边界。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from auto_engineering.loop.architect_plan_coverage import (
    architect_plan_coverage_violations,
)


def architect_result_coverage_violations(
    *,
    action: Mapping[str, Any],
    outcomes: Sequence[Any],
    coordinator_payload: Mapping[str, Any],
) -> tuple[str, ...]:
    """阻止 Architect Result 丢失 Worker 已产出的计划。"""

    if action.get("stage") != "architect" or len(outcomes) != 1:
        return ()
    worker_payload = getattr(outcomes[0], "payload", None)
    if not isinstance(worker_payload, Mapping):
        return ("ARCHITECT_RESULT_COVERAGE_INVALID",)
    return architect_plan_coverage_violations(
        worker_payloads=[worker_payload],
        coordinator_payload=coordinator_payload,
    )


__all__ = ["architect_result_coverage_violations"]
