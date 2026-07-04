---
name: project-worktree
description: Create an isolated git worktree for parallel development
---

# /ae:project-worktree — Create Git Worktree

## Description

Create an isolated git worktree for parallel feature development. The worktree shares the same .git directory but has its own working tree, allowing multiple agents to work on different features simultaneously.

## Usage

```
/ae:project-worktree <branch-name> [--base main]
```

## Arguments

| Name | Required | Description |
|------|----------|-------------|
| `branch-name` | Yes | Name of the new branch/worktree (e.g., `feat/oauth-login`) |

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--base BRANCH` | main | Base branch to fork from |
| `--path PATH` | auto-generate | Custom worktree path |

## Execution

```bash
BRANCH="$1"
shift

BASE="main"
PATH_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      BASE="$2"
      shift 2
      ;;
    --path)
      PATH_OVERRIDE="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done

if [[ -z "$BRANCH" ]]; then
  echo '{"error":"branch name required"}'
  exit 2
fi

WT_PATH="${PATH_OVERRIDE:-../$(basename "$PWD")-$BRANCH}"

git worktree add -b "$BRANCH" "$WT_PATH" "$BASE"
echo "{\"worktree\":\"$WT_PATH\",\"branch\":\"$BRANCH\",\"base\":\"$BASE\"}"
```

## Output

```json
{"worktree":"../project-feat-oauth-login","branch":"feat/oauth-login","base":"main"}
```

## Examples

```
/ae:project-worktree feat/oauth-login
/ae:project-worktree fix/memory-leak --base develop
/ae:project-worktree experiment/new-arch --path /tmp/experiment
```
