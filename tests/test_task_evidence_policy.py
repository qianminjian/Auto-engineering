"""Phase 81 T428：任务类型决定可接受的 Core 验证证据。"""

from auto_engineering.loop.task_evidence_policy import TaskEvidencePolicy


def _gate(*, status: str, passed: bool | None, message: str = "") -> dict:
    return {"status": status, "passed": passed, "message": message}


def test_business_task_rejects_agent_smoke_claim_without_core_test() -> None:
    verdict = TaskEvidencePolicy().evaluate(
        tasks=[{"id": "B1-T1", "kind": "implementation"}],
        gate_results={"safety": _gate(status="pass", passed=True)},
        test_results_claim={"passed": 1, "failed": 0, "kind": "smoke"},
    )

    assert verdict["status"] == "fail"
    assert verdict["reason_code"] == "authoritative_test_required"


def test_setup_task_accepts_limited_core_smoke_gate() -> None:
    verdict = TaskEvidencePolicy().evaluate(
        tasks=[{"id": "B1-T1", "kind": "project_setup"}],
        gate_results={"build": _gate(status="pass", passed=True)},
        test_results_claim={"passed": 1, "failed": 0},
    )

    assert verdict["status"] == "pass"
    assert verdict["evidence_kind"] == "core_smoke"


def test_missing_toolchain_is_environment_failure_not_code_failure() -> None:
    verdict = TaskEvidencePolicy().evaluate(
        tasks=[{"id": "B1-T1", "kind": "implementation"}],
        gate_results={
            "test": _gate(
                status="fail",
                passed=False,
                message="pnpm 命令未找到",
            )
        },
        test_results_claim={"passed": 1, "failed": 0},
    )

    assert verdict["status"] == "environment_failure"
    assert verdict["reason_code"] == "missing_toolchain_or_manifest"


def test_business_task_accepts_successful_core_test_gate() -> None:
    verdict = TaskEvidencePolicy().evaluate(
        tasks=[{"id": "B1-T1", "kind": "contract_test"}],
        gate_results={"test": _gate(status="pass", passed=True)},
        test_results_claim={"passed": 0, "failed": 0},
    )

    assert verdict["status"] == "pass"
    assert verdict["evidence_kind"] == "core_test"
