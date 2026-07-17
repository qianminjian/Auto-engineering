#!/bin/bash
# session-start.sh — Auto-Engineering environment precheck (v5.0 §PE.3)
# Triggered: SessionStart hook
# Output: JSON {"status":"ok|degraded|error","checks":{...}} to stdout

set -u
# NOTE: do NOT use set -e — we want to report all check results, not fail-fast

# ── V8-2: Multi-platform detection ──
if [[ -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
  export AE_PLATFORM="claude-code"
  export AE_PLUGIN_ROOT="$CLAUDE_PLUGIN_ROOT"
elif [[ -n "${CODEX_PLUGIN_ROOT:-}" ]]; then
  export AE_PLATFORM="codex"
  export AE_PLUGIN_ROOT="$CODEX_PLUGIN_ROOT"
elif [[ -n "${CODEBUDDY_PLUGIN_ROOT:-}" ]]; then
  export AE_PLATFORM="codebuddy"
  export AE_PLUGIN_ROOT="$CODEBUDDY_PLUGIN_ROOT"
else
  export AE_PLATFORM="unknown"
  export AE_PLUGIN_ROOT=""
fi

CHECKS_JSON=""

# ── Auto-bootstrap: run uv sync if venv/ae not installed ──
_bootstrap() {
  if [[ ! -x ".venv/bin/ae" ]] && command -v uv >/dev/null 2>&1; then
    uv sync --quiet 2>/dev/null || uv sync 2>/dev/null || true
  fi
  # Ensure ae is on PATH for this session
  if [[ -d ".venv/bin" ]]; then
    export PATH="$PWD/.venv/bin:$PATH"
  fi
}

check_command() {
  local name="$1"
  local cmd="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    local version
    version=$("$cmd" --version 2>/dev/null | head -1 || echo "unknown")
    CHECKS_JSON="$CHECKS_JSON\"$name\":\"ok\",\"${name}_version\":\"$version\","
  else
    CHECKS_JSON="$CHECKS_JSON\"$name\":\"missing\","
  fi
}

check_env() {
  local name="$1"
  local desc="$2"
  if [[ -n "${!name:-}" ]]; then
    # Mask all but first/last 4 chars for safety
    local val="${!name}"
    local masked
    if [[ ${#val} -gt 8 ]]; then
      masked="${val:0:4}...${val: -4}"
    else
      masked="***"
    fi
    CHECKS_JSON="$CHECKS_JSON\"$name\":\"set\",\"${name}_masked\":\"$masked\","
  else
    CHECKS_JSON="$CHECKS_JSON\"$name\":\"missing\","
  fi
}

# 0. Bootstrap Python environment before checking
_bootstrap

# 1. Python
check_command "python" "python3"

# 2. uv (package manager)
check_command "uv" "uv"

# 3. git
check_command "git" "git"

# 4. sqlite3
check_command "sqlite3" "sqlite3"

# 5. Plugin mode detection (2026-07-04 P0-2)
# 4 级 fallback 与 auto_engineering.utils.plugin_mode.detect_plugin_mode 对齐:
#   CLAUDE_CODE / CLAUDE_CODE_ENTRYPOINT / ANTHROPIC_CLI(含claude) / ANTHROPIC_AUTH_TOKEN
PLUGIN_SIGNAL=""
PLUGIN_MODE=false
if [[ -n "${CLAUDE_CODE:-}" ]]; then
    PLUGIN_SIGNAL="CLAUDE_CODE"
    PLUGIN_MODE=true
elif [[ -n "${CLAUDE_CODE_ENTRYPOINT:-}" ]]; then
    PLUGIN_SIGNAL="CLAUDE_CODE_ENTRYPOINT"
    PLUGIN_MODE=true
elif [[ -n "${ANTHROPIC_CLI:-}" ]] && echo "${ANTHROPIC_CLI}" | grep -qi "claude"; then
    PLUGIN_SIGNAL="ANTHROPIC_CLI (claude substring)"
    PLUGIN_MODE=true
elif [[ -n "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
    PLUGIN_SIGNAL="ANTHROPIC_AUTH_TOKEN"
    PLUGIN_MODE=true
fi

if [[ "${PLUGIN_MODE}" == "true" ]]; then
    CHECKS_JSON="$CHECKS_JSON\"plugin_mode\":\"enabled\",\"plugin_signal\":\"${PLUGIN_SIGNAL}\","
else
    CHECKS_JSON="$CHECKS_JSON\"plugin_mode\":\"disabled\","
fi

# 6. LLM credentials (2026-07-04 P0-2 适配 plugin mode)
# Plugin mode 下 ANTHROPIC_API_KEY 不必需 (OAuth 透传), 用 plugin_signal 替代.
# CLI 调试模式下仍检查 ANTHROPIC_API_KEY.
if [[ "${PLUGIN_MODE}" == "true" ]]; then
    # plugin mode: 用 ANTHROPIC_AUTH_TOKEN (OAuth) 替代
    check_env "ANTHROPIC_AUTH_TOKEN" "Anthropic OAuth token (Claude Code Plugin)"
    CHECKS_JSON="$CHECKS_JSON\"api_key_mode\":\"plugin_oauth\","
else
    check_env "ANTHROPIC_API_KEY" "Anthropic API key"
    CHECKS_JSON="$CHECKS_JSON\"api_key_mode\":\"standalone\","
fi

# 7. .ae-state directory
if [[ -d ".ae-state" ]]; then
  CHECKS_JSON="$CHECKS_JSON\"ae_state\":\"present\","
else
  CHECKS_JSON="$CHECKS_JSON\"ae_state\":\"missing\","
fi

# 8. .venv
if [[ -d ".venv" ]]; then
  CHECKS_JSON="$CHECKS_JSON\"venv\":\"present\","
else
  CHECKS_JSON="$CHECKS_JSON\"venv\":\"missing\","
fi

# 9. ae (in .venv)
if [[ -x ".venv/bin/ae" ]]; then
  CHECKS_JSON="$CHECKS_JSON\"ae_cli\":\"ok\","
else
  CHECKS_JSON="$CHECKS_JSON\"ae_cli\":\"missing\","
fi

# Remove trailing comma, wrap in braces
CHECKS_JSON="${CHECKS_JSON%,}"
CHECKS_JSON="{$CHECKS_JSON}"

# Determine overall status (2026-07-04 P0-2: plugin mode 适配)
# - plugin mode enabled → plugin_oauth → ANTHROPIC_API_KEY missing 不算 error
# - plugin mode disabled → standalone → ANTHROPIC_API_KEY missing 算 degraded
if echo "$CHECKS_JSON" | grep -q '"missing"' && echo "$CHECKS_JSON" | grep -qE '"(python|uv|ae_cli)":"missing"'; then
  STATUS="error"
elif echo "$CHECKS_JSON" | grep -q '"missing"' && [[ "${PLUGIN_MODE}" == "false" ]]; then
  # CLI 模式 + 缺 key → degraded
  STATUS="degraded"
elif echo "$CHECKS_JSON" | grep -q '"missing"' && [[ "${PLUGIN_MODE}" == "true" ]]; then
  # Plugin 模式 + 缺 ANTHROPIC_AUTH_TOKEN 但有其他 plugin signal → degraded
  # (Plugin signal 都齐, 但 OAuth token 可能没注入)
  STATUS="degraded"
else
  STATUS="ok"
fi

echo "{\"status\":\"$STATUS\",\"checks\":$CHECKS_JSON}"

exit 0
