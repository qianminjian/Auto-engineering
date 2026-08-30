# Auto-Engineering BEACON
> 创建：2026-06-24｜更新：2026-08-30｜阶段：P0-E2E 端到端产品闭环
> 决策状态翻转（✅↔❌）或架构降级必须先获用户批准。

## 导航

- 当前权威设计：[`v5.8-Main-Agent-Coordinator-Recovery-Design.md`](v5.8-Main-Agent-Coordinator-Recovery-Design.md)
- 当前任务：[`IMPLEMENTATION-TRACKER.md`](IMPLEMENTATION-TRACKER.md)
- BEACON 演进历史：[`BEACON-HIS.md`](BEACON-HIS.md)
- 项目里程碑：[`HISTORY.md`](HISTORY.md)

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
| D50-D52 | D50 的旧失败路由由 D56 修订；D51-D52 继续要求 batch 精确覆盖及私有 `outcome_path`→Collector，禁止 Coordinator 创造 native outcome | ✅ |
| D53 | 当前主 Agent 是活跃宿主会话内唯一 Loop Coordinator；所有业务角色由独立子 Agent 执行，Python 只做确定性治理 | ✅ |
| D54 | Worker handle 只在当前宿主会话内有效；跨会话恢复只信任原子落盘 outcome，未落盘 Worker 以新执行身份安全重跑 | ✅ |
| D55 | 预算默认 soft，不因 token、费用、Action/Tick 数或时长停机；旧 Supervisor 先旁路，双宿主 L4 通过后再退役 | ✅ |
| D56 | 同时修订 D37 与 D50 的失败路由：wait 到期不是失败；明确失败只重试失败 Worker，资源/所有权不确定才 WAIT_RESOURCE；generation + fencing token 阻止迟到双写 | ✅ |
## 当前状态
- `P0-E2E` 是唯一产品交付任务；既有 Phase/T、L1/L2、覆盖率和 archive 安装仅作支撑证据，不能替代 L4。
- 上一候选 Build `5.8.0-rc.5+sha256.4f32a506f46b0f94` 仅作为历史 archive smoke 证据；本轮工作树已有未提交改动，旧 Build Identity 不适用于当前代码，必须重新构建制品后才能进行新的安装验收。本轮自动回归为 2788 passed/1 skipped，新增主 Agent 入口、软预算、异步等待和 generation/fencing 回归已通过；真实产品 L3/L4 仍未执行，不得以 archive smoke 或自动测试替代。
- Phase 85 已进入主控权纠偏实施：默认主控返回当前主 Agent，业务角色继续独立 Worker 化；Python Supervisor 仅保留旁路兼容。预算默认软约束，先跑通再优化。T609-T615 已完成第一批实现，T616-T620 待真实验收。
## 待解决问题
- 完成异步故障回放、安装后契约和同一 Build 双宿主 L4 前保持发布阻断；T621 仅在双宿主通过后退役 Supervisor。当前工作树尚未提交，新的 Build Identity 尚未生成。
## 引用文件
`design/v5.8-Main-Agent-Coordinator-Recovery-Design.md` · `design/BEACON-HIS.md` · `design/v5.8-Session-Decoupling-Design.md` · `design/v5.8-Session-Decoupling-PLAN.md` · `design/incidents/2026-07-29-claude-146-tick-long-run.md` · `design/IMPLEMENTATION-TRACKER.md` · `design/HISTORY.md`
