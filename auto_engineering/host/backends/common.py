"""Action-scoped CLI 后端共享的无状态工具。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from auto_engineering.host.invocation import ActionExecutionRequest

ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


class CancellableProcessRunner:
    """单 invocation 的无 Shell 进程执行器，支持有界 terminate→kill。"""

    def __init__(
        self,
        *,
        cancel_grace_seconds: float = 2.0,
        progress_callback: Callable[[float], None] | None = None,
        heartbeat_seconds: float = 300.0,
    ) -> None:
        self._cancel_grace_seconds = cancel_grace_seconds
        self._progress_callback = progress_callback
        self._heartbeat_seconds = heartbeat_seconds
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None

    def _terminate(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=self._cancel_grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def cancel(self) -> None:
        with self._lock:
            process = self._process
        if process is not None:
            self._terminate(process)

    def __call__(
        self,
        command: tuple[str, ...],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        raw_cwd = kwargs.get("cwd")
        cwd = str(raw_cwd) if isinstance(raw_cwd, (str, Path)) else None
        raw_env = kwargs.get("env")
        env = (
            {str(key): str(value) for key, value in raw_env.items()}
            if isinstance(raw_env, Mapping)
            else None
        )
        raw_input = kwargs.get("input")
        input_text = raw_input if isinstance(raw_input, str) else None
        raw_timeout = kwargs.get("timeout")
        timeout = (
            float(raw_timeout)
            if isinstance(raw_timeout, (int, float))
            and not isinstance(raw_timeout, bool)
            else None
        )
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            text=True,
            start_new_session=True,
        )
        with self._lock:
            if self._process is not None:
                process.kill()
                process.wait()
                raise RuntimeError("HOST_INVOCATION_ALREADY_ACTIVE")
            self._process = process
        heartbeat_stop = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        progress_callback = self._progress_callback
        if progress_callback is not None and self._heartbeat_seconds > 0:
            started_at = time.monotonic()

            def emit_heartbeat() -> None:
                while not heartbeat_stop.wait(self._heartbeat_seconds):
                    progress_callback(time.monotonic() - started_at)

            heartbeat_thread = threading.Thread(
                target=emit_heartbeat,
                name="ae-host-context-heartbeat",
                daemon=True,
            )
            heartbeat_thread.start()
        try:
            try:
                stdout, stderr = process.communicate(
                    input=input_text,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                self._terminate(process)
                stdout, stderr = process.communicate()
                raise subprocess.TimeoutExpired(
                    command,
                    timeout if timeout is not None else 0.0,
                    output=stdout,
                    stderr=stderr,
                ) from None
            return subprocess.CompletedProcess(
                command,
                process.returncode,
                stdout=stdout,
                stderr=stderr,
            )
        except BaseException:
            self._terminate(process)
            raise
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=1.0)
            with self._lock:
                if self._process is process:
                    self._process = None


def launcher_prompt(request: ActionExecutionRequest) -> str:
    """仅携带当前 Action 引用；不携带历史对话或 Core 事件。"""
    payload = json.dumps(
        request.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    write_policy = (
        "本 Action 允许按 Prompt 要求修改 project_root 内业务文件；"
        "不得修改执行包、Core 状态或 result 文件。"
        if "edit" in request.allowed_tools
        else "本 Action 不允许修改项目业务文件；只可写 coordinator_result 和 outcomes。"
    )
    return (
        "AUTO_ENGINEERING_ACTION_CONTEXT_V1\n"
        "你只执行下面绑定的一个 Action。校验 compact envelope 与 coordinator ref 的 "
        f"SHA-256 后读取并严格执行；{write_policy}不得调用 dev-loop "
        "init/tick/resume，不得驱动下一 Action，不得读取或总结旧聊天记录。最终只返回 "
        "ActionContextOutcome。coordinator_result 顶层只包含 expected_format 业务字段；"
        "result_contract 是机器类型事实源，数组和对象必须写为原生 JSON，不得再次序列化为字符串；"
        "不得包装在 result 中，不得复制 action/stage/tick/thread_id 等 Core 身份。"
        "在返回 completed 前必须把业务 JSON 原子写入 request.work_files.coordinator_result；"
        "需要 Worker 时同时写 outcomes；绝不写 request.work_files.result。\n"
        + payload
    )


def jsonl_events(output: str) -> tuple[Mapping[str, object], ...]:
    events: list[Mapping[str, object]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            events.append(value)
    return tuple(events)


def existing_work_file_digests(request: ActionExecutionRequest) -> dict[str, str]:
    root = Path(request.project_root).resolve()
    digests: dict[str, str] = {}
    for name, relative in request.work_files.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def normalize_coordinator_work_output(
    request: ActionExecutionRequest,
) -> None:
    """在 context 成功回执前按 compact Action 合同规范化业务输出。"""

    from auto_engineering.host.execution_assembler import (
        HostEvidenceValidationError,
        HostExecutionAssembler,
    )

    root = Path(request.project_root).resolve()
    envelope_path = (root / request.compact_envelope_ref).resolve()
    coordinator_path = (
        root / request.work_files["coordinator_result"]
    ).resolve()
    if not envelope_path.is_relative_to(root) or not coordinator_path.is_relative_to(root):
        raise HostEvidenceValidationError(("ACTION_OUTPUT_PATH_INVALID",))
    # 旧测试/旧 Request 没有物化 compact envelope 时保持读取兼容；产品编译器始终写入。
    if not envelope_path.is_file() or not coordinator_path.is_file():
        return
    try:
        action = json.loads(envelope_path.read_text(encoding="utf-8"))
        payload = json.loads(coordinator_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostEvidenceValidationError(("HOST_OUTCOME_INPUT_INVALID",)) from exc
    if not isinstance(action, Mapping) or not isinstance(payload, Mapping):
        raise HostEvidenceValidationError(("HOST_OUTCOME_INPUT_INVALID",))
    normalized = HostExecutionAssembler._normalize_business_payload(
        action=action,
        coordinator_payload=payload,
    )
    if normalized == payload:
        return
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{coordinator_path.name}.",
        suffix=".tmp",
        dir=coordinator_path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, coordinator_path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def non_negative_number(value: object) -> int | float | None:
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value >= 0
    ):
        return value
    return None


def command_supports_flags(
    command: tuple[str, ...],
    required_flags: frozenset[str],
) -> bool:
    """以 CLI 自报 help 为能力事实；旧版本不得进入真实 Action。"""
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    help_text = f"{result.stdout}\n{result.stderr}"
    return result.returncode == 0 and all(
        flag in help_text for flag in required_flags
    )


def write_invocation_diagnostic(
    request: ActionExecutionRequest,
    *,
    backend: str,
    context_id: str,
    status: str,
    exit_code: int | None,
    stdout: str = "",
    stderr: str = "",
) -> Path:
    """持久化有界进程尾部；绝不写 launcher Prompt 或环境变量。"""
    root = Path(request.project_root).resolve()
    directory = root / ".ae-state" / "host-runtime" / "diagnostics"
    directory.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(
        f"{request.action_message_id}:{context_id}".encode()
    ).hexdigest()[:24]
    path = directory / f"{identity}.json"
    payload = json.dumps({
        "schema_version": "1.0",
        "thread_id": request.thread_id,
        "action_message_id": request.action_message_id,
        "host_context_id": context_id,
        "backend": backend,
        "status": status,
        "exit_code": exit_code,
        "stdout_tail": stdout[-4096:],
        "stderr_tail": stderr[-4096:],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".diagnostic-", suffix=".json", dir=directory, text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return path


__all__ = [
    "CancellableProcessRunner",
    "ProcessRunner",
    "command_supports_flags",
    "existing_work_file_digests",
    "jsonl_events",
    "launcher_prompt",
    "non_negative_number",
    "normalize_coordinator_work_output",
    "write_invocation_diagnostic",
]
