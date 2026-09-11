"""Worker Action generation/fencing 的唯一校验实现。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from auto_engineering.host.worker_evidence_contracts import HostEvidenceValidationError


def resolve_worker_execution_binding(
    action: Mapping[str, Any],
    template: Mapping[str, Any] | None,
    worker_id: str,
) -> tuple[int | None, str | None]:
    """解析并校验 Action 顶层与宿主 Worker 模板的同一代际绑定。"""

    action_generation = action.get("execution_generation")
    action_fence = action.get("fencing_token")
    template_generation = template.get("execution_generation") if template else None
    template_fence = template.get("fencing_token") if template else None
    has_action_binding = action_generation is not None or action_fence is not None
    if has_action_binding:
        if (
            not isinstance(action_generation, int)
            or isinstance(action_generation, bool)
            or action_generation < 1
            or not isinstance(action_fence, str)
            or len(action_fence) != 64
        ):
            raise HostEvidenceValidationError(
                (f"WORKER_EXECUTION_BINDING_INVALID:{worker_id}",)
            )
        if template is None:
            return None, None
        if template_generation != action_generation:
            raise HostEvidenceValidationError(
                (f"WORKER_EXECUTION_BINDING_MISMATCH:{worker_id}",)
            )
        if template_fence is None:
            return action_generation, None
        if not isinstance(template_fence, str) or len(template_fence) != 64:
            raise HostEvidenceValidationError(
                (f"WORKER_EXECUTION_BINDING_INVALID:{worker_id}",)
            )
        return action_generation, template_fence
    if template_generation is None and template_fence is None:
        return None, None
    if (
        not isinstance(template_generation, int)
        or isinstance(template_generation, bool)
        or template_generation < 1
        or not isinstance(template_fence, str)
        or len(template_fence) != 64
    ):
        raise HostEvidenceValidationError(
            (f"WORKER_EXECUTION_BINDING_INVALID:{worker_id}",)
        )
    return template_generation, template_fence


__all__ = ["resolve_worker_execution_binding"]
