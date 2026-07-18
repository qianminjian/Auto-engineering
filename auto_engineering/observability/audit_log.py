"""Structured audit log — JSONL LLM call recording (T61).

Design ref: v5.6-Design-Loop.md appendix E §E.6.2.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


class AuditLogger:
    """Structured audit log — records complete LLM request/response per call.

    Output: JSONL format, one JSON object per line.
    File: <log_dir>/llm-calls.jsonl
    """

    def __init__(self, log_dir: Path) -> None:
        self._dir = log_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._dir / "llm-calls.jsonl"

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
        entry = {
            "timestamp": timestamp or time.strftime("%Y-%m-%dT%H:%M:%S"),
            "stage": stage,
            "provider": provider,
            "model": model,
            "request": {
                "messages_count": len(request_messages),
                "messages": request_messages,
                "tools_count": len(request_tools) if request_tools else 0,
            },
            "response": response,
            "duration_ms": duration_ms,
            "tokens": {
                "prompt": tokens_prompt,
                "completion": tokens_completion,
                "total": tokens_prompt + tokens_completion,
            },
        }
        with open(self._log_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
