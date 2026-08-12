"""Phase 60 T281-T283：Prompt Compiler 行为契约。"""

from __future__ import annotations

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.action_builder import ActionBuilder
from auto_engineering.prompts.compiler import (
    PromptContextError,
    PromptLayoutError,
    compile_prompt_bundle,
)
from auto_engineering.prompts.contracts import default_prompt_contracts
from auto_engineering.prompts.registry import default_registry

_PROFILE_SUMMARY = {
    "profile_id": "sha256:test",
    "project": {"type": "python", "languages": ["python"]},
    "paths": {"source_roots": ["auto_engineering"], "test_roots": ["tests"]},
    "commands": {"test": ["uv", "run", "pytest"]},
}


def test_architect_worker_receives_requirement_and_refine_feedback() -> None:
    contract = default_prompt_contracts()["architect"]

    bundle = compile_prompt_bundle(
        contract=contract,
        role_prompt="你是 Architect。",
        context={
            "requirement": "实现跨宿主确定性治理内核",
            "design_doc_path": "design/spec.md",
            "project_profile_summary": {"profile_id": "sha256:test"},
            "feedback": {"mode": "PLAN_REFINE", "reason": "补齐失败恢复"},
        },
        expected_format={"plan": "string"},
    )

    assert len(bundle.worker_prompts) == 1
    prompt = bundle.worker_prompts[0].prompt
    assert "实现跨宿主确定性治理内核" in prompt
    assert "PLAN_REFINE" in prompt
    assert "补齐失败恢复" in prompt
    assert '"plan": "string"' in prompt
    assert '"role": "worker"' in prompt
    assert '"may_drive_loop": false' in prompt
    assert '"may_spawn_workers": false' in prompt
    assert "不得调用 Auto-Engineering Loop" in prompt
    assert bundle.worker_prompts[0].execution_identity["role"] == "worker"


def test_single_worker_receives_dynamic_context_in_actual_prompt() -> None:
    contract = default_prompt_contracts()["component_verifier"]

    bundle = compile_prompt_bundle(
        contract=contract,
        role_prompt="你是 Component Verifier。",
        context={
            "component": "EventStore",
            "design_section": "B3",
            "design_spec": ["事件只追加", "重复 Result 幂等"],
            "implementation_files": ["auto_engineering/events/store.py"],
            "project_profile_summary": {"profile_id": "sha256:test"},
        },
        expected_format={"coverage_map": "array"},
    )

    prompt = bundle.worker_prompts[0].prompt
    assert "EventStore" in prompt
    assert "事件只追加" in prompt
    assert "auto_engineering/events/store.py" in prompt


def test_missing_required_context_fails_closed() -> None:
    contract = default_prompt_contracts()["architect"]

    with pytest.raises(PromptContextError, match="design_doc_path"):
        compile_prompt_bundle(
            contract=contract,
            role_prompt="你是 Architect。",
            context={"requirement": "实现功能"},
            expected_format={"plan": "string"},
        )


def test_inline_developer_receives_feedback_without_forcing_git_commit() -> None:
    contract = default_prompt_contracts()["developer"]

    bundle = compile_prompt_bundle(
        contract=contract,
        role_prompt="你是 Developer。执行 RED → GREEN → REFACTOR。",
        context={
            "requirement": "修复状态恢复",
            "feedback": [{"severity": "P0", "issue": "重复推进"}],
            "batch_id": "B1",
            "component": "EventStore",
            "tasks": [{"id": "T1", "description": "补幂等测试"}],
            "project_profile_summary": {
                "profile_id": "sha256:test",
                "commands": {"test": ["pytest"]},
            },
            "git_authorized": False,
        },
        expected_format={"files_changed": "array", "test_results": "object"},
    )

    prompt = bundle.coordinator_prompt
    assert "重复推进" in prompt
    assert "RED → GREEN → REFACTOR" in prompt
    assert '"git_authorized": false' in prompt


def test_plate_workers_each_receive_context_and_unique_role() -> None:
    contract = default_prompt_contracts()["plate_deep_audit"]

    bundle = compile_prompt_bundle(
        contract=contract,
        role_prompt=default_registry().get("plate_deep_audit"),
        context={"plate": "协议层", "components": ["Envelope", "EventStore"]},
        expected_format={"findings": "array"},
    )

    assert len(bundle.worker_prompts) == 3
    assert {worker.role for worker in bundle.worker_prompts} == set(
        contract.worker_roles
    )
    for worker in bundle.worker_prompts:
        assert "协议层" in worker.prompt
        assert "Envelope" in worker.prompt
        assert worker.role in worker.prompt
    assert len({worker.prompt_hash for worker in bundle.worker_prompts}) == 3


def test_multi_worker_layout_mismatch_fails_closed() -> None:
    contract = default_prompt_contracts()["plate_deep_audit"]

    with pytest.raises(PromptLayoutError, match="PROMPT_LAYOUT_INVALID"):
        compile_prompt_bundle(
            contract=contract,
            role_prompt="协调者\n***\n只有一个 Worker",
            context={"plate": "协议层", "components": ["Envelope"]},
            expected_format={"findings": "array"},
        )


def test_system_audit_workers_receive_coverage_map() -> None:
    contract = default_prompt_contracts()["system_deep_audit"]

    bundle = compile_prompt_bundle(
        contract=contract,
        role_prompt=default_registry().get("system_deep_audit"),
        context={
            "coverage_map": [
                {"design_item": "幂等", "status": "MISSING"},
            ],
            "audit_scope": {"project_root": "/workspace", "files": ["store.py"]},
        },
        expected_format={"findings": "array"},
    )

    assert len(bundle.worker_prompts) == 5
    assert all('"status": "MISSING"' in w.prompt for w in bundle.worker_prompts)


def test_context_selector_drops_undeclared_completed_batch_history() -> None:
    contract = default_prompt_contracts()["developer"]
    history = [{"batch_id": f"B{i}", "result": "done"} for i in range(100)]

    bundle = compile_prompt_bundle(
        contract=contract,
        role_prompt="你是 Developer。",
        context={
            "requirement": "实现当前批次",
            "feedback": "修复当前问题",
            "batch_id": "B101",
            "component": "Kernel",
            "tasks": [{"id": "T101"}],
            "project_profile_summary": {"profile_id": "sha256:test"},
            "completed_batches": history,
        },
        expected_format={"files_changed": "array"},
    )

    assert "B101" in bundle.coordinator_prompt
    assert "B99" not in bundle.coordinator_prompt
    assert "completed_batches" not in bundle.coordinator_prompt


def test_context_selector_rejects_conversation_history_even_if_extra() -> None:
    contract = default_prompt_contracts()["developer"]

    with pytest.raises(PromptContextError, match="PROMPT_HISTORY_FORBIDDEN"):
        compile_prompt_bundle(
            contract=contract,
            role_prompt="你是 Developer。",
            context={
                "requirement": "实现当前批次",
                "feedback": None,
                "batch_id": "B1",
                "component": "Kernel",
                "tasks": [{"id": "T1"}],
                "project_profile_summary": {"profile_id": "sha256:test"},
                "action_history": [{"tick": i} for i in range(100)],
            },
            expected_format={"files_changed": "array"},
        )


def test_context_selector_rejects_selected_context_over_budget() -> None:
    contract = default_prompt_contracts()["developer"]

    with pytest.raises(PromptContextError, match="PROMPT_CONTEXT_TOO_LARGE"):
        compile_prompt_bundle(
            contract=contract,
            role_prompt="你是 Developer。",
            context={
                "requirement": "x" * 70_000,
                "feedback": None,
                "batch_id": "B1",
                "component": "Kernel",
                "tasks": [{"id": "T1"}],
                "project_profile_summary": {"profile_id": "sha256:test"},
            },
            expected_format={"files_changed": "array"},
        )


def test_context_manifest_has_unique_block_hashes() -> None:
    contract = default_prompt_contracts()["developer"]
    bundle = compile_prompt_bundle(
        contract=contract,
        role_prompt="Developer",
        context={
            "requirement": "req",
            "feedback": None,
            "batch_id": "B1",
            "component": "Kernel",
            "tasks": [{"id": "T1"}],
            "project_profile_summary": {"profile_id": "sha256:test"},
        },
        expected_format={"status": "string"},
    )
    manifest = bundle.context_manifest
    assert manifest["duplicate_block_bytes"] == 0
    assert manifest["total_inline_bytes"] > 0


def test_duplicate_nonempty_context_blocks_fail_closed() -> None:
    contract = default_prompt_contracts()["developer"]
    with pytest.raises(PromptContextError, match="PROMPT_CONTEXT_DUPLICATE"):
        compile_prompt_bundle(
            contract=contract,
            role_prompt="Developer",
            context={
                "requirement": "same",
                "feedback": "same",
                "batch_id": "B1",
                "component": "Kernel",
                "tasks": [{"id": "T1"}],
                "project_profile_summary": {"profile_id": "sha256:test"},
            },
            expected_format={"status": "string"},
        )


def test_project_profile_summary_is_bounded_and_identifiable(tmp_path) -> None:
    profile = {
        **_PROFILE_SUMMARY,
        "evidence": [{"source": "pyproject.toml", "digest": "secret-digest"}],
        "resolution": {"providers": ["local_probe"], "confidence": "confirmed"},
    }
    state = EngineState(
        thread_id="t",
        current_stage="developer",
        plan="plan",
        project_profile=profile,
        project_profile_id="sha256:test",
    )

    action = ActionBuilder(tmp_path).build_action(state)

    summary = action["context"]["project_profile_summary"]
    assert summary == _PROFILE_SUMMARY
    assert "evidence" not in summary
    assert "resolution" not in summary
    assert "secret-digest" not in action["instruction"]
    assert "sha256:test" in action["instruction"]
