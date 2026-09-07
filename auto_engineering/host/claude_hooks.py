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


def _capture_claude_post_tool(payload: Mapping[str, object]) -> dict[str, object]:
    """由 PostToolUse Hook 固化 Claude Agent 的原生返回，不让 Coordinator 重建。"""

    tool_name = payload.get("tool_name")
    if tool_name not in {"Agent", "TaskOutput"}:
        return {"systemMessage": "Auto-Engineering Hook 已安全跳过"}
    cwd = payload.get("cwd")
    tool_input = payload.get("tool_input")
    if not isinstance(cwd, str) or not isinstance(tool_input, Mapping):
        return {"systemMessage": "Auto-Engineering Hook 输入无效，已安全跳过"}
    from auto_engineering.host import HostPlatform
    from auto_engineering.host.native_launch_guard import active_native_workers

    try:
        workers = active_native_workers(
            project_root=Path(cwd).resolve(),
            platform=HostPlatform.CLAUDE_CODE,
        )
    except (OSError, TypeError, ValueError):
        return {"systemMessage": "Auto-Engineering 原生 Worker 证据未能固化"}
    if workers is None:
        return {"systemMessage": "Auto-Engineering 原生 Worker 证据未能固化"}
    worker: Mapping[str, object] | None
    if tool_name == "Agent":
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
            project_root=Path(cwd).resolve(),
        )
        response = _task_output_payload(payload.get("tool_response"))
        if response is None:
            return {"systemMessage": "Auto-Engineering Hook 已记录 Worker 仍在运行"}
    native_path = worker.get("native_result_path") if worker else None
    if worker is None or not isinstance(native_path, str) or response is None:
        return {"systemMessage": "Auto-Engineering 原生 Worker 证据未能固化"}

    root = Path(cwd).resolve()
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
        if event_name not in {"Stop", "SessionEnd", "StopFailure"} or not isinstance(cwd, str) or not cwd:
            return 0
        if event_name in {"SessionEnd", "StopFailure"}:
            response = handle_claude_session_end(Path(cwd), payload)
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
