"""当前单一运行时边界的小模块行为覆盖。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_action_effects_require_planning_and_bind_spawn_artifacts(tmp_path: Path) -> None:
    from auto_engineering.loop.action_builder_effects import ActionBuilderEffectsMixin

    class Builder(ActionBuilderEffectsMixin):
        project_root = tmp_path

        def __init__(self, sink: object) -> None:
            self._effect_intent_sink = sink
            self._effect_sink = None
            self.intents = []

        def _execute_effect(self, intent):
            self.intents.append(intent)
            return SimpleNamespace()

    with pytest.raises(RuntimeError, match="ACTION_PLAN_REQUIRED"):
        ActionBuilderEffectsMixin._execute_effect(Builder(None), SimpleNamespace())

    planned = Builder(lambda intent: None)
    planned._write_spawn_proof_file("total", "developer")
    assert len(planned.intents) == 2

    proof_dir = tmp_path / ".ae-state" / "spawn-proofs"
    challenge_dir = tmp_path / ".ae-state" / "spawn-challenges"
    proof_dir.mkdir(parents=True)
    challenge_dir.mkdir(parents=True)
    for directory in (proof_dir, challenge_dir):
        for token in ("total", "worker"):
            (directory / f"{token}.json").write_text(
                '{"status":"pending"}', encoding="utf-8"
            )

    builder = Builder(None)
    builder.bind_spawn_proofs({
        "thread_id": "thread-1",
        "message_id": "action-1",
        "stage": "developer",
        "spawn_proof_token": "total",
        "spawn": {"invocations": [{"receipt_path": "worker.json", "requested_effort": "high"}]},
    })
    assert len(builder.intents) == 4


def test_action_effects_load_prompt_rejects_empty_or_missing_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import auto_engineering.loop.action_builder as action_builder
    from auto_engineering.loop.action_builder_effects import ActionBuilderEffectsMixin

    class Builder(ActionBuilderEffectsMixin):
        project_root = tmp_path
        _effect_sink = None

        def _effect_intent_sink(self, intent):
            del intent

    class Registry:
        def get(self, stage: str) -> str:
            if stage == "empty":
                return ""
            raise KeyError(stage)

    monkeypatch.setattr(action_builder, "default_registry", lambda: Registry())
    with pytest.raises(RuntimeError, match="PROMPT_REGISTRY_EMPTY"):
        Builder()._load_prompt("empty")
    with pytest.raises(RuntimeError, match="PROMPT_REGISTRY_UNAVAILABLE"):
        Builder()._load_prompt("missing")


def test_dev_loop_paths_write_atomically_and_cleanup_only_after_commit(
    tmp_path: Path,
) -> None:
    from auto_engineering.cli.dev_loop_paths import (
        cleanup_completed_action_work_files,
        ensure_event_db_path,
        write_json_atomically,
    )

    output = tmp_path / "nested" / "result.json"
    write_json_atomically(output, {"ok": True})
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    assert ensure_event_db_path(tmp_path).name == "events.db"

    action = {"message_id": "action-1", "spawn": {"invocations": []}}
    work = tmp_path / ".ae-state" / "host-runtime" / "work"
    import hashlib
    action_dir = work / hashlib.sha256(b"action-1").hexdigest()[:24]
    action_dir.mkdir(parents=True)
    result_file = action_dir / "result.json"
    result_file.write_text("{}", encoding="utf-8")
    (action_dir / "outcomes.json").write_text("{}", encoding="utf-8")

    cleanup_completed_action_work_files(
        root=tmp_path,
        result_file=result_file,
        completed_action=action,
        next_action={"message_id": "next"},
        map_bound_action_for_host=lambda *args, **kwargs: {},
        root_bound_path=lambda path, root: root / path,
        logger=SimpleNamespace(debug=lambda *args, **kwargs: None),
    )
    assert not result_file.exists()


def test_result_repair_exhaustion_preserves_violation_evidence() -> None:
    from auto_engineering.cli.result_repair_projection import result_repair_exhausted_action

    result = result_repair_exhausted_action(
        {"message_id": "action-1"},
        {"attempt": 2},
        violations=["task_ids"],
    )
    assert result["error_code"] == "HOST_RESULT_REPAIR_EXHAUSTED"
    assert result["violations"] == ["task_ids"]


def test_project_setup_scope_only_reports_new_business_files(tmp_path: Path) -> None:
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.project_setup_scope import (
        is_minimal_setup_source,
        project_setup_scope_violations,
    )

    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "main.py").write_text("# AE_SETUP_SMOKE\n", encoding="utf-8")
    (tmp_path / "src" / "feature.py").write_text("business()\n", encoding="utf-8")
    (tmp_path / "tests" / "feature_test.py").write_text("assert True\n", encoding="utf-8")
    owner = SimpleNamespace(
        project_root=tmp_path,
        _state=EngineState(
            thread_id="thread-1",
            project_setup_baseline_files=["src/main.py"],
        ),
    )
    profile = SimpleNamespace(source_roots=("src",), test_roots=("tests",))

    violations = project_setup_scope_violations(owner, profile)

    assert violations["business_implementation"] == ["src/feature.py"]
    assert violations["business_tests"] == ["tests/feature_test.py"]
    assert is_minimal_setup_source(owner, Path("src/main.py"))


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("App.jsx", "export default function App(){return <div>ready</div>}", True),
        ("test/setup.js", "import 'vitest';", True),
        ("random.py", "print('business')", False),
    ],
)
def test_project_setup_source_classifier_handles_safe_smoke_shapes(
    tmp_path: Path,
    name: str,
    content: str,
    expected: bool,
) -> None:
    from auto_engineering.loop.project_setup_scope import is_minimal_setup_source

    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    owner = SimpleNamespace(project_root=tmp_path, _state=None)
    assert is_minimal_setup_source(owner, Path(name)) is expected


def test_state_reconciliation_replayed_response_must_keep_canonical_shape() -> None:
    from auto_engineering.loop.state_reconciliation import (
        StateReconciliationError,
        StateReconciliationService,
    )

    service = object.__new__(StateReconciliationService)
    with pytest.raises(StateReconciliationError, match="reconciliation"):
        service._outcome_from_response({})
    with pytest.raises(StateReconciliationError, match="replayed reconciliation"):
        service._outcome_from_response({"extensions": {"ae": {"reconciliation": {}}}})


def test_thread_selection_requires_event_store_capabilities() -> None:
    from auto_engineering.cli.active_action_source import active_thread, unfinished_thread

    assert active_thread(object()) is None
    assert unfinished_thread(object()) is None


def test_native_result_probe_accepts_only_root_bound_json_documents(
    tmp_path: Path,
) -> None:
    from auto_engineering.cli.native_result_recovery import native_result_worker_ids

    result = tmp_path / "result.json"
    result.write_text('{"status":"completed"}', encoding="utf-8")
    host_execution = {
        "workers": [
            {"worker_id": "worker-1", "native_result_path": "result.json"},
            {"worker_id": "", "native_result_path": "result.json"},
            {"worker_id": "worker-2", "native_result_path": "missing.json"},
        ]
    }

    assert native_result_worker_ids(
        host_execution,
        root=tmp_path,
        root_bound_path_fn=lambda path, root: root / path,
    ) == ["worker-1"]
    assert native_result_worker_ids(
        {"workers": "invalid"}, root=tmp_path,
        root_bound_path_fn=lambda path, root: root / path,
    ) == []


def test_tick_usage_is_normalized_into_one_event_fact(tmp_path: Path) -> None:
    from auto_engineering.config.runtime_config import RuntimeConfig
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.events import LoopEventType
    from auto_engineering.loop.tick_orchestrator import TickOrchestrator

    class UsageCollector:
        def collect(self) -> dict[str, object]:
            return {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_read_tokens": 30,
                "cache_write_tokens": 4,
                "provider": "test-provider",
                "model": "test-model",
                "usage_source": "test-source",
                "estimated": False,
                "host_context_window_units": 1000,
                "estimator_version": "v1",
            }

    orchestrator = TickOrchestrator(
        tmp_path,
        usage_collector=UsageCollector(),
        runtime_config=RuntimeConfig(
            environ={"AE_PII_ENABLED": "0", "AE_TOKEN_TRACKING": "1"}
        ),
    )
    orchestrator._state = EngineState(
        thread_id="thread-1", current_stage="developer", tick=2,
    )
    orchestrator._active_action = {
        "message_id": "action-1",
        "extensions": {"context_manifest": {
            "total_inline_bytes": 10,
            "duplicate_block_bytes": 2,
        }},
    }
    queued: list[tuple[LoopEventType, dict[str, object]]] = []
    orchestrator._queue_domain_event = lambda event_type, payload: queued.append(
        (event_type, payload)
    )

    orchestrator._collect_token_usage()

    assert orchestrator._state.tick_token_usage["input_tokens"] == 100
    assert orchestrator._state.session_input_units == 100
    assert queued[0][0] is LoopEventType.USAGE_RECORDED
    assert queued[0][1]["usage"]["action_message_id"] == "action-1"


def test_resume_host_platform_rejects_incomplete_action_and_invalid_reports(
    tmp_path: Path,
) -> None:
    from auto_engineering.cli.host_action_identity import resume_host_platform

    assert resume_host_platform(tmp_path, {}) is None
    report_dir = tmp_path / ".ae-state" / "host-runtime" / "stop-reports"
    report_dir.mkdir(parents=True)
    (report_dir / "bad.json").write_text("not-json", encoding="utf-8")
    (report_dir / "wrong.json").write_text(
        json.dumps({"thread_id": "other", "disposition": "CONTINUE"}),
        encoding="utf-8",
    )
    assert resume_host_platform(
        tmp_path, {"thread_id": "thread-1", "message_id": "action-1"}
    ) is None


def test_host_action_identity_fail_closed_for_invalid_lease_reports_and_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auto_engineering.cli.host_action_identity import (
        _has_valid_native_result_artifact,
        _has_worker_generation_artifact,
        bind_worker_execution_identity,
        resume_host_platform,
    )
    from auto_engineering.host.runtime_driver import HostRunLeaseStore

    monkeypatch.setattr(
        HostRunLeaseStore,
        "load",
        lambda self: SimpleNamespace(
            thread_id="thread-1", action_message_id="action-1", platform="invalid"
        ),
    )
    assert resume_host_platform(
        tmp_path, {"thread_id": "thread-1", "message_id": "action-1"}
    ) is None
    monkeypatch.setattr(HostRunLeaseStore, "load", lambda self: None)

    report_dir = tmp_path / ".ae-state" / "host-runtime" / "stop-reports"
    report_dir.mkdir(parents=True)
    (report_dir / "list.json").write_text("[]", encoding="utf-8")
    (report_dir / "missing-platform.json").write_text(
        json.dumps({
            "thread_id": "thread-1", "action_message_id": "action-1",
            "disposition": "CONTINUE", "lease_cleared": True,
        }), encoding="utf-8",
    )
    (report_dir / "invalid-platform.json").write_text(
        json.dumps({
            "thread_id": "thread-1", "action_message_id": "action-1",
            "disposition": "CONTINUE", "lease_cleared": True,
            "platform": "not-a-host",
        }), encoding="utf-8",
    )
    assert resume_host_platform(
        tmp_path, {"thread_id": "thread-1", "message_id": "action-1"}
    ) is None

    valid_report = report_dir / "valid.json"
    valid_report.write_text(
        json.dumps({
            "thread_id": "thread-1", "action_message_id": "action-1",
            "disposition": "CONTINUE", "lease_cleared": True,
            "platform": "codex",
        }), encoding="utf-8",
    )
    original_stat = Path.stat

    def fail_valid_report_stat(path: Path, *args: object, **kwargs: object):
        if path == valid_report:
            raise OSError("report disappeared")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_valid_report_stat)
    assert resume_host_platform(
        tmp_path, {"thread_id": "thread-1", "message_id": "action-1"}
    ) == "codex"

    action = {"spawn": {}, "message_id": ""}
    assert bind_worker_execution_identity(action, tmp_path) is action
    monkeypatch.setenv("AE_HOST_PLATFORM", "unknown")
    assert bind_worker_execution_identity(
        {"spawn": {}, "message_id": "action-1"}, tmp_path
    )["message_id"] == "action-1"
    monkeypatch.setenv("AE_HOST_PLATFORM", "codex")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    assert bind_worker_execution_identity(
        {"spawn": {}, "message_id": "action-1"}, tmp_path
    )["message_id"] == "action-1"

    malformed = {"message_id": "m", "spawn": {"invocations": [{}, {"worker_id": ""}]}}
    assert not _has_worker_generation_artifact(malformed, tmp_path, 0)
    assert not _has_worker_generation_artifact(malformed, tmp_path, 1)
    assert not _has_valid_native_result_artifact(malformed, tmp_path, 0)
    assert not _has_valid_native_result_artifact(malformed, tmp_path, 1)
    assert not _has_worker_generation_artifact(
        {"message_id": "m", "spawn": {"invocations": "invalid"}}, tmp_path, 1
    )
    assert not _has_valid_native_result_artifact(
        {"message_id": "m", "spawn": {"invocations": "invalid"}}, tmp_path, 1
    )


@pytest.mark.parametrize(
    ("event_type", "payload", "message"),
    [
        ("STAGE_ADVANCED", {}, "StageAdvanced"),
        ("ARCHITECTURE_BASELINE_ACCEPTED", {}, "ArchitectureBaselineAccepted"),
        ("RUNTIME_REVISION_DETECTED", {}, "RuntimeRevisionDetected"),
        ("RUNTIME_REVISION_ACTIVATED", {}, "RuntimeRevisionActivated"),
        ("STATE_CHANNELS_CHANGED", {}, "StateChannelsChanged"),
        ("GAP_STATE_UPDATED", {}, "GapStateUpdated"),
        ("COMPONENT_COMPLETED", {}, "COMPONENT_COMPLETED"),
        ("PLATE_COMPLETED", {}, "PLATE_COMPLETED"),
        ("WORK_REOPENED", {"unexpected": True}, "WORK_REOPENED"),
        ("WORK_REPAIR_COMPLETED", {}, "WORK_REPAIR_COMPLETED"),
        ("BATCH_COMPLETED", {}, "BATCH_COMPLETED_PAYLOAD_INVALID"),
    ],
)
def test_reducer_rejects_invalid_channel_payloads(
    event_type: str,
    payload: dict,
    message: str,
) -> None:
    from auto_engineering.engine.state import EngineState
    from auto_engineering.loop.events import LoopEvent, LoopEventType
    from auto_engineering.loop.reducers import default_reducer_registry

    state = EngineState(thread_id="thread-1", current_stage="developer")
    event = LoopEvent.create(
        thread_id=state.thread_id,
        sequence=1,
        event_type=LoopEventType[event_type],
        payload=payload,
        correlation_id=state.thread_id,
    )

    with pytest.raises(ValueError, match=message):
        default_reducer_registry().reduce(state, event)
