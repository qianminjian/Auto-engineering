"""T73 Integration tests — ContextOffloader wired into TickOrchestrator.

Test layers:
  Layer 1 (Unit) — existing tests in test_context_offloading.py
  Layer 2 (Integration) — TickOrchestrator creates and calls ContextOffloader
  Layer 3 (E2E) — full tick flow triggers offload at stage transitions

Design ref: v5.6-Design-Loop.md appendix E §E.2.2 (T53).
"""

from __future__ import annotations

from pathlib import Path

from auto_engineering.context.offloading import ContextOffloader
from auto_engineering.loop.guardrail import GuardrailChain
from auto_engineering.loop.tick_orchestrator import TickOrchestrator

from .test_tick_orchestrator import _orchestrator

# =============================================================================
# Helpers
# =============================================================================

_VALID_PLAN = "StageRouter 实现方案: 23 状态转换表 + MAJOR 阈值计数。"

_VALID_BATCH_PLAN = [{
    "batch_id": "B1",
    "design_section": "B2",
    "component": "StageRouter",
    "depends_on": [],
    "tasks": [
        {"id": "T1", "description": "StageDecision + next() 骨架",
         "module_ref": "§B2",
         "file_targets": ["auto_engineering/loop/stage_router.py"]},
    ],
}]

_ARCHITECT_RESULT = {
    "stage": "architect",
    "plan": _VALID_PLAN,
    "batch_plan": _VALID_BATCH_PLAN,
    "file_list": ["auto_engineering/loop/stage_router.py"],
    "contracts": [],
}

_DEVELOPER_RESULT = {
    "stage": "developer",
    "batch_id": "B1",
    "files_changed": ["auto_engineering/loop/stage_router.py"],
    "test_results": {"passed": 5, "failed": 0, "errors": 0, "total": 5},
    "commit_hash": "abc123",
}

_CRITIC_APPROVE_RESULT = {
    "stage": "critic",
    "verdict": "APPROVE",
    "findings": [],
    "strengths": ["Good test coverage"],
}


# =============================================================================
# Layer 2 — Integration: ContextOffloader wired into TickOrchestrator
# =============================================================================


class TestContextOffloaderWiring:
    """T73: Verify TickOrchestrator integrates ContextOffloader."""

    def test_orchestrator_accepts_context_offloader(self, tmp_path: Path) -> None:
        """TickOrchestrator MUST accept an optional ContextOffloader."""
        offloader = ContextOffloader(tmp_path / "offload")
        orch = TickOrchestrator(
            project_root=tmp_path,
            context_offloader=offloader,
            guardrail=GuardrailChain([]),
        )
        assert orch._context_offloader is not None
        assert isinstance(orch._context_offloader, ContextOffloader)

    def test_orchestrator_has_offloader_attribute_default_none(self) -> None:
        """Without explicit offloader, _context_offloader should be None."""
        orch = _orchestrator()
        assert hasattr(orch, "_context_offloader"), (
            "T73 NOT WIRED: TickOrchestrator has no _context_offloader attribute"
        )

    def test_after_architect_calls_offload(self, tmp_path: Path) -> None:
        """_after_architect MUST call offloader.offload() with stage='architect'."""
        offloader = ContextOffloader(tmp_path / "offload")
        orch = TickOrchestrator(
            project_root=tmp_path,
            context_offloader=offloader,
            guardrail=GuardrailChain([]),
        )
        orch.init("实现 StageRouter")
        # Simulate architect result application
        orch._state.batch_plan = _VALID_BATCH_PLAN
        orch._state.plan = _VALID_PLAN
        orch._state.file_list = ["auto_engineering/loop/stage_router.py"]

        orch._after_architect()

        loaded = offloader.load_summary("architect")
        assert loaded is not None, (
            "T73 NOT WIRED: _after_architect did not call offloader.offload()"
        )
        assert loaded.stage == "architect"

    def test_after_developer_calls_offload(self, tmp_path: Path) -> None:
        """_after_developer MUST call offloader.offload() with stage='developer'."""
        offloader = ContextOffloader(tmp_path / "offload")
        orch = TickOrchestrator(
            project_root=tmp_path,
            context_offloader=offloader,
            guardrail=GuardrailChain([]),
            gate_runner=lambda names, root: (True, {}, ""),
        )
        orch.init("实现 StageRouter")
        orch._state.batch_plan = _VALID_BATCH_PLAN
        orch._state.plan = _VALID_PLAN
        orch._state.file_list = ["auto_engineering/loop/stage_router.py"]
        orch._state.current_stage = "developer"
        orch._after_architect()  # sets up batch_state
        orch._state.test_results = {"passed": 5, "failed": 0, "errors": 0}

        orch._after_developer()

        loaded = offloader.load_summary("developer")
        assert loaded is not None, (
            "T73 NOT WIRED: _after_developer did not call offloader.offload()"
        )
        assert loaded.stage == "developer"

    def test_offload_files_persist_across_stage_transitions(self, tmp_path: Path) -> None:
        """After architect→developer→critic sequence, all 3 offloads exist."""
        offloader = ContextOffloader(tmp_path / "offload")
        orch = TickOrchestrator(
            project_root=tmp_path,
            context_offloader=offloader,
            guardrail=GuardrailChain([]),
            gate_runner=lambda names, root: (True, {}, ""),
        )
        orch.init("实现 StageRouter")

        # architect
        orch._state.batch_plan = _VALID_BATCH_PLAN
        orch._state.plan = _VALID_PLAN
        orch._state.file_list = ["auto_engineering/loop/stage_router.py"]
        orch._after_architect()
        assert offloader.load_summary("architect") is not None

        # developer
        orch._state.test_results = {"passed": 5, "failed": 0, "errors": 0}
        orch._after_developer()
        assert offloader.load_summary("developer") is not None

        # critic
        orch._state.critic_verdict = "APPROVE"
        orch._state.findings = []
        orch._after_critic({"verdict": "APPROVE", "findings": []})
        assert offloader.load_summary("critic") is not None, (
            "T73 NOT WIRED: _after_critic did not call offloader.offload()"
        )



