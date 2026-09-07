"""Claude PostToolUse 原生 Worker 证据捕获测试。"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path


def _worker(root: Path) -> dict[str, object]:
    return {
        "worker_id": "architect-0",
        "native_result_path": ".ae-state/host-runtime/native-results/architect.json",
    }


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
