# Auto-Engineering BEACON

> 创建：2026-06-24｜更新：2026-07-30｜阶段：v5.8 Phase 66 完成，Phase 67 验收中
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
Engineering；把 archive smoke 冒充真实产品安装；修改外部参考源码。

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
| D13 | Core 按 ContextBudget 发出 rollover；新会话仅消费 ResumeCapsule | ✅ |
| D14 | 修复计划使用 PlanPatch；完成事实不可由普通计划更新重新激活 | ✅ |
| D15 | runner 错配、零测试、空快照和证据失配全部 fail-closed | ✅ |

## 当前状态

- Phase 1-62 已完成；当前发布基线为 v5.7.1、2023 passed / 1 skipped、覆盖率 90.28%。
- LoopEvent、SQLite EventStore、EngineState Projector 和单 Tick 原子事务已落地。
- 11 个 Stage 已全部唯一注册 Handler；旧 stage-specific `_after_*` 已移除。
- Host SPI 2.0、十类黄金轨迹、故障恢复和跨宿主语义等价已验收。
- 双宿主 archive smoke、Claude Code/Codex 真实安装、命令与 `doctor` 已通过。
- v5.6 checkpoint 可一次性只读导入；旧调用入口在迁移期保持兼容。
- Phase 59 已完成只读 SQLite、自包含 marketplace、manifest 与 release 安全解压。
- Phase 60 已完成 Prompt Contract、全阶段上下文编译、多 Agent 独立 receipt、
  Result 兼容警告和不可覆盖 rendered 日志。
- Phase 62 已完成宿主诊断、计划同步、双宿主隔离生命周期、零告警 CI 加固和
  v5.7.1 GitHub Release；远端制品 SHA-256 已核验，阻塞：无。
- Phase 64 已完成真实运行可信度止血：计划增量、Gate runner、空快照与状态不变量
  均 fail-closed。
- Phase 65 已完成会话解耦：ContextBudget、ResumeCapsule、rollover/claim、SQLite
  原子接管与双宿主适配落地；150 Tick/3 sessions 验收通过。
- Phase 66 已完成有界 Prompt、ArtifactRef、Usage Ledger、摘要隔离与循环预算；
  全量 2095 passed / 1 skipped，Ruff/mypy/sync 通过。
- Phase 67 已生成 `5.8.0-rc.1` 候选包并通过 Claude archive smoke；真实产品 LLM
  项目仍为 `not_run`，不得发布正式版。

## 最近演进

| 日期 | 变更 |
|---|---|
| 2026-07-30 | Phase 64-66 完成，开始 Phase 67 双宿主真实项目门禁 |
| 2026-07-29 | 批准 v5.8 确定性状态与宿主会话解耦，登记 Phase 64-67 |
| 2026-07-29 | 归档 146-Tick 真跑事故报告，补充摘要隔离与循环预算 |
| 2026-07-28 | Phase 62 完成 T295-T300，v5.7.1 GitHub Release 正式发布 |
| 2026-07-28 | Phase 61 完成 v5.7.1 发布收口，T288-T294 全部验证 |

## 待解决问题

- T319-T321：完成双宿主真实项目、故障恢复与发布收口门禁。

## 引用文件

`design/v5.8-Session-Decoupling-Design.md` · `design/v5.8-Session-Decoupling-PLAN.md` · `design/incidents/2026-07-29-claude-146-tick-long-run.md` · `design/IMPLEMENTATION-TRACKER.md` · `design/HISTORY.md`
