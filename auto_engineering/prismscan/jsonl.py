"""PrismScan V5.1 — JSONL 协议封装.

Python Orchestrator ↔ Agent Subprocess 通信层.
文件桥接模式: Python 写请求文件, Agent 写响应文件.

协议消息格式:
  {"request": "analyze|plan|generate", <payload>}

错误码:
  TIMEOUT          — Agent 响应超时 (默认 30s)
  INVALID_JSON     — 响应文件不是有效 JSON
  AGENT_ERROR      — Agent 返回了 error 类型消息
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

_logger = logging.getLogger("ae.prismscan.jsonl")

DEFAULT_TIMEOUT_SEC = 30
VALID_REQUESTS = {"analyze", "plan", "generate"}


class JSONLProtocol:
    """JSONL 文件桥接协议.

    mode="file": Python 写请求文件 → Agent 读取 → Agent 写响应文件 → Python 读取.

    用法:
        proto = JSONLProtocol(mode="file")
        req_path = proto.write_request("analyze", {"project_shape": ...}, Path("req.json"))
        # Agent reads req_path, processes, writes response
        response = proto.read_response(req_path)
    """

    def __init__(self, mode: str = "file") -> None:
        if mode not in ("file",):
            raise ValueError(f"Unsupported mode: {mode}. Only 'file' mode is supported.")
        self.mode = mode

    def write_request(
        self,
        request_type: str,
        payload: dict,
        filepath: str | Path,
    ) -> Path:
        """写 JSONL 请求文件.

        Args:
            request_type: 请求类型 (analyze/plan/generate).
            payload: 请求负载 (将被展开到消息顶层, request 字段除外).
            filepath: 输出文件路径.

        Returns:
            写入的文件 Path.

        Raises:
            ValueError: request_type 无效.
        """
        if request_type not in VALID_REQUESTS:
            raise ValueError(
                f"Invalid request_type: {request_type}. Must be one of {VALID_REQUESTS}"
            )

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        msg: dict = {"request": request_type}
        if "request" in payload:
            raise ValueError(
                "Payload must not contain 'request' key — it is reserved."
            )
        msg.update(payload)

        path.write_text(json.dumps(msg, ensure_ascii=False, indent=2))
        _logger.info("JSONL request written: %s (type=%s)", path, request_type)
        return path

    def read_response(self, filepath: str | Path) -> dict:
        """读取 JSONL 响应文件.

        Args:
            filepath: 响应文件路径.

        Returns:
            解析后的 JSON 字典.

        Raises:
            FileNotFoundError: 文件不存在.
            json.JSONDecodeError: JSON 格式无效.
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Response file not found: {path}")

        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            raise json.JSONDecodeError("Empty response file", "", 0)

        return json.loads(raw)

    def heartbeat(self) -> bool:
        """心跳检查 — 文件模式下始终返回 True."""
        return True

    def wait_for_response(
        self,
        filepath: str | Path,
        timeout: float = DEFAULT_TIMEOUT_SEC,
        poll_interval: float = 0.5,
    ) -> dict:
        """轮询等待响应文件出现并读取.

        Args:
            filepath: 预期的响应文件路径.
            timeout: 最大等待时间 (秒).
            poll_interval: 轮询间隔 (秒).

        Returns:
            解析后的响应字典.

        Raises:
            TimeoutError: 超时未收到响应.
        """
        path = Path(filepath)
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            if path.exists():
                try:
                    return self.read_response(path)
                except (json.JSONDecodeError, OSError):
                    pass
            time.sleep(poll_interval)

        raise TimeoutError(
            f"Timeout waiting for response file: {path} (timeout={timeout}s)"
        )
