"""T363 ProjectProfile Gate 与跨进程恢复。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from auto_engineering.gates.base import SubprocessResult
from auto_engineering.gates.profile import ProfileCommandGate
from auto_engineering.gates.registry import build_gates_from_profile
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
        lambda command, project_root, timeout, **kwargs: MagicMock(
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


def test_profile_test_gate_rejects_vitest_watch_script_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8"
    )
    from auto_engineering.gates import profile as profile_module

    monkeypatch.setattr(
        profile_module,
        "run_gate_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("交互式测试命令不得启动")
        ),
    )

    verdict = ProfileCommandGate("test", ("npm", "run", "test")).run(tmp_path)

    assert verdict.passed is False
    assert "PROJECT_TEST_COMMAND_INTERACTIVE" in verdict.message
    assert "vitest run" in verdict.message


def test_profile_test_gate_allows_explicit_vitest_run_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8"
    )
    from auto_engineering.gates import profile as profile_module

    monkeypatch.setattr(
        profile_module,
        "run_gate_command",
        lambda *_args, **_kwargs: SubprocessResult(
            returncode=0, stdout="1 passed", stderr=""
        ),
    )

    verdict = ProfileCommandGate("test", ("npm", "run", "test")).run(tmp_path)

    assert verdict.passed is True


def test_profile_gate_preserves_spawn_error_diagnostics(tmp_path: Path, monkeypatch) -> None:
    from auto_engineering.gates import profile as profile_module

    monkeypatch.setattr(
        profile_module,
        "run_gate_command",
        lambda command, project_root, timeout, **kwargs: SubprocessResult(
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


def test_profile_gate_does_not_inherit_plugin_runtime_for_project_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auto_engineering.gates import profile as profile_module

    project_bin = tmp_path / ".venv/bin"
    project_bin.mkdir(parents=True)
    plugin_bin = tmp_path / ".ae-state/.ae-runtime/bin"
    plugin_bin.mkdir(parents=True)
    captured: dict[str, object] = {}

    def fake_run(command, project_root, timeout, *, env):
        captured["command"] = command
        captured["env"] = env
        return SubprocessResult(returncode=0, stdout="1 passed")

    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / ".ae-state/.ae-runtime"))
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / ".ae-state/.ae-runtime"))
    monkeypatch.setenv("PATH", str(plugin_bin) + ":/usr/bin")
    monkeypatch.setattr(profile_module, "run_gate_command", fake_run)

    verdict = ProfileCommandGate("test", ("python3", "-m", "pytest")).run(tmp_path)

    assert verdict.passed is True
    assert captured["command"] == ["python3", "-m", "pytest"]
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert "UV_PROJECT_ENVIRONMENT" not in environment
    assert "VIRTUAL_ENV" not in environment
    assert environment["PATH"].split(":")[:2] == [str(project_bin), "/usr/bin"]
