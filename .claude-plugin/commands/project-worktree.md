---
name: project-worktree
description: 隔离 worktree 中执行 dev-loop
---

# /project-worktree — Isolated Worktree Loop

Execute the dev-loop inside an isolated git worktree to avoid polluting the main working tree.

```
/project-worktree "requirement"
```

## CLI contract

| Command | Behavior |
|---------|----------|
| `ae dev-loop --worktree "requirement"` | Run dev-loop in isolated git worktree |

Useful for experimental changes or when you need to run multiple loops in parallel without interference.
