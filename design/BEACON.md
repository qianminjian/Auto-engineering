# Auto-Engineering BEACON

> 创建：2026-06-24｜更新：2026-07-28｜阶段：v5.7 Phase 52-56 已完成
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

## 当前状态

- Phase 1-56 已完成；当前基线为 1996 passed / 1 skipped，覆盖率 90.35%。
- LoopEvent、SQLite EventStore、EngineState Projector 和单 Tick 原子事务已落地。
- 11 个 Stage 已全部唯一注册 Handler；旧 stage-specific `_after_*` 已移除。
- Host SPI 2.0、十类黄金轨迹、故障恢复和跨宿主语义等价已验收。
- 双宿主 archive smoke 通过；真实产品安装保持 `not_run`。
- v5.6 checkpoint 可一次性只读导入；旧调用入口在迁移期保持兼容。
- 阻塞：无；真实产品安装状态保持 `not_run`。

## 最近演进

| 日期 | 变更 |
|---|---|
| 2026-07-28 | Phase 56 完成黄金轨迹、故障恢复、跨宿主等价与 v5.7 收口 |
| 2026-07-28 | Phase 55 完成 Host SPI 2.0、双宿主映射与能力 fail closed |
| 2026-07-28 | Phase 54 完成无状态 ActionBuilder、全 StageHandler 与统一终态 |
| 2026-07-28 | Phase 53 完成 Event Store、可重放投影、原子事务和 checkpoint 导入 |
| 2026-07-27 | Phase 52 完成 Protocol Envelope v1.1、跨进程幂等与受限兼容入口 |
| 2026-07-27 | 批准 v5.7 渐进式协议内核重构与双基线策略 |
| 2026-07-27 | Phase 51 收口兼容性告警，全量测试输出零告警 |
| 2026-07-27 | Phase 50 完成 Codex 迁移、配置 SSOT 和双层发布验收 |
| 2026-07-27 | Phase 49 完成 Host-neutral Core 与双宿主基础适配 |

## 待解决问题

- 下一阶段需基于真实宿主产品安装结果决定发布或继续兼容性加固。

## 引用文件

`design/v5.6-Design-Loop.md` · `design/v5.7-Protocol-Kernel-Design.md` ·
`design/v5.7-Protocol-Kernel-PLAN.md` · `design/IMPLEMENTATION-TRACKER.md` ·
`design/HISTORY.md`
