"""Phase 80 T409：TransitionContext 扩展构造脱离 façade。"""

from __future__ import annotations

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.verification_layers import VerificationLayers
from auto_engineering.loop.transition_context_factory import TransitionContextFactory


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
