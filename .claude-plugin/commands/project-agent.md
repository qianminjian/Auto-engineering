---
name: project-agent
description: 单 Agent 调用 — architect/developer/critic 任意角色
---

# /project-agent — Single Agent Invocation

Invoke a single agent role directly, bypassing the full loop orchestration.

```
/project-agent architect "Design a payment module"
/project-agent developer "Implement the payment module"
/project-agent critic "Review the payment module"
```

## CLI contract

| Command | Behavior |
|---------|----------|
| `ae agent architect <instruction>` | Run architect agent |
| `ae agent developer <instruction>` | Run developer agent |
| `ae agent critic <instruction>` | Run critic agent |

Each agent invocation is a single, isolated LLM call. Use for quick design questions, code generation, or review without full loop overhead.

See `auto_engineering/cli/agent.py` for role definitions and `auto_engineering/agents/authz.py` for tool authorization per role.
