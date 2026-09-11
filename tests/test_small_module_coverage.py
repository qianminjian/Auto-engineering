"""小型编排模块的失败、安全降级与结果契约。"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_tick_evidence_records_latency_and_spawn_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.loop.tick_evidence as evidence
    from auto_engineering.engine.state import EngineState

    state = EngineState(thread_id="thread-1", current_stage="developer")
    target = SimpleNamespace(
        project_root=Path("."),
        _state=state,
        _active_action={"spawn": {"count": 2}},
        _t_gate_ms=1.0,
        _t_guard_sub_ms=1.0,
    )
    monkeypatch.setattr(evidence.time, "perf_counter", lambda: 1.2)

    evidence.record_tick_latency(target, 1.0, 4, budget_ms=0)

    assert state.action_history[0]["tick"] == 4
    assert state.action_history[0]["spawn_count"] == 2


def test_tick_evidence_handles_missing_state_and_malformed_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import auto_engineering.loop.tick_evidence as evidence

    empty = SimpleNamespace(_state=None, _active_action=None)
    evidence.record_tick_latency(empty, 0.0, 1, budget_ms=1)

    state_target = SimpleNamespace(
        project_root=Path("."),
        _state=SimpleNamespace(action_history=[], current_stage="developer"),
        _active_action={"spawn": {"count": "bad"}},
        _t_gate_ms=0.0,
        _t_guard_sub_ms=0.0,
    )
    monkeypatch.setattr(evidence.time, "perf_counter", lambda: 1.0)
    evidence.record_tick_latency(state_target, 0.0, 2, budget_ms=1000)
    assert state_target._state.action_history[0]["spawn_count"] == 0


@pytest.mark.parametrize(
    ("runner", "expected"),
    [
        (lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""), (0, 0)),
        (lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="3\t1\tsrc/a.py\n-\t-\tbin\ninvalid\trow\tbad\n",
            stderr="",
        ), (3, 1)),
        (lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("git down")), (0, 0)),
    ],
)
def test_tick_evidence_computes_diff_stats_without_second_driver(
    runner: object,
    expected: tuple[int, int],
) -> None:
    from auto_engineering.loop.tick_evidence import compute_diff_stats

    target = SimpleNamespace(project_root=Path("."))
    assert compute_diff_stats(target, ["src/a.py"], git_runner=runner) == expected
    assert compute_diff_stats(target, [], git_runner=runner) == (0, 0)


def test_escalation_gate_defaults_and_custom_options(tmp_path: Path) -> None:
    from auto_engineering.loop.escalation_handler import EscalationHandler

    default = EscalationHandler.build_agent_escalation_gate(None)
    custom = EscalationHandler.build_agent_escalation_gate({
        "question": "选择",
        "options": ["A", "B"],
        "default": "B",
    })
    assert default["default"] == default["options"][0]
    assert custom["question"] == "选择"
    assert custom["default"] == "B"

    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    assert EscalationHandler is not None


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("pyproject.toml", "python"), ("go.mod", "go"), ("none", None)],
)
def test_escalation_detects_project_language(
    tmp_path: Path, filename: str, expected: str | None,
) -> None:
    from auto_engineering.loop.escalation_handler import detect_project_language

    if filename != "none":
        (tmp_path / filename).write_text("{}", encoding="utf-8")
    assert detect_project_language(tmp_path) == expected


def test_escalation_treats_unreadable_package_manifest_as_typescript(
    tmp_path: Path,
) -> None:
    from auto_engineering.loop.escalation_handler import detect_project_language

    (tmp_path / "package.json").write_text("not-json", encoding="utf-8")

    assert detect_project_language(tmp_path) == "typescript"


def test_escalation_resolutions_use_injected_single_tick_callbacks() -> None:
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.escalation_handler import (
        EscalationContext,
        EscalationHandler,
    )

    state = EngineState(
        thread_id="thread-1",
        current_stage="developer",
        missing_project_capabilities=["python"],
    )
    calls: list[str] = []
    actions: list[dict] = []

    class Batch:
        def advance_batch(self) -> None:
            calls.append("advance_batch")

    context = EscalationContext(
        state=state,
        batch_state=Batch(),
        build_action=lambda **kwargs: actions.append(kwargs) or {"action": "next"},
        persist_state=lambda: calls.append("persist"),
        queue_domain_event=lambda *_args: calls.append("event"),
    )
    handler = EscalationHandler(context)

    terminated = handler.resolve_agent_escalation({"resolution": "终止 loop"})
    assert terminated["verdict"] == "TERMINATED"

    state.current_stage = "critic"
    handler.resolve_agent_escalation({
        "resolution": "回退重设计",
        "resolution_detail": {"note": "补充边界"},
    })
    assert state.current_stage == "architect"

    handler.resolve_agent_escalation({"resolution": "跳过"})
    assert "advance_batch" in calls

    state.current_stage = "architect"
    state.project_profile = None
    handler.resolve_agent_escalation({"resolution": "批准继续"})
    assert state.current_stage == "project_setup"
    assert actions


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
