"""v5.8 T324：修复循环、Worker 与深审计预算。"""

from auto_engineering.loop.loop_budget import (
    LoopBudgetPolicy,
    LoopUsage,
    evaluate_loop_budget,
)

POLICY = LoopBudgetPolicy(
    policy_id="loop-budget-v1",
    max_repair_cycles=6,
    max_workers_per_stage=5,
    max_workers_per_thread=50,
    max_plate_audits=3,
    max_system_audits=3,
)


def test_worker_stage_and_thread_limits_fail_closed() -> None:
    stage = evaluate_loop_budget(POLICY, LoopUsage(
        repair_cycles=0,
        requested_workers=6,
        completed_workers=0,
        plate_audits=0,
        system_audits=0,
    ))
    thread = evaluate_loop_budget(POLICY, LoopUsage(
        repair_cycles=0,
        requested_workers=2,
        completed_workers=49,
        plate_audits=0,
        system_audits=0,
    ))

    assert stage.error_code == "WORKER_STAGE_LIMIT"
    assert thread.error_code == "WORKER_THREAD_LIMIT"


def test_repair_and_deep_audit_limits_fail_closed() -> None:
    repair = evaluate_loop_budget(POLICY, LoopUsage(
        repair_cycles=6,
        requested_workers=1,
        completed_workers=10,
        plate_audits=0,
        system_audits=0,
    ))
    plate = evaluate_loop_budget(POLICY, LoopUsage(
        repair_cycles=0,
        requested_workers=3,
        completed_workers=10,
        plate_audits=3,
        system_audits=0,
        next_stage="plate_deep_audit",
    ))

    assert repair.error_code == "REPAIR_CYCLE_LIMIT"
    assert plate.error_code == "PLATE_AUDIT_LIMIT"


def test_below_loop_limits_continues() -> None:
    assert evaluate_loop_budget(POLICY, LoopUsage(
        repair_cycles=2,
        requested_workers=3,
        completed_workers=12,
        plate_audits=1,
        system_audits=1,
        next_stage="developer",
    )).allowed
