"""Codex rollout 主/子会话的增量用量采集。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.metrics.transcript_parser import CodexSessionTranscriptParser


def _append(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload) + "\n")


def _meta(
    *, thread_id: str, cwd: Path, parent_thread_id: str | None = None
) -> dict:
    payload: dict[str, object] = {
        "session_id": thread_id,
        "cwd": str(cwd),
        "thread_source": "subagent" if parent_thread_id else "user",
    }
    if parent_thread_id:
        payload["parent_thread_id"] = parent_thread_id
    return {"type": "session_meta", "payload": payload}


def _usage(input_tokens: int, cached: int, output: int) -> dict:
    return {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": cached,
                    "cache_write_input_tokens": 0,
                    "output_tokens": output,
                }
            },
        },
    }


def test_codex_parser_aggregates_parent_and_children_and_ignores_unrelated(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / "sessions" / "2026" / "08" / "21"
    parent_id = "parent-thread"
    parent = sessions / f"rollout-{parent_id}.jsonl"
    child = sessions / "rollout-child.jsonl"
    unrelated = sessions / "rollout-unrelated.jsonl"
    _append(parent, _meta(thread_id=parent_id, cwd=project))
    _append(parent, {"type": "turn_context", "payload": {"model": "gpt-test"}})
    _append(parent, _usage(1000, 800, 100))
    _append(child, _meta(
        thread_id=parent_id, cwd=project, parent_thread_id=parent_id
    ))
    _append(child, _usage(500, 400, 50))
    _append(unrelated, _meta(
        thread_id="other", cwd=project, parent_thread_id="other"
    ))
    _append(unrelated, _usage(9999, 0, 9999))

    parser = CodexSessionTranscriptParser(
        project, thread_id=parent_id, sessions_root=tmp_path / "sessions"
    )

    result = parser.collect()

    assert result["input_tokens"] == 300
    assert result["cache_read_tokens"] == 1200
    assert result["output_tokens"] == 150
    assert result["model"] == "gpt-test"
    assert result["message_count"] == 2


def test_codex_parser_reports_only_positive_cumulative_delta(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = tmp_path / "sessions" / "2026" / "08" / "21"
    thread_id = "parent-thread"
    parent = sessions / f"rollout-{thread_id}.jsonl"
    _append(parent, _meta(thread_id=thread_id, cwd=project))
    _append(parent, _usage(1000, 800, 100))
    parser = CodexSessionTranscriptParser(
        project, thread_id=thread_id, sessions_root=tmp_path / "sessions"
    )
    first = parser.collect()
    assert first["input_tokens"] == 200

    _append(parent, _usage(1400, 1100, 140))
    second = parser.collect()

    assert second["input_tokens"] == 100
    assert second["cache_read_tokens"] == 300
    assert second["output_tokens"] == 40
    assert parser.collect()["input_tokens"] == 0
