REMOVED: # Auto-Engineering Plugin — Usage Guide
REMOVED: 
REMOVED: > **Version**: 5.0.0 | **Status**: Production-ready | **Last updated**: 2026-07-01
REMOVED: 
REMOVED: Auto-Engineering v5.0 is a multi-agent AI engineering loop with stage-aware guardrails, a 7-gate quality system, and a v2 SQLite checkpoint persistence layer. As a Claude Code plugin, it exposes 8 slash commands, 5 lifecycle hooks, and 1 skill.
REMOVED: 
REMOVED: ---
REMOVED: 
REMOVED: ## 1. Installation
REMOVED: 
REMOVED: ### 1.1 Prerequisites
REMOVED: 
REMOVED: - **Python** ≥ 3.10
REMOVED: - **uv** ≥ 0.1.0 (package manager — install from [astral-sh/uv](https://github.com/astral-sh/uv))
REMOVED: - **git** ≥ 2.30
REMOVED: - **sqlite3** ≥ 3.35 (CLI tool, for inspecting checkpoint DB)
REMOVED: - **Claude Code** ≥ 1.0.0
REMOVED: - **ANTHROPIC_API_KEY** environment variable
REMOVED: 
REMOVED: ### 1.2 Steps
REMOVED: 
REMOVED: ```bash
REMOVED: # 1. Clone or copy the plugin into your target project
REMOVED: cd ~/path/to/your-project
REMOVED: cp -r /path/to/auto-engineering/.claude-plugin ./
REMOVED: 
REMOVED: # 2. Provision the Python environment (one-time)
REMOVED: cd /path/to/your-project
REMOVED: uv sync                           # creates .venv, installs deps
REMOVED: 
REMOVED: # 3. Set API key
REMOVED: 
REMOVED: # 4. Restart Claude Code to load the plugin
REMOVED: #    (close and reopen the Claude Code session)
REMOVED: ```
REMOVED: 
REMOVED: ### 1.3 Verify installation
REMOVED: 
REMOVED: In Claude Code, type:
REMOVED: 
REMOVED: ```
REMOVED: /help
REMOVED: ```
REMOVED: 
REMOVED: You should see 8 new slash commands prefixed with `/ae:`:
REMOVED: 
REMOVED: - `/ae:dev-loop`
REMOVED: - `/ae:status`
REMOVED: - `/ae:checkpoint`
REMOVED: - `/ae:project-tdd`
REMOVED: - `/ae:project-worktree`
REMOVED: - `/ae:project-agent`
REMOVED: - `/ae:project-ci`
REMOVED: 
REMOVED: (7 commands — `/init` is provided by the Init subsystem, not the plugin.)
REMOVED: 
REMOVED: ---
REMOVED: 
REMOVED: ## 2. Slash Commands
REMOVED: 
REMOVED: ### 2.1 `/ae:dev-loop` — Run the dev-loop
REMOVED: 
REMOVED: Launches the full multi-agent loop on a requirement.
REMOVED: 
REMOVED: ```
REMOVED: /ae:dev-loop "Add OAuth2 login flow" --max-rounds 20
REMOVED: /ae:dev-loop --resume
REMOVED: ```
REMOVED: 
REMOVED: ### 2.2 `/ae:status` — Inspect loop state
REMOVED: 
REMOVED: ```
REMOVED: /ae:status
REMOVED: /ae:status --json
REMOVED: /ae:status --verbose
REMOVED: ```
REMOVED: 
REMOVED: ### 2.3 `/ae:checkpoint` — Manage checkpoints
REMOVED: 
REMOVED: ```
REMOVED: /ae:checkpoint list
REMOVED: /ae:checkpoint list --round 3
REMOVED: /ae:checkpoint show --id ckpt-001
REMOVED: /ae:checkpoint resume --id ckpt-001
REMOVED: /ae:checkpoint delete --id ckpt-001
REMOVED: ```
REMOVED: 
REMOVED: ### 2.4 `/ae:project-tdd` — Run TDD cycle
REMOVED: 
REMOVED: ```
REMOVED: /ae:project-tdd "validate email format"
REMOVED: /ae:project-tdd "add retry to API client" --module auto_engineering/api
REMOVED: ```
REMOVED: 
REMOVED: ### 2.5 `/ae:project-worktree` — Create isolated worktree
REMOVED: 
REMOVED: ```
REMOVED: /ae:project-worktree feat/oauth-login
REMOVED: /ae:project-worktree fix/memory-leak --base develop
REMOVED: ```
REMOVED: 
REMOVED: ### 2.6 `/ae:project-agent` — Invoke single agent
REMOVED: 
REMOVED: ```
REMOVED: /ae:project-agent architect "design REST API for user management"
REMOVED: /ae:project-agent developer "implement retry logic" --context src/api.py
REMOVED: /ae:project-agent critic "review the auth refactor PR"
REMOVED: ```
REMOVED: 
REMOVED: ### 2.7 `/ae:project-ci` — Run full CI
REMOVED: 
REMOVED: ```
REMOVED: /ae:project-ci                # all gates
REMOVED: /ae:project-ci --quick        # lint + type_check + test only
REMOVED: /ae:project-ci --fix          # auto-fix what can be auto-fixed
REMOVED: ```
REMOVED: 
REMOVED: ---
REMOVED: 
REMOVED: ## 3. Lifecycle Hooks
REMOVED: 
REMOVED: The plugin installs 5 hooks (all chmod +x):
REMOVED: 
REMOVED: | Hook | Trigger | Purpose |
REMOVED: |------|---------|---------|
REMOVED: | `session-start.sh` | SessionStart | Environment precheck (uv/python/git/ANTHROPIC_API_KEY) |
REMOVED: | `pre-tool.sh` | PreToolUse | Block dangerous commands (13 denylist patterns) + file sandbox |
REMOVED: | `post-edit.sh` | PostToolUse (Edit/Write) | Auto-run `ae gate-check --quick` on src/ changes |
REMOVED: | `stop.sh` | Stop | Mark running checkpoint as interrupted on session end |
REMOVED: | `on-pr.sh` | PostToolUse (gh pr create) | Append Gate results to PR body |
REMOVED: 
REMOVED: ---
REMOVED: 
REMOVED: ## 4. Environment Variables
REMOVED: 
REMOVED: | Var | Default | Description |
REMOVED: |-----|---------|-------------|
REMOVED: | `AE_DB_PATH` | `.ae-state/checkpoints.db` | SQLite checkpoint database path |
REMOVED: | `AE_LOG_LEVEL` | `INFO` | Engine log level (DEBUG/INFO/WARN/ERROR) |
REMOVED: | `AE_GATE_TIMEOUT` | `300` | Gate execution timeout (seconds) |
REMOVED: 
REMOVED: ---
REMOVED: 
REMOVED: ## 5. Troubleshooting
REMOVED: 
REMOVED: ### 5.1 Slash commands not registered
REMOVED: 
REMOVED: **Symptom**: `/help` doesn't show `/ae:*` commands.
REMOVED: 
REMOVED: **Causes & fixes**:
REMOVED: - Plugin not installed → `cp -r .claude-plugin TARGET/.claude-plugin/`
REMOVED: - Claude Code not restarted → close & reopen the session
REMOVED: - Wrong location → plugin must be at `<project>/.claude-plugin/` (not nested)
REMOVED: 
REMOVED: ### 5.2 `ae_cli: missing`
REMOVED: 
REMOVED: **Cause**: `ae` doesn't exist.
REMOVED: 
REMOVED: **Fix**:
REMOVED: ```bash
REMOVED: uv sync
REMOVED: ae doctor    # should pass all checks
REMOVED: ```
REMOVED: 
REMOVED: ### 5.3 `ANTHROPIC_API_KEY: missing`
REMOVED: 
REMOVED: **Cause**: API key not exported in current shell.
REMOVED: 
REMOVED: **Fix**:
REMOVED: ```bash
REMOVED: echo $ANTHROPIC_API_KEY | head -c 8   # verify
REMOVED: ```
REMOVED: 
REMOVED: ### 5.4 `denylist pattern matched`
REMOVED: 
REMOVED: **Cause**: A `Bash` tool call matched one of 13 dangerous patterns (e.g., `rm -rf /`).
REMOVED: 
REMOVED: **Fix**: use a safer variant (e.g., `rm -rf ./build/` not `rm -rf /`).
REMOVED: 
REMOVED: ### 5.5 `path outside sandbox`
REMOVED: 
REMOVED: **Cause**: Tried to edit a file outside the project root.
REMOVED: 
REMOVED: **Fix**: stay within the project root or use absolute paths under `/tmp/`.
REMOVED: 
REMOVED: ### 5.6 Loop stuck or hung
REMOVED: 
REMOVED: **Symptom**: dev-loop doesn't progress after several minutes.
REMOVED: 
REMOVED: **Fix**:
REMOVED: ```bash
REMOVED: # 1. Inspect state
REMOVED: ae status
REMOVED: 
REMOVED: # 2. Save interrupted checkpoint
REMOVED: ae checkpoint save interrupted
REMOVED: 
REMOVED: # 3. Resume from latest
REMOVED: /ae:dev-loop --resume
REMOVED: ```
REMOVED: 
REMOVED: ---
REMOVED: 
REMOVED: ## 6. Uninstalling
REMOVED: 
REMOVED: ```bash
REMOVED: # Remove plugin from project
REMOVED: rm -rf .claude-plugin/
REMOVED: 
REMOVED: # Remove .venv and ae-state
REMOVED: rm -rf .venv .ae-state/
REMOVED: 
REMOVED: # Restart Claude Code
REMOVED: ```
REMOVED: 
REMOVED: ---
REMOVED: 
REMOVED: ## 7. Reference
REMOVED: 
REMOVED: - `ae-plugin-acceptance-test.sh` — runs 3 acceptance scenarios
REMOVED: - `design/v5.0-Design-Loop.md` — Engine design spec
REMOVED: - `_scratch/v5.0-refactor-plan.md` — refactor plan (模块 10)
REMOVED: - `skills/auto-engineering/SKILL.md` — in-conversation skill reference
