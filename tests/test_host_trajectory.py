"""Phase 82 T443：完整 Host Contract 轨迹与故障处置。"""

from __future__ import annotations

from pathlib import Path

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.host import HostPlatform
from auto_engineering.loop.action_builder import ActionBuilder
from tests.host_runtime.trajectory_runner import (
    HostTrajectoryError,
    HostTrajectoryRunner,
)


def _action(root: Path) -> dict[str, object]:
    action = ActionBuilder(root).build_action(EngineState(
        thread_id="trajectory",
        current_stage="architect",
        requirement="按设计实现",
    ))
    action["message_id"] = "action-1"
    return action


def test_trajectory_requires_result_submission_to_core(tmp_path: Path) -> None:
    runner = HostTrajectoryRunner(tmp_path, HostPlatform.CODEX)

    with pytest.raises(HostTrajectoryError, match="CORE_RESULT_SUBMITTER_REQUIRED"):
        runner.run(
            _action(tmp_path),
            workers=[lambda invocation: {"plan": "ok", "batch_plan": []}],
            submit_result=None,
        )


def test_trajectory_binds_invocation_receipt_result_and_next_action(
    tmp_path: Path,
) -> None:
    seen_result: dict[str, object] = {}

    def submit(result: dict[str, object]) -> dict[str, object]:
        seen_result.update(result)
        return {"action": "developer", "message_id": "action-2"}

    trajectory = HostTrajectoryRunner(tmp_path, HostPlatform.CODEX).run(
        _action(tmp_path),
        workers=[lambda invocation: {
            "plan": "保留原设计",
            "batch_plan": [{"batch_id": "B1"}],
        }],
        submit_result=submit,
    )

    assert trajectory.events == (
        "action_received", "worker_invoked", "attestation_recorded",
        "proof_completed", "result_submitted", "next_action_received",
    )
    assert seen_result["spawned"] is True
    assert len(seen_result["worker_attestations"]) == 1
    assert trajectory.next_action["action"] == "developer"


def test_partial_multi_worker_completion_fails_closed(tmp_path: Path) -> None:
    action = ActionBuilder(tmp_path).build_action(EngineState(
        thread_id="multi-trajectory",
        current_stage="system_deep_audit",
        requirement="系统审计",
    ))
    action["message_id"] = "action-multi"

    with pytest.raises(HostTrajectoryError, match="WORKER_COUNT_MISMATCH"):
        HostTrajectoryRunner(tmp_path, HostPlatform.CODEX).run(
            action,
            workers=[lambda invocation: {"findings": []}],
            submit_result=lambda result: {"action": "done"},
        )


def test_prompt_hash_drift_fails_before_worker_execution(tmp_path: Path) -> None:
    action = _action(tmp_path)
    action["spawn"]["invocations"][0]["prompt_sha256"] = "b" * 64  # type: ignore[index]
    called = False

    def worker(invocation):
        nonlocal called
        called = True
        return {"plan": "bad"}

    with pytest.raises(Exception, match="WORKER_PROMPT_HASH_MISMATCH"):
        HostTrajectoryRunner(tmp_path, HostPlatform.CODEX).run(
            action,
            workers=[worker],
            submit_result=lambda result: {"action": "done"},
        )
    assert called is False
