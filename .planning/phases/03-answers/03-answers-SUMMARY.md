---
phase: 03-answers
plan: 02
subsystem: init
tags: [python, dataclass, ChainMap, yaml, lazy-loading, tdd]

# Dependency graph
requires:
  - phase: 01-env
    provides: [pyyaml dependency, test infrastructure]
  - phase: 02-errors-config
    provides: [TemplateConfig, Question types]
provides:
  - AnswersMap with 6-layer priority ChainMap (cli_overrides > interactive > previous > defaults > builtins > external)
  - _LazyExternalDict with lazy YAML/JSON loading and caching
  - save_partial/from_answers_file round-trip for interrupt recovery
  - write_to/to_answers_file for .ae-answers.yml serialization
affects: [03-prompts, 04-renderer, 05-scaffold, 06-environment]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy loading pattern: _LazyExternalDict loads YAML/JSON only on first __getitem__ access, caches result"
    - "ChainMap priority stack: cli_overrides > interactive > previous > defaults > builtins > external"
    - "TDD Red-Green-Refactor: tests committed first, then implementation"

key-files:
  created:
    - tests/test_answers.py - 53 tests with 100% coverage of answers.py
  modified:
    - auto_engineering/init/answers.py - rewritten from 78 to 167 lines (6 layers + _LazyExternalDict)

key-decisions:
  - "_LazyExternalDict as separate internal class rather than embedding lazy logic in AnswersMap"
  - "External data injected as _external_data key in combined() dict for Jinja2 template access"
  - "None values in layers treated as 'not set', continuing to lower-priority lookup"
  - "JSON loading supported via json module, other suffixes fall back to yaml.safe_load"

patterns-established:
  - "Test-first: all 53 tests written and confirmed FAIL before any implementation"
  - "100% coverage: every code path tested including JSON fallback, missing file, caching"

requirements-completed: []

# Metrics
duration: 5min
completed: 2026-06-24
---

# Phase 03: AnswersMap 6-layer ChainMap with Lazy External Data Loading

**6-layer AnswersMap with _LazyExternalDict for lazy YAML/JSON external data injection, 53 TDD tests at 100% coverage**

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-24T00:15:00+08:00
- **Completed:** 2026-06-24T00:16:05+08:00
- **Tasks:** 1
- **Files modified:** 2 (1 created, 1 rewritten)

## Accomplishments

- Extended AnswersMap from 5 to 6 layers: added `external: dict[str, str]` field and `_external_cache` for lazy file loading
- Implemented `_LazyExternalDict` class supporting YAML (.yml/.yaml) and JSON (.json) files with on-first-access loading and caching
- `combined()` injects `_external_data` as a lazy-loading dict — files are only read when their keys are first accessed
- All existing API preserved: `get()`, `combined()`, `hide()`, `save_partial()`, `from_answers_file()`, `to_answers_file()`, `write_to()`, `__getitem__`, `__contains__`
- 53 unit tests with 100% statement coverage on `answers.py`

## Task Commits

Each TDD phase was committed atomically:

1. **RED: Test creation** - `d4e5b46` (test) — 53 failing tests importing non-existent `_LazyExternalDict`
2. **GREEN: Implementation** - `1c3c41a` (feat) — Rewrote answers.py with 6-layer AnswersMap + _LazyExternalDict

## Files Created/Modified

- `tests/test_answers.py` - 53 tests covering BUILTIN_VARS, construction, get() priority chain, combined() with lazy _external_data, _load_external() caching, hide(), save_partial(), from_answers_file(), to_answers_file() filtering, write_to(), __getitem__/__contains__, and full _LazyExternalDict behavior
- `auto_engineering/init/answers.py` - Rewritten from 78 lines (5 layers, no external) to 167 lines (6 layers, _LazyExternalDict, JSON support, lazy loading)

## Decisions Made

- Extracted `_LazyExternalDict` as a separate internal class rather than embedding lazy-loading logic directly in AnswersMap — keeps the dataclass clean and the lazy dict reusable
- `combined()` injects `_external_data` as the `_LazyExternalDict` instance rather than eagerly loading all files — consistent with the "only load on first access" design principle
- `_load_external` returns `None` for missing files rather than raising an exception — allows templates to handle `_external_data.key is none` gracefully

## Deviations from Plan

None — plan executed exactly as written. The 6-layer design, _LazyExternalDict, and all methods match the spec in `design/v1.0-INIT.md` §1.3.3.

## Issues Encountered

None.

## Next Phase Readiness

- AnswersMap is ready for Phase 03 (prompts.py — InteractivePrompt) which depends on `AnswersMap.combined()` for rendering context
- All existing imports from `auto_engineering.init.answers` remain backward compatible

---
*Phase: 03-answers*
*Completed: 2026-06-24*
