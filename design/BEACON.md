# Auto-Engineering BEACON

> 创建：2026-06-24｜更新：2026-07-28｜阶段：Phase 62 v5.7.1 正式发布完成
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
| D7 | 采用双基线：v5.6 是当前实现，v5.7 是已批准目标 | ✅ |
| D8 | v5.7 采用渐进协议内核重构，不建立双内核 | ✅ |
| D9 | 事件是事实源，EngineState 是可重建投影 | ✅ |
| D10 | Prompt Contract 采用兼容式编译，不改变 Action/Result v1.1 核心语义 | ✅ |
| D11 | 多 Agent 必须逐 Worker 交付上下文并提供独立完成回执 | ✅ |

## 当前状态

- Phase 1-62 已完成；当前基线为 2023 passed / 1 skipped，覆盖率 90.28%。
- LoopEvent、SQLite EventStore、EngineState Projector 和单 Tick 原子事务已落地。
- 11 个 Stage 已全部唯一注册 Handler；旧 stage-specific `_after_*` 已移除。
- Host SPI 2.0、十类黄金轨迹、故障恢复和跨宿主语义等价已验收。
- 双宿主 archive smoke 通过；Claude Code 真实安装与命令调用通过。
- Phase 57 已完成告警归零与验收文档去漂移。
- Codex CLI 已从 0.135.0 升级到 0.145.0；真实安装、启用、安装缓存
  `doctor`、`gpt-5.6-sol` 新进程 Skill 加载和 status 调用均已通过。
- v5.6 checkpoint 可一次性只读导入；旧调用入口在迁移期保持兼容。
- Phase 59 已完成只读 SQLite、双宿主自包含 marketplace、manifest 零告警和
  release 安全解压兼容；v5.7.0 release 已在两个真实宿主中安装并识别。
- Phase 60 已完成 Prompt Contract、全阶段上下文编译、多 Agent 独立 receipt、
  Result 兼容警告和不可覆盖 rendered 日志。
- Phase 62 已完成宿主诊断、计划同步、双宿主隔离生命周期、零告警 CI 加固和
  v5.7.1 GitHub Release；远端制品 SHA-256 已核验，阻塞：无。

## 最近演进

| 日期 | 变更 |
|---|---|
| 2026-07-28 | Phase 62 完成 T295-T300，v5.7.1 GitHub Release 正式发布 |
| 2026-07-28 | Phase 62 启动 v5.7.1 正式发布，T295-T300 进行中 |
| 2026-07-28 | Phase 61 完成 v5.7.1 发布收口，T288-T294 全部验证 |
| 2026-07-28 | Phase 60 完成 T280-T287；2019 passed / 1 skipped，coverage 90.27% |
| 2026-07-28 | 批准 Phase 60 兼容式 Prompt Contract Compiler 与多 Agent 交付完整性重构 |
| 2026-07-28 | Phase 59 完成 T275-T279，release-v3 双宿主真实安装调用通过 |
| 2026-07-28 | Codex CLI 升级至 0.145.0，关闭 T274，登记只读 SQLite 兼容问题 T275 |
| 2026-07-28 | Phase 58 Claude Code 真实安装通过；Codex 安装通过、端到端调用环境阻塞 |
| 2026-07-28 | Phase 57 完成资源告警归零与验收文档命令去漂移 |
| 2026-07-28 | Phase 56 完成黄金轨迹、故障恢复、跨宿主等价与 v5.7 收口 |
| 2026-07-28 | Phase 55 完成 Host SPI 2.0、双宿主映射与能力 fail closed |
| 2026-07-27 | 批准 v5.7 渐进式协议内核重构与双基线策略 |

## 待解决问题

- 无发布阻断项；Claude `-p` 空输出已定位为双安装/自定义 endpoint 宿主环境问题。

## 引用文件

`design/v5.6-Design-Loop.md` · `design/v5.7-Protocol-Kernel-Design.md` · `design/v5.7-Protocol-Kernel-PLAN.md` · `design/v5.7-Prompt-Contract-Design.md` · `design/v5.7-Prompt-Contract-PLAN.md` · `design/IMPLEMENTATION-TRACKER.md` · `design/HISTORY.md`
