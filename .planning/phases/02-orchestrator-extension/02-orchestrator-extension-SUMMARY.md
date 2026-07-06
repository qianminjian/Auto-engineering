---
phase: "02"
plan: "orchestrator-extension"
subsystem: "orchestrator"
tags: ["v5.5", "DeepAudit", "T9", "PLAN-REFINE", "EngineState", "StageRouter", "ConvergenceConfig"]
requires: ["01-deep-audit-gate"]
provides: ["03-plan-refine-architect"]
affects: ["orchestrator", "stage_router", "convergence", "engine_state", "task_factory"]
tech-stack:
  added: []
  patterns: ["TDD Red-Green-Refactor", "StageRouter transition table extension"]
key-files:
  created:
    - tests/test_orchestrator_v55.py
  modified:
    - auto_engineering/engine/state.py
    - auto_engineering/loop/stage_router.py
    - auto_engineering/loop/orchestrator.py
    - auto_engineering/loop/convergence.py
    - auto_engineering/loop/task_factory.py
    - tests/test_engine_state.py
    - tests/test_stage_router.py
    - tests/test_loop_convergence.py
    - tests/test_task_factory.py
    - tests/test_loop_orchestrator.py
decisions:
  - "[T9]: DeepAudit issues route back to architect for PLAN-REFINE, skip ConvergenceJudge"
  - "[T9-LIMIT]: plan_refine_count >= max_plan_refines triggers hard stop"
  - "[Severity]: LLM severity labels mapped to P0/P1/P2 in task_factory before state write"
  - "[DocSync]: _sync_design_docs skeleton defers full implementation to Phase 3+"
  - "[clear_stage_fields]: Fixed None-default skip bug (was `if default is not None`)"
metrics:
  duration: "~15 min"
  completed_date: "2026-07-07"
---

# Phase 2 Plan 1: Orchestrator Integration + EngineState Extension Summary

One-liner: Integrated DeepAuditGate into the Orchestrator 12-step main loop with T9 PLAN-REFINE routing, extended EngineState with 4 v5.5 fields, and added severity mapping for LLM findings.

## Tasks Executed

| # | Task | Type | Commit | Status |
|---|------|------|--------|--------|
| 2.0 | EngineState field expansion | feat | e7121f3 | Complete |
| 2.1 | StageRouter T9 transitions | feat | f287de5 | Complete |
| 2.4 | ConvergenceConfig extension | feat | 33211ed | Complete |
| 2.3b | Severity mapping in task_factory | feat | 8c1d4f9 | Complete |
| 2.2+2.3+2.6 | Orchestrator DeepAudit + T9 + DocSync | feat | 08b5b7d | Complete |
| 2.5 | Phase 2 integration tests | test | 0a354e2 | Complete |

## Changes Made

### EngineState (v5.5 B1.1 fields 18-21)
- `audit_findings: list[dict] | None` — DeepAudit findings, consumed by architect PLAN-REFINE
- `plan_refine_count: int = 0` — T9 loop counter, separate from MAJOR counts
- `strengths: list[str] | None` — CriticOutput extension
- `assessment: str | None` — CriticOutput extension
- Field count: 17 → 21

### StageRouter T9/T9-LIMIT
- `next()` new params: `audit_found_issues`, `plan_refine_count`, `max_plan_refines`
- T9: `audit_found_issues=True + under limit` → route to architect (PLAN-REFINE)
- T9-LIMIT: `plan_refine_count >= max_plan_refines` → hard stop
- Backward compatible: defaults preserve T4 behavior

### Orchestrator 12-Step Loop Extensions
- Step 2i: `_sync_design_docs()` skeleton (Phase 2 log-only, Phase 3+ full implementation)
- Step 2j: `_run_deep_audit()` — calls DeepAuditOrchestrator + DeepAuditGate
- Step 2k: T9 routing — if audit_found_issues, skip ConvergenceJudge, route to architect
- Helper: `_all_gates_passed()` — checks all gate verdicts from RoundResult

### ConvergenceConfig Extension
- `auto_tune: bool = False` — max_iter automatic learning
- `max_plan_refines: int = 3` — T9 loop limit
- `min_samples_for_learning: int = 5` — cold start minimum samples

### Severity Mapping
- `_SEVERITY_MAP`: Critical→P0, Important→P1, Minor→P2
- Applied in `apply_outcome_to_state()` for critic role findings
- Unknown labels pass through unchanged

### Bug Fix
- `clear_stage_fields()`: Fixed None-default skip — was `if default is not None` preventing None-valued defaults from being set

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] clear_stage_fields None-default skip**
- **Found during:** Task 2.0 REFACTOR (test_clear_architect_fields)
- **Issue:** `if default is not None` caused None defaults (audit_findings) to never be cleared
- **Fix:** Changed to `if field_name in ROLE_FIELD_DEFAULTS` check
- **Files modified:** `auto_engineering/loop/stage_router.py`
- **Commit:** e7121f3

**2. [Rule 1 - Bug] Field count assertions outdated**
- **Found during:** Task 2.0 GREEN
- **Issue:** `test_all_18_fields_exist` and `test_field_count_is_18` expected 17/18 fields, now 21
- **Fix:** Updated assertions to reflect v5.5 field count (21)
- **Files modified:** `tests/test_engine_state.py`, `tests/test_stage_router.py`
- **Commit:** e7121f3

## Threat Flags

None — no new network endpoints, auth paths, or trust boundary changes introduced.

## Known Stubs

| Stub | File | Line | Reason |
|------|------|------|--------|
| `_sync_design_docs()` log-only | orchestrator.py | ~860 | Full doc sync implementation deferred to Phase 3+ |
| `DeepAuditOrchestrator.run_audit()` returns empty | deep_audit.py | 58 | Real 3-agent LLM audit deferred to Phase 5+ |

## Self-Check: PASSED

- [x] All 6 tasks have commits on `main` branch
- [x] 429 existing tests pass (0 new regressions)
- [x] 16 new integration tests pass
- [x] 6 pre-existing failures identified (guardrail block, checkpoint deserialization, derive_status — all at baseline)
- [x] Created files verified on disk
- [x] All commits verified in git log
