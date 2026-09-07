# Auto-Engineering BEACON
> 创建：2026-06-24｜更新：2026-09-07｜阶段：P0-E2E 端到端产品闭环
> 决策状态翻转（✅↔❌）或架构降级必须先获用户批准。
## 导航
- 当前权威设计：[`v5.8-Main-Agent-Coordinator-Recovery-Design.md`](v5.8-Main-Agent-Coordinator-Recovery-Design.md)
- 当前任务：[`IMPLEMENTATION-TRACKER.md`](IMPLEMENTATION-TRACKER.md)
- 历史与里程碑：[`BEACON-HIS.md`](BEACON-HIS.md) · [`HISTORY.md`](HISTORY.md)
## 目标与成功标准
1. 用户执行一次设计驱动命令后，产品无非预期人工介入地运行到 `TERMINAL`。
2. 定位为跨 Agent 宿主的确定性工程治理内核；宿主负责推理、工具和连续驱动。
3. 设计、缺口、任务、代码和验证使用同一稳定工程模型全程追溯。
4. Core 负责协议、状态、验证、安全和审计，Agent 不复制机器事实。
5. Claude Code 与 Codex 的独立安装制品完成等价 L4 终态后才可发布。
## 范围边界
**做：** Protocol Envelope、Event Store、Tick Kernel、StageHandler、Host SPI、
Gate/Guardrail、五层验证、审计、v5.6 兼容迁移和双宿主验收。
**不做：** Core 内调用 LLM；复制宿主 Agent Runtime；恢复退役 CLI；实现 Init Engineering 的问答、模板或脚手架；把 archive smoke 冒充真实产品安装；修改外部参考源码。
## 当前设计决策
| ID | 决策 | 状态 |
|---|---|:---:|
| D1 | Core 只做确定性治理，Agent 在 Tick 之间推理和执行工具 | ✅ |
| D2 | Host Adapter 隔离宿主差异，Core 不感知 Claude/Codex | ✅ |
| D3 | Claude/Codex 共用规则模板、Skill 协议和 `scripts/ae-run` | ✅ |
| D4 | `FeatureManifest` 是 `AE_*` 默认值唯一事实源 | ✅ |
| D5 | archive smoke 与真实 product install 分开报告 | ✅ |
| D6 | 当前资产短小可追溯，详细历史由 Git 和 `HISTORY.md` 保留 | ✅ |
| D7 | 采用双基线：v5.7.1 是当前发布实现，v5.8 是已批准目标 | ✅ |
| D8 | v5.7 采用渐进协议内核重构，不建立双内核 | ✅ |
| D9 | 事件是事实源，EngineState 是可重建投影 | ✅ |
| D10 | Prompt Contract 采用兼容式编译，不改变 Action/Result v1.1 核心语义 | ✅ |
| D11 | 多 Agent 必须逐 Worker 交付上下文并提供独立完成回执 | ✅ |
| D12 | Thread 与 ExecutionSession 分离；聊天历史、BEACON 和自动摘要不是状态事实源 | ✅ |
| D13 | 2026-08-23 的 Action-scoped Supervisor 批准范围存在争议；保留历史，由 D53-D55 取代 | ⚠️ |
| D14 | 修复计划使用 PlanPatch；完成事实不可由普通计划更新重新激活 | ✅ |
| D15 | runner 错配、零测试、空快照和证据失配全部 fail-closed | ✅ |
| D16 | Core 以 ProjectProfile 消费项目能力；本地确定性探测为默认 Provider，Init Engineering 仅是可选兼容 Provider | ✅ |
| D17 | Core 保持单 Tick；宿主按 Execution Control 在一次启动内连续驱动 | ✅ |
| D18 | Prompt/Policy 等运行时变化只在 Action 边界激活，活动 Action 不可变 | ✅ |
| D19 | 新状态事实使用显式领域事件；完整 state patch 只作 legacy 读取 | ✅ |
| D20 | ActionCompiler 纯化，TickOrchestrator 按 Stage 绞杀，不建立第二内核 | ✅ |
| D21 | Legacy 兼容按 payload 能力适配全部旧事件类型；新写入在 EventStore 边界拒绝 `state_patch` | ✅ |
| D22 | Baseline、PlanPatch、contracts、obligations 只物化一次 Architecture Candidate，校验与激活共享 | ✅ |
| D23 | SemVer 表示发布版本，内容寻址 Build Identity 区分同版本的不同制品和源码 | ✅ |
| D24 | 显式设计文档与旧状态冲突时先由用户选择重新初始化或修复续作；旧状态保留审计 | ✅ |
| D25 | Gap 决策由 Core 单项持久化；batch 展示标题与多组件路由键分离；Git 仅是可选证据源 | ✅ |
| D26 | 本机产品安装使用 Codex/Claude 原生 Marketplace；运行时不依赖插件源码工作区 | ✅ |
| D27 | Host Runtime 属于插件产品层；Core 保持单 Tick，用户不承担 continue/supervisor 管理命令 | ✅ |
| D28 | Worker outcome 由宿主 Assembler 原子固化为 receipt、attestation、total proof 和 Result | ✅ |
| D29 | partial 设计权威只允许保守执行原设计；advisory 架构变化必须显式用户批准 | ✅ |
| D30 | 宿主临时交接文件按 Action identity 隔离；固定根目录文件不得跨 Tick 复用 | ✅ |
| D31 | Core 状态目录必须从宿主工作区 diff 隔离，但不得隐藏业务源码或改写用户根忽略策略 | ✅ |
| D32-D36 | Tick 后清理临时交接并有界等待；自动 Gap 决策双重重绑；已批准 Fill 保持 binding；Gate 使用独立 Result 契约 | ✅ |
| D37 | 旧 Worker 失败统一转 WAIT_RESOURCE 的规则由 D56 修订；历史保留 | ⚠️ |
| D38 | Finalizer 以 active Action 的工作文件为唯一事实源；宿主传入陈旧路径时自动续接当前文件，禁止跨 Action 误提交 | ✅ |
| D39 | 系统审计覆盖维度固定、执行 fan-out 按 Core 计算的项目规模伸缩；小项目不重复发送五份上下文 | ✅ |
| D40-D43 | ProjectProfile 以真实 Gate 证明能力且可修复失败自动续作；Canonical Action 与 compact 宿主视图分离；五类 refine 信号无损归一并强制修复映射 | ✅ |
| D44 | Gap Scan 始终输出有界可见摘要；零缺口必须逐章节可证明并自动续作，真实设计决策才进入用户确认，丢失产物不得降级为空结果 | ✅ |
| D45 | 后续唯一 P0 为单命令运行到 `TERMINAL`；局部能力只作支撑证据，L4 未通过不得关闭产品任务 | ✅ |
| D46 | 运行态设计权威由 Core 统一投影；当前 Tick 的批准必须对同 Tick 下一 Action 可见，ActionBuilder 不得独立重读静态 ledger | ✅ |
| D47 | Core 拒绝后的同 Action repair 必须复用 journal 权威 Worker outcomes；修复包只允许 Coordinator，冲突在当前 Action fail-closed 并生成 Stop Report | ✅ |
| D48 | `done/TERMINAL` 只证明 Core 收敛；必须携带 Core 验证覆盖率与未验证项，真实产品验收仍由 L4 独立证明 | ✅ |
| D49 | `remaining_recommendations` 仅可自动采用明确标注 `requires_user_approval=false` 的普通 Gap；字段缺失或绑定设计影响必须等待用户 Gate | ✅ |
| D50-D52/D71 | D50 的旧失败路由由 D56 修订；batch 仍须精确覆盖；原生返回由 Host Driver 在唯一回写边界严格解析并原子固化到私有 `outcome_path`，禁止 Coordinator 手工创造宿主事实或第二条循环 | ✅ |
| D53 | 当前主 Agent 是活跃宿主会话内唯一 Loop Coordinator；所有业务角色由独立子 Agent 执行，Python 只做确定性治理 | ✅ |
| D54 | Worker handle 只在当前宿主会话内有效；跨会话恢复只信任原子落盘 outcome，未落盘 Worker 以新执行身份安全重跑 | ✅ |
| D55 | 预算默认 soft，不因 token、费用、Action/Tick 数或时长停机；旧 Supervisor 主控路径已退役 | ✅ |
| D56 | 同时修订 D37 与 D50 的失败路由：wait 到期不是失败；明确失败只重试失败 Worker，资源/所有权不确定才 WAIT_RESOURCE；generation + fencing token 阻止迟到双写 | ✅ |
| D57-D58 | 统一 generation 绑定映射入口；EventStore 是唯一新协议事实源，checkpoint 仅兼容回退且禁止拼接 | ✅ |
| D59-D65 | Tick 回滚撤销未提交命名 JSON effect；验收 artifact 由事件/回执推导 machine_claims 并交叉校验；跟踪按证据层级分层；L2 必须经过公开 CLI 轨迹；损坏 receipt/空事件流在边界稳定 fail-closed；Worker 原生事实回写随 Action 下发逐 Worker 机器模板；compact 视图不得丢失回写合同和代际身份 | ✅ |
| D66 | 当前 Action 禁止生成或消费 `subagent_prompt`；Coordinator prompt 使用内容寻址 `coordinator_prompt_ref`，Worker prompt 只通过 invocation `prompt_ref`/`native_launch_prompt` 交付；旧字段仅由显式历史迁移边界拒绝或转换 | ✅ |
| D67 | 宿主提交 Worker 失败前，CLI 必须检查当前 Action 的私有 outcome 与 native attestation；若仅缺宿主事实，先投影 `worker_attestation_pending`，不得消费失败预算或重启 Worker | ✅ |
| D68-D69 | 结果确定性校验失败属于当前 Action 的 Coordinator repair；Core/CLI 必须保持 Action identity、复用已认证 Worker outcome 并隐藏 `spawn`，不得把语义修复变成新 Worker Action；validate→tick 连续调用也必须重复投影 repair；`WAIT_RESOURCE` 是有界 yield，重复失败不得继续递增状态或写事件，修复后的有效 Result 仍可恢复原 active Action | ✅ |
| D70/D72 | Feature 配置是可选覆盖；默认值、环境变量和 `ae.toml` 是唯一读取链；旧强制配置闸门退役 | ✅ |
| D73-D74 | 设计来源漂移只有显式 `state_reconciliation/reinitialize` 可以轮换项目级设计账本；旧账本归档保留，普通恢复与只读校验不得改写来源绑定；Developer 的缺工具链/依赖失败属于可恢复资源等待，统一投影为 `WAIT_RESOURCE` 并自动重试原 active Action，真实设计/授权选择仍保持 `WAIT_USER` | ✅ |
## 当前状态：`P0-E2E` 已完成；核心架构严格是“主 Agent 唯一 Coordinator + Python 单 Tick + EventStore 事实源 + 原生 Worker 交接”。同一 final140 Build `5.8.0-rc.5+sha256.5892735d72dc9851` 已分别在全新 Codex 与 Claude Code 项目完成一次设计驱动命令，均连续到 `TERMINAL/GOAL_ACHIEVED`。Codex 与 Claude 的 Setup、Gap Scan、Architect、Developer、Critic 阶段均有真实宿主证据；Claude 的越权 outcome 写入被 Hook 拒绝后按固定回写边界恢复，Developer lint 与 Architect obligation 修正均在同一 Loop 内完成。T838 的新增文件 patch 契约与 T837 的 generation/fencing 修复均在真实宿主中复验通过。final143 archive `5.8.0-rc.5+sha256.f46d72d68586709b` 已由提交 `a528810e` 构建并通过 Codex/Claude smoke。当前不再自动真跑；后续仅归档证据、运行常规回归和按发布流程交付。
- T707-T750 已补齐隔离证据、同 Action recovery、Codex 单层 `result` 原生回包、无 Git 证据、Worker liveness 观察合同、锁定解释器安装入口、Gate 的 finalize/validate/submit 合同、PlanPatch canonical batch、`complete` 状态别名、短启动合同中的共享 outcomes 禁写约束、`--native-result-stdin` 原样暂存通道、Loop 前 Build Identity 强制预检、产品 artifact 预检事实绑定、SQLite 测试连接显式关闭、Project Setup service/scope 拆分、Worker Evidence 原语、Outcome Recovery 恢复服务、Result Contract 纯策略、Worker Failure 失败事务单一归属、Python CLI 无长期 Coordinator 的架构回归、Codex/Claude/product acceptance 独立入口的仓库根解析、浏览器能力探测单一归属、EngineState 字段校验单一归属、DesignDoc 解析器单一归属、TaskOutcome 执行回执单一模型、ProgressTree 身份辅助单一模块、BatchState 编解码单一模块、Action 响应模型单一模块、Convergence 值对象单一模块、ReducerRegistry 单一模块、EventStore 编解码/schema 单一模块及 Host Action 映射编译器单一模块、Design Stage 辅助单一模块及 PlanRefine 单一模块、Result 校验/PII 入站策略/Tick 证据/Stage Action 编译/Worker 路径/Host Action 运行时与 CLI 恢复读取单一归属、旧 Action 迁移 Gate 单一归属、显式 reinitialize 的设计账本轮换单一归属；当前仍保持主 Agent 唯一协调、Python 单 Tick，旧 Supervisor/第二套循环不在运行路径。
## 待解决问题：当前没有未完成的 P0/P1 工程任务；A008/P0-E2E 已由同一 final140 Build 在全新 Codex 与 Claude Code 项目完成真实终态验收。
- 发布层仍可单独创建版本 Tag、Release Archive 和 GitHub Release；这些是交付动作，不是 Loop 开发阻断，也不得重新打开 A008 或恢复旧 Supervisor。
- 后续新问题必须以新的运行证据建立新任务；本文件和跟踪表中的历史“待复验”只保留审计，不得重新生成当前待办。
## 引用文件：`design/v5.8-Main-Agent-Coordinator-Recovery-Design.md` · `design/BEACON-HIS.md` · `design/v5.8-Session-Decoupling-Design.md` · `design/v5.8-Session-Decoupling-PLAN.md` · `design/incidents/2026-07-29-claude-146-tick-long-run.md` · `design/incidents/2026-08-30-architecture-audit-remediation.md` · `design/IMPLEMENTATION-TRACKER.md` · `design/HISTORY.md`
