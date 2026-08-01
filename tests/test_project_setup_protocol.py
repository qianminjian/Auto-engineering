"""T362 空项目 project_setup Action/Result 协议。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _orchestrator(project_root: Path) -> TickOrchestrator:
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    return TickOrchestrator(
        project_root=project_root,
        gate_runner=lambda gate_names, project_root: {
            name: MagicMock(passed=True, message="ok") for name in gate_names
        },
        guardrail=guardrail,
        checkpoint_store=None,
    )


def test_empty_project_emits_structured_setup_action(tmp_path: Path) -> None:
    action = _orchestrator(tmp_path).init("实现一个页面")

    assert action["action"] == "project_setup_required"
    assert action["stage"] == "project_setup"
    assert action["reason_code"] == "insufficient_project_evidence"
    assert action["missing_capabilities"] == [
        "primary_language",
        "source_roots",
        "test_command",
    ]
    assert action["constraints"]["must_not_assume_framework"] is True
    assert action["message_type"] == "action"


def test_unverified_setup_result_keeps_setup_stage(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["package.json"],
    })

    assert action["action"] == "error"
    assert action["error_code"] == "PROJECT_SETUP_UNVERIFIED"
    assert orchestrator._state.current_stage == "project_setup"


def test_verified_setup_result_reprobes_and_continues(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}),
        encoding="utf-8",
    )

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["package.json", "src"],
    })

    assert action["action"] == "architect"
    assert action["stage"] == "architect"
    assert orchestrator._state.project_profile_id.startswith("sha256:")
    assert orchestrator._state.missing_project_capabilities == []


def test_setup_result_requires_expected_result_type(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    orchestrator.init("实现一个页面")

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "claimed_complete",
        "artifacts": [],
    })

    assert action["action"] == "error"
    assert action["error_code"] == "RESULT_VALIDATION_ERROR"
