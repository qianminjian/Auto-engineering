"""设计输入的权威层级与变更策略。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class DesignAuthorityError(ValueError):
    """设计来源试图越权改变 binding design。"""


class DesignSourceAuthority(StrEnum):
    BINDING = "binding"
    ADVISORY = "advisory"


@dataclass(frozen=True, slots=True)
class DesignAuthorityPolicy:
    binding_sources: tuple[str, ...]
    advisory_sources: tuple[str, ...]
    change_policy: str = "user_gate_required"

    @classmethod
    def default(cls) -> DesignAuthorityPolicy:
        return cls(
            binding_sources=("explicit_design", "approved_change"),
            advisory_sources=("research", "agent_assumption"),
        )

    def authority_for(self, source: str) -> DesignSourceAuthority:
        if source in self.binding_sources:
            return DesignSourceAuthority.BINDING
        if source in self.advisory_sources:
            return DesignSourceAuthority.ADVISORY
        raise DesignAuthorityError(f"DESIGN_SOURCE_UNKNOWN: {source}")

    def validate_change(self, *, source: str, requested_authority: str) -> None:
        actual = self.authority_for(source)
        if requested_authority == DesignSourceAuthority.BINDING.value and (
            actual is not DesignSourceAuthority.BINDING
        ):
            raise DesignAuthorityError(
                f"DESIGN_AUTHORITY_ESCALATION: {source} requires user gate"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_sources": list(self.binding_sources),
            "advisory_sources": list(self.advisory_sources),
            "change_policy": self.change_policy,
        }


__all__ = [
    "DesignAuthorityError",
    "DesignAuthorityPolicy",
    "DesignSourceAuthority",
]
