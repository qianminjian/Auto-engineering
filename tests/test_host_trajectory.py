"""Phase 82 T443：完整 Host Contract 轨迹与故障处置。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.host import HostPlatform
from auto_engineering.loop.action_builder import ActionBuilder
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.tick_orchestrator import TickOrchestrator
from tests.host_runtime.trajectory_runner import (
    HostTrajectoryError,
    HostTrajectoryRunner,
)


def _core(root: Path, events: SQLiteEventStore) -> tuple[TickOrchestrator, dict]:
    (root / "pyproject.toml").write_text("[project]\nname='trajectory'\n")
    (root / "trajectory").mkdir()
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    core = TickOrchestrator(
        root,
        event_store=events,
        guardrail=guardrail,
        gate_runner=lambda names, project: {
            name: MagicMock(passed=True, message="ok") for name in names
        },
    )
    return core, core.init("按设计实现")


def test_trajectory_requires_core_persisted_active_action(tmp_path: Path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, action = _core(tmp_path, events)
        forged = {**action, "message_id": "forged"}
        runner = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events
        )

        with pytest.raises(HostTrajectoryError, match="CORE_ACTIVE_ACTION_REQUIRED"):
            runner.run(forged, workers=[lambda invocation: {}])


def test_trajectory_binds_invocation_receipt_result_and_next_action(
    tmp_path: Path,
) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, action = _core(tmp_path, events)
        trajectory = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events
        ).run(
            action,
            workers=[lambda invocation: {
                "plan": (
                    "保留原设计并按 TDD 完成实现、测试、审查和构建验证，"
                    "同时执行类型检查、契约校验、失败回归和最终构建验收。"
                ),
                "batch_plan": [{
                    "batch_id": "B1", "component": "core",
                    "tasks": [{
                        "id": "B1-T1", "description": "实现核心",
                        "file_targets": ["trajectory/core.py"],
                    }],
                }],
                "file_list": ["trajectory/core.py"], "contracts": {},
            }],
        )

        assert trajectory.result["spawned"] is True
        assert len(trajectory.result["worker_attestations"]) == 1
        assert "ResultAccepted" in trajectory.events
        assert "ActionIssued" in trajectory.events
        assert trajectory.next_action["action"] == "developer"


def test_partial_multi_worker_completion_fails_closed(tmp_path: Path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, _ = _core(tmp_path, events)
        action = ActionBuilder(tmp_path).build_action(EngineState(
            thread_id="multi-trajectory", current_stage="system_deep_audit",
            requirement="系统审计",
        ))
        with pytest.raises(HostTrajectoryError, match="CORE_ACTIVE_ACTION_REQUIRED"):
            HostTrajectoryRunner(
                tmp_path, HostPlatform.CODEX, core=core, event_store=events
            ).run(action, workers=[lambda invocation: {"findings": []}])


def test_prompt_hash_drift_fails_before_worker_execution(tmp_path: Path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, action = _core(tmp_path, events)
        action["spawn"]["invocations"][0]["prompt_sha256"] = "b" * 64
        called = False

        def worker(invocation):
            nonlocal called
            called = True
            return {"plan": "bad"}

        with pytest.raises(Exception, match="WORKER_PROMPT_HASH_MISMATCH"):
            HostTrajectoryRunner(
                tmp_path, HostPlatform.CODEX, core=core, event_store=events
            ).run(action, workers=[worker])
        assert called is False


def test_duplicate_result_replays_same_core_action(tmp_path: Path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, action = _core(tmp_path, events)
        trajectory = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events
        ).run(action, workers=[lambda invocation: {
            "plan": (
                "按原设计执行完整的开发、测试、审查、类型检查、契约验证和构建流程，"
                "并保留所有可重放的确定性验证证据。"
            ),
            "batch_plan": [{
                "batch_id": "B1", "component": "core",
                "tasks": [{
                    "id": "B1-T1", "description": "实现核心",
                    "file_targets": ["trajectory/core.py"],
                }],
            }],
            "file_list": ["trajectory/core.py"], "contracts": {},
        }])
        state_after = events.load_projection(action["thread_id"]).to_dict()

        replay = core.tick_dict(trajectory.result)

        assert replay == trajectory.next_action
        assert events.load_projection(action["thread_id"]).to_dict() == state_after


def test_crash_after_worker_receipt_keeps_core_action_active(tmp_path: Path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, action = _core(tmp_path, events)
        runner = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events
        )

        with pytest.raises(HostTrajectoryError, match="FAULT_AFTER_RECEIPT"):
            runner.run(
                action,
                workers=[lambda invocation: {"plan": "尚未提交"}],
                fail_after_receipt=True,
            )

        assert events.load_action_snapshot(action["thread_id"]) == action
