"""T540-T541：Codex/Claude 一次性宿主调用后端。"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from auto_engineering.host.invocation import ActionExecutionRequest


def _request(root: Path) -> ActionExecutionRequest:
    return ActionExecutionRequest.from_dict({
        "schema_version": "1.0",
        "thread_id": "thread-1",
        "action_message_id": "action-1",
        "tick": 1,
        "stage": "developer",
        "build_id": "release-build-1",
        "project_root": str(root.resolve()),
        "compact_envelope_ref": ".ae-state/work/a/envelope.json",
        "compact_envelope_sha256": "a" * 64,
        "coordinator_ref": ".ae-state/work/a/coordinator.md",
        "coordinator_sha256": "b" * 64,
        "work_files": {
            "outcomes": ".ae-state/work/a/outcomes.json",
            "coordinator_result": ".ae-state/work/a/coordinator-result.json",
            "result": ".ae-state/work/a/result.json",
        },
        "allowed_tools": ["read", "edit", "shell"],
    })


def test_codex_backend_builds_ephemeral_non_resuming_command(tmp_path: Path) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    backend = CodexInvocationBackend(executable="/opt/bin/codex")
    command = backend.build_command(_request(tmp_path))

    assert command[:3] == ("/opt/bin/codex", "exec", "--ephemeral")
    assert ("-C", str(tmp_path.resolve())) == command[
        command.index("-C") : command.index("-C") + 2
    ]
    assert "--json" in command
    assert command[
        command.index("-s") : command.index("-s") + 2
    ] == ("-s", "workspace-write")
    assert "--output-schema" in command
    assert "--ignore-user-config" in command
    assert "--skip-git-repo-check" in command
    assert command.count("--disable") == 3
    assert {"plugins", "skill_search", "apps"} <= set(command)
    assert "sandbox_workspace_write.network_access=true" in command
    assert "resume" not in command
    assert "--continue" not in command


def test_launcher_forbids_identity_and_result_wrappers(tmp_path: Path) -> None:
    from auto_engineering.host.backends.common import launcher_prompt

    prompt = launcher_prompt(_request(tmp_path))

    assert "只包含 expected_format 业务字段" in prompt
    assert "result_contract" in prompt
    assert "数组和对象必须写为原生 JSON" in prompt
    assert "不得包装在 result" in prompt
    assert "不得复制 action/stage/tick/thread_id" in prompt
    assert "允许按 Prompt 要求修改 project_root 内业务文件" in prompt
    assert "不得修改执行包、Core 状态或 result 文件" in prompt
    assert "必须把业务 JSON 原子写入" in prompt
    assert 'outcomes 的 JSON object：{"outcomes":[{' in prompt
    assert "不得写顶层数组、单个 outcome 或字符串化 JSON" in prompt
    assert "绝不写 request.work_files.result" in prompt
    assert "spawn_permitted=false" in prompt
    assert "不得重新启动 Worker" in prompt


def test_launcher_keeps_audit_action_project_read_only(tmp_path: Path) -> None:
    from dataclasses import replace

    from auto_engineering.host.backends.common import launcher_prompt

    request = replace(_request(tmp_path), allowed_tools=("read", "shell"))

    assert "不允许修改项目业务文件" in launcher_prompt(request)
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    command = CodexInvocationBackend(executable="/opt/bin/codex").build_command(
        request
    )
    assert "sandbox_workspace_write.network_access=true" not in command


def test_codex_output_schema_requires_every_declared_property(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    command = CodexInvocationBackend(executable="/opt/bin/codex").build_command(
        _request(tmp_path)
    )
    schema_path = Path(command[command.index("--output-schema") + 1])
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["error_code"]["type"] == ["string", "null"]


def test_codex_probe_requires_the_exact_executable(tmp_path: Path) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    backend = CodexInvocationBackend(executable=str(tmp_path / "missing-codex"))
    probe = backend.probe()
    assert probe.supported is False
    assert probe.reason_code == "HOST_CODEX_CLI_MISSING"


def test_codex_probe_fails_closed_when_required_flags_are_missing(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    executable = tmp_path / "codex"
    executable.write_text(
        "#!/bin/sh\necho --ephemeral --output-schema\n", encoding="utf-8",
    )
    executable.chmod(0o755)

    probe = CodexInvocationBackend(executable=str(executable)).probe()

    assert probe.supported is False
    assert probe.reason_code == "HOST_CODEX_CAPABILITY_MISSING"


def test_claude_backend_builds_non_persistent_bounded_command(tmp_path: Path) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    backend = ClaudeInvocationBackend(
        executable="/opt/bin/claude",
        environ={},
        max_budget_usd=2.0,
    )
    command = backend.build_command(_request(tmp_path))

    assert command[:2] == ("/opt/bin/claude", "-p")
    assert "--no-session-persistence" in command
    assert "--setting-sources" not in command
    assert command[
        command.index("--mcp-config") : command.index("--mcp-config") + 2
    ] == ("--mcp-config", '{"mcpServers":{}}')
    assert "--strict-mcp-config" in command
    assert "--disable-slash-commands" in command
    assert "--no-chrome" in command
    assert command[
        command.index("--effort") : command.index("--effort") + 2
    ] == ("--effort", "low")
    assert "--bare" not in command
    assert "--safe-mode" in command
    assert command[
        command.index("--output-format") : command.index("--output-format") + 2
    ] == ("--output-format", "stream-json")
    assert "--max-turns" not in command
    assert command[
        command.index("--max-budget-usd") : command.index("--max-budget-usd") + 2
    ] == ("--max-budget-usd", "1.8")
    assert "--resume" not in command
    assert "--continue" not in command


def test_claude_backend_separates_thread_and_action_budgets(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    backend = ClaudeInvocationBackend(
        executable="/opt/bin/claude",
        environ={},
        max_budget_usd=10.0,
        max_invocation_budget_usd=2.0,
    )

    command = backend.build_command(_request(tmp_path))

    assert command[
        command.index("--max-budget-usd") : command.index("--max-budget-usd") + 2
    ] == ("--max-budget-usd", "2.0")


def test_claude_probe_fails_closed_inside_claude_code(tmp_path: Path) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    executable = tmp_path / "claude"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    backend = ClaudeInvocationBackend(
        executable=str(executable),
        environ={"CLAUDECODE": "1"},
    )

    probe = backend.probe()
    assert probe.supported is False
    assert probe.reason_code == "HOST_NESTED_INVOCATION_UNAVAILABLE"
    assert backend.child_environment()["CLAUDECODE"] == "1"


def test_claude_probe_fails_closed_when_required_flags_are_missing(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    executable = tmp_path / "claude"
    executable.write_text(
        "#!/bin/sh\necho --print --no-session-persistence --max-budget-usd\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    probe = ClaudeInvocationBackend(
        executable=str(executable), environ={},
    ).probe()

    assert probe.supported is False
    assert probe.reason_code == "HOST_CLAUDE_CAPABILITY_MISSING"


def test_codex_execute_builds_receipt_from_cli_events_not_model_claim(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    request = _request(tmp_path)
    result_path = tmp_path / request.work_files["coordinator_result"]
    result_path.parent.mkdir(parents=True)
    result_path.write_text('{"summary":"done"}', encoding="utf-8")
    output = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "context-codex-1"}),
        json.dumps({
            "type": "turn.completed",
            "usage": {
                "input_tokens": 31,
                "cached_input_tokens": 17,
                "output_tokens": 5,
            },
        }),
    ])
    calls: list[dict[str, object]] = []

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    receipt = CodexInvocationBackend(
        executable="/opt/bin/codex",
        runner=run,
    ).execute(request)

    assert receipt.host_context_id == "context-codex-1"
    assert receipt.usage["cached_input_tokens"] == 17
    assert receipt.work_file_digests["coordinator_result"]
    assert "host_context_id" not in str(calls[0]["input"])
    assert "transcript" not in str(calls[0]["input"]).lower()


@pytest.mark.parametrize("backend_name", ["codex", "claude"])
def test_host_backend_converts_launcher_oserror_to_stable_failure_receipt(
    tmp_path: Path,
    backend_name: str,
) -> None:
    if backend_name == "codex":
        from auto_engineering.host.backends.codex import CodexInvocationBackend

        backend = CodexInvocationBackend(
            executable="/opt/bin/codex",
            runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("executable disappeared")
            ),
        )
    else:
        from auto_engineering.host.backends.claude import ClaudeInvocationBackend

        backend = ClaudeInvocationBackend(
            executable="/opt/bin/claude",
            environ={},
            runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("executable disappeared")
            ),
        )

    receipt = backend.execute(_request(tmp_path))

    assert receipt.status == "failed"
    assert receipt.error_code == (
        "HOST_CODEX_EXECUTION_FAILED"
        if backend_name == "codex"
        else "HOST_CLAUDE_EXECUTION_FAILED"
    )
    assert receipt.exit_code is None
    assert backend.active_context_id is None


def test_codex_backend_normalizes_stringified_business_array_before_receipt(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    request = _request(tmp_path)
    envelope = tmp_path / request.compact_envelope_ref
    envelope.parent.mkdir(parents=True)
    envelope.write_text(json.dumps({
        "stage": "critic",
        "expected_format": {"verdict": "APPROVE | MAJOR", "findings": "array"},
        "result_contract": {
            "schema_version": "1.0",
            "required": ["verdict", "findings"],
            "properties": {
                "verdict": {"type": "string"},
                "findings": {"type": "array"},
            },
            "additionalProperties": False,
        },
    }), encoding="utf-8")
    coordinator = tmp_path / request.work_files["coordinator_result"]
    coordinator.parent.mkdir(parents=True, exist_ok=True)
    coordinator.write_text(json.dumps({
        "verdict": "MAJOR",
        "findings": '[{"severity":"P1","issue":"bug"}]',
    }), encoding="utf-8")

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    receipt = CodexInvocationBackend(
        executable="/opt/bin/codex",
        runner=run,
    ).execute(request)

    assert receipt.status == "completed"
    assert json.loads(coordinator.read_text())["findings"] == [
        {"severity": "P1", "issue": "bug"},
    ]


def test_codex_backend_defers_invalid_business_output_to_result_repair(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    request = _request(tmp_path)
    envelope = tmp_path / request.compact_envelope_ref
    envelope.parent.mkdir(parents=True)
    envelope.write_text(json.dumps({
        "stage": "critic",
        "expected_format": {"verdict": "APPROVE | MAJOR", "findings": "array"},
        "result_contract": {
            "schema_version": "1.0",
            "required": ["verdict", "findings"],
            "properties": {
                "verdict": {"type": "string"},
                "findings": {"type": "array"},
            },
            "additionalProperties": False,
        },
    }), encoding="utf-8")
    coordinator = tmp_path / request.work_files["coordinator_result"]
    coordinator.parent.mkdir(parents=True, exist_ok=True)
    coordinator.write_text(
        '{"verdict":"MAJOR","findings":"not-json"}',
        encoding="utf-8",
    )

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    receipt = CodexInvocationBackend(
        executable="/opt/bin/codex",
        runner=run,
    ).execute(request)

    assert receipt.status == "completed"
    assert receipt.error_code is None


def test_claude_backend_defers_invalid_business_output_to_result_repair(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    request = _request(tmp_path)
    envelope = tmp_path / request.compact_envelope_ref
    envelope.parent.mkdir(parents=True)
    envelope.write_text(json.dumps({
        "stage": "critic",
        "result_contract": {
            "schema_version": "1.0",
            "required": ["verdict", "findings"],
            "properties": {
                "verdict": {"type": "string"},
                "findings": {"type": "array"},
            },
            "additionalProperties": False,
        },
    }), encoding="utf-8")
    coordinator = tmp_path / request.work_files["coordinator_result"]
    coordinator.parent.mkdir(parents=True, exist_ok=True)
    coordinator.write_text(
        '{"verdict":"MAJOR","findings":"not-json"}',
        encoding="utf-8",
    )
    output = json.dumps({
        "type": "result",
        "session_id": "context-claude-repair",
        "is_error": False,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    })

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    receipt = ClaudeInvocationBackend(
        executable="/opt/bin/claude",
        environ={},
        runner=run,
    ).execute(request)

    assert receipt.status == "completed"
    assert receipt.error_code is None


def test_claude_execute_preserves_cli_usage_and_session_identity(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    request = _request(tmp_path)
    coordinator = tmp_path / request.work_files["coordinator_result"]
    coordinator.parent.mkdir(parents=True)
    coordinator.write_text('{"summary":"done"}', encoding="utf-8")
    output = "\n".join([
        json.dumps({"type": "system", "subtype": "init", "session_id": "context-claude-1"}),
        json.dumps({
            "type": "result",
            "session_id": "context-claude-1",
            "is_error": False,
            "total_cost_usd": 0.42,
            "usage": {
                "input_tokens": 41,
                "cache_read_input_tokens": 23,
                "output_tokens": 7,
            },
        }),
    ])

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    receipt = ClaudeInvocationBackend(
        executable="/opt/bin/claude",
        environ={},
        runner=run,
    ).execute(request)

    assert receipt.host_context_id == "context-claude-1"
    assert receipt.usage == {
        "input_tokens": 41,
        "cached_input_tokens": 23,
        "output_tokens": 7,
        "cost_usd": 0.42,
    }


def test_claude_backend_decrements_total_budget_across_actions(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    commands: list[tuple[str, ...]] = []
    invocation = 0

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal invocation
        invocation += 1
        commands.append(command)
        request = _request(tmp_path)
        output_path = tmp_path / request.work_files["coordinator_result"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('{"summary":"done"}', encoding="utf-8")
        output = json.dumps({
            "type": "result", "session_id": f"context-{invocation}",
            "is_error": False, "total_cost_usd": 0.75,
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 5,
                      "output_tokens": 2},
        })
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    backend = ClaudeInvocationBackend(
        executable="/opt/bin/claude", environ={}, max_budget_usd=2.0, runner=run,
    )
    backend.execute(_request(tmp_path))
    backend.execute(_request(tmp_path))

    first = commands[0][commands[0].index("--max-budget-usd") + 1]
    second = commands[1][commands[1].index("--max-budget-usd") + 1]
    assert float(first) == pytest.approx(1.8)
    assert float(second) == pytest.approx(1.05)
    assert backend.remaining_budget_usd == pytest.approx(0.5)


def test_claude_backend_does_not_invoke_after_persisted_budget_is_exhausted(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("budget exhausted must not invoke Claude")

    receipt = ClaudeInvocationBackend(
        executable="/opt/bin/claude", environ={}, max_budget_usd=2.0,
        spent_budget_usd=2.0, runner=run,
    ).execute(_request(tmp_path))

    assert receipt.status == "failed"
    assert receipt.error_code == "HOST_CLAUDE_BUDGET_EXHAUSTED"


def test_claude_backend_reserves_one_inference_unit_before_invocation(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("safety reserve must prevent invocation")

    receipt = ClaudeInvocationBackend(
        executable="/opt/bin/claude", environ={}, max_budget_usd=2.0,
        spent_budget_usd=1.85, budget_reserve_usd=0.2, runner=run,
    ).execute(_request(tmp_path))

    assert receipt.error_code == "HOST_CLAUDE_BUDGET_EXHAUSTED"


def test_claude_failed_result_uses_model_usage_not_zero_summary(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    output = json.dumps({
        "type": "result", "is_error": True,
        "subtype": "error_max_budget_usd", "total_cost_usd": 0.177335,
        "usage": {"input_tokens": 0, "cache_read_input_tokens": 0,
                  "output_tokens": 0},
        "modelUsage": {
            "deepseek-v4-flash": {
                "inputTokens": 33782, "cacheReadInputTokens": 5,
                "outputTokens": 337, "costUSD": 0.177335,
            }
        },
    })

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout=output, stderr="")

    receipt = ClaudeInvocationBackend(
        executable="/opt/bin/claude", environ={}, runner=run,
    ).execute(_request(tmp_path))

    assert receipt.usage["input_tokens"] == 33782
    assert receipt.usage["cached_input_tokens"] == 5
    assert receipt.usage["output_tokens"] == 337


def test_backend_nonzero_exit_returns_failed_receipt_without_advancing(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    request = _request(tmp_path)

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 9, stdout="", stderr="failed")

    receipt = CodexInvocationBackend(
        executable="/opt/bin/codex",
        runner=run,
    ).execute(request)
    assert receipt.status == "failed"
    assert receipt.exit_code == 9
    assert receipt.error_code == "HOST_CODEX_EXECUTION_FAILED"
    diagnostics = list(
        (tmp_path / ".ae-state/host-runtime/diagnostics").glob("*.json")
    )
    assert len(diagnostics) == 1
    diagnostic = json.loads(diagnostics[0].read_text(encoding="utf-8"))
    assert diagnostic["exit_code"] == 9
    assert diagnostic["stderr_tail"] == "failed"
    assert "AUTO_ENGINEERING_ACTION_CONTEXT_V1" not in diagnostics[0].read_text(
        encoding="utf-8"
    )


def test_codex_usage_limit_is_classified_as_resource_exhaustion(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    request = _request(tmp_path)

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="You've hit your usage limit. Try again later.",
            stderr="",
        )

    receipt = CodexInvocationBackend(
        executable="/opt/bin/codex",
        runner=run,
    ).execute(request)

    assert receipt.status == "failed"
    assert receipt.error_code == "HOST_CODEX_USAGE_LIMIT"


def test_claude_budget_limit_is_classified_as_resource_exhaustion(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    request = _request(tmp_path)
    output = json.dumps({
        "type": "result",
        "is_error": True,
        "subtype": "error_max_budget_usd",
        "result": "Maximum budget reached",
    })

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout=output, stderr="")

    receipt = ClaudeInvocationBackend(
        executable="/opt/bin/claude",
        environ={},
        runner=run,
    ).execute(request)

    assert receipt.status == "failed"
    assert receipt.error_code == "HOST_CLAUDE_BUDGET_EXHAUSTED"


def test_claude_invalid_launch_configuration_has_stable_error_code(
    tmp_path: Path,
) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 1, stdout="",
            stderr="Error: Invalid MCP configuration: expected record",
        )

    receipt = ClaudeInvocationBackend(
        executable="/opt/bin/claude", environ={}, runner=run,
    ).execute(_request(tmp_path))

    assert receipt.error_code == "HOST_CLAUDE_LAUNCH_CONFIG_INVALID"


def test_backend_timeout_returns_bounded_receipt(tmp_path: Path) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    request = _request(tmp_path)

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout=3)

    receipt = CodexInvocationBackend(
        executable="/opt/bin/codex",
        runner=run,
        timeout_seconds=3,
    ).execute(request)
    assert receipt.status == "timed_out"
    assert receipt.exit_code is None
    assert receipt.error_code == "HOST_CODEX_EXECUTION_TIMEOUT"


def test_claude_timeout_returns_bounded_receipt(tmp_path: Path) -> None:
    from auto_engineering.host.backends.claude import ClaudeInvocationBackend

    request = _request(tmp_path)

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout=4)

    receipt = ClaudeInvocationBackend(
        executable="/opt/bin/claude",
        environ={},
        runner=run,
        timeout_seconds=4,
    ).execute(request)
    assert receipt.status == "timed_out"
    assert receipt.exit_code is None
    assert receipt.error_code == "HOST_CLAUDE_EXECUTION_TIMEOUT"


def test_zero_exit_without_coordinator_output_is_not_completed(tmp_path: Path) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend

    request = _request(tmp_path)
    output = json.dumps({"type": "thread.started", "thread_id": "context-1"})

    def run(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    receipt = CodexInvocationBackend(
        executable="/opt/bin/codex",
        runner=run,
    ).execute(request)
    assert receipt.status == "failed"
    assert receipt.error_code == "HOST_ACTION_OUTPUT_MISSING"


def test_backend_cancels_only_the_matching_active_invocation(tmp_path: Path) -> None:
    from auto_engineering.host.backends.codex import CodexInvocationBackend
    from auto_engineering.host.invocation import ActionExecutionContractError

    request = _request(tmp_path)

    class BlockingRunner:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.released = threading.Event()
            self.cancelled = False

        def __call__(self, command, **kwargs):
            self.started.set()
            assert self.released.wait(timeout=2)
            return subprocess.CompletedProcess(command, -15, stdout="", stderr="")

        def cancel(self) -> None:
            self.cancelled = True
            self.released.set()

    runner = BlockingRunner()
    backend = CodexInvocationBackend(executable="/opt/bin/codex", runner=runner)
    receipts: list[object] = []
    thread = threading.Thread(target=lambda: receipts.append(backend.execute(request)))
    thread.start()
    assert runner.started.wait(timeout=1)
    active_id = backend.active_context_id
    assert active_id is not None
    with pytest.raises(ActionExecutionContractError, match="HOST_INVOCATION_NOT_ACTIVE"):
        backend.cancel("stale-context")
    backend.cancel(active_id)
    thread.join(timeout=2)
    assert runner.cancelled is True
    assert thread.is_alive() is False


def test_cancellable_runner_emits_bounded_progress_heartbeat() -> None:
    from auto_engineering.host.backends.common import CancellableProcessRunner

    heartbeats: list[float] = []
    result = CancellableProcessRunner(
        progress_callback=heartbeats.append,
        heartbeat_seconds=0.01,
    )(
        (sys.executable, "-c", "import time; time.sleep(0.06)"),
        text=True,
        capture_output=True,
        timeout=1,
        check=False,
    )

    assert result.returncode == 0
    assert len(heartbeats) >= 2
    assert heartbeats == sorted(heartbeats)


def test_cancellable_runner_reports_context_start_before_waiting() -> None:
    """宿主等待模型时，前台必须先收到 context 已启动的事实。"""
    from auto_engineering.host.backends.common import CancellableProcessRunner

    heartbeats: list[float] = []
    result = CancellableProcessRunner(
        progress_callback=heartbeats.append,
        heartbeat_seconds=1.0,
    )(
        (sys.executable, "-c", "print('ready')"),
        text=True,
        capture_output=True,
        timeout=1,
        check=False,
    )

    assert result.returncode == 0
    assert heartbeats and heartbeats[0] == 0.0
