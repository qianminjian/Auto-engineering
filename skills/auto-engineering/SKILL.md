---
name: auto-engineering
description: >
  Loop Engineering 调度脚手架 — Tick-Based Discrete Invocation loop
  (architect → developer → critic → 5-layer verification).
  Use when the user asks to implement a feature, run a dev loop,
  check loop status, manage checkpoints, or run gate checks.
---

# Auto-Engineering v5.6 — Tick-Based Agent Loop

Claude Code Plugin that implements a Python-gated, Agent-executed development loop.
The **Python engine is the deterministic gatekeeper** (StageRouter → Guardrail → Gate
→ ConvergenceJudge → Checkpoint). The **Agent (you) is the LLM executor** — you drive
the loop by following the action JSON produced by each `ae dev-loop --tick` call.

## Hard Constraints (v5.6 Tick Protocol)

<!-- FRAGMENT:iron_law_gatekeeper START -->
When executing dev-loop:

1. MUST invoke `ae dev-loop --init "<requirement>"` first — Python initializes state
2. MUST invoke `ae dev-loop --tick --result <file>` after each stage — Python validates
3. MUST NOT edit code before Python outputs `{"action":"developer"}`
4. MUST NOT declare completion before Python outputs `{"action":"done"}`
5. If Python rejects a result (`{"action":"error"}`), read error message and fix
6. MUST commit after each developer batch (Guardrail: working tree must be clean)
7. All gate results are decided by Python — do not skip or fake gates
<!-- FRAGMENT:iron_law_gatekeeper END -->

## When to Use Which Command

| User intent | Command |
|-------------|---------|
| Implement a feature | `/dev-loop "requirement"` |
| Check loop progress | `/status` |
| Manage checkpoints | `/checkpoint list|show|delete|resume` |
| Fast TDD cycle | `/project-tdd "requirement"` |
| Isolated experiment | `/project-worktree "requirement"` |
| Single agent query | `/project-agent <role> <instruction>` |
| Run CI gates | `/project-ci` |

## Role execution — Subagent isolation

This loop uses **Claude Code built-in subagents** (Plan / code-reviewer / general-purpose)
for context isolation across roles. These are platform-native capabilities — not external
dependencies. The B14 external-dependency ban applies only to external-framework agents
(gsd-* / superpowers-*).

- **developer**: Main agent (you) — only role with cross-tick context coherence
- **architect**: `subagent_type="Plan"` (Sonnet)
- **critic**: `subagent_type="code-reviewer"` (Sonnet)
- **component_verifier**: `subagent_type="general-purpose"` (Haiku)
- **plate_deep_audit**: 3× `subagent_type="code-reviewer"` (Sonnet, parallel)
- **system_verifier**: `subagent_type="general-purpose"` (Haiku)
- **system_deep_audit**: 3× `subagent_type="code-reviewer"` (Sonnet, parallel)

MCP tools and search skills are information gathering tools — allowed as research aids,
not as execution delegates.

## References

- `commands/dev-loop.md` — Full tick protocol and action reference
- `design/v5.6-Design-Loop.md` — Architecture and stage specification
- `design/BEACON.md` — Design decisions (#39/#40/#41/#64) and current state
