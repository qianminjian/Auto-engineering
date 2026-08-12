"""Tests for Stage Checkpoint Gate — --pause-at-stage (T64)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from auto_engineering.host import HostPlatform
from auto_engineering.host.spawn_contract import SpawnPlan
from auto_engineering.host.worker_attestation import WorkerAttestation
from auto_engineering.loop.tick_orchestrator import TickOrchestrator

_VALID_PLAN = (
    "实现组件, 包含完整的 TDD Red-Green-Refactor 循环 + Gate 验证流程, 确保文件隔离检查通过"
)


def _pass_gate_runner(gate_names, project_root):
    return {name: MagicMock(passed=True, message="ok") for name in gate_names}


def _pass_guardrail():
    g = MagicMock()
    g.check.return_value = MagicMock(action="pass")
    return g


def _orchestrator(
    max_rounds: int = 10,
    pause_at_stages: list[str] | None = None,
) -> TickOrchestrator:
    orch = TickOrchestrator(
        gate_runner=_pass_gate_runner,
        guardrail=_pass_guardrail(),
        checkpoint_store=None,
    )
    if pause_at_stages:
        orch.set_pause_at_stages(pause_at_stages)
    return orch


def _make_result_file(data: dict) -> Path:
    f = Path(tempfile.mktemp(suffix=".json"))
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


def _architect_result() -> dict:
    return {
        "stage": "architect",
        "spawned": True,
        "plan": _VALID_PLAN,
        "batch_plan": [{
            "batch_id": "B1",
            "design_section": "B2",
            "component": "Test",
            "depends_on": [],
            "tasks": [{"id": "T1", "description": "Test task",
                       "module_ref": "§B2",
                       "file_targets": ["test.py"]}],
        }],
        "file_list": ["test.py"],
        "contracts": {},
    }


def _architect_result_file(orch: TickOrchestrator) -> Path:
    result = _architect_result()
    token = orch._active_action["spawn_proof_token"]
    proof_path = orch.project_root / ".ae-state" / "spawn-proofs" / f"{token}.json"
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["status"] = "completed"
    proof["completed_at"] = "2026-08-01T00:00:00Z"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    result["spawn_proof_token"] = token
    plan = SpawnPlan.from_action(orch._active_action)
    result["worker_attestations"] = [
        WorkerAttestation.completed(
            platform=HostPlatform.CODEX,
            action_message_id=orch._active_action["message_id"],
            invocation=spec,
            effective_effort=spec.requested_effort,
            isolation_evidence="fork_turns=none",
            visible_capabilities=tuple(sorted(spec.capabilities)),
            actual_model="test-model",
        ).to_dict()
        for spec in plan.invocations
    ]
    for spec in plan.invocations:
        (orch.project_root / spec.receipt_path).write_text(json.dumps({
            "status": "completed", "stage": orch._active_action["stage"],
            "requested_effort": spec.requested_effort,
            "actual_model": "test-model",
        }), encoding="utf-8")
    return _make_result_file(result)


class TestStageCheckpoint:
    """Stage Checkpoint Gate: --pause-at-stage behavior (T64)."""

    def test_pause_at_architect_returns_gate_action_on_init(self) -> None:
        """init with architect in pause-at-stage → gate action."""
        orch = _orchestrator(pause_at_stages=["architect"])
        action = orch.init("test requirement", max_rounds=5)
        assert action["action"] == "gate"
        assert action["stage"] == "architect"
        gate = action["gate"]
        assert gate["type"] == "stage_checkpoint"
        assert gate["id"] == "checkpoint_architect"
        assert "继续" in gate["options"]
        assert "终止 loop" in gate["options"]
        assert gate["default"] == "继续"
        assert gate["timeout_ms"] == 0

    def test_pause_at_critic_returns_gate_action_after_developer(self) -> None:
        """After developer completion with critic in pause-at-stage → gate action."""
        orch = _orchestrator(pause_at_stages=["critic"])
        orch.init("test requirement", max_rounds=5)

        # Simulate architect completion
        action = orch.tick(_architect_result_file(orch))
        assert action["action"] == "developer"

        # Simulate developer completion
        dev_result = _make_result_file({
            "stage": "developer",
            "batch_id": "B1",
            "files_changed": ["test.py"],
            "test_results": {"passed": 3, "failed": 0},
        })
        action = orch.tick(dev_result)
        assert action["action"] == "gate"
        assert action["stage"] == "critic"
        assert action["gate"]["id"] == "checkpoint_critic"

    def test_gate_resolution_continue_proceeds_to_stage(self) -> None:
        """Gate resolution '继续' marks checkpoint and proceeds."""
        orch = _orchestrator(pause_at_stages=["architect"])
        action = orch.init("test requirement", max_rounds=5)
        assert action["action"] == "gate"
        gate_id = action["gate"]["id"]

        # Submit gate resolution via tick
        resolution = _make_result_file({
            "gate_resolution": {"gate_id": gate_id, "resolution": "继续"},
        })
        action = orch.tick(resolution)
        assert action["action"] == "architect"

    def test_gate_resolution_terminate_returns_done(self) -> None:
        """Gate resolution '终止 loop' returns done."""
        orch = _orchestrator(pause_at_stages=["architect"])
        action = orch.init("test requirement", max_rounds=5)
        gate_id = action["gate"]["id"]

        resolution = _make_result_file({
            "gate_resolution": {"gate_id": gate_id, "resolution": "终止 loop"},
        })
        action = orch.tick(resolution)
        assert action["action"] == "done"
        assert action.get("verdict") == "TERMINATED"

    def test_checkpoint_not_triggered_twice_for_same_stage(self) -> None:
        """After passing checkpoint, same stage doesn't trigger again."""
        orch = _orchestrator(pause_at_stages=["architect"])
        action = orch.init("test requirement", max_rounds=5)
        gate_id = action["gate"]["id"]

        # Resolve gate → continue
        resolution = _make_result_file({
            "gate_resolution": {"gate_id": gate_id, "resolution": "继续"},
        })
        action = orch.tick(resolution)
        assert action["action"] == "architect"

        # Simulate architect result → should go to developer
        action = orch.tick(_architect_result_file(orch))
        # Should go to developer, NOT gate again for architect
        assert action["action"] == "developer"

    def test_progress_summary_in_gate_action(self) -> None:
        """Gate action contains progress_summary."""
        orch = _orchestrator(pause_at_stages=["architect"])
        action = orch.init("test requirement", max_rounds=5)
        assert action["action"] == "gate"
        assert "progress_summary" in action
        summary = action["progress_summary"]
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_pause_at_stage_not_in_list_no_gate(self) -> None:
        """Stage not in pause list → no gate, proceeds directly."""
        orch = _orchestrator()  # no pause stages
        action = orch.init("test requirement", max_rounds=5)
        # Should go straight to architect (or gap_scan), not gate
        assert action["action"] != "gate"

    def test_set_pause_at_stages_accepts_string_list(self) -> None:
        """set_pause_at_stages accepts string list."""
        orch = _orchestrator()
        orch.set_pause_at_stages(["architect", "critic"])
        action = orch.init("test requirement", max_rounds=5)
        assert action["action"] == "gate"
        assert action["stage"] == "architect"

    def test_gate_action_includes_all_three_options(self) -> None:
        """Gate action has exactly 3 options: 继续, 审查当前产出, 终止 loop."""
        orch = _orchestrator(pause_at_stages=["architect"])
        action = orch.init("test requirement", max_rounds=5)
        options = action["gate"]["options"]
        assert len(options) == 3
        assert "继续" in options
        assert "审查当前产出" in options
        assert "终止 loop" in options

    def test_gate_resolution_review_returns_review_feedback(self) -> None:
        """Gate resolution '审查当前产出' returns stage action with feedback."""
        orch = _orchestrator(pause_at_stages=["architect"])
        action = orch.init("test requirement", max_rounds=5)
        gate_id = action["gate"]["id"]

        resolution = _make_result_file({
            "gate_resolution": {"gate_id": gate_id, "resolution": "审查当前产出"},
        })
        action = orch.tick(resolution)
        assert action["stage"] == "architect"
        assert "feedback" in action

    def test_gate_resolution_invalid_returns_error(self) -> None:
        """Invalid/unknown gate resolution returns ErrorResponse."""
        orch = _orchestrator(pause_at_stages=["architect"])
        action = orch.init("test requirement", max_rounds=5)
        gate_id = action["gate"]["id"]

        resolution = _make_result_file({
            "gate_resolution": {"gate_id": gate_id, "resolution": "garbage"},
        })
        action = orch.tick(resolution)
        assert action["action"] == "error"
        assert "INVALID_GATE_RESOLUTION" in str(action)

    def test_gate_resolution_empty_string_returns_error(self) -> None:
        """Empty resolution string is treated as invalid → ErrorResponse (T64 audit fix)."""
        orch = _orchestrator(pause_at_stages=["architect"])
        action = orch.init("test requirement", max_rounds=5)
        gate_id = action["gate"]["id"]

        resolution = _make_result_file({
            "gate_resolution": {"gate_id": gate_id, "resolution": ""},
        })
        action = orch.tick(resolution)
        assert action["action"] == "error"
        assert "INVALID_GATE_RESOLUTION" in str(action)

    def test_unknown_stage_warns(self, caplog) -> None:
        """Unknown stage name in set_pause_at_stages produces warning (P2 D3 fix)."""
        orch = _orchestrator()
        import logging
        caplog.set_level(logging.WARNING)
        orch.set_pause_at_stages(["nonexistent_stage", "architect"])
        assert "nonexistent_stage" in caplog.text
        assert "not a known stage" in caplog.text

    def test_progress_summary_without_batch_state(self) -> None:
        """_progress_summary works when _batch_state is None."""
        orch = _orchestrator()
        orch.init("实现功能")
        summary = orch._action_builder.progress_summary(orch._state)
        assert isinstance(summary, str)
        assert "tick=0" in summary
