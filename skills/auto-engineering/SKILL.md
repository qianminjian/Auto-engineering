---
name: auto-engineering
description: >
  宿主无关的 Tick-Based Loop Engineering 调度协议
  （architect → developer → critic → verification）。
  Use when the user invokes $auto-engineering, asks to implement through
  dev-loop, check loop status, resume a checkpoint, or run gated development.
---

# Auto-Engineering v5.8 — 跨宿主确定性会话 Tick 协议

Auto-Engineering 将职责拆成两层：

- Python 引擎是确定性 gatekeeper，负责路由、Guardrail、Gate、收敛和 checkpoint。
- 当前 Agent 宿主是执行器，负责推理、编辑、验证，并按 action 调用宿主原生子代理能力。

`$auto-engineering` 是 Codex 的显式入口；其他 Agent 平台使用各自的 Skill 或
Command 适配层进入同一协议。所有平台都必须通过 bundled `ae-run` 调用共享核心，
不得复制或分叉业务逻辑。

## 铁律

<!-- FRAGMENT:iron_law_gatekeeper START -->
IRON LAW: PYTHON IS THE GATEKEEPER.
NO STAGE ADVANCEMENT WITHOUT `ae-run dev-loop --tick` VALIDATION.
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
| 启动开发循环 | `ae-run dev-loop --init "<requirement>"` |
| 预校验 Result | `ae-run dev-loop --validate-result <file>` |
| 推进一个 Tick | `ae-run dev-loop --tick --result <file>` |
| 查看循环状态 | `ae-run status --format json` |
| 恢复 checkpoint | `ae-run dev-loop --resume <id>` |

设计文档模式必须把自然语言需求和文档路径分开传入：

```bash
ae-run dev-loop --init "实现 Voice Clone 页面" \
  --design-doc design/V1.0-Design-VoiceClonePage.md
```

若只按设计文档的全部内容开发，可省略自然语言 requirement：

```bash
ae-run dev-loop --init \
  --design-doc design/V1.0-Design-VoiceClonePage.md
```

不得把 `design/*.md` 路径直接作为 requirement；启动后应核验首个 Action 的
`design_doc_path` 非空。

## Action 执行协议

每次先读取 `action.instruction`：

- `action == "error"`：报告 `error_code` 和 `message`，停止。
- `action == "gate"` 或 `"skip"`：不写 result，直接执行下一次 tick。
- `action == "session_rollover"`：仅表示进程退出、compaction 失败或跨宿主接管等
  异常恢复；正常宿主 compaction 不产生该 Action。旧执行实例停止所有工作 Action；
  通过宿主原生能力
  创建全新会话，只加载 `action.capsule` 指向的 ResumeCapsule，不携带完整聊天历史；
  新会话提交 `{stage:"session_claimed", claim_token, session_id, host}` 后，才可继续
  Core 返回的原 active Action。宿主不能创建/接管新会话时报告
  `HOST_SESSION_HANDOFF_UNAVAILABLE` 并停止，禁止在旧会话降级继续。
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

1. 单 Worker：将 `action.subagent_prompt` 原样交给该 Worker。
2. 多 Worker：逐个读取并校验 `action.spawn.agents[i].prompt_ref` 与
   `prompt_hash`，将对应正文交给 Worker；不得把 Coordinator 的
   `action.subagent_prompt` 复制给所有 Worker。
3. 按 `action.spawn.count` 和 `action.spawn.parallel` 创建隔离执行。
4. 多 Worker 完成后，每个 Worker 必须以单个 JSON 覆写自己的
   `action.spawn.agents[i].receipt_path`，记录 `requested_effort` 与宿主可见的
   `actual_model`（不可见时写 `unknown`）；workers must not write the shared total proof。
   Receipt 超过 Action 策略声明的上限时必须将完整结果写入内容寻址 Artifact
   Store，receipt 只保留策略允许的有界摘要与带 SHA-256 的 `artifact_ref`；
   Skill 不复制策略默认数字。
5. Team Lead 收齐并验证全部 receipt 后，按 `action.subagent_prompt` 合并输出，
   再覆写 `action.spawn_proof_token` 对应的总 proof。
6. 从真实输出中提取 `action.expected_format` 要求的字段。只有全部要求的 Worker
   实际完成后，result 才能写 `"spawned": true`。

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
