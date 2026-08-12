"""Tick CLI 编排层的直接行为测试。"""

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest


class _Store:
    instances: list[_Store] = []

    def __init__(self, path: Path) -> None:
        self.path = path
        self.closed = False
        self.thread_checkpoint: str | None = "resolved-checkpoint"
        self.__class__.instances.append(self)

    def close(self) -> None:
        self.closed = True

    def find_by_thread_id(self, candidate: str) -> str | None:
        return self.thread_checkpoint

    def reserve_project_thread(self, candidate: str) -> str | None:
        self.reserved_thread_id = candidate
        return None

    def release_project_thread(self, thread_id: str) -> bool:
        self.released_thread_id = thread_id
        return True


class _Orchestrator:
    restore_calls: list[str | None] = []
    fail_first_restore = False
    action: dict[str, object] = {"action": "developer", "tick": 2}
    tick_error: Exception | None = None

    def __init__(self, root: Path, **kwargs: object) -> None:
        self.root = root
        self.pause_stages: list[str] = []
        self._state = SimpleNamespace(
            thread_id="thread-1",
            current_stage="developer",
            expected_stage="developer",
            tick=2,
            round=1,
            critic_verdict=None,
            total_majors=0,
            plan_refine_count=0,
        )
        self._batch_state = None

    def set_pause_at_stages(self, stages: list[str]) -> None:
        self.pause_stages = stages

    def init(
        self,
        requirement: str,
        *,
        design_doc_path: str | None,
        max_rounds: int,
        thread_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "action": "architect",
            "thread_id": thread_id or "thread-1",
            "requirement": requirement,
        }

    @classmethod
    def restore(
        cls,
        root: Path,
        store: _Store,
        *,
        checkpoint_id: str | None = None,
        **kwargs: object,
    ) -> _Orchestrator:
        cls.restore_calls.append(checkpoint_id)
        if cls.fail_first_restore and len(cls.restore_calls) == 1:
            raise ValueError("not found")
        return cls(root)

    def tick(self, result_file: Path) -> dict[str, object]:
        if self.tick_error is not None:
            raise self.tick_error
        return dict(self.action)

    def build_action(self) -> dict[str, object]:
        return {"action": "resume", "thread_id": "thread-1"}


@pytest.fixture(autouse=True)
def _reset_fakes() -> None:
    _Store.instances.clear()
    _Orchestrator.restore_calls.clear()
    _Orchestrator.fail_first_restore = False
    _Orchestrator.action = {"action": "developer", "tick": 2}
    _Orchestrator.tick_error = None


@pytest.fixture
def _patch_tick_types(monkeypatch: pytest.MonkeyPatch) -> None:
    import auto_engineering.loop.checkpoint.store as store_module
    import auto_engineering.loop.tick_orchestrator as orchestrator_module

    monkeypatch.setattr(store_module, "SQLiteCheckpointStore", _Store)
    monkeypatch.setattr(orchestrator_module, "TickOrchestrator", _Orchestrator)


def _config(*, metrics: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        metrics_enabled=metrics,
        audit_log_enabled=False,
        audit_log_dir="",
        otlp_endpoint="",
        environ={},
        is_active=lambda key: False,
    )


@pytest.mark.parametrize(
    ("requirement", "expected"),
    [
        ("fix typo", "simple_function"),
        ("database schema migration", "complex_multi_module"),
        ("implement profile page", "medium_crud"),
    ],
)
def test_requirement_category_inference(
    requirement: str,
    expected: str,
) -> None:
    from auto_engineering.cli.dev_loop import _infer_category

    assert _infer_category(requirement) == expected


def test_interactive_config_gate_runs_mandatory_wizard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dev_loop = import_module("auto_engineering.cli.dev_loop")
    doctor = import_module("auto_engineering.cli.doctor")

    monkeypatch.delenv("AE_SKIP_CONFIG_CHECK", raising=False)
    monkeypatch.setattr(
        doctor,
        "_run_wizard",
        lambda root: bool((root / "ae.toml").write_text(
            '[safety]\npii-enabled = "1"\n'
        ) or True),
    )

    assert dev_loop._check_config_gate(tmp_path, interactive=True)
    assert (tmp_path / "ae.toml").is_file()


def test_config_gate_short_circuits_for_env_or_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auto_engineering.cli.dev_loop import _check_config_gate

    (tmp_path / "ae.toml").write_text('[safety]\npii-enabled = "1"\n')
    assert _check_config_gate(tmp_path) is True


def test_noninteractive_config_gate_never_reads_piped_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import click

    from auto_engineering.cli.dev_loop import _check_config_gate

    monkeypatch.delenv("AE_SKIP_CONFIG_CHECK", raising=False)
    monkeypatch.delenv("AE_CONFIG_POLICY", raising=False)
    monkeypatch.setattr(
        click,
        "prompt",
        lambda *args, **kwargs: pytest.fail("非交互宿主不得读取 stdin/pipeline"),
    )

    assert _check_config_gate(tmp_path, interactive=False)
    assert (tmp_path / "ae.toml").is_file()
    assert "非交互宿主已写入 standard profile" in capsys.readouterr().err


@pytest.mark.parametrize("policy", ["defaults", "create"])
def test_noninteractive_config_policies_are_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    policy: str,
) -> None:
    from auto_engineering.cli.dev_loop import _check_config_gate

    monkeypatch.delenv("AE_SKIP_CONFIG_CHECK", raising=False)
    assert _check_config_gate(
        tmp_path,
        policy=policy,
        interactive=False,
    )
    assert (tmp_path / "ae.toml").is_file()


def test_noninteractive_require_policy_pauses_with_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import click

    from auto_engineering.cli.dev_loop import _check_config_gate

    monkeypatch.delenv("AE_SKIP_CONFIG_CHECK", raising=False)
    with pytest.raises(click.ClickException, match="CONFIG_POLICY_REQUIRED"):
        _check_config_gate(
            tmp_path,
            policy="require",
            interactive=False,
        )


def test_invalid_or_empty_existing_config_never_silently_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import click

    from auto_engineering.cli.dev_loop import _check_config_gate

    monkeypatch.delenv("AE_SKIP_CONFIG_CHECK", raising=False)
    (tmp_path / "ae.toml").write_text("# old commented template\n")
    with pytest.raises(click.ClickException, match="CONFIG_REQUIRED"):
        _check_config_gate(tmp_path, interactive=False)

    (tmp_path / "ae.toml").write_text("[broken\n")
    with pytest.raises(click.ClickException, match="CONFIG_INVALID"):
        _check_config_gate(tmp_path, interactive=False)


def test_config_gate_reports_env_file_default_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from auto_engineering.cli.dev_loop import _check_config_gate

    monkeypatch.delenv("AE_SKIP_CONFIG_CHECK", raising=False)
    monkeypatch.setenv("AE_METRICS", "1")

    assert _check_config_gate(
        tmp_path,
        policy="defaults",
        interactive=False,
    )
    output = capsys.readouterr().err
    assert "[配置来源]" in output
    assert "env=" in output
    assert "file=0" in output
    assert "default=" in output


def test_tick_init_emits_action_and_closes_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _patch_tick_types: None,
) -> None:
    dev_loop = import_module("auto_engineering.cli.dev_loop")

    (tmp_path / "ae.toml").write_text("")
    monkeypatch.setattr(
        dev_loop,
        "_check_config_gate",
        lambda root, **kwargs: True,
    )
    monkeypatch.setattr(dev_loop, "_build_injectables", lambda root: {
        "context_offloader": object(),
        "session_summarizer": object(),
        "tracer": None,
        "audit_logger": None,
    })
    monkeypatch.setattr(dev_loop, "get_default_config", lambda: _config())

    dev_loop.run_tick_init(
        "implement profile",
        None,
        tmp_path,
        3,
        pause_at_stage="architect, critic",
    )

    assert json.loads(capsys.readouterr().out)["action"] == "architect"
    assert _Store.instances[-1].closed is True


@pytest.mark.parametrize("terminal", [False, True])
def test_tick_step_updates_metrics_and_closes_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _patch_tick_types: None,
    terminal: bool,
) -> None:
    dev_loop = import_module("auto_engineering.cli.dev_loop")
    import auto_engineering.metrics.collector as collector_module

    class Collector:
        resumed: list[str] = []
        ended: list[tuple[str, int]] = []
        flushed = 0

        def __init__(self, root: Path) -> None:
            self.root = root

        def resume_events(self, thread_id: str) -> None:
            self.resumed.append(thread_id)

        def end_requirement(self, verdict: str, *, total_ticks: int) -> None:
            self.ended.append((verdict, total_ticks))

        def _flush(self) -> None:
            self.__class__.flushed += 1

    active: dict[str, Collector] = {}
    monkeypatch.setattr(collector_module, "MetricsCollector", Collector)
    monkeypatch.setattr(
        collector_module,
        "set_collector",
        lambda collector: active.update(value=collector),
    )
    monkeypatch.setattr(
        collector_module,
        "get_collector",
        lambda: active.get("value"),
    )
    monkeypatch.setattr(dev_loop, "_build_injectables", lambda root: {
        "context_offloader": object(),
        "session_summarizer": object(),
        "tracer": None,
        "audit_logger": None,
    })
    monkeypatch.setattr(dev_loop, "get_default_config", lambda: _config(metrics=True))
    _Orchestrator.action = (
        {"action": "done", "verdict": "PASS", "tick": 9}
        if terminal
        else {"action": "developer", "tick": 3}
    )

    result_file = tmp_path / "result.json"
    result_file.write_text("{}")
    dev_loop.run_tick_step(result_file, tmp_path)

    assert json.loads(capsys.readouterr().out)["action"] == _Orchestrator.action["action"]
    assert Collector.resumed[-1] == "thread-1"
    if terminal:
        assert Collector.ended[-1] == ("PASS", 9)
    else:
        assert Collector.flushed == 1
    assert _Store.instances[-1].closed is True


def test_tick_step_returns_structured_projection_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _patch_tick_types: None,
) -> None:
    """已知投影异常必须成为 ERROR Action，不能向宿主泄露 traceback。"""
    from auto_engineering.loop.event_store import StateProjectionMismatchError

    dev_loop = import_module("auto_engineering.cli.dev_loop")
    monkeypatch.setattr(dev_loop, "_build_injectables", lambda root: {
        "context_offloader": object(),
        "session_summarizer": object(),
        "tracer": None,
        "audit_logger": None,
    })
    monkeypatch.setattr(dev_loop, "get_default_config", lambda: _config())
    _Orchestrator.tick_error = StateProjectionMismatchError(["critic_verdict"])
    result_file = tmp_path / "result.json"
    result_file.write_text("{}", encoding="utf-8")

    dev_loop.run_tick_step(result_file, tmp_path)

    captured = capsys.readouterr()
    action = json.loads(captured.out)
    assert action["action"] == "error"
    assert action["error_code"] == "STATE_PROJECTION_MISMATCH"
    assert action["extensions"]["ae"]["execution_control"]["disposition"] == "ERROR"
    assert "Traceback" not in captured.out
    assert _Store.instances[-1].closed is True


def test_tick_status_verbose_renders_batch_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _patch_tick_types: None,
) -> None:
    dev_loop = import_module("auto_engineering.cli.dev_loop")

    component = SimpleNamespace(name="api")

    class BatchState:
        current_batch_idx = 1
        _seen_components = {"api"}

        def current_component(self) -> SimpleNamespace:
            return component

        def batches_for(self, selected: object) -> list[dict[str, object]]:
            return [{
                "batch_id": "b1",
                "component": "api",
                "tasks": ["one", "two"],
            }]

    original_restore = _Orchestrator.restore.__func__

    def restore(cls: type[_Orchestrator], root: Path, store: _Store, **kwargs: object) -> _Orchestrator:
        instance = original_restore(cls, root, store, **kwargs)
        instance._batch_state = BatchState()
        return instance

    monkeypatch.setattr(_Orchestrator, "restore", classmethod(restore))

    dev_loop.run_tick_status(tmp_path, verbose=True)
    summary = json.loads(capsys.readouterr().out)

    assert summary["batch_progress"]["current_component"] == "api"
    assert summary["batch_progress"]["batches"][0]["task_count"] == 2
    assert _Store.instances[-1].closed is True


def test_tick_status_verbose_degrades_when_batch_component_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _patch_tick_types: None,
) -> None:
    dev_loop = import_module("auto_engineering.cli.dev_loop")

    class BrokenBatchState:
        current_batch_idx = 1
        _seen_components: set[str] = set()

        def current_component(self) -> SimpleNamespace:
            raise RuntimeError("corrupt batch state")

    original_restore = _Orchestrator.restore.__func__

    def restore(cls: type[_Orchestrator], root: Path, store: _Store, **kwargs: object) -> _Orchestrator:
        instance = original_restore(cls, root, store, **kwargs)
        instance._batch_state = BrokenBatchState()
        return instance

    monkeypatch.setattr(_Orchestrator, "restore", classmethod(restore))

    dev_loop.run_tick_status(tmp_path, verbose=True)
    summary = json.loads(capsys.readouterr().out)

    assert summary["batch_progress"]["current_component"] == "?"
    assert summary["batch_progress"]["total_batches"] == 0
    assert _Store.instances[-1].closed is True


def test_tick_resume_falls_back_from_thread_id(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    _patch_tick_types: None,
) -> None:
    from auto_engineering.cli.dev_loop import run_tick_resume

    _Orchestrator.fail_first_restore = True

    run_tick_resume("thread-1", tmp_path)

    assert _Orchestrator.restore_calls == ["thread-1", "resolved-checkpoint"]
    assert json.loads(capsys.readouterr().out)["action"] == "resume"
    assert _Store.instances[-1].closed is True


def test_thread_lookup_returns_none_for_store_errors() -> None:
    from auto_engineering.cli.dev_loop import _resolve_checkpoint_by_thread_id

    class BrokenStore:
        def find_by_thread_id(self, candidate: str) -> str:
            raise ValueError("broken")

    assert _resolve_checkpoint_by_thread_id("thread", BrokenStore()) is None
