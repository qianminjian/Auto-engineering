"""Phase 80 T408：ActionCompiler 纯度。"""

from __future__ import annotations

from auto_engineering.loop.action_compiler import (
    ActionCompiler,
    ActionIdentity,
)
from auto_engineering.loop.runtime_revision import RuntimeRevision


def _revision() -> RuntimeRevision:
    return RuntimeRevision(
        protocol_version="1.1",
        event_schema_version="1.0",
        projection_schema_version="1.0",
        action_contract_version="1.0",
        prompt_revision="prompt",
        policy_revision="policy",
        engine_build_id="rc.6",
    )


def test_same_explicit_inputs_produce_identical_action_drafts(tmp_path) -> None:
    compiler = ActionCompiler()
    payload = {
        "action": "developer",
        "thread_id": "thread-1",
        "tick": 2,
        "stage": "developer",
        "instruction": "实现当前任务",
    }
    identity = ActionIdentity(
        message_id="action-2",
        correlation_id="thread-1",
        causation_id="result-1",
    )
    before = list(tmp_path.rglob("*"))

    first = compiler.compile(
        payload=payload,
        identity=identity,
        runtime_revision=_revision(),
        issued_at="2026-08-09T00:00:00+00:00",
    )
    second = compiler.compile(
        payload=payload,
        identity=identity,
        runtime_revision=_revision(),
        issued_at="2026-08-09T00:00:00+00:00",
    )

    assert first == second
    assert first.payload["message_id"] == "action-2"
    assert first.payload["extensions"]["ae"]["runtime_revision"] == _revision().to_dict()
    assert list(tmp_path.rglob("*")) == before
    assert payload.get("extensions") is None
