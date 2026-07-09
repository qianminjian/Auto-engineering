---
name: auto-engineering
description: Multi-agent AI engineering loop with stage-aware guardrails, Gate quality system, and Init-Loop contract
---

# Auto-Engineering Skill

This skill encapsulates the Auto-Engineering v5.0 plugin's domain knowledge. Use it whenever the user mentions "auto-engineering", "dev-loop", "multi-agent development", or invokes any `/ae:*` slash command.

## When to use

- User wants to run a multi-agent dev-loop on a requirement
- User wants to inspect/manage checkpoints
- User wants to invoke a single agent (architect/developer/critic)
- User wants to run TDD on a specific task
- User wants to run the full CI gate suite
- User wants to create an isolated git worktree for parallel work

## How to use

1. **Check environment first**: invoke `bash .claude-plugin/hooks/session-start.sh` to confirm `uv` and `.venv/bin/ae` are present.
2. **Map user intent to a slash command**:

   | User intent | Slash command |
   |-------------|---------------|
   | "Run dev-loop on X" | `/ae:dev-loop X` |
   | "Show loop status" | `/ae:status` |
   | "Manage checkpoints" | `/ae:checkpoint list\|show\|resume\|delete` |
   | "TDD on X" | `/ae:project-tdd X` |
   | "Create worktree" | `/ae:project-worktree BRANCH` |
   | "Single agent" | `/ae:project-agent ROLE TASK` |
   | "Run CI" | `/ae:project-ci` |

3. **Respect the loop state**: if `ae status` shows a loop is already running, ask the user before starting a new one.
4. **Stream JSON output**: commands emit JSONL events — surface them in chat for transparency.

## Constraints

- **Environment**: requires Python ≥3.10, `uv ≥0.1.0`, `git ≥2.30`, `sqlite3 ≥3.35`.
- **Project root**: must be invoked from inside a project with `.venv/bin/ae` provisioned. Otherwise commands fail with `ae_cli: missing`.
- **Resource budget**: 16G physical memory cap — see `pytest-memory-management` rule. Plugin does NOT run pytest directly; it delegates to `ae gate-check`.
- **Sandbox**: pre-tool hook blocks writes outside project root + `.ae-state/` + `/tmp/` (see `pre-tool.sh` denylist).
- **Network**: plugin does NOT make outbound network calls except via the Engine's `anthropic` SDK (Claude Code auto-injects credentials).
- **State**: v2 SQLite checkpoint DB at `.ae-state/checkpoints.db` (overridable via `AE_DB_PATH`).
- **Plugin compatibility**: requires Claude Code ≥ `1.0.0` (per `plugin.json` metadata).

## Key files

| File | Purpose |
|------|---------|
| `plugin.json` | Plugin manifest (name, version, commands, hooks, skills) |
| `commands/*.md` | 7 slash command definitions |
| `hooks/*.sh` | 5 lifecycle hooks (chmod +x) |
| `SKILL.md` | This file |
| `docs/PLUGIN-USAGE.md` | User-facing install + usage guide |
| `ae-plugin-acceptance-test.sh` | Acceptance test (3 scenarios) |

## Failure modes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `/ae:*` not registered | Plugin not loaded | `cp -r .claude-plugin/ TARGET/.claude-plugin/`, restart Claude Code, `/help` |
| `ae_cli: missing` | `.venv` not provisioned | `uv sync` |
| `API credentials missing` | Claude Code not running | Run inside Claude Code session (SDK auto-injects credentials) |
| `denylist pattern matched` | Bash command refused | Use safer command variant |
| `path outside sandbox` | File write outside project | Stay within project root |

## See also

- `docs/PLUGIN-USAGE.md` — full install + usage
- `_scratch/v5.0-refactor-plan.md` — design spec (模块 10) *(已迁移到 design/v5.6-Design-Loop.md)*
- `ae-plugin-acceptance-test.sh` — acceptance test
