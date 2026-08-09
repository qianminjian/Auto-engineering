"""Phase 80 T411：跨运行时长轨迹与双宿主执行语义。"""

from __future__ import annotations

from auto_engineering.host.driver_contract import HostDriverDecision, decide_host_step
from auto_engineering.loop.action_compiler import ActionCompiler, ActionIdentity
from auto_engineering.loop.runtime_revision import (
    CompatibilityDecision,
    RuntimeRevision,
    evaluate_compatibility,
)


def _revision(prompt: str, build: str) -> RuntimeRevision:
    return RuntimeRevision(
        protocol_version="1.1",
        event_schema_version="1.0",
        projection_schema_version="1.0",
        action_contract_version="1.0",
        prompt_revision=prompt,
        policy_revision="policy-1",
        engine_build_id=build,
    )


def test_150_tick_cross_version_trajectory_has_no_capacity_stop() -> None:
    old = _revision("prompt-old", "rc.5")
    new = _revision("prompt-new", "rc.6")
    active = old
    compiler = ActionCompiler()
    host_traces: dict[str, list[HostDriverDecision]] = {
        "claude": [],
        "codex": [],
    }

    for tick in range(1, 151):
        if tick == 76:
            assert evaluate_compatibility(
                issued=active,
                current=new,
                has_active_action=True,
            ) is CompatibilityDecision.ACTIVATE_AFTER_ACTION
            # 上一 Action 的 Result 已被接受后，才在新 Action 边界激活。
            active = new
        draft = compiler.compile(
            payload={
                "action": "developer",
                "thread_id": "thread-long",
                "tick": tick,
                "stage": "developer",
                "instruction": f"执行确定性批次 {tick}",
            },
            identity=ActionIdentity(
                message_id=f"action-{tick}",
                correlation_id="thread-long",
                causation_id=f"result-{tick - 1}" if tick > 1 else None,
            ),
            runtime_revision=active,
            issued_at=f"2026-08-09T00:{tick // 60:02d}:{tick % 60:02d}+00:00",
        )
        for host in host_traces:
            host_traces[host].append(decide_host_step(draft.payload))

    assert host_traces["claude"] == host_traces["codex"]
    assert set(host_traces["claude"]) == {HostDriverDecision.EXECUTE_NEXT}
    assert len(host_traces["claude"]) == 150
    assert active is new
