"""原生 Worker 工具调用必须消费当前 Action 的机器合同。"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _worker_template() -> dict[str, object]:
    return {
        "worker_id": "developer-0",
        "native_launch_prompt": (
            "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\n"
            "VERBATIM=1;NO_EXTRA\n"
            "outcome_path: object {worker_id,status,payload,summary}\n"
            '{"prompt_sha256":"abc"}'
        ),
        "native_result_path": ".ae-state/host-runtime/native-results/action-developer-0-g1.json",
        "prompt_ref": ".ae-state/effects/prompt/developer.txt",
        "outcome_path": ".ae-state/host-runtime/worker-outcomes/action-developer-0-g1.json",
        "action_work_files": {
            "outcomes": ".ae-state/host-runtime/work/action/outcomes.json",
            "coordinator_result": ".ae-state/host-runtime/work/action/coordinator-result.json",
            "result": ".ae-state/host-runtime/work/action/result.json",
        },
        "record_worker_outcome": {
            "argv_template": [
                "dev-loop",
                "--record-worker-outcome",
                "--worker-id",
                "developer-0",
                "--native-result-file",
                ".ae-state/host-runtime/native-results/action-developer-0-g1.json",
                "--project-root",
                "/tmp/project",
            ],
        },
    }


def test_native_spawn_must_use_exact_action_bound_prompt() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        guard_system_message,
        validate_native_tool_call,
    )

    assert "不要报告能力缺失" in guard_system_message(
        "NATIVE_LAUNCH_PROMPT_MISMATCH"
    )

    worker = _worker_template()
    validate_native_tool_call(
        platform="codex",
        tool_name="collaboration.spawn_agent",
        tool_input={"prompt": worker["native_launch_prompt"]},
        workers=[worker],
        project_root=Path("/tmp/project"),
    )
    validate_native_tool_call(
        platform="claude-code",
        tool_name="Agent",
        tool_input={"prompt": worker["native_launch_prompt"]},
        workers=[worker],
        project_root=Path("/tmp/project"),
    )
    validate_native_tool_call(
        platform="codex",
        tool_name="Edit",
        tool_input={"file_path": "src/App.tsx"},
        workers=[worker],
        project_root=Path("/tmp/project"),
    )

    with pytest.raises(NativeLaunchGuardError, match="NATIVE_LAUNCH_PROMPT_MISMATCH"):
        validate_native_tool_call(
            platform="codex",
            tool_name="collaboration.spawn_agent",
            tool_input={
                "prompt": str(worker["native_launch_prompt"]).replace(
                    "abc", "def"
                ),
            },
            workers=[worker],
            project_root=Path("/tmp/project"),
        )

    with pytest.raises(NativeLaunchGuardError, match="NATIVE_LAUNCH_PROMPT_MISMATCH"):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Agent",
            tool_input={
                "prompt": f'{worker["native_launch_prompt"]}\n额外的 Worker 指令',
            },
            workers=[worker],
            project_root=Path("/tmp/project"),
        )


def test_codex_wait_must_consume_action_observation_timeout() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    worker = _worker_template()
    worker["worker_observation"] = {
        "mode": "native_wait",
        "wait_timeout_ms": 300_000,
    }
    validate_native_tool_call(
        platform="codex",
        tool_name="collaboration.wait_agent",
        tool_input={"targets": ["agent-1"], "timeout_ms": 300_000},
        workers=[worker],
        project_root=Path("/tmp/project"),
    )

    with pytest.raises(NativeLaunchGuardError, match="NATIVE_WAIT_TIMEOUT_MISMATCH"):
        validate_native_tool_call(
            platform="codex",
            tool_name="collaboration.wait_agent",
            tool_input={"targets": ["agent-1"], "timeout_ms": 30_000},
            workers=[worker],
            project_root=Path("/tmp/project"),
        )


def test_binding_design_is_read_only_for_active_host_mutation(tmp_path: Path) -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    ledger = tmp_path / ".ae-state" / "design-decision-ledger.json"
    ledger.parent.mkdir()
    ledger.write_text(
        json.dumps({"source_ref": "design/binding.md"}), encoding="utf-8"
    )
    binding = tmp_path / "design" / "binding.md"
    binding.parent.mkdir()
    binding.write_text("# Binding", encoding="utf-8")

    with pytest.raises(NativeLaunchGuardError, match="BINDING_DESIGN_READ_ONLY"):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Write",
            tool_input={"file_path": str(binding), "content": "# changed"},
            workers=[],
            project_root=tmp_path,
        )

    validate_native_tool_call(
        platform="claude-code",
        tool_name="Write",
        tool_input={"file_path": str(tmp_path / "README.md"), "content": "ok"},
        workers=[],
        project_root=tmp_path,
    )


def test_binding_design_guard_only_applies_while_host_lease_is_active(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        guard_active_native_tool_call,
    )

    ledger = tmp_path / ".ae-state" / "design-decision-ledger.json"
    ledger.parent.mkdir()
    ledger.write_text(
        json.dumps({"source_ref": "design/binding.md"}), encoding="utf-8"
    )
    binding = tmp_path / "design" / "binding.md"
    binding.parent.mkdir()
    binding.write_text("# Binding", encoding="utf-8")
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(binding), "content": "# changed"},
    }

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [],
    )
    with pytest.raises(NativeLaunchGuardError, match="BINDING_DESIGN_READ_ONLY"):
        guard_active_native_tool_call(
            payload, project_root=tmp_path, platform=HostPlatform.CLAUDE_CODE
        )

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: None,
    )
    guard_active_native_tool_call(
        payload, project_root=tmp_path, platform=HostPlatform.CLAUDE_CODE
    )


def test_coordinator_cannot_write_assembler_owned_result_files() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    with pytest.raises(
        NativeLaunchGuardError, match="NATIVE_ASSEMBLER_WORK_FILE_FORBIDDEN"
    ):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Write",
            tool_input={
                "file_path": ".ae-state/host-runtime/work/action/result.json",
                "content": "{}",
            },
            workers=[],
            project_root=Path("/tmp/project"),
        )

    validate_native_tool_call(
        platform="claude-code",
        tool_name="Write",
        tool_input={
            "file_path": ".ae-state/host-runtime/work/action/coordinator-result.json",
            "content": "{}",
        },
        workers=[],
        project_root=Path("/tmp/project"),
    )

def test_claude_spawn_accepts_bound_machine_contract_with_task_suffix() -> None:
    from auto_engineering.host.native_launch_guard import validate_native_tool_call

    worker = _worker_template()
    prompt = (
        f'{worker["native_launch_prompt"]}\n\n---\n\n'
        "PROJECT ROOT: /tmp/project\nROLE: architect\n"
        "TASK: Produce the batch plan from the bound prompt_ref."
    )

    validate_native_tool_call(
        platform="claude-code",
        tool_name="Agent",
        tool_input={"prompt": prompt},
        workers=[worker],
        project_root=Path("/tmp/project"),
    )


def test_native_prompt_requires_worker_to_read_bound_prompt_artifact() -> None:
    from auto_engineering.host.action_mapper import _native_worker_launch_prompt

    prompt = _native_worker_launch_prompt(
        project_root="/tmp/project",
        worker_id="developer-0",
        prompt_ref=".ae-state/effects/prompt/developer.txt",
        prompt_sha256="a" * 64,
        outcome_path=".ae-state/host-runtime/worker-outcomes/developer.json",
        required_isolation_evidence="fresh_context",
        execution_generation=1,
        fencing_token="b" * 64,
    )

    assert "read prompt_ref exactly" in prompt
    assert "no summary/reconstruction" in prompt
    assert "write exactly one JSON object;" in prompt
    assert "no bare payload" in prompt


def test_coordinator_must_not_read_worker_prompt_artifact() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    with pytest.raises(
        NativeLaunchGuardError,
        match="NATIVE_WORKER_PROMPT_READ_FORBIDDEN",
    ):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Read",
            tool_input={"file_path": _worker_template()["prompt_ref"]},
            workers=[_worker_template()],
            project_root=Path("/tmp/project"),
        )


def test_native_worker_context_may_read_its_bound_prompt_artifact() -> None:
    from auto_engineering.host.native_launch_guard import validate_native_tool_call

    validate_native_tool_call(
        platform="claude-code",
        tool_name="Read",
        tool_input={"file_path": _worker_template()["prompt_ref"]},
        workers=[_worker_template()],
        project_root=Path("/tmp/project"),
        worker_context=True,
    )


def test_claude_spawn_accepts_equivalent_machine_contract_formatting() -> None:
    from auto_engineering.host.native_launch_guard import validate_native_tool_call

    worker = _worker_template()
    compact_prompt = (
        "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\n"
        "VERBATIM=1;NO_EXTRA\n"
        "outcome_path=.ae-state/host-runtime/worker-outcomes/action-developer-0-g1.json;"
        "payload仅业务字段;expected_format业务字段全放payload，禁止同级字段;"
        "status=completed/failed/cancelled/timed_out;"
        "禁宿主字段、共享outcomes、diff/日志/报告、数组/字符串JSON\n"
        '{"prompt_sha256":"abc"}'
    )

    validate_native_tool_call(
        platform="claude-code",
        tool_name="Agent",
        tool_input={"prompt": compact_prompt},
        workers=[worker],
        project_root=Path("/tmp/project"),
    )


def test_claude_spawn_accepts_only_prompt_hash_artifact_suffix() -> None:
    from auto_engineering.host.native_launch_guard import validate_native_tool_call

    worker = _worker_template()
    prompt = str(worker["native_launch_prompt"]).replace(
        '"prompt_sha256":"abc"', '"prompt_sha256":"abc.txt"'
    )

    validate_native_tool_call(
        platform="claude-code",
        tool_name="Agent",
        tool_input={"prompt": prompt},
        workers=[worker],
        project_root=Path("/tmp/project"),
    )


def test_claude_spawn_accepts_known_leading_space_key_alias_only() -> None:
    from auto_engineering.host.native_launch_guard import validate_native_tool_call

    worker = _worker_template()
    worker["native_launch_prompt"] = (
        "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\n"
        "VERBATIM=1;NO_EXTRA\n"
        '{"may_drive_loop":false,"prompt_sha256":"abc"}'
    )
    prompt = str(worker["native_launch_prompt"]).replace(
        '"may_drive_loop"', '" may_drive_loop"'
    )

    validate_native_tool_call(
        platform="claude-code",
        tool_name="Agent",
        tool_input={"prompt": prompt},
        workers=[worker],
        project_root=Path("/tmp/project"),
    )


def test_claude_spawn_rejects_modified_prompt_hash() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    worker = _worker_template()
    prompt = str(worker["native_launch_prompt"]).replace(
        '"prompt_sha256":"abc"', '"prompt_sha256":"def.txt"'
    )

    with pytest.raises(NativeLaunchGuardError, match="NATIVE_LAUNCH_PROMPT_MISMATCH"):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Agent",
            tool_input={"prompt": prompt},
            workers=[worker],
            project_root=Path("/tmp/project"),
        )


def test_native_record_must_use_current_worker_result_path() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    worker = _worker_template()
    valid = (
        "PLUGIN_ROOT=/plugin printf x | $PLUGIN_ROOT/bin/ae-run dev-loop "
        "--record-worker-outcome --worker-id developer-0 "
        "--native-result-file "
        ".ae-state/host-runtime/native-results/action-developer-0-g1.json "
        "--project-root /tmp/project"
    )
    validate_native_tool_call(
        platform="codex",
        tool_name="Bash",
        tool_input={"command": valid},
        workers=[worker],
        project_root=Path("/tmp/project"),
    )

    with pytest.raises(NativeLaunchGuardError, match="NATIVE_RESULT_PATH_MISMATCH"):
        validate_native_tool_call(
            platform="codex",
            tool_name="Bash",
            tool_input={
                "command": valid.replace(
                    "action-developer-0-g1.json", "stale-native.json"
                ),
            },
            workers=[worker],
            project_root=Path("/tmp/project"),
        )


def test_native_record_accepts_root_bound_absolute_result_path() -> None:
    from auto_engineering.host.native_launch_guard import validate_native_tool_call

    worker = _worker_template()
    absolute = (
        "/tmp/project/.ae-state/host-runtime/native-results/"
        "action-developer-0-g1.json"
    )
    validate_native_tool_call(
        platform="codex",
        tool_name="Bash",
        tool_input={
            "command": (
                "ae-run dev-loop --record-worker-outcome --worker-id developer-0 "
                f"--native-result-file {absolute} --project-root /tmp/project"
            )
        },
        workers=[worker],
        project_root=Path("/tmp/project"),
    )


def test_finalizer_must_use_current_action_shared_work_files() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    worker = _worker_template()
    valid = (
        "ae-run dev-loop --finalize-result "
        ".ae-state/host-runtime/work/action/outcomes.json "
        "--coordinator-result .ae-state/host-runtime/work/action/coordinator-result.json "
        "--output-result .ae-state/host-runtime/work/action/result.json "
        "--project-root /tmp/project"
    )
    validate_native_tool_call(
        platform="codex",
        tool_name="Bash",
        tool_input={"command": valid},
        workers=[worker],
        project_root=Path("/tmp/project"),
    )

    with pytest.raises(
        NativeLaunchGuardError,
        match="NATIVE_WORKER_OUTCOME_MUTATION_FORBIDDEN",
    ):
        validate_native_tool_call(
            platform="codex",
            tool_name="Bash",
            tool_input={
                "command": valid.replace(
                    ".ae-state/host-runtime/work/action/outcomes.json",
                    ".ae-state/host-runtime/worker-outcomes/action-developer-0-g1.json",
                )
            },
            workers=[worker],
            project_root=Path("/tmp/project"),
        )
def test_unrelated_tool_call_is_not_interpreted_as_worker_launch() -> None:
    from auto_engineering.host.native_launch_guard import validate_native_tool_call

    validate_native_tool_call(
        platform="claude-code",
        tool_name="Bash",
        tool_input={"command": "npm test"},
        workers=[_worker_template()],
        project_root=Path("/tmp/project"),
    )


def test_diagnostic_stderr_redirection_is_not_state_mutation() -> None:
    from auto_engineering.host.native_launch_guard import validate_native_tool_call

    validate_native_tool_call(
        platform="claude-code",
        tool_name="Bash",
        tool_input={
            "command": (
                "ls -la .ae-state/host-runtime/native-results 2>/dev/null"
            )
        },
        workers=[_worker_template()],
        project_root=Path("/tmp/project"),
    )


def test_active_worker_cannot_edit_loop_state_files() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    with pytest.raises(NativeLaunchGuardError, match="AE_STATE_MUTATION_FORBIDDEN"):
        validate_native_tool_call(
            platform="codex",
            tool_name="apply_patch",
            tool_input={
                "patch": "*** Update File: .ae-state/events.db"
            },
            workers=[_worker_template()],
            project_root=Path("/tmp/project"),
        )


def test_state_reads_and_normal_project_edits_remain_allowed() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    worker = _worker_template()
    validate_native_tool_call(
        platform="codex",
        tool_name="Read",
        tool_input={"file_path": ".ae-state/events.db"},
        workers=[worker],
        project_root=Path("/tmp/project"),
    )
    with pytest.raises(
        NativeLaunchGuardError,
        match="NATIVE_WORKER_OUTCOME_MUTATION_FORBIDDEN",
    ):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Write",
            tool_input={
                "file_path": ".ae-state/host-runtime/worker-outcomes/action-developer-0-g1.json",
                "content": "{}",
            },
            workers=[worker],
            project_root=Path("/tmp/project"),
        )


def test_worker_private_outcome_write_is_not_confused_with_shared_state() -> None:
    from auto_engineering.host.native_launch_guard import validate_native_tool_call

    worker = _worker_template()
    validate_native_tool_call(
        platform="codex",
        tool_name="Bash",
        tool_input={
            "command": (
                "printf '%s' '{}' > "
                ".ae-state/host-runtime/worker-outcomes/action-developer-0-g1.json"
            )
        },
        workers=[worker],
        project_root=Path("/tmp/project"),
        worker_context=True,
    )


def test_worker_context_cannot_write_another_action_outcome() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    with pytest.raises(
        NativeLaunchGuardError,
        match="NATIVE_WORKER_OUTCOME_PATH_MISMATCH",
    ):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Write",
            tool_input={
                "file_path": ".ae-state/host-runtime/worker-outcomes/other-action.json",
                "content": "{}",
            },
            workers=[_worker_template()],
            project_root=Path("/tmp/project"),
            worker_context=True,
        )


def test_coordinator_cannot_forge_worker_outcome_with_shell_redirection() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    with pytest.raises(
        NativeLaunchGuardError,
        match="NATIVE_WORKER_OUTCOME_MUTATION_FORBIDDEN",
    ):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Bash",
            tool_input={
                "command": (
                    "printf '%s' '{}' > "
                    ".ae-state/host-runtime/worker-outcomes/action-developer-0-g1.json"
                )
            },
            workers=[_worker_template()],
            project_root=Path("/tmp/project"),
        )


def test_hook_agent_id_marks_fresh_worker_context(monkeypatch, tmp_path: Path) -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import guard_active_native_tool_call

    worker = _worker_template()
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [worker],
    )
    guard_active_native_tool_call(
        {
            "tool_name": "Read",
            "tool_input": {"file_path": worker["prompt_ref"]},
            "agent_id": "native-agent-1",
        },
        project_root=tmp_path,
        platform=HostPlatform.CLAUDE_CODE,
    )


def test_coordinator_read_is_allowed_when_action_has_no_workers(monkeypatch, tmp_path: Path) -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import guard_active_native_tool_call

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [],
    )
    guard_active_native_tool_call(
        {
            "tool_name": "Read",
            "tool_input": {"file_path": ".ae-state/effects/prompt/coordinator.txt"},
        },
        project_root=tmp_path,
        platform=HostPlatform.CLAUDE_CODE,
    )


def test_unplanned_native_worker_is_rejected_when_action_has_no_workers(
    monkeypatch, tmp_path: Path
) -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        guard_active_native_tool_call,
    )

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: [],
    )
    with pytest.raises(NativeLaunchGuardError, match="NATIVE_WORKER_TEMPLATE_UNAVAILABLE"):
        guard_active_native_tool_call(
            {
                "tool_name": "Agent",
                "tool_input": {"prompt": "unplanned worker"},
            },
            project_root=tmp_path,
            platform=HostPlatform.CLAUDE_CODE,
        )


def test_protocol_state_mutation_is_rejected_after_lease_loss(
    monkeypatch, tmp_path: Path
) -> None:
    """lease 清理后，旧 Coordinator 仍不能伪造 native-result 证据。"""

    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        guard_active_native_tool_call,
    )

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: None,
    )
    guard_active_native_tool_call(
        {
            "tool_name": "Agent",
            "tool_input": {"prompt": "普通项目协助"},
        },
        project_root=tmp_path,
        platform=HostPlatform.CLAUDE_CODE,
    )

    with pytest.raises(NativeLaunchGuardError, match="NATIVE_ACTIVE_ACTION_UNAVAILABLE"):
        guard_active_native_tool_call(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "cat > .ae-state/host-runtime/native-results/current.json"
                    ),
                },
            },
            project_root=tmp_path,
            platform=HostPlatform.CLAUDE_CODE,
        )


def test_unbound_ordinary_agent_remains_allowed_after_lease_loss(
    monkeypatch, tmp_path: Path
) -> None:
    """无 Loop lease 时，普通宿主 Agent 不应被协议守门器接管。"""

    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import guard_active_native_tool_call

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: None,
    )
    guard_active_native_tool_call(
        {
            "tool_name": "Agent",
            "tool_input": {"prompt": "普通项目协助"},
        },
        project_root=tmp_path,
        platform=HostPlatform.CLAUDE_CODE,
    )


def test_spawn_is_rejected_after_lease_loss_while_loop_action_remains_active(
    monkeypatch, tmp_path: Path
) -> None:
    """WAIT_RESOURCE 后必须 resume，不能绕过 lease 直接再起 Worker。"""

    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        guard_active_native_tool_call,
    )

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        lambda **_: None,
    )
    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard._spawn_action_requires_lease",
        lambda **_: True,
    )
    with pytest.raises(NativeLaunchGuardError, match="NATIVE_ACTIVE_ACTION_UNAVAILABLE"):
        guard_active_native_tool_call(
            {
                "tool_name": "Agent",
                "tool_input": {"prompt": "retry developer"},
            },
            project_root=tmp_path,
            platform=HostPlatform.CLAUDE_CODE,
        )


def test_coordinator_can_write_action_scoped_work_and_worker_outcome_files() -> None:
    from auto_engineering.host.native_launch_guard import validate_native_tool_call

    worker = _worker_template()
    validate_native_tool_call(
        platform="claude-code",
        tool_name="Write",
        tool_input={
            "file_path": ".ae-state/host-runtime/work/action/coordinator-result.json",
            "content": "{}",
        },
        workers=[worker],
        project_root=Path("/tmp/project"),
    )


def test_coordinator_cannot_write_assembler_owned_action_outcomes_or_result() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    worker = _worker_template()
    for file_name in ("outcomes.json", "result.json"):
        with pytest.raises(
            NativeLaunchGuardError, match="NATIVE_ASSEMBLER_WORK_FILE_FORBIDDEN"
        ):
            validate_native_tool_call(
                platform="claude-code",
                tool_name="Write",
                tool_input={
                    "file_path": f".ae-state/host-runtime/work/action/{file_name}",
                    "content": "{}",
                },
                workers=[worker],
                project_root=Path("/tmp/project"),
            )


def test_action_scoped_coordinator_tools_do_not_require_worker_templates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import guard_active_native_tool_call

    def unexpected_worker_lookup(**_: object) -> None:
        raise AssertionError("普通 Coordinator 工具不应进入 Worker Guard")

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.active_native_workers",
        unexpected_worker_lookup,
    )
    guard_active_native_tool_call(
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": ".ae-state/host-runtime/work/action/coordinator-result.json",
                "content": "{}",
            },
        },
        project_root=Path("/tmp/project"),
        platform=HostPlatform.CLAUDE_CODE,
    )
    guard_active_native_tool_call(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": "ae-run dev-loop --finalize-result .ae-state/host-runtime/work/result.json"
            },
        },
        project_root=Path("/tmp/project"),
        platform=HostPlatform.CLAUDE_CODE,
    )


def test_protocol_json_with_shell_metacharacters_is_not_misclassified_as_mutation() -> None:
    from auto_engineering.host.native_launch_guard import validate_native_tool_call

    validate_native_tool_call(
        platform="claude-code",
        tool_name="Bash",
        tool_input={
            "command": (
                "ae-run dev-loop --finalize-result "
                "'{\"evidence\":\"Coordinator -> Core\","
                "\"path\":\".ae-state/host-runtime/work/result.json\"}' "
                "--project-root /tmp/project"
            )
        },
        workers=[_worker_template()],
        project_root=Path("/tmp/project"),
    )


def test_shared_state_redirection_is_still_blocked() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    with pytest.raises(NativeLaunchGuardError, match="AE_STATE_MUTATION_FORBIDDEN"):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Bash",
            tool_input={"command": "printf x > .ae-state/events.db"},
            workers=[_worker_template()],
            project_root=Path("/tmp/project"),
        )


def test_claude_task_stop_is_blocked_during_spawn_action() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    with pytest.raises(NativeLaunchGuardError, match="NATIVE_WORKER_STOP_FORBIDDEN"):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="TaskStop",
            tool_input={"task_id": "agent-123"},
            workers=[_worker_template()],
            project_root=Path("/tmp/project"),
        )


def test_guard_helper_parsers_fail_closed_for_missing_values() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        _option,
        _tool_path,
        _worker_id,
        validate_native_tool_call,
    )

    assert _option("ae-run", "--worker-id") is None
    assert _worker_id({"worker_id": ""}) is None
    assert _worker_id({"worker_id": 1}) is None
    assert _tool_path({"file_path": ""}) is None
    assert _tool_path({"content": "payload"}) is None

    with pytest.raises(NativeLaunchGuardError, match="NATIVE_LAUNCH_PROMPT_MISSING"):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Agent",
            tool_input={},
            workers=[_worker_template()],
            project_root=Path("/tmp/project"),
        )


def test_claude_contract_parser_rejects_malformed_or_ambiguous_suffixes() -> None:
    from auto_engineering.host.native_launch_guard import (
        _claude_launch_contract_matches,
        _json_contract,
    )

    worker = _worker_template()
    expected = str(worker["native_launch_prompt"])
    assert _json_contract("plain text") is None
    assert _json_contract("prefix {not-json}") is None
    assert not _claude_launch_contract_matches("wrong-header", expected)
    assert not _claude_launch_contract_matches(
        expected + "\nextra suffix", expected
    )
    assert not _claude_launch_contract_matches(
        expected + "\n\n---\n\n" + expected, expected
    )


def test_record_command_rejects_missing_identity_and_project_mismatch() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    worker = _worker_template()
    base = (
        "ae-run dev-loop --record-worker-outcome --worker-id developer-0 "
        "--native-result-file .ae-state/host-runtime/native-results/action-developer-0-g1.json "
        "--project-root /tmp/project"
    )
    cases = [
        (base.replace("--worker-id developer-0", "--worker-id" ).replace(
            "--native-result-file .ae-state/host-runtime/native-results/action-developer-0-g1.json",
            ""
        ), "NATIVE_RECORD_ARGUMENTS_MISSING"),
        (base.replace("developer-0", "unknown-0", 1), "NATIVE_RECORD_WORKER_MISMATCH"),
        (base.replace("--project-root /tmp/project", "--project-root /tmp/other"), "NATIVE_PROJECT_ROOT_MISMATCH"),
    ]
    for command, code in cases:
        with pytest.raises(NativeLaunchGuardError, match=code):
            validate_native_tool_call(
                platform="codex",
                tool_name="Bash",
                tool_input={"command": command},
                workers=[worker],
                project_root=Path("/tmp/project"),
            )

    broken_worker = dict(worker)
    broken_worker["native_result_path"] = None
    with pytest.raises(NativeLaunchGuardError, match="NATIVE_RESULT_PATH_MISMATCH"):
        validate_native_tool_call(
            platform="codex",
            tool_name="Bash",
            tool_input={"command": base},
            workers=[broken_worker],
            project_root=Path("/tmp/project"),
        )


def test_record_command_requires_literal_paths_before_shell_expansion() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        guard_system_message,
        validate_native_tool_call,
    )

    worker = _worker_template()
    base = (
        "ae-run dev-loop --record-worker-outcome --worker-id developer-0 "
        "--native-result-file .ae-state/host-runtime/native-results/action-developer-0-g1.json "
        "--project-root /tmp/project"
    )
    with pytest.raises(NativeLaunchGuardError, match="NATIVE_RESULT_PATH_MISMATCH"):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Bash",
            tool_input={"command": base.replace(
                ".ae-state/host-runtime/native-results/action-developer-0-g1.json",
                "$NATIVE_RESULT_FILE",
            )},
            workers=[worker],
            project_root=Path("/tmp/project"),
        )
    with pytest.raises(NativeLaunchGuardError, match="NATIVE_PROJECT_ROOT_MISMATCH"):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Bash",
            tool_input={"command": base.replace(
                "/tmp/project", "$AE_INVOCATION_PROJECT_ROOT"
            )},
            workers=[worker],
            project_root=Path("/tmp/project"),
        )
    assert "字面量" in guard_system_message("NATIVE_PROJECT_ROOT_MISMATCH")
    assert "$VAR" in guard_system_message("NATIVE_RECORD_ARGUMENTS_MISSING")
    assert "不得复用上一 Action" in guard_system_message(
        "NATIVE_WORKER_TEMPLATE_UNAVAILABLE"
    )


def test_finalize_command_rejects_missing_or_wrong_action_work_files() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    worker = _worker_template()
    valid = (
        "ae-run dev-loop --finalize-result .ae-state/host-runtime/work/action/outcomes.json "
        "--coordinator-result .ae-state/host-runtime/work/action/coordinator-result.json "
        "--output-result .ae-state/host-runtime/work/action/result.json"
    )
    missing = valid.replace(
        " --output-result .ae-state/host-runtime/work/action/result.json", ""
    )
    with pytest.raises(NativeLaunchGuardError, match="NATIVE_FINALIZE_PATH_MISSING"):
        validate_native_tool_call(
            platform="codex", tool_name="Bash", tool_input={"command": missing},
            workers=[worker], project_root=Path("/tmp/project")
        )
    with pytest.raises(NativeLaunchGuardError, match="NATIVE_FINALIZE_PATH_MISMATCH"):
        validate_native_tool_call(
            platform="codex", tool_name="Bash",
            tool_input={"command": valid.replace("result.json", "wrong.json")},
            workers=[worker], project_root=Path("/tmp/project")
        )

    no_files = dict(worker)
    no_files.pop("action_work_files")
    validate_native_tool_call(
        platform="codex", tool_name="Bash", tool_input={"command": valid},
        workers=[no_files], project_root=Path("/tmp/project")
    )


def test_state_mutation_parser_reports_unparseable_shell() -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        validate_native_tool_call,
    )

    with pytest.raises(NativeLaunchGuardError, match="AE_STATE_MUTATION_UNPARSEABLE"):
        validate_native_tool_call(
            platform="claude-code",
            tool_name="Bash",
            tool_input={"command": "printf 'unterminated .ae-state/events.db"},
            workers=[_worker_template()],
            project_root=Path("/tmp/project"),
        )


def test_active_native_workers_rejects_invalid_lease_and_action_states(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        active_native_workers,
    )
    from auto_engineering.host.runtime_driver import HostRunLeaseError

    class LeaseStore:
        def __init__(self, _root: Path) -> None:
            pass

        def load(self) -> object:
            raise HostRunLeaseError("bad lease")

    monkeypatch.setattr(
        "auto_engineering.host.runtime_driver.HostRunLeaseStore", LeaseStore
    )
    with pytest.raises(NativeLaunchGuardError, match="bad lease"):
        active_native_workers(project_root=tmp_path, platform=HostPlatform.CODEX)

    class EmptyLeaseStore(LeaseStore):
        def load(self) -> object:
            return None

    monkeypatch.setattr(
        "auto_engineering.host.runtime_driver.HostRunLeaseStore", EmptyLeaseStore
    )
    assert active_native_workers(project_root=tmp_path, platform=HostPlatform.CODEX) is None

    class WrongPlatformLeaseStore(LeaseStore):
        def load(self) -> object:
            return SimpleNamespace(disposition="CONTINUE", platform="claude-code")

    monkeypatch.setattr(
        "auto_engineering.host.runtime_driver.HostRunLeaseStore", WrongPlatformLeaseStore
    )
    with pytest.raises(NativeLaunchGuardError, match="NATIVE_HOST_PLATFORM_MISMATCH"):
        active_native_workers(project_root=tmp_path, platform=HostPlatform.CODEX)


def test_active_native_workers_maps_current_action_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        active_native_workers,
    )

    state = tmp_path / ".ae-state"
    state.mkdir()
    (state / "events.db").touch()
    lease = SimpleNamespace(
        disposition="CONTINUE", platform="codex", thread_id="thread-1",
        action_message_id="action-1", execution_generation=2,
    )

    class LeaseStore:
        def __init__(self, _root: Path) -> None:
            pass

        def load(self) -> object:
            return lease

    class Events:
        def __init__(self, _path: Path) -> None:
            pass

        def load_action_snapshot(self, _thread_id: str) -> object:
            return {"message_id": "action-1", "project_root": str(tmp_path)}

        def close(self) -> None:
            pass

    class Adapter:
        capabilities = object()

        def profile(self, **_kwargs: object) -> object:
            return object()

        def map_action(self, action: object, *, profile: object) -> object:
            assert isinstance(action, dict)
            assert action["execution_generation"] == 2
            return SimpleNamespace(payload={"host_execution": {"workers": [{"worker_id": "x"}]}})

    monkeypatch.setattr("auto_engineering.host.runtime_driver.HostRunLeaseStore", LeaseStore)
    monkeypatch.setattr("auto_engineering.loop.event_store.SQLiteEventStore", Events)
    monkeypatch.setattr("auto_engineering.host.adapters.adapter_for", lambda _platform: Adapter())
    assert active_native_workers(project_root=tmp_path, platform=HostPlatform.CODEX) == [{"worker_id": "x"}]

    class NoWorkersAdapter(Adapter):
        def map_action(self, action: object, *, profile: object) -> object:
            return SimpleNamespace(payload={"host_execution": {}})

    monkeypatch.setattr("auto_engineering.host.adapters.adapter_for", lambda _platform: NoWorkersAdapter())
    assert active_native_workers(project_root=tmp_path, platform=HostPlatform.CODEX) == []

    class InvalidWorkersAdapter(Adapter):
        def map_action(self, action: object, *, profile: object) -> object:
            return SimpleNamespace(payload={"host_execution": {"workers": ["bad"]}})

    monkeypatch.setattr("auto_engineering.host.adapters.adapter_for", lambda _platform: InvalidWorkersAdapter())
    with pytest.raises(NativeLaunchGuardError, match="NATIVE_WORKER_TEMPLATE_UNAVAILABLE"):
        active_native_workers(project_root=tmp_path, platform=HostPlatform.CODEX)


def test_spawn_action_requires_lease_uses_event_store_without_checkpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """无 lease 的防重复启动判断不能依赖旧 checkpoint 定位 Action。"""

    from auto_engineering.host.native_launch_runtime import spawn_action_requires_lease

    state = tmp_path / ".ae-state"
    state.mkdir()
    (state / "events.db").touch()

    class Events:
        def __init__(self, _path: Path) -> None:
            pass

        def unfinished_threads(self) -> list[str]:
            return ["event-thread"]

        def load_action_snapshot(self, _thread_id: str) -> object:
            return {
                "project_root": str(tmp_path),
                "host_execution": {"workers": [{"worker_id": "developer-0"}]},
            }

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "auto_engineering.loop.event_store.SQLiteEventStore", Events
    )
    assert spawn_action_requires_lease(tmp_path) is True


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("ambiguous", True),
        ("empty", False),
        ("error", False),
        ("invalid_thread", False),
        ("invalid_action", False),
        ("wrong_root", False),
    ],
)
def test_spawn_action_requires_lease_fails_closed_on_thread_resolution_edges(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: str,
    expected: bool,
) -> None:
    """未终态查询异常或歧义不能放行无 lease 的 Worker。"""
    from auto_engineering.host.native_launch_runtime import spawn_action_requires_lease

    state = tmp_path / ".ae-state"
    state.mkdir()
    (state / "events.db").touch()

    class Events:
        def __init__(self, _path: Path) -> None:
            pass

        def unfinished_threads(self) -> list[str]:
            if mode == "error":
                raise ValueError("broken event store")
            if mode == "ambiguous":
                return ["thread-a", "thread-b"]
            if mode == "empty":
                return []
            if mode == "invalid_thread":
                return [""]
            return ["thread-1"]

        def load_action_snapshot(self, _thread_id: str) -> object:
            if mode == "invalid_action":
                return None
            return {
                "project_root": (
                    str(tmp_path / "other") if mode == "wrong_root" else str(tmp_path)
                ),
                "host_execution": {"workers": [{"worker_id": "developer-0"}]},
            }

        def close(self) -> None:
            pass

    monkeypatch.setattr("auto_engineering.loop.event_store.SQLiteEventStore", Events)
    assert spawn_action_requires_lease(tmp_path) is expected


def test_spawn_action_requires_lease_ignores_checkpoint_only_state(tmp_path: Path) -> None:
    """只有 checkpoint 的旧 Action 不能阻断普通宿主 Agent。"""

    from auto_engineering.host.native_launch_runtime import spawn_action_requires_lease

    state = tmp_path / ".ae-state"
    state.mkdir()
    (state / "checkpoints.db").touch()
    assert spawn_action_requires_lease(tmp_path) is False


def test_native_guard_main_emits_stable_allow_and_block_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from auto_engineering.host.native_launch_guard import (
        NativeLaunchGuardError,
        main,
    )

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"not": "a payload"})))
    assert main() == 0
    assert capsys.readouterr().out == ""

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"platform": "bad", "cwd": str(tmp_path)})))
    with pytest.raises(ValueError):
        main()

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"platform": "codex"})))
    assert main() == 0
    assert capsys.readouterr().out == ""

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.guard_active_native_tool_call",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"platform": "codex", "cwd": str(tmp_path)})))
    assert main() == 0
    allowed = json.loads(capsys.readouterr().out)
    assert allowed == {"systemMessage": "Auto-Engineering Hook 已安全跳过"}

    def blocked(*args: object, **kwargs: object) -> None:
        raise NativeLaunchGuardError("NATIVE_LAUNCH_PROMPT_MISMATCH")

    monkeypatch.setattr(
        "auto_engineering.host.native_launch_guard.guard_active_native_tool_call", blocked
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"platform": "codex", "cwd": str(tmp_path)})))
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert set(output) == {"systemMessage", "hookSpecificOutput"}
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert output["hookSpecificOutput"]["permissionDecisionReason"]
