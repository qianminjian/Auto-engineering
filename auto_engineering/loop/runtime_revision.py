"""运行时兼容向量与 Action 边界激活策略。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class CompatibilityDecision(StrEnum):
    """恢复时对签发修订与当前修订的确定性判定。"""

    COMPATIBLE = "compatible"
    MIGRATION_REQUIRED = "migration_required"
    ACTIVATE_AFTER_ACTION = "activate_after_action"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class RuntimeRevision:
    """与单个 Action 绑定的运行时语义版本。"""

    protocol_version: str
    event_schema_version: str
    projection_schema_version: str
    action_contract_version: str
    prompt_revision: str
    policy_revision: str
    engine_build_id: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, str) or not value:
                raise ValueError(f"RuntimeRevision.{name} 必须为非空字符串")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RuntimeRevision:
        required = tuple(cls.__dataclass_fields__)
        if set(value) != set(required):
            raise ValueError("RuntimeRevision 字段集合不符合契约")
        return cls(**{name: value[name] for name in required})


def evaluate_compatibility(
    *,
    issued: RuntimeRevision,
    current: RuntimeRevision,
    has_active_action: bool,
) -> CompatibilityDecision:
    """比较签发与当前修订；Prompt/Policy 只在 Action 边界激活。"""

    if (
        issued.protocol_version != current.protocol_version
        or issued.action_contract_version != current.action_contract_version
    ):
        return CompatibilityDecision.INCOMPATIBLE
    if (
        issued.event_schema_version != current.event_schema_version
        or issued.projection_schema_version != current.projection_schema_version
    ):
        return CompatibilityDecision.MIGRATION_REQUIRED
    content_changed = (
        issued.prompt_revision != current.prompt_revision
        or issued.policy_revision != current.policy_revision
    )
    if content_changed and has_active_action:
        return CompatibilityDecision.ACTIVATE_AFTER_ACTION
    return CompatibilityDecision.COMPATIBLE


__all__ = [
    "CompatibilityDecision",
    "RuntimeRevision",
    "evaluate_compatibility",
]
