"""Structured audit log — JSONL LLM call recording (T61).

Design ref: v5.6-Design-Loop.md appendix E §E.6.2.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


def _canonical_bytes(value: object) -> bytes:
    """Return a stable digest input without allowing non-JSON values through."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return repr(value).encode("utf-8", errors="replace")


def _summary(value: object) -> dict[str, int | str]:
    encoded = _canonical_bytes(value)
    return {
        "payload_bytes": len(encoded),
        "payload_sha256": hashlib.sha256(encoded).hexdigest(),
    }


class AuditLogger:
    """Structured, bounded LLM call audit log.

    默认只记录摘要和 hash，避免把 Prompt、工具输出或模型响应写入生产日志。
    ``debug_full=True`` 才允许记录正文，且单行仍受 ``max_entry_bytes`` 限制。
    """

    def __init__(
        self,
        log_dir: Path,
        *,
        debug_full: bool = False,
        max_entry_bytes: int = 64 * 1024,
        max_log_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        if max_entry_bytes < 256:
            raise ValueError("审计日志单条上限必须至少为 256 字节")
        if max_log_bytes < max_entry_bytes:
            raise ValueError("审计日志文件上限不得小于单条上限")
        self._dir = log_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._dir / "llm-calls.jsonl"
        self._debug_full = debug_full
        self._max_entry_bytes = max_entry_bytes
        self._max_log_bytes = max_log_bytes

    def log_call(
        self,
        *,
        stage: str,
        provider: str,
        model: str,
        request_messages: list[dict],
        request_tools: list[dict] | None,
        response: dict,
        timestamp: str = "",
        duration_ms: int = 0,
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
    ) -> None:
        request_summary: dict[str, Any] = {
            "messages_count": len(request_messages),
            "tools_count": len(request_tools) if request_tools else 0,
            **_summary(request_messages),
        }
        response_summary: dict[str, Any] = {
            "keys": sorted(str(key) for key in response),
            **_summary(response),
        }
        if self._debug_full:
            request_summary["messages"] = request_messages
            if request_tools:
                request_summary["tools"] = request_tools
            response_summary["payload"] = response

        entry: dict[str, Any] = {
            "timestamp": timestamp or time.strftime("%Y-%m-%dT%H:%M:%S"),
            "stage": stage,
            "provider": provider,
            "model": model,
            "request": request_summary,
            "response": response_summary,
            "duration_ms": duration_ms,
            "tokens": {
                "prompt": tokens_prompt,
                "completion": tokens_completion,
                "total": tokens_prompt + tokens_completion,
            },
        }
        self._append(entry)

    def log_event(
        self,
        *,
        event: str,
        stage: str = "",
        tick: int = 0,
        timestamp: str = "",
        **kwargs: object,
    ) -> None:
        """Record a non-LLM event (gate run, convergence, guardrail block, etc.)."""
        entry: dict[str, object] = {
            "timestamp": timestamp or time.strftime("%Y-%m-%dT%H:%M:%S"),
            "event": event,
            "stage": stage,
            "tick": tick,
        }
        entry.update(kwargs)
        self._append(entry)

    def _append(self, entry: dict[str, Any]) -> None:
        encoded = json.dumps(
            entry,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
        if len(encoded) > self._max_entry_bytes:
            encoded = json.dumps(
                {
                    "bounded": True,
                    "stage": entry.get("stage", ""),
                    "event": entry.get("event", ""),
                    "entry_sha256": hashlib.sha256(encoded).hexdigest(),
                    "entry_bytes": len(encoded),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        if self._log_path.exists() and (
            self._log_path.stat().st_size + len(encoded) + 1 > self._max_log_bytes
        ):
            backup = self._log_path.with_name(f"{self._log_path.name}.1")
            if backup.exists():
                backup.unlink()
            self._log_path.replace(backup)
        with open(self._log_path, "ab") as stream:
            stream.write(encoded + b"\n")
