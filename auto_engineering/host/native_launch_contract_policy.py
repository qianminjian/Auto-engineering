"""原生 Worker 启动、回写和路径合同的纯校验策略。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from auto_engineering.host import HostPlatform
from auto_engineering.host.native_launch_messages import NativeLaunchGuardError

_SPAWN_TOOLS = {
    HostPlatform.CODEX.value: {
        "collaboration.spawn_agent",
        "multi_agent_v1__spawn_agent",
    },
    HostPlatform.CLAUDE_CODE.value: {"Agent"},
}
_WAIT_TOOLS = {
    HostPlatform.CODEX.value: {
        "collaboration.wait_agent",
        "multi_agent_v1__wait_agent",
    },
}
_PROMPT_FIELDS = ("prompt", "message", "instructions")
_MUTATING_FILE_TOOLS = {"Edit", "Write", "MultiEdit", "apply_patch"}
_MUTATING_COMMANDS = {
    "cp",
    "install",
    "mv",
    "rm",
    "rmdir",
    "unlink",
    "shred",
    "tee",
    "sed",
}
_REDIRECTION_TOKENS = {">", ">>"}
_SHARED_STATE = re.compile(
    r"\.ae-state/(?:events\.db|checkpoints\.db|design-decision-ledger\.json|"
    r"host-runtime/(?:native-results(?:/|$)|active-lease\.json(?:$|/)|"
    r"outcomes(?:/|$)|worker-observations(?:/|$))|"
    r"spawn-(?:proofs|challenges))"
)
_ASSEMBLER_OWNED_WORK_FILE = re.compile(
    r"\.ae-state/host-runtime/work/[^/]+/(?:outcomes|result)\.json(?:$|[^\w])"
)
_WORKER_OUTCOME = re.compile(r"\.ae-state/host-runtime/worker-outcomes(?:/|$)")
_BINDING_DESIGN_TOOLS = {"Edit", "Write", "MultiEdit", "apply_patch"}
_LAUNCH_HEADER = "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\nVERBATIM=1;NO_EXTRA\n"


def option(command: str, name: str) -> str | None:
    pattern = re.compile(
        rf"(?:^|\s){re.escape(name)}(?:=|\s+)"
        rf"(?:\"([^\"]*)\"|'([^']*)'|([^\s]+))"
    )
    match = pattern.search(command)
    return None if match is None else next(
        (item for item in match.groups() if item is not None), None
    )


def tool_path(tool_input: Mapping[str, object]) -> str | None:
    for key in ("file_path", "filepath", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def binding_design_path(project_root: Path) -> Path | None:
    ledger_path = project_root.resolve() / ".ae-state" / "design-decision-ledger.json"
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    source_ref = payload.get("source_ref") if isinstance(payload, Mapping) else None
    if not isinstance(source_ref, str) or not source_ref:
        return None
    candidate = Path(source_ref)
    return (candidate if candidate.is_absolute() else project_root / candidate).resolve()


def is_binding_design_mutation(
    *, tool_name: str, tool_input: Mapping[str, object], project_root: Path
) -> bool:
    if tool_name not in _BINDING_DESIGN_TOOLS:
        return False
    supplied = tool_path(tool_input)
    if not supplied:
        return False
    try:
        candidate = Path(supplied)
        supplied_path = (
            candidate if candidate.is_absolute() else project_root / candidate
        ).resolve()
    except (OSError, RuntimeError):
        return False
    binding_path = binding_design_path(project_root)
    return binding_path is not None and supplied_path == binding_path


def validate_binding_design_mutation(
    *, tool_name: str, tool_input: Mapping[str, object], project_root: Path
) -> None:
    if is_binding_design_mutation(
        tool_name=tool_name, tool_input=tool_input, project_root=project_root
    ):
        raise NativeLaunchGuardError("BINDING_DESIGN_READ_ONLY")


def validate_assembler_work_file_mutation(
    *, tool_name: str, tool_input: Mapping[str, object]
) -> None:
    if tool_name not in _MUTATING_FILE_TOOLS:
        return
    values = [value for value in tool_input.values() if isinstance(value, str)]
    if any(_ASSEMBLER_OWNED_WORK_FILE.search(value) for value in values):
        raise NativeLaunchGuardError("NATIVE_ASSEMBLER_WORK_FILE_FORBIDDEN")


def validate_worker_prompt_read(
    *,
    tool_input: Mapping[str, object],
    workers: Sequence[Mapping[str, object]],
    project_root: Path,
    worker_context: bool,
) -> None:
    if worker_context:
        return
    supplied = tool_path(tool_input)
    if not supplied:
        return
    try:
        supplied_path = Path(supplied)
        supplied_resolved = (
            supplied_path if supplied_path.is_absolute() else project_root / supplied_path
        ).resolve()
    except (OSError, RuntimeError):
        return
    if project_root.resolve() not in supplied_resolved.parents:
        return
    for worker in workers:
        prompt_ref = worker.get("prompt_ref")
        if not isinstance(prompt_ref, str) or not prompt_ref:
            continue
        try:
            expected_path = Path(prompt_ref)
            expected_resolved = (
                expected_path if expected_path.is_absolute() else project_root / expected_path
            ).resolve()
        except (OSError, RuntimeError):
            continue
        if supplied_resolved == expected_resolved:
            raise NativeLaunchGuardError("NATIVE_WORKER_PROMPT_READ_FORBIDDEN")


def validate_spawn_prompt(
    *, platform: str, tool_input: Mapping[str, object], workers: Sequence[Mapping[str, object]]
) -> None:
    prompt = next(
        (
            tool_input.get(field)
            for field in _PROMPT_FIELDS
            if isinstance(tool_input.get(field), str)
        ),
        None,
    )
    if not isinstance(prompt, str) or not prompt:
        raise NativeLaunchGuardError("NATIVE_LAUNCH_PROMPT_MISSING")
    expected = {
        candidate
        for worker in workers
        if isinstance(candidate := worker.get("native_launch_prompt"), str)
    }
    if prompt in expected:
        return
    if platform == HostPlatform.CLAUDE_CODE.value and any(
        claude_launch_contract_matches(prompt, candidate) for candidate in expected
    ):
        return
    raise NativeLaunchGuardError("NATIVE_LAUNCH_PROMPT_MISMATCH")


def _json_contract(prompt: str) -> tuple[dict[str, object], int] | None:
    decoder = json.JSONDecoder()
    start = 0
    while True:
        offset = prompt.find("{", start)
        if offset < 0:
            return None
        try:
            value, end = decoder.raw_decode(prompt[offset:])
        except json.JSONDecodeError:
            start = offset + 1
            continue
        if isinstance(value, dict):
            return value, offset + end
        start = offset + 1


def claude_launch_contract_matches(supplied: str, expected: str) -> bool:
    if not supplied.startswith(_LAUNCH_HEADER) or not expected.startswith(_LAUNCH_HEADER):
        return False
    supplied_contract = _json_contract(supplied)
    expected_contract = _json_contract(expected)
    if supplied_contract is None or expected_contract is None:
        return False
    supplied_value, supplied_end = supplied_contract
    expected_value, expected_end = expected_contract
    if supplied_value != expected_value:
        if " may_drive_loop" in supplied_value and "may_drive_loop" not in supplied_value:
            normalized = dict(supplied_value)
            normalized["may_drive_loop"] = normalized.pop(" may_drive_loop")
            if normalized == expected_value:
                supplied_value = normalized
        supplied_hash = supplied_value.get("prompt_sha256")
        expected_hash = expected_value.get("prompt_sha256")
        if supplied_hash == f"{expected_hash}.txt":
            supplied_value = dict(supplied_value)
            supplied_value["prompt_sha256"] = expected_hash
    if supplied_value != expected_value or expected[expected_end:].strip():
        return False
    suffix = supplied[supplied_end:]
    return (
        not suffix.strip()
        or (suffix.startswith("\n\n---\n\n") and _LAUNCH_HEADER not in suffix)
    )


def validate_record_command(
    *, command: str, workers: Sequence[Mapping[str, object]], project_root: Path
) -> None:
    if "--record-worker-outcome" not in command:
        return
    worker_id = option(command, "--worker-id")
    native_result_path = option(command, "--native-result-file")
    supplied_project_root = option(command, "--project-root")
    if not worker_id or not native_result_path or not supplied_project_root:
        raise NativeLaunchGuardError("NATIVE_RECORD_ARGUMENTS_MISSING")
    worker = next((item for item in workers if item.get("worker_id") == worker_id), None)
    if worker is None:
        raise NativeLaunchGuardError("NATIVE_RECORD_WORKER_MISMATCH")
    expected_native_path = worker.get("native_result_path")
    if not isinstance(expected_native_path, str):
        raise NativeLaunchGuardError("NATIVE_RESULT_PATH_MISMATCH")
    try:
        supplied_path = Path(native_result_path)
        expected_path = Path(expected_native_path)
        supplied_resolved = (
            supplied_path if supplied_path.is_absolute() else project_root / supplied_path
        ).resolve()
        expected_resolved = (
            expected_path if expected_path.is_absolute() else project_root / expected_path
        ).resolve()
    except (OSError, RuntimeError):
        raise NativeLaunchGuardError("NATIVE_RESULT_PATH_MISMATCH") from None
    if supplied_resolved != expected_resolved or project_root.resolve() not in supplied_resolved.parents:
        raise NativeLaunchGuardError("NATIVE_RESULT_PATH_MISMATCH")
    try:
        actual_root = Path(supplied_project_root).resolve()
    except (OSError, RuntimeError):
        raise NativeLaunchGuardError("NATIVE_PROJECT_ROOT_INVALID") from None
    if actual_root != project_root.resolve():
        raise NativeLaunchGuardError("NATIVE_PROJECT_ROOT_MISMATCH")


def validate_finalize_command(
    *, command: str, workers: Sequence[Mapping[str, object]], project_root: Path
) -> None:
    if "--finalize-result" not in command:
        return
    if "--coordinator-result" not in command and "--output-result" not in command:
        return
    work_files = next(
        (
            item.get("action_work_files")
            for item in workers
            if isinstance(item.get("action_work_files"), Mapping)
        ),
        None,
    )
    if not isinstance(work_files, Mapping):
        return

    def resolve(value: str) -> Path:
        candidate = Path(value)
        return (candidate if candidate.is_absolute() else project_root / candidate).resolve()

    expected = {
        option_name: work_files.get(key)
        for option_name, key in (
            ("--finalize-result", "outcomes"),
            ("--coordinator-result", "coordinator_result"),
            ("--output-result", "result"),
        )
    }
    for option_name, expected_value in expected.items():
        supplied = option(command, option_name)
        if expected_value is None:
            continue
        if not isinstance(expected_value, str) or not supplied:
            raise NativeLaunchGuardError("NATIVE_FINALIZE_PATH_MISSING")
        try:
            if resolve(supplied) != resolve(expected_value):
                raise NativeLaunchGuardError("NATIVE_FINALIZE_PATH_MISMATCH")
        except (OSError, RuntimeError):
            raise NativeLaunchGuardError("NATIVE_FINALIZE_PATH_MISMATCH") from None


__all__ = [
    "_ASSEMBLER_OWNED_WORK_FILE",
    "_MUTATING_COMMANDS",
    "_MUTATING_FILE_TOOLS",
    "_REDIRECTION_TOKENS",
    "_SHARED_STATE",
    "_SPAWN_TOOLS",
    "_WAIT_TOOLS",
    "_WORKER_OUTCOME",
    "claude_launch_contract_matches",
    "is_binding_design_mutation",
    "validate_assembler_work_file_mutation",
    "validate_binding_design_mutation",
    "validate_finalize_command",
    "validate_record_command",
    "validate_spawn_prompt",
    "validate_worker_prompt_read",
]
