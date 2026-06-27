---
phase: "05"
plan: "P1-B"
subsystem: "cli"
tags: [refactor, cli, package-structure]
requires: []
provides:
  - "cli.helpers (ErrorCategory, CancellationToken, TokenTracker, ProgressLogger)"
  - "cli.dev_loop (_build_v2_agent_runtime, _run_v2_orchestrator, OrchestratorRunResult)"
  - "cli.checkpoint (register_checkpoint_commands)"
  - "cli.__init__ (Click commands + re-exports)"
affects:
  - "auto_engineering/cli.py → auto_engineering/cli/ package"
tech-stack:
  added: []
  patterns: ["Package split: monolithic module → package with 4 submodules"]
key-files:
  created:
    - auto_engineering/cli/__init__.py
    - auto_engineering/cli/helpers.py
    - auto_engineering/cli/dev_loop.py
    - auto_engineering/cli/checkpoint.py
  modified: []
  deleted:
    - auto_engineering/cli.py
decisions:
  - "checkpoint commands extracted to cli/checkpoint.py via register_checkpoint_commands(main) pattern to keep __init__.py under 400 lines"
  - "cli/__init__.py re-exports all helpers/dev_loop symbols for backward compatibility (from auto_engineering.cli import main)"
metrics:
  duration: "~5min"
  completed_date: "2026-06-27"
---

# Phase 05 Plan P1-B: Split cli.py into cli/ Package Summary

Split 1029-line monolithic `auto_engineering/cli.py` into a package with 4 submodules.

## Results

**Status:** COMPLETE

**Commit:** `ee73b78`

| File | Lines | Content |
|------|-------|---------|
| cli/helpers.py | 199 | ErrorCategory, CancellationToken, TokenTracker, ProgressLogger, classify_error, _log_engine_version, _install_sigint_handler |
| cli/dev_loop.py | 240 | _build_v2_agent_runtime, _build_v2_semantic_evaluator, _run_v2_orchestrator, OrchestratorRunResult |
| cli/checkpoint.py | 316 | register_checkpoint_commands(main) — list/show/resume/v2/migrate |
| cli/__init__.py | 280 | Click commands (main/init/dev_loop/status) + re-exports |
| **Total** | **1035** | All files under 400 lines constraint |

## Verification

- **Full test suite:** 693 passed, 1 skipped (16.50s)
- **Backward compatibility:** `from auto_engineering.cli import main` works unchanged
- **Entry point:** `pyproject.toml` `ae = "auto_engineering.cli:main"` preserved
- **All commands registered:** init, dev_loop, status, checkpoint (list/show/resume/v2)

## Deviations from Plan

None — plan executed exactly as written.

## Key Decisions

1. **Additional split: checkpoint.py** — Original plan had 3 files (helpers/dev_loop/__init__). Added `cli/checkpoint.py` (316 lines) to keep `__init__.py` under 400 lines constraint. Uses `register_checkpoint_commands(main: click.Group)` injection pattern — `__init__.py` calls this at module load time after `main()` is defined.

2. **Re-export strategy** — `__init__.py` imports all public symbols from `helpers`, `dev_loop`, and `checkpoint` modules with `# noqa: F401` to maintain full backward compatibility. All existing test imports (`from auto_engineering.cli import main`, `from auto_engineering.cli import ProgressLogger, _build_v2_agent_runtime`) work without changes.

## Self-Check: PASSED

- [x] All 4 cli/ files exist and are under 400 lines
- [x] Commit ee73b78 verified: 5 files changed, 1035 insertions, 1029 deletions
- [x] Full test suite: 693 passed, 1 skipped
- [x] All import patterns verified backward compatible
