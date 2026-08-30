"""Phase 85 T617：历史宿主故障统一回放矩阵。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_engineering.host import HostPlatform
from auto_engineering.host.execution_assembler import (
    HostExecutionAssembler,
    NativeWorkerOutcome,
    WorkerOutcomeCollectionError,
)
from auto_engineering.host.outcome_journal import OutcomeJournal
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.tick_orchestrator import TickOrchestrator
from tests.host_runtime.trajectory_runner import HostTrajectoryRunner


def _core(root: Path, events: SQLiteEventStore) -> TickOrchestrator:
    (root / "pyproject.toml").write_text("[project]\nname='failure-matrix'\n")
    (root / "src").mkdir()
    (root / "tests").mkdir()
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    return TickOrchestrator(
        root,
        event_store=events,
        guardrail=guardrail,
        gate_runner=lambda names, project: {
            name: MagicMock(passed=True, message="ok") for name in names
        },
    )


def _architect_payload() -> dict[str, object]:
    return {
        "plan": (
            "按原设计完成实现、测试、审查、类型检查和构建验证，"
            "并保留跨宿主一致性、故障恢复与最终验收的完整证据。"
        ),
        "batch_plan": [{
            "batch_id": "B1",
            "component": "core",
            "tasks": [{
                "id": "B1-T1",
                "description": "实现核心",
                "file_targets": ["src/core.py"],
            }],
        }],
        "file_list": ["src/core.py"],
        "contracts": {},
    }


def test_owner_lost_is_resource_wait_and_keeps_active_action(tmp_path: Path) -> None:
    """所有权不确定不能伪装成 Worker 业务失败。"""

    with SQLiteEventStore(tmp_path / "events.db") as events:
        core = _core(tmp_path, events)
        action = core.init("按原设计完成实现")
        response = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events
        ).submit_host_failure(
            action,
            error_code="HOST_WORKER_OWNER_LOST",
            message="宿主无法确认旧 Worker 是否已终止",
        )

        assert response["action"] == "resource_wait"
        assert response["reason_code"] == "HOST_WORKER_OWNER_LOST"
        assert events.load_action_snapshot(action["thread_id"]) == action


def test_late_generation_result_is_audit_only(tmp_path: Path) -> None:
    """旧执行代际的迟到结果不得改变当前 active Action。"""

    with SQLiteEventStore(tmp_path / "events.db") as events:
        core = _core(tmp_path, events)
        action = core.init("按原设计完成实现")
        late = {
            "schema_version": "1.1",
            "message_type": "result",
            "message_id": "late-generation-result",
            "thread_id": action["thread_id"],
            "tick": action["tick"],
            "stage": action["stage"],
            "causation_id": "retired-generation-action",
            "correlation_id": action["correlation_id"],
            "extensions": {},
            "spawned": False,
            "spawn_error_code": "HOST_WORKER_OWNER_LOST",
            "spawn_error": "旧执行迟到",
        }
        response = core.tick_dict(late)

        assert response["action"] == "error"
        assert response["error_code"] == "ACTION_NOT_ACTIVE"
        stale_files = list(
            (tmp_path / ".ae-state/host-runtime/stale-results").glob("*.json")
        )
        assert len(stale_files) == 1
        assert json.loads(stale_files[0].read_text())["status"] == "stale"
        assert events.load_action_snapshot(action["thread_id"]) == action


def test_duplicate_result_is_idempotent_without_second_tick(tmp_path: Path) -> None:
    """重复提交同一 Result 只能重放相同下一 Action。"""

    with SQLiteEventStore(tmp_path / "events.db") as events:
        core = _core(tmp_path, events)
        action = core.init("按原设计完成实现")
        runner = HostTrajectoryRunner(
            tmp_path, HostPlatform.CODEX, core=core, event_store=events
        )
        trajectory = runner.run(
            action,
            workers=[lambda invocation: _architect_payload()],
        )
        stream_before = events.load_stream(action["thread_id"])
        replay = core.tick_dict(trajectory.result)

        assert replay == trajectory.next_action
        assert events.load_stream(action["thread_id"]) == stream_before


def test_partial_private_outcome_fails_closed_without_partial_merge(
    tmp_path: Path,
) -> None:
    """Worker 私有产出缺失时不能用已完成子集推进 Coordinator。"""

    with SQLiteEventStore(tmp_path / "events.db") as events:
        core = _core(tmp_path, events)
        action = core.init("按原设计完成实现")
        mapped = HostExecutionAssembler(tmp_path)
        # 先把当前唯一 invocation 的路径改成不可读文件，模拟部分完成。
        worker = action["spawn"]["invocations"][0]
        assert isinstance(worker, dict)
        private_path = tmp_path / worker["outcome_path"]
        private_path.parent.mkdir(parents=True, exist_ok=True)
        private_path.write_text("{}", encoding="utf-8")

        with pytest.raises(
            WorkerOutcomeCollectionError,
            match="HOST_WORKER_OUTPUT_INVALID:architect-0",
        ):
            mapped.collect_worker_outcomes_from_artifacts(
                action=action,
                outcomes_path=tmp_path / "outcomes.json",
            )
        assert events.load_action_snapshot(action["thread_id"]) == action


def test_core_rejection_reuses_worker_outcome_for_repair(tmp_path: Path) -> None:
    """Core 拒绝后只修复 Coordinator，不重复 Worker。"""

    with SQLiteEventStore(tmp_path / "events.db") as events:
        core = _core(tmp_path, events)
        action = core.init("按原设计完成实现")
        from auto_engineering.host.adapters import adapter_for

        adapter = adapter_for(HostPlatform.CODEX)
        mapped = adapter.map_action(
            action,
            profile=adapter.profile(
                detected=adapter.capabilities,
                authorized=adapter.capabilities,
            ),
        )
        mapped_action = mapped.payload
        worker = mapped_action["host_execution"]["workers"][0]
        native = NativeWorkerOutcome(
            worker_id=worker["worker_id"],
            native_worker_handle="native-stable",
            status="completed",
            payload=_architect_payload(),
            summary="architect complete",
            actual_model="unreported",
            isolation_evidence=worker["expected_isolation_evidence"],
            execution_generation=worker["execution_generation"],
            fencing_token=worker["fencing_token"],
        )
        assembler = HostExecutionAssembler(tmp_path)
        candidate = assembler.finalize(
            action=mapped_action,
            outcomes=[native],
            coordinator_payload=_architect_payload(),
        )
        corrupted = dict(candidate)
        corrupted["plan"] = "坏"
        rejected = core.tick_dict(corrupted)
        assert rejected["action"] == "error"
        assert OutcomeJournal(tmp_path).complete_from_core(corrupted, rejected)
        repaired = assembler.finalize(
            action=mapped_action,
            outcomes=[native],
            coordinator_payload=_architect_payload(),
        )
        repair = core.tick_dict(repaired)
        OutcomeJournal(tmp_path).complete_from_core(repaired, repair)

        assert repair["action"] == "developer"
        journal = json.loads(
            (tmp_path / ".ae-state/host-runtime/outcomes" / f"{action['message_id']}.json").read_text()
        )
        assert journal["status"] == "accepted"
