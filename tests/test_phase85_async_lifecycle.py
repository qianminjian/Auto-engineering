"""Phase 85 T616/T617：真实异步 Worker 轨迹与迟到结果回放。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_engineering.host.execution_assembler import HostExecutionAssembler
from auto_engineering.host.outcome_journal import OutcomeJournal
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _action(tmp_path: Path) -> dict:
    from tests.test_host_execution_assembler import _action as build_action

    return build_action(tmp_path)


def test_wait_observation_does_not_fail_worker_before_async_outcome_arrives(
    tmp_path: Path,
) -> None:
    action = _action(tmp_path)
    outcome_path = tmp_path / action["spawn"]["invocations"][0]["outcome_path"]
    outcome_path.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "import json,time; time.sleep(0.15); "
        "json.dump({'worker_id':'critic-0','native_worker_handle':'native-async',"
        "'status':'completed','payload':{'verdict':'PASS'},"
        "'summary':'async complete','actual_model':'unreported'},"
        "open(" + repr(str(outcome_path)) + ",'w',encoding='utf-8'))"
    )
    process = subprocess.Popen([sys.executable, "-c", script])

    with pytest.raises(subprocess.TimeoutExpired):
        process.wait(timeout=0.01)
    assert process.poll() is None

    process.wait(timeout=2)
    outcomes = HostExecutionAssembler(tmp_path).collect_worker_outcomes_from_artifacts(
        action=action,
        outcomes_path=tmp_path / ".ae-state/work/outcomes.json",
    )
    result = HostExecutionAssembler(tmp_path).finalize(
        action=action,
        outcomes=outcomes,
        coordinator_payload={"verdict": "PASS", "findings": []},
    )

    assert result["spawned"] is True
    receipt = json.loads(
        (tmp_path / ".ae-state/spawn-proofs/worker-token.json").read_text()
    )
    assert receipt["worker"] == "critic-0"


def test_async_worker_continues_through_core_tick_after_wait_observation(
    tmp_path: Path,
) -> None:
    """T616：等待观察不能脱离真实 Core/EventStore 纵向链。"""

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='async-trajectory'\n", encoding="utf-8"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    with SQLiteEventStore(tmp_path / "events.db") as events:
        core = TickOrchestrator(
            tmp_path,
            event_store=events,
            guardrail=guardrail,
            gate_runner=lambda names, root: {
                name: MagicMock(passed=True, message="ok") for name in names
            },
        )
        action = core.init("按原设计完成实现")
        assert action["stage"] == "architect"

        from auto_engineering.host import HostPlatform
        from auto_engineering.host.adapters import adapter_for

        adapter = adapter_for(HostPlatform.CODEX)
        mapped = adapter.map_action(
            action,
            profile=adapter.profile(
                detected=adapter.capabilities,
                authorized=adapter.capabilities,
            ),
        ).payload
        worker = mapped["host_execution"]["workers"][0]
        outcome_path = tmp_path / worker["outcome_path"]
        outcome_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "plan": (
                "按原设计完成实现、测试、审查、类型检查和构建验证，"
                "并保留跨宿主一致性、可恢复故障与最终验收的完整证据。"
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
        script = (
            "import json,time; time.sleep(0.15); "
            "json.dump({"
            "'worker_id':'architect-0','native_worker_handle':'native-async',"
            "'status':'completed','payload':" + repr(payload) + ","
            "'summary':'async complete','actual_model':'unreported',"
            "'isolation_evidence':" + repr(worker["expected_isolation_evidence"]) + ","
            "'execution_generation':" + repr(worker["execution_generation"]) + ","
            "'fencing_token':" + repr(worker["fencing_token"]) + "},"
            "open(" + repr(str(outcome_path)) + ",'w',encoding='utf-8'))"
        )
        process = subprocess.Popen([sys.executable, "-c", script])
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.01)
        assert process.poll() is None
        process.wait(timeout=2)

        outcomes = HostExecutionAssembler(tmp_path).collect_worker_outcomes_from_artifacts(
            action=mapped,
            outcomes_path=tmp_path / ".ae-state/work/outcomes.json",
        )
        result = HostExecutionAssembler(tmp_path).finalize(
            action=mapped,
            outcomes=outcomes,
            coordinator_payload=payload,
        )
        next_action = core.tick_dict(result)
        OutcomeJournal(tmp_path).complete_from_core(result, next_action)

        assert next_action["action"] == "developer"
        assert next_action["stage"] == "developer"
        assert events.load_action_snapshot(action["thread_id"]) == next_action
        event_types = [event.event_type.value for event in events.load_stream(action["thread_id"])]
        assert "ResultAccepted" in event_types
        assert "ActionIssued" in event_types
        journal = json.loads(
            (tmp_path / ".ae-state/host-runtime/outcomes" / f"{action['message_id']}.json").read_text()
        )
        assert journal["status"] == "accepted"
