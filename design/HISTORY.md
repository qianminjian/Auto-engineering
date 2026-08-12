# Auto-Engineering 历史摘要

> 更新：2026-08-12｜本文件只保留里程碑和追溯入口；详细差异以 Git 为准。

## 里程碑

| 阶段 | 结果 |
|---|---|
| Phase 1-48 | 建立 Loop Engineering、Tick 协议、Checkpoint、Gate、Guardrail、五层验证、Init-Loop 消费契约与基础 CLI/Plugin |
| Phase 49 | 完成 Host-neutral Core、Claude Code/Codex Adapter 和双宿主发布基础验收 |
| Phase 50 | 完成 Codex 迁移收口、跨 Agent 规则同步、配置 SSOT、发布双层报告、文档重写与覆盖率提升 |
| Phase 51 | 将兼容性弃用告警纳入显式测试契约；基线 1889 passed / 1 skipped、覆盖率 90.15% |
| Phase 52 | 完成 Protocol Envelope v1.1、闭合 schema、Action/Result 因果身份、进程内与跨进程幂等、v1.0 受限兼容；基线 1913 passed / 1 skipped、覆盖率 90.21% |
| Phase 53 | 完成不可变 LoopEvent、SQLite EventStore、可重放 EngineState 投影、单 Tick 原子事务和 v5.6 checkpoint 一次性导入；基线 1945 passed / 1 skipped、覆盖率 90.14% |
| Phase 54-56 | 完成 Tick Kernel、全 StageHandler、Host SPI 2.0、十类黄金轨迹与跨宿主语义等价 |
| Phase 57-59 | 完成质量收口、双宿主真实安装和 release 自包含兼容加固；基线 2001 passed / 1 skipped |
| Phase 60 | 完成兼容式 Prompt Contract Compiler、全阶段上下文交付、多 Agent 独立 receipt、输出兼容警告和不可覆盖 rendered 日志；基线 2019 passed / 1 skipped、覆盖率 90.27% |
| Phase 61 | 发布 v5.7.1 候选包，补齐宿主逐 Worker 提示词执行协议与插件载荷零告警；双宿主 archive、真实安装缓存和 Prompt Contract 链路通过；基线 2021 passed / 1 skipped、覆盖率 90.27% |
| Phase 62 | 完成 Claude 宿主输出诊断、计划去漂移、双宿主隔离 init/status/resume、Node 24 与 OTEL 发布门禁加固；正式发布 v5.7.1 并核验远端 SHA-256；基线 2023 passed / 1 skipped、覆盖率 90.28% |
| Phase 63 | 完成非交互配置治理；`require/defaults/create` 策略与配置来源报告通过真实 CLI 和回归测试 |
| Phase 64-66 | 完成真实运行可信度止血、确定性状态与宿主会话解耦、有界 Prompt、ArtifactRef、Usage Ledger、摘要隔离与循环预算；基线 2095 passed / 1 skipped |
| Phase 67 | 故障恢复与成本基线已通过；双宿主真实 LLM 项目与 v5.8 发布收口验收中 |
| Phase 73 | 以 ProjectProfile 解除 Init Engineering 运行时前置依赖；T359-T366 已完成，T367 仅剩真实双宿主 LLM 轨迹 |
| 146-Tick 事故归档 | 永久记录输入超限、批次回退、验证假通过和空快照证据；补充 T322-T324 |
| Phase 74-75 | 深度审计修复与真跑准入加固完成；2166 passed / 1 skipped、coverage 90.41%、双宿主 archive smoke 通过；真实 LLM 长跑、历史秘密确认和依赖审计仍未闭环 |
| Phase 76-77 | 统一设计文档入口；rc.4 真跑证伪后恢复原始批量 Gap Review、Action schema fail-closed、公共 status 与 Gate 语义；rc.5 基线 2178 passed / 1 skipped |
| Phase 78-79 | 修复架构基线、Gate 转移、PlanPatch 与 Contract 激活；自动门禁通过但真实产品复验未关闭 |
| Phase 80 | 2026-08-09 T403-T410 协议内核收敛完成；T413 显式绑定 Codex `spawn_agent` 与推理强度，禁止工具调用前主观判定能力缺失；真实双宿主产品长跑仍阻断发布 |
| Phase 81-82 | 状态协调与 Gap/Repair 完成；T440-T444 已闭合严格 Host 合同、设计批准链、真实 EventStore 故障矩阵和双宿主黄金生命周期，T445 已建立 Hermetic/同 Build 证据门禁，真实产品 L3/L4 仍阻断发布 |
| Phase 82 T447-T450 | 持久化旧 Build Worker 角色误判事故；补齐 spawn 失败恢复、线程级结构化 Gap 推荐授权和 RuntimeConfig→Action 配置事实链 |
| Phase 82 T451-T453 | 真跑证伪宿主手工拼接 Worker 证明；补齐平台化证明模板、原生句柄/协议身份分离、纯 EventStore 恢复诊断和三 Worker 生产 Tick 轨迹 |

## 持续有效的决策

- Core 只负责确定性治理，不在 Python 内调用 LLM。
- 宿主负责推理、工具执行和原生 Agent 调度。
- Claude Code 与 Codex 共用生成规则、Skill 协议和 `scripts/ae-run`。
- Init Engineering 是独立项目；Core 通过中立 ProjectProfile 消费项目能力，Init manifest
  仅作为迁移期只读兼容输入。
- archive smoke 与真实产品安装验收必须分开报告。
- v5.7.1 是当前正式发布实现；v5.8.0-rc.5 纠偏实现和自动门禁已完成，待双宿主真实 LLM 项目、历史秘密确认和依赖审计通过后发布。
- Phase 80 完成前冻结新的点状真跑补丁；活动 Action 边界升级、机器化宿主续跑、显式
  领域 Reducer 和纯 ActionCompiler 必须作为一个架构闭环实施。

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
