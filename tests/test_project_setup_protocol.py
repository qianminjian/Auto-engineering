"""T362 空项目 project_setup Action/Result 协议。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEventType
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


def test_setup_instruction_only_mentions_requested_capabilities(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    action = orchestrator.init("实现 Python slugify")

    assert "eslint_flat_config" not in action["instruction"]
    assert "jsdom_dependency" not in action["instruction"]
    assert "primary_language" in action["instruction"]
    assert "source_roots" in action["instruction"]
    assert "test_command" in action["instruction"]


def test_unverified_setup_result_keeps_setup_stage(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path)
    initial = orchestrator.init("实现一个页面")

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["package.json"],
    })

    assert action["action"] == "project_setup_required"
    assert action["stage"] == "project_setup"
    assert action["feedback"].startswith("PROJECT_SETUP_UNVERIFIED")
    assert action["message_id"] != initial["message_id"]
    assert action["tick"] > initial["tick"]
    assert action["extensions"]["ae"]["execution_control"]["disposition"] == (
        "CONTINUE"
    )
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


def test_verified_setup_commits_stage_transition_with_event_store(
    tmp_path: Path,
) -> None:
    """真跑路径必须以 StageAdvanced 拥有 setup→architect 投影变化。"""
    with SQLiteEventStore(tmp_path / "events.db") as events:
        orchestrator = TickOrchestrator(
            project_root=tmp_path,
            gate_runner=lambda gate_names, project_root: {
                name: MagicMock(passed=True, message="ok")
                for name in gate_names
            },
            checkpoint_store=None,
            event_store=events,
        )
        initial = orchestrator.init("实现一个页面")
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
        stream = events.load_stream(initial["thread_id"])
        expected_types = (
            LoopEventType.RESULT_ACCEPTED,
            LoopEventType.PROJECT_SETUP_COMPLETED,
            LoopEventType.STAGE_ADVANCED,
            LoopEventType.ACTION_ISSUED,
        )
        assert [
            event.event_type
            for event in stream
            if event.event_type in expected_types
        ][-4:] == list(expected_types)
        assert events.load_projection(initial["thread_id"]).current_stage == (
            "architect"
        )


def test_failed_setup_commits_only_new_setup_action_without_stage_advance(
    tmp_path: Path,
) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as events:
        orchestrator = TickOrchestrator(
            project_root=tmp_path,
            gate_runner=lambda gate_names, project_root: {
                name: MagicMock(
                    passed=True,
                    message="ok",
                    not_applicable=False,
                    advisory=False,
                )
                for name in gate_names
            },
            checkpoint_store=None,
            event_store=events,
        )
        initial = orchestrator.init("实现一个页面")

        action = orchestrator.tick_dict({
            "stage": "project_setup",
            "result_type": "project_setup_completed",
            "artifacts": ["package.json"],
        })

        assert action["action"] == "project_setup_required"
        stream = events.load_stream(initial["thread_id"])
        assert sum(
            event.event_type is LoopEventType.ACTION_ISSUED for event in stream
        ) == 2
        assert not any(
            event.event_type in {
                LoopEventType.PROJECT_SETUP_COMPLETED,
                LoopEventType.STAGE_ADVANCED,
            }
            for event in stream
        )
        assert events.load_projection(initial["thread_id"]).current_stage == (
            "project_setup"
        )


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


def test_setup_does_not_complete_when_declared_quality_gate_fails(
    tmp_path: Path,
) -> None:
    def gate_runner(gate_names, project_root):
        return {
            name: MagicMock(
                passed=name != "lint",
                message="lint config ineffective" if name == "lint" else "ok",
                not_applicable=False,
                advisory=False,
            )
            for name in gate_names
        }

    orchestrator = TickOrchestrator(
        project_root=tmp_path,
        gate_runner=gate_runner,
        guardrail=MagicMock(check=MagicMock(return_value=MagicMock(action="pass"))),
        checkpoint_store=None,
    )
    orchestrator.init("实现一个页面")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/main.ts").write_text("export {};\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/setup.test.ts").write_text("export {};\n")
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {
            "lint": "eslint .",
            "typecheck": "tsc --noEmit",
            "test": "vitest run",
            "build": "vite build",
        },
        "devDependencies": {"eslint": "^8.0.0", "typescript": "^5.0.0"},
    }))

    action = orchestrator.tick_dict({
        "stage": "project_setup",
        "result_type": "project_setup_completed",
        "artifacts": ["package.json", "src", "tests"],
    })

    assert action["action"] == "project_setup_required"
    assert action["feedback"].startswith("PROJECT_SETUP_GATE_FAILED")
    assert orchestrator._state.current_stage == "project_setup"
    assert orchestrator._state.missing_project_capabilities == ["setup_gate:lint"]
    assert orchestrator._state.gate_results["lint"]["passed"] is False
