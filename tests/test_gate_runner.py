"""Gate Runner 的批量编排与 fail-closed 契约。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


class _Gate:
    def __init__(self, verdict: object = None, error: Exception | None = None) -> None:
        self.verdict = verdict
        self.error = error
        self.files_changed: list[str] = []

    def run(self, project_root: Path) -> object:
        if self.error is not None:
            raise self.error
        return self.verdict


def test_run_gates_reports_pass_fail_skip_and_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.gates.runner as runner

    gates = {
        "pass": _Gate(SimpleNamespace(
            passed=True,
            skipped=False,
            message="ok",
            gate_name="lint",
        )),
        "fail": _Gate(SimpleNamespace(
            passed=False,
            skipped=False,
            message="bad",
            gate_name="test",
        )),
        "skip": _Gate(SimpleNamespace(
            passed=False,
            skipped=True,
            not_applicable=True,
            message="not applicable",
            gate_name="build",
        )),
    }
    monkeypatch.setattr(
        runner,
        "_instantiate_gate",
        lambda name, project_root: gates.get(name),
    )
    monkeypatch.setattr(runner, "_production_active", lambda project_root: False)

    result = runner.run_gates(
        ("pass", "fail", "skip", "missing"),
        tmp_path,
        files_changed=["src/app.py"],
    )

    assert result["passed"] == 1
    assert result["failed"] == 1
    assert result["skipped"] == 2
    assert result["gate_summary"]["pass"]["status"] == "pass"
    assert result["gate_summary"]["fail"]["status"] == "fail"
    assert result["gate_summary"]["skip"]["status"] == "skipped"
    assert result["gate_summary"]["skip"]["passed"] is None
    assert result["gate_summary"]["skip"]["not_applicable"] is True
    assert result["gate_summary"]["missing"]["message"] == "no such gate"
    assert gates["pass"].files_changed == ["src/app.py"]


def test_run_gates_marks_production_failure_as_hard_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.gates.runner as runner

    gate = _Gate(SimpleNamespace(
        passed=False,
        skipped=False,
        message="failed",
        gate_name="safety",
    ))
    monkeypatch.setattr(
        runner,
        "_instantiate_gate",
        lambda name, project_root: gate,
    )
    monkeypatch.setattr(runner, "_production_active", lambda project_root: True)

    result = runner.run_gates(("safety",), tmp_path)

    assert result["gate_summary"]["safety"]["status"] == "hard_fail"
    assert result["failed"] == 1


def test_run_gates_converts_gate_crash_to_failed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.gates.runner as runner

    monkeypatch.setattr(
        runner,
        "_instantiate_gate",
        lambda name, project_root: _Gate(error=RuntimeError("boom")),
    )

    result = runner.run_gates(("audit",), tmp_path)

    assert result["failed"] == 1
    assert result["gate_summary"]["audit"] == {
        "status": "error",
        "passed": False,
        "message": "run error: boom",
    }


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_run_gates_does_not_swallow_process_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
) -> None:
    import auto_engineering.gates.runner as runner

    class InterruptingGate:
        def run(self, project_root: Path) -> object:
            raise error_type()

    monkeypatch.setattr(
        runner,
        "_instantiate_gate",
        lambda name, project_root: InterruptingGate(),
    )

    with pytest.raises(error_type):
        runner.run_gates(("test",), tmp_path)


def test_runner_helpers_handle_registry_and_config_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.gates.registry as registry
    import auto_engineering.gates.runner as runner

    monkeypatch.setattr(registry, "get_gate_by_name", lambda name: None)
    assert runner._instantiate_gate("missing", tmp_path) is None

    expected_gate = _Gate()
    monkeypatch.setattr(
        registry,
        "get_gate_by_name",
        lambda name: expected_gate,
    )
    assert runner._instantiate_gate("lint", tmp_path) is expected_gate

    monkeypatch.setattr(
        registry,
        "get_gate_by_name",
        lambda name: (_ for _ in ()).throw(TypeError("invalid")),
    )
    assert runner._instantiate_gate("broken", tmp_path) is None


def test_production_mode_comes_from_runtime_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.config.runtime_config as runtime_config
    import auto_engineering.gates.runner as runner

    monkeypatch.setattr(
        runtime_config,
        "get_default_config",
        lambda: SimpleNamespace(production_enabled=True),
    )
    assert runner._production_active(tmp_path) is True

    monkeypatch.setattr(
        runtime_config,
        "get_default_config",
        lambda: SimpleNamespace(),
    )
    assert runner._production_active(tmp_path) is False
