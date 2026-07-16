# Auto-Engineering Plugin — Usage Guide

> **Version**: 5.6.0 | **Status**: Production-ready | **Last updated**: 2026-07-16

Auto-Engineering v5.6 is a Tick-Based Discrete Invocation loop engine with 5-layer verification pipeline, 9-guardrail system, and SQLite checkpoint persistence. As a Claude Code plugin, it exposes 7 slash commands, 5 lifecycle hooks, and 1 skill.

---

## 1. Installation

### 1.1 Prerequisites

- **Python** ≥ 3.10
- **uv** ≥ 0.1.0 (package manager — install from [astral-sh/uv](https://github.com/astral-sh/uv))
- **git** ≥ 2.30
- **sqlite3** ≥ 3.35 (CLI tool, for inspecting checkpoint DB)
- **Claude Code** ≥ 1.0.0
- **ANTHROPIC_API_KEY** environment variable (or ANTHROPIC_AUTH_TOKEN in Plugin mode)

### 1.2 Steps

```bash
# 1. Clone or copy the plugin into your target project
cd ~/path/to/your-project
cp -r /path/to/auto-engineering/.claude-plugin ./

# 2. Provision the Python environment (one-time)
cd /path/to/your-project
uv sync                           # creates .venv, installs deps

# 3. Set API key (optional — Plugin mode uses Claude Code agent's OAuth token)

# 4. Restart Claude Code to load the plugin
#    (close and reopen the Claude Code session)
```

### 1.3 Verify installation

In Claude Code, type:

```
/help
```

You should see 7 slash commands prefixed with `/ae:`:

- `/ae:dev-loop`
- `/ae:status`
- `/ae:checkpoint`
- `/ae:project-tdd`
- `/ae:project-worktree`
- `/ae:project-agent`
- `/ae:project-ci`

(7 commands — `/init` is provided by the Init subsystem, not the plugin.)

---

## 2. Slash Commands

### 2.1 `/ae:dev-loop` — Run the dev-loop

Launches the full multi-agent Tick-Based loop on a requirement.

```
/ae:dev-loop "Add OAuth2 login flow" --max-rounds 20
/ae:dev-loop --init                  # Initialize tick loop
/ae:dev-loop --tick --result result.json  # Submit tick result
/ae:dev-loop --resume                # Resume from checkpoint
```

### 2.2 `/ae:status` — Inspect loop state

```
/ae:status
/ae:status --json
/ae:status --verbose
```

### 2.3 `/ae:checkpoint` — Manage checkpoints

```
/ae:checkpoint list
/ae:checkpoint list --round 3
/ae:checkpoint show --id ckpt-001
/ae:checkpoint resume --id ckpt-001
/ae:checkpoint delete --id ckpt-001
```

### 2.4 `/ae:project-tdd` — Run TDD cycle

```
/ae:project-tdd "validate email format"
/ae:project-tdd "add retry to API client" --module auto_engineering/api
```

### 2.5 `/ae:project-worktree` — Create isolated worktree

```
/ae:project-worktree feat/oauth-login
/ae:project-worktree fix/memory-leak --base develop
```

### 2.6 `/ae:project-agent` — Invoke single agent

```
/ae:project-agent architect "design REST API for user management"
/ae:project-agent developer "implement retry logic" --context src/api.py
/ae:project-agent critic "review the auth refactor PR"
```

### 2.7 `/ae:project-ci` — Run full CI

```
/ae:project-ci                # all gates
/ae:project-ci --quick        # lint + type_check + test only
/ae:project-ci --fix          # auto-fix what can be auto-fixed
```

---

## 3. Lifecycle Hooks

The plugin installs 5 hooks (all chmod +x):

| Hook | Trigger | Purpose |
|------|---------|---------|
| `session-start.sh` | SessionStart | Environment precheck (uv/python/git/ANTHROPIC_API_KEY) |
| `pre-tool.sh` | PreToolUse | Block dangerous commands (13 denylist patterns) + file sandbox |
| `post-edit.sh` | PostToolUse (Edit/Write) | Auto-run `ae gate-check --quick` on src/ changes |
| `stop.sh` | Stop | Mark running checkpoint as interrupted on session end |
| `on-pr.sh` | PostToolUse (gh pr create) | Append Gate results to PR body |

---

## 4. Environment Variables

| Var | Default | Description |
|-----|---------|-------------|
| `AE_DB_PATH` | `.ae-state/checkpoints.db` | SQLite checkpoint database path |
| `AE_LOG_LEVEL` | `INFO` | Engine log level (DEBUG/INFO/WARN/ERROR) |
| `AE_GATE_TIMEOUT` | `300` | Gate execution timeout (seconds) |
| `AE_NO_GATES` | `false` | Skip 7-gate system (3-level convergence) |
| `AE_MAX_ITERATIONS` | `20` | Max tick loop iterations |

---

## 5. Troubleshooting

### 5.1 Slash commands not registered

**Symptom**: `/help` doesn't show `/ae:*` commands.

**Causes & fixes**:
- Plugin not installed → `cp -r .claude-plugin TARGET/.claude-plugin/`
- Claude Code not restarted → close & reopen the session
- Wrong location → plugin must be at `<project>/.claude-plugin/` (not nested)

### 5.2 `ae_cli: missing`

**Cause**: `ae` doesn't exist.

**Fix**:
```bash
uv sync
ae doctor    # should pass all checks
```

### 5.3 `ANTHROPIC_API_KEY: missing`

**Cause**: API key not exported in current shell (CLI mode).

**Fix**: Plugin mode uses Claude Code agent's OAuth token automatically. For CLI mode:
```bash
echo $ANTHROPIC_API_KEY | head -c 8   # verify
```

### 5.4 `denylist pattern matched`

**Cause**: A `Bash` tool call matched one of 13 dangerous patterns (e.g., `rm -rf /`).

**Fix**: use a safer variant (e.g., `rm -rf ./build/` not `rm -rf /`).

### 5.5 `path outside sandbox`

**Cause**: Tried to edit a file outside the project root.

**Fix**: stay within the project root or use absolute paths under `/tmp/`.

### 5.6 Loop stuck or hung

**Symptom**: dev-loop doesn't progress after several minutes.

**Fix**:
```bash
# 1. Inspect state
ae dev-loop --status --format json

# 2. Resume from latest checkpoint
ae dev-loop --resume
```

---

## 6. Uninstalling

```bash
# Remove plugin from project
rm -rf .claude-plugin/

# Remove .venv and ae-state
rm -rf .venv .ae-state/

# Restart Claude Code
```

---

## 7. Reference

- `ae-plugin-acceptance-test.sh` — runs 20 acceptance scenarios
- `design/v5.6-Design-Loop.md` — Engine design spec (Tick-Based protocol + 5-layer verification)
- `design/BEACON.md` — Design baseline (goals, scope, decisions)
- `docs/api-reference.md` — Full API reference
- `skills/auto-engineering/SKILL.md` — in-conversation skill reference
