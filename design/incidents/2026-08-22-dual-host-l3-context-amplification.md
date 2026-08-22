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

## T525-T527 复验（Build `5.8.0-rc.5+sha256.41f2b07e39187219`）

Codex frozen Canary 到达 `done`，17 tests、Ruff、mypy、build、组件覆盖和系统审计均通过；
Core usage 为 370,682 input、3,070,976 cache read、35,878 output，外层为
3,292,465 input（3,048,448 cached）和 18,326 output。相对旧 Build，外层 input/cache
仅下降约 34.2%/37.2%，仍为百万级重放，因此 T526 失败；Claude 与 L4 按门禁未启动。

首次受控运行被验收编排的未消费 JSON pipe 反压中断；恢复时又发现 prepared outcome journal
与宿主可写 work copy 漂移。T527 已改为由 Core 以 prepared journal 原文原子重建 outcomes，
2528/1、Ruff、mypy 通过；全新 Canary 未再出现 `OUTCOME_JOURNAL_CONFLICT`。

结论：compact envelope 消除了 Action 正文重复，但无法删除宿主聊天历史；继续压缩字段只能边际
优化，不能从机制上消除每回合重放。下一步必须在“每 Action 自动新建宿主执行会话，Thread 状态
仍完全留在 Core”与“接受长会话百万级成本”之间作架构决策；前者会翻转 D13，需用户批准。

## T528 Digest-Bound Launcher 复验

Build `5.8.0-rc.5+sha256.d51c7397bc9bdc8d` 的 Codex frozen Canary 再次到达 `done`；
四次 native `spawn_agent` 的 prompt 均为 533 bytes，只包含 root/ref/hash/权限，完整 Worker
Prompt 未进入 Coordinator 工具调用，证明第二条正文复制通道已经闭合。

但最终外层 usage 为 4,718,497 input（4,591,616 cached）和 17,982 output；Core 聚合
480,775 input、10,483,456 cache read、81,153 output。原因已从 Prompt 重复转为每个 fresh
Worker 都加载完整宿主基础上下文：Architect、Critic、Component Verifier、System Audit 共四次
独立基线。T526 继续失败，Claude/L4 不启动。

后续先按 D39 的规模伸缩原则实施“小项目独立 Assurance Worker 合并 Critic、组件覆盖和五维
系统审计”，保持与 Developer 隔离且不减少任何审计维度，将四个 Worker 降为两个；若仍超预算，
再申请翻转 D13。禁止把更换便宜模型当作 token 根治。

## T529 Assurance Fusion 复验

Build `5.8.0-rc.5+sha256.ad1c63a0a975fe40` 的 Codex frozen Canary 在 Critic 后直接
`done`；只有 Architect 与 Assurance 两个 Worker，两次 launcher 均为 533 bytes。Assurance
一次交付 Critic、组件 coverage 和固定五维审计，Core 重计数后收敛，未启动 Component/System
Worker。19 tests、Ruff、mypy、build 均通过。

外层 usage 为 3,785,090 input（3,568,640 cached）和 16,239 output；相对 T528 下降
19.8%/22.3%，但仍是百万级。Core usage 为 686,981 input、6,109,440 cache read、54,795
output。非翻转优化已依次排除 Action 内联、Worker Prompt 复制和重复验收 Worker，剩余主因是
固定宿主会话在每个 LLM/tool 回合重放此前聊天历史。T526 继续失败，Claude/L4 不启动。

下一步 T530 必须把“Core ExecutionSession”与“宿主模型上下文”进一步解耦：用户只启动一次，
确定性 supervisor 为每个 Action 创建 fresh host context，只传 compact envelope/ref，并以 Core
thread/action identity 自动续接。这会翻转 D13 的固定会话部分，未获用户批准前不得实施。
