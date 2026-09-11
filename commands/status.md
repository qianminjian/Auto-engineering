---
name: status
description: 查看当前 dev-loop 进度与状态
---

# /status — Loop Progress

Display the current EventStore-projected loop state: stage, tick, verdict, and progress summary.

```
ae-run status
```

## CLI contract

| Command | Behavior |
|---------|----------|
| `ae-run status` | Print current loop progress JSON |

See `auto_engineering/cli/status.py` for the output schema.
