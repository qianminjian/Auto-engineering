"""T363 ProjectProfile Gate 与跨进程恢复。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_engineering.gates.base import SubprocessResult
from auto_engineering.gates.profile import ProfileCommandGate
from auto_engineering.gates.registry import build_gates_from_profile
from auto_engineering.loop.checkpoint.records import CheckpointNotFoundError
from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
from auto_engineering.loop.tick_orchestrator import TickOrchestrator
from auto_engineering.project_profile import ProjectProfile


def _profile(tmp_path: Path, commands: dict[str, list[str]]) -> ProjectProfile:
    (tmp_path / "src").mkdir(exist_ok=True)
    return ProjectProfile.from_dict(
        {
            "schema_version": "1.0",
            "project": {
                "type": "application",
                "languages": ["typescript"],
                "package_manager": "npm",
            },
            "paths": {
                "source_roots": ["src"],
                "test_roots": [],
                "design_roots": [],
            },
            "commands": commands,
            "evidence": [{
                "source": "package.json",
                "digest": "a" * 64,
                "facts": ["language:typescript"],
            }],
            "resolution": {
                "providers": ["local_probe"],
                "confidence": "confirmed",
            },
        },
        project_root=tmp_path,
    )


def test_profile_gates_use_exact_commands_without_python_fallback(tmp_path: Path) -> None:
    profile = _profile(tmp_path, {
        "lint": ["npm", "run", "lint"],
        "test": ["npm", "run", "test"],
    })

    gates = build_gates_from_profile(profile)
    by_name = {gate.name: gate for gate in gates}

    assert isinstance(by_name["lint"], ProfileCommandGate)
    assert by_name["lint"].command == ("npm", "run", "lint")
    assert by_name["test"].command == ("npm", "run", "test")
    assert by_name["type_check"].command is None
    assert "PROJECT_COMMAND_UNVERIFIED" in by_name["type_check"].run(tmp_path).message


def test_profile_test_gate_rejects_zero_tests(tmp_path: Path, monkeypatch) -> None:
    from auto_engineering.gates import profile as profile_module

    monkeypatch.setattr(
        profile_module,
        "run_gate_command",
        lambda command, project_root, timeout: MagicMock(
            timed_out=False,
            returncode=0,
            stdout="no tests collected",
            stderr="",
        ),
    )
    gate = ProfileCommandGate("test", ("npm", "run", "test"))

    verdict = gate.run(tmp_path)

    assert verdict.passed is False
    assert "未收集到测试" in verdict.message


def test_profile_gate_preserves_spawn_error_diagnostics(tmp_path: Path, monkeypatch) -> None:
    from auto_engineering.gates import profile as profile_module

    monkeypatch.setattr(
        profile_module,
        "run_gate_command",
        lambda command, project_root, timeout: SubprocessResult(
            returncode=-1,
            command=tuple(command),
            error="无法启动进程: 参数过长",
        ),
    )

    verdict = ProfileCommandGate("type_check", ("npx", "tsc", "--noEmit")).run(tmp_path)

    assert verdict.passed is False
    assert "npx tsc --noEmit" in verdict.message
    assert "无法启动进程: 参数过长" in verdict.message
    assert "exit=-1" not in verdict.message


def test_restore_rejects_persisted_profile_when_local_evidence_disappears(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run", "lint": "eslint ."}}),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    store = SQLiteCheckpointStore(tmp_path / "checkpoint.db")
    guardrail = MagicMock()
    guardrail.check.return_value = MagicMock(action="pass")
    orchestrator = TickOrchestrator(
        project_root=tmp_path,
        gate_runner=lambda gate_names, project_root: {},
        guardrail=guardrail,
        checkpoint_store=store,
    )
    orchestrator.init("实现功能")
    (tmp_path / "package.json").unlink()

    with pytest.raises(CheckpointNotFoundError, match="REVALIDATION_REQUIRED"):
        TickOrchestrator.restore(
            tmp_path,
            store,
            gate_runner=lambda gate_names, project_root: {},
            guardrail=guardrail,
        )
    store.close()
