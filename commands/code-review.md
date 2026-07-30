---
name: code-review
description: Create a GitHub PR with gate results, critic findings, and diff summary
---

# /auto-engineering:code-review — 经授权创建 Pull Request

Create a well-structured GitHub PR after dev-loop completes with Critic APPROVE.
Collects gate results, critic findings, and diff summary into the PR body for human peer review.

## Agent Behavioral Constraints

<!-- FRAGMENT:red_flags START -->
## Red Flags — STOP，不要继续，向用户报告

- 我正准备在 Python 输出 {"action":"developer"} 前编辑代码
- 我正准备在 Python 输出 {"action":"done"} 前宣布完成
- 命令执行失败了，我正准备静默切换到手工模式继续
- 宿主原生子代理能力不可用，我正准备自己手工模拟这个 stage
- 我正准备跳过 --tick 自己推进到下一个 stage
- critic 返回 MAJOR，我正准备忽略 findings 直接进收敛

以上任何一条都意味着：停止。向用户报告失败原因 + 状态 + 选项。禁止静默降级。
<!-- FRAGMENT:red_flags END -->

## Usage

```
/auto-engineering:code-review
/auto-engineering:code-review --base main
/auto-engineering:code-review --draft
```

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--base` | main | Target branch for PR |
| `--draft` | false | Create as draft PR |

## Prerequisites Check

Before creating PR, verify:

1. 当前用户消息明确授权本次 `push` 和创建 PR。
2. `gh` CLI is installed and authenticated: `gh auth status`
3. Current branch has unpushed commits: `git log origin/$(git branch --show-current)..HEAD --oneline`
4. Critic has APPROVED: `ae-run status --format json`

`CURRENT_USER_GIT_AUTHORIZATION_REQUIRED`：执行下方写操作前，Agent 必须从当前用户
消息获得明确授权。不得从历史消息、宿主能力或 loop 完成状态推断授权；授权缺失时
只报告当前分支、验证结果和待授权操作，然后停止。

## Execution

```bash
set -euo pipefail

BASE="main"
DRAFT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      BASE="$2"
      shift 2
      ;;
    --draft)
      DRAFT="--draft"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

# Step 1: Pre-flight checks
echo "=== Pre-flight checks ==="

# Check gh CLI
if ! command -v gh &> /dev/null; then
  echo "Error: GitHub CLI (gh) is not installed."
  echo "Install: brew install gh && gh auth login"
  exit 1
fi

if ! gh auth status &> /dev/null; then
  echo "Error: GitHub CLI not authenticated. Run: gh auth login"
  exit 1
fi

# Check critic status
STATUS_JSON=$(ae-run status --format json 2>/dev/null || echo '{"verdict":""}')
VERDICT=$(echo "$STATUS_JSON" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('verdict',''))" 2>/dev/null || echo "")

if [[ "$VERDICT" != "APPROVE" ]]; then
  echo "Error: Critic has not APPROVED yet (verdict=$VERDICT)."
  echo "Run /auto-engineering:dev-loop first, or check /auto-engineering:status for details."
  exit 1
fi

echo "Critic: APPROVED"

# Check for unpushed commits
BRANCH=$(git branch --show-current)
UNPUSHED=$(git log "origin/$BRANCH..HEAD" --oneline 2>/dev/null | wc -l | tr -d ' ')
if [[ "$UNPUSHED" -eq 0 ]]; then
  echo "Warning: No unpushed commits on branch '$BRANCH'."
  echo "Nothing to create PR for."
  exit 1
fi

echo "Unpushed commits: $UNPUSHED"

# Step 2: Collect PR body content
echo ""
echo "=== Collecting PR context ==="

# Gate results
# Phase 40: gate-check CLI 已删除。Gate 在 dev-loop 内自动运行。使用共享 resolver 查询状态。
GATE_OUTPUT=$(ae-run status --format json 2>&1 || echo '{"gates":[]}')
GATE_TABLE=$(echo "$GATE_OUTPUT" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    gates = data.get('gates', [])
    if not gates:
        print('| (no gate results) | - | - |')
    else:
        # Header
        print('| Gate | Status | Message |')
        print('|------|--------|---------|')
        for g in gates:
            name = g.get('name', '?')
            status = g.get('status', '?')
            msg = g.get('message', '')[:100]
            emoji = 'PASS' if status == 'pass' else ('CRASH' if status == 'crashed' else 'FAIL')
            print(f'| {name} | {emoji} | {msg} |')
except Exception as e:
    print(f'Gate summary error: {e}')
" 2>/dev/null)

# Diff summary
DIFF_STAT=$(git diff "$BASE...HEAD" --stat 2>/dev/null | tail -1 || echo "N/A")
DIFF_FILES=$(git diff "$BASE...HEAD" --name-only 2>/dev/null | head -20)
COMMITS=$(git log "$BASE...HEAD" --oneline 2>/dev/null | head -10)

# Step 3: Construct PR title and body
# Title: use the first commit message or requirement
PR_TITLE=$(git log "$BASE...HEAD" --oneline --format="%s" 2>/dev/null | head -1 || echo "Auto-Engineering: Code changes")

# Status info for header
ROUNDS=$(echo "$STATUS_JSON" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('round',0))" 2>/dev/null || echo "?")
THREAD_ID=$(echo "$STATUS_JSON" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('thread_id',''))" 2>/dev/null || echo "")

# Step 4: Push and create PR
echo ""
echo "=== Pushing and creating PR ==="

# CURRENT_USER_GIT_AUTHORIZATION_REQUIRED:
# 只有当前用户消息明确授权 push + create PR 时才可执行以下两条写操作。
git push -u origin "$BRANCH" 2>&1 || {
  echo "Error: Failed to push to origin/$BRANCH"
  exit 1
}

PR_URL=$(gh pr create \
  --title "$PR_TITLE" \
  --base "$BASE" \
  --head "$BRANCH" \
  $DRAFT \
  --body "$(cat <<PRBODY
## AI Dev-Loop Summary

**Status**: APPROVED by Critic | **Rounds**: ${ROUNDS} | **Thread**: \`${THREAD_ID}\`

### Gate Results

${GATE_TABLE}

### Changes

\`\`\`
${DIFF_STAT}
\`\`\`

**Files changed**:
\`\`\`
${DIFF_FILES}
\`\`\`

### Commits

\`\`\`
${COMMITS}
\`\`\`

### Human Review Checklist

- [ ] Core logic is correct for the requirement
- [ ] No security risks introduced (secrets, injection, unsafe I/O)
- [ ] Test coverage is adequate (check CI results below)
- [ ] Architecture is consistent with existing codebase
- [ ] No dead code, debug statements, or leftover TODOs

---
Generated by Auto-Engineering v5.8 | [Review docs](https://github.com/qianminjian/Auto-engineering)
PRBODY
)" 2>&1)

echo ""
echo "=== PR Created ==="
echo "$PR_URL"
```

## Post-Creation

After PR is created:
1. The `on-pr.sh` hook automatically appends additional gate details
2. CI workflows (if configured) will run tests and coverage checks
3. Assign reviewers via GitHub UI or `gh pr review --request`

## References

- design/v5.6-Design-Loop.md §2 (Hook 表, L178) — on-pr.sh hook specification
