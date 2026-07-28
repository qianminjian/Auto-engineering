"""Phase 53 T250：单 Tick 事件、投影、Action 原子提交。"""

from __future__ import annotations

import pytest

from auto_engineering.engine.state import EngineState
from auto_engineering.loop.event_store import SQLiteEventStore
from auto_engineering.loop.events import LoopEvent, LoopEventType
from auto_engineering.loop.tick_orchestrator import TickOrchestrator


def _event() -> LoopEvent:
    state = _state()
    return LoopEvent.create(
        thread_id="thread-1",
        sequence=0,
        event_type=LoopEventType.LOOP_INITIALIZED,
        payload={"state": state.to_dict()},
        correlation_id="thread-1",
    )


def _state() -> EngineState:
    return EngineState(
        thread_id="thread-1",
        requirement="原子提交",
        current_stage="architect",
    )


def _action() -> dict[str, object]:
    return {
        "schema_version": "1.1",
        "message_type": "action",
        "message_id": "action-1",
        "thread_id": "thread-1",
        "tick": 0,
        "stage": "architect",
        "correlation_id": "thread-1",
        "extensions": {},
        "action": "architect",
    }


def test_commit_tick_atomically_writes_event_projection_and_action() -> None:
    state = _state()
    with SQLiteEventStore(":memory:") as store:
        store.commit_tick(events=[_event()], state=state, action=_action())

        assert len(store.load_stream("thread-1")) == 1
        assert store.load_projection("thread-1").to_dict() == state.to_dict()
        assert store.load_action_snapshot("thread-1") == _action()


@pytest.mark.parametrize(
    "failure_point",
    ["after_events", "after_projection", "after_action"],
)
def test_failure_at_any_write_rolls_back_whole_tick(failure_point: str) -> None:
    def fail_at(point: str) -> None:
        if point == failure_point:
            raise RuntimeError(f"fault:{point}")

    state = _state()
    with SQLiteEventStore(":memory:", fault_injector=fail_at) as store:
        with pytest.raises(RuntimeError, match=f"fault:{failure_point}"):
            store.commit_tick(events=[_event()], state=state, action=_action())

        assert store.load_stream("thread-1") == []
        assert store.load_projection("thread-1") is None
        assert store.load_action_snapshot("thread-1") is None


@pytest.mark.parametrize(
    "failure_point",
    ["after_events", "after_projection", "after_action"],
)
def test_retry_after_injected_failure_commits_exactly_once(
    failure_point: str,
) -> None:
    armed = True

    def fail_once(point: str) -> None:
        nonlocal armed
        if armed and point == failure_point:
            armed = False
            raise RuntimeError(f"fault:{point}")

    state = _state()
    with SQLiteEventStore(":memory:", fault_injector=fail_once) as store:
        with pytest.raises(RuntimeError, match=f"fault:{failure_point}"):
            store.commit_tick(events=[_event()], state=state, action=_action())

        store.commit_tick(events=[_event()], state=state, action=_action())

        assert len(store.load_stream("thread-1")) == 1
        assert store.load_projection("thread-1").to_dict() == state.to_dict()
        assert store.load_action_snapshot("thread-1") == _action()


def test_commit_rejects_cross_thread_projection_and_action() -> None:
    with SQLiteEventStore(":memory:") as store:
        with pytest.raises(ValueError, match="thread_id"):
            store.commit_tick(
                events=[_event()],
                state=EngineState(thread_id="other"),
                action=_action(),
            )
        wrong_action = {**_action(), "thread_id": "other"}
        with pytest.raises(ValueError, match="thread_id"):
            store.commit_tick(
                events=[_event()],
                state=EngineState(thread_id="thread-1"),
                action=wrong_action,
            )


def test_commit_rejects_projection_that_does_not_match_replay() -> None:
    with SQLiteEventStore(":memory:") as store:
        divergent = EngineState(thread_id="thread-1", requirement="不一致")
        with pytest.raises(ValueError, match="投影"):
            store.commit_tick(events=[_event()], state=divergent, action=_action())


def test_orchestrator_init_uses_event_transaction_without_checkpoint_write(
    tmp_path,
) -> None:
    with SQLiteEventStore(tmp_path / "events.db") as store:
        orchestrator = TickOrchestrator(
            tmp_path,
            checkpoint_store=None,
            event_store=store,
        )

        action = orchestrator.init("通过事件启动")

        stream = store.load_stream(action["thread_id"])
        assert [event.event_type for event in stream] == [
            LoopEventType.LOOP_INITIALIZED,
            LoopEventType.ACTION_ISSUED,
        ]
        assert store.load_projection(action["thread_id"]).to_dict() == (
            orchestrator._state.to_dict()
        )
        assert store.load_action_snapshot(action["thread_id"]) == action
