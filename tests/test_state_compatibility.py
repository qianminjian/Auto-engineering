from __future__ import annotations

from pathlib import Path

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.execution_control import (
    ExecutionDisposition,
    control_for_action,
)
from auto_engineering.loop.invocation_intent import InvocationIntent
from auto_engineering.loop.state_compatibility import (
    CompatibilityStatus,
    StateCompatibilityInspector,
)
from auto_engineering.project_profile.resolver import (
    ProjectProfileResolution,
    ResolutionStatus,
)


def _intent(root: Path, content: str = "# Design\n") -> InvocationIntent:
    design = root / "design" / "feature.md"
    design.parent.mkdir(exist_ok=True)
    design.write_text(content, encoding="utf-8")
    return InvocationIntent.from_design_doc(root, "design/feature.md")


def _state(intent: InvocationIntent) -> EngineState:
    state = EngineState(
        thread_id="old-thread",
        current_stage="developer",
        design_doc_path=intent.design_doc_path,
    )
    state.project_profile = {
        "paths": {"source_roots": ["src"], "test_roots": ["tests"]},
        "evidence": [],
    }
    state.architecture_baseline = {
        "design_doc": {
            "path": intent.design_doc_path,
            "digest": intent.design_doc_digest.removeprefix("sha256:"),
        }
    }
    return state


def test_same_design_and_existing_declared_roots_are_compatible(tmp_path: Path) -> None:
    intent = _intent(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    report = StateCompatibilityInspector(tmp_path).inspect(
        intent=intent,
        state=_state(intent),
        profile_resolution=ProjectProfileResolution(
            status=ResolutionStatus.RESOLVED,
            profile=None,
        ),
        active_action={"action": "agent", "stage": "developer", "files": ["src/api.py"]},
    )

    assert report.status is CompatibilityStatus.COMPATIBLE
    assert report.reason_codes == ()


def test_changed_design_is_a_conflict(tmp_path: Path) -> None:
    original = _intent(tmp_path, "# Original\n")
    state = _state(original)
    current = _intent(tmp_path, "# Changed\n")

    report = StateCompatibilityInspector(tmp_path).inspect(
        intent=current,
        state=state,
        profile_resolution=ProjectProfileResolution(
            status=ResolutionStatus.RESOLVED,
            profile=None,
        ),
        active_action={"action": "agent", "stage": "developer"},
    )

    assert report.status is CompatibilityStatus.CONFLICT
    assert "design_doc_changed" in report.reason_codes


def test_missing_roots_conflict_even_when_legacy_manifest_still_exists(tmp_path: Path) -> None:
    intent = _intent(tmp_path)
    (tmp_path / ".ae-state").mkdir()
    (tmp_path / ".ae-state" / "init-manifest.json").write_text("{}")

    report = StateCompatibilityInspector(tmp_path).inspect(
        intent=intent,
        state=_state(intent),
        profile_resolution=ProjectProfileResolution(
            status=ResolutionStatus.SETUP_REQUIRED,
            profile=None,
            missing_capabilities=("source_roots",),
        ),
        active_action={"action": "agent", "stage": "developer"},
    )

    assert report.status is CompatibilityStatus.CONFLICT
    assert report.missing_anchors == ("src", "tests")
    assert "project_anchors_missing" in report.reason_codes


def test_missing_state_design_digest_is_corrupt(tmp_path: Path) -> None:
    intent = _intent(tmp_path)
    state = _state(intent)
    state.architecture_baseline = None

    report = StateCompatibilityInspector(tmp_path).inspect(
        intent=intent,
        state=state,
        profile_resolution=ProjectProfileResolution(
            status=ResolutionStatus.SETUP_REQUIRED,
            profile=None,
        ),
        active_action=None,
    )

    assert report.status is CompatibilityStatus.CORRUPT
    assert "state_design_digest_missing" in report.reason_codes


def test_state_reconciliation_decision_gate_waits_for_user() -> None:
    control = control_for_action({
        "action": "gate",
        "gate": {"id": "state_reconciliation", "type": "decision"},
    })

    assert control.disposition is ExecutionDisposition.WAIT_USER
    assert control.reason_code == "STATE_RECONCILIATION_REQUIRED"
