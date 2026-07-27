"""Codex Hook schema、stdin 和事件归一化测试。"""

from __future__ import annotations

import json
import subprocess
from io import StringIO
from pathlib import Path

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
    assert all(command == "./hooks/codex-hook.sh" for command in commands)


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
    assert result.stdout == ""
    assert result.stderr == ""


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
