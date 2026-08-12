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

每次先读取 `action.extensions.ae.execution_control`。宿主必须在同一次用户启动中执行：

```text
while control.disposition == "CONTINUE":
  execute current Action
  validate and submit Result
  read next Action and its execution_control
```

`CONTINUE` 不允许向用户交回控制；`WAIT_RESOURCE` 由宿主回收已完成 Worker、等待容量
变化后自动重试原 active Action，不询问用户；`WAIT_USER` 只询问 `reason_code` 对应的真实决策；
`TERMINAL`、`ERROR`、`HANDOFF_REQUIRED` 分别表示正常终态、稳定错误和异常接管。
不得根据 stage 名、自然语言 recap 或“已经输出 Action”自行停止。

当 `reason_code == "STATE_RECONCILIATION_REQUIRED"` 时，宿主必须原样展示 Core
返回的 `gate.options`：`reinitialize`（重新初始化）或 `reconcile`（修复状态并继续）。
用户选择前禁止编辑项目文件；宿主不得自动恢复旧 Action、删除 `.ae-state` 或代替用户选择。
提交 Result 时 `gate_resolution.gate_id` 必须为 `state_reconciliation`，`resolution`
必须使用 option id（不是显示标签），并由 `causation_id` 绑定当前 Gate message。

然后读取 `action.instruction`：

- `action == "error"`：报告 `error_code` 和 `message`，停止。
- `action == "gate"`：若 execution control 为 `WAIT_USER`，先取得用户选择并按 Gate
  Result 契约提交；不得跳过。仅无需用户输入的自动 Gate 才可直接执行下一次 tick。
- `action == "skip"`：直接执行下一次 tick。
- `action == "session_rollover"`：仅表示进程退出、compaction 失败或跨宿主接管等
  异常恢复；正常宿主 compaction 不产生该 Action。旧执行实例停止所有工作 Action；
  通过宿主原生能力
  创建全新会话，只加载 `action.capsule` 指向的 ResumeCapsule，不携带完整聊天历史；
  新会话提交 `{stage:"session_claimed", claim_token, session_id, host}` 后，才可继续
  Core 返回的原 active Action。宿主不能创建/接管新会话时报告
  `HOST_SESSION_HANDOFF_UNAVAILABLE` 并停止，禁止在旧会话降级继续。
- `action == "resource_wait"`：不得把该 Action 当作业务 Result。回收已完成 Worker 的
  原生句柄（宿主提供时），或等待已知运行中 Worker 进入终态；容量变化后重新执行 Core
  保留的原 active Action。该状态不是用户决策点。
- `action.spawn` 存在：检查当前 `HostCapabilities`，并逐项原样消费
  `action.spawn.invocations[]`；`instruction` 与旧 `subagent_prompt` 只作兼容诊断，禁止据此
  重新推导 prompt、effort、隔离方式或 receipt path。
- `action.stage == gap_review` 时，只展示 `action.current_gap`：按问题、证据、影响、推荐、
  理由、合法选项的顺序说明，并只询问当前项。用户回答后立即按 `expected_format.decision`
  提交单项 Result；累计决策与游标由 Core 持久化，宿主禁止本地批量缓存、提前询问其他
  gap、代选默认值或改写 `gap_id`。
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

### Codex 原生能力绑定

Codex 适配层以当前会话实际暴露的工具清单为能力事实源：

- 工具清单存在 `collaboration.spawn_agent` 时，必须将
  `HostCapabilities.subagents` 视为可用并调用该工具；不得因为当前回复尚未调用子代理就判定能力不存在。
- `action.spawn.effort` 映射到 `collaboration.spawn_agent` 的
  `reasoning_effort`；例如 `xhigh` 必须按 `xhigh` 传入，并选择允许该推理参数的
  `fork_turns`，不得因需要高推理强度而降级为 unavailable。
- Codex 创建 Worker 必须使用 invocation 声明的 Prompt 且 `fork_turns="none"`；Worker
  不继承 Coordinator 聊天和 Loop Skill 驱动职责，不得再次调用 `$auto-engineering`、
  `dev-loop` 或 `collaboration.spawn_agent`。
- `action.spawn.parallel=true` 时，只要当前会话允许创建所需数量的独立 Agent，必须按
  `action.spawn.count` 发起原生调用；不能用“本轮尚未创建”为由报告并行能力缺失。
- 当上述工具已经暴露时，工具调用明确失败前，不得报告 `HOST_CAPABILITY_UNAVAILABLE`；
  调用失败后必须保留原始错误证据，不能用主 Agent inline 模拟。
- 原生调用返回 Agent 线程/并发容量耗尽时，先等待已知 Worker 完成并通过宿主原生能力
  回收其句柄，再重试一次。仍失败时提交 `spawned=false`、
  `spawn_error_code=HOST_AGENT_CAPACITY` 和原始 `spawn_error`；不得伪造 Worker。
- `execution_control.disposition == "CONTINUE"` 时，能力满足的 spawn Action 必须在同一
  次用户启动中继续驱动，不得先向用户输出终态消息或请求无关确认。

能力满足时，使用宿主原生子代理能力：

1. 当前严格合同：无论单/多 Worker，都逐个读取并校验
   `action.spawn.invocations[i].prompt_ref` 与 `prompt_sha256`，并原样使用该 invocation
   的 effort、isolation、capabilities 和 receipt_path。
2. 仅当 active Action 的 Runtime Vector 明确是旧合同且没有 `contract_version` 时，才按
   旧 `subagent_prompt` / `spawn.agents[]` 只读兼容；当前 Action 禁止混用旧字段推导执行。
3. 按 `action.spawn.count` 和 `action.spawn.parallel` 创建隔离执行。
4. Worker 完成后，由宿主协调器为每个 Worker 以单个 JSON 写入
   `action.spawn.invocations[i].receipt_path`，记录 `requested_effort` 与宿主可见的
   `actual_model`（不可见时写 `unknown`）；Worker 不得修改
   `.ae-state/spawn-challenges/` 或 shared total receipt（workers must not write the shared total proof）。
   Receipt 超过 Action 策略声明的上限时必须将完整结果写入内容寻址 Artifact
   Store，receipt 只保留策略允许的有界摘要与带 SHA-256 的 `artifact_ref`；
   Skill 不复制策略默认数字。
5. Team Lead 收齐并验证全部 receipt 后，按 `action.subagent_prompt` 合并输出，
   再由宿主协调器写入 `action.spawn_proof_token` 对应的总 receipt；Core challenge
   保持不可变。
6. 从真实输出中提取 `action.expected_format` 要求的字段。只有全部要求的 Worker
   实际完成后，result 才能写 `"spawned": true`。
7. 每个 Worker 完成后由宿主生成 `worker_attestations[]`，绑定 Action message_id、worker_id、
   prompt_sha256、requested/effective effort、实际模型、隔离证据和可见能力摘要。Worker
   Outcome 不得包含 `spawned`、总 proof 或 Loop 控制字段；`fork_turns=none` 只证明会话
   turns 隔离，不得声明为完整工具沙箱。

Core 返回 `resource_wait` / `WAIT_RESOURCE` 时，宿主继续执行上述资源回收流程，并在
容量可用后重新执行原 active Action；不得提交 `resource_wait` 为 Result，也不得推进 Tick。

Gap Review 默认仍是用户决策。用户可通过结构化字段
`apply_to_remaining=recommendations` 授权当前线程后续 Gap 采用 Core 推荐；宿主不得从
`user_note` 自然语言推断授权。授权生效后，Core 会在 Gap Action 返回 `auto_decision`，
宿主必须原样提交该决定并继续，不再次询问，也不得自行构造或扩展授权范围。

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
