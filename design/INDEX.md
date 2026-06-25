# design/ — 文档索引

> 创建：2026-06-25 | 维护规则：每次合并后更新本文件

---

## 文档分类

| 类别 | 文件 | 描述 |
|------|------|------|
| **项目明灯** | `BEACON.md` | 当前阶段/目标/阻塞项/设计决策 |
| **设计文档** | `v1.0-SHARED.md` | 共享架构 |
| | `v1.0-INIT.md` | init 子系统设计 |
| | `v1.0-LOOP.md` | loop 子系统设计 v3.0 |
| | `v1.0-TEMPLATES.md` | 模板资产定义 |
| **审计报告** | `v1.1-AUDIT-REPORT.md` | 架构审计（含3个附录） |
| **执行计划** | `v1.1-UNIFIED-DEV-PLAN.md` | 统一开发计划 |
| | `v1.1-TODO-LIST.md` | 当前高优先级 TODO |
| **演进分析** | `v2.0-LOOP-ANALYSIS.md` | v2.0 多 Agent 并发架构 |
| **归档** | `his_bak/` | 历史版本（见 §归档清单） |

---

## 合并日志

> 每次合并后追加一行。格式：`日期 | 主文档 | 来源附件 | 摘要`

| 日期 | 主文档 | 来源附件 | 摘要 |
|------|--------|---------|------|
| 2026-06-25 | `v1.1-AUDIT-REPORT.md` | `his_bak/v1.0-LOOP-AUDIT.md` | 合并附录 A：LangGraph/AutoGen/CrewAI 框架深度分析 |
| 2026-06-25 | `v1.1-AUDIT-REPORT.md` | `his_bak/v1.0-AUDIT-SUPPLEMENT.md` | 合并附录 B：第二轮 10 个优化点 |
| 2026-06-25 | `v1.1-AUDIT-REPORT.md` | — | 合并附录 C：P1 完成状态（8/8） |
| 2026-06-25 | `v1.1-UNIFIED-DEV-PLAN.md` | `his_bak/v1.1-LOOP-ROADMAP.md` | 合并 Loop 路线图 P0-P3 |
| 2026-06-25 | `v1.1-UNIFIED-DEV-PLAN.md` | `his_bak/v1.1-DEV-PLAN.md` | 合并 P1 开发计划 |
| 2026-06-25 | `v1.1-UNIFIED-DEV-PLAN.md` | `his_bak/init-PLAN.md`, `init-TODO.md`, `LOOP-DEVELOPMENT-PLAN.md`, `dev-loop-TODO.md`, `v1.1-DEVELOPMENT-PLANS.md`, `6×v1.1-PLAN-*.json` | 合并 12 个历史待办文件（2026-06-24 整合） |
| 2026-06-25 | `his_bak/` | `v1.0-DESIGN.md.archived` | 归档：早期完整设计（已被拆分为 SHARED/INIT/LOOP/TEMPLATES） |
| 2026-06-25 | `his_bak/` | `v1.0-INIT-PLAN.md` | 归档：init 执行计划（已完成） |
| 2026-06-25 | `his_bak/` | `v1.0-LOOP-AUDIT.md` | 归档：loop 深度审计（已合并入 AUDIT-REPORT） |
| 2026-06-25 | `his_bak/` | `v1.0-AUDIT-SUPPLEMENT.md` | 归档：第二轮补充审计（已合并入 AUDIT-REPORT） |

---

## 归档清单（his_bak/）

详见 `his_bak/README.md`

### 快速索引

| 原文件名 | 归档路径 | 合并到 | 日期 |
|---------|---------|--------|------|
| `v1.0-DESIGN.md.archived` | `his_bak/v1.0-DESIGN.md.archived` | — | 2026-06-25 |
| `v1.0-LOOP-AUDIT.md` | `his_bak/v1.0-LOOP-AUDIT.md` | `v1.1-AUDIT-REPORT.md` 附录 A | 2026-06-25 |
| `v1.0-AUDIT-SUPPLEMENT.md` | `his_bak/v1.0-AUDIT-SUPPLEMENT.md` | `v1.1-AUDIT-REPORT.md` 附录 B | 2026-06-25 |
| `v1.1-LOOP-ROADMAP.md` | `his_bak/v1.1-LOOP-ROADMAP.md` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `v1.1-DEV-PLAN.md` | `his_bak/v1.1-DEV-PLAN.md` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `v1.1-DEVELOPMENT-PLANS.md` | `his_bak/v1.1-DEVELOPMENT-PLANS.md` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `v1.1-PLAN-A-bugfixes.json` | `his_bak/v1.1-PLAN-A-bugfixes.json` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `v1.1-PLAN-B-config-cli.json` | `his_bak/v1.1-PLAN-B-config-cli.json` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `v1.1-PLAN-C-templates-borrowing.json` | `his_bak/v1.1-PLAN-C-templates-borrowing.json` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `v1.1-PLAN-D1-runtime-guardrail.json` | `his_bak/v1.1-PLAN-D1-runtime-guardrail.json` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `v1.1-PLAN-D2-agent-tools.json` | `his_bak/v1.1-PLAN-D2-agent-tools.json` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `v1.1-PLAN-D3-cli-observability.json` | `his_bak/v1.1-PLAN-D3-cli-observability.json` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `init-PLAN.md` | `his_bak/init-PLAN.md` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `init-TODO.md` | `his_bak/init-TODO.md` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `init-TODO.md.bak.20260624-1410` | `his_bak/init-TODO.md.bak.20260624-1410` | — | 2026-06-25 |
| `LOOP-DEVELOPMENT-PLAN.md` | `his_bak/LOOP-DEVELOPMENT-PLAN.md` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `dev-loop-TODO.md` | `his_bak/dev-loop-TODO.md` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `v1.0-INIT-PLAN.md` | `his_bak/v1.0-INIT-PLAN.md` | `v1.1-TODO-LIST.md` | 2026-06-25 |

---

## 工作流程规范

### 临时工作文档命名

```
v<VERSION>-<TYPE>-working-<YYYYMMDD>.md
v1.2-AUDIT-working-20260626.md     # 审计工作版
v1.2-PLAN-working-20260626.md       # 计划工作版
v1.2-DESIGN-featureX-20260626.md   # 设计工作版
```

### 合并流程

1. **工作中**：在 `design/` 根目录创建带时间戳的工作文档
2. **完成确认后**：
   - 将内容合并到对应的主文档（UNIFIED-DEV-PLAN / AUDIT-REPORT / etc.）
   - 将工作文档移动到 `his_bak/`，命名改为 `v<VERSION>-<TYPE>-<YYYYMMDD>.md`
   - 在本 INDEX.md 的合并日志追加一行
3. **主文档头部**：必须包含 `来源:` 字段，指向本 INDEX

### 主文档头部格式

```markdown
# <文档名>

> 来源：@design/INDEX.md 合并日志 | 创建：YYYY-MM-DD | 更新：YYYY-MM-DD
```

---

## 引用约定

- 主文档引用：`@design/<filename.md>`
- 归档引用：`@design/his_bak/<filename.md>`
- 代码引用：`@auto_engineering/<path>`
