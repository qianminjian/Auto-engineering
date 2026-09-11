"""Claude Code Stop Hook 到共享 Host Runtime 门禁的适配。"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import TextIO

from auto_engineering.host.runtime_driver import (
    HostRunLeaseError,
    HostRunLeaseStore,
    StopGuardDecision,
    continuation_recovery_contract,
    evaluate_stop,
)
from auto_engineering.host.stop_report import handle_claude_session_end


def _launch_contract(prompt: object) -> dict[str, object] | None:
    if not isinstance(prompt, str):
        return None
    marker = prompt.rfind("{")
    while marker >= 0:
        try:
            value = json.loads(prompt[marker:])
        except json.JSONDecodeError:
            marker = prompt.rfind("{", 0, marker)
            continue
        if isinstance(value, dict) and isinstance(value.get("worker_id"), str):
            return value
        marker = prompt.rfind("{", 0, marker)
    return None


def _task_output_payload(response: object) -> object | None:
    """把 Claude TaskOutput 的完成观察转换为可解析的原生正文。"""

    if isinstance(response, Mapping):
        status = response.get("status")
        if status in {"running", "pending", "async_launched"}:
            return None
        # Claude Code 的对象格式 TaskOutput 会把真实结果放在
        # ``task.output`` 中，并额外包一层 retrieval_status/task。这个
        # 宿主内部信封不能直接进入 Worker evidence；只提取完成态的原生
        # 正文，交给统一的 native-result parser 解析业务 JSON。
        task = response.get("task")
        if isinstance(task, Mapping):
            task_status = task.get("status")
            if task_status in {"running", "pending", "async_launched"}:
                return None
            if task_status not in {"completed", "complete", "success", "ok"}:
                return None
            output = task.get("output")
            if not isinstance(output, str) or not output.strip():
                return None
            return {"content": [{"type": "text", "text": output}]}
        output = response.get("output")
        if status in {"completed", "complete", "success", "ok"} and isinstance(output, str):
            if output.strip():
                return {"content": [{"type": "text", "text": output}]}
            return None
        return response
    if not isinstance(response, str):
        return response
    status_match = re.search(r"<status>\s*([^<]+?)\s*</status>", response)
    if status_match and status_match.group(1).strip().lower() not in {
        "completed", "complete", "success", "ok",
    }:
        return None
    output_match = re.search(
        r"<output>\s*(.*?)\s*</output>", response, flags=re.DOTALL
    )
    text = output_match.group(1).strip() if output_match else response.strip()
    if not text:
        return None
    return {"content": [{"type": "text", "text": text}]}


def _resolve_task_output_worker(
    *,
    workers: list[Mapping[str, object]],
    task_id: str,
    project_root: Path,
) -> Mapping[str, object] | None:
    """通过先前固化的 Agent handle 找到对应 Worker，禁止按顺序猜测。"""

    for worker in workers:
        native_path = worker.get("native_result_path")
        if not isinstance(native_path, str):
            continue
        target = (
            (project_root / native_path).resolve()
            if not Path(native_path).is_absolute()
            else Path(native_path).resolve()
        )
        if project_root not in target.parents or not target.is_file():
            continue
        try:
            metadata = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            continue
        if isinstance(metadata, Mapping) and (
            metadata.get("agentId") == task_id
            or metadata.get("task_id") == task_id
            or worker.get("native_worker_handle") == task_id
        ):
            return worker
    return None


def _record_native_observation(
    *,
    root: Path,
    worker: Mapping[str, object],
    native_status: str,
    owner_known: bool,
    native_worker_handle: str | None,
) -> bool:
    """固化 Agent 调用阶段，供外层 watchdog 区分合法等待与失活。"""

    from datetime import UTC, datetime

    from auto_engineering.host.worker_observation import WorkerObservationRecord
    from auto_engineering.host.worker_observation_store import WorkerObservationStore

    lease = HostRunLeaseStore(root).load()
    generation = worker.get("execution_generation")
    fencing_token = worker.get("fencing_token")
    if (
        lease is None
        or not isinstance(generation, int)
        or isinstance(generation, bool)
        or not isinstance(fencing_token, str)
    ):
        return False
    try:
        record = WorkerObservationRecord(
            schema_version="1.0",
            action_message_id=lease.action_message_id,
            worker_id=str(worker["worker_id"]),
            execution_generation=generation,
            fencing_token=fencing_token,
            observed_at=datetime.now(UTC).isoformat(),
            native_status=native_status,
            wait_attempt=0,
            owner_known=owner_known,
            native_worker_handle=native_worker_handle,
        )
        WorkerObservationStore(root).save(record)
    except (KeyError, OSError, TypeError, ValueError):
        return False
    return True


def _record_agent_post_tool_observation(
    *,
    root: Path,
    worker: Mapping[str, object],
    response: object,
) -> None:
    status = response.get("status") if isinstance(response, Mapping) else None
    native_status = (
        "running"
        if status in {"running", "pending", "async_launched"}
        else status
        if status in {"failed", "cancelled", "timed_out"}
        else "unknown"
    )
    _record_native_observation(
        root=root,
        worker=worker,
        native_status=native_status,
        owner_known=False,
        native_worker_handle=None,
    )


def _pre_tool_worker(payload: Mapping[str, object]) -> Mapping[str, object] | None:
    """为当前 Agent launch 找到唯一 Action-bound Worker。"""

    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import active_native_workers

    cwd = payload.get("cwd")
    tool_input = payload.get("tool_input")
    if not isinstance(cwd, str) or not isinstance(tool_input, Mapping):
        return None
    if payload.get("tool_name") not in {"Agent", "Task"}:
        return None
    contract = _launch_contract(tool_input.get("prompt"))
    worker_id = contract.get("worker_id") if contract else None
    if not isinstance(worker_id, str):
        return None
    try:
        workers = active_native_workers(
            project_root=Path(cwd).resolve(),
            platform=HostPlatform.CLAUDE_CODE,
        )
    except (OSError, TypeError, ValueError):
        return None
    if workers is None:
        return None
    return next(
        (
            item for item in workers
            if item.get("worker_id") == worker_id
        ),
        None,
    )


def _capture_claude_post_tool(payload: Mapping[str, object]) -> dict[str, object]:
    """由 PostToolUse Hook 固化 Claude Agent 的原生返回，不让 Coordinator 重建。"""

    tool_name = payload.get("tool_name")
    if tool_name not in {"Agent", "Task", "TaskOutput"}:
        return {"systemMessage": "Auto-Engineering Hook 已安全跳过"}
    cwd = payload.get("cwd")
    tool_input = payload.get("tool_input")
    if not isinstance(cwd, str) or not isinstance(tool_input, Mapping):
        return {"systemMessage": "Auto-Engineering Hook 输入无效，已安全跳过"}
    root = Path(cwd).resolve()
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import active_native_workers

    try:
        workers = active_native_workers(
            project_root=root,
            platform=HostPlatform.CLAUDE_CODE,
        )
    except (OSError, TypeError, ValueError):
        return {"systemMessage": "Auto-Engineering 原生 Worker 证据未能固化"}
    if workers is None:
        return {"systemMessage": "Auto-Engineering 原生 Worker 证据未能固化"}
    worker: Mapping[str, object] | None
    if tool_name in {"Agent", "Task"}:
        contract = _launch_contract(tool_input.get("prompt"))
        worker_id = contract.get("worker_id") if contract else None
        if not isinstance(worker_id, str):
            return {"systemMessage": "Auto-Engineering Hook 已安全跳过"}
        worker = next((item for item in workers if item.get("worker_id") == worker_id), None)
        response = payload.get("tool_response")
    else:
        task_id = tool_input.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return {"systemMessage": "Auto-Engineering Hook 已安全跳过"}
        worker = _resolve_task_output_worker(
            workers=workers,
            task_id=task_id,
            project_root=root,
        )
        response = _task_output_payload(payload.get("tool_response"))
        if response is None:
            if worker is not None:
                _record_native_observation(
                    root=Path(cwd).resolve(),
                    worker=worker,
                    native_status="running",
                    owner_known=True,
                    native_worker_handle=task_id,
                )
            return {"systemMessage": "Auto-Engineering Hook 已记录 Worker 仍在运行"}
    native_path = worker.get("native_result_path") if worker else None
    if worker is None or not isinstance(native_path, str) or response is None:
        if tool_name in {"Agent", "Task"} and worker is not None:
            _record_agent_post_tool_observation(
                root=root,
                worker=worker,
                response=response,
            )
        return {"systemMessage": "Auto-Engineering 原生 Worker 证据未能固化"}

    target = (root / native_path).resolve() if not Path(native_path).is_absolute() else Path(native_path).resolve()
    if root not in target.parents or target.name == "":
        return {"systemMessage": "Auto-Engineering 原生 Worker 路径无效"}
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(response, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
        os.replace(temporary, target)
    except (OSError, TypeError, ValueError):
        with suppress(OSError):
            os.unlink(temporary)
        return {"systemMessage": "Auto-Engineering 原生 Worker 证据未能固化"}
    if tool_name in {"Agent", "Task"}:
        _record_agent_post_tool_observation(
            root=root,
            worker=worker,
            response=response,
        )
    if tool_name == "TaskOutput":
        _record_native_observation(
            root=root,
            worker=worker,
            native_status="completed",
            owner_known=True,
            native_worker_handle=task_id,
        )
    return {"systemMessage": "Auto-Engineering 原生 Worker 证据已固化"}


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> int:
    try:
        payload = json.load(stdin)
        if not isinstance(payload, dict):
            raise ValueError("Hook 输入必须是 JSON object")
        event_name = payload.get("hook_event_name")
        cwd = payload.get("cwd")
        if event_name == "PostToolUse":
            response = _capture_claude_post_tool(payload)
            json.dump(response, stdout, ensure_ascii=False)
            stdout.write("\n")
            return 0
        if event_name == "PreToolUse":
            worker = _pre_tool_worker(payload)
            if worker is not None and isinstance(cwd, str) and cwd:
                recorded = _record_native_observation(
                    root=Path(cwd).resolve(),
                    worker=worker,
                    native_status="running",
                    owner_known=False,
                    native_worker_handle=None,
                )
                message = (
                    "Auto-Engineering 已记录原生 Worker 启动"
                    if recorded
                    else "Auto-Engineering 原生 Worker 启动观察未能固化"
                )
                json.dump({"systemMessage": message}, stdout, ensure_ascii=False)
                stdout.write("\n")
            return 0
        if event_name not in {"Stop", "SessionEnd", "StopFailure"} or not isinstance(cwd, str) or not cwd:
            return 0
        if event_name in {"SessionEnd", "StopFailure"}:
            # 普通外层适配器也必须延后：它拥有完整的 attempt 输出，Hook
            # 只有有限的事件 payload，不能抢先把真实上游错误降级为 unknown。
            if os.environ.get("AE_HOST_ADAPTER_ACTIVE") == "1":
                response = {"systemMessage": "Auto-Engineering 退出事实交由外层宿主边界记录"}
            else:
                preserve_lease = os.environ.get("AE_HOST_ADAPTER_AUTO_RESUME") == "1"
                response = handle_claude_session_end(Path(cwd), payload, clear_lease=not preserve_lease)
            json.dump(response, stdout, ensure_ascii=False)
            stdout.write("\n")
            return 0
        session_id = payload.get("session_id")
        normalized_session = session_id if isinstance(session_id, str) else None
        try:
            lease = HostRunLeaseStore(Path(cwd)).load()
        except HostRunLeaseError:
            json.dump(
                {
                    "decision": "block",
                    "reason_code": "AE_HOST_RUN_LEASE_CORRUPT",
                    "systemMessage": "Auto-Engineering 运行租约损坏，已阻止不安全停止",
                },
                stdout,
                ensure_ascii=False,
            )
            stdout.write("\n")
            return 0
        if evaluate_stop(
            lease,
            host_session_id=normalized_session,
        ) is StopGuardDecision.BLOCK:
            assert lease is not None
            json.dump(
                {
                    "decision": "block",
                    "reason_code": "AE_CONTINUATION_REQUIRED",
                    "action_message_id": lease.action_message_id,
                    "continuation": continuation_recovery_contract(lease),
                    "systemMessage": "Auto-Engineering 仍有必须继续执行的 Action",
                },
                stdout,
                ensure_ascii=False,
            )
            stdout.write("\n")
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        json.dump(
            {"systemMessage": "Auto-Engineering Hook 输入无效，已安全跳过"},
            stdout,
            ensure_ascii=False,
        )
        stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
