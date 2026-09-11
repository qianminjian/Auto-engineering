"""Codex Hook schema、stdin 和事件归一化测试。"""

from __future__ import annotations

import json
import re
import subprocess
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
EVENTS = {"SessionStart", "PreToolUse", "PostToolUse", "Stop"}


def _load_hooks(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def test_plugin_hooks_use_codex_matcher_handler_schema() -> None:
    config = _load_hooks(ROOT / "hooks-codex.json")
    hooks = config["hooks"]

    assert isinstance(hooks, dict)
    assert set(hooks) == EVENTS
    for groups in hooks.values():
        assert isinstance(groups, list)
        assert groups
        for group in groups:
            assert isinstance(group, dict)
            handlers = group["hooks"]
            assert isinstance(handlers, list)
            assert handlers
            assert handlers[0]["type"] == "command"
            assert "$PLUGIN_ROOT/hooks/codex-hook.sh" in handlers[0]["command"]


def test_plugin_hook_matchers_are_valid_codex_regexes() -> None:
    """Codex matcher 必须是可编译的正则，避免版本相关的通配符歧义。"""

    config = _load_hooks(ROOT / "hooks-codex.json")
    hooks = config["hooks"]

    assert isinstance(hooks, dict)
    for groups in hooks.values():
        assert isinstance(groups, list)
        for group in groups:
            assert isinstance(group, dict)
            matcher = group.get("matcher")
            if isinstance(matcher, str):
                assert matcher != "*"
                re.compile(matcher)


def test_project_hooks_use_workspace_handler_path() -> None:
    config = _load_hooks(ROOT / ".codex" / "hooks.json")
    hooks = config["hooks"]

    assert isinstance(hooks, dict)
    assert set(hooks) == EVENTS
    commands = [
        handler["command"]
        for groups in hooks.values()
        for group in groups
        for handler in group["hooks"]
    ]
    assert commands
    assert all(
        command == '"$(git rev-parse --show-toplevel)/hooks/codex-hook.sh"'
        for command in commands
    )


def test_normalizes_codex_pre_tool_event(tmp_path: Path) -> None:
    from auto_engineering.host.codex_hooks import normalize_codex_event

    event = normalize_codex_event({
        "hook_event_name": "PreToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "session_id": "session-1",
    })

    assert event.event == "pre_tool"
    assert event.platform == "codex"
    assert event.tool == "Bash"
    assert event.file_path is None
    assert event.project_root == tmp_path.resolve()
    assert event.raw["session_id"] == "session-1"


def test_normalizes_codex_file_path(tmp_path: Path) -> None:
    from auto_engineering.host.codex_hooks import normalize_codex_event

    event = normalize_codex_event({
        "hook_event_name": "PostToolUse",
        "cwd": str(tmp_path),
        "tool_name": "apply_patch",
        "tool_input": {"file_path": "src/app.py"},
    })

    assert event.event == "post_tool"
    assert event.file_path == "src/app.py"


def test_codex_pre_tool_dispatch_emits_host_blocking_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from auto_engineering.host.codex_hook_dispatch import main
    from auto_engineering.host.native_launch_guard import NativeLaunchGuardError

    def blocked(*args: object, **kwargs: object) -> None:
        raise NativeLaunchGuardError("AE_STATE_MUTATION_FORBIDDEN")

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.guard_active_native_tool_call",
        blocked,
    )
    output = StringIO()
    assert main(StringIO(json.dumps({
        "hook_event_name": "PreToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "printf x > .ae-state/events.db"},
    })), output) == 0

    payload = json.loads(output.getvalue())
    assert set(payload) == {"systemMessage", "hookSpecificOutput"}
    assert payload["hookSpecificOutput"] == {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": payload["systemMessage"],
    }


def test_codex_pre_tool_dispatch_emits_explicit_allow_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from auto_engineering.host.codex_hook_dispatch import main

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.guard_active_native_tool_call",
        lambda *args, **kwargs: None,
    )
    output = StringIO()
    assert main(StringIO(json.dumps({
        "hook_event_name": "PreToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
    })), output) == 0

    payload = json.loads(output.getvalue())
    assert payload == {"systemMessage": "Auto-Engineering Hook 已安全跳过"}


def test_codex_post_tool_persists_spawn_response_without_rebuilding_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auto_engineering.host import codex_hooks

    worker = {
        "worker_id": "developer-0",
        "native_launch_prompt": "native-prompt",
        "native_result_path": ".ae-state/host-runtime/native-results/developer.json",
    }
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    raw = '{"receiver_thread_ids":["agent-1"],"agents_states":{"agent-1":"pending"}}'
    output = StringIO()
    assert codex_hooks.main(StringIO(json.dumps({
        "hook_event_name": "PostToolUse",
        "cwd": str(tmp_path),
        "tool_name": "multi_agent_v1__spawn_agent",
        "tool_input": {"prompt": "native-prompt"},
        "tool_response": raw,
    })), output) == 0
    path = tmp_path / str(worker["native_result_path"])
    assert path.read_bytes() == raw.encode()
    assert "启动事实已固化" in json.loads(output.getvalue())["systemMessage"]


def test_codex_post_tool_persists_only_target_completed_body_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auto_engineering.host import codex_hooks

    worker = {
        "worker_id": "developer-0",
        "native_result_path": ".ae-state/host-runtime/native-results/developer.json",
    }
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    spawn_raw = '{"receiver_thread_ids":["agent-1"]}'
    path = tmp_path / str(worker["native_result_path"])
    path.parent.mkdir(parents=True)
    path.write_bytes(spawn_raw.encode())
    completed = '{"worker_id":"developer-0","status":"completed"}'
    wait_raw = json.dumps({"status": {"agent-1": {"completed": completed}}})
    output = StringIO()
    assert codex_hooks.main(StringIO(json.dumps({
        "hook_event_name": "PostToolUse", "cwd": str(tmp_path),
        "tool_name": "collaboration.wait_agent",
        "tool_input": {"targets": ["agent-1"]}, "tool_response": wait_raw,
    })), output) == 0
    assert path.read_bytes() == completed.encode()
    assert "完成证据已固化" in json.loads(output.getvalue())["systemMessage"]


def test_codex_post_tool_persists_real_wait_message_body_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 Codex wait 将完成 envelope 放在 target.message 中。"""

    from auto_engineering.host import codex_hooks

    worker = {
        "worker_id": "critic-0",
        "native_result_path": ".ae-state/host-runtime/native-results/critic.json",
    }
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    spawn_raw = '{"receiver_thread_ids":["agent-1"]}'
    path = tmp_path / str(worker["native_result_path"])
    path.parent.mkdir(parents=True)
    path.write_bytes(spawn_raw.encode())
    completed = (
        '{"worker_id":"critic-0","status":"completed",'
        '"payload":{"verdict":"APPROVE"}}'
    )
    wait_raw = json.dumps({
        "agents_states": {
            "agent-1": {"status": "completed", "message": completed},
        },
    })
    output = StringIO()
    assert codex_hooks.main(StringIO(json.dumps({
        "hook_event_name": "PostToolUse", "cwd": str(tmp_path),
        "tool_name": "collaboration.wait_agent",
        "tool_input": {"targets": ["agent-1"]}, "tool_response": wait_raw,
    })), output) == 0
    assert path.read_bytes() == completed.encode()
    assert "完成证据已固化" in json.loads(output.getvalue())["systemMessage"]


def test_codex_post_tool_records_completed_status_without_null_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 Codex completed:null 只能形成终态观察，不能伪造业务正文。"""

    from auto_engineering.host import codex_hooks

    worker = {
        "worker_id": "developer-0",
        "execution_generation": 1,
        "fencing_token": "a" * 64,
        "native_result_path": ".ae-state/host-runtime/native-results/developer.json",
    }
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    monkeypatch.setattr(
        "auto_engineering.host.runtime_driver.HostRunLeaseStore.load",
        lambda _store: SimpleNamespace(action_message_id="action-1"),
    )
    native_path = tmp_path / str(worker["native_result_path"])
    native_path.parent.mkdir(parents=True)
    native_path.write_text(
        '{"receiver_thread_ids":["agent-1"]}', encoding="utf-8"
    )
    output = StringIO()
    wait_raw = json.dumps({
        "agents_states": {
            "agent-1": {"status": "completed", "message": None},
        },
    })

    assert codex_hooks.main(StringIO(json.dumps({
        "hook_event_name": "PostToolUse",
        "cwd": str(tmp_path),
        "tool_name": "collaboration.wait_agent",
        "tool_input": {"targets": ["agent-1"], "timeout_ms": 300_000},
        "tool_response": wait_raw,
    })), output) == 0

    observation = json.loads(
        (tmp_path / ".ae-state/host-runtime/worker-observations/"
         "action-1-developer-0-g1.json").read_text(encoding="utf-8")
    )
    assert observation["native_status"] == "completed"
    assert observation["native_worker_handle"] == "agent-1"
    assert "--native-status-only" in json.loads(
        output.getvalue()
    )["systemMessage"]
    assert native_path.read_text(encoding="utf-8") == (
        '{"receiver_thread_ids":["agent-1"]}'
    )


def test_codex_wait_post_tool_records_running_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """wait 未终态时，Hook 必须自动落盘 Action-scoped 观察事实。"""

    from auto_engineering.host import codex_hooks

    worker = {
        "worker_id": "developer-0",
        "execution_generation": 1,
        "fencing_token": "a" * 64,
        "native_result_path": ".ae-state/host-runtime/native-results/developer.json",
    }
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    monkeypatch.setattr(
        "auto_engineering.host.runtime_driver.HostRunLeaseStore.load",
        lambda _store: SimpleNamespace(action_message_id="action-1"),
    )
    native_path = tmp_path / str(worker["native_result_path"])
    native_path.parent.mkdir(parents=True)
    native_path.write_text(
        '{"receiver_thread_ids":["agent-1"]}', encoding="utf-8"
    )
    output = StringIO()
    wait_raw = json.dumps({
        "agents_states": {
            "agent-1": {"status": "running", "message": "仍在运行"},
        },
    })

    assert codex_hooks.main(StringIO(json.dumps({
        "hook_event_name": "PostToolUse",
        "cwd": str(tmp_path),
        "tool_name": "collaboration.wait_agent",
        "tool_input": {"targets": ["agent-1"], "timeout_ms": 300_000},
        "tool_response": wait_raw,
    })), output) == 0

    observation = json.loads(
        (tmp_path / ".ae-state/host-runtime/worker-observations/"
         "action-1-developer-0-g1.json").read_text(encoding="utf-8")
    )
    assert observation["native_status"] == "running"
    assert observation["wait_attempt"] == 1
    assert observation["owner_known"] is True


def test_codex_wait_third_observation_requires_owner_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三次长等待后不得把 CONTINUE 静默交还给宿主。"""

    from auto_engineering.host import codex_hooks

    worker = {
        "worker_id": "developer-0",
        "execution_generation": 1,
        "fencing_token": "a" * 64,
        "native_result_path": ".ae-state/host-runtime/native-results/developer.json",
    }
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    monkeypatch.setattr(
        "auto_engineering.host.runtime_driver.HostRunLeaseStore.load",
        lambda _store: SimpleNamespace(action_message_id="action-1"),
    )
    native_path = tmp_path / str(worker["native_result_path"])
    native_path.parent.mkdir(parents=True)
    native_path.write_text(
        '{"receiver_thread_ids":["agent-1"]}', encoding="utf-8"
    )
    observation_dir = tmp_path / ".ae-state/host-runtime/worker-observations"
    observation_dir.mkdir(parents=True)
    observation_path = observation_dir / "action-1-developer-0-g1.json"
    observation_path.write_text(
        json.dumps({"wait_attempt": 2}), encoding="utf-8"
    )
    output = StringIO()
    wait_raw = json.dumps({
        "agents_states": {
            "agent-1": {"status": "running", "message": "仍在运行"},
        },
    })

    assert codex_hooks.main(StringIO(json.dumps({
        "hook_event_name": "PostToolUse",
        "cwd": str(tmp_path),
        "tool_name": "collaboration.wait_agent",
        "tool_input": {"targets": ["agent-1"], "timeout_ms": 300_000},
        "tool_response": wait_raw,
    })), output) == 0

    response = json.loads(output.getvalue())
    assert "所有权不确定" in response["systemMessage"]
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    assert observation["native_status"] == "unknown"
    assert observation["wait_attempt"] == 3
    assert observation["owner_known"] is False


def test_codex_post_tool_does_not_reencode_structured_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auto_engineering.host import codex_hooks

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [{
            "worker_id": "developer-0",
            "native_launch_prompt": "native-prompt",
            "native_result_path": ".ae-state/host-runtime/native-results/developer.json",
        }],
    )
    output = StringIO()
    assert codex_hooks.main(StringIO(json.dumps({
        "hook_event_name": "PostToolUse", "cwd": str(tmp_path),
        "tool_name": "collaboration.spawn_agent",
        "tool_input": {"prompt": "native-prompt"},
        "tool_response": {"receiver_thread_ids": ["agent-1"]},
    })), output) == 0
    assert "未提供原始返回" in json.loads(output.getvalue())["systemMessage"]


def test_codex_pre_tool_blocks_native_contract_guard_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_engineering.host import codex_hooks
    from auto_engineering.host.native_launch_guard import NativeLaunchGuardError

    def reject(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise NativeLaunchGuardError("NATIVE_LAUNCH_PROMPT_MISMATCH")

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.guard_active_native_tool_call",
        reject,
    )
    output = StringIO()
    payload = {
        "hook_event_name": "PreToolUse",
        "cwd": str(tmp_path),
        "tool_name": "collaboration.spawn_agent",
        "tool_input": {"prompt": "stale"},
    }

    assert codex_hooks.main(StringIO(json.dumps(payload)), output) == 0
    response = json.loads(output.getvalue())
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert response["hookSpecificOutput"]["permissionDecisionReason"] == response[
        "systemMessage"
    ]
    assert "原生 Worker 启动" in response["systemMessage"]


def test_codex_pre_tool_blocks_wait_timeout_that_ignores_action_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hook 层必须阻止宿主绕过 Action 注入的等待预算。"""

    from auto_engineering.host import codex_hooks

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [{
            "worker_id": "architect-0",
            "worker_observation": {
                "mode": "native_wait",
                "wait_timeout_ms": 300_000,
            },
        }],
    )
    output = StringIO()
    payload = {
        "hook_event_name": "PreToolUse",
        "cwd": str(tmp_path),
        "tool_name": "collaboration.wait_agent",
        "tool_input": {"targets": ["architect-native"], "timeout_ms": 30_000},
    }

    assert codex_hooks.main(StringIO(json.dumps(payload)), output) == 0
    response = json.loads(output.getvalue())
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "短等待" in response["systemMessage"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"hook_event_name": "Unknown", "cwd": "/tmp"},
        {"hook_event_name": "Stop"},
    ],
)
def test_normalizer_rejects_incomplete_or_unknown_events(
    payload: dict[str, object],
) -> None:
    from auto_engineering.host.codex_hooks import normalize_codex_event

    with pytest.raises(ValueError):
        normalize_codex_event(payload)


@pytest.mark.parametrize("payload", ["[]", "{not-json"])
def test_hook_main_safely_reports_invalid_stdin(payload: str) -> None:
    from auto_engineering.host.codex_hooks import main

    output = StringIO()

    assert main(StringIO(payload), output) == 0
    response = json.loads(output.getvalue())
    assert "安全跳过" in response["systemMessage"]


def test_codex_hook_handler_reads_valid_json_from_stdin(tmp_path: Path) -> None:
    handler = ROOT / "hooks" / "codex-hook.sh"
    environ = {"PLUGIN_ROOT": str(ROOT), "PATH": "/usr/bin:/bin"}
    payload = json.dumps({
        "hook_event_name": "SessionStart",
        "cwd": str(tmp_path),
        "session_id": "session-1",
    })

    result = subprocess.run(
        [str(handler)],
        input=payload,
        env=environ,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "安全跳过" in json.loads(result.stdout)["systemMessage"]


def test_codex_hook_handler_safely_skips_invalid_json() -> None:
    handler = ROOT / "hooks" / "codex-hook.sh"
    environ = {"PLUGIN_ROOT": str(ROOT), "PATH": "/usr/bin:/bin"}

    result = subprocess.run(
        [str(handler)],
        input="{not-json",
        env=environ,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert "systemMessage" in response
    assert "安全跳过" in response["systemMessage"]


def test_stop_hook_blocks_same_session_with_continue_lease(tmp_path: Path) -> None:
    from auto_engineering.host.runtime_driver import HostRunLease, HostRunLeaseStore

    HostRunLeaseStore(tmp_path).save(HostRunLease(
        schema_version="1.0",
        thread_id="thread-1",
        action_message_id="action-1",
        platform="codex",
        host_session_id="session-1",
        build_id="build-1",
        disposition="CONTINUE",
        continuation_required=True,
        yield_allowed=False,
    ))
    output = StringIO()
    payload = {
        "hook_event_name": "Stop",
        "cwd": str(tmp_path),
        "session_id": "session-1",
    }

    from auto_engineering.host.codex_hooks import main

    assert main(StringIO(json.dumps(payload)), output) == 0
    response = json.loads(output.getvalue())
    assert response == {
        "continue": False,
        "stopReason": "AE_CONTINUATION_REQUIRED",
        "systemMessage": "Auto-Engineering 仍有必须继续执行的 Action",
    }


def test_claude_stop_hook_blocks_same_session_with_continue_lease(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.runtime_driver import HostRunLease, HostRunLeaseStore

    HostRunLeaseStore(tmp_path).save(HostRunLease(
        schema_version="1.0",
        thread_id="thread-1",
        action_message_id="action-1",
        platform="claude-code",
        host_session_id="session-1",
        build_id="build-1",
        disposition="CONTINUE",
        continuation_required=True,
        yield_allowed=False,
    ))
    output = StringIO()
    payload = {
        "hook_event_name": "Stop",
        "cwd": str(tmp_path),
        "session_id": "session-1",
    }

    from auto_engineering.host.claude_hooks import main

    assert main(StringIO(json.dumps(payload)), output) == 0
    response = json.loads(output.getvalue())
    assert response["decision"] == "block"
    assert response["reason_code"] == "AE_CONTINUATION_REQUIRED"
    assert response["continuation"]["resume_operation"]["argv"] == [
        "dev-loop", "--resume", "thread-1",
    ]


def test_claude_stop_shell_uses_plugin_runtime(tmp_path: Path) -> None:
    from auto_engineering.host.runtime_driver import HostRunLease, HostRunLeaseStore

    HostRunLeaseStore(tmp_path).save(HostRunLease(
        schema_version="1.0",
        thread_id="thread-1",
        action_message_id="action-1",
        platform="claude-code",
        host_session_id="session-1",
        build_id="build-1",
        disposition="CONTINUE",
        continuation_required=True,
        yield_allowed=False,
    ))
    payload = json.dumps({
        "hook_event_name": "Stop",
        "cwd": str(tmp_path),
        "session_id": "session-1",
    })

    result = subprocess.run(
        [str(ROOT / "hooks" / "stop.sh")],
        input=payload,
        env={"PLUGIN_ROOT": str(ROOT), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["decision"] == "block"


def test_claude_stop_shell_uses_only_dedicated_runtime_contract() -> None:
    source = (ROOT / "hooks" / "stop.sh").read_text(encoding="utf-8")

    assert '"$RUNTIME_ROOT/bin/python"' in source
    assert '"$PLUGIN_DIR/.venv/bin/python"' not in source
    assert '"$PLUGIN_DIR/scripts/ae-run" --run-module' in source
