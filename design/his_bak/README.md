# design/his_bak — 历史文档归档

> 创建：2026-06-25 | 整理人：Claude Code
> 整理日期：2026-06-25

---

## 归档清单

| 文件 | 大小 | 说明 |
|------|------|------|
| `v1.0-DESIGN.md.archived` | 120KB | 早期完整设计文档（已被拆分：SHARED/INIT/LOOP/TEMPLATES） |
| `v1.0-INIT-PLAN.md` | 14KB | init 执行计划（已完成，整合到 TODO-LIST） |
| `init-PLAN.md` | 11KB | init 断路修复执行计划（已被 v1.0-INIT-PLAN 整合） |
| `init-TODO.md` | 4KB | init 子系统待办（已被统一开发计划覆盖） |
| `init-TODO.md.bak.20260624-1410` | 4KB | init-TODO 备份 |
| `LOOP-DEVELOPMENT-PLAN.md` | 10KB | loop 开发计划（已被统一开发计划覆盖） |
| `dev-loop-TODO.md` | 3KB | dev-loop 后续待办（已被统一开发计划覆盖） |
| `v1.1-DEVELOPMENT-PLANS.md` | 8KB | atdo 格式开发计划总览（已被统一开发计划覆盖） |
| `v1.1-DEV-PLAN.md` | 10KB | P1 开发计划（已被 UNIFIED-DEV-PLAN 覆盖，2026-06-25 整合） |
| `v1.1-LOOP-ROADMAP.md` | 15KB | Loop 工程路线图（已整合入 UNIFIED-DEV-PLAN） |
| `v1.0-LOOP-AUDIT.md` | 23KB | loop 深度审计报告（已整合入 AUDIT-REPORT 附录 A） |
| `v1.1-PLAN-A-bugfixes.json` | 3KB | Plan A bugfixes（已整合到 UNIFIED-DEV-PLAN） |
| `v1.1-PLAN-B-config-cli.json` | 3KB | Plan B config-cli（已整合到 UNIFIED-DEV-PLAN） |
| `v1.1-PLAN-C-templates-borrowing.json` | 3KB | Plan C templates（已整合到 UNIFIED-DEV-PLAN） |
| `v1.1-PLAN-D1-runtime-guardrail.json` | 4KB | Plan D1 runtime-guardrail（已整合到 UNIFIED-DEV-PLAN） |
| `v1.1-PLAN-D2-agent-tools.json` | 5KB | Plan D2 agent-tools（已整合到 UNIFIED-DEV-PLAN） |
| `v1.1-PLAN-D3-cli-observability.json` | 3KB | Plan D3 cli-observability（已整合到 UNIFIED-DEV-PLAN） |
| `v1.0-AUDIT-SUPPLEMENT.md` | 11KB | 设计审计补充报告（已整合入 v1.1-AUDIT-REPORT.md 附录 B） |
| `v1.0-LOOP-AUDIT.md` | 23KB | loop 深度审计报告（已整合入 v1.1-AUDIT-REPORT.md 附录 A） |
| `v1.1-LOOP-ROADMAP.md` | 15KB | Loop 工程路线图（已整合入 v1.1-UNIFIED-DEV-PLAN.md） |

---

## 归档依据

- `v1.1-UNIFIED-DEV-PLAN.md`（2026-06-25 更新）含 P1 完成状态：整合了 12 个待办文件 → init-PLAN, init-TODO, LOOP-DEVELOPMENT-PLAN, dev-loop-TODO, v1.1-DEVELOPMENT-PLANS, 6×v1.1-PLAN-*.json, v1.1-LOOP-ROADMAP（第二轮追加 v1.1-DEV-PLAN）
- `v1.1-AUDIT-REPORT.md`（2026-06-25 更新）含 3 个附录：**附录 A（v1.0-LOOP-AUDIT 框架分析）**、**附录 B（v1.0-AUDIT-SUPPLEMENT 10项）**、**附录 C（P1 完成状态 8/8）**
- `v1.0-DESIGN.md.archived` 是拆分前的原始完整设计，已被 `v1.0-SHARED.md`、`v1.0-INIT.md`、`v1.0-LOOP.md`、`v1.0-TEMPLATES.md` 四个专项文档替代

---

## 整合后 design 目录结构

```
design/
├── BEACON.md                    ← 项目明灯（始终保留）
├── v1.0-SHARED.md              ← 共享架构设计
├── v1.0-INIT.md                ← init 子系统设计
├── v1.0-LOOP.md               ← loop 子系统设计 v3.0
├── v1.0-TEMPLATES.md           ← 模板资产定义
├── v1.1-AUDIT-REPORT.md        ← 统一审计报告（含3个附录）
├── v1.1-UNIFIED-DEV-PLAN.md    ← 统一开发计划（含 P1 完成状态）
├── v1.1-TODO-LIST.md           ← 当前 TODO 清单
├── v2.0-LOOP-ANALYSIS.md       ← v2.0 loop 优化分析
└── his_bak/                    ← 历史归档（可查阅，不参与主线）
```

## 文档职责划分

| 文件 | 职责 |
|------|------|
| BEACON.md | 项目明灯，当前阶段/目标/阻塞项 |
| v1.0-SHARED/INIT/LOOP | 三大板块设计文档（静态，修改需评审） |
| v1.0-TEMPLATES.md | 模板资产定义 |
| v1.1-AUDIT-REPORT | 统一审计报告（P0-P2问题 + 2个框架深度附录） |
| v1.1-UNIFIED-DEV-PLAN | 统一执行计划（含依赖图/工作量/风险） |
| v1.1-TODO-LIST | 当前高优先级待办清单 |
| v2.0-LOOP-ANALYSIS | v2.0 架构演进方向（多 Agent 并发） |
