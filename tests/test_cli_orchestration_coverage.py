"""Tick CLI 编排层的直接行为测试。"""

from __future__ import annotations

import json
import os
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest


class _EventStore:
    instances: list[_EventStore] = []

    def __init__(self, path: Path) -> None:
        self.path = path
        self.closed = False
        self.__class__.instances.append(self)

    def close(self) -> None:
        self.closed = True

    def load_action_snapshot(self, thread_id: str) -> dict[str, object] | None:
        del thread_id
        return None

    def load_projection(self, thread_id: str):
        del thread_id
        return None

    def load_stream(self, thread_id: str) -> list[object]:
        del thread_id
        return []

class _Orchestrator:
    restore_calls: list[str | None] = []
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
        thread_id: str | None = None,
    ) -> dict[str, object]:
        return {
            "action": "architect",
            "thread_id": thread_id or "thread-1",
            "requirement": requirement,
        }

    @classmethod
    def restore_from_event_store(
        cls,
        root: Path,
        store: _EventStore | None = None,
        **kwargs: object,
    ) -> _Orchestrator:
        del store, kwargs
        cls.restore_calls.append(None)
        return cls(root)

    def tick(self, result_file: Path) -> dict[str, object]:
        if self.tick_error is not None:
            raise self.tick_error
        return dict(self.action)

    def build_action(self) -> dict[str, object]:
        return {"action": "resume", "thread_id": "thread-1"}

    def state_snapshot(self) -> SimpleNamespace:
        return SimpleNamespace(**vars(self._state))

    def active_action_snapshot(self) -> dict[str, object] | None:
        return None

    def status_snapshot(self, *, verbose: bool = False) -> dict[str, object]:
        summary: dict[str, object] = {
            "thread_id": self._state.thread_id,
            "current_stage": self._state.current_stage,
            "expected_stage": self._state.expected_stage,
            "tick": self._state.tick,
            "verdict": self._state.critic_verdict,
            "total_majors": self._state.total_majors,
            "plan_refine_count": self._state.plan_refine_count,
        }
        if verbose and self._batch_state is not None:
            batches = []
            component = None
            try:
                component = self._batch_state.current_component()
                batches = [
                    {
                        "batch_id": batch.get("batch_id", ""),
                        "component": batch.get("component", ""),
                        "task_count": len(batch.get("tasks", [])),
                    }
                    for batch in self._batch_state.batches_for(component)
                ]
            except Exception:
                pass
            summary["batch_progress"] = {
                "current_component": component.name if component else "?",
                "current_batch_idx": self._batch_state.current_batch_idx,
                "total_batches": len(batches) if component else 0,
                "batches": batches,
                "total_components_seen": len(self._batch_state._seen_components),
            }
        return summary


@pytest.fixture(autouse=True)
def _reset_fakes() -> None:
    _EventStore.instances.clear()
    _Orchestrator.restore_calls.clear()
    _Orchestrator.action = {"action": "developer", "tick": 2}
    _Orchestrator.tick_error = None


@pytest.fixture
def _patch_tick_types(monkeypatch: pytest.MonkeyPatch) -> None:
    import auto_engineering.loop.event_store as store_module
    import auto_engineering.loop.tick_orchestrator as orchestrator_module
    dev_loop = import_module("auto_engineering.cli.dev_loop")

    monkeypatch.setattr(store_module, "SQLiteEventStore", _EventStore)
    monkeypatch.setattr(orchestrator_module, "TickOrchestrator", _Orchestrator)
    monkeypatch.setattr(dev_loop, "_active_thread", lambda _events: "thread-1")
    monkeypatch.setattr(dev_loop, "_unfinished_thread", lambda _events: "thread-1")


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


def test_tick_init_emits_action_with_event_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _patch_tick_types: None,
) -> None:
    dev_loop = import_module("auto_engineering.cli.dev_loop")

    monkeypatch.setattr(dev_loop, "_build_injectables", lambda root: {
        "context_offloader": object(),
        "session_summarizer": object(),
        "tracer": None,
        "audit_logger": None,
    })
    monkeypatch.setattr(dev_loop, "_unfinished_thread", lambda _events: None)
    monkeypatch.setattr(dev_loop, "get_default_config", lambda: _config())

    dev_loop.run_tick_init(
        "implement profile",
        None,
        tmp_path,
        3,
        pause_at_stage="architect, critic",
    )

    assert json.loads(capsys.readouterr().out)["action"] == "architect"


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

        def __init__(self, root: Path, *, event_store=None) -> None:
            self.root = root

        def resume_from_event_store(self, thread_id: str) -> None:
            self.resumed.append(thread_id)

        def end_requirement(self, verdict: str, *, total_ticks: int) -> None:
            self.ended.append((verdict, total_ticks))

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

    original_restore = _Orchestrator.restore_from_event_store.__func__

    def restore(
        cls: type[_Orchestrator],
        root: Path,
        store: _EventStore | None = None,
        **kwargs: object,
    ) -> _Orchestrator:
        instance = original_restore(cls, root, store, **kwargs)
        instance._batch_state = BatchState()
        return instance

    monkeypatch.setattr(_Orchestrator, "restore_from_event_store", classmethod(restore))

    dev_loop.run_tick_status(tmp_path, verbose=True)
    summary = json.loads(capsys.readouterr().out)

    assert summary["batch_progress"]["current_component"] == "api"
    assert summary["batch_progress"]["batches"][0]["task_count"] == 2


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

    original_restore = _Orchestrator.restore_from_event_store.__func__

    def restore(
        cls: type[_Orchestrator],
        root: Path,
        store: _EventStore | None = None,
        **kwargs: object,
    ) -> _Orchestrator:
        instance = original_restore(cls, root, store, **kwargs)
        instance._batch_state = BrokenBatchState()
        return instance

    monkeypatch.setattr(_Orchestrator, "restore_from_event_store", classmethod(restore))

    dev_loop.run_tick_status(tmp_path, verbose=True)
    summary = json.loads(capsys.readouterr().out)

    assert summary["batch_progress"]["current_component"] == "?"
    assert summary["batch_progress"]["total_batches"] == 0


def test_tick_status_does_not_use_stale_continue_lease_as_thread_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _patch_tick_types: None,
) -> None:
    """旧租约不能把已无活动的 thread 伪装成可继续状态。"""
    dev_loop = import_module("auto_engineering.cli.dev_loop")

    class StaleLease:
        disposition = "CONTINUE"
        thread_id = "stale-thread"

    monkeypatch.setattr(
        "auto_engineering.host.runtime_driver.HostRunLeaseStore.load",
        lambda _store: StaleLease(),
    )
    dev_loop.run_tick_status(tmp_path)
    summary = json.loads(capsys.readouterr().out)

    assert summary["error_code"] == "HOST_RUN_LEASE_THREAD_MISMATCH"
    assert summary["recovery_required"] is True


def test_tick_resume_does_not_fall_back_to_second_state_source(
    tmp_path: Path,
    _patch_tick_types: None,
) -> None:
    import click

    from auto_engineering.cli.dev_loop import run_tick_resume

    with pytest.raises(click.ClickException, match="EVENT_ACTION_NOT_FOUND"):
        run_tick_resume("thread-1", tmp_path)
    assert _Orchestrator.restore_calls == []
    assert len(_EventStore.instances) == 1


def test_tick_resume_reuses_stop_report_host_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """跨宿主父进程恢复时，Claude Action 不能漂移成 Codex 合同。"""

    dev_loop = import_module("auto_engineering.cli.dev_loop")
    action = {
        "action": "architect",
        "thread_id": "thread-resume-platform",
        "message_id": "action-resume-platform",
    }

    class _Events:
        def __init__(self, path: Path) -> None:
            self.path = path

        def load_action_snapshot(self, thread_id: str) -> dict[str, object] | None:
            assert thread_id == action["thread_id"]
            return action

        def close(self) -> None:
            return None

    reports = tmp_path / ".ae-state/host-runtime/stop-reports"
    reports.mkdir(parents=True)
    (reports / "resume.json").write_text(json.dumps({
        "thread_id": action["thread_id"],
        "action_message_id": action["message_id"],
        "platform": "claude-code",
        "disposition": "CONTINUE",
        "lease_cleared": True,
    }), encoding="utf-8")

    captured: dict[str, str | None] = {}

    def prepare(current: dict[str, object], root: Path) -> dict[str, object]:
        assert current == action
        assert root == tmp_path
        captured["platform"] = os.environ.get("AE_HOST_PLATFORM")
        return current

    monkeypatch.setattr(
        "auto_engineering.loop.event_store.SQLiteEventStore", _Events,
    )
    monkeypatch.setattr(dev_loop, "_prepare_action_for_host", prepare)
    monkeypatch.setenv("AE_HOST_PLATFORM", "codex")

    dev_loop.run_tick_resume(str(action["thread_id"]), tmp_path)

    assert captured["platform"] == "claude-code"
    assert os.environ["AE_HOST_PLATFORM"] == "codex"
    assert json.loads(capsys.readouterr().out)["message_id"] == action["message_id"]
