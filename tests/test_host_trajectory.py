"""Phase 82 T443：完整 Host Contract 轨迹与故障处置。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.host import HostPlatform
from auto_engineering.host.capabilities import HostCapabilities, HostCapabilityError
from auto_engineering.loop.action_builder import ActionBuilder
from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
from auto_engineering.loop.design_decision_ledger import DesignDecisionLedger
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.tick_orchestrator import TickOrchestrator
from tests.host_runtime.trajectory_runner import (
    HostTrajectoryError,
    HostTrajectoryRunner,
)


def _inline_result(action: dict, **payload: object) -> dict:
    return {
        "schema_version": "1.1",
        "message_type": "result",
        "message_id": f"result-{action['message_id']}",
        "thread_id": action["thread_id"],
        "tick": action["tick"],
        "stage": action["stage"],
        "causation_id": action["message_id"],
        "correlation_id": action["correlation_id"],
        "extensions": {},
        **payload,
    }


def _core(
    root: Path,
    events: SQLiteEventStore,
    checkpoint_store: SQLiteCheckpointStore | None = None,
) -> tuple[TickOrchestrator, dict]:
    (root / "pyproject.toml").write_text("[project]\nname='trajectory'\n")
    (root / "trajectory").mkdir()
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    core = TickOrchestrator(
        root,
        checkpoint_store=checkpoint_store,
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


def test_architect_design_conflict_uses_core_user_gate_and_approval_event(
    tmp_path: Path,
) -> None:
    change_request = {
        "source": "research",
        "source_ref": "gap-research-1",
        "requested_authority": "binding",
        "change_summary": "将原设计改为新架构",
        "affected_design_refs": ["§4.1"],
    }
    checkpoints = SQLiteCheckpointStore(tmp_path / "checkpoints.db")
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, action = _core(tmp_path, events, checkpoints)
        core._state.research_archive = {
            "gap-research-1": {
                "recommended_design": "将原设计改为新架构",
                "evidence": ["研究证据"],
            },
        }
        trajectory = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events
        ).run(action, workers=[lambda invocation: {
            "design_change_requests": [change_request],
        }])

        gate = trajectory.next_action
        assert gate["action"] == "gate"
        assert gate["gate"]["reason_code"] == "DESIGN_CHANGE_APPROVAL_REQUIRED"
        assert (
            gate["extensions"]["ae"]["execution_control"]["disposition"]
            == "WAIT_USER"
        )
        approved = core.tick_dict(_inline_result(
            gate,
            gate_resolution={
                "gate_id": gate["gate"]["id"],
                "resolution": "批准变更",
            },
        ))

        assert approved["action"] == "architect"
        assert len(approved["design_decision_ledger"]["approved_changes"]) == 1
        assert change_request["source_ref"] in approved["subagent_prompt"]
        assert "approved_changes" in approved["subagent_prompt"]
        projected = DesignDecisionLedger.project_approved_changes(
            events.load_stream(action["thread_id"])
        )
        assert len(projected) == 1
        approval = next(iter(projected.values()))
        assert approval["source_ref"] == "gap-research-1"

        restored_guardrail = MagicMock()
        restored_guardrail.check.return_value = MagicMock(action="pass")
        core = TickOrchestrator.restore(
            tmp_path,
            checkpoints,
            event_store=events,
            thread_id=action["thread_id"],
            guardrail=restored_guardrail,
            gate_runner=lambda names, project: {
                name: MagicMock(passed=True, message="ok") for name in names
            },
        )
        approved = events.load_action_snapshot(action["thread_id"])
        assert approved is not None
        assert len(approved["design_decision_ledger"]["approved_changes"]) == 1

        planned = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events
        ).run(approved, workers=[lambda invocation: {
            "plan": (
                "按已批准的新架构完成实现、测试、审查、类型检查、"
                "契约验证和最终构建验收，并保留设计决定、实现任务、"
                "测试证据和最终交付之间的完整追溯关系。"
            ),
            "batch_plan": [{
                "batch_id": "B1",
                "component": "core",
                "tasks": [{
                    "id": "B1-T1",
                    "description": "实现已批准的新架构",
                    "file_targets": ["trajectory/core.py"],
                }, {
                    "id": "B1-T2",
                    "description": "验证已批准的新架构",
                    "kind": "test",
                    "file_targets": ["tests/test_core.py"],
                }],
            }],
            "file_list": ["trajectory/core.py", "tests/test_core.py"],
            "contracts": {},
            "obligations": [{
                "id": "O-gap-research-1",
                "source_ref": "gap-research-1",
                "implementation_targets": ["B1-T1"],
                "verification_targets": ["B1-T2"],
                "contract_refs": [],
            }],
        }]).next_action
        assert planned["action"] == "developer", planned.get("feedback")
    checkpoints.close()


def test_three_worker_plate_audit_uses_templates_through_core_tick(
    tmp_path: Path,
) -> None:
    """复现真跑的三 Worker 边界，并走完真实 EventStore 因果链。"""

    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, architect = _core(tmp_path, events)
        runner = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events
        )
        action = runner.run(
            architect,
            workers=[lambda invocation: {
                "plan": (
                    "按原设计完成两个组件的实现、测试、审查、契约验证、"
                    "类型检查和最终构建验收，并保留确定性状态、失败恢复、"
                    "跨宿主一致性与完整审计证据。"
                ),
                "batch_plan": [
                    {
                        "batch_id": "B1", "component": "Foo",
                        "tasks": [{
                            "id": "B1-T1", "description": "实现 Foo",
                            "file_targets": ["trajectory/foo.py"],
                        }],
                    },
                    {
                        "batch_id": "B2", "component": "Bar",
                        "tasks": [{
                            "id": "B2-T1", "description": "实现 Bar",
                            "file_targets": ["trajectory/bar.py"],
                        }],
                    },
                ],
                "file_list": ["trajectory/foo.py", "trajectory/bar.py"],
                "contracts": {},
            }],
        ).next_action

        for batch_id, component in (("B1", "Foo"), ("B2", "Bar")):
            action = runner.run(
                action,
                workers=[lambda invocation, batch=batch_id, name=component: {
                    "batch_id": batch,
                    "files_changed": [f"trajectory/{name.lower()}.py"],
                    "commit_hash": "",
                    "test_results": {"passed": 1, "failed": 0, "total": 1},
                    "red_evidence": [],
                }],
            ).next_action
            action = runner.run(
                action,
                workers=[lambda invocation: {
                    "verdict": "APPROVE", "findings": [],
                    "critic_feedback": "验证通过",
                }],
            ).next_action
            action = runner.run(
                action,
                workers=[lambda invocation, name=component: {
                    "component": name,
                    "coverage_map": [{
                        "design_item": f"{name}-1", "status": "IMPLEMENTED",
                        "file": f"trajectory/{name.lower()}.py", "line": 1,
                        "note": "",
                    }],
                    "missing_count": 0,
                    "diverged_count": 0,
                }],
            ).next_action

        assert action["stage"] == "plate_deep_audit"
        assert action["spawn"]["count"] == 3
        trajectory = runner.run(
            action,
            workers=[lambda invocation: {
                "plate": "(single)", "findings": [],
                "p0_count": 0, "p1_count": 0, "p2_count": 0,
                "cross_component_issues": [], "total_audited_files": 2,
            }] * 3,
        )

        assert len(trajectory.result["worker_attestations"]) == 3
        assert trajectory.next_action["stage"] == "system_deep_audit"
        assert events.load_action_snapshot(action["thread_id"]) == trajectory.next_action
        assert "ResultAccepted" in trajectory.events


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


@pytest.mark.parametrize("attempt", [1, 2])
def test_capacity_exhaustion_waits_without_advancing_core(
    tmp_path: Path, attempt: int,
) -> None:
    with SQLiteEventStore(tmp_path / f"events-{attempt}.db") as events:
        core, action = _core(tmp_path, events)
        runner = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events
        )

        response = runner.submit_host_failure(
            action, error_code="HOST_AGENT_CAPACITY", message="capacity exhausted"
        )

        assert response["action"] == "resource_wait"
        assert response["extensions"]["ae"]["execution_control"]["disposition"] == "WAIT_RESOURCE"
        assert events.load_action_snapshot(action["thread_id"]) == action


def test_worker_timeout_waits_and_keeps_action_for_automatic_retry(
    tmp_path: Path,
) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, action = _core(tmp_path, events)
        response = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events
        ).submit_host_failure(
            action, error_code="HOST_WORKER_TIMEOUT", message="worker timed out",
            extra={"spawn_retry_attempt": 1},
        )

        assert response["action"] == "resource_wait"
        assert response["reason_code"] == "HOST_WORKER_TIMEOUT"
        assert response["extensions"]["ae"]["execution_control"]["disposition"] == "WAIT_RESOURCE"
        assert events.load_action_snapshot(action["thread_id"]) == action


def test_malformed_worker_output_fails_before_core_submission(tmp_path: Path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, action = _core(tmp_path, events)
        with pytest.raises(Exception, match="WORKER_OUTCOME_PRIVILEGE_ESCALATION"):
            HostTrajectoryRunner(
                tmp_path, HostPlatform.CODEX, core=core, event_store=events
            ).run(action, workers=[lambda invocation: {"spawned": True}])
        assert events.load_action_snapshot(action["thread_id"]) == action


def test_stringified_critic_findings_are_normalized_before_core_submission(
    tmp_path: Path,
) -> None:
    """复现 2026-08-24 真跑：嵌套数组被二次序列化仍在当前 Action 闭环。"""

    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, action = _core(tmp_path, events)
        runner = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events,
        )
        action = runner.run(action, workers=[lambda invocation: {
                "plan": (
                    "按原设计完成实现、测试、审查和构建验证，并保持类型契约、"
                    "状态恢复、安全门禁及跨宿主结果完全一致，同时补齐故障注入和回归证据。"
                ),
            "batch_plan": [{
                "batch_id": "B1", "component": "core",
                "tasks": [{
                    "id": "B1-T1", "description": "实现核心",
                    "file_targets": ["trajectory/core.py"],
                }],
            }],
            "file_list": ["trajectory/core.py"], "contracts": {},
        }]).next_action
        action = runner.run(action, workers=[lambda invocation: {
            "batch_id": "B1",
            "files_changed": ["trajectory/core.py"],
            "commit_hash": "",
            "test_results": {"passed": 1, "failed": 0, "total": 1},
            "red_evidence": [],
        }]).next_action

        trajectory = runner.run(action, workers=[lambda invocation: {
            "verdict": "MAJOR",
            "findings": '[{"severity":"P1","file":"trajectory/core.py",'
                        '"issue":"缺少边界校验","suggestion":"补充验证"}]',
            "critic_feedback": "需要修复",
        }])

        assert trajectory.result["findings"] == [{
            "severity": "P1",
            "file": "trajectory/core.py",
            "issue": "缺少边界校验",
            "suggestion": "补充验证",
        }]
        assert trajectory.next_action["action"] == "developer"
        assert trajectory.next_action["feedback"]
        assert "ResultAccepted" in trajectory.events


def test_recovered_action_fails_closed_when_host_capability_changes(
    tmp_path: Path, monkeypatch,
) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, action = _core(tmp_path, events)
        monkeypatch.setattr(
            "auto_engineering.host.worker_invocation.capabilities_for",
            lambda platform: HostCapabilities(
                native_subagents=True, isolated_worker_invocation=False
            ),
        )

        with pytest.raises(HostCapabilityError, match="ISOLATED_WORKER_INVOCATION_REQUIRED"):
            HostTrajectoryRunner(
                tmp_path, HostPlatform.CODEX, core=core, event_store=events
            ).run(action, workers=[lambda invocation: {}])
        assert events.load_action_snapshot(action["thread_id"]) == action


def test_late_result_for_non_active_action_is_rejected(tmp_path: Path) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core, action = _core(tmp_path, events)
        late = {
            "schema_version": "1.1", "message_type": "result",
            "message_id": "late-result", "thread_id": action["thread_id"],
            "tick": action["tick"], "stage": action["stage"],
            "causation_id": "retired-action", "correlation_id": action["correlation_id"],
            "extensions": {}, "spawned": False,
            "spawn_error_code": "HOST_WORKER_TIMEOUT", "spawn_error": "late",
        }

        response = core.tick_dict(late)

        assert response["action"] == "error"
        assert response["error_code"] == "ACTION_NOT_ACTIVE"
        assert "不要继续提交旧 Result" in response["suggestion"]
        assert events.load_action_snapshot(action["thread_id"]) == action

        stale_files = list(
            (tmp_path / ".ae-state/host-runtime/stale-results").glob("*.json")
        )
        assert len(stale_files) == 1
        stale = json.loads(stale_files[0].read_text(encoding="utf-8"))
        assert stale["status"] == "stale"
        assert stale["reason"] == "ACTION_NOT_ACTIVE"
        assert stale["thread_id"] == action["thread_id"]
        assert stale["causation_id"] == "retired-action"
        assert stale["message_id"] == "late-result"
        assert len(stale["payload_sha256"]) == 64
        assert "spawn_error" not in stale
