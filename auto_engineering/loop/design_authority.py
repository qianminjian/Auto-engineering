"""设计输入的权威层级与变更策略。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class DesignAuthorityError(ValueError):
    """设计来源试图越权改变 binding design。"""


class DesignSourceAuthority(StrEnum):
    BINDING = "binding"
    ADVISORY = "advisory"


@dataclass(frozen=True, slots=True)
class DesignChangeRequest:
    source: str
    source_ref: str
    requested_authority: str
    change_summary: str
    affected_design_refs: tuple[str, ...]
    authority_scope_key: str
    request_id: str
    proposed_change_sha256: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DesignChangeRequest:
        source = value.get("source")
        source_ref = value.get("source_ref")
        requested = value.get("requested_authority")
        summary = value.get("change_summary")
        refs = value.get("affected_design_refs")
        if (
            source not in {"research", "agent_assumption"}
            or not isinstance(source_ref, str)
            or not source_ref
            or requested != "binding"
            or not isinstance(summary, str)
            or not summary.strip()
            or not isinstance(refs, list)
            or not refs
            or any(not isinstance(item, str) or not item for item in refs)
        ):
            raise DesignAuthorityError("DESIGN_CHANGE_REQUEST_INVALID")
        canonical = json.dumps(
            {
                "source": source,
                "source_ref": source_ref,
                "requested_authority": requested,
                "change_summary": summary,
                "affected_design_refs": refs,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        authority_scope = json.dumps(
            {
                "source": source,
                "source_ref": source_ref,
                "affected_design_refs": sorted(set(refs)),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            source=source,
            source_ref=source_ref,
            requested_authority=requested,
            change_summary=summary,
            affected_design_refs=tuple(refs),
            authority_scope_key=hashlib.sha256(authority_scope).hexdigest(),
            request_id=f"change-{digest[:16]}",
            proposed_change_sha256=digest,
        )

    def to_gate(self) -> dict[str, Any]:
        return {
            "id": f"design_change:{self.request_id}",
            "type": "decision",
            "reason_code": "DESIGN_CHANGE_APPROVAL_REQUIRED",
            "question": (
                f"建议来源 {self.source_ref} 请求改变当前设计："
                f"{self.change_summary}。是否批准？"
            ),
            "options": [
                {"id": "approve", "label": "批准变更"},
                {"id": "preserve", "label": "保留原设计"},
            ],
            "change": {
                "request_id": self.request_id,
                "source": self.source,
                "source_ref": self.source_ref,
                "requested_authority": self.requested_authority,
                "change_summary": self.change_summary,
                "affected_design_refs": list(self.affected_design_refs),
                "authority_scope_key": self.authority_scope_key,
                "proposed_change_sha256": self.proposed_change_sha256,
            },
        }


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
    "DesignChangeRequest",
    "DesignSourceAuthority",
]
