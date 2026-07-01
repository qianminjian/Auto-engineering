# design/ — 文档索引

> 创建：2026-06-25 | 更新：2026-06-29 | 维护规则：每次合并/重命名后更新本文件

---

## 跨项目资产（位于其他目录）

| 路径 | 用途 | 引用 |
|------|------|------|
| `../docs/atdo-runtime-smoke-policy.md` | atdo Plan 报告必须含 runtime smoke 验证（防止虚化测试） | BEACON 决策 18 |
| `../docs/his_bak/` | 历史文档归档（v1.0/v2.0/v2.5 时期的 docs, v5.0 不再使用） | 主动归档 |

---

## 文档分类

| 类别 | 文件 | 描述 |
|------|------|------|
| **项目明灯** | `BEACON.md` | 当前阶段/目标/阻塞项/设计决策 |
| **设计文档** | `v5.0-Design-Loop.md` | v5.0 Loop Engineering 完整设计（含 3 Stage + 5 Guardrail + 7 Gate + Init-Loop 接口契约 IL.1-IL.6） |
| ~~`v5.0-Design-Init.md`~~ | **已移出本项目** | Init Engineering 现在是独立项目, Init 侧按 `v5.0-Design-Loop.md` §IL.1-IL.6 实现 |
| ~~`v5.0-Design.md`~~ | **已拆分** → Init 独立项目 + `v5.0-Design-Loop.md` |
| **归档** | `his_bak/` | v1.0/v1.1/v2.0/v2.3/v2.4/v2.5 历史设计/计划/审计（见 §归档清单） |

---

## 命名规范

```
V<major>.<minor>-<Category>-<Name>.md
```

| Category 前缀 | 含义 |
|--------------|------|
| `Design` | 设计文档 — 架构/子系统设计 |
| `Audit` | 审计报告 — 问题发现/评估 |
| `Plan` | 执行计划 — 开发任务/路线图 |
| `Analysis` | 分析报告 — 深度研究/对比 |

**例外**：`BEACON.md` / `INDEX.md` — 特殊角色文件，保持原名。

---

## 合并日志

> 每次合并或重命名后追加一行。格式：`日期 | 主文档 | 来源/操作 | 摘要`

| 日期 | 主文档 | 来源/操作 | 摘要 |
|------|--------|---------|------|
| 2026-06-30 | `v5.0-Design-Loop.md` | /tttt 深度迭代重写 | 自包含开发就绪规格: 17 字段 LoopState, 11 类型+12 接口+3 DDL+15 测试场景, Agent prompt 完整模板, 19 错误码, 跨 Stage 数据流契约, ContractGate 算法, Gate 失败恢复. 自评 9.2/10. |
| 2026-06-30 | `v5.0-Design-Loop.md` | PE.1 Plugin 字段修订 | 业界对标 5 个真实 Claude Code plugin.json: `min_claude_code_version`/`requirements`/`env` 3 个非官方字段移入 `metadata` 子对象避免与官方约定冲突; 补充 `repository`/`homepage`/`keywords` 官方识别字段; 新增 PE.1a 多 Skill 拆分建议 (借鉴 project-engineering-init, v5.0 保留单 Skill, v5.1 候选); 新增 PE.1b hooks `chmod +x` 约束. 备份: `his_bak/v5.0-Design-Loop.md-20260630-pre-plugin-revision.md` |
| 2026-06-30 | `v5.0-Design-Loop.md` | Init Engineering 拆分独立项目 | Loop 项目范围收紧, Init 项目独立. Init-Loop 衔接通过 Loop 设计文档 §IL.1-IL.6 接口契约定义 (Init 侧按契约实现). |
| 2026-06-30 | (项目清理) | 删除 Init 实现 + Init 设计 + 7 Init 测试 | `auto_engineering/init/`(528K), `design/v5.0-Design-Init.md`(24K), `tests/test_init*.py`, `tests/test_answers.py`, `tests/test_prompts.py`, `templates/` 移除. 备份: `_backup_cleanup_20260630/` |
| 2026-06-29 | `v5.0-Design-Init.md` + `v5.0-Design-Loop.md` | 拆分自 `v5.0-Design.md` | v5.0 合订文档拆分为 2 个专项文档: Init Engineering（含 init ↔ loop 共享契约 §10, 来自 v1.0-Design-Shared.md §三）与 Loop Engineering（含 3 Stage + 5 Guardrail + 7 Gate）。衔接内容在 Init，Loop 通过索引引用。 |
| 2026-06-29 | `v5.0-Design.md` | → `his_bak/v5.0-Design.md-20260629.md` | v5.0 合订文档归档（已拆分为 Init + Loop 两个专项文档） |
| 2026-06-28 | `v2.5-Plan-Dev.md` | 新增 | v2.5 生产就绪最终修复: 3 P0 (ContractGate/Real Agent/Split) + 5 P1 + 3 P2. v1.0 退役授权, P0-FINAL 撤销决策 11/12/22/24/26 |
| 2026-06-27 | `v2.4-Plan-Dev.md` | 新增 | v2.4 整合修复: ContractGate 真实实现 + Real Agent 注册 + state/cli/checkpoint 拆分 + ReadFileTool 沙箱 |
| 2026-06-25 | `v1.1-Plan-Dev.md` | 重命名 | 整合 v1.1-TODO-LIST + v1.1-UNIFIED-DEV-PLAN → 单一开发计划 |
| 2026-06-25 | `v1.0-Design-*.md` | 重命名 | 设计文档四件套启用新命名规范 |
| 2026-06-25 | `v1.1-Audit-Report.md` | 重命名 + 合并 | 合并 v1.1-AUDIT-REPORT + his_bak 附录 A/B/C |
| 2026-06-25 | `v2.0-Analysis-Loop.md` | 重命名 | 原 v2.0-LOOP-ANALYSIS → Analysis-Loop |
| 2026-06-25 | `v1.1-Audit-Report.md` | `his_bak/v1.0-LOOP-AUDIT.md` | 合并附录 A：LangGraph/AutoGen/CrewAI 框架深度分析 |
| 2026-06-25 | `v1.1-Audit-Report.md` | `his_bak/v1.0-AUDIT-SUPPLEMENT.md` | 合并附录 B：第二轮 10 个优化点 |
| 2026-06-25 | `v1.1-Audit-Report.md` | — | 合并附录 C：P1 完成状态（8/8） |
| 2026-06-25 | `v1.1-UNIFIED-DEV-PLAN.md` | `his_bak/v1.1-LOOP-ROADMAP.md` | 合并 Loop 路线图 P0-P3 |
| 2026-06-25 | `v1.1-UNIFIED-DEV-PLAN.md` | `his_bak/v1.1-DEV-PLAN.md` | 合并 P1 开发计划 |
| 2026-06-25 | `v1.1-UNIFIED-DEV-PLAN.md` | `his_bak/init-PLAN.md`, `init-TODO.md`, `LOOP-DEVELOPMENT-PLAN.md`, `dev-loop-TODO.md`, `v1.1-DEVELOPMENT-PLANS.md`, `6×v1.1-PLAN-*.json` | 合并 12 个历史待办文件（2026-06-24 整合） |
| 2026-06-25 | `his_bak/` | `v1.0-DESIGN.md.archived` | 归档：早期完整设计（已被拆分为 SHARED/INIT/LOOP/TEMPLATES） |
| 2026-06-25 | `his_bak/` | `v1.0-LOOP-AUDIT.md` | 归档：loop 深度审计（已合并入 Audit-Report） |
| 2026-06-25 | `his_bak/` | `v1.0-AUDIT-SUPPLEMENT.md` | 归档：第二轮补充审计（已合并入 Audit-Report） |

---

## 归档清单（his_bak/）

详见 `his_bak/README.md`

### 快速索引

| 原文件名 | 归档路径 | 合并到 | 日期 |
|---------|---------|--------|------|
| `v1.0-DESIGN.md.archived` | `his_bak/v1.0-DESIGN.md.archived` | — | 2026-06-25 |
| `v1.0-LOOP-AUDIT.md` | `his_bak/v1.0-LOOP-AUDIT.md` | `v1.1-Audit-Report.md` 附录 A | 2026-06-25 |
| `v1.0-AUDIT-SUPPLEMENT.md` | `his_bak/v1.0-AUDIT-SUPPLEMENT.md` | `v1.1-Audit-Report.md` 附录 B | 2026-06-25 |
| `v1.1-TODO-LIST.md` | `his_bak/v1.1-TODO-LIST.md` | `v1.1-Plan-Dev.md` §一 | 2026-06-25 |
| `v1.1-UNIFIED-DEV-PLAN.md` | `his_bak/v1.1-UNIFIED-DEV-PLAN.md` | `v1.1-Plan-Dev.md` §二-九 | 2026-06-25 |
| `v1.1-DEVELOPMENT-PLANS.md` | `his_bak/v1.1-DEVELOPMENT-PLANS.md` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `v1.1-LOOP-ROADMAP.md` | `his_bak/v1.1-LOOP-ROADMAP.md` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
| `v1.1-DEV-PLAN.md` | `his_bak/v1.1-DEV-PLAN.md` | `v1.1-UNIFIED-DEV-PLAN.md` | 2026-06-25 |
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
v<VERSION>-<Category>-working-<YYYYMMDD>.md
v1.2-Audit-working-20260626.md     # 审计工作版
v1.2-Plan-working-20260626.md     # 计划工作版
v1.2-Design-featureX-20260626.md   # 设计工作版
```

### 合并/重命名流程

1. **工作中**：在 `design/` 根目录创建带时间戳的工作文档
2. **完成确认后**：
   - 将内容合并到对应的主文档
   - 将工作文档移动到 `his_bak/`，命名改为 `v<VERSION>-<Category>-<YYYYMMDD>.md`
   - 在本 INDEX.md 的合并日志追加一行
3. **主文档头部**：必须包含 `来源:` 字段，指向本 INDEX

### 主文档头部格式

```markdown
# <文档名>

> 来源：@design/INDEX.md | 创建：YYYY-MM-DD | 更新：YYYY-MM-DD
```

---

## 引用约定

- 主文档引用：`@design/<filename.md>`
- 归档引用：`@design/his_bak/<filename.md>`
- 代码引用：`@auto_engineering/<path>`

## 文档更新规则 (2026-06-29 起, 防文件碎片化)

**原则**: 单一信息源 (single source of truth). 不为每次小改生成独立 v5.0-Design-UpdateN.md, 也不为子主题拆 v5.0-Init.md / v5.0-Loop.md — 这些会断文档, 读者不知从哪看起.

**操作流程**:
1. **备份老版本**: `cp design/<file>.md design/his_bak/<file>/<TIMESTAMP>-pre-change.md` (例: `2026-06-29-pre-add-v5.0-stage-graph.md`)
2. **就地修改**: 直接编辑 `design/<file>.md` 在原位增删, 用 PR diff 体现变化
3. **更新头部**: 主文档头部 `更新: YYYY-MM-DD` 字段同步更新
4. **合并日志**: 本 INDEX.md 合并日志追加一行 (`日期 | 主文档 | 来源/操作 | 摘要`)

**禁止**:
- ❌ 不为每次小改生成 `v5.0-Design-Update1.md` 等独立文件
- ❌ 不为 v5.0 内的子主题拆 v5.0-Init.md / v5.0-Loop.md / v5.0-Plugin.md (除非版本大升级, 如 v6.0)
- ❌ 不复制主文档内容到 his_bak 后不删原文件 (his_bak 是备份, 不是 shadow copy)

**例外 (可生成独立文件)**:
- 主版本号升级 (v5.0 → v6.0): 新文件 `v6.0-Design.md`
- 完全不同的子主题 (v5.0-Design.md 之外新增完全独立的设计: 例 `claude-code-integration.md`)

**主文档头部格式** (v5.0+):
```markdown
# <文档名>

> 来源：@design/INDEX.md | 创建：YYYY-MM-DD | 更新：YYYY-MM-DD | 阶段：<阶段>
```
