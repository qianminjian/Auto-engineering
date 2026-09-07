"""在原生 Worker 工具调用前验证当前 Action 的宿主合同。"""

from __future__ import annotations

import json
import re
import shlex
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from auto_engineering.host import HostPlatform


class NativeLaunchGuardError(ValueError):
    """原生 Worker 工具调用没有消费当前 Action 的固定字段。"""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def guard_system_message(code: str) -> str:
    """返回宿主能直接执行的拒绝反馈，避免模型沿错误路径继续探查。"""

    messages = {
        "NATIVE_WORKER_PROMPT_READ_FORBIDDEN": (
            "已阻止读取 Worker prompt 正文；Coordinator 必须直接消费当前 Action 的 "
            "action.host_execution.workers[].native_launch_prompt，Worker 才能在 fresh context "
            "内读取 prompt_ref。"
        ),
        "NATIVE_LAUNCH_PROMPT_MISMATCH": (
            "已阻止原生 Worker 启动，但当前 Action 仍可继续：不要报告能力缺失，"
            "请从当前 compact Action 重新读取 action.host_execution.workers[]."
            "native_launch_prompt，并将该字段原样传入同一个 Agent 重试；禁止把 "
            "stage prompt 或 prompt_ref 正文作为 Agent 参数。"
        ),
        "NATIVE_WORKER_STOP_FORBIDDEN": (
            "已阻止停止当前 Worker；必须继续对同一个 Agent handle 调用 TaskOutput，"
            "直到 Worker 进入终态。"
        ),
        "NATIVE_WORKER_OUTCOME_MUTATION_FORBIDDEN": (
            "已阻止 Coordinator 直接写入 Worker 私有 outcome；必须使用原生 Agent/Task"
            "返回和固定 record-worker-outcome 回写边界，不能手工伪造 Worker 事实。"
        ),
        "NATIVE_WORKER_OUTCOME_PATH_MISMATCH": (
            "已阻止 Worker 写入不属于当前 Action 的 outcome 路径；只能写入当前"
            " invocation 绑定的私有业务产物。"
        ),
        "NATIVE_RECORD_ARGUMENTS_MISSING": (
            "已阻止 Worker 回写命令：请原样使用当前 Action 的 record-worker-outcome "
            "argv_template，并把所有占位符替换为字面量；不得用 $VAR、$(...) 或 pwd。"
        ),
        "NATIVE_RESULT_PATH_MISMATCH": (
            "已阻止 Worker 回写命令：--native-result-file 必须逐字使用当前 Action "
            "绑定的路径；只修正这一参数后重试，不得手写 worker-outcomes。"
        ),
        "NATIVE_PROJECT_ROOT_INVALID": (
            "已阻止 Worker 回写命令：--project-root 必须是当前 Action 给出的字面量绝对路径，"
            "不得使用环境变量或命令替换；修正后重试同一命令。"
        ),
        "NATIVE_PROJECT_ROOT_MISMATCH": (
            "已阻止 Worker 回写命令：--project-root 必须逐字匹配当前项目根的字面量绝对路径，"
            "不得使用环境变量或命令替换；修正后重试同一命令。"
        ),
        "NATIVE_WORKER_TEMPLATE_UNAVAILABLE": (
            "已阻止未由当前 Action 声明的原生 Worker；当前 Action 没有可消费的"
            " workers[] 合同。若存在 host_execution.recovery 且 spawn_permitted=false，"
            "必须直接执行 recovery 的 finalize/validate/submit，不能自行发起 Worker。"
        ),
        "BINDING_DESIGN_READ_ONLY": (
            "已阻止修改当前 Loop 绑定的设计文档；该文档是只读设计权威。若确需变更，"
            "只能提交 design_change_requests[]，等待 Core 发出用户 Gate 后再执行。"
        ),
        "NATIVE_ASSEMBLER_WORK_FILE_FORBIDDEN": (
            "已阻止宿主直接写入 Core/Assembler 管理的 outcomes.json 或 result.json；"
            "只能写入当前 Action 的 coordinator-result.json，再按绑定的 "
            "finalize → validate → submit 操作生成完整 Result。"
        ),
    }
    return messages.get(
        code,
        "原生 Worker 调用未消费当前 Action 合同，已阻止执行。",
    )


_SPAWN_TOOLS = {
    HostPlatform.CODEX.value: {
        "collaboration.spawn_agent",
        "multi_agent_v1__spawn_agent",
    },
    HostPlatform.CLAUDE_CODE.value: {"Agent"},
}
_PROMPT_FIELDS = ("prompt", "message", "instructions")
_MUTATING_FILE_TOOLS = {"Edit", "Write", "MultiEdit", "apply_patch"}
_MUTATING_COMMANDS = {"cp", "install", "mv", "rm", "rmdir", "unlink", "shred", "tee", "sed"}
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
_WORKER_OUTCOME = re.compile(
    r"\.ae-state/host-runtime/worker-outcomes(?:/|$)"
)
_BINDING_DESIGN_TOOLS = {"Edit", "Write", "MultiEdit", "apply_patch"}
_LAUNCH_HEADER = "AUTO_ENGINEERING_NATIVE_WORKER_LAUNCH_V1\nVERBATIM=1;NO_EXTRA\n"


def _option(command: str, name: str) -> str | None:
    """读取简单 shell argv 选项，支持无空格路径和单/双引号。"""

    pattern = re.compile(
        rf"(?:^|\s){re.escape(name)}(?:=|\s+)"
        rf"(?:\"([^\"]*)\"|'([^']*)'|([^\s]+))"
    )
    match = pattern.search(command)
    if match is None:
        return None
    return next((item for item in match.groups() if item is not None), None)


def _worker_id(worker: Mapping[str, object]) -> str | None:
    value = worker.get("worker_id")
    return value if isinstance(value, str) and value else None


def _tool_path(tool_input: Mapping[str, object]) -> str | None:
    """读取文件工具的目标路径，不把 prompt 正文当作控制输入。"""

    for key in ("file_path", "filepath", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _binding_design_path(project_root: Path) -> Path | None:
    """读取当前账本绑定的设计来源；缺失账本时不猜测设计路径。"""

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


def _is_binding_design_mutation(
    *,
    tool_name: str,
    tool_input: Mapping[str, object],
    project_root: Path,
) -> bool:
    """阻止 Claude/Codex 通过直接文件工具改写当前绑定设计。"""

    if tool_name not in _BINDING_DESIGN_TOOLS:
        return False
    supplied = _tool_path(tool_input)
    if not supplied:
        return False
    try:
        candidate = Path(supplied)
        supplied_path = (candidate if candidate.is_absolute() else project_root / candidate).resolve()
    except (OSError, RuntimeError):
        return False
    binding_path = _binding_design_path(project_root)
    return binding_path is not None and supplied_path == binding_path


def _validate_binding_design_mutation(
    *,
    tool_name: str,
    tool_input: Mapping[str, object],
    project_root: Path,
) -> None:
    if _is_binding_design_mutation(
        tool_name=tool_name,
        tool_input=tool_input,
        project_root=project_root,
    ):
        raise NativeLaunchGuardError("BINDING_DESIGN_READ_ONLY")


def _validate_assembler_work_file_mutation(
    *,
    tool_name: str,
    tool_input: Mapping[str, object],
) -> None:
    """禁止宿主伪造 Assembler 所有的共享结果文件。"""

    if tool_name not in _MUTATING_FILE_TOOLS:
        return
    values = [value for value in tool_input.values() if isinstance(value, str)]
    if any(_ASSEMBLER_OWNED_WORK_FILE.search(value) for value in values):
        raise NativeLaunchGuardError("NATIVE_ASSEMBLER_WORK_FILE_FORBIDDEN")


def _validate_worker_prompt_read(
    *,
    tool_input: Mapping[str, object],
    workers: Sequence[Mapping[str, object]],
    project_root: Path,
    worker_context: bool,
) -> None:
    """Coordinator 不得读取 Worker prompt；Worker 在 fresh context 内读取。"""

    if worker_context:
        return

    supplied = _tool_path(tool_input)
    if not supplied:
        return
    try:
        supplied_path = Path(supplied)
        supplied_resolved = (
            supplied_path if supplied_path.is_absolute()
            else project_root / supplied_path
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
                expected_path if expected_path.is_absolute()
                else project_root / expected_path
            ).resolve()
        except (OSError, RuntimeError):
            continue
        if supplied_resolved == expected_resolved:
            raise NativeLaunchGuardError("NATIVE_WORKER_PROMPT_READ_FORBIDDEN")


def _validate_spawn_prompt(
    *,
    platform: str,
    tool_input: Mapping[str, object],
    workers: Sequence[Mapping[str, object]],
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
    expected: set[str] = set()
    for worker in workers:
        candidate = worker.get("native_launch_prompt")
        if isinstance(candidate, str):
            expected.add(candidate)
    if prompt in expected:
        return
    if platform == HostPlatform.CLAUDE_CODE.value and any(
        _claude_launch_contract_matches(prompt, candidate)
        for candidate in expected
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


def _claude_launch_contract_matches(supplied: str, expected: str) -> bool:
    """允许 Claude 原生工具格式化说明行，但不放宽机器合同 JSON。"""

    if not supplied.startswith(_LAUNCH_HEADER) or not expected.startswith(_LAUNCH_HEADER):
        return False
    supplied_contract = _json_contract(supplied)
    expected_contract = _json_contract(expected)
    if supplied_contract is None or expected_contract is None:
        return False
    supplied_value, supplied_end = supplied_contract
    expected_value, expected_end = expected_contract
    if supplied_value != expected_value:
        # Claude 偶尔会在复制长 JSON 合同时把第一个键复制成
        # ``" may_drive_loop"``。这不是对合同值的放宽：只接受这个已知的
        # 键名前空格别名，且归一化后仍必须与当前 Action 完全相等。
        if (
            isinstance(supplied_value, dict)
            and " may_drive_loop" in supplied_value
            and "may_drive_loop" not in supplied_value
        ):
            normalized = dict(supplied_value)
            normalized["may_drive_loop"] = normalized.pop(" may_drive_loop")
            if normalized == expected_value:
                supplied_value = normalized
        # Claude 在复制长机器合同的 hash 时，可能把 prompt artifact 的
        # `.txt` 后缀一并带入 `prompt_sha256`。只接受“当前期望 hash + .txt”
        # 这一种可证明的表示误差；任何其他字段或 hash 都仍然 fail-closed。
        supplied_hash = supplied_value.get("prompt_sha256")
        expected_hash = expected_value.get("prompt_sha256")
        if supplied_hash == f"{expected_hash}.txt":
            supplied_value = dict(supplied_value)
            supplied_value["prompt_sha256"] = expected_hash
    if supplied_value != expected_value or expected[expected_end:].strip():
        return False
    suffix = supplied[supplied_end:]
    if not suffix.strip():
        return True
    # Claude's Agent tool may append the same Worker task description after
    # the machine contract.  Keep the contract/header immutable and accept
    # only the host-generated separator form; arbitrary suffixes stay blocked.
    return suffix.startswith("\n\n---\n\n") and _LAUNCH_HEADER not in suffix


def _validate_record_command(
    *,
    command: str,
    workers: Sequence[Mapping[str, object]],
    project_root: Path,
) -> None:
    if "--record-worker-outcome" not in command:
        return
    worker_id = _option(command, "--worker-id")
    native_result_path = _option(command, "--native-result-file")
    supplied_project_root = _option(command, "--project-root")
    if not worker_id or not native_result_path or not supplied_project_root:
        raise NativeLaunchGuardError("NATIVE_RECORD_ARGUMENTS_MISSING")
    worker = next(
        (item for item in workers if item.get("worker_id") == worker_id),
        None,
    )
    if worker is None:
        raise NativeLaunchGuardError("NATIVE_RECORD_WORKER_MISMATCH")
    expected_native_path = worker.get("native_result_path")
    if not isinstance(expected_native_path, str):
        raise NativeLaunchGuardError("NATIVE_RESULT_PATH_MISMATCH")
    try:
        supplied_path = Path(native_result_path)
        expected_path = Path(expected_native_path)
        supplied_resolved = (
            supplied_path if supplied_path.is_absolute()
            else project_root / supplied_path
        ).resolve()
        expected_resolved = (
            expected_path if expected_path.is_absolute()
            else project_root / expected_path
        ).resolve()
    except (OSError, RuntimeError):
        raise NativeLaunchGuardError("NATIVE_RESULT_PATH_MISMATCH") from None
    if (
        supplied_resolved != expected_resolved
        or project_root.resolve() not in supplied_resolved.parents
    ):
        raise NativeLaunchGuardError("NATIVE_RESULT_PATH_MISMATCH")
    try:
        actual_root = Path(supplied_project_root).resolve()
    except (OSError, RuntimeError):
        raise NativeLaunchGuardError("NATIVE_PROJECT_ROOT_INVALID") from None
    if actual_root != project_root.resolve():
        raise NativeLaunchGuardError("NATIVE_PROJECT_ROOT_MISMATCH")


def _validate_finalize_command(
    *,
    command: str,
    workers: Sequence[Mapping[str, object]],
    project_root: Path,
) -> None:
    """在宿主边界校验 Finalizer 只使用当前 Action 的共享工作文件。"""

    if "--finalize-result" not in command:
        return
    # 非 spawn Action 可能把业务 payload 作为 finalize 输入；只有带有
    # spawn 专属的共享 coordinator/result 文件参数时，才执行 Worker Action
    # 的三路径校验。
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
        option: work_files.get(key)
        for option, key in (
            ("--finalize-result", "outcomes"),
            ("--coordinator-result", "coordinator_result"),
            ("--output-result", "result"),
        )
    }
    for option, expected_value in expected.items():
        supplied = _option(command, option)
        if expected_value is None:
            continue
        if not isinstance(expected_value, str) or not supplied:
            raise NativeLaunchGuardError("NATIVE_FINALIZE_PATH_MISSING")
        try:
            if resolve(supplied) != resolve(expected_value):
                raise NativeLaunchGuardError("NATIVE_FINALIZE_PATH_MISMATCH")
        except (OSError, RuntimeError):
            raise NativeLaunchGuardError("NATIVE_FINALIZE_PATH_MISMATCH") from None


def _validate_state_mutation(
    *,
    tool_name: str,
    tool_input: Mapping[str, object],
    workers: Sequence[Mapping[str, object]],
    project_root: Path,
    worker_context: bool,
) -> None:
    """禁止 Coordinator/Worker 直接修改 Loop 的协议状态文件。"""

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


def active_native_workers(
    *,
    project_root: Path,
    platform: HostPlatform,
) -> list[Mapping[str, object]] | None:
    """读取当前租约绑定 Action 的宿主 Worker 模板。

    没有 CONTINUE 租约时返回 ``None``，不接管宿主的普通 Agent/Bash 调用；
    有租约但无法读取唯一 Action 时抛错，避免验证器静默放行。
    """

    from auto_engineering.host.adapters import adapter_for
    from auto_engineering.host.runtime_driver import HostRunLeaseError, HostRunLeaseStore
    from auto_engineering.loop.event_store import SQLiteEventStore

    try:
        lease = HostRunLeaseStore(project_root).load()
    except HostRunLeaseError as exc:
        raise NativeLaunchGuardError(str(exc)) from exc
    if lease is None or lease.disposition != "CONTINUE":
        return None
    if lease.platform != platform.value:
        raise NativeLaunchGuardError("NATIVE_HOST_PLATFORM_MISMATCH")
    events_path = project_root.resolve() / ".ae-state" / "events.db"
    if not events_path.is_file():
        raise NativeLaunchGuardError("NATIVE_ACTIVE_ACTION_UNAVAILABLE")
    events = SQLiteEventStore(events_path)
    try:
        action = events.load_action_snapshot(lease.thread_id)
    finally:
        events.close()
    if not isinstance(action, Mapping) or action.get("message_id") != lease.action_message_id:
        raise NativeLaunchGuardError("NATIVE_ACTIVE_ACTION_MISMATCH")
    if action.get("project_root") != str(project_root.resolve()):
        raise NativeLaunchGuardError("NATIVE_PROJECT_ROOT_MISMATCH")
    bound_action = dict(action)
    bound_action["execution_generation"] = lease.execution_generation
    adapter = adapter_for(platform)
    profile = adapter.profile(
        detected=adapter.capabilities,
        authorized=adapter.capabilities,
    )
    try:
        mapped = adapter.map_action(bound_action, profile=profile).payload
    except (OSError, TypeError, ValueError) as exc:
        raise NativeLaunchGuardError("NATIVE_ACTIVE_ACTION_INVALID") from exc
    host_execution = mapped.get("host_execution")
    if not isinstance(host_execution, Mapping):
        raise NativeLaunchGuardError("NATIVE_WORKER_TEMPLATE_UNAVAILABLE")
    if "workers" not in host_execution:
        return []
    workers = host_execution.get("workers")
    if not isinstance(workers, list) or not all(
        isinstance(item, Mapping) for item in workers
    ):
        raise NativeLaunchGuardError("NATIVE_WORKER_TEMPLATE_UNAVAILABLE")
    return workers


def _spawn_action_requires_lease(project_root: Path) -> bool:
    """判断无 lease 时是否仍有未恢复的 Loop Worker Action。"""

    checkpoint_path = project_root.resolve() / ".ae-state" / "checkpoints.db"
    events_path = project_root.resolve() / ".ae-state" / "events.db"
    if not checkpoint_path.is_file() or not events_path.is_file():
        return False
    from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore
    from auto_engineering.loop.event_store import SQLiteEventStore

    store: SQLiteCheckpointStore[Any] = SQLiteCheckpointStore(
        checkpoint_path, read_only=True
    )
    events = SQLiteEventStore(events_path)
    try:
        thread_id = store.active_project_thread()
        if not isinstance(thread_id, str) or not thread_id:
            return False
        action = events.load_action_snapshot(thread_id)
        if not isinstance(action, Mapping):
            return False
        if action.get("project_root") != str(project_root.resolve()):
            return False
        host_execution = action.get("host_execution")
        workers = host_execution.get("workers") if isinstance(host_execution, Mapping) else None
        return isinstance(workers, list) and bool(workers)
    except (OSError, TypeError, ValueError, sqlite3.Error):
        return False
    finally:
        events.close()
        store.close()


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

    payload = json.load(__import__("sys").stdin)
    if not isinstance(payload, Mapping):
        return 0
    raw_platform = payload.get("platform")
    platform = HostPlatform(raw_platform) if isinstance(raw_platform, str) else None
    cwd = payload.get("cwd")
    if platform is None or not isinstance(cwd, str) or not cwd:
        return 0
    try:
        guard_active_native_tool_call(
            payload,
            project_root=Path(cwd).resolve(),
            platform=platform,
        )
    except NativeLaunchGuardError as exc:
        message = guard_system_message(exc.code)
        print(json.dumps({
            "decision": "block",
            "reason_code": exc.code,
            "reason": message,
            "systemMessage": message,
            "permissionDecision": "deny",
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            },
        }, ensure_ascii=False))
        return 0
    print(json.dumps({
        "decision": "approve",
        "permissionDecision": "allow",
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        },
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "NativeLaunchGuardError",
    "active_native_workers",
    "guard_active_native_tool_call",
    "guard_system_message",
    "validate_native_tool_call",
]
