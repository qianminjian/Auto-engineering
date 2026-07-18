"""Tests for FileAccessGuardrail glob pattern matching — pathspec integration (T62a)."""

from __future__ import annotations

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.guardrail import FileAccessGuardrail


def _make_state(
    files_changed: list[str] | None = None,
    batch_plan: list[dict] | None = None,
) -> EngineState:
    return EngineState(
        requirement="test",
        files_changed=files_changed or [],
        batch_plan=batch_plan or [],
    )


def _batch_plan_with_targets(file_targets: list[str]) -> list[dict]:
    return [{
        "batch_id": "B1",
        "tasks": [{
            "id": "T1",
            "description": "Test",
            "file_targets": file_targets,
        }],
    }]


class TestGlobMatching:
    """Glob pattern matching via pathspec in FileAccessGuardrail."""

    @pytest.fixture
    def guardrail(self) -> FileAccessGuardrail:
        return FileAccessGuardrail()

    def test_glob_double_star_matches_nested(self, guardrail: FileAccessGuardrail) -> None:
        """src/**/*.py matches deeply nested Python files."""
        state = _make_state(
            files_changed=["src/deep/nested/module.py"],
            batch_plan=_batch_plan_with_targets(["src/**/*.py"]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "pass"

    def test_glob_double_star_does_not_match_other_types(self, guardrail: FileAccessGuardrail) -> None:
        """src/**/*.py does not match .ts files."""
        state = _make_state(
            files_changed=["src/deep/component.ts"],
            batch_plan=_batch_plan_with_targets(["src/**/*.py"]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "block"

    def test_glob_single_star_matches_flat(self, guardrail: FileAccessGuardrail) -> None:
        """tests/*.py matches flat directory, not nested."""
        state = _make_state(
            files_changed=["tests/test_app.py"],
            batch_plan=_batch_plan_with_targets(["tests/*.py"]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "pass"

    def test_glob_wildcard_question_mark(self, guardrail: FileAccessGuardrail) -> None:
        """Glob ? matches single character."""
        state = _make_state(
            files_changed=["src/p1.py"],
            batch_plan=_batch_plan_with_targets(["src/p?.py"]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "pass"

    def test_glob_bracket_range(self, guardrail: FileAccessGuardrail) -> None:
        """Glob [0-9] matches digit range."""
        state = _make_state(
            files_changed=["src/v1.py"],
            batch_plan=_batch_plan_with_targets(["src/v[0-9].py"]),
        )
        result = guardrail.check(stage="developer", state=state)
        assert result.action == "pass"
