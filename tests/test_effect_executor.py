"""Phase 80 T408：Action 文件副作用隔离。"""

from __future__ import annotations

import hashlib

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.action_builder import ActionBuilder
from auto_engineering.loop.effects import (
    EffectExecutionError,
    EffectExecutor,
    WriteContentAddressedArtifact,
    WriteJsonArtifact,
)


def test_content_addressed_effect_is_idempotent(tmp_path) -> None:
    content = "worker prompt"
    digest = hashlib.sha256(content.encode()).hexdigest()
    intent = WriteContentAddressedArtifact(
        kind="prompt",
        content=content,
        sha256=digest,
    )
    executor = EffectExecutor(tmp_path)

    first = executor.execute(intent)
    second = executor.execute(intent)

    assert first == second
    assert first.sha256 == digest
    assert (tmp_path / first.relative_path).read_text() == content


def test_effect_rejects_hash_mismatch_before_write(tmp_path) -> None:
    executor = EffectExecutor(tmp_path)

    with pytest.raises(EffectExecutionError, match="hash"):
        executor.execute(WriteContentAddressedArtifact(
            kind="prompt",
            content="content",
            sha256="0" * 64,
        ))

    assert list(tmp_path.rglob("*")) == []


def test_effect_kind_cannot_escape_effect_root(tmp_path) -> None:
    content = "content"
    with pytest.raises(EffectExecutionError, match="kind"):
        EffectExecutor(tmp_path).execute(WriteContentAddressedArtifact(
            kind="../outside",
            content=content,
            sha256=hashlib.sha256(content.encode()).hexdigest(),
        ))


def test_named_json_effect_writes_only_under_ae_state(tmp_path) -> None:
    receipt = EffectExecutor(tmp_path).execute(WriteJsonArtifact(
        relative_path="spawn-proofs/proof-1.json",
        payload={"token": "proof-1", "status": "pending"},
    ))

    assert receipt.relative_path == ".ae-state/spawn-proofs/proof-1.json"
    assert (tmp_path / receipt.relative_path).read_text() == (
        '{"status":"pending","token":"proof-1"}'
    )


def test_named_json_effect_rejects_path_escape(tmp_path) -> None:
    with pytest.raises(EffectExecutionError, match="path"):
        EffectExecutor(tmp_path).execute(WriteJsonArtifact(
            relative_path="../outside.json",
            payload={"status": "pending"},
        ))


def test_action_builder_returns_explicit_action_plan(tmp_path) -> None:
    plan = ActionBuilder(tmp_path).build_plan(EngineState(
        thread_id="thread-1",
        current_stage="architect",
        requirement="实现功能",
    ))

    assert plan.effect_intents
    assert plan.preview_receipts
    assert any("spawn-proofs" in item.relative_path for item in plan.preview_receipts)
    assert "effect_receipts" not in plan.payload.get("extensions", {}).get("ae", {})


def test_action_plan_merges_identity_binding_effects(tmp_path) -> None:
    plan = ActionBuilder(tmp_path).build_plan(EngineState(
        thread_id="thread-1",
        current_stage="architect",
        requirement="实现功能",
    ))

    merged = plan.with_effects(
        intents=plan.effect_intents[:1],
        receipts=plan.preview_receipts[:1],
    )

    assert len(merged.effect_intents) == len(plan.effect_intents) + 1
    assert len(merged.preview_receipts) == len(plan.preview_receipts) + 1
    assert merged.payload is plan.payload


def test_action_builder_plans_effects_without_writing_in_core_mode(tmp_path) -> None:
    plan = ActionBuilder(tmp_path).build_plan(EngineState(
        thread_id="thread-1",
        current_stage="architect",
        requirement="实现功能",
    ))

    assert plan.effect_intents
    assert plan.preview_receipts
    assert not (tmp_path / ".ae-state" / "spawn-proofs").exists()
    assert not (tmp_path / ".ae-state" / "effects").exists()
    assert "effect_receipts" not in plan.payload.get("extensions", {}).get("ae", {})


def test_action_builder_effect_references_are_stable_for_same_snapshot(tmp_path) -> None:
    state = EngineState(
        thread_id="thread-1",
        current_stage="architect",
        requirement="实现功能",
        tick=2,
    )
    first = ActionBuilder(tmp_path).build_action(state)
    second = ActionBuilder(tmp_path).build_action(state)

    assert first["spawn_proof_token"] == second["spawn_proof_token"]
    assert first["spawn"]["invocations"] == second["spawn"]["invocations"]


def test_discard_removes_only_uncommitted_named_json_artifacts(tmp_path) -> None:
    executor = EffectExecutor(tmp_path)
    proof = executor.execute(WriteJsonArtifact(
        relative_path="spawn-proofs/proof-1.json",
        payload={"token": "proof-1", "status": "pending"},
    ))
    prompt_text = "shared prompt"
    prompt = executor.execute(WriteContentAddressedArtifact(
        kind="prompt",
        content=prompt_text,
        sha256=hashlib.sha256(prompt_text.encode()).hexdigest(),
    ))

    executor.discard([proof, prompt])

    assert not (tmp_path / proof.relative_path).exists()
    assert (tmp_path / prompt.relative_path).read_text() == prompt_text
