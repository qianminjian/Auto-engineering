"""当前启动意图与持久化 Loop 状态的有界兼容检查。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.invocation_intent import InvocationIntent
from auto_engineering.project_profile.resolver import ProjectProfileResolution


class CompatibilityStatus(StrEnum):
    COMPATIBLE = "compatible"
    CONFLICT = "conflict"
    CORRUPT = "corrupt"


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    status: CompatibilityStatus
    reason_codes: tuple[str, ...]
    old_thread_id: str
    old_design_digest: str | None
    current_design_digest: str
    missing_anchors: tuple[str, ...] = ()
    changed_roots: tuple[str, ...] = ()


class StateCompatibilityInspector:
    """只核验状态已声明的固定锚点，不递归探测项目。"""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root.resolve()

    def inspect(
        self,
        *,
        intent: InvocationIntent,
        state: EngineState,
        profile_resolution: ProjectProfileResolution,
        active_action: Mapping[str, Any] | None,
    ) -> CompatibilityReport:
        baseline = state.architecture_baseline
        old_digest = (
            self._baseline_design_digest(baseline)
            or state.design_doc_digest
            or self._active_action_design_digest(active_action)
        )
        if not isinstance(old_digest, str) or not old_digest:
            return self._report(
                CompatibilityStatus.CORRUPT,
                ("state_design_digest_missing",),
                intent,
                state,
                old_digest=None,
            )

        reasons: list[str] = []
        if self._normalize_digest(old_digest) != self._normalize_digest(
            intent.design_doc_digest
        ):
            reasons.append("design_doc_changed")

        roots = self._declared_roots(state.project_profile)
        missing = tuple(
            root for root in roots if not (self._project_root / root).is_dir()
        )
        if missing:
            reasons.append("project_anchors_missing")
        if (
            profile_resolution.profile is None
            and profile_resolution.missing_capabilities
            and "project_profile_unresolved" not in reasons
            and not missing
        ):
            reasons.append("project_profile_unresolved")

        return self._report(
            CompatibilityStatus.CONFLICT if reasons else CompatibilityStatus.COMPATIBLE,
            tuple(reasons),
            intent,
            state,
            old_digest=old_digest,
            missing_anchors=missing,
        )

    @staticmethod
    def _baseline_design_digest(baseline: object) -> str | None:
        if not isinstance(baseline, Mapping):
            return None
        design_doc = baseline.get("design_doc")
        if isinstance(design_doc, Mapping):
            digest = design_doc.get("digest")
            if isinstance(digest, str):
                return digest
        legacy_digest = baseline.get("design_doc_digest")
        return legacy_digest if isinstance(legacy_digest, str) else None

    @staticmethod
    def _active_action_design_digest(
        active_action: Mapping[str, Any] | None,
    ) -> str | None:
        if not isinstance(active_action, Mapping):
            return None
        ledger = active_action.get("design_decision_ledger")
        if not isinstance(ledger, Mapping):
            return None
        digest = ledger.get("source_sha256")
        return digest if isinstance(digest, str) and digest else None

    @staticmethod
    def _normalize_digest(value: str) -> str:
        return value.removeprefix("sha256:")

    @staticmethod
    def _declared_roots(profile: object) -> tuple[str, ...]:
        if not isinstance(profile, Mapping):
            return ()
        paths = profile.get("paths")
        if not isinstance(paths, Mapping):
            return ()
        values: list[str] = []
        for key in ("source_roots", "test_roots"):
            roots = paths.get(key)
            if isinstance(roots, list):
                values.extend(root for root in roots if isinstance(root, str) and root)
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _report(
        status: CompatibilityStatus,
        reasons: tuple[str, ...],
        intent: InvocationIntent,
        state: EngineState,
        *,
        old_digest: str | None,
        missing_anchors: tuple[str, ...] = (),
    ) -> CompatibilityReport:
        return CompatibilityReport(
            status=status,
            reason_codes=reasons,
            old_thread_id=state.thread_id,
            old_design_digest=old_digest,
            current_design_digest=intent.design_doc_digest,
            missing_anchors=missing_anchors,
        )


__all__ = [
    "CompatibilityReport",
    "CompatibilityStatus",
    "StateCompatibilityInspector",
]
