"""小型编排模块的失败、安全降级与结果契约。"""

from __future__ import annotations

import os
import socket
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (SimpleNamespace(returncode=0, timed_out=False, stdout="", stderr=""), True),
        (SimpleNamespace(returncode=1, timed_out=False, stdout="x" * 1200, stderr=""), False),
        (SimpleNamespace(returncode=1, timed_out=True, stdout="", stderr=""), False),
    ],
)
def test_build_gate_declared_command_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: SimpleNamespace,
    expected: bool,
) -> None:
    import auto_engineering.gates.build as build

    monkeypatch.setattr(build, "run_gate_command", lambda *args: result)

    verdict = build.BuildGate(build_cmd="npm run build").run(tmp_path)

    assert verdict.passed is expected


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (SimpleNamespace(returncode=0, timed_out=False, stdout="", stderr=""), "成功"),
        (SimpleNamespace(returncode=1, timed_out=False, stdout="", stderr="bad"), "skip"),
        (SimpleNamespace(returncode=1, timed_out=True, stdout="", stderr=""), "超时"),
    ],
)
def test_build_gate_detected_language_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: SimpleNamespace,
    message: str,
) -> None:
    import auto_engineering.gates.build as build

    monkeypatch.setattr(build, "detect_project_language", lambda root: "go")
    monkeypatch.setattr(build, "run_gate_command", lambda *args: result)

    verdict = build.BuildGate().run(tmp_path)

    assert message in verdict.message


def test_build_gate_manifest_factory_uses_declared_command() -> None:
    from auto_engineering.gates.build import BuildGate

    assert BuildGate.from_manifest({
        "conventions": {"build_cmd": "cargo check"},
    }).build_cmd == "cargo check"
    assert BuildGate.from_manifest({"conventions": "invalid"}).build_cmd == ""


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (SimpleNamespace(returncode=0, timed_out=False, stdout="", stderr=""), True),
        (SimpleNamespace(returncode=1, timed_out=False, stdout="", stderr="bad"), False),
        (SimpleNamespace(returncode=1, timed_out=True, stdout="", stderr=""), False),
    ],
)
def test_build_gate_python_import_outcomes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: SimpleNamespace,
    expected: bool,
) -> None:
    import auto_engineering.gates.build as build

    monkeypatch.setattr(build, "detect_project_language", lambda root: "python")
    monkeypatch.setattr(build, "run_gate_command", lambda *args: result)

    assert build.BuildGate().run(tmp_path).passed is expected


@pytest.mark.parametrize(("action", "expected_key"), [("keep", "snapshot_tag"), ("revert", "rollback")])
def test_ratchet_runner_applies_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    expected_key: str,
) -> None:
    import auto_engineering.metrics.ratchet as ratchet_module
    import auto_engineering.metrics.ratchet_runner as runner
    import auto_engineering.metrics.threshold_learner as learner_module

    class Ratchet:
        def __init__(self, root: Path) -> None:
            self.root = root

        def evaluate(self, before: dict, after: dict) -> SimpleNamespace:
            return SimpleNamespace(action=action, reason="decision", config_version="v1")

        def save_config_snapshot(self, values: dict) -> str:
            return "snapshot-v1"

        def rollback(self) -> dict:
            return {"restored": True}

    monkeypatch.setattr(ratchet_module, "RatchetController", Ratchet)
    monkeypatch.setattr(
        learner_module.ThresholdLearner,
        "propose_adjustments",
        lambda self: [{"param": "AE_GATE_TIMEOUT", "proposed": 90}],
    )
    collector = SimpleNamespace(load_baseline=lambda: {"M1": 1.0, "ignored": "x"})

    result = runner.run_ratchet(
        tmp_path,
        collector,
        {"metrics_signals": {"M1": 1.2, "ignored": None}},
    )

    assert result is not None
    assert result["action"] == action
    assert expected_key in result


def test_ratchet_runner_skips_incomplete_or_invalid_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.metrics.ratchet as ratchet_module
    from auto_engineering.metrics.ratchet_runner import run_ratchet

    assert run_ratchet(
        tmp_path,
        SimpleNamespace(load_baseline=lambda: {}),
        {"metrics_signals": {"M1": 1}},
    ) is None

    monkeypatch.setattr(
        ratchet_module,
        "RatchetController",
        lambda root: (_ for _ in ()).throw(ValueError("bad config")),
    )
    assert run_ratchet(
        tmp_path,
        SimpleNamespace(load_baseline=lambda: {"M1": 1}),
        {"metrics_signals": {"M1": 2}},
    ) is None


def test_checkpoint_manager_delegates_and_handles_io_errors() -> None:
    from auto_engineering.loop.checkpoint.manager import CheckpointManager
    from auto_engineering.loop.checkpoint.records import CheckpointNotFoundError

    class Store:
        fail = False

        def save(self, **kwargs: object) -> str:
            if self.fail:
                raise sqlite3.OperationalError("disk")
            return "checkpoint-1"

        def list_all(self) -> list[str]:
            return ["meta"]

        def load(self, checkpoint_id: str) -> str:
            return checkpoint_id

        def count(self) -> int:
            return 1

    empty = CheckpointManager()
    assert empty.save(object(), 1) is None
    assert empty.save(None, 1) is None
    assert empty.list_metas() == []
    assert empty.count() == 0
    with pytest.raises(CheckpointNotFoundError):
        empty.load("missing")

    store = Store()
    manager = CheckpointManager(store)
    assert manager.save(None, 1) is None
    assert manager.store is store
    assert manager.save(object(), 2, history=["event"], tag="tag") == "checkpoint-1"
    assert manager.list_metas() == ["meta"]
    assert manager.load("checkpoint-1") == "checkpoint-1"
    assert manager.count() == 1
    store.fail = True
    assert manager.save(object(), 3) is None


def test_tracing_unreachable_collector_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry import trace
    from opentelemetry.trace import ProxyTracerProvider

    import auto_engineering.observability.tracing as tracing

    monkeypatch.delenv("AE_OTLP_SKIP_PROBE", raising=False)
    monkeypatch.setenv("AE_OTLP_ENDPOINT", "http://localhost:4317")
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: ProxyTracerProvider())
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("down")),
    )

    tracer = tracing.setup_tracing(otlp_endpoint="http://localhost:4317")

    assert tracer is not None
    assert "AE_OTLP_ENDPOINT" not in os.environ


def test_tracing_connected_collector_setup_failure_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import opentelemetry.exporter.otlp.proto.grpc.trace_exporter as exporter_module
    from opentelemetry import trace
    from opentelemetry.trace import ProxyTracerProvider

    import auto_engineering.observability.tracing as tracing

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.delenv("AE_OTLP_SKIP_PROBE", raising=False)
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: ProxyTracerProvider())
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: Connection())
    monkeypatch.setattr(
        exporter_module,
        "OTLPSpanExporter",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("broken")),
    )

    assert tracing.setup_tracing(
        otlp_endpoint="http://localhost:4317",
    ) is not None


def test_metrics_enrichment_emits_diagnosis_and_ratchet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import auto_engineering.metrics.enrichment as enrichment

    signal = SimpleNamespace(
        name="slow",
        severity="warning",
        metric="M1",
        value=2,
        baseline=1,
        description="slower",
    )
    diagnosis = SimpleNamespace(
        signal_name="slow",
        severity="warning",
        possible_causes=["tests"],
        suggested_actions=["optimize"],
        auto_adjustable=["AE_GATE_TIMEOUT"],
        needs_human=False,
    )
    monkeypatch.setattr(
        enrichment.SignalDetector,
        "analyze",
        lambda self, history, baseline: [signal],
    )
    monkeypatch.setattr(
        enrichment.Diagnoser,
        "diagnose",
        lambda self, item: diagnosis,
    )
    monkeypatch.setattr(
        enrichment,
        "generate_suggestions",
        lambda signals, diagnoses: ["adjust"],
    )
    monkeypatch.setattr(
        enrichment.RatchetController,
        "evaluate",
        lambda self, **kwargs: SimpleNamespace(
            action="keep",
            reason="improved",
        ),
    )
    collector = SimpleNamespace(get_latest_summary=lambda: {"M1": 2})

    result = enrichment.compute_metrics_signals(
        collector,
        baseline={"M1": 1},
        project_root=str(tmp_path),
    )

    assert result["metrics_diagnoses"][0]["signal_name"] == "slow"
    assert result["metrics_ratchet_decisions"][0]["action"] == "keep"


def test_metrics_enrichment_handles_ratchet_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import auto_engineering.metrics.enrichment as enrichment

    signal = SimpleNamespace(
        name="slow",
        severity="warning",
        metric="M1",
        value=2,
        baseline=1,
        description="slower",
    )
    diagnosis = SimpleNamespace(
        signal_name="slow",
        severity="warning",
        possible_causes=[],
        suggested_actions=[],
        auto_adjustable=["AE_GATE_TIMEOUT"],
        needs_human=False,
    )
    monkeypatch.setattr(enrichment.SignalDetector, "analyze", lambda *args: [signal])
    monkeypatch.setattr(enrichment.Diagnoser, "diagnose", lambda *args: diagnosis)
    monkeypatch.setattr(enrichment, "generate_suggestions", lambda *args: [])
    monkeypatch.setattr(
        enrichment.RatchetController,
        "evaluate",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad")),
    )

    result = enrichment.compute_metrics_signals(
        SimpleNamespace(get_latest_summary=lambda: {"M1": 2}),
        baseline={"M1": 1},
        project_root=str(tmp_path),
    )

    assert "metrics_ratchet_decisions" not in result


def test_metrics_enrichment_returns_empty_without_summary() -> None:
    from auto_engineering.metrics.enrichment import compute_metrics_signals

    assert compute_metrics_signals(
        SimpleNamespace(get_latest_summary=lambda: None),
    ) == {}
