"""显式设计决策的可验证账本。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from auto_engineering.loop.events import LoopEvent, LoopEventType


class DesignDecisionError(ValueError):
    """设计影响缺失、越权或范围被非法提升。"""


class DecisionScope(StrEnum):
    CURRENT = "current"
    KNOWN_ISSUE = "known_issue"
    FUTURE = "future"
    OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True, slots=True)
class DesignDecision:
    decision_id: str
    source_ref: str
    scope: DecisionScope
    statement: str
    classification: str
    change_policy: str
    prohibited_promotions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.decision_id
            or not self.source_ref
            or not self.statement
            or self.classification not in {"binding", "advisory"}
            or self.change_policy != "explicit_user_approval"
        ):
            raise DesignDecisionError("DESIGN_DECISION_INVALID")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "source_ref": self.source_ref,
            "scope": self.scope.value,
            "statement": self.statement,
            "classification": self.classification,
            "change_policy": self.change_policy,
            "prohibited_promotions": list(self.prohibited_promotions),
        }


@dataclass(frozen=True, slots=True)
class DesignDecisionLedger:
    decisions: tuple[DesignDecision, ...]
    source_sha256: str = ""
    source_ref: str = ""

    def __post_init__(self) -> None:
        ids = [item.decision_id for item in self.decisions]
        if len(ids) != len(set(ids)):
            raise DesignDecisionError("DESIGN_DECISION_DUPLICATE")

    @property
    def enforcement_status(self) -> str:
        return "full" if self.decisions else "partial"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DesignDecisionLedger:
        raw = value.get("decisions", [])
        if not isinstance(raw, list):
            raise DesignDecisionError("DESIGN_LEDGER_INVALID")
        try:
            source_sha256 = str(value.get("source_sha256", ""))
            if source_sha256 and (
                len(source_sha256) != 64
                or any(char not in "0123456789abcdef" for char in source_sha256)
            ):
                raise DesignDecisionError("DESIGN_LEDGER_SOURCE_INVALID")
            return cls(tuple(
                DesignDecision(
                    decision_id=str(item["decision_id"]),
                    source_ref=str(item["source_ref"]),
                    scope=DecisionScope(item["scope"]),
                    statement=str(item["statement"]),
                    classification=str(item["classification"]),
                    change_policy=str(item["change_policy"]),
                    prohibited_promotions=tuple(item.get("prohibited_promotions", ())),
                )
                for item in raw
            ), source_sha256=source_sha256, source_ref=str(value.get("source_ref", "")))
        except (KeyError, TypeError, ValueError) as exc:
            raise DesignDecisionError("DESIGN_LEDGER_INVALID") from exc

    @classmethod
    def from_project(cls, project_root: Path) -> DesignDecisionLedger:
        path = project_root / ".ae-state" / "design-decision-ledger.json"
        if not path.is_file():
            return cls(())
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DesignDecisionError("DESIGN_LEDGER_INVALID") from exc
        if not isinstance(value, dict):
            raise DesignDecisionError("DESIGN_LEDGER_INVALID")
        return cls.from_dict(value)

    @classmethod
    def ensure_intake(
        cls,
        project_root: Path,
        design_doc_path: Path,
    ) -> DesignDecisionLedger:
        """为显式设计输入建立来源绑定；不从自然语言臆造语义决策。"""

        root = project_root.resolve()
        source = design_doc_path.resolve()
        try:
            source_ref = source.relative_to(root).as_posix()
        except ValueError as exc:
            raise DesignDecisionError("DESIGN_LEDGER_SOURCE_OUTSIDE_PROJECT") from exc
        if not source.is_file():
            raise DesignDecisionError("DESIGN_LEDGER_SOURCE_MISSING")
        source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
        path = root / ".ae-state" / "design-decision-ledger.json"
        if path.is_file():
            ledger = cls.from_project(root)
            ledger.validate_source_binding(
                source_sha256=source_sha256,
                binding_decision_ids=(
                    item.decision_id for item in ledger.decisions
                    if item.classification == "binding"
                ),
            )
            if ledger.source_ref and ledger.source_ref != source_ref:
                raise DesignDecisionError("DESIGN_LEDGER_SOURCE_MISMATCH")
            return ledger

        ledger = cls((), source_sha256=source_sha256, source_ref=source_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(ledger.to_dict(), ensure_ascii=False, indent=2) + "\n"
        fd, temporary = tempfile.mkstemp(prefix=".ledger-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return ledger

    def validate_impacts(
        self,
        impacts: Iterable[dict[str, Any]],
        *,
        approved_changes: dict[str, dict[str, Any]],
    ) -> None:
        impact_list = list(impacts)
        by_id = {str(item.get("decision_id")): item for item in impact_list}
        if len(by_id) != len(impact_list):
            raise DesignDecisionError("DECISION_IMPACT_DUPLICATE")
        known_ids = {item.decision_id for item in self.decisions}
        if any(decision_id not in known_ids for decision_id in by_id):
            raise DesignDecisionError("DECISION_IMPACT_UNKNOWN")
        for decision in self.decisions:
            impact = by_id.get(decision.decision_id)
            if (
                impact is None
                and decision.classification == "binding"
                and decision.scope is DecisionScope.CURRENT
            ):
                raise DesignDecisionError(
                    f"DECISION_IMPACT_MISSING: {decision.decision_id}"
                )
            if impact is None:
                continue
            if impact.get("impact") == "preserve":
                continue
            approval_id = impact.get("approved_change_id")
            approval = approved_changes.get(approval_id) if isinstance(approval_id, str) else None
            if (
                impact.get("impact") != "change"
                or approval is None
                or approval.get("status") != "approved"
                or approval.get("decision_id") != decision.decision_id
                or not approval.get("causation_id")
            ):
                raise DesignDecisionError(
                    f"DESIGN_CHANGE_NOT_APPROVED: {decision.decision_id}"
                )

    @staticmethod
    def project_approved_changes(
        events: Iterable[LoopEvent],
    ) -> dict[str, dict[str, Any]]:
        """只从 Core EventStore 中已解决的设计变更 Gate 投影批准事实。"""

        projected: dict[str, dict[str, Any]] = {}
        for event in events:
            payload = event.payload
            if (
                event.event_type is not LoopEventType.GATE_RESOLVED
                or not event.causation_id
                or payload.get("resolution") != "批准变更"
                or payload.get("status") != "approved"
            ):
                continue
            decision_id = payload.get("decision_id")
            approval_id = payload.get("approval_id")
            if (
                not isinstance(decision_id, str)
                or not isinstance(approval_id, str)
                or payload.get("gate_id") != f"design_change:{decision_id}"
                or approval_id in projected
            ):
                continue
            projected[approval_id] = {
                "decision_id": decision_id,
                "status": "approved",
                "causation_id": event.causation_id,
            }
        return projected

    def validate_gap(self, gap: dict[str, Any]) -> None:
        decision_id = gap.get("decision_id")
        decision = next(
            (item for item in self.decisions if item.decision_id == decision_id),
            None,
        )
        if decision is None:
            return
        if (
            decision.scope in {DecisionScope.FUTURE, DecisionScope.KNOWN_ISSUE}
            and gap.get("scope") == DecisionScope.CURRENT.value
            and gap.get("blocking") is True
        ):
            raise DesignDecisionError(
                f"FUTURE_SCOPE_PROMOTION: {decision.decision_id}"
            )

    def validate_source_binding(
        self,
        *,
        source_sha256: str,
        binding_decision_ids: Iterable[str],
    ) -> None:
        expected_ids = set(binding_decision_ids)
        actual_ids = {
            item.decision_id for item in self.decisions
            if item.classification == "binding"
        }
        if not self.source_sha256 or self.source_sha256 != source_sha256:
            raise DesignDecisionError("DESIGN_LEDGER_SOURCE_MISMATCH")
        if actual_ids != expected_ids:
            raise DesignDecisionError("DESIGN_LEDGER_BINDING_SET_MISMATCH")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "semantic_enforcement": self.enforcement_status,
            "source_sha256": self.source_sha256,
            "source_ref": self.source_ref,
            "decisions": [item.to_dict() for item in self.decisions],
        }


__all__ = [
    "DecisionScope", "DesignDecision", "DesignDecisionError",
    "DesignDecisionLedger",
]
