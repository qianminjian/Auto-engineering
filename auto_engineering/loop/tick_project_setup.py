"""TickOrchestrator 的项目画像探测与 Project Setup 边界适配。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.events import LoopEventType
from auto_engineering.loop.project_setup_scope import (
    ProjectSetupScopeOwner,
    is_minimal_setup_source,
    is_minimal_setup_test,
    is_setup_safe_local_import,
    project_setup_files,
    project_setup_scope_violations,
    project_setup_snapshot_files,
)
from auto_engineering.loop.project_setup_service import ProjectSetupService
from auto_engineering.project_profile import (
    ProjectProfile,
    ProjectProfileResolution,
)


class TickProjectSetupMixin(ProjectSetupScopeOwner):
    """承接 Project Setup 投影，避免主 Tick 编排器继续膨胀。"""

    project_root: Path
    _state: EngineState | None
    _project_setup_service: ProjectSetupService
    _tick_gate_runner: Any

    def _queue_domain_event(
        self, event_type: LoopEventType, payload: dict[str, Any]
    ) -> None: ...

    def _complete_project_setup(self) -> dict:
        return self._project_setup_service.complete()

    def _record_project_setup_failure(self, result: dict) -> dict:
        return self._project_setup_service.record_failure(result)

    def _retry_project_setup(self, feedback: str, missing: list[str]) -> dict:
        return self._project_setup_service.retry(feedback, missing)

    def _reject_project_setup_scope(self, violations: dict[str, list[str]]) -> dict:
        return self._project_setup_service.reject_scope(violations)

    def _project_setup_scope_violations(
        self, profile: ProjectProfile | None,
    ) -> dict[str, list[str]]:
        return project_setup_scope_violations(self, profile)

    def _is_minimal_setup_test(self, relative: Path) -> bool:
        return is_minimal_setup_test(self, relative)

    def _is_setup_safe_local_import(self, relative: Path, imported: str) -> bool:
        return is_setup_safe_local_import(self, relative, imported)

    def _is_minimal_setup_source(self, relative: Path) -> bool:
        return is_minimal_setup_source(self, relative)

    def _project_setup_files(self) -> list[str]:
        return project_setup_files(self)

    def _project_setup_snapshot_files(self, profile: ProjectProfile) -> list[str]:
        return project_setup_snapshot_files(self, profile)

    def _apply_project_profile_resolution(
        self, resolution: ProjectProfileResolution,
    ) -> None:
        profile = resolution.profile
        if profile is None:
            return
        state = self._state
        if state is None:
            raise RuntimeError("PROJECT_SETUP_STATE_UNAVAILABLE")
        state.project_profile = profile.to_dict()
        state.project_profile_id = profile.profile_id
        state.missing_project_capabilities = list(resolution.missing_capabilities)
        witnessed = list(state.project_anchor_baseline)
        for root in (*profile.source_roots, *profile.test_roots):
            if root not in witnessed and (self.project_root / root).is_dir():
                witnessed.append(root)
        if witnessed != state.project_anchor_baseline:
            state.project_anchor_baseline = witnessed
            self._queue_domain_event(
                LoopEventType.PROJECT_ANCHORS_WITNESSED,
                {"changes": {"project_anchor_baseline": witnessed}},
            )
        self._tick_gate_runner.reload(profile)
