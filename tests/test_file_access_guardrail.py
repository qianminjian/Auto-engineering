"""Tests for FileAccessGuardrail — post-agent file boundary check (T62)."""

from __future__ import annotations

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.guardrail import FileAccessGuardrail


def _make_state(
    files_changed: list[str] | None = None,
    batch_plan: list[dict] | None = None,
) -> EngineState:
    """Build minimal EngineState for guardrail testing."""
    return EngineState(
        requirement="test",
        files_changed=files_changed or [],
        batch_plan=batch_plan or [],
    )


def _batch_plan_with_targets(file_targets: list[str]) -> list[dict]:
    """Build a minimal batch_plan with one batch containing one task."""
    return [{
        "batch_id": "B1",
        "tasks": [{
            "id": "T1",
            "description": "Test task",
            "file_targets": file_targets,
        }],
    }]


class TestFileAccessGuardrail:
    """FileAccessGuardrail — post-developer file access boundary enforcement."""

    @pytest.fixture
    def guardrail(self) -> FileAccessGuardrail:
        return FileAccessGuardrail()

    def test_empty_files_changed_passes(self, guardrail: FileAccessGuardrail) -> None:
        """No files changed → pass."""
        state = _make_state(
            files_changed=[],
            batch_plan=_batch_plan_with_targets(["src/app.py"]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "pass"

    def test_no_batch_plan_passes(self, guardrail: FileAccessGuardrail) -> None:
        """No batch_plan (first run) → skip, pass."""
        state = _make_state(files_changed=["src/app.py"], batch_plan=[])
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "pass"

    def test_no_file_targets_passes(self, guardrail: FileAccessGuardrail) -> None:
        """No file_targets in batch → skip, pass."""
        state = _make_state(
            files_changed=["src/app.py"],
            batch_plan=[{"batch_id": "B1", "tasks": [{"id": "T1", "description": "Test"}]}],
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "pass"

    def test_files_in_targets_passes(self, guardrail: FileAccessGuardrail) -> None:
        """All changed files are within declared targets → pass."""
        state = _make_state(
            files_changed=["src/app.py", "src/utils.py"],
            batch_plan=_batch_plan_with_targets(["src/app.py", "src/utils.py", "tests/test_app.py"]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "pass"

    def test_file_outside_targets_blocks(self, guardrail: FileAccessGuardrail) -> None:
        """A changed file not in targets → block."""
        state = _make_state(
            files_changed=["src/secrets.py"],
            batch_plan=_batch_plan_with_targets(["src/app.py"]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "block"
        assert "src/secrets.py" in result.message

    def test_multiple_out_of_bounds_files_blocked(self, guardrail: FileAccessGuardrail) -> None:
        """Multiple out-of-bounds files all reported."""
        state = _make_state(
            files_changed=["src/a.py", "src/b.py", "src/c.py"],
            batch_plan=_batch_plan_with_targets(["src/a.py"]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "block"
        assert "src/b.py" in result.message
        assert "src/c.py" in result.message

    def test_whitelist_ae_state_allowed(self, guardrail: FileAccessGuardrail) -> None:
        """Files under .ae-state/ are whitelisted (always pass)."""
        state = _make_state(
            files_changed=[".ae-state/checkpoint.db"],
            batch_plan=_batch_plan_with_targets([]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "pass"

    def test_whitelist_scratch_allowed(self, guardrail: FileAccessGuardrail) -> None:
        """Files under _scratch/ are whitelisted (always pass)."""
        state = _make_state(
            files_changed=["_scratch/reports/audit.md"],
            batch_plan=_batch_plan_with_targets([]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "pass"

    def test_non_developer_stage_skips(self, guardrail: FileAccessGuardrail) -> None:
        """Only applies to developer stage — other stages pass."""
        state = _make_state(
            files_changed=["src/secrets.py"],
            batch_plan=_batch_plan_with_targets([]),
        )
        result = guardrail.check(stage="architect", state=state)
        assert result.action == "pass"

    def test_mixed_whitelist_and_oob_blocks(self, guardrail: FileAccessGuardrail) -> None:
        """Whitelisted files don't mask out-of-bounds violations."""
        state = _make_state(
            files_changed=[".ae-state/checkpoint.db", "src/secrets.py"],
            batch_plan=_batch_plan_with_targets(["src/app.py"]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "block"
        assert "src/secrets.py" in result.message
        # Whitelisted file should NOT be in error message
        assert ".ae-state/checkpoint.db" not in result.message

    def test_collects_targets_across_batches_and_tasks(self, guardrail: FileAccessGuardrail) -> None:
        """file_targets are collected from all batches and all tasks."""
        state = _make_state(
            files_changed=["src/x.py"],
            batch_plan=[
                {"batch_id": "B1", "tasks": [{"id": "T1", "file_targets": ["src/a.py"]}]},
                {"batch_id": "B2", "tasks": [{"id": "T2", "file_targets": ["src/x.py"]}]},
            ],
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "pass"
