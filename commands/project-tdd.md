---
name: project-tdd
description: 快速 TDD 循环 — 跳过语义评估与 Gate 检查
---

# /project-tdd — Fast TDD Loop

Accelerated TDD loop that skips semantic evaluation and most gates for rapid Red→Green→Refactor cycles.

```
/project-tdd "requirement"
```

## CLI contract

| Command | Behavior |
|---------|----------|
| `ae dev-loop --standalone --max-rounds 3 "requirement"` | Run dev-loop in standalone mode with fast iteration |

Use when you want fast feedback on a single component. Full verification (gates, deep audit) should still run before PR merge.
