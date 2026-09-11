"""在原生 Worker 工具调用前验证当前 Action 的宿主合同（含 BINDING_DESIGN_READ_ONLY）。"""

from __future__ import annotations

import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path

from auto_engineering.host import HostPlatform
from auto_engineering.host import native_launch_contract_policy as _contract_policy
from auto_engineering.host.native_launch_contract_policy import (
    _ASSEMBLER_OWNED_WORK_FILE,
    _MUTATING_COMMANDS,
    _MUTATING_FILE_TOOLS,
    _REDIRECTION_TOKENS,
    _SHARED_STATE,
    _SPAWN_TOOLS,
    _WAIT_TOOLS,
    _WORKER_OUTCOME,
)
from auto_engineering.host.native_launch_contract_policy import (
    is_binding_design_mutation as _is_binding_design_mutation,
)
from auto_engineering.host.native_launch_contract_policy import (
    validate_assembler_work_file_mutation as _validate_assembler_work_file_mutation,
)
from auto_engineering.host.native_launch_contract_policy import (
    validate_binding_design_mutation as _validate_binding_design_mutation,
)
from auto_engineering.host.native_launch_contract_policy import (
    validate_finalize_command as _validate_finalize_command,
)
from auto_engineering.host.native_launch_contract_policy import (
    validate_record_command as _validate_record_command,
)
from auto_engineering.host.native_launch_contract_policy import (
    validate_spawn_prompt as _validate_spawn_prompt,
)
from auto_engineering.host.native_launch_contract_policy import (
    validate_worker_prompt_read as _validate_worker_prompt_read,
)
from auto_engineering.host.native_launch_messages import (
    NativeLaunchGuardError,
    guard_system_message,
)
from auto_engineering.host.native_launch_runtime import (
    active_native_workers,
)
from auto_engineering.host.native_launch_runtime import (
    spawn_action_requires_lease as _spawn_action_requires_lease,
)

_claude_launch_contract_matches = _contract_policy.claude_launch_contract_matches
_json_contract = _contract_policy._json_contract
_option = _contract_policy.option
_tool_path = _contract_policy.tool_path


def _worker_id(worker: Mapping[str, object]) -> str | None:
    value = worker.get("worker_id")
    return value if isinstance(value, str) and value else None


def _validate_state_mutation(
    *,
    tool_name: str,
    tool_input: Mapping[str, object],
    workers: Sequence[Mapping[str, object]],
    project_root: Path,
    worker_context: bool,
) -> None:
    if tool_name in _MUTATING_FILE_TOOLS:
        values = [value for value in tool_input.values() if isinstance(value, str)]
        _validate_worker_outcome_mutation(
            values=values,
            workers=workers,
            project_root=project_root,
            worker_context=worker_context,
        )
        if any(
            _SHARED_STATE.search(value) or _ASSEMBLER_OWNED_WORK_FILE.search(value)
            for value in values
        ):
            raise NativeLaunchGuardError("AE_STATE_MUTATION_FORBIDDEN")
    if tool_name in {"Bash", "shell", "command_execution"}:
        command = tool_input.get("command")
        if isinstance(command, str) and ".ae-state" in command:
            try:
                tokens = shlex.shlex(command, posix=True, punctuation_chars="><|;&")
                tokens.whitespace_split = True
                shell_tokens = list(tokens)
            except ValueError:
                raise NativeLaunchGuardError("AE_STATE_MUTATION_UNPARSEABLE") from None
            redirected_targets = [
                shell_tokens[index + 1]
                for index, token in enumerate(shell_tokens[:-1])
                if token in _REDIRECTION_TOKENS
            ]
            mutation = any(
                _SHARED_STATE.search(target)
                or _ASSEMBLER_OWNED_WORK_FILE.search(target)
                or _WORKER_OUTCOME.search(target)
                for target in redirected_targets
            )
            mutation = mutation or any(
                Path(token).name in _MUTATING_COMMANDS for token in shell_tokens
            )
            command_text = " ".join(shell_tokens)
            _validate_worker_outcome_mutation(
                values=shell_tokens,
                workers=workers,
                project_root=project_root,
                worker_context=worker_context,
            )
            if mutation and (
                _SHARED_STATE.search(command_text)
                or _ASSEMBLER_OWNED_WORK_FILE.search(command_text)
            ):
                raise NativeLaunchGuardError("AE_STATE_MUTATION_FORBIDDEN")


def _validate_worker_outcome_mutation(
    *,
    values: Sequence[str],
    workers: Sequence[Mapping[str, object]],
    project_root: Path,
    worker_context: bool,
) -> None:
    """把私有 outcome 写入限制到当前 Action 的 Worker 上下文和路径。"""

    references = [value for value in values if _WORKER_OUTCOME.search(value)]
    if not references:
        return
    if not worker_context:
        raise NativeLaunchGuardError("NATIVE_WORKER_OUTCOME_MUTATION_FORBIDDEN")

    root = project_root.resolve()
    allowed: set[Path] = set()
    for worker in workers:
        outcome_path = worker.get("outcome_path")
        if not isinstance(outcome_path, str) or not outcome_path:
            continue
        candidate = Path(outcome_path)
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if root in resolved.parents:
            allowed.add(resolved)
    if not allowed:
        raise NativeLaunchGuardError("NATIVE_WORKER_OUTCOME_PATH_MISMATCH")
    for reference in references:
        candidate = Path(reference)
        resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if resolved not in allowed:
            raise NativeLaunchGuardError("NATIVE_WORKER_OUTCOME_PATH_MISMATCH")


def validate_native_tool_call(
    *,
    platform: str,
    tool_name: str,
    tool_input: Mapping[str, object],
    workers: Sequence[Mapping[str, object]],
    project_root: Path,
    worker_context: bool = False,
) -> None:
    """验证一次原生 spawn 或宿主回写工具调用。"""

    _validate_binding_design_mutation(
        tool_name=tool_name,
        tool_input=tool_input,
        project_root=project_root,
    )
    _validate_assembler_work_file_mutation(
        tool_name=tool_name,
        tool_input=tool_input,
    )
    if platform == HostPlatform.CLAUDE_CODE.value and tool_name == "TaskStop":
        raise NativeLaunchGuardError("NATIVE_WORKER_STOP_FORBIDDEN")
    if tool_name == "Read":
        _validate_worker_prompt_read(
            tool_input=tool_input,
            workers=workers,
            project_root=project_root,
            worker_context=worker_context,
        )
    if tool_name in _SPAWN_TOOLS.get(platform, set()):
        _validate_spawn_prompt(
            platform=platform,
            tool_input=tool_input,
            workers=workers,
        )
        return
    if tool_name in _WAIT_TOOLS.get(platform, set()):
        _validate_wait_timeout(tool_input=tool_input, workers=workers)
        return
    _validate_state_mutation(
        tool_name=tool_name,
        tool_input=tool_input,
        workers=workers,
        project_root=project_root,
        worker_context=worker_context,
    )
    if tool_name in {"Bash", "shell", "command_execution"}:
        command = tool_input.get("command")
        if isinstance(command, str):
            _validate_record_command(
                command=command,
                workers=workers,
                project_root=project_root,
            )
            _validate_finalize_command(
                command=command,
                workers=workers,
                project_root=project_root,
            )


def _validate_wait_timeout(
    *,
    tool_input: Mapping[str, object],
    workers: Sequence[Mapping[str, object]],
) -> None:
    """强制 Codex wait 消费 Action 的机器等待预算。"""

    expected: set[int] = set()
    for worker in workers:
        observation = worker.get("worker_observation")
        if isinstance(observation, Mapping):
            timeout = observation.get("wait_timeout_ms")
            if isinstance(timeout, int) and not isinstance(timeout, bool):
                expected.add(timeout)
    if len(expected) != 1:
        raise NativeLaunchGuardError("NATIVE_WAIT_CONTRACT_MISSING")
    supplied = tool_input.get("timeout_ms")
    if supplied != next(iter(expected)):
        raise NativeLaunchGuardError("NATIVE_WAIT_TIMEOUT_MISMATCH")


def guard_active_native_tool_call(
    payload: Mapping[str, object],
    *,
    project_root: Path,
    platform: HostPlatform,
) -> None:
    """对 Hook wire event 执行当前 Action 的原生工具闸门。"""

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, Mapping):
        return
    relevant = tool_name in _SPAWN_TOOLS.get(platform.value, set())
    relevant = relevant or tool_name in _WAIT_TOOLS.get(platform.value, set())
    relevant = relevant or tool_name == "Read"
    relevant = relevant or (
        platform is HostPlatform.CLAUDE_CODE and tool_name == "TaskStop"
    )
    command = tool_input.get("command")
    worker_context = any(
        isinstance(payload.get(field), str) and bool(payload.get(field))
        for field in ("agent_id", "agentId")
    )
    relevant = relevant or (
        tool_name in {"Bash", "shell", "command_execution"}
        and isinstance(command, str)
        and "--record-worker-outcome" in command
    )
    relevant = relevant or (
        tool_name in {"Bash", "shell", "command_execution"}
        and isinstance(command, str)
        and _SHARED_STATE.search(command) is not None
    )
    if tool_name in _MUTATING_FILE_TOOLS:
        relevant = relevant or _is_binding_design_mutation(
            tool_name=tool_name,
            tool_input=tool_input,
            project_root=project_root,
        )
        relevant = relevant or any(
            isinstance(value, str)
            and (
                _SHARED_STATE.search(value) is not None
                or _ASSEMBLER_OWNED_WORK_FILE.search(value) is not None
                or _WORKER_OUTCOME.search(value) is not None
            )
            for value in tool_input.values()
        )
    if tool_name in {"Bash", "shell", "command_execution"}:
        relevant = relevant or (
            isinstance(command, str)
            and _WORKER_OUTCOME.search(command) is not None
        )
    if not relevant:
        return
    workers = active_native_workers(project_root=project_root, platform=platform)
    if workers is None:
        # Lease 丢失不等于协议状态重新归宿主自由写入。Stop/SessionEnd
        # 清理 lease 后，旧 Coordinator 仍可能持有同一会话并尝试改写
        # native-result、outcome 或共享状态；这些调用必须先停住，交给
        # 显式 recovery 重新取得当前 Action，不能因为模板暂时不可见
        # 就放行第二条证据路径。普通项目工具、普通 Agent 和 Read 仍不受影响。
        protocol_mutation = False
        if tool_name in _MUTATING_FILE_TOOLS:
            values = [value for value in tool_input.values() if isinstance(value, str)]
            protocol_mutation = any(
                _SHARED_STATE.search(value)
                or _ASSEMBLER_OWNED_WORK_FILE.search(value)
                or _WORKER_OUTCOME.search(value)
                for value in values
            )
        elif tool_name in {"Bash", "shell", "command_execution"}:
            command = tool_input.get("command")
            protocol_mutation = isinstance(command, str) and (
                "--record-worker-outcome" in command
                or _SHARED_STATE.search(command) is not None
                or _ASSEMBLER_OWNED_WORK_FILE.search(command) is not None
                or _WORKER_OUTCOME.search(command) is not None
            )
        if protocol_mutation or (
            tool_name in _SPAWN_TOOLS.get(platform.value, set())
            and _spawn_action_requires_lease(project_root=project_root)
        ):
            raise NativeLaunchGuardError("NATIVE_ACTIVE_ACTION_UNAVAILABLE")
        return
    _validate_binding_design_mutation(
        tool_name=tool_name,
        tool_input=tool_input,
        project_root=project_root,
    )
    _validate_assembler_work_file_mutation(
        tool_name=tool_name,
        tool_input=tool_input,
    )
    if not workers:
        if tool_name == "Read":
            return
        raise NativeLaunchGuardError("NATIVE_WORKER_TEMPLATE_UNAVAILABLE")
    validate_native_tool_call(
        platform=platform.value,
        tool_name=tool_name,
        tool_input=tool_input,
        workers=workers,
        project_root=project_root,
        worker_context=worker_context,
    )


def main() -> int:
    """供 Claude PreToolUse 脚本调用的 JSON stdin 入口。"""

    from auto_engineering.host.native_launch_cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = [
    "NativeLaunchGuardError",
    "active_native_workers",
    "guard_active_native_tool_call",
    "guard_system_message",
    "validate_native_tool_call",
]
