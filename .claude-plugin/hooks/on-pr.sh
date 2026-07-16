#!/bin/bash
# on-pr.sh — Auto-Engineering PR body Gate summary (v5.0 §PE.3)
# Triggered: PostToolUse (gh pr create) or manual
# Behavior: collect last gate-check results, append to PR body

set -u

TOOL_INPUT="${1:-${CLAUDE_TOOL_INPUT:-}}"
[[ -z "$TOOL_INPUT" ]] && exit 0

# Detect gh pr create call
if ! echo "$TOOL_INPUT" | grep -q "gh pr create"; then
  exit 0
fi

# Run quick gate to attach to PR body
[[ ! -x "ae" ]] && exit 0

GATE_OUTPUT=$(ae gate-check --quick --json 2>&1) || true

# Format as markdown table
PR_BODY=$(echo "$GATE_OUTPUT" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    gates = data.get('gates', [])
    if not gates:
        print('No gate results available.')
    else:
        print('## Auto-Engineering Gate Results')
        print()
        print('| Gate | Status | Duration |')
        print('|------|--------|----------|')
        for g in gates:
            name = g.get('name', '?')
            status = g.get('status', '?')
            dur = g.get('duration_ms', 0)
            print(f'| {name} | {status} | {dur}ms |')
        print()
        print(f\"_Total: {data.get('summary', 'N/A')}_\")
except Exception as e:
    print(f'Gate summary unavailable: {e}')
" 2>/dev/null || echo "Gate summary unavailable.")

# Surface to stdout — Claude Code will include in tool output
echo "{\"decision\":\"allow\",\"pr_body_addendum\":$(echo "$PR_BODY" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')}"
exit 0
