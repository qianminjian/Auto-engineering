---
name: audit
description: 深度审计 — 架构/代码质量/工程化/协作/虚化度 5 维度扫描，含本项目参考项目对比
---

# /auto-engineering:audit — Auto-Engineering 项目深度审计

自含审计流程 — 委托项目自有 AuditGate + system_deep_audit 方法论，
**不依赖任何外部 `/audit` 运行时**（B14：零外部运行时依赖）。

## 项目上下文（自动注入审计 Agent）

- **语言**: Python
- **核心模块**: agents/ loop/ gates/ engine/ cli/ runtime/ tools/
- **设计基线**: `design/BEACON.md`
- **设计文档**: `design/BEACON.md`、`design/INDEX.md`、`design/v5.8-Main-Agent-Coordinator-Recovery-Design.md`、`design/v5.8-Scheme-A-Convergence-Plan.md`
- **验收标准**: `design/v5.8-Real-Host-Acceptance-Runbook.md` 与 `design/IMPLEMENTATION-TRACKER.md`
- **外部对标**: 仅按 AGENTS.md 的“Grep 定位 → 片段读取”规则单文件、只读、按需对标；禁止并行或全量扫描参考源码。

## 执行（三阶段，自含）

### Phase 1 — 自动化确定性扫描（项目自有 Gate）

```bash
# Phase 40: ae gate-check CLI 已删除。Gate 在 dev-loop 的单 Tick 提交中自动运行。
make check-gate           # 静默吞异常闸门
make audit-dead-imports   # dead import (F401)
make audit-line-count     # 超 400 行文件
make audit-test-gap       # 测试缺口
```

AuditGate 的 5 维静态扫描提供确定性基线 findings（`gates/audit.py`），
无需 LLM，可复现。

### Phase 2 — 隔离只读深度审计（内化 system_deep_audit 方法论，§B6.7a）

按 `loop/deep_audit.py` 的 `AUDIT_DIMENSIONS` 分配最多 3 个隔离只读审计任务，
遵守项目内存约束，不并行扫描外部参考源码；各自 Read 有界上下文后产出结构化 findings ——
**不委托任何外部 `/audit` 命令**：

| 子 Agent | agent_source | 覆盖维度（audit-role.md 5 维映射）|
|---------|--------------|--------------------------------|
| 架构审计 | `architecture` | 架构合理性 + 代码逻辑虚化度 |
| 质量审计 | `code_quality` | 代码质量 + 团队协作友好度 |
| 工程审计 | `engineering` | 工程化规范 |

每个子 Agent 必须：
1. 先 Read `design/BEACON.md` 对齐设计基线
2. 对比当前设计入口及 `design/v5.8-Main-Agent-Coordinator-Recovery-Design.md` 与代码实际实现（差异默认判为代码缺口，见 `design-document-inviolability.md`）
3. 参考 LangGraph/AutoGen/CrewAI 对应模块逐项比对，标注差异（遵守 `CLAUDE.md` §硬禁令：grep 定位 → 50-200 行 Read → 丢弃，禁批量/并行扫描参考源）
4. 遵守 `@.claude/rules/audit-role.md` 审计约束
5. 输出 findings：`[{severity(P0/P1/P2), dimension, agent_source, file, line, description, evidence, suggested_fix}]`

### Phase 3 — 合并去重 + 报告（Python 确定性求值）

3 个子 Agent 的 findings 合并后走 `gates/deep_audit.py:recount_findings()`
确定性去重重算（去重键 =(file, line, description[:40] 归一化)，碰撞保留最高
severity + 合并 agent_source，Python 重算 p0/p1/p2 为权威计数）—— 对齐
`system_deep_audit` stage 的 Python 侧求值语义。

报告文件: `_scratch/reports/YYYY-MM-DD-audit.md`
