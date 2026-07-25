"""Tests for FileAccessGuardrail — post-agent file boundary check (T62 + T78 integration).

Test layers:
  Layer 1 (Unit) — FileAccessGuardrail.check() behavior
  Layer 2 (Integration) — GuardrailChain.default() includes G11 and triggers on developer
  Layer 3 (E2E) — default chain check post/developer with out-of-bounds files → block
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.guardrail import FileAccessGuardrail, GuardrailChain


def _make_git_repo(tmp_path: Path) -> Path:
    """Create a clean temp git repo with one commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x",
    }
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@x"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True, capture_output=True, env=env)
    (repo / "seed.txt").write_text("hello\n")
    subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True, capture_output=True, env=env)
    return repo


def _make_state(
    files_changed: list[str] | None = None,
    batch_plan: list[dict] | None = None,
    test_results: dict | None = None,
    plan: str = "",
    file_list: list[str] | None = None,
) -> EngineState:
    """Build minimal EngineState for guardrail testing."""
    kwargs: dict = dict(  # noqa: C408
        requirement="test",
        files_changed=files_changed or [],
        batch_plan=batch_plan or [],
        plan=plan,
    )
    if test_results is not None:
        kwargs["test_results"] = test_results
    if file_list is not None:
        kwargs["file_list"] = file_list
    return EngineState(**kwargs)


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


# =============================================================================
# Layer 2 — Integration: G11 wired into GuardrailChain.default()
# =============================================================================


class TestFileAccessGuardrailIntegration:
    """T78: Verify FileAccessGuardrail is wired into the production call chain.

    These tests FAIL until G11 is registered in GuardrailChain.default().
    This is the "integration wiring" test layer — verifying not just that
    the module works (unit tests above), but that it's actually REACHABLE
    from the production code path.
    """

    def test_g11_is_in_default_chain(self) -> None:
        """GuardrailChain.default() MUST include FileAccessGuardrail (G11).

        RED: Currently default() returns 9 guardrails (G1-G6 + G7 + G8 + G9),
        FileAccessGuardrail is NOT in the chain.
        """
        chain = GuardrailChain.default()
        names = [type(g).__name__ for g in chain.guardrails]
        assert "FileAccessGuardrail" in names, (
            "G11 FileAccessGuardrail is NOT in GuardrailChain.default() — "
            "developer file access is unprotected in production"
        )

    def test_default_chain_has_10_guardrails(self) -> None:
        """After adding G12, default() should have 12 guardrails."""
        chain = GuardrailChain.default()
        assert len(chain.guardrails) == 12, (
            f"Expected 12 guardrails (G1-G12), got {len(chain.guardrails)}"
        )

    def test_default_chain_block_on_out_of_bounds_file(self, tmp_path: Path) -> None:
        """E2E: default chain check post/developer with out-of-bounds file → block.

        Verifies that G11 is not just registered but actually TRIGGERS
        when a developer modifies files outside declared targets.
        """
        repo = _make_git_repo(tmp_path)
        chain = GuardrailChain.default()
        state = _make_state(
            files_changed=["src/secrets.py"],
            batch_plan=_batch_plan_with_targets(["src/app.py"]),
            test_results={"passed": 1, "failed": 0, "errors": 0},
        )
        result = chain.check("post", "developer", state, project_root=repo)
        assert result.action == "block", (
            f"Expected block for out-of-bounds file, got {result.action}. "
            "G11 FileAccessGuardrail is either not in chain or not triggering."
        )
        assert "src/secrets.py" in result.message

    def test_default_chain_pass_when_files_in_targets(self, tmp_path: Path) -> None:
        """E2E: default chain passes when all files are within declared targets."""
        repo = _make_git_repo(tmp_path)
        chain = GuardrailChain.default()
        state = _make_state(
            files_changed=["src/app.py", "tests/test_app.py"],
            batch_plan=_batch_plan_with_targets(["src/app.py", "tests/test_app.py"]),
            test_results={"passed": 1, "failed": 0, "errors": 0},
        )
        result = chain.check("post", "developer", state, project_root=repo)
        assert result.action == "pass", (
            f"Expected pass for in-target files, got {result.action}: {result.message}"
        )

    def test_g11_not_triggered_on_non_developer_stage(self) -> None:
        """G11 only applies to developer stage — architect/critic should not trigger."""
        chain = GuardrailChain.default()
        state = _make_state(
            files_changed=["src/secrets.py"],
            batch_plan=_batch_plan_with_targets(["src/app.py"]),
            plan="test plan",
            file_list=["a.py"],
        )
        # architect stage should not trigger G11
        result = chain.check("post", "architect", state)
        assert result.action == "pass", (
            f"G11 should not trigger on architect stage, got {result.action}"
        )
