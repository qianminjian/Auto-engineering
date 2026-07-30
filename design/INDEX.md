# design/ 资产索引

> 更新：2026-07-30｜当前实现：v5.8.0-rc.2；Phase 68 真跑缺陷修复中

## 当前权威资产

| 文件 | 用途 |
|---|---|
| `BEACON.md` | 北方之星、范围、批准决策与下一步（≤80 行） |
| `v5.6-Design-Loop.md` | 当前已实现行为与兼容基线 |
| `v5.7-Protocol-Kernel-Design.md` | 已批准的协议内核目标设计 |
| `v5.7-Protocol-Kernel-PLAN.md` | Phase 52-56 可执行实施计划 |
| `v5.7-Prompt-Contract-Design.md` | Phase 60 Prompt Contract 与多 Agent 交付设计 |
| `v5.7-Prompt-Contract-PLAN.md` | Phase 60 T280-T287 TDD 实施计划 |
| `v5.8-Session-Decoupling-Design.md` | Phase 64-67 确定性状态、宿主会话、上下文预算与验证可信度设计 |
| `v5.8-Session-Decoupling-PLAN.md` | Phase 64-67 T302-T324 可执行实施计划 |
| `incidents/2026-07-29-claude-146-tick-long-run.md` | 146-Tick 真跑事故事实、根因、任务映射与关闭标准 |
| `incidents/2026-07-30-claude-rc1-partial-run.md` | rc.1 部分真跑的跨进程状态、Gate、Usage 与成本缺陷 |
| `IMPLEMENTATION-TRACKER.md` | 当前任务状态、优先级与 EARS 验收 |
| `HISTORY.md` | 历史里程碑与 Git 追溯入口 |

## 解释顺序

1. 当前运行行为以 v5.6 设计、代码和新鲜测试证据为准。
2. 尚未实现的目标行为以 v5.8 设计为准，不得伪装为已交付。
3. 实施顺序和任务状态以 PLAN 与 Tracker 为准。
4. 历史争议以 Git 记录追溯，不把旧报告继续保存在活动工作区。

## 维护规则

1. 修改架构前同步 BEACON、目标设计、计划和 Tracker。
2. 完成任务后记录新鲜验证，不用历史通过替代。
3. 被替代设计、测试报告和临时分析删除后由 Git 或外部备份承担恢复。
4. 设计与代码不一致时默认补齐代码，不通过降低设计标准消除差异。
