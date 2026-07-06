---
phase: "4"
plan: "1"
name: "学习系统"
subsystem: "loop-learning"
type: "feature"
autonomous: true
tags: [learning, threshold, auto-tune, cold-start, jsonl]
depends_on:
  requires: [phase-1-deep-audit-gate, phase-2-orchestrator-extension]
  provides: [threshold-learning, max-iter-adaptive]
  affects: [convergence, orchestrator]
tech-stack:
  added: []
  patterns: [JSONL-audit-history, 3-consistent-auto-tune, cold-start-guard]
key-files:
  created: []
  modified:
    - auto_engineering/loop/orchestrator.py
    - auto_engineering/loop/threshold_learner.py
    - auto_engineering/loop/convergence.py
    - tests/test_orchestrator_v55.py
    - tests/test_threshold_learner.py
    - tests/test_loop_convergence.py
decisions:
  - "_run_deep_audit() now writes JSONL audit history after every audit run"
  - "_get_p1_threshold() returns cold-start default 6, extensible for Phase 5+ ThresholdLearner integration"
  - "auto_tune_threshold() uses 3-consecutive-consistent P1 counts before recommending new threshold"
  - "auto_tune_max_iter() cold-start guard: returns None when entries < min_samples_for_learning"
  - "min_samples_for_learning in ConvergenceConfig is the single source for cold-start threshold"
metrics:
  duration: "~17 min"
  completed_date: "2026-07-07"
---

# Phase 4 Plan 1: 学习系统 Summary

**One-liner:** P1 threshold auto-learning with 3-consistent detection, max_iter adaptive tuning, and JSONL audit history integration

## Tasks Completed

| # | Type | Name | Commit | Files |
|---|------|------|--------|-------|
| 4.1 | auto | JSONL 日志写入集成 | 02b91b1 | orchestrator.py, test_orchestrator_v55.py |
| 4.2 | auto | 统计算法完善 (auto_tune_threshold) | e305afd | threshold_learner.py, test_threshold_learner.py |
| 4.3 | auto | auto_tune 模式 + 冷启动 | 3bf9ee3 | convergence.py, test_loop_convergence.py |

## Implementation Details

### Task 4.1: JSONL 日志写入集成

- Added `_get_p1_threshold()` method to Orchestrator returning cold-start default of 6
- In `_run_deep_audit()`, after gate evaluation, writes an `AuditHistory.append_entry()` call with p0/p1/p2 counts, threshold, total files, and plan_refine_triggered flag
- `.ae-state/` directory auto-created via `AuditHistory.append_entry()`

### Task 4.2: 统计算法完善

- Added `auto_tune_threshold(current: int) -> int | None` to ThresholdLearner
- Algorithm: reads last 3 entries, checks if P1 counts are all identical, if so computes p75 via `compute_p1_threshold()` and validates via `should_adjust()`
- Returns None when: insufficient entries (< 3), P1 counts not all same, or change >50%
- Confirmed boundary: `compute_p1_threshold()` already returns `max(int(p75), 1)`

### Task 4.3: auto_tune + 冷启动

- Added `auto_tune_max_iter(audit_history) -> int | None` to ConvergenceJudge
- Cold start guard: entries < `config.min_samples_for_learning` (default 5) returns None
- Sufficient samples: delegates to `ThresholdLearner.compute_max_iter()` returning `min(avg_rounds * 2, 20)`
- Confirmed `min_samples_for_learning: int = 5` exists in ConvergenceConfig (Phase 2 Task 2.4)
- Confirmed semantic_evaluator model name is correct: `claude-haiku-4-5-20251001`

## Verification

**Test command:** `.venv/bin/pytest tests/test_threshold_learner.py tests/test_audit_history.py tests/ -k "convergence or auto_tune or threshold" -v --no-cov --timeout=60`

**Result:** 113 passed, 1 pre-existing failure (test_derive_status_with_real_engine_state — `_derive_status` removed from stage_router.py, not caused by this phase)

**TDD compliance:** Each task followed RED (failing test) -> GREEN (minimal implementation) -> REFACTOR (not needed, implementations minimal)

## Deviations from Plan

None - plan executed exactly as written. All three tasks completed in order.

## Self-Check

- [x] All created/modified files exist on disk
- [x] All commits exist in git log (6 commits: 02b91b1, e305afd, 3bf9ee3 + 3 RED commits)
- [x] All tests pass (except pre-existing issue)
- [x] No secrets, keys, or sensitive data in any file

## Known Stubs

None introduced. The implemented methods are fully functional using the existing AuditHistory JSONL backend and ThresholdLearner statistical computations.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries were introduced.

<!-- gsd:write-continue -->
