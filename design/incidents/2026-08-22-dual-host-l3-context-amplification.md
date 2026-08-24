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

该结论经重新审计后撤回：当时 Developer 仍在 Coordinator inline 执行，“非翻转优化已耗尽”
并不成立。获批方案保持 D13，由 T530 把 Developer 改为 fresh Worker，T531 在 journal 前限制
Worker outcome，并以 T532 的同 Build 双宿主证据决定是否需要重新评审 Action-scoped 方案。

## T530-T532 复验进展

Build `5.8.0-rc.5+sha256.7acfd6d1b4392f9b` 已从独立内容寻址 Release 安装到 Codex 与
Claude Code，真实产品入口均通过零开发目录来源验收。Codex frozen Canary 首会话完成
Architect、B1、B2、Critic；两个 Developer Action 都由独立 fresh Worker 执行，Critic 的 P0
回修被 Core 确定性投影为下一 Developer Action。运行到 15 分钟边界后主动中止，状态保留在
`developer/round 4`，新宿主会话能读取同一 checkpoint，证明状态与宿主会话没有绑定。

续跑随后因 Codex WebSocket TLS EOF，降级 HTTPS 后仍连续连接失败，未进入 Loop Action，也未
形成 terminal usage。该故障属于宿主外部传输，不作为 Loop 缺陷；但按 T532 门禁，缺失完整
Codex/Claude terminal 与分项成本即判验收未完成，Claude L3、L4 和发布不得启动。T533 也不能
仅凭网络故障触发，必须等到可比较的完整同 Build 成本证据后再由用户显式审批。

## 2026-08-23 同 checkpoint 恢复审计

网络恢复后继续原 checkpoint，确认此前“外部传输中断”之外还存在三个 Loop 底层缺口：Critic
返工再次发出 `BatchCompleted` 导致完成事实重复；连续 MAJOR 通过隐式副作用把 cursor 从 B2
回退到 B1；Assembler 在 attestation 校验前写 prepared journal，使一次格式错误污染后续恢复。
这些问题分别通过完成/返工事件分离、`WorkRepairCompleted` 显式 reducer 自愈、先验证后写入及
无效历史 journal 的 append-only rejected archive 修复。自动基线已推进到 2540 passed/1 skipped。

继续真实恢复时，Codex 原生工具把隔离事实返回为 `{"fork_context": false}`，协议 canonical
值为 `fork_context=false`。两者语义一致，但 Assembler 只在旧 prepared journal 恢复分支做了
规范化，导致新 Action 重复报 `ATTESTATION_ISOLATION_MISMATCH`。最终设计不是让 LLM 手工改写，
而是在所有 Action 的 journal 前对两个精确白名单等价表示做确定性规范化；任何其他 mapping、
`true` 或未知表示仍拒绝。该实现已通过 23 项 Assembler、270 项恢复链路和 2541/1 全量测试；
下一步必须复用同一 checkpoint 到 terminal，证明恢复而非重置成功。

本轮 Codex 已记录的非终态宿主用量仍显著偏高：两个恢复会话分别约为 868,047 input（815,872
cached）/5,200 output 与 1,801,287 input（1,721,088 cached）/7,168 output。即使功能最终收敛，
T532 成本门禁也不得据此宣称通过；须取得完整 terminal 样本后再决定是否把 T533 提交用户审批。

同日新 Build 续跑时，Canary 启动目录缺少传入的设计文件。宿主没有在该根 fail-closed，而是扫描
`/tmp`、找到另一个历史 Voice Clone 项目、改写 `--project-root` 并初始化新 thread。人工发现后
立即终止；错误项目已产生一个新 thread 和 gap_scan 工作文件，未删除或伪装。根因是首个 Action
前只约束 runner，尚未把启动 cwd 作为不可变 Root Lease；首 Action 后的 root 约束无法阻止这次
漂移。T534 将同时补齐 Host 启动契约、首 Action root equality 和 Core 相对路径穿越拒绝。
T534 已完成并通过 2543 passed/1 skipped、Ruff、mypy、规则同步与 metadata 门禁；错误项目中的
历史副作用保留作审计证据，未经删除授权不清理。

使用 T534 Build 恢复正确 checkpoint 后，Root Lease 校验通过且没有重复 spawn；Finalizer 仍
拒绝 outcome，因为真实宿主同时记录 `fork_context=false` 与 `fork_turns=none`，而首版白名单
只接受两个单项对象。两项均表达 fresh isolation 且无冲突，应增加唯一组合白名单；含未知键、
`true` 或不一致值的对象继续拒绝，禁止放宽为任意 mapping。

组合白名单 Build 原地接受旧 Critic outcome 后，真实 Codex 连续完成 Architect refine、Developer、
Critic、Component Verifier 和 System Audit；Tick 16 再次进入 Architect 时，Worker 把新修复批次
命名为已完成的 `B3`，Core 以 `PLAN_BATCH_CONFLICT: B3` 正确停止。根因不是校验过严，而是
PLAN_REFINE Prompt 只说“使用新 ID”，未传完整占用集合和下一确定性 ID。T535 将由 Core 注入
`batch_id_policy`，杜绝 Worker 从聊天或文件猜测。该会话 usage 为 2,439,722 input、2,330,880
cached input、11,116 output，已直接证明现成本门禁失败；功能闭环仍需先达到 terminal。

T535 后用旧 Action 的 committed outcome 修正为 B4，跨过版本边界后新 Build 生效；后续 Developer
补齐两项测试，最终在 Tick 18 到达 `TERMINAL/GOAL_ACHIEVED`。最后续跑会话 usage 为
1,350,270 input、1,280,256 cached、7,445 output。期间宿主手工抄错一次 coordinator Prompt
文件名，并把 coordinator-result 路径误作 Finalizer outcomes；Core 均拒绝且没有污染状态，但
增加了无价值往返。T536 将把 finalize/validate/submit 变为 Core 生成的 action-scoped argv。

## T537-T543 Action-scoped 受控复验

新 Supervisor 已在一次用户启动内依次创建独立 `gap_scan` 与 `architect` context，并由 Core
机器操作自动推进；Receipt 持久化 action/build/context/tick/stage/usage 和 work digest，不保存
Prompt、环境变量或 transcript。真跑依次暴露并通过 TDD 修复：Codex Structured Output 的 strict
required 规则、首次生成 ae.toml 后配置快照未刷新、Prompt 要求 stage 而 Finalizer 禁止 stage、
Python pyproject 无 pytest command 探测、机器操作失败无有界 stderr、宿主不报告 actual model、
抽象 fresh_context 被误填为隔离执行事实。

Codex 后端增加官方 `--ignore-user-config` 后，受控两 Action 外层 input 从约 765,432 降到
407,668，约下降 47%；cache read 从 681,472 降到 363,264。该证据证明隔离无关用户插件配置有效，
也证明单次 fresh context 仍有约 200k 固定基线，尚不能据此宣称完整线程低于 1.0M。正式 frozen
Canary 随后自动完成 Gap、Architect、B1 Developer、B2 Developer 与 repair，项目
25 项业务测试及 lint、type、build、safety/audit 均通过。五个成功 Action 加 Critic 启动尝试累计
994,227 input、817,920 cache read、9,790 output；Critic 尚未执行业务即遇到 Codex 账户硬额度，
因此没有 terminal，也不能把成本阈值判为通过。该故障已由 TDD 固化为跨宿主
`HOST_ACTION_CONTEXT_RESOURCE_EXHAUSTED → WAIT_RESOURCE`，同一 active Action、tick 和业务预算保持
不变。当前自动门禁为 2594 passed/1 skipped，Ruff、mypy、规则同步、metadata、diff 和最新内容
寻址 Release archive 来源隔离均通过；真实产品安装、Codex terminal 与 Claude capability/terminal
全部完成前继续阻断发布。

## 2026-08-24 Claude Action-scoped 真实复验

首轮 Claude Gap Action 成功执行，但输出采用
`{action,stage,tick,thread_id,status,result}` 包装，被旧 Finalizer 以
`COORDINATOR_IDENTITY_OVERRIDE` 拒绝并泄漏 traceback。修复后，Core 只对固定包装键、同值身份与
成功 status 做安全解包；launcher 明确要求纯业务 payload，机器异常由 CLI 转为稳定错误，相对
design-doc 按 project-root 解析。

第二轮同一新 Build 自动完成 Gap 与 Architect，进入 Developer 后返回
`HOST_ACTION_CONTEXT_RESOURCE_EXHAUSTED/WAIT_RESOURCE`，active Action 未前移。真实成本依次为
USD 0.661090、1.325861、0.177335；最后一次在 CLI 剩余预算 USD 0.013049 时仍产生一个推理单元，
累计 USD 2.164286，证明 `--max-budget-usd` 存在事后超调且本 Canary 未满足 USD 2.00 terminal 门禁。
Backend 已增加 USD 0.20 超调预留，预算由 Receipt journal 跨 Action/恢复扣减；失败事件从
`modelUsage` 采集 33,782 input 而非接受顶层零值。另增加 5 分钟纯时长心跳。修复后自动基线为
2612 passed/1 skipped，Ruff、mypy、规则同步、metadata 与 diff 均通过；不重跑制造通过结论。

第三次仅验证新隔离启动参数时，Claude 在模型调用前以
`Invalid MCP configuration: expected record` 拒绝 `--mcp-config {}`，成本为零。配置已改为官方结构
`{"mcpServers":{}}`，并新增 `HOST_CLAUDE_LAUNCH_CONFIG_INVALID`。双宿主 capability probe 现在从
当前 CLI help 核验所有公开参数；Claude 2.1.220 不公开的 `--max-turns` 已移除，以进程超时和
thread 总预算替代。最终自动基线 2615 passed/1 skipped；未再发起付费重跑。

随后以不调用模型的 `claude mcp list` 验证参数：单独 strict MCP 仍加载用户插件；完整
`--setting-sources project --strict-mcp-config --mcp-config '{"mcpServers":{}}'
--disable-slash-commands --no-chrome` 返回 `No MCP servers configured`，证明新组合确实隔离用户 MCP。
