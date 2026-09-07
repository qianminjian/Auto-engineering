"""Phase 80 T404：协议内核收敛的结构性负向契约。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.loop.protocol import action_envelope

ROOT = Path(__file__).resolve().parents[1]


def _legacy_projector_source() -> str:
    path = ROOT / "auto_engineering/loop/stage_result_projector.py"
    return path.read_text(encoding="utf-8") if path.exists() else ""


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


def test_tick_orchestrator_has_one_file_input_validation_path() -> None:
    """文件桥接不得保留已退役的第二套 Result 校验实现。"""
    source = (ROOT / "auto_engineering/loop/tick_orchestrator.py").read_text(
        encoding="utf-8"
    )

    assert "def _read_and_validate" not in source


def test_tick_orchestrator_has_no_stale_result_downgrade_state() -> None:
    """上一阶段 Result 不能通过旧 E2 状态绕过 active Action 绑定。"""
    source = (ROOT / "auto_engineering/loop/tick_orchestrator.py").read_text(
        encoding="utf-8"
    )

    assert "_last_completed_stage" not in source
    assert "E2 downgrade" not in source


def test_gap_scan_report_is_not_projected_by_legacy_projector_branch() -> None:
    """Gap Scan 的业务事实必须由 Handler 事件产生，而非旁路赋值。"""
    source = _legacy_projector_source()

    assert 'if stage == "gap_scan"' not in source


def test_critic_facts_are_not_projected_by_legacy_projector_branch() -> None:
    """Critic 事实必须随 Handler 的领域事件提交。"""
    source = _legacy_projector_source()

    assert 'stage == "critic"' not in source


def test_gap_review_decisions_are_not_projected_by_legacy_projector_branch() -> None:
    """Gap Review 决策必须随 Handler 事件提交。"""
    source = _legacy_projector_source()

    assert 'stage == "gap_review"' not in source


def test_verification_facts_are_not_projected_by_legacy_projector_branches() -> None:
    """验证事实必须由 Verification Handler 事件提交。"""
    source = _legacy_projector_source()

    assert 'stage == "component_verifier"' not in source
    assert 'stage == "system_verifier"' not in source


def test_deep_audit_revision_is_not_projected_by_legacy_projector_branch() -> None:
    """Deep Audit 指纹必须随 Verification 事实事件提交。"""
    source = _legacy_projector_source()

    assert 'stage in {"plate_deep_audit", "system_deep_audit"}' not in source
    assert "audit_revision_fingerprints" not in source


def test_architect_facts_are_not_projected_by_legacy_projector_branch() -> None:
    """Architect Projection 必须由 Architect Handler 事件提交。"""
    source = _legacy_projector_source()

    assert 'stage == "architect"' not in source


def test_architecture_activation_does_not_write_projection_directly() -> None:
    """Baseline 必须由 ArchitectureBaselineAccepted Reducer 应用。"""
    source = (ROOT / "auto_engineering/loop/architecture_activation.py").read_text(
        encoding="utf-8"
    )

    assert "state.architecture_baseline =" not in source
    assert "state._runtime_ctx.pop" not in source


def test_developer_projection_does_not_use_legacy_projector() -> None:
    """Developer 结果也必须经过 Handler 事件，不保留第二条投影路径。"""
    orchestrator = (ROOT / "auto_engineering/loop/tick_orchestrator.py").read_text(
        encoding="utf-8"
    )
    projector = ROOT / "auto_engineering/loop/stage_result_projector.py"

    assert "StageResultProjector" not in orchestrator
    assert not projector.exists()
