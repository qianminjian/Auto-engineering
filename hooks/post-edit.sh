#!/bin/bash
# post-edit.sh — Auto-Engineering post-edit auto-gate (v5.0 §PE.3)
# Triggered: PostToolUse hook (after Edit/Write)
# Behavior: if file is in src/ or auto_engineering/, run `ae gate-check --quick`

set -u

TOOL_INPUT="${1:-${CLAUDE_TOOL_INPUT:-}}"
[[ -z "$TOOL_INPUT" ]] && exit 0

# Extract file path
FILE_PATH=$(echo "$TOOL_INPUT" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    ti=d.get('tool_input',d)
    for k in ['file_path','filepath','path']:
        v=ti.get(k,'')
        if v: print(v); break
except: pass
" 2>/dev/null)

[[ -z "$FILE_PATH" ]] && exit 0

# Only trigger on source code paths
case "$FILE_PATH" in
  *src/*|*/auto_engineering/*|*.py) ;;
  *) exit 0 ;;
esac

# Skip test files (let developer agent own test quality)
case "$FILE_PATH" in
  *test_*.py|*tests/*) exit 0 ;;
esac

# Skip if .venv not present (avoid noise during plugin dev)
[[ ! -x "ae" ]] && exit 0

# Run quick gate
RESULT=$(ae gate-check --quick --json 2>&1) || true

# Always allow — just surface results
if echo "$RESULT" | grep -q '"status":"fail"'; then
  echo "{\"decision\":\"allow\",\"warning\":\"post-edit gate-check reported failures\",\"output\":$(echo "$RESULT" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')}"
else
  echo "{\"decision\":\"allow\"}"
fi
exit 0
