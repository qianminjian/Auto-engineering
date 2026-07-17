---
name: checkpoint
description: Checkpoint 管理 — list/show/delete/resume 操作 (v5.6 SQLite WAL)
---

# /checkpoint — State Management

Manage persistent checkpoints stored in `.ae-state/checkpoints.db` (SQLite WAL).

## Usage

```
/checkpoint list                    # 列出所有 checkpoint
/checkpoint show <id>               # 查看指定 checkpoint 详情
/checkpoint delete <id>             # 删除指定 checkpoint
/checkpoint resume <id>             # 从指定 checkpoint 恢复
```

## CLI contract

| Command | Behavior |
|---------|----------|
| `ae checkpoint list` | List all checkpoints |
| `ae checkpoint show <id>` | Show checkpoint detail |
| `ae checkpoint delete <id>` | Delete a checkpoint |
| `ae checkpoint resume <id>` | Resume from checkpoint (outputs action JSON) |
| `ae checkpoint v2 list` | v2.0 checkpoint list |
| `ae checkpoint v2 show <id>` | v2.0 checkpoint detail |
| `ae checkpoint v2 delete <id>` | v2.0 checkpoint delete |
| `ae checkpoint v2 migrate` | Migrate legacy checkpoints to v2.0 |

See `auto_engineering/cli/checkpoint.py` for full schema.
