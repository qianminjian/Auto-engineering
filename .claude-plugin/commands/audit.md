---
name: audit
description: 深度审计 — 架构/代码质量/工程化/协作/虚化度 5 维度扫描，含本项目参考项目对比
---

# /ae:audit — Auto-Engineering 项目深度审计

本项目特化版，在通用 `/audit` 基础上追加项目特定上下文。

## 项目上下文（自动注入审计 Agent）

- **语言**: Python
- **核心模块**: agents/ loop/ gates/ engine/ cli/ runtime/ tools/
- **设计基线**: `design/BEACON.md`
- **设计文档**: `design/v5.6-Design-Loop.md`
- **验收标准**: `docs/EARS-v5.0.md`
- **参考项目**:
  - LangGraph — `~/Documents/06-Mi-Model-Rule/历史项目或资料备份/auto-eng/references/langgraph/`（tick/after_tick 控制流）
  - AutoGen — `~/Documents/06-Mi-Model-Rule/历史项目或资料备份/auto-eng/references/autogen/`（AgentRuntime 懒实例化）
  - CrewAI — `~/Documents/06-Mi-Model-Rule/历史项目或资料备份/auto-eng/references/crewai/`（Guardrail 模式）

## 执行

执行通用 `/audit` 的 Phase 1→2→3 流程，但在 Phase 2 的每个 Agent prompt 中**追加**上述项目上下文（特别是参考项目路径，让 Agent 可以 Read 参考代码逐项对比）。

Phase 1 的自动化扫描使用项目特定命令:
```bash
make check-gate          # 静默吞异常闸门
make audit-dead-imports   # dead import
make audit-line-count     # 超 400 行文件
make audit-test-gap       # 测试缺口
```

Phase 2 的 3 个 Agent 必须:
1. 先 Read `design/BEACON.md` 对齐设计基线
2. 对比 `design/v5.6-Design-Loop.md` 中的设计约定与代码实际实现
3. 参考 LangGraph/AutoGen/CrewAI 对应模块，标注差异
4. 遵守 `@.claude/rules/audit-role.md` 的审计约束

报告文件: `_scratch/reports/YYYY-MM-DD-v5.4-audit.md`
