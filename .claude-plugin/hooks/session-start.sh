#!/bin/bash
# session-start.sh — Auto-Engineering environment precheck (v5.0 §PE.3)
# Triggered: SessionStart hook
# Output: JSON {"status":"ok|degraded|error","checks":{...}} to stdout

set -u
# NOTE: do NOT use set -e — we want to report all check results, not fail-fast

CHECKS_JSON=""

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

# 1. Python
check_command "python" "python3"

# 2. uv (package manager)
check_command "uv" "uv"

# 3. git
check_command "git" "git"

# 4. sqlite3
check_command "sqlite3" "sqlite3"

# 5. ANTHROPIC_API_KEY
check_env "ANTHROPIC_API_KEY" "Anthropic API key"

# 6. .ae-state directory
if [[ -d ".ae-state" ]]; then
  CHECKS_JSON="$CHECKS_JSON\"ae_state\":\"present\","
else
  CHECKS_JSON="$CHECKS_JSON\"ae_state\":\"missing\","
fi

# 7. .venv
if [[ -d ".venv" ]]; then
  CHECKS_JSON="$CHECKS_JSON\"venv\":\"present\","
else
  CHECKS_JSON="$CHECKS_JSON\"venv\":\"missing\","
fi

# 8. .venv/bin/ae
if [[ -x ".venv/bin/ae" ]]; then
  CHECKS_JSON="$CHECKS_JSON\"ae_cli\":\"ok\","
else
  CHECKS_JSON="$CHECKS_JSON\"ae_cli\":\"missing\","
fi

# Remove trailing comma, wrap in braces
CHECKS_JSON="${CHECKS_JSON%,}"
CHECKS_JSON="{$CHECKS_JSON}"

# Determine overall status
if echo "$CHECKS_JSON" | grep -q '"missing"' && echo "$CHECKS_JSON" | grep -qE '"(python|uv|ae_cli)":"missing"'; then
  STATUS="error"
elif echo "$CHECKS_JSON" | grep -q '"missing"'; then
  STATUS="degraded"
else
  STATUS="ok"
fi

echo "{\"status\":\"$STATUS\",\"checks\":$CHECKS_JSON}"

exit 0
