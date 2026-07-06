---
phase: "03"
plan: "agent-prompt"
subsystem: "agents"
tags: ["v5.5", "Superpowers", "prompt-engineering", "code-review", "brainstorming", "TDD", "output-models"]
requires: ["02-orchestrator-extension"]
provides: ["04-three-agent-execution"]
affects: ["agents/prompts", "agents/output_models", "loop/plan", "loop/task_factory"]
tech-stack:
  added: []
  patterns: ["TDD Red-Green-Refactor", "Superpowers code-reviewer.md integration", "Superpowers receiving-code-review 5-step protocol", "Superpowers brainstorming 4-step workflow"]
key-files:
  created:
    - tests/test_prompts_v55.py
  modified:
    - auto_engineering/agents/output_models.py
    - auto_engineering/agents/prompts.py
    - auto_engineering/loop/plan.py
    - auto_engineering/loop/task_factory.py
    - tests/test_output_models.py
    - tests/test_task_factory.py
decisions:
  - "[CriticOutput]: strengths and assessment fields default to None for backward compatibility"
  - "[CriticPrompt]: Superpowers three-tier assessment replaces binary APPROVE/MAJOR with Ready-to-merge / Ready-to-merge: With-fixes / Needs-rework"
  - "[DevPrompt]: 5-step protocol (Read/Understand/Locate/Fix/Verify+Report) replaces simple priority-based Critic feedback handling"
  - "[ArchPrompt]: 3-mode auto-selection (INTERACTIVE/PLAN-REFINE/DESIGN-INTEGRATION) based on TaskContext state"
  - "[BatchPlan]: verification and steps are optional fields, architect populates when known, developer may fill-in otherwise"
  - "[BatchPlan/Task]: verification defaults to None, steps defaults to None — existing batch_plan dicts without these fields work without migration"
metrics:
  duration: "~9.5 min"
  completed_date: "2026-07-07"
---

# Phase 3 Plan 1: Agent Prompt Enhancement (Superpowers Integration) Summary

One-liner: Integrated Superpowers code-reviewer.md, receiving-code-review, and brainstorming skills into Agent system prompts with extended CriticOutput model (strengths + assessment) and batch_plan fields (verification + steps).

## Tasks Executed

| # | Task | Type | Commit | Status |
|---|------|------|--------|--------|
| 3.1 | CriticOutput model extension | feat | 3c72180 | Complete |
| 3.5 | batch_plan field extension | feat | 930e8ba | Complete |
| 3.2 | Critic system prompt rewrite | feat | 17ca7a9 | Complete |
| 3.3 | Developer system prompt enhancement | feat | d35ff6f | Complete |
| 3.4 | Architect system prompt rewrite | feat | 013a811 | Complete |

## Verification Results

- Plan-specified test suite: 164 passed, 0 failed
- Full prompt tests (test_prompts_v55.py): 15 passed across all three agents
- Output model tests (test_output_models.py): 20 passed
- Task factory integration tests (test_task_factory.py): 27 passed
- Agent regression tests (test_agents_3.py, test_cli_agent.py, test_agents_base_llm.py): 98 passed
- Total: 164 + 98 = 262 passed across all test suites

## Deviations from Plan

None — plan executed exactly as written in the specified implementation order (3.1 -> 3.5 -> 3.2 -> 3.3 -> 3.4).

## Key Changes

### CriticOutput (output_models.py)
- Added `strengths: list[dict] | None` — what the implementation did well, format: [{description, location}]
- Added `assessment: str | None` — three-tier verdict: "Ready to merge" / "Ready to merge: With fixes" / "Needs rework"
- Both fields default to None for backward compatibility with existing CriticOutput usage

### Task Model (plan.py) + Task Factory (task_factory.py)
- Added `verification: str | None` to Task — verification command (e.g., "pytest tests/test_xxx.py")
- Added `steps: list[str] | None` to Task — implementation steps (1-2-3 list)
- `_tasks_from_batch_plan` consumes `verification` and `steps` from batch_plan dicts
- ROLE_FIELD_MAP extended for critic: added `strengths` and `assessment`
- ROLE_FIELD_DEFAULTS extended with `strengths: None` and `assessment: None`

### Critic Prompt (CRITIC_SYSTEM_PROMPT)
- Superpowers 7 review dimensions: correctness, security, performance, maintainability, readability, testing, production readiness
- Superpowers "What to Check" checklist and DO/DON'T rules
- Three-tier assessment with strengths-before-findings output ordering
- All existing functionality preserved: verdict enum, P0/P1 checklists, tool permissions, behavior constraints

### Developer Prompt (DEVELOPER_SYSTEM_PROMPT)
- 5-step Critic feedback response protocol: Read -> Understand -> Locate -> Fix -> Verify+Report
- Anti-performative-agreement rules from Superpowers receiving-code-review
- YAGNI check: verify reviewer suggestions before implementing
- All existing TDD RED->GREEN->REFACTOR cycle preserved

### Architect Prompt (ARCHITECT_SYSTEM_PROMPT)
- 3-mode auto-selection: INTERACTIVE (from scratch), PLAN-REFINE (with audit findings), DESIGN-INTEGRATION (extend existing)
- Brainstorming 4-step simplified workflow from Superpowers 9-step
- Batch plan output extended with verification + steps fields
- Agent-Reach MCP reference for external documentation queries
- All existing files precheck, design principles, and output format preserved

## Known Stubs

None. All model fields are fully implemented with Pydantic validation and integration into the task factory pipeline.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries introduced.
