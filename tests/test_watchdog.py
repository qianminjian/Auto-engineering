"""canonical watchdog 的直接行为测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import auto_engineering.host.watchdog as watchdog


def test_alive_distinguishes_running_zombie_and_missing_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(watchdog.os, "kill", lambda *_: None)
    monkeypatch.setattr(
        watchdog.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="R\n"),
    )
    assert watchdog._alive(10) is True
    monkeypatch.setattr(
        watchdog.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="Z\n"),
    )
    assert watchdog._alive(10) is False

    monkeypatch.setattr(
        watchdog.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("ps unavailable")),
    )
    assert watchdog._alive(10) is True
    monkeypatch.setattr(watchdog.os, "kill", lambda *_: None)
    monkeypatch.setattr(
        watchdog.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=""),
    )
    assert watchdog._alive(10) is False
    monkeypatch.setattr(
        watchdog.os,
        "kill",
        lambda *_: (_ for _ in ()).throw(PermissionError),
    )
    assert watchdog._alive(10) is False
    monkeypatch.setattr(
        watchdog.os,
        "kill",
        lambda *_: (_ for _ in ()).throw(ProcessLookupError),
    )
    assert watchdog._alive(10) is False


def test_terminate_marks_reason_and_escalates_when_term_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signals: list[object] = []
    monkeypatch.setattr(watchdog.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(watchdog, "_alive", lambda _pid: True)
    clock = iter((0.0, 10.0))
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(watchdog.time, "sleep", lambda _: None)

    marker = tmp_path / "idle.marker"
    watchdog._terminate(42, marker)

    assert marker.is_file()
    assert signals == [(42, watchdog.signal.SIGTERM), (42, watchdog.signal.SIGKILL)]


def test_terminate_returns_when_host_already_exited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        watchdog.os,
        "kill",
        lambda *_: (_ for _ in ()).throw(ProcessLookupError),
    )
    marker = tmp_path / "timeout.marker"
    watchdog._terminate(42, marker)
    assert marker.is_file()


def test_terminate_does_not_escalate_after_graceful_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signals: list[object] = []
    monkeypatch.setattr(watchdog.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    alive = iter((False, False))
    monkeypatch.setattr(watchdog, "_alive", lambda _pid: next(alive))
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: 0.0)
    marker = tmp_path / "protocol.marker"

    watchdog._terminate(42, marker)

    assert marker.is_file()
    assert signals == [(42, watchdog.signal.SIGTERM)]


def test_terminate_waits_once_when_process_exits_during_grace_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signals: list[object] = []
    monkeypatch.setattr(watchdog.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    alive = iter((True, False, False))
    monkeypatch.setattr(watchdog, "_alive", lambda _pid: next(alive))
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(watchdog.time, "sleep", lambda _: None)

    watchdog._terminate(42, tmp_path / "idle.marker")

    assert signals == [(42, watchdog.signal.SIGTERM)]


def test_event_store_signature_uses_canonical_reader_and_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeStore:
        def __init__(self, path: Path, *, read_only: bool) -> None:
            assert path == tmp_path / "events.db"
            assert read_only is True

        def __enter__(self) -> FakeStore:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def semantic_signature(self) -> tuple[str, ...]:
            return ("committed",)

    monkeypatch.setattr(watchdog, "SQLiteEventStore", FakeStore)
    assert watchdog._event_store_semantic_signature(tmp_path / "events.db") == (
        "committed",
    )

    class BrokenStore(FakeStore):
        def __enter__(self) -> BrokenStore:
            raise RuntimeError("broken store")

    monkeypatch.setattr(watchdog, "SQLiteEventStore", BrokenStore)
    assert watchdog._event_store_semantic_signature(tmp_path / "events.db") is None

    class EmptyStore(FakeStore):
        def semantic_signature(self) -> None:
            return None

    monkeypatch.setattr(watchdog, "SQLiteEventStore", EmptyStore)
    assert watchdog._event_store_semantic_signature(tmp_path / "events.db") is None


def test_state_signature_normalizes_content_and_reads_event_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / ".ae-state"
    (state / "spawn-receipts").mkdir(parents=True)
    (state / "spawn-proofs").mkdir(parents=True)
    (state / "spawn-challenges").mkdir(parents=True)
    (state / "host-runtime" / "worker-outcomes").mkdir(parents=True)
    (state / "host-runtime" / "outcomes").mkdir(parents=True)
    (state / "events.db").write_bytes(b"database")
    (state / "spawn-receipts" / "receipt.json").write_text("receipt", encoding="utf-8")
    (state / "spawn-proofs" / "historical.json").write_text("proof", encoding="utf-8")
    (state / "spawn-challenges" / "historical.json").write_text("challenge", encoding="utf-8")
    (state / "host-runtime" / "worker-outcomes" / "one.json").write_text(
        '{"b":2,"a":1}', encoding="utf-8"
    )
    (state / "host-runtime" / "outcomes" / "bad.json").write_text(
        "not-json", encoding="utf-8"
    )
    monkeypatch.setattr(
        watchdog,
        "_event_store_semantic_signature",
        lambda path: ("event", str(path)),
    )

    signature = watchdog._state_signature(state)

    assert any(item[0].endswith("events.db") for item in signature)
    assert any(item[0].endswith("one.json") for item in signature)
    assert any(item[0].endswith("bad.json") for item in signature)
    assert not any("spawn-receipts" in item[0] for item in signature)
    assert not any("spawn-proofs" in item[0] for item in signature)
    assert not any("spawn-challenges" in item[0] for item in signature)
    assert watchdog._content_marker(tmp_path / "missing.json") is None


def test_state_signature_skips_unreadable_and_unreadable_event_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / ".ae-state"
    state.mkdir()
    (state / "events.db").write_bytes(b"db")
    monkeypatch.setattr(watchdog, "_event_store_semantic_signature", lambda _: None)
    original_stat = Path.stat

    def stat_with_race(path: Path, *args: object, **kwargs: object):
        if path.name == "events.db":
            raise OSError("vanished")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_with_race)
    assert watchdog._state_signature(state) == ()


def test_state_signature_skips_unreadable_content_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / ".ae-state"
    outcomes = state / "host-runtime" / "outcomes"
    outcomes.mkdir(parents=True)
    (outcomes / "outcome.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(watchdog, "_content_marker", lambda _: None)
    assert watchdog._state_signature(state) == ()


def test_state_signature_fails_closed_for_directory_race_and_empty_event_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / ".ae-state"
    outcomes = state / "host-runtime" / "outcomes"
    outcomes.mkdir(parents=True)
    (outcomes / "race.json").write_text("{}", encoding="utf-8")
    (state / "events.db").write_bytes(b"db")
    original_stat = Path.stat

    def stat_with_race(path: Path, *args: object, **kwargs: object):
        if path.name == "race.json":
            raise OSError("vanished")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat_with_race)
    monkeypatch.setattr(watchdog, "_event_store_semantic_signature", lambda _: None)
    assert watchdog._state_signature(state) == ()


def _write_lease(root: Path, *, platform: str = "claude-code") -> dict[str, object]:
    lease = {
        "platform": platform,
        "disposition": "CONTINUE",
        "action_message_id": "action-watchdog",
        "execution_generation": 2,
        "fencing_token": "a" * 64,
    }
    path = root / "host-runtime" / "active-lease.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lease), encoding="utf-8")
    return lease


def test_native_sync_wait_active_accepts_startup_grace_and_bound_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_lease(tmp_path)
    monkeypatch.setenv("AE_HOST_PLATFORM", "claude-code")
    monkeypatch.setattr(watchdog.time, "time", lambda: 1000.0)
    assert watchdog._native_sync_wait_active(
        state_root=tmp_path, attempt_started_epoch=999.0, max_idle=1.0
    ) is True

    monkeypatch.setattr(watchdog.time, "time", lambda: 1000.0)
    observation_root = tmp_path / "host-runtime" / "worker-observations"
    observation_root.mkdir(parents=True)
    (observation_root / "running.json").write_text(
        json.dumps({
            "observed_at": "1970-01-01T00:16:39.123456789+0000",
            "action_message_id": "action-watchdog",
            "execution_generation": 2,
            "fencing_token": "a" * 64,
            "native_status": "running",
        }),
        encoding="utf-8",
    )
    assert watchdog._native_sync_wait_active(
        state_root=tmp_path, attempt_started_epoch=0.0, max_idle=0.1
    ) is True


@pytest.mark.parametrize(
    "observation",
    [
        "not-json",
        {},
        {"observed_at": "not-a-date"},
        {"observed_at": "1970-01-01T00:16:39+00:00", "native_status": "done"},
        {
            "observed_at": "1970-01-01T00:16:39+00:00",
            "action_message_id": "other-action",
            "execution_generation": 2,
            "fencing_token": "a" * 64,
            "native_status": "running",
        },
    ],
)
def test_native_sync_wait_active_rejects_stale_or_malformed_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observation: object,
) -> None:
    _write_lease(tmp_path)
    monkeypatch.setenv("AE_HOST_PLATFORM", "claude-code")
    monkeypatch.setattr(watchdog.time, "time", lambda: 1000.0)
    root = tmp_path / "host-runtime" / "worker-observations"
    root.mkdir(parents=True)
    value = observation if isinstance(observation, str) else json.dumps(observation)
    (root / "observation.json").write_text(value, encoding="utf-8")
    assert watchdog._native_sync_wait_active(
        state_root=tmp_path, attempt_started_epoch=0.0, max_idle=1.0
    ) is False


def test_native_sync_wait_active_fails_closed_without_observation_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_lease(tmp_path)
    monkeypatch.setenv("AE_HOST_PLATFORM", "claude-code")
    monkeypatch.setattr(watchdog.time, "time", lambda: 1000.0)
    assert watchdog._native_sync_wait_active(
        state_root=tmp_path, attempt_started_epoch=0.0, max_idle=1.0
    ) is False


def test_native_sync_wait_active_fails_closed_when_lease_is_missing(
    tmp_path: Path,
) -> None:
    assert watchdog._native_sync_wait_active(
        state_root=tmp_path, attempt_started_epoch=0.0, max_idle=1.0
    ) is False


@pytest.mark.parametrize(
    "lease",
    [
        None,
        {"platform": "codex", "disposition": "CONTINUE"},
        {
            "platform": "claude-code",
            "disposition": "CONTINUE",
            "action_message_id": "action-watchdog",
            "execution_generation": 0,
            "fencing_token": "bad",
        },
    ],
)
def test_native_sync_wait_active_rejects_invalid_lease(
    tmp_path: Path, lease: object
) -> None:
    path = tmp_path / "host-runtime" / "active-lease.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lease), encoding="utf-8")
    assert watchdog._native_sync_wait_active(
        state_root=tmp_path, attempt_started_epoch=0.0, max_idle=1.0
    ) is False


def test_meaningful_stream_activity_whitelists_first_terminal_and_agent_message() -> None:
    assert watchdog._meaningful_stream_activity(
        ["", "noise", "[]", '{"type":"message"}'], terminal_seen=False
    ) == (False, False)
    assert watchdog._meaningful_stream_activity(
        ['{"type":"item.completed","item":{"type":"agent_message"}}'],
        terminal_seen=False,
    ) == (True, False)
    assert watchdog._meaningful_stream_activity(
        ['{"type":"result"}'], terminal_seen=False
    ) == (True, True)
    assert watchdog._meaningful_stream_activity(
        ['{"type":"result"}', '{"type":"message","is_api_error_message":true}'],
        terminal_seen=True,
    ) == (False, True)
    assert watchdog._meaningful_stream_activity(
        ['{"type":"message","is_api_error_message":true}'],
        terminal_seen=False,
    ) == (True, True)
    assert watchdog._meaningful_stream_activity(
        ['{"type":"item.completed","item":{"type":"tool_call"}}'],
        terminal_seen=False,
    ) == (False, False)


def _main_args(
    root: Path,
    *,
    max_runtime: str = "",
    max_idle: str = "100",
    max_protocol: str = "100",
    max_polls: str = "100",
) -> list[str]:
    output = root / "host.jsonl"
    return [
        str(root),
        "42",
        str(output),
        max_idle,
        max_runtime,
        max_protocol,
        max_polls,
        "NATIVE_WORKER_STOP_FORBIDDEN",
        str(root / "idle.marker"),
        str(root / "timeout.marker"),
        str(root / "protocol.marker"),
        str(root / "poll.marker"),
        str(root),
        "0",
    ]


@pytest.mark.parametrize(
    ("kind", "kwargs", "marker"),
    [
        ("runtime", {"max_runtime": "1"}, "timeout.marker"),
        ("idle", {"max_idle": "1"}, "idle.marker"),
        ("protocol", {"max_protocol": "1"}, "protocol.marker"),
        ("poll", {"max_polls": "1"}, "poll.marker"),
    ],
)
def test_main_terminates_only_through_bounded_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    kwargs: dict[str, str],
    marker: str,
) -> None:
    (tmp_path / "host.jsonl").write_text(
        "NATIVE_WORKER_STOP_FORBIDDEN\n"
        if kind == "protocol"
        else "dev-loop --resume 12345678-1234-1234-1234-123456789abc\n"
        if kind == "poll"
        else '{"type":"item.completed","item":{"type":"agent_message"}}'
        if kind == "runtime"
        else "",
        encoding="utf-8",
    )
    if kind == "idle":
        _write_lease(tmp_path, platform="codex")
    monkeypatch.setattr(watchdog, "_alive", lambda _pid: True)
    monkeypatch.setattr(watchdog, "_state_signature", lambda _root: ())
    monkeypatch.setattr(watchdog, "_native_sync_wait_active", lambda **_: False)
    monkeypatch.setattr(watchdog.time, "sleep", lambda _: None)
    clock = iter((0.0, 2.0))
    monkeypatch.setattr(watchdog.time, "monotonic", lambda: next(clock))
    captured: list[Path] = []
    monkeypatch.setattr(
        watchdog,
        "_terminate",
        lambda _pid, marker_path: captured.append(marker_path),
    )

    assert watchdog.main(_main_args(tmp_path, **kwargs)) == 0
    assert captured and captured[0].name == marker


def test_main_handles_output_race_and_truncation_without_exiting_watchdog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "host.jsonl"
    state_calls = 0

    def state_signature(_: Path) -> tuple[tuple[str, str, int], ...]:
        nonlocal state_calls
        state_calls += 1
        if state_calls == 2:
            output.write_text('{"type":"item.completed","item":{"type":"agent_message"}}', encoding="utf-8")
        elif state_calls == 3:
            output.write_text("", encoding="utf-8")
        return () if state_calls != 2 else (("changed", "1", 1),)

    alive = iter((True, True, True, False))
    monkeypatch.setattr(watchdog, "_alive", lambda _pid: next(alive))
    monkeypatch.setattr(watchdog, "_state_signature", state_signature)
    monkeypatch.setattr(watchdog, "_native_sync_wait_active", lambda **_: False)
    monkeypatch.setattr(watchdog.time, "sleep", lambda _: None)
    monkeypatch.setattr(watchdog.time, "monotonic", iter((0.0, 1.0, 2.0, 3.0)).__next__)

    assert watchdog.main(_main_args(tmp_path, max_idle="100")) == 0
    assert state_calls == 4


def test_main_handles_attempt_output_open_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "host.jsonl"
    output.write_text(
        '{"type":"item.completed","item":{"type":"agent_message"}}',
        encoding="utf-8",
    )
    original_open = Path.open

    def open_with_race(path: Path, *args: object, **kwargs: object):
        if path == output:
            raise OSError("vanished")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(watchdog, "_alive", lambda _pid: True)
    monkeypatch.setattr(watchdog, "_state_signature", lambda _root: ())
    monkeypatch.setattr(watchdog, "_native_sync_wait_active", lambda **_: False)
    monkeypatch.setattr(watchdog.time, "sleep", lambda _: None)
    monkeypatch.setattr(watchdog.time, "monotonic", iter((0.0, 2.0)).__next__)
    monkeypatch.setattr(Path, "open", open_with_race)
    captured: list[Path] = []
    monkeypatch.setattr(watchdog, "_terminate", lambda _pid, path: captured.append(path))

    assert watchdog.main(_main_args(tmp_path, max_runtime="1", max_idle="100")) == 0
    assert captured and captured[0].name == "timeout.marker"


def test_main_tolerates_missing_attempt_output_before_runtime_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watchdog, "_alive", lambda _pid: True)
    monkeypatch.setattr(watchdog, "_state_signature", lambda _root: ())
    monkeypatch.setattr(watchdog, "_native_sync_wait_active", lambda **_: False)
    monkeypatch.setattr(watchdog.time, "sleep", lambda _: None)
    monkeypatch.setattr(watchdog.time, "monotonic", iter((0.0, 2.0)).__next__)
    captured: list[Path] = []
    monkeypatch.setattr(watchdog, "_terminate", lambda _pid, path: captured.append(path))

    assert watchdog.main(
        _main_args(tmp_path, max_runtime="1", max_idle="100")
    ) == 0
    assert captured and captured[0].name == "timeout.marker"
