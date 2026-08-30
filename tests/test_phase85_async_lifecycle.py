"""Phase 85 T616/T617：真实异步 Worker 轨迹与迟到结果回放。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from auto_engineering.host.execution_assembler import HostExecutionAssembler


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
