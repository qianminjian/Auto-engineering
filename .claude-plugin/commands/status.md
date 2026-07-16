---
name: status
description: 查看当前 dev-loop 进度与状态
---

# /status — Loop Progress

Display the current tick loop state: stage, round, tick, verdict, and progress summary.

```
ae status
```

## CLI contract

| Command | Behavior |
|---------|----------|
| `ae status` | Print current loop progress JSON |

See `auto_engineering/cli/status.py` for the output schema.
