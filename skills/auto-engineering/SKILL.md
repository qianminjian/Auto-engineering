---
name: auto-engineering
description: >
  宿主无关的 Tick-Based Loop Engineering 调度协议
  （architect → developer → critic → verification）。
  Use when the user invokes $auto-engineering, asks to implement through
  dev-loop, check loop status, resume a checkpoint, or run gated development.
---

# Auto-Engineering v5.7 — 跨宿主 Tick 协议

Auto-Engineering 将职责拆成两层：

- Python 引擎是确定性 gatekeeper，负责路由、Guardrail、Gate、收敛和 checkpoint。
- 当前 Agent 宿主是执行器，负责推理、编辑、验证，并按 action 调用宿主原生子代理能力。

`$auto-engineering` 是 Codex 的显式入口；其他 Agent 平台使用各自的 Skill 或
Command 适配层进入同一协议。所有平台都必须通过 `scripts/ae-run` 调用共享核心，
不得复制或分叉业务逻辑。

## 铁律

<!-- FRAGMENT:iron_law_gatekeeper START -->
IRON LAW: PYTHON IS THE GATEKEEPER.
NO STAGE ADVANCEMENT WITHOUT `scripts/ae-run dev-loop --tick` VALIDATION.
You may NOT edit code before Python outputs {"action":"developer"}.
You may NOT declare done before Python outputs {"action":"done"}.
Violating the letter of this rule is violating the spirit of this rule.
<!-- FRAGMENT:iron_law_gatekeeper END -->

Git commit、push 和 PR 是外部副作用，只有获得用户明确授权后才能执行；宿主具备
相关能力不等于获得授权。

checkpoint 是循环恢复边界，checkpoint 不要求 commit。普通 developer batch 可以
保留未提交变更并继续 Tick；若某个确定性 Guardrail 确实需要 Git 写操作，必须暂停
并针对具体操作请求用户授权，不得把 checkpoint、clean working tree 或历史授权
解释为当前授权。

## 命令入口

| 用户意图 | 共享命令 |
|---|---|
| 启动开发循环 | `scripts/ae-run dev-loop --init "<requirement>"` |
| 推进一个 Tick | `scripts/ae-run dev-loop --tick --result <file>` |
| 查看循环状态 | `scripts/ae-run status --format json` |
| 恢复 checkpoint | `scripts/ae-run dev-loop --resume <id>` |

## Action 执行协议

每次先读取 `action.instruction`：

- `action == "error"`：报告 `error_code` 和 `message`，停止。
- `action == "gate"` 或 `"skip"`：不写 result，直接执行下一次 tick。
- `action.spawn` 存在：检查当前 `HostCapabilities`，再按以下规则执行。
- 无 `action.spawn`：仅 developer 阶段可由主 Agent inline 执行。

Spawn action 必须读取：

- `action.spawn.count`：需要的子代理数量。
- `action.spawn.parallel`：是否要求并行隔离执行。
- `action.spawn.effort`：抽象推理强度，由适配层映射到宿主支持的控制项。

默认使用满足任务的最低经济推理强度；只有复杂架构、安全问题、跨模块失败或
action 明确要求时才提高。若 `HostCapabilities.subagents` 不可用，或要求并行但
`HostCapabilities.parallel_subagents` 不可用，必须返回并报告
`HOST_CAPABILITY_UNAVAILABLE`，停止该阶段。不得伪造子代理已经启动、并行执行或
已经生成证据。

能力满足时，使用宿主原生子代理能力：

1. 将 `action.subagent_prompt` 原样传递给每个子代理。
2. 按 `action.spawn.count` 和 `action.spawn.parallel` 创建隔离执行。
3. 从真实输出中提取 `action.expected_format` 要求的字段。
4. 只有实际完成 spawn 后，result 才能写 `"spawned": true`。

## 角色边界

| 角色 | 执行方式 | 职责 |
|---|---|---|
| architect | 隔离子代理 | 设计与 batch plan |
| developer | 主 Agent inline | TDD 实现与本地验证 |
| critic | 隔离子代理 | diff 审查与门禁结论 |
| component_verifier | 隔离子代理 | 组件设计覆盖验证 |
| plate_deep_audit | 多个隔离子代理 | 板块多维审计 |
| system_verifier | 隔离子代理 | 系统设计覆盖验证 |
| system_deep_audit | 多个隔离子代理 | 全系统多维审计 |

## References

- `commands/dev-loop.md` — 完整 Tick 驱动手册
- `design/v5.6-Design-Loop.md` — 架构与阶段规格
- `design/BEACON.md` — 当前设计决策与状态
