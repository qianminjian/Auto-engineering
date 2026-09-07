"""Phase 80 T409：TransitionContext 扩展构造脱离 façade。"""

from __future__ import annotations

import json

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.verification_layers import VerificationLayers
from auto_engineering.loop.transition_context_factory import (
    TransitionContextFactory,
    project_gate_results,
)


def test_developer_context_contains_cursor_and_blocking_gates() -> None:
    batch_state = BatchState.from_batch_plan([
        {"batch_id": "B1", "component": "Core", "tasks": [{"id": "T1"}]},
        {
            "batch_id": "B2",
            "component": "Core",
            "tasks": [{"id": "T2", "description": "实现 B2"}],
            "gate": {"name": "tests"},
        },
    ])
    gate_results = {
        "type_check": {"status": "hard_fail", "passed": False},
        "lint": {"status": "pass", "passed": True},
    }

    extensions = TransitionContextFactory().build(
        "developer",
        batch_state=batch_state,
        verification_layers=VerificationLayers.LEAF,
        max_repair_cycles=6,
        p1_threshold=10,
        gate_results=gate_results,
    )

    assert extensions["completed_batch_id"] == "B1"
    assert extensions["has_more_batches_after_advance"] is True
    assert extensions["next_task"] == "实现 B2"
    assert len(extensions["blocking_gate_results"]) == 1


def test_blocking_gate_feedback_is_bounded_before_next_worker_prompt() -> None:
    """Gate 原始输出不能整体回灌 Developer Prompt。"""
    raw_message = "失败定位\n" + ("详细日志 " * 60_000)
    raw_gate_results = {
        "type_check": {
            "status": "hard_fail",
            "passed": False,
            "message": raw_message,
            "selected_files": [f"src/generated/{index}.py" for index in range(10_000)],
            "files_snapshot_sha": "sha256:test",
            "ran_at": "2026-09-01T00:00:00+00:00",
        },
    }

    blocking = TransitionContextFactory.blocking_gate_results(raw_gate_results)

    assert len(json.dumps(blocking, ensure_ascii=False).encode("utf-8")) < 8_192
    assert blocking == [
        {
            "gate_name": "type_check",
            "status": "hard_fail",
            "passed": False,
            "message": blocking[0]["message"],
            "files_snapshot_sha": "sha256:test",
        },
    ]
    assert len(blocking[0]["message"].encode("utf-8")) < 2_500

    projected = project_gate_results(raw_gate_results)
    assert len(json.dumps(projected, ensure_ascii=False).encode("utf-8")) < 8_192
    assert "selected_files" not in projected["type_check"]
