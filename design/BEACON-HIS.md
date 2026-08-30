# Auto-Engineering BEACON 历史

> 从 `design/BEACON.md` 归档的设计演进摘要。当前目标、有效决策和任务状态仍以 BEACON、权威设计与 Tracker 为准；更完整差异以 Git 为准。

## 最近归档演进

| 日期 | 变更 |
|---|---|
| 2026-08-23 | T533 获批修订 D13：工程线程连续，模型上下文按 Action 隔离且由 Supervisor 自动续作 |
| 2026-08-28 | 真跑证伪 T465 局部验收；D46 统一有效设计权威投影，收口 Research→Approval→Fresh Architect→Developer 因果轨迹 |
| 2026-08-28 | 真跑发现人工 Gate 被错误映射为 CONTINUE；T558 收敛 Gate→ExecutionControl 单一判定并兼容旧快照 |
| 2026-08-28 | 真跑发现 rejected journal 未恢复 Worker 事实，导致重复回执冲突和无终态停滞；T559 收敛 repair-only 恢复与冲突终止 |
| 2026-08-29/30 | 全场景审计补齐跨平台路径、Lease、Phase 0、advisory、重试与清理边界（T563-T570）；Codex 加固 finite usage、bounded audit、Host Runtime budgets、Tick rollback、protocol/prompt fail-closed、`.ae-runtime` hermetic hooks；T579-T586 收口 Worker 超时、outcomes 合同、repair 隔离、Supervisor 心跳、只读状态、Build 证据和事故回放；真跑回放进一步发现失败类别串扰、Research null 契约漂移、refine coverage 投影缺失和 Verifier 范围失控，纳入 T589-T595；Build `5.8.0-rc.5+sha256.4f32a506f46b0f94` archive smoke 通过；8-30 又修复 Worker 无结构化产出误报 `HOST_OUTCOME_INPUT_INVALID`，并改为私有 outcome artifact→Collector→Assembler 的统一生命周期 |
| 2026-08-30 | D13 原批准标记为存在争议；D53-D56 明确恢复主 Agent 协调权、Artifact 恢复边界、预算默认 soft、失败路由和 Supervisor 先旁路后退役 |

## 归档规则

- BEACON 只保留当前目标、有效决策、当前状态和下一步。
- 已被新决策取代但仍有审计价值的条目保留在 BEACON 决策表，并标记 `⚠️`；不通过归档抹除争议。
- 设计演进摘要移入本文件；阶段性完成证据继续归档到 `design/HISTORY.md`。
- 本文件不作为运行时状态源，也不替代 EventStore、Tracker 或 Git。
