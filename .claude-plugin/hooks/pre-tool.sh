#!/bin/bash
# pre-tool.sh — Auto-Engineering tool-call safety guard (v5.0 §B12.2 + §B12.3)
# Triggered: PreToolUse hook
# Input: JSON via $CLAUDE_TOOL_INPUT (tool name + arguments)
# Output: JSON {"decision":"allow|block","reason":"..."} to stdout
# Refuses: 13 denylist patterns + file-sandbox escape (dual realpath)

set -u

# Read tool input (Claude Code passes as $1 or stdin)
TOOL_INPUT="${1:-${CLAUDE_TOOL_INPUT:-}}"

if [[ -z "$TOOL_INPUT" ]]; then
  echo '{"decision":"allow","reason":"no tool input"}'
  exit 0
fi

# Extract tool name (best effort — JSON parse with python fallback)
TOOL_NAME=$(echo "$TOOL_INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null || echo "")

# Extract command for Bash tool, or file path for Edit/Write
extract_arg() {
  local key="$1"
  echo "$TOOL_INPUT" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    # try tool_input.command, then tool_input.file_path, then tool_input.path
    ti=d.get('tool_input', d)
    for k in ['$key','command','file_path','path','filepath']:
        v=ti.get(k,'')
        if v: print(v); break
except: pass
" 2>/dev/null
}

# --- 13-pattern denylist (v5.0 §B12.2) ---
# Use literal text in single quotes; escape special regex chars with backslash
DENYLIST_PATTERNS=(
  'rm -rf /'
  'rm -rf ~'
  'rm -rf .'
  'mkfs.'
  'dd if=/dev/(zero|random|urandom)'
  ':(){:|:&};:'                # fork bomb (literal)
  'shutdown '
  'reboot '
  'halt '
  'chmod -R 777 /'
  'curl | bash'                # curl pipe to bash (literal)
  'wget | bash'                # wget pipe to bash (literal)
  '> /etc/(passwd|shadow|sudoers)'  # system file overwrite
)

check_denylist() {
  local input="$1"
  for pat in "${DENYLIST_PATTERNS[@]}"; do
    # Use fixed-string matching via fgrep to avoid regex engine quirks on macOS
    # (Claude Code wraps grep with ugrep which treats () specially)
    if echo "$input" | grep -qF -- "$pat" 2>/dev/null || echo "$input" | /usr/bin/grep -qE -- "$pat" 2>/dev/null; then
      echo "{\"decision\":\"block\",\"reason\":\"denylist pattern matched: $pat\"}"
      exit 0
    fi
  done
}

# --- File sandbox check (v5.0 §B12.3) ---
# Allowed: project root + .ae-state + /tmp
check_sandbox() {
  local target_path="$1"
  [[ -z "$target_path" ]] && return 0

  # Resolve to absolute path (follows symlinks for proper check on macOS)
  local abs
  abs=$(python3 -c "import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))" "$target_path" 2>/dev/null) || abs="$target_path"

  # macOS: /tmp is a symlink to /private/tmp — normalize both forms
  case "$abs" in
    /private/tmp/*)  abs="/tmp/${abs#/private/tmp/}" ;;
    /private/var/folders/*/T/*) abs="/var/folders/${abs#/private/var/folders/}" ;;
  esac

  # Allowed roots
  local project_root
  project_root=$(python3 -c "import os; print(os.path.realpath('.'))")

  local allowed=1
  case "$abs" in
    "$project_root"/*) allowed=1 ;;
    "$project_root")   allowed=1 ;;
    /tmp/*)             allowed=1 ;;
    /var/folders/*/T/*) allowed=1 ;;  # macOS temp
    "$HOME"/.ae-state/*) allowed=1 ;;  # global ae state
    *)                  allowed=0 ;;
  esac

  if [[ $allowed -eq 0 ]]; then
    echo "{\"decision\":\"block\",\"reason\":\"path outside sandbox: $abs (project_root=$project_root)\"}"
    exit 0
  fi
}

# Dispatch by tool type
case "$TOOL_NAME" in
  Bash)
    ARG=$(extract_arg "command")
    check_denylist "$ARG"
    ;;
  Edit|Write|MultiEdit|Read)
    ARG=$(extract_arg "file_path")
    check_sandbox "$ARG"
    ;;
  *)
    # Unknown tool — allow
    ;;
esac

echo '{"decision":"allow"}'
exit 0
