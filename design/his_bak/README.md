# design/his_bak — 历史文档归档

> 创建：2026-06-25 | 整理人：Claude Code
> 归档原因：内容已被 `v1.1-UNIFIED-DEV-PLAN.md` 整合覆盖，或已完成执行

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
| `v1.1-PLAN-A-bugfixes.json` | 3KB | Plan A bugfixes（已整合到 UNIFIED-DEV-PLAN） |
| `v1.1-PLAN-B-config-cli.json` | 3KB | Plan B config-cli（已整合到 UNIFIED-DEV-PLAN） |
| `v1.1-PLAN-C-templates-borrowing.json` | 3KB | Plan C templates（已整合到 UNIFIED-DEV-PLAN） |
| `v1.1-PLAN-D1-runtime-guardrail.json` | 4KB | Plan D1 runtime-guardrail（已整合到 UNIFIED-DEV-PLAN） |
| `v1.1-PLAN-D2-agent-tools.json` | 5KB | Plan D2 agent-tools（已整合到 UNIFIED-DEV-PLAN） |
| `v1.1-PLAN-D3-cli-observability.json` | 3KB | Plan D3 cli-observability（已整合到 UNIFIED-DEV-PLAN） |
| `v1.0-AUDIT-SUPPLEMENT.md` | 11KB | 设计审计补充报告（内容与 v1.0-LOOP-AUDIT 重叠） |

---

## 归档依据

- `v1.1-UNIFIED-DEV-PLAN.md` 开头明确说明：**整合了 12 个待办文件** → 即上表前 8 项
- `v1.1-DEVELOPMENT-PLANS.md` 的 6 个 Plan（A/B/C/D1/D2/D3）分别对应 6 个 JSON 文件，已全部被统一计划合并
- `v1.0-AUDIT-SUPPLEMENT.md` 覆盖：配置/错误/模板/护栏维度，与 `v1.0-LOOP-AUDIT.md` 有内容重叠（后者保留）
- `v1.0-DESIGN.md.archived` 是拆分前的原始完整设计，已被 `v1.0-SHARED.md`、`v1.0-INIT.md`、`v1.0-LOOP.md`、`v1.0-TEMPLATES.md` 四个专项文档替代

---

## 保留 vs 归档对照

| 主题 | 保留文件 | 归档文件 |
|------|---------|---------|
| init 设计 | `v1.0-INIT.md` | `v1.0-INIT-PLAN.md`, `init-PLAN.md`, `init-TODO.md` |
| loop 设计 | `v1.0-LOOP.md` | `LOOP-DEVELOPMENT-PLAN.md`, `dev-loop-TODO.md` |
| 开发计划 | `v1.1-UNIFIED-DEV-PLAN.md`, `v1.1-DEV-PLAN.md`, `v1.1-TODO-LIST.md` | `v1.1-DEVELOPMENT-PLANS.md`, 6×`v1.1-PLAN-*.json` |
| 审计 | `v1.0-LOOP-AUDIT.md`, `v1.1-AUDIT-REPORT.md` | `v1.0-AUDIT-SUPPLEMENT.md` |
| 早期主设计 | `v1.0-SHARED.md`, `v1.0-LOOP.md`, `v1.0-INIT.md`, `v1.0-TEMPLATES.md` | `v1.0-DESIGN.md.archived` |
