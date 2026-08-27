# Auto-Engineering BEACON
> 创建：2026-06-24｜更新：2026-08-25｜阶段：P0-E2E 端到端产品闭环
> 决策状态翻转（✅↔❌）或架构降级必须先获用户批准。

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
| D13 | 工程线程连续；宿主模型上下文按 Action 隔离且自动续作；Capsule 仅用于异常恢复 | ✅ |
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
| D26 | 本机产品安装只注册开发目录之外的内容寻址 Release；运行时来源不得反向访问源码工作区 | ✅ |
| D27 | Host Runtime 属于插件产品层；Core 保持单 Tick，用户不承担 continue/supervisor 管理命令 | ✅ |
| D28 | Worker outcome 由宿主 Assembler 原子固化为 receipt、attestation、total proof 和 Result | ✅ |
| D29 | partial 设计权威只允许保守执行原设计；advisory 架构变化必须显式用户批准 | ✅ |
| D30 | 宿主临时交接文件按 Action identity 隔离；固定根目录文件不得跨 Tick 复用 | ✅ |
| D31 | Core 状态目录必须从宿主工作区 diff 隔离，但不得隐藏业务源码或改写用户根忽略策略 | ✅ |
| D32-D36 | Tick 后清理临时交接并有界等待；自动 Gap 决策双重重绑；已批准 Fill 保持 binding；Gate 使用独立 Result 契约 | ✅ |
| D37 | Worker 失败写 `worker_failed` 尝试并由 Core 返回 WAIT_RESOURCE；只有成功 journal 才禁止重复 spawn | ✅ |
| D38 | Finalizer 以 active Action 的工作文件为唯一事实源；宿主传入陈旧路径时自动续接当前文件，禁止跨 Action 误提交 | ✅ |
| D39 | 系统审计覆盖维度固定、执行 fan-out 按 Core 计算的项目规模伸缩；小项目不重复发送五份上下文 | ✅ |
| D40-D43 | ProjectProfile 以真实 Gate 证明能力且可修复失败自动续作；Canonical Action 与 compact 宿主视图分离；五类 refine 信号无损归一并强制修复映射 | ✅ |
| D44 | Gap Scan 始终输出有界可见摘要；零缺口必须逐章节可证明并自动续作，真实设计决策才进入用户确认，丢失产物不得降级为空结果 | ✅ |
| D45 | 后续唯一 P0 为单命令运行到 `TERMINAL`；局部能力只作支撑证据，L4 未通过不得关闭产品任务 | ✅ |

## 当前状态

- `P0-E2E` 是唯一产品交付任务；既有 Phase/T 项仅作为能力与回归证据。
- v5.8.0-rc.5 的 L1/L2、覆盖率和 archive 安装不能替代真实 L4。
- Section 双身份、公开执行包离线终态已补齐；最新 Build `5.8.0-rc.5+sha256.3927b1f572df8ece` 已重新安装到 Codex/Claude，覆盖回放一致性修复后回归为 `2676 passed, 1 skipped`；Codex L4 已通过，Claude Code L4 仍待真实宿主复验。
- 后续冻结无关治理和点状补丁，按设计模型、连续 Runtime、Agent 边界、真实验收四个工作面纵向闭环。
## 最近演进
| 日期 | 变更 |
|---|---|
| 2026-08-25 | 移除耗时型质量拒绝；公开执行包双宿主以 9 次 context 经真实 operations 到 TERMINAL |
| 2026-08-25 | 真跑证实修复 Action 重启 Worker 会形成 outcome conflict；改为只修 Coordinator 并保留 Worker 完成事实 |
| 2026-08-25 | Gap 执行包改用可读 section_ref；Assembler 拒绝纳入同 Action 自动修复事务，2661/1 回归通过 |
| 2026-08-25 | D45 获批：实施战略翻转为唯一 `P0-E2E`，L4 终态成为产品完成定义 |
| 2026-08-21 | T512-T518 关闭重复 spawn、错误恢复、计划校验终止、Worker 超时伪成功与无限重启链路 |
| 2026-08-23 | T533 获批修订 D13：工程线程连续，模型上下文按 Action 隔离且由 Supervisor 自动续作 |
| 2026-08-27 | 修复 component_verifier 成功路径遗漏 coverage_map 领域事件；真实 Claude 不再触发 STATE_PROJECTION_MISMATCH |
## 待解决问题
- 完成 `P0-E2E`：同一 Build 在 Codex/Claude 从单次设计命令连续运行到等价 `TERMINAL`；当前剩余 Claude Code 真实 L4。

## 引用文件
`design/v5.8-End-to-End-Product-Closure-Design.md` · `design/v5.8-Host-Runtime-Convergence-Design.md` · `design/v5.8-Session-Decoupling-Design.md` · `design/v5.8-Session-Decoupling-PLAN.md` · `design/incidents/2026-07-29-claude-146-tick-long-run.md` · `design/IMPLEMENTATION-TRACKER.md` · `design/HISTORY.md`
