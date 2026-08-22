# 2026-08-22 双宿主 L3 上下文放大事故

## 结论

Build `5.8.0-rc.5+sha256.818e7459aa264e5d` 的确定性 Core 与恢复语义通过
Codex L3，但宿主会话成本不达标；Claude Code 在 Critic 前耗尽 2 美元硬预算。
因此 L3 整体失败，L4 不启动，发布继续阻断。

## 受控输入

- 同一 frozen Canary：`tests/fixtures/golden/l3_canary_*`
- 同一设计摘要：`376b51d3dc94643aa12334aeb976bdfd943d6a60340b07c492f735fb0b4c2e25`
- 同一内容寻址 Build，运行目录均位于开发目录之外
- Codex thread：`af58b609-5343-4918-8604-9788601825d4`
- Claude thread：`aa4ba53b-67ae-4463-b6f0-0194c05aafbc`

## 结果

| 宿主 | 业务终态 | Core input | Core cache read | Core output | 外层证据 |
|---|---|---:|---:|---:|---|
| Codex | `GOAL_ACHIEVED`，Tick 6 | 668,411 | 8,104,192 | 65,180 | 5,007,488 input，其中 4,852,992 cached；14,561 output |
| Claude Code | Critic，预算终止 | 95,591 | 1,705,088 | 20,226 | 32 turns，$2.008643，`budget_exhausted` |

Codex 还出现一次 Architect Worker 已完成后 Coordinator 先漏传 outcomes；Core 以
`WORKER_SET_MISMATCH` 拒绝，宿主未重复 spawn 并成功恢复。该行为证明 fail-closed
有效，但增加了一次不必要的协议往返。

## 根因

每个 Tick 的 CLI stdout 内联完整 Action；同一信息同时存在于 `instruction`、
`context`、`subagent_prompt`、`spawn.invocations[].prompt_ref` 对应正文和工具输出中。
宿主把这些输出及原生 Worker tool call 留在长会话历史，后续每一轮再次作为 input/cache
发送。T520 的“discard previous Action”只能约束推理行为，不能从宿主 API 历史删除 token。

## 纠正原则

1. Full Action 仍是 EventStore 中的权威协议事实，不降低验证或审计标准。
2. 产品宿主只消费 compact control envelope；大字段使用项目内、内容寻址、根目录受限的引用。
3. Worker 只从 `prompt_ref` 获取单次任务；Coordinator 不再同时接收同一 Worker prompt 正文。
4. L3/L4 除业务终态外必须校验成本，功能通过不能覆盖效率失败。
5. 若 compact control plane 仍不达阈值，自动 fresh session 属于 D13 状态翻转，必须另行审批。

