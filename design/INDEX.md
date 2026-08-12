# design/ 资产索引

> 更新：2026-08-12｜当前实现：v5.8.0-rc.5；Phase 81 自动修复完成，真实产品长跑待验

## 当前权威资产

| 文件 | 用途 |
|---|---|
| `BEACON.md` | 北方之星、范围、批准决策与下一步（≤80 行） |
| `v5.6-Design-Loop.md` | 当前已实现行为与兼容基线 |
| `v5.7-Protocol-Kernel-Design.md` | 已批准的协议内核目标设计 |
| `v5.7-Protocol-Kernel-PLAN.md` | Phase 52-56 可执行实施计划 |
| `v5.7-Prompt-Contract-Design.md` | Phase 60 Prompt Contract 与多 Agent 交付设计 |
| `v5.7-Prompt-Contract-PLAN.md` | Phase 60 T280-T287 TDD 实施计划 |
| `v5.8-Protocol-Kernel-Convergence-Design.md` | Phase 80 当前权威收敛设计；统一 Host/Core/Event/Prompt/Session 边界 |
| `v5.8-Protocol-Kernel-Convergence-PLAN.md` | Phase 80 T403-T412 分波次 TDD 实施计划 |
| `v5.8-State-Reconciliation-Design.md` | Phase 81 显式启动意图、状态冲突二选一、任务续作与验证证据设计 |
| `v5.8-State-Reconciliation-PLAN.md` | Phase 81 T423-T430 逐步 TDD 实施计划 |
| `v5.8-Gap-Review-Wizard-Design.md` | T432 单项 Gap 向导、计划路由、事件恢复与新项目证据设计 |
| `v5.8-Automatic-Context-Governance.md` | Phase 70 自动 compaction、有界增量上下文与成本治理权威设计 |
| `v5.8-Session-Decoupling-Design.md` | Phase 64-67 状态恢复设计；日常 rollover 已由 Phase 70 纠偏 |
| `v5.8-Session-Decoupling-PLAN.md` | Phase 64-70 T302-T350 可执行实施计划 |
| `v5.8-Deep-Audit-Remediation-PLAN.md` | Phase 74 T368-T376 深度审计修复计划 |
| `v5.8-Deep-Audit-Report-2026-08-02.md` | Phase 75 自动门禁、风险和真实宿主准入证据 |
| `v5.8-Architecture-Baseline-and-Repair-Design.md` | Phase 78 架构事实、Gate 转移、义务覆盖与修复控制权威设计 |
| `v5.8-Architecture-Baseline-and-Repair-PLAN.md` | Phase 78 T387-T396 TDD 实施计划 |
| `incidents/2026-07-29-claude-146-tick-long-run.md` | 146-Tick 真跑事故事实、根因、任务映射与关闭标准 |
| `incidents/2026-07-30-claude-rc1-partial-run.md` | rc.1 部分真跑的跨进程状态、Gate、Usage 与成本缺陷 |
| `incidents/2026-07-30-claude-9-tick-evidence-chain.md` | 9-Tick 真跑的旧版本识别、Debug 编号、进度与版本溯源缺陷 |
| `incidents/2026-08-05-rc5-15-tick-architecture-gate-failure.md` | rc.5 15-Tick 的 Gate fail-open、架构事实丢失与错误修复路由事故 |
| `incidents/2026-08-09-hidden-state-stale-resume.md` | 隐藏 `.ae-state` 覆盖显式设计文档并错误恢复旧 B2 的事故 |
| `incidents/2026-08-11-gap-review-wizard-real-run.md` | Gap 批量决策、计划标识、Critic replay 与新项目证据事故及关闭证据 |
| `IMPLEMENTATION-TRACKER.md` | 当前任务状态、优先级与 EARS 验收 |
| `HISTORY.md` | 历史里程碑与 Git 追溯入口 |

## 解释顺序

1. Phase 80 目标架构与迁移边界以 Protocol Kernel Convergence 为准；当前剩余未迁移行为
   仍以 v5.6 设计、代码和新鲜测试证据为准，不得把目标误称为已实现。
2. 上下文与日常会话行为以 Automatic Context Governance 为准；恢复语义再读取
   Session Decoupling，冲突时前者优先。
3. 实施顺序和任务状态以 PLAN 与 Tracker 为准。
4. 历史争议以 Git 记录追溯，不把旧报告继续保存在活动工作区。
5. 真实产品验收必须独立记录 `product_install`；archive smoke 通过不等于宿主产品通过。

## 维护规则

1. 修改架构前同步 BEACON、目标设计、计划和 Tracker。
2. 完成任务后记录新鲜验证，不用历史通过替代。
3. 被替代设计、测试报告和临时分析删除后由 Git 或外部备份承担恢复。
4. 设计与代码不一致时默认补齐代码，不通过降低设计标准消除差异。
