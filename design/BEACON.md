# Auto-Engineering BEACON

> 创建：2026-06-24｜更新：2026-07-27｜阶段：Phase 50 实施中
> 决策状态翻转（✅↔❌）或架构降级必须先获用户批准。

## 目标与成功标准

1. 以 `TickOrchestrator` 为唯一 Core 状态机，通过离散 Tick 驱动工程循环。
2. Claude Code 与 Codex 只在 Host Adapter 层体现差异，Core 不感知宿主。
3. Guardrail、Gate、五层验证、Checkpoint 与 Init-Loop 契约保持可测试。
4. 当前设计、运行配置、测试基线和发布验收均有唯一事实源。
5. Claude Code 使用 `/ae:dev-loop`，Codex 使用 `$auto-engineering`；二者共用 `scripts/ae-run`。

## 范围边界

**做：** Tick 协议、Host Adapter、双宿主资产、配置 SSOT、Release 双层验收、当前文档。

**不做：** 在 Python Core 内调用 LLM；恢复已退役 CLI；实现 Init Engineering；把模拟宿主信号冒充真实产品安装；修改外部参考源码。

## 当前设计决策

| ID | 决策 | 状态 |
|---|---|:---:|
| D1 | Core 只做确定性状态转换，Agent 在 Tick 之间完成推理与工具调用 | ✅ |
| D2 | `HostAdapter` 统一检测、能力、事件、CLI 和 usage source | ✅ |
| D3 | Claude/Codex 共用规则模板、Skill 协议和 `scripts/ae-run` | ✅ |
| D4 | `FeatureManifest` 是 `AE_*` 默认值唯一事实源；Provider SDK 可选 | ✅ |
| D5 | Release 报告分开记录 archive smoke 与真实 product install | ✅ |
| D6 | 历史设计只读归档，当前入口保持短小且可追溯 | ✅ |

## 当前状态

- Phase 49：22/22，双宿主基础适配完成。
- Phase 50：7/8；T233-T239 完成。
- 正在执行：T240 全量验收与收口。
- 下一步：补足真实覆盖率至 ≥90%，再完成 T240。
- 阻塞：当前全量覆盖率 84.51%，低于项目 90% 硬门禁；不得通过缩小统计范围降级。

## 最近演进

| 日期 | 变更 |
|---|---|
| 2026-07-27 | T237 将 archive smoke 与 product install 状态分离 |
| 2026-07-27 | T236 完成 manifest、依赖与配置 SSOT |
| 2026-07-27 | T235 落地 Claude/Codex `HostAdapter` 完整契约 |
| 2026-07-27 | T233-T234 修复测试真实性并同步跨 Agent 规则 |
| 2026-07-27 | Phase 49 完成 Host-neutral Core 与双宿主 Release 基础验收 |

## 待解决问题

- T238：完成归档索引及当前设计入口验证。
- T239：移除 README、用户指南、API 与培训手册中的退役能力宣称。
- T240：sync、metadata、Ruff、mypy、1815 tests 与双宿主 archive smoke 已通过；
  覆盖率 84.51% 未达 90%，真实产品安装仍为 `not_run`。
- 真实 Claude Code/Codex 产品安装验收由用户在对应产品中执行，自动报告保持 `not_run`。

## 引用文件

`design/v5.6-Design-Loop.md` · `design/IMPLEMENTATION-TRACKER.md` · `design/phase50-codex-migration-closure-design.md` · `design/archive/INDEX.md`
