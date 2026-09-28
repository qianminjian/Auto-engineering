"""Result recovery projection 的 Worker 产物修复合同测试。"""

from __future__ import annotations

from typing import Any

from auto_engineering.cli.result_recovery_projection import (
    project_host_attestation_repair_action,
)


def test_worker_artifact_repair_projection_forbids_respawn() -> None:
    action = {
        "message_id": "action-1",
        "instruction": "执行当前 Action",
        "spawn": {
            "count": 1,
            "invocations": [{"worker_id": "critic-0"}],
        },
        "host_execution": {
            "work_files": {
                "outcomes": ".ae-state/work/outcomes.json",
                "coordinator_result": ".ae-state/work/coordinator.json",
                "result": ".ae-state/work/result.json",
            }
        },
    }
    captured: dict[str, Any] = {}

    def project_result_repair(
        mapped_action: dict[str, Any],
        rejection: dict[str, Any],
    ) -> dict[str, Any]:
        captured["rejection"] = rejection
        return dict(mapped_action)

    projected = project_host_attestation_repair_action(
        action,
        worker_id="critic-0",
        detail="private_artifact_incomplete_native_result_available",
        repair_kind="worker_artifact",
        project_result_repair_action_fn=project_result_repair,
    )

    recovery = projected["host_execution"]["recovery"]
    assert captured["rejection"]["error_code"] == "HOST_WORKER_ARTIFACT_REPAIRABLE"
    assert recovery["status"] == "worker_artifact_repair"
    assert recovery["required_operation"] == "repair_worker_artifact_then_finalize"
    assert recovery["spawn_permitted"] is False
    assert recovery["repair_kind"] == "worker_artifact"
    assert recovery["outcomes_ref"] == (
        ".ae-state/work/outcomes.json"
    )
    assert "spawn" not in projected
    assert "禁止重新启动 Worker" in projected["instruction"]
