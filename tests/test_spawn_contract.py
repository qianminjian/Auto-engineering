"""Phase 82 T440：严格 SpawnPlan 与结果职责分离。"""

from __future__ import annotations

import hashlib
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
from auto_engineering.loop.protocol import (
    ProtocolValidationError,
    validate_action_envelope,
)

ROOT = Path(__file__).parents[1]


def _architect_action(tmp_path: Path) -> dict[str, object]:
    plan = ActionBuilder(tmp_path).build_plan(EngineState(
        thread_id="spawn-plan",
        current_stage="architect",
        requirement="实现确定性治理内核",
    ))
    from auto_engineering.loop.effects import EffectExecutor

    executor = EffectExecutor(tmp_path)
    for intent in plan.effect_intents:
        executor.execute(intent)
    action = plan.payload
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

    assert "subagent_prompt" not in action
    assert invocation["worker_id"] == "architect-0"
    assert invocation["role"] == "architect"
    assert invocation["isolation"] == "fresh_context"
    assert invocation["capabilities"] == {
        "may_drive_loop": False,
        "may_spawn_workers": False,
    }
    assert invocation["prompt_sha256"]
    assert invocation["receipt_path"].startswith(".ae-state/spawn-proofs/")
    assert invocation["outcome_path"].startswith(
        ".ae-state/host-runtime/worker-outcomes/"
    )

    schema = json.loads(
        (ROOT / "auto_engineering/loop/action.schema.json").read_text()
    )
    jsonschema.validate(action, schema)


def test_current_worker_contract_requires_canonical_outcome_path(
    tmp_path: Path,
) -> None:
    action = _architect_action(tmp_path)
    invocation = action["spawn"]["invocations"][0]  # type: ignore[index]
    invocation.pop("outcome_path")
    schema = json.loads(
        (ROOT / "auto_engineering/loop/action.schema.json").read_text()
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(action, schema)
    with pytest.raises(SpawnContractError, match="WORKER_INVOCATION_INVALID"):
        SpawnPlan.from_action(action)


def test_current_action_rejects_legacy_subagent_prompt(tmp_path: Path) -> None:
    action = _architect_action(tmp_path)
    action["subagent_prompt"] = "legacy prompt"
    schema = json.loads(
        (ROOT / "auto_engineering/loop/action.schema.json").read_text()
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(action, schema)


def test_protocol_rejects_unsafe_coordinator_prompt_reference(
    tmp_path: Path,
) -> None:
    action = _architect_action(tmp_path)
    action.update({
        "thread_id": "thread-1",
        "tick": 1,
        "stage": "architect",
        "coordinator_prompt_ref": {
            "path": "/tmp/prompt.txt",
            "sha256": "a" * 64,
            "size_bytes": 12,
            "media_type": "text/plain; charset=utf-8",
        },
    })

    with pytest.raises(ProtocolValidationError, match="coordinator_prompt_ref"):
        validate_action_envelope(action)


def test_multi_worker_action_exposes_content_addressed_coordinator_prompt(
    tmp_path: Path,
) -> None:
    plan = ActionBuilder(tmp_path).build_plan(EngineState(
        thread_id="multi-coordinator-ref",
        current_stage="system_deep_audit",
        requirement="审计协议层",
        file_list=[f"src/module_{index}.py" for index in range(21)],
    ))
    from auto_engineering.loop.effects import EffectExecutor

    executor = EffectExecutor(tmp_path)
    for intent in plan.effect_intents:
        executor.execute(intent)
    action = plan.payload
    reference = action["coordinator_prompt_ref"]

    assert "subagent_prompt" not in action
    assert reference["path"].startswith(".ae-state/effects/prompt/")
    content = (tmp_path / reference["path"]).read_text(encoding="utf-8")
    assert hashlib.sha256(content.encode()).hexdigest() == reference["sha256"]
    assert reference["size_bytes"] == len(content.encode())


def test_action_schema_rejects_legacy_spawn_without_contract_version(
    tmp_path: Path,
) -> None:
    action = _architect_action(tmp_path)
    del action["spawn"]["invocations"]  # type: ignore[index]
    del action["spawn"]["contract_version"]  # type: ignore[index]
    schema = json.loads(
        (ROOT / "auto_engineering/loop/action.schema.json").read_text()
    )
    with pytest.raises(jsonschema.ValidationError):
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
    invocation = action["spawn"]["invocations"][0]  # type: ignore[index]
    prompt = (tmp_path / invocation["prompt_ref"]).read_text(encoding="utf-8")

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
    builder = ActionBuilder(tmp_path)
    plan = builder.build_plan(EngineState(
        thread_id="compact-audit",
        current_stage="system_deep_audit",
        requirement="审计小型项目",
        file_list=["src/counter.py", "tests/test_counter.py"],
    ))
    from auto_engineering.loop.effects import EffectExecutor

    executor = EffectExecutor(tmp_path)
    for intent in plan.effect_intents:
        executor.execute(intent)
    action = plan.payload
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

    assert WorkerOutcome.from_business_payload({"plan": "ok"}).payload == {"plan": "ok"}


def test_worker_outcome_rejects_non_artifact_business_payload() -> None:
    with pytest.raises(SpawnContractError, match="WORKER_OUTCOME_INVALID"):
        WorkerOutcome.from_dict({"plan": "ok"})


def test_worker_private_artifact_has_exact_business_shape() -> None:
    artifact = {
        "worker_id": "developer-0",
        "status": "completed",
        "payload": {"files_changed": ["auto_engineering/example.py"]},
        "summary": "已完成",
    }

    outcome = WorkerOutcome.from_dict(artifact)

    assert outcome.worker_id == "developer-0"
    assert outcome.status == "completed"
    assert outcome.payload == artifact["payload"]
    assert outcome.summary == "已完成"


@pytest.mark.parametrize("invalid", [
    ["worker-id", "completed", {}, "已完成"],
    '{"worker_id":"developer-0"}',
    {"outcome": {
        "worker_id": "developer-0", "status": "completed",
        "payload": {}, "summary": "已完成",
    }},
    {
        "worker_id": "developer-0", "status": "completed", "payload": {},
        "summary": "已完成", "agents": [],
    },
    {
        "worker_id": "developer-0", "status": "completed", "payload": {},
        "summary": "已完成", "native_worker_handle": "h",
    },
    {
        "worker_id": "developer-0", "status": "completed", "payload": {},
        "summary": "已完成", "actual_model": "m",
    },
    {
        "worker_id": "developer-0", "status": "completed", "payload": {},
        "summary": "已完成", "isolation_evidence": "fresh_context",
    },
    {"worker_id": "developer-0", "status": "completed", "payload": {}, "summary": "已完成", "attestation": {}},
    {"worker_id": "developer-0", "status": "completed", "payload": {}, "summary": "已完成", "receipt": {}},
    {"worker_id": "developer-0", "status": "completed", "payload": {}, "summary": "已完成", "outcomes": []},
])
def test_worker_private_artifact_rejects_wrappers_and_host_facts(
    invalid: object,
) -> None:
    with pytest.raises(
        SpawnContractError,
        match=r"WORKER_OUTCOME_(INVALID|PRIVILEGE_ESCALATION)",
    ):
        WorkerOutcome.from_dict(invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize("legacy", [
    {"agents": []},
    {"subagent_prompt": "旧提示词"},
])
def test_spawn_plan_rejects_legacy_worker_entry_points(
    tmp_path: Path, legacy: dict[str, object],
) -> None:
    action = _architect_action(tmp_path)
    action["spawn"].update(legacy)  # type: ignore[union-attr]

    with pytest.raises(SpawnContractError, match="SPAWN_LEGACY_FIELD_REJECTED"):
        SpawnPlan.from_action(action)


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
