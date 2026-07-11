# 剩余任务执行计划（Phase 3–7 全量纳入）

> 创建：2026-07-11 | 触发：用户「剩余的所有都纳入计划，继续」
> 权威任务表：`design/IMPLEMENTATION-TRACKER.md`（本文件只做**执行排序 + 红线门标注**，不复制任务详情）
> 执行纪律：每任务一 commit（TDD Red→Green）；红线门必须停下问用户；测试遵守 pytest-memory-management

---

## 红线门（命中必停，不自作主张）

| 门 | 红线 | 任务 | 处置 |
|----|------|------|------|
| G-A4 | #1 删文件 | A4 `gap_analysis.py` 接线 or 删除 | 停 → AskUserQuestion（接线/删除）|
| G-A9 | #5 装依赖 | A9 移除 `# type:ignore` 需 mypy | 停 → 问装 mypy dev-dep or 接受文档化 ignore |
| G-CI | #2 CI/CD 配置 | T16h/T16i `.github/workflows/` | 停 → 问是否授权写 CI 配置 |
| G-retire | 架构（退役活跃路径）| T10d v5.5 orchestrator + semantic_evaluator 移除 | 停 → 确认退役时机（当前 legacy 仍活跃）|

---

## Wave 1 — Phase 3 完成（让 tick 引擎从 Claude Code 可用）

> 目标：T9 已接 CLI；本 wave 补 Command/Skill 层 + progress CLI，使 `/ae:dev-loop` 走 tick 模式端到端可用。

| 序 | T | 产出 | 类型 | 依赖 |
|----|---|------|------|------|
| 1.1 | T12 | BEACON.md 更新决策表 + 当前状态（记录 v5.6 tick + T9 接线）| doc | — |
| 1.2 | T9b | `cli/progress.py`（ae progress，读持久化 progress_tree_json）| code | T9 ✅ |
| 1.3 | T10b | `commands/progress.md`（新建）| md | 1.2 |
| 1.4 | T10 | `commands/dev-loop.md` 8-stage 重写（--init/--tick 模式，移除 4 外部依赖）| md | T9 ✅ |
| 1.5 | T11 | `skills/auto-engineering/SKILL.md` 分层验证约束 | md | 1.4 |
| 1.6 | T10c | `tools/pr_backend.py`（PRBackend/GitHub/GitLab）| code | T26e 选型 |
| 🚧 | **T10d** | v5.5 退役 + semantic 移除 | — | **G-retire 停** |

## Wave 2 — Phase 4 Agent Prompt 模板（10）

T13 ComponentVerifier / T14 SystemVerifier / T15 Critic 精简 / T16 Architect design-doc /
T16b gap_scan+research prompt+authz / T16c Developer B11 / T16d SKILL+dev-loop B11 /
T16e prompts/registry.py / T16f prompts 目录骨架+迁移(9+8) / T16g sync-prompts.py+base.py 重构
→ 均无红线。T16e/f/g 由 Phase 5 T26d 背书（测试）。

## Wave 3 — Phase 5 测试加固（剩余）

T19 验证层集成 / T20 plan-refine 回路 / T21 收尾(2 轮 design-doc E2E) / T24 ProgressTree 动态同步 /
T25 收尾(Pre-flight 4 路径) / T26 ResearchAgent / T26b 收尾(P95) / T26c verifier Sonnet 兜底 /
T26d PromptRegistry / T26e PRBackend 选型 / T26f 环内增量 / T26g B15 Guardrail / T26h AuditGate
→ 均无红线。背书关系：T26d→Wave2；T26e→T10c/T33；T26f→T16l/n；T26g→T29/30；T26h→T31。

## Wave 4 — Phase 6 审计与验证方法论 B15（5）

T27 deep_audit 3-agent / T28 commands/audit.md 内化 / T29 REDGuard+FreshGate /
T30 RegressionGate / T31 AuditGate 语义层 → 均无红线。

## Wave 5 — Phase 4b 非 CI 部分（5，跳过 CI 红线）

T16j code-review.md 校准 / T16k git add -A→精确 / T16l 环内增量 test_gate /
T16m sync-prompts 扩展 / T16n commit_msg_gate（可选）→ 无红线。
🚧 **T16h/T16i**（CI/CD）→ **G-CI 停**。

## Wave 6 — Phase 7 Init-Loop 契约（4）

T32 schema.json SSOT / T33 ci_platform+design_root 字段 / T34 monorepo 降级 WARN /
T35 fixture round-trip 契约测试 → 均无红线。

## Wave 7 — 决策门收口（需用户拍板）

🚧 G-A4（gap_analysis 删/接线）/ 🚧 G-A9（mypy）/ 🚧 G-CI（T16h/i）/ 🚧 G-retire（T10d）

---

## 执行策略

- 按 Wave 顺序推进；每 Wave 内按序号；每任务一 commit。
- 命中红线门 → 停 + AskUserQuestion，其余继续。
- 每完成一个 Wave 更新 tracker 对应行 + 决策日志。
- 上下文接近阈值 → 写 session-summary + 报告进度。
- 参考框架只读探索遵守 CLAUDE.md 硬禁令（grep 定位→片段 Read→丢弃，禁批量/并行）。
