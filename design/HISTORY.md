# Auto-Engineering 历史摘要

> 更新：2026-07-28｜本文件只保留里程碑和追溯入口；详细差异以 Git 为准。

## 里程碑

| 阶段 | 结果 |
|---|---|
| Phase 1-48 | 建立 Loop Engineering、Tick 协议、Checkpoint、Gate、Guardrail、五层验证、Init-Loop 消费契约与基础 CLI/Plugin |
| Phase 49 | 完成 Host-neutral Core、Claude Code/Codex Adapter 和双宿主发布基础验收 |
| Phase 50 | 完成 Codex 迁移收口、跨 Agent 规则同步、配置 SSOT、发布双层报告、文档重写与覆盖率提升 |
| Phase 51 | 将兼容性弃用告警纳入显式测试契约；基线 1889 passed / 1 skipped、覆盖率 90.15% |
| Phase 52 | 完成 Protocol Envelope v1.1、闭合 schema、Action/Result 因果身份、进程内与跨进程幂等、v1.0 受限兼容；基线 1913 passed / 1 skipped、覆盖率 90.21% |
| Phase 53 | 完成不可变 LoopEvent、SQLite EventStore、可重放 EngineState 投影、单 Tick 原子事务和 v5.6 checkpoint 一次性导入；基线 1945 passed / 1 skipped、覆盖率 90.14% |
| Phase 54-56 | 已批准待实施：Tick Kernel、Host SPI 2.0 与黄金轨迹 |

## 持续有效的决策

- Core 只负责确定性治理，不在 Python 内调用 LLM。
- 宿主负责推理、工具执行和原生 Agent 调度。
- Claude Code 与 Codex 共用生成规则、Skill 协议和 `scripts/ae-run`。
- Init Engineering 是独立项目，本项目只消费其 manifest。
- archive smoke 与真实产品安装验收必须分开报告。
- v5.6 是当前实现基线，v5.7 是已批准目标基线。

## 已清理资产

2026-07-27 起，活动工作区不再保留以下重复或临时内容：

- pre-Phase 50 的 BEACON、Tracker 和完整设计副本。
- 已完成的 Phase 50 设计/计划与真跑计划。
- 历史讨论、对标草稿、示例规格和阶段性文档备份。
- `_scratch/` 报告、prompt 日志、benchmark 输出、coverage 数据和系统杂项。

上述 tracked 内容仍可由 Git 恢复；ignored 内容由用户的物理备份承担恢复。

## 近期 Git 追溯

| Commit | 主题 |
|---|---|
| `1614d4f` | Phase 50 收口相关变更 |
| `5205a95` | Codex 迁移与规则资产 |
| `f3b41ac` | Host-neutral/双宿主相关变更 |
| `755bcfa` | 设计与实施资产演进 |
| `4093256` | 前序工程基线 |

使用 `git show <commit>` 查看当时文件，使用 `git log --all -- <path>` 追溯已删除资产。
