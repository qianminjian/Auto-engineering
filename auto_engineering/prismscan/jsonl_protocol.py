"""PrismScan V5.1 — JSONL 文件桥接协议.

Python Orchestrator ↔ Agent Subprocess 通信层.
Python 写请求文件 (.jsonl), Agent 写响应文件 (.jsonl.response).

协议格式 (每行一个 JSON 消息):
  {"type": "analyze_request", "version": "1.0", "payload": {...}}

错误码:
  TIMEOUT          — Agent 响应超时 (默认 30s)
  INVALID_JSON     — 响应文件不是有效 JSON/JSONL
  AGENT_ERROR      — Agent 返回了 error 类型的消息
  FILE_NOT_FOUND   — 请求文件不存在
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

_logger = logging.getLogger("ae.prismscan.jsonl")

PROTOCOL_VERSION = "1.0"
DEFAULT_TIMEOUT_SEC = 30

# ── 请求类型 ──
REQUEST_TYPES = {"analyze", "plan", "generate"}

# ── 错误码 ──
class JSONLErrorCode:
    TIMEOUT = "TIMEOUT"
    INVALID_JSON = "INVALID_JSON"
    AGENT_ERROR = "AGENT_ERROR"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    INVALID_REQUEST_TYPE = "INVALID_REQUEST_TYPE"


class JSONLTimeoutError(TimeoutError):
    """Agent 响应超时."""
    def __init__(self, request_file: str, timeout: float) -> None:
        super().__init__(f"Agent 响应超时: {request_file} (timeout={timeout}s)")
        self.error_code = JSONLErrorCode.TIMEOUT


class JSONLProtocolError(Exception):
    """JSONL 协议错误."""
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _make_message(msg_type: str, payload: dict) -> dict:
    """构造标准 JSONL 消息."""
    return {
        "type": msg_type,
        "version": PROTOCOL_VERSION,
        "payload": payload,
    }


def write_request(
    request_type: str,
    payload: dict,
    work_dir: str | Path | None = None,
) -> Path:
    """写 JSONL 请求文件.

    Args:
        request_type: 请求类型 (analyze/plan/generate).
        payload: 请求负载数据.
        work_dir: 工作目录, 默认 repowiki/.state/

    Returns:
        写入的请求文件路径 (.jsonl).

    Raises:
        JSONLProtocolError: 如果 request_type 不合法.
    """
    if request_type not in REQUEST_TYPES:
        raise JSONLProtocolError(
            JSONLErrorCode.INVALID_REQUEST_TYPE,
            f"非法请求类型: {request_type}, 需为: {', '.join(sorted(REQUEST_TYPES))}",
        )

    wd = Path(work_dir) if work_dir else Path("repowiki/.state")
    wd.mkdir(parents=True, exist_ok=True)

    msg = _make_message(f"{request_type}_request", payload)
    request_file = wd / f"{request_type}-request.jsonl"
    request_file.write_text(json.dumps(msg, ensure_ascii=False) + "\n")
    _logger.info("JSONL request written: %s (type=%s)", request_file, request_type)
    return request_file


def read_response(
    request_file: str | Path,
    timeout: float = DEFAULT_TIMEOUT_SEC,
    poll_interval: float = 0.5,
) -> dict:
    """等待并读取 Agent 响应文件.

    Agent 应将响应写入 {request_file}.response.

    Args:
        request_file: write_request 返回的请求文件路径.
        timeout: 最长等待时间 (秒).
        poll_interval: 轮询间隔 (秒).

    Returns:
        响应消息的 payload 部分.

    Raises:
        JSONLTimeoutError: 超时未收到响应.
        JSONLProtocolError: 响应格式错误或 Agent 返回错误.
    """
    req_path = Path(request_file)
    if not req_path.exists():
        raise JSONLProtocolError(
            JSONLErrorCode.FILE_NOT_FOUND,
            f"请求文件不存在: {req_path}",
        )

    resp_path = req_path.parent / f"{req_path.stem}.response.jsonl"

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if resp_path.exists():
            try:
                raw = resp_path.read_text(encoding="utf-8").strip()
                if not raw:
                    time.sleep(poll_interval)
                    continue
            except Exception:
                time.sleep(poll_interval)
                continue

            try:
                lines = [json.loads(line) for line in raw.split("\n") if line.strip()]
            except json.JSONDecodeError as e:
                raise JSONLProtocolError(
                    JSONLErrorCode.INVALID_JSON,
                    f"响应文件不是有效 JSON: {e}",
                )

            if not lines:
                time.sleep(poll_interval)
                continue

            last_msg = lines[-1]

            if last_msg.get("type") == "error":
                raise JSONLProtocolError(
                    JSONLErrorCode.AGENT_ERROR,
                    last_msg.get("payload", {}).get("message", "Agent returned error"),
                )

            return last_msg.get("payload", last_msg)

        time.sleep(poll_interval)

    raise JSONLTimeoutError(str(req_path), timeout)


def write_response(
    request_file: str | Path,
    payload: dict,
    *,
    error: bool = False,
) -> Path:
    """写 JSONL 响应文件 (Agent 侧调用).

    Args:
        request_file: 对应的请求文件路径.
        payload: 响应负载数据.
        error: 是否为错误响应.

    Returns:
        写入的响应文件路径.
    """
    req_path = Path(request_file)
    resp_path = req_path.parent / f"{req_path.stem}.response.jsonl"

    if error:
        msg = {
            "type": "error",
            "version": PROTOCOL_VERSION,
            "payload": payload,
        }
    else:
        msg = {
            "type": f"{req_path.stem.replace('-request', '')}_response",
            "version": PROTOCOL_VERSION,
            "payload": payload,
        }

    resp_path.write_text(json.dumps(msg, ensure_ascii=False) + "\n")
    _logger.info("JSONL response written: %s", resp_path)
    return resp_path


def read_request(request_file: str | Path) -> dict:
    """读取 JSONL 请求文件 (Agent 侧调用).

    Returns:
        请求消息的 payload 部分.

    Raises:
        JSONLProtocolError: 文件不存在或格式错误.
    """
    path = Path(request_file)
    if not path.exists():
        raise JSONLProtocolError(
            JSONLErrorCode.FILE_NOT_FOUND,
            f"请求文件不存在: {path}",
        )
    try:
        raw = path.read_text(encoding="utf-8").strip()
        msg = json.loads(raw)
    except json.JSONDecodeError as e:
        raise JSONLProtocolError(
            JSONLErrorCode.INVALID_JSON,
            f"请求文件不是有效 JSON: {e}",
        )
    return msg.get("payload", msg)
