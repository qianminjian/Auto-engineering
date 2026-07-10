# design/ — 文档索引

> 创建：2026-06-25 | 更新：2026-07-08 | 维护规则：每次合并/重命名后更新本文件

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
| **项目明灯** | `BEACON.md` | 当前阶段/目标/阻塞项/设计决策（v5.6 Tick-Based 协议 + 5 层验证架构, 决策 #1-#40） |
| **设计文档** | `v5.6-Design-Loop.md` | v5.6 Loop Engineering 完整设计 — Tick-Based Discrete Invocation + 5 层验证架构 (1974 行, 自包含) |
| **讨论记录** | `discussion/v5.6-layered-verification-design.md` | v5.6 分层验证架构设计讨论全过程 — 已解决问题/用户纠正/设计原则/后续参考 |
| ~~`v5.0-Design-Init.md`~~ | **已移出本项目** | Init Engineering 现在是独立项目, Init 侧按 `v5.6-Design-Loop.md` §IL.1-IL.6 实现 |
| ~~`v5.0-Design.md`~~ | **已拆分** → Init 独立项目 + `v5.6-Design-Loop.md` |
| **归档** | `his_bak/` | v1.0/v1.1/v2.0/v2.5 + v5.1 discussion + v5.5 IMPL-PLAN + v5.0 bak（见 §归档清单） |

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
| 2026-07-09 | `INIT-LOOP-CONTRACT.md` (新建) | Init 项目需求交接文档 | 将 D21 契约变革中**对 Init 项目的需求输入**抽为自包含交接文档（Init 团队照此实现，不依赖 Loop 内部设计文档）：TL;DR 4 件事 / 契约总览 / manifest 完整字段规格 + 示例 / 枚举 / v5.6 新增字段设计思路(ci_platform B1 + design_root B2) / Schema SSOT 协议(复制内化+版本 pin+生成自校验+变更流程) + 权威 JSON Schema 1.1 / reference fixture 双仓库同步 / monorepo 单包约定 / 明确不属于 Init 的部分 / Init 侧验收清单 / 变更历史。挂入 BEACON 引用文件。供用户单独更新 Init 项目 |
| 2026-07-09 | `v5.6-Design-Loop.md` + `discussion/…` | Init-Loop 契约 v5.6 扩展 (IL.2-IL.5) | 评估"和 Init 工程衔接如何定义/是否合理/优化"：架构选型正确(单向/文件桥接/只读/forward-compat)，两缺口——①跨仓库无 Schema SSOT(设计文档表+Python函数两处定义→漂移) ②相对 v5.6 滞后(缺 design_doc/ci_platform, monorepo 枚举不自洽)。IL 章重写：IL.1(移除 checkpoints.db 契约面声明解 spec 债) + IL.2 Schema SSOT(A, `init-manifest.schema.json` 版本化 JSON Schema 骨架, jsonschema 校验, 复制内化) + IL.3 完整字段表(+ conventions.ci_platform[B1] + structure.design_root[B2], monorepo 单包降级[C]) + IL.4(+IL-AC-06/07/08) + IL.5 消费者驱动契约测试(D, 共享 reference fixture 双仓库同步)。+D21 + Phase 7(T32-T35)。discussion §十五(现状/评估/A-B-C-D 决策与判断依据/已解决问题/后续参考)。关键决策：schema SSOT 消漂移、design_doc 内容走 CLI 不入 manifest、monorepo 不删枚举避免降级。BEACON 决策 #48 |
| 2026-07-09 | `v5.6-Design-Loop.md` + `discussion/…` | Superpowers 验证方法论借鉴 (B15) | 两组分析合并去重：① Superpowers 三工具（test-driven-development/verification-before-completion/requesting-code-review）方法论 → REDGuard+FreshGate+RegressionGate（一律 Python 确定性门控，非 Agent 自觉）；② 本项目 `/audit` 三层实现现状（audit.md 依赖 Superpowers 运行时/audit.py 只有正则无语义/deep_audit.py 骨架未实际 spawn）→ 内化+语义层+骨架→实际+AuditGate↔system_deep_audit 分层澄清。新增 B15 章 6 小节（核心定位/audit 现状/借鉴清单 4 主题/9 项优先级矩阵/不借鉴项/与 v5.6 关系）+ D20 + Phase 6 (T27-T31)。discussion 追加 §十四（两组分析合并逻辑/三工具 Iron Law 内核/audit 三层缺口/9 项去重矩阵/已解决问题/后续参考）。关键决策：借鉴一律实现为 Python 确定性门控、`/audit` 与 5 层验证互补不冗余、AuditGate 与 system_deep_audit 频率×深度分层。BEACON 决策 #47 |
| 2026-07-10 | `IMPLEMENTATION-TRACKER.md` + (归档整理) | 状态核对 + 历史归档 | tracker 与代码对齐：Phase 2→6/6✅、Phase 5→4/17◐、总完成 6→16（~26%），标注关键风险"v5.6 引擎未接入 CLL"。归档 `.planning/`（v5.5 GSD 里程碑）→ `his_bak/planning-v5.5-milestone/`、`DESIGN-REFINEMENT-PLAN.md`（13 DS 全完成）→ `his_bak/`。核对确认历史文件无待整合任务（3-agent audit→T27、_sync_design_docs→v5.6 flag+feedback 取代）|
| 2026-07-09 | `v5.6-Design-Loop.md` + `discussion/…` | 外部 Skill/Agent 依赖审计 + 内化约束 (B14) | 全项目(75.py+3命令+SKILL+5hook)排查外部依赖：唯一运行时问题=dev-loop.md v5.1 4项（Plan/code-reviewer//code-review/gsd-code-fixer）。新增 B14 章 4 小节（可移植性原则/审计结论/内化规则/与B12/B13关系）+ D19 + T10 细化为移除 4 项 + T10c(PRBackend 抽象)。discussion 追加 §十三（分析方法/内化vs引用判断/mcp-server 误会澄清/gsd零容忍/已解决问题/后续参考）。确立"不 spawn 外部 agent、借鉴=复制非链接、系统依赖需抽象"准入规则。BEACON 决策 #46 |
| 2026-07-09 | `v5.6-Design-Loop.md` + `discussion/…` | Commit→PR→CI/CD Pipeline 专题设计 (B13) | 5 轮讨论固化：新增 B13 章 9 小节（心智模型/颗粒度金字塔/生命周期时间轴/动作主表/环界线/PR 颗粒度输入端控制 4 方案/CI 双平台薄壳/环内增量 vs 远程全量/Gap Analysis/实施清单）+ D18 + Phase 4b (T16h-T16n)。discussion 追加 §十二（讨论过程：现状问题/颗粒度/PR=plate 中断分析/CI 双平台/环内vs远程共享标准非运行时/已解决问题/后续参考）。关键决策：PR 颗粒度由输入端控制（呼应 D13）、人工闸门恒在环外、CI 单一入口+薄壳(DRY)、共享 pyproject 标准非运行时。文档 3070→约3220 行。BEACON 决策 #45 |
| 2026-07-09 | `discussion/v5.6-layered-verification-design.md` | 追加 §十 + §十一（讨论过程补录） | 补录此前遗漏持久化的两个讨论：§十 借鉴 Superpowers 提示词技术（分析方法/两种架构哲学差异/借鉴 6 项/不借鉴 3 项原因/已解决问题/后续参考）、§十一 中央提示词管理（三层三版本漂移证据/三类提示词/Prompt Registry 结论/C 类不移位边界/dev-loop 虚构引用修复/已解决问题）。确立"讨论过程即使未改代码也须持久化"原则 |
| 2026-07-09 | `v5.6-Design-Loop.md` + `commands/dev-loop.md` | 中央提示词管理 (B12) + 虚构引用修复 | 提示词清单盘点(A/B/C 三类跨 design+code)后新增 B12 章 (8 小节): 全清单/两类消费者/`prompts/` 目录结构(roles+fragments+schema)/PromptRegistry 组合机制(frontmatter 声明片段)/init 加载+sha256 hash 锁/`sync-prompts.py` C 类注入/YAGNI 边界。+D17、Phase 4 T13-T16d 改写为写入 `prompts/roles/` + 新增 T16e/T16f/T16g。同步修复 `.claude-plugin/commands/dev-loop.md` 虚构 "BEACON 决策 47" (BEACON 仅到 #43/#44) → 改引真实 #39 + 过时横幅。文档 2932→3070 行。BEACON 决策 #44 |
| 2026-07-08 | `v5.6-Design-Loop.md` | 借鉴 Superpowers 提示词技术固化 (B11) | 新增 B11 章 (8 小节): CSO description 纪律 / Iron Law / Red Flags / 合理化破解表 (developer/critic/architect/verifier 成品文本) / Letter-vs-Spirit / 渐进披露 / 不借鉴 3 项 / Superpowers Skill→Agent 映射。+D16、Phase 4 加 T16c/T16d、B6 加 B11 交叉引用。开发时直接粘贴到 prompts.py/SKILL.md/commands。文档 2776→2932 行。BEACON 决策 #43 |
| 2026-07-08 | `v5.6-Design-Loop.md` | Pre-flight Gap Analysis + ResearchAgent 分层知识源 | 新增 B10 章 (设计文档模糊性预检: gap_scan/gap_review/research + 4 用户路径 + Supplement)、Phase 0 转换 T0.1-T0.8、G6 Guardrail、EngineState #28-#32、TickOrchestrator 3 handler + _inject_supplement、tick flow 图 Phase 0、C.13 D14/D15。ResearchAgent 四层知识源 (Tier0 CLAUDE.md 声明→Tier3 web fallback)。文档 2418→2776 行。BEACON 决策 #42 |
| 2026-07-08 | `discussion/v5.6-layered-verification-design.md` | 追加 §九 | Pre-flight Gap Analysis + ResearchAgent 分层知识源讨论记录: 起点/结论/用户提案/YAGNI+内存安全约束/已解决问题/后续参考 |
| 2026-07-08 | `discussion/v5.6-layered-verification-design.md` | 新建 | v5.6 分层验证架构设计讨论全过程记录: 已解决问题/用户纠正/设计原则/后续参考。供后续设计变更时对照规避 |
| 2026-07-08 | (归档整理) | → `his_bak/` | `v5.6-Architecture-Recovery.md` 已删除(内容合并) / `v5.5-IMPLEMENTATION-PLAN.md` 归档 (被 v5.6 替代) / `discussion/` 目录归档 (v5.1 历史设计讨论) / `decisions/` 空目录归档 / `v5.6-Design-Loop.md.bak` 归档 |
| 2026-06-30 | `v5.6-Design-Loop.md` | /tttt 深度迭代重写 | 自包含开发就绪规格: 17 字段 LoopState, 11 类型+12 接口+3 DDL+15 测试场景, Agent prompt 完整模板, 19 错误码, 跨 Stage 数据流契约, ContractGate 算法, Gate 失败恢复. 自评 9.2/10. |
| 2026-06-30 | `v5.6-Design-Loop.md` | PE.1 Plugin 字段修订 | 业界对标 5 个真实 Claude Code plugin.json: `min_claude_code_version`/`requirements`/`env` 3 个非官方字段移入 `metadata` 子对象避免与官方约定冲突; 补充 `repository`/`homepage`/`keywords` 官方识别字段; 新增 PE.1a 多 Skill 拆分建议 (借鉴 project-engineering-init, v5.0 保留单 Skill, v5.1 候选); 新增 PE.1b hooks `chmod +x` 约束. 备份: `his_bak/v5.6-Design-Loop.md-20260630-pre-plugin-revision.md` |
| 2026-06-30 | `v5.6-Design-Loop.md` | Init Engineering 拆分独立项目 | Loop 项目范围收紧, Init 项目独立. Init-Loop 衔接通过 Loop 设计文档 §IL.1-IL.6 接口契约定义 (Init 侧按契约实现). |
| 2026-06-30 | (项目清理) | 删除 Init 实现 + Init 设计 + 7 Init 测试 | `auto_engineering/init/`(528K), `design/v5.0-Design-Init.md`(24K), `tests/test_init*.py`, `tests/test_answers.py`, `tests/test_prompts.py`, `templates/` 移除. 备份: `_backup_cleanup_20260630/` |
| 2026-06-29 | `v5.0-Design-Init.md` + `v5.6-Design-Loop.md` | 拆分自 `v5.0-Design.md` | v5.0 合订文档拆分为 2 个专项文档: Init Engineering（含 init ↔ loop 共享契约 §10, 来自 v1.0-Design-Shared.md §三）与 Loop Engineering（含 3 Stage + 5 Guardrail + 7 Gate）。衔接内容在 Init，Loop 通过索引引用。 |
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
| `.planning/` (STATE.md + 5 phase SUMMARY) | `his_bak/planning-v5.5-milestone/` | v5.5 GSD 里程碑记录，被 v5.6 `IMPLEMENTATION-TRACKER.md` 取代 | 2026-07-10 |
| `DESIGN-REFINEMENT-PLAN.md` | `his_bak/DESIGN-REFINEMENT-PLAN.md-完成态归档.md` | 13 DS 全完成，产出已回写 `v5.6-Design-Loop.md`（B3/B5/B6/B10/C.2.6 等）| 2026-07-10 |

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
