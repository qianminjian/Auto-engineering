"""Phase 60 T286：Prompt rendered 日志不可覆盖且不虚构投递事实。"""

from __future__ import annotations

import json
from pathlib import Path

from auto_engineering.loop.prompt_logger import write_action_prompt_log


def test_same_tick_stage_keeps_each_message_version(tmp_path: Path) -> None:
    base = {
        "action": "architect",
        "stage": "architect",
        "thread_id": "thread-123",
        "tick": 1,
        "instruction": "spawn",
        "subagent_prompt": "architect prompt",
        "expected_format": {"plan": "string"},
    }

    write_action_prompt_log(tmp_path, {**base, "message_id": "msg-1"})
    write_action_prompt_log(tmp_path, {**base, "message_id": "msg-2"})

    files = list((tmp_path / "_scratch" / "prompt-log").iterdir())
    assert len(files) == 4
    assert any("msg-1" in path.name for path in files)
    assert any("msg-2" in path.name for path in files)


def test_rendered_log_does_not_claim_host_delivery(tmp_path: Path) -> None:
    write_action_prompt_log(
        tmp_path,
        {
            "action": "plate_deep_audit",
            "stage": "plate_deep_audit",
            "thread_id": "thread-123",
            "message_id": "msg-1",
            "tick": 8,
            "instruction": "spawn",
            "subagent_prompt": "merge",
            "spawn": {
                "count": 1,
                "agents": [{
                    "index": 0,
                    "role": "architecture",
                    "prompt": "worker prompt",
                    "prompt_hash": "abc123",
                }],
            },
        },
    )

    prompt_path = next(
        (tmp_path / "_scratch" / "prompt-log").glob("*-rendered-*.md")
    )
    text = prompt_path.read_text(encoding="utf-8")
    assert "内核渲染提示词" in text
    assert "未证明宿主已投递" in text
    assert "architecture" in text
    assert "abc123" in text


def test_rendered_artifacts_declare_engine_and_protocol_versions(
    tmp_path: Path,
) -> None:
    write_action_prompt_log(
        tmp_path,
        {
            "action": "developer",
            "stage": "developer",
            "thread_id": "thread-123",
            "message_id": "msg-1",
            "tick": 2,
            "schema_version": "1.1",
            "instruction": "implement",
        },
    )

    log_dir = tmp_path / "_scratch" / "prompt-log"
    payload = json.loads(next(log_dir.glob("*.json")).read_text(encoding="utf-8"))
    markdown = next(log_dir.glob("*.md")).read_text(encoding="utf-8")
    assert payload["_diagnostics"]["engine_version"]
    assert payload["_diagnostics"]["protocol_version"] == "1.1"
    assert "engine version:" in markdown
    assert "protocol version: `1.1`" in markdown


def test_worker_prompt_reference_is_visible_without_reinlining_body(
    tmp_path: Path,
) -> None:
    write_action_prompt_log(
        tmp_path,
        {
            "action": "system_deep_audit",
            "stage": "system_deep_audit",
            "thread_id": "thread-123",
            "message_id": "msg-2",
            "tick": 3,
            "spawn": {
                "agents": [{
                    "index": 0,
                    "role": "security",
                    "prompt_ref": ".ae-state/prompt-artifacts/abc.md",
                    "prompt_hash": "abc",
                }],
            },
        },
    )

    markdown = next(
        (tmp_path / "_scratch" / "prompt-log").glob("*.md")
    ).read_text(encoding="utf-8")
    assert "prompt ref: `.ae-state/prompt-artifacts/abc.md`" in markdown
    assert "0 chars" not in markdown
