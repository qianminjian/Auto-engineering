"""Phase 80 T404：协议内核收敛的结构性负向契约。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.loop.protocol import action_envelope

ROOT = Path(__file__).resolve().parents[1]


def test_non_terminal_action_declares_machine_execution_control() -> None:
    action = action_envelope(
        {
            "action": "developer",
            "thread_id": "thread-1",
            "tick": 1,
            "stage": "developer",
        }
    )

    control = action["extensions"]["ae"]["execution_control"]
    assert control == {
        "schema_version": "1.0",
        "disposition": "CONTINUE",
        "continuation_required": True,
        "yield_allowed": False,
        "allowed_stop_reasons": [],
    }


def test_new_rollover_contract_excludes_capacity_proxy_reasons() -> None:
    schema = json.loads(
        (ROOT / "auto_engineering/loop/action.schema.json").read_text(
            encoding="utf-8"
        )
    )
    rollover_rule = schema["allOf"][-1]["then"]["properties"]["reason"]["enum"]

    assert rollover_rule == [
        "host_process_lost",
        "context_compaction_failed",
        "cross_host",
        "manual_recovery",
    ]


def test_new_result_event_path_does_not_embed_complete_engine_state() -> None:
    source = (ROOT / "auto_engineering/loop/tick_orchestrator.py").read_text(
        encoding="utf-8"
    )

    assert '"state_patch": self._state.to_dict()' not in source


def test_action_builder_has_no_implicit_context_or_file_effects() -> None:
    source = (ROOT / "auto_engineering/loop/action_builder.py").read_text(
        encoding="utf-8"
    )

    assert "ContextVar" not in source
    assert "path.write_text(prompt" not in source
    assert "state.action_timestamp =" not in source


def test_restore_does_not_use_thread_wide_prompt_registry_lock() -> None:
    source = (ROOT / "auto_engineering/loop/tick_orchestrator.py").read_text(
        encoding="utf-8"
    )

    assert "PROMPT_REGISTRY_DRIFT" not in source


def test_stage_handlers_do_not_emit_legacy_imperative_commands() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "auto_engineering/loop/stages").glob("*.py")
    )

    for prohibited in (
        '"state_patch"',
        '"cursor_operation"',
        '"critic_progress"',
        '"initialize_architecture"',
    ):
        assert prohibited not in source


def test_tick_orchestrator_contains_no_stage_specific_branches() -> None:
    source = (ROOT / "auto_engineering/loop/tick_orchestrator.py").read_text(
        encoding="utf-8"
    )

    for stage in (
        "gap_scan",
        "gap_review",
        "research",
        "architect",
        "developer",
        "critic",
        "component_verifier",
        "plate_deep_audit",
        "system_verifier",
        "system_deep_audit",
    ):
        assert f'if stage == "{stage}"' not in source
        assert f'elif stage == "{stage}"' not in source
        assert f'current_stage == "{stage}"' not in source
