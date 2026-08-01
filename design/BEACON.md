# Auto-Engineering BEACON

> 创建：2026-06-24｜更新：2026-08-01｜阶段：Phase 73 自动门禁通过，待真实宿主轨迹
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

**不做：** Core 内调用 LLM；复制宿主 Agent Runtime；恢复退役 CLI；实现 Init
Engineering 的问答、模板或脚手架；把 archive smoke 冒充真实产品安装；修改外部参考源码。

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

## 当前状态

- Phase 1-62 已完成；协议、事件状态、11 个 StageHandler、Host SPI 2.0、Prompt
  Contract、迁移兼容、双宿主黄金轨迹与 v5.7.1 Release 已验收。
- Phase 64 已完成真实运行可信度止血：计划增量、Gate runner、空快照与状态不变量
  均 fail-closed。
- Phase 65 已完成会话解耦：ContextBudget、ResumeCapsule、rollover/claim、SQLite
  原子接管与双宿主适配落地；150 Tick/3 sessions 验收通过。
- Phase 66 已完成有界 Prompt、ArtifactRef、Usage Ledger、摘要隔离与循环预算；
  全量 2095 passed / 1 skipped，Ruff/mypy/sync 通过。
- Phase 68 T326-T335 已完成：快照、线程租约、Gate/Findings、Usage、Result、
  稳定身份、checkpoint 与成本治理已修复；T336 等待 Claude Code 真实复验。
- Phase 69 已完成：标准 Profile、强制首次配置与双宿主 archive smoke 通过。
- Phase 72 已修复插件 runner 误解析到目标项目；rc.4 自动门禁通过。
- Phase 73 T359-T366 已完成；T367 自动门禁 2153 passed / 1 skipped、coverage
  90%、静态检查与双宿主 archive install 通过，待真实 LLM 轨迹。

## 最近演进
| 日期 | 变更 |
|---|---|
| 2026-07-31 | 批准 D16：解除 Init Engineering 运行时前置依赖，保留只读兼容 Provider |
| 2026-07-30 | 批准 Phase 70：撤销固定 Tick rollover，改为宿主自动 compaction |
| 2026-07-29 | 批准 v5.8 确定性状态与宿主会话解耦，登记 Phase 64-67 |
| 2026-07-29 | 归档 146-Tick 真跑事故报告，补充摘要隔离与循环预算 |
| 2026-07-28 | Phase 62 完成 T295-T300，v5.7.1 GitHub Release 正式发布 |

## 待解决问题

- T336/T350：用发布候选版执行 Claude Code/Codex 真实产品 150 Tick 长跑。
- T367：完成 Phase 73 全量、覆盖率、双宿主制品与真实产品轨迹验收。

## 引用文件

`design/v5.8-Automatic-Context-Governance.md` · `design/v5.8-Session-Decoupling-Design.md` · `design/v5.8-Session-Decoupling-PLAN.md` · `design/v5.8-Init-Runtime-Decoupling-Design.md` · `design/incidents/2026-07-29-claude-146-tick-long-run.md` · `design/IMPLEMENTATION-TRACKER.md` · `design/HISTORY.md`
