"""Phase 82 T440：严格 SpawnPlan 与结果职责分离。"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.host.spawn_contract import (
    SpawnContractError,
    SpawnPlan,
    WorkerOutcome,
)
from auto_engineering.loop.action_builder import ActionBuilder

ROOT = Path(__file__).parents[1]


def _architect_action(tmp_path: Path) -> dict[str, object]:
    action = ActionBuilder(tmp_path).build_action(EngineState(
        thread_id="spawn-plan",
        current_stage="architect",
        requirement="实现确定性治理内核",
    ))
    action.update({
        "schema_version": "1.1",
        "message_type": "action",
        "message_id": "action-1",
        "correlation_id": "thread-1",
        "extensions": {},
    })
    return action


def test_single_worker_action_contains_strict_invocation(tmp_path: Path) -> None:
    action = _architect_action(tmp_path)
    invocation = action["spawn"]["invocations"][0]  # type: ignore[index]

    assert invocation["worker_id"] == "architect-0"
    assert invocation["role"] == "architect"
    assert invocation["isolation"] == "fresh_context"
    assert invocation["capabilities"] == {
        "may_drive_loop": False,
        "may_spawn_workers": False,
    }
    assert invocation["prompt_sha256"]
    assert invocation["receipt_path"].startswith(".ae-state/spawn-proofs/")

    schema = json.loads(
        (ROOT / "auto_engineering/loop/action.schema.json").read_text()
    )
    jsonschema.validate(action, schema)


def test_action_schema_accepts_legacy_spawn_without_contract_version(
    tmp_path: Path,
) -> None:
    action = _architect_action(tmp_path)
    del action["spawn"]["invocations"]  # type: ignore[index]
    del action["spawn"]["contract_version"]  # type: ignore[index]
    schema = json.loads(
        (ROOT / "auto_engineering/loop/action.schema.json").read_text()
    )
    jsonschema.validate(action, schema)


def test_action_schema_rejects_current_contract_without_invocations(
    tmp_path: Path,
) -> None:
    action = _architect_action(tmp_path)
    del action["spawn"]["invocations"]  # type: ignore[index]
    schema = json.loads(
        (ROOT / "auto_engineering/loop/action.schema.json").read_text()
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(action, schema)


def test_worker_prompt_excludes_coordinator_spawn_fields(tmp_path: Path) -> None:
    action = _architect_action(tmp_path)
    prompt = action["subagent_prompt"]

    assert '"spawned"' not in prompt
    assert "spawn_proof_token" not in prompt
    assert "推进 Tick" in prompt  # prohibition remains explicit


def test_multi_worker_plan_has_unique_invocations(tmp_path: Path) -> None:
    action = ActionBuilder(tmp_path).build_action(EngineState(
        thread_id="multi-plan",
        current_stage="system_deep_audit",
        requirement="审计协议层",
        file_list=[f"src/module_{index}.py" for index in range(21)],
    ))
    plan = SpawnPlan.from_action(action)

    assert len(plan.invocations) == 5
    assert len({item.worker_id for item in plan.invocations}) == 5
    assert len({item.prompt_sha256 for item in plan.invocations}) == 5
    assert all(item.isolation == "fresh_context" for item in plan.invocations)


def test_small_system_audit_merges_five_dimensions_into_one_worker(
    tmp_path: Path,
) -> None:
    action = ActionBuilder(tmp_path).build_action(EngineState(
        thread_id="compact-audit",
        current_stage="system_deep_audit",
        requirement="审计小型项目",
        file_list=["src/counter.py", "tests/test_counter.py"],
    ))
    plan = SpawnPlan.from_action(action)

    assert action["audit_execution_profile"] == {
        "profile": "compact",
        "audited_file_count": 2,
        "dimension_count": 5,
    }
    assert len(plan.invocations) == 1
    assert action["spawn"]["parallel"] is False
    assert action["spawn"]["effort"] == "high"
    assert plan.invocations[0].role == "system_audit_compact"
    prompt = (tmp_path / plan.invocations[0].prompt_ref).read_text(encoding="utf-8")
    for dimension in (
        "架构合理性", "代码质量", "工程化规范", "虚化实现", "团队与设计覆盖",
    ):
        assert dimension in prompt


def test_worker_outcome_rejects_coordinator_fields() -> None:
    with pytest.raises(SpawnContractError, match="WORKER_OUTCOME_PRIVILEGE_ESCALATION"):
        WorkerOutcome.from_dict({"spawned": True, "plan": "bad"})

    assert WorkerOutcome.from_dict({"plan": "ok"}).payload == {"plan": "ok"}


@pytest.mark.parametrize("change", [
    {"contract_version": "9.0"},
    {"count": 99},
    {"effort": "low"},
])
def test_spawn_plan_rejects_inconsistent_top_level_contract(
    tmp_path: Path, change: dict[str, object],
) -> None:
    action = _architect_action(tmp_path)
    action["spawn"].update(change)  # type: ignore[union-attr]

    with pytest.raises(SpawnContractError, match="SPAWN_PLAN_INVALID"):
        SpawnPlan.from_action(action)


def test_spawn_plan_rejects_path_traversal(tmp_path: Path) -> None:
    action = _architect_action(tmp_path)
    action["spawn"]["invocations"][0]["receipt_path"] = "../../outside.json"  # type: ignore[index]

    with pytest.raises(SpawnContractError, match="WORKER_INVOCATION_INVALID"):
        SpawnPlan.from_action(action)
