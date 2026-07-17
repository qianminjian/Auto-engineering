---
name: project-ci
description: 跑全量 Gate 检查 (safety/lint/type_check/audit/contract/test/build)
---

# /project-ci — Full CI Gate Check

Run all 7+1 gates against the current working tree.

```
/project-ci
```

## CLI contract

| Command | Behavior |
|---------|----------|
| `ae gate-check --all` | Run all 7 gates (safety → lint → type_check → audit → contract → test → build) |
| `ae gate-check --quick` | Run 3 fast gates (safety + lint + type_check) |

Gates run in parallel (asyncio.gather). Each gate is a subprocess quality check with pass/fail verdict.

See `auto_engineering/gates/` for individual gate implementations.
