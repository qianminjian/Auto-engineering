"""Claude PostToolUse 原生 Worker 证据捕获测试。"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest


def _worker(root: Path) -> dict[str, object]:
    return {
        "worker_id": "architect-0",
        "native_result_path": ".ae-state/host-runtime/native-results/architect.json",
    }


def test_session_end_defers_stop_report_to_outer_host_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """外层适配器存在时，Hook 不能先消费退出租约。"""

    from auto_engineering.host import claude_hooks
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
    monkeypatch.setenv("AE_HOST_ADAPTER_ACTIVE", "1")
    output = StringIO()

    assert claude_hooks.main(
        StringIO(json.dumps({
            "hook_event_name": "StopFailure",
            "cwd": str(tmp_path),
            "session_id": "session-1",
            "reason": "unknown",
        })),
        output,
    ) == 0

    assert HostRunLeaseStore(tmp_path).load() is not None
    assert list((tmp_path / ".ae-state/host-runtime/stop-reports").glob("*.json")) == []


def test_post_tool_captures_agent_response_at_action_bound_path(
    tmp_path: Path, monkeypatch
) -> None:
    from auto_engineering.host import claude_hooks

    worker = _worker(tmp_path)
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    prompt = (
        "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\n"
        "VERBATIM=1;NO_EXTRA\n"
        '{"worker_id":"architect-0","outcome_path":"private.json"}'
    )
    response = {"content": [{"type": "text", "text": '{"verdict":"APPROVE"}'}]}

    output = StringIO()
    assert claude_hooks.main(
        StringIO(json.dumps({
            "hook_event_name": "PostToolUse",
            "cwd": str(tmp_path),
            "tool_name": "Agent",
            "tool_input": {"prompt": prompt},
            "tool_response": response,
        })),
        output,
    ) == 0

    native_path = tmp_path / str(worker["native_result_path"])
    assert json.loads(native_path.read_text(encoding="utf-8")) == response
    assert "已固化" in json.loads(output.getvalue())["systemMessage"]


def test_post_tool_does_not_capture_non_agent_tools(tmp_path: Path, monkeypatch) -> None:
    from auto_engineering.host import claude_hooks

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: (_ for _ in ()).throw(AssertionError("不应读取 Worker")),
    )
    output = StringIO()
    assert claude_hooks.main(
        StringIO(json.dumps({
            "hook_event_name": "PostToolUse",
            "cwd": str(tmp_path),
            "tool_name": "Write",
            "tool_input": {},
        })),
        output,
    ) == 0
    assert "安全跳过" in json.loads(output.getvalue())["systemMessage"]


def test_task_output_replaces_async_agent_metadata_with_completed_output(
    tmp_path: Path, monkeypatch
) -> None:
    from auto_engineering.host import claude_hooks

    worker = _worker(tmp_path)
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    agent_prompt = (
        "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\n"
        "VERBATIM=1;NO_EXTRA\n"
        '{"worker_id":"architect-0","outcome_path":"private.json"}'
    )
    agent_output = StringIO()
    claude_hooks.main(
        StringIO(json.dumps({
            "hook_event_name": "PostToolUse",
            "cwd": str(tmp_path),
            "tool_name": "Agent",
            "tool_input": {"prompt": agent_prompt},
            "tool_response": {"agentId": "agent-123", "status": "async_launched"},
        })),
        agent_output,
    )

    task_output = "<task_id>agent-123</task_id>\n<status>completed</status>\n<output>"
    task_output += '{"verdict":"APPROVE"}'
    task_output += "</output>"
    output = StringIO()
    assert claude_hooks.main(
        StringIO(json.dumps({
            "hook_event_name": "PostToolUse",
            "cwd": str(tmp_path),
            "tool_name": "TaskOutput",
            "tool_input": {"task_id": "agent-123"},
            "tool_response": task_output,
        })),
        output,
    ) == 0

    native_path = tmp_path / str(worker["native_result_path"])
    assert json.loads(native_path.read_text(encoding="utf-8")) == {
        "content": [{"type": "text", "text": '{"verdict":"APPROVE"}'}]
    }
    assert "已固化" in json.loads(output.getvalue())["systemMessage"]


def test_task_output_running_observation_preserves_agent_handle(
    tmp_path: Path, monkeypatch
) -> None:
    from auto_engineering.host import claude_hooks

    worker = _worker(tmp_path)
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    native_path = tmp_path / str(worker["native_result_path"])
    native_path.parent.mkdir(parents=True)
    metadata = {"agentId": "agent-123", "status": "async_launched"}
    native_path.write_text(json.dumps(metadata), encoding="utf-8")

    output = StringIO()
    assert claude_hooks.main(
        StringIO(json.dumps({
            "hook_event_name": "PostToolUse",
            "cwd": str(tmp_path),
            "tool_name": "TaskOutput",
            "tool_input": {"task_id": "agent-123"},
            "tool_response": "<task_id>agent-123</task_id>\n<status>running</status>",
        })),
        output,
    ) == 0

    assert json.loads(native_path.read_text(encoding="utf-8")) == metadata
    assert "仍在运行" in json.loads(output.getvalue())["systemMessage"]


def test_task_output_unwraps_completed_object_envelope(
    tmp_path: Path, monkeypatch
) -> None:
    """对象格式 TaskOutput 只能固化 task.output，不得泄漏宿主信封。"""

    from auto_engineering.host import claude_hooks

    worker = _worker(tmp_path)
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    agent_prompt = (
        "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\n"
        "VERBATIM=1;NO_EXTRA\n"
        '{"worker_id":"architect-0","outcome_path":"private.json"}'
    )
    claude_hooks.main(
        StringIO(json.dumps({
            "hook_event_name": "PostToolUse",
            "cwd": str(tmp_path),
            "tool_name": "Agent",
            "tool_input": {"prompt": agent_prompt},
            "tool_response": {"agentId": "agent-123", "status": "async_launched"},
        })),
        StringIO(),
    )

    output = StringIO()
    task_output = {
        "retrieval_status": "success",
        "task": {
            "task_id": "agent-123",
            "status": "completed",
            "output": "完成。```json\n{\"verdict\":\"APPROVE\"}\n```",
        },
    }
    assert claude_hooks.main(
        StringIO(json.dumps({
            "hook_event_name": "PostToolUse",
            "cwd": str(tmp_path),
            "tool_name": "TaskOutput",
            "tool_input": {"task_id": "agent-123"},
            "tool_response": task_output,
        })),
        output,
    ) == 0

    native_path = tmp_path / str(worker["native_result_path"])
    assert json.loads(native_path.read_text(encoding="utf-8")) == {
        "content": [{
            "type": "text",
            "text": "完成。```json\n{\"verdict\":\"APPROVE\"}\n```",
        }],
    }
    assert "已固化" in json.loads(output.getvalue())["systemMessage"]


@pytest.mark.parametrize("tool_name", ["Agent", "Task"])
def test_pre_tool_records_native_agent_running_observation(
    tmp_path: Path, monkeypatch, tool_name: str
) -> None:
    """Claude Agent 调用开始前必须留下当前 Action 的运行观察。"""

    from auto_engineering.host import claude_hooks
    from auto_engineering.host.runtime_driver import (
        HostRunLease,
        HostRunLeaseStore,
        fencing_token_for,
    )

    session_id = "claude-session"
    HostRunLeaseStore(tmp_path).save(HostRunLease(
        schema_version="1.0",
        thread_id="thread-1",
        action_message_id="action-1",
        platform="claude-code",
        host_session_id=session_id,
        build_id="build-1",
        disposition="CONTINUE",
        continuation_required=True,
        yield_allowed=False,
        execution_generation=1,
        fencing_token=fencing_token_for("action-1", session_id, 1),
    ))
    worker = {
        **_worker(tmp_path),
        "execution_generation": 1,
        "fencing_token": fencing_token_for("action-1", "architect-0", 1),
    }
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    prompt = (
        "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\n"
        "VERBATIM=1;NO_EXTRA\n"
        '{"worker_id":"architect-0","outcome_path":"private.json"}'
    )

    output = StringIO()
    assert claude_hooks.main(
        StringIO(json.dumps({
            "hook_event_name": "PreToolUse",
            "cwd": str(tmp_path),
            "tool_name": tool_name,
            "tool_input": {"prompt": prompt},
        })),
        output,
    ) == 0

    observation_path = (
        tmp_path / ".ae-state/host-runtime/worker-observations/"
        "action-1-architect-0-g1.json"
    )
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    assert observation["action_message_id"] == "action-1"
    assert observation["worker_id"] == "architect-0"
    assert observation["native_status"] == "running"
    assert observation["owner_known"] is False


def test_post_tool_agent_closes_running_observation(
    tmp_path: Path, monkeypatch
) -> None:
    """同步 Agent 结束后，旧 running 观察不得继续伪装活跃。"""

    from auto_engineering.host import claude_hooks
    from auto_engineering.host.runtime_driver import (
        HostRunLease,
        HostRunLeaseStore,
        fencing_token_for,
    )

    session_id = "claude-session"
    HostRunLeaseStore(tmp_path).save(HostRunLease(
        schema_version="1.0",
        thread_id="thread-1",
        action_message_id="action-1",
        platform="claude-code",
        host_session_id=session_id,
        build_id="build-1",
        disposition="CONTINUE",
        continuation_required=True,
        yield_allowed=False,
        execution_generation=1,
        fencing_token=fencing_token_for("action-1", session_id, 1),
    ))
    worker = {
        **_worker(tmp_path),
        "execution_generation": 1,
        "fencing_token": fencing_token_for("action-1", "architect-0", 1),
    }
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    prompt = (
        "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\n"
        "VERBATIM=1;NO_EXTRA\n"
        '{"worker_id":"architect-0","outcome_path":"private.json"}'
    )

    claude_hooks.main(
        StringIO(json.dumps({
            "hook_event_name": "PreToolUse",
            "cwd": str(tmp_path),
            "tool_name": "Agent",
            "tool_input": {"prompt": prompt},
        })),
        StringIO(),
    )
    claude_hooks.main(
        StringIO(json.dumps({
            "hook_event_name": "PostToolUse",
            "cwd": str(tmp_path),
            "tool_name": "Agent",
            "tool_input": {"prompt": prompt},
            "tool_response": {"content": [{"type": "text", "text": "{}"}]},
        })),
        StringIO(),
    )

    observation_path = (
        tmp_path / ".ae-state/host-runtime/worker-observations/"
        "action-1-architect-0-g1.json"
    )
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    assert observation["native_status"] == "unknown"
    assert observation["owner_known"] is False
