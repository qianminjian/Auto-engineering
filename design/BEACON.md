# Auto-Engineering BEACON
> 创建：2026-06-24｜更新：2026-08-12｜阶段：Phase 81 状态协调与真跑修复
> 决策状态翻转（✅↔❌）或架构降级必须先获用户批准。

## 目标与成功标准
1. 定位为跨 Agent 宿主的确定性工程治理内核。
2. 宿主负责推理与工具执行；Core 负责协议、状态、验证、安全和审计。
3. 所有跨宿主消息使用版本化协议，并具有消息身份与因果关系。
4. 状态可由 append-only 事件重放，重复 Result 不重复推进。
5. Claude Code 与 Codex 对同一黄金轨迹产生等价 Core 结果。

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
| D13 | 宿主自动 compaction；固定 Tick 不换会话；Capsule 仅用于异常恢复 | ✅ |
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

## 当前状态

- Phase 1-79 的功能与自动门禁历史见 Tracker/HISTORY；v5.8.0-rc.5 仍未通过真实产品长跑门禁。
- 2026-08-09 架构审计确认 Phase 54/55 的目标出口未完全成立：旧可变
  TickOrchestrator、全状态事件补丁、线程级 Prompt 锁和非机器化续跑仍在生产路径。
- 方案 B 已批准；Phase 80 按 Runtime Vector、Execution Control、显式 Reducer、纯
  ActionCompiler 和 Stage-by-Stage strangling 统一收敛，完成前冻结新的点状真跑补丁。
- T404-T410、T413-T420 已通过自动门禁；真实 rc.5 旧流已在隔离副本从 Architect
  恢复到 Developer，TickOrchestrator 已无具体 Stage 分支。
- 当前发布阻断只剩 T411-T412 的真实双宿主产品长跑与发布证据收口；自动门禁为
  2266 passed/1 skipped、coverage 90%、Ruff/mypy、双宿主 archive smoke 通过。
- 最新真跑证明隐藏 `.ae-state` 可覆盖本次显式设计文档；Phase 81 在任何新 RC 前完成
  InvocationIntent、状态协调 Gate、可恢复重开、计划协调和可信验证证据。
- T432 已关闭 Gap wizard、计划路由、Critic replay、Result SSOT、新项目证据和 setup 预检缺陷；真实产品长跑仍独立阻断发布。
## 最近演进
| 日期 | 变更 |
|---|---|
| 2026-08-12 | 关闭 T432 真跑差距：单项 Gap wizard、多 key 路由、Critic replay 与新项目证据 |
| 2026-08-09 | 批准状态冲突二选一：重新初始化或修复状态续作 |
| 2026-08-09 | 关闭 rc.5 旧事件重放、PlanPatch 候选分叉与 Build Identity 事故 |
| 2026-08-09 | 修复 Codex Architect 对原生 `spawn_agent` 的错误能力判定 |
| 2026-08-09 | 完成 T404-T410 协议内核收敛；façade 退出 Stage 专属分支 |
| 2026-08-06 | 归档 Tick 19 PlanPatch 冲突；禁止 full-plan refine，按义务延迟激活 Contract |
| 2026-07-30 | 批准 Phase 70：撤销固定 Tick rollover，改为宿主自动 compaction |
| 2026-08-02 | 再次审计：自动门禁可进入受控真跑，真实 LLM 长跑仍是发布阻断项 |
## 待解决问题

- T411-T412、T422-T430：Phase 81 完成后重做跨版本与双宿主真实产品门禁。
- T421：清理测试套件中 SQLite connection `ResourceWarning`，不阻断本次协议修复。

## 引用文件

`design/v5.8-Session-Decoupling-Design.md` · `design/v5.8-Session-Decoupling-PLAN.md` · `design/incidents/2026-07-29-claude-146-tick-long-run.md` · `design/v5.8-State-Reconciliation-Design.md` · `design/v5.8-Gap-Review-Wizard-Design.md` · `design/incidents/2026-08-11-gap-review-wizard-real-run.md` · `design/IMPLEMENTATION-TRACKER.md` · `design/HISTORY.md`
