"""T73+T74 Integration tests — ContextOffloader + SessionSummarizer wired into TickOrchestrator.

Test layers:
  Layer 1 (Unit) — existing tests in test_context_offloading.py + test_context_summarization.py
  Layer 2 (Integration) — TickOrchestrator creates and calls ContextOffloader/SessionSummarizer
  Layer 3 (E2E) — full tick flow triggers offload at stage transitions + summary at tick>5

RED phase: These tests FAIL because:
  - TickOrchestrator.__init__() does not accept ContextOffloader or SessionSummarizer
  - _after_architect/_after_developer/_after_critic do not call offload()
  - _build_action does not inject session summary for developer when tick > 5

Design ref: v5.6-Design-Loop.md appendix E §E.2.2 (T53), §E.2.3 (T54).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_engineering.context.offloading import ContextOffloader
from auto_engineering.context.summarization import SessionSummarizer, SessionSummary
from auto_engineering.loop.guardrail import GuardrailChain
from auto_engineering.loop.tick_orchestrator import TickOrchestrator

from .test_tick_orchestrator import _make_result_file, _orchestrator


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


# =============================================================================
# Layer 2 — Integration: SessionSummarizer wired into TickOrchestrator
# =============================================================================


class TestSessionSummarizerWiring:
    """T74: Verify TickOrchestrator integrates SessionSummarizer."""

    def test_orchestrator_accepts_session_summarizer(self, tmp_path: Path) -> None:
        """TickOrchestrator MUST accept an optional SessionSummarizer."""
        mock_llm = MagicMock()
        summarizer = SessionSummarizer(mock_llm)
        orch = TickOrchestrator(
            project_root=tmp_path,
            session_summarizer=summarizer,
            guardrail=GuardrailChain([]),
        )
        assert orch._session_summarizer is not None
        assert isinstance(orch._session_summarizer, SessionSummarizer)

    def test_orchestrator_has_summarizer_attribute_default_none(self) -> None:
        """Without explicit summarizer, _session_summarizer should be None."""
        orch = _orchestrator()
        assert hasattr(orch, "_session_summarizer"), (
            "T74 NOT WIRED: TickOrchestrator has no _session_summarizer attribute"
        )

    def test_developer_action_includes_summary_when_tick_exceeds_threshold(
        self, tmp_path: Path
    ) -> None:
        """When tick > 5 and summarizer is set, developer action includes session summary."""
        mock_llm = MagicMock()
        summarizer = SessionSummarizer(mock_llm)
        orch = TickOrchestrator(
            project_root=tmp_path,
            session_summarizer=summarizer,
            guardrail=GuardrailChain([]),
        )
        orch.init("实现 StageRouter")
        orch._state.batch_plan = _VALID_BATCH_PLAN
        orch._state.plan = _VALID_PLAN
        orch._state.file_list = ["auto_engineering/loop/stage_router.py"]
        orch._after_architect()  # sets up batch_state, advances to developer

        # Simulate high tick count to trigger summarization
        orch._state.tick = 6
        action = orch._build_action()

        assert "session_summary" in action, (
            "T74 NOT WIRED: _build_action does not include session_summary "
            "when tick > 5 and summarizer is configured"
        )

    def test_developer_action_no_summary_when_tick_below_threshold(
        self, tmp_path: Path
    ) -> None:
        """When tick ≤ 5, developer action should NOT include session summary."""
        mock_llm = MagicMock()
        summarizer = SessionSummarizer(mock_llm)
        orch = TickOrchestrator(
            project_root=tmp_path,
            session_summarizer=summarizer,
            guardrail=GuardrailChain([]),
        )
        orch.init("实现 StageRouter")
        orch._state.batch_plan = _VALID_BATCH_PLAN
        orch._state.plan = _VALID_PLAN
        orch._state.file_list = ["auto_engineering/loop/stage_router.py"]
        orch._after_architect()
        orch._state.tick = 3  # below threshold

        action = orch._build_action()

        # No summary when tick ≤ 5
        assert "session_summary" not in action, (
            "session_summary should not be present when tick ≤ 5"
        )
