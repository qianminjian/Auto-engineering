# Auto-Engineering Plugin — Usage Guide

> **Version**: 5.0.0 | **Status**: Production-ready | **Last updated**: 2026-07-01

Auto-Engineering v5.0 is a multi-agent AI engineering loop with stage-aware guardrails, a 7-gate quality system, and a v2 SQLite checkpoint persistence layer. As a Claude Code plugin, it exposes 8 slash commands, 5 lifecycle hooks, and 1 skill.

---

## 1. Installation

### 1.1 Prerequisites

- **Python** ≥ 3.10
- **uv** ≥ 0.1.0 (package manager — install from [astral-sh/uv](https://github.com/astral-sh/uv))
- **git** ≥ 2.30
- **sqlite3** ≥ 3.35 (CLI tool, for inspecting checkpoint DB)
- **Claude Code** ≥ 1.0.0
- **ANTHROPIC_API_KEY** environment variable

### 1.2 Steps

```bash
# 1. Clone or copy the plugin into your target project
cd ~/path/to/your-project
cp -r /path/to/auto-engineering/.claude-plugin ./

# 2. Provision the Python environment (one-time)
cd /path/to/your-project
uv sync                           # creates .venv, installs deps

# 3. Set API key
export ANTHROPIC_API_KEY="sk-ant-..."

# 4. Restart Claude Code to load the plugin
#    (close and reopen the Claude Code session)
```

### 1.3 Verify installation

In Claude Code, type:

```
/help
```

You should see 8 new slash commands prefixed with `/ae:`:

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

Launches the full multi-agent loop on a requirement.

```
/ae:dev-loop "Add OAuth2 login flow" --max-rounds 20
/ae:dev-loop --resume
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
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key for Claude API |
| `AE_DB_PATH` | `.ae-state/checkpoints.db` | SQLite checkpoint database path |
| `AE_LOG_LEVEL` | `INFO` | Engine log level (DEBUG/INFO/WARN/ERROR) |
| `AE_GATE_TIMEOUT` | `300` | Gate execution timeout (seconds) |

---

## 5. Troubleshooting

### 5.1 Slash commands not registered

**Symptom**: `/help` doesn't show `/ae:*` commands.

**Causes & fixes**:
- Plugin not installed → `cp -r .claude-plugin TARGET/.claude-plugin/`
- Claude Code not restarted → close & reopen the session
- Wrong location → plugin must be at `<project>/.claude-plugin/` (not nested)

### 5.2 `ae_cli: missing`

**Cause**: `.venv/bin/ae` doesn't exist.

**Fix**:
```bash
uv sync
.venv/bin/ae doctor    # should pass all checks
```

### 5.3 `ANTHROPIC_API_KEY: missing`

**Cause**: API key not exported in current shell.

**Fix**:
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
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
.venv/bin/ae status

# 2. Save interrupted checkpoint
.venv/bin/ae checkpoint save interrupted

# 3. Resume from latest
/ae:dev-loop --resume
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

- `ae-plugin-acceptance-test.sh` — runs 3 acceptance scenarios
- `design/v5.0-Design-Loop.md` — Engine design spec
- `_scratch/v5.0-refactor-plan.md` — refactor plan (模块 10)
- `.claude-plugin/skills/auto-engineering/SKILL.md` — in-conversation skill reference
