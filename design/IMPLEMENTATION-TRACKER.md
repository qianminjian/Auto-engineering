# v5.6 实施跟踪表（IMPLEMENTATION-TRACKER）

> 创建：2026-07-09 | 用途：v5.6 实现阶段的进度主表（跨会话 SSOT），驱动开发 + 汇报进度
> 任务源：`v5.6-Design-Loop.md` C.12 实现计划 + C.12.1 追溯矩阵（62 T-task）
> 粒度：**T-task 级** | 节奏：**连续跑到阻塞点**（仅红线/卡死/需决策时停）
> 权威关系：设计规格在 `v5.6-Design-Loop.md`（不变）；本表只记进度（每轮变）。设计章节+验收明细见 C.12.1。

## 状态图例

| 符号 | 含义 |
|------|------|
| ☐ | 待办 |
| ◐ | 进行中 |
| ✅ | 完成（实现 + 验收通过 + 已提交）|
| ⛔ | 阻塞（需决策/红线/卡死，备注说明）|
| ⊘ | 跳过（可选任务，备注理由）|

## 更新协议

1. 开始一个 T-task → 状态置 ◐；完成（验收过 + commit）→ ✅ + 填 commit hash。
2. 阻塞 → ⛔ + 备注（原因 + 需要的决策），停下汇报，不静默重试。
3. 每 Phase 收尾更新「进度总览」百分比。
4. 汇报格式：Phase 级百分比总览 + 展开当前 Phase 的 T-task 明细。

---

## 进度总览

| Phase | 名称 | 任务数 | 完成 | 状态 |
|-------|------|:---:|:---:|------|
| 1 | 数据模型 + 核心路由 | 6 | 1 | ◐ 进行中 |
| 2 | TickOrchestrator | 6 | 0 | ☐ 未开始 |
| 3 | CLI + Command | 7 | 0 | ☐ 未开始 |
| 4 | Agent Prompt 模板 | 10 | 0 | ☐ 未开始 |
| 4b | Commit→PR→CI/CD Pipeline | 7 | 0 | ☐ 未开始 |
| 5 | 测试 | 17 | 0 | ☐ 未开始 |
| 6 | 审计与验证方法论 (B15) | 5 | 0 | ☐ 未开始 |
| 7 | Init-Loop 契约扩展 | 4 | 0 | ☐ 未开始 |
| **合计** | | **62** | **1** | **~2%** |

---

## Phase 1 — 数据模型 + 核心路由

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T1 | `engine/state.py`（tick/expected_stage/coverage_map/batch_state_json/progress_tree_json + #33-36 + _VALID_STAGES）| T17/T22 + test_engine_state(ext) | ✅ | (本次) |
| T2 | `loop/stage_router.py`（23 转换 + 分源/全局 refine 计数）| T18 | ☐ | |
| T3 | `engine/batch_state.py`（**新建** B1.1a）| T22 | ☐ | |
| T4 | `engine/design_doc.py`（**新建** B10.4a parse）| T25/T21 | ☐ | |
| T4b | `engine/progress_tree.py`（**新建** B9）| T23/T24 | ☐ | |
| T4c | `engine/gap_analysis.py`（**新建** B10.2）| T25 | ☐ | |

## Phase 2 — TickOrchestrator

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T5 | `loop/orchestrator.py` 4 个 `_after_*` verifier/audit handler | T17/T19 | ☐ | |
| T6 | `loop/orchestrator.py` `_build_action()` 8 种 action | T17 | ☐ | |
| T7 | `loop/orchestrator.py` `_apply_result_to_state()` 扩展 | T17/T19 | ☐ | |
| T7b | `loop/orchestrator.py` ProgressTree 更新 + `_display_progress()` | T23 | ☐ | |
| T7c | `loop/orchestrator.py` Phase 0 handlers（gap_scan/gap_review/research/inject_supplement）| T25 | ☐ | |
| T8 | `loop/convergence.py` `evaluate()` +design_coverage_ok/system_deep_audit_ok | T21 + test_loop_convergence(ext) | ☐ | |

## Phase 3 — CLI + Command

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T9 | `cli/dev_loop.py` --design-doc 选项 | T21 + test_cli_dev_loop_extended(ext) | ☐ | |
| T9b | `cli/progress.py`（**新建** ae progress）| T23 | ☐ | |
| T10 | `commands/dev-loop.md` 8-stage 重写（移除 4 外部依赖）| Plugin 验收 + grep 断言 | ☐ | |
| T10b | `commands/progress.md`（**新建**）| Plugin 验收 | ☐ | |
| T10c | `tools/pr_backend.py`（**新建** PRBackend/GitHub/GitLab）| T26e | ☐ | |
| T11 | `skills/auto-engineering/SKILL.md` 分层验证约束 | Plugin 验收 + grep | ☐ | |
| T12 | `design/BEACON.md` 更新决策表+当前状态 | 文档评审 | ☐ | |

## Phase 4 — Agent Prompt 模板

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T13 | `prompts/roles/` ComponentVerifier prompt | T19/T26c | ☐ | |
| T14 | `prompts/roles/` SystemVerifier prompt | T19/T26c | ☐ | |
| T15 | `prompts/roles/` Critic prompt 精简 | T19 + grep | ☐ | |
| T16 | `prompts/roles/` Architect prompt design-doc 模式 | T20/T21 | ☐ | |
| T16b | `prompts/roles/` + `agents/authz.py` gap_scan/research prompt+授权 | T25/T26 + test_authz(ext) | ☐ | |
| T16c | `prompts/roles/` Developer prompt B11 注入 | T21 + wc -w | ☐ | |
| T16d | `SKILL.md` + `commands/dev-loop.md` B11 注入 | wc -w + Plugin 验收 | ☐ | |
| T16e | `prompts/registry.py`（**新建** PromptRegistry）| T26d | ☐ | |
| T16f | `prompts/roles/`(9) + `prompts/fragments/`(8) B12 目录骨架+迁移 | T26d | ☐ | |
| T16g | `scripts/sync-prompts.py` + `agents/base.py` 重构 | T26d + T16m | ☐ | |

## Phase 4b — Commit→PR→CI/CD Pipeline (B13)

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T16h | `.github/workflows/ci.yml`（**新建**远程 CI 薄壳）| make ci 绿 | ☐ | |
| T16i | `.github/workflows/release.yml` 修复 merge 冲突 | grep 断言无冲突标记 | ☐ | |
| T16j | `commands/code-review.md` 终态语义校准 + 去虚构引用 | T16m + Plugin 验收 | ☐ | |
| T16k | `tools/git_tools.py:110` git add -A→精确 | test_git_tools(ext) | ☐ | |
| T16l | `gates/test_gate.py` 环内增量测试（files_changed→pytest -k）| T26f | ☐ | |
| T16m | `scripts/sync-prompts.py` 扩展覆盖 code-review.md | 自含（标记区校验）| ☐ | |
| T16n | `gates/commit_msg_gate.py`（**可选新建** Angular 格式）| T26f | ☐ | |

## Phase 5 — 测试

| T | 内容 | 状态 | Commit |
|---|------|:---:|--------|
| T17 | TickOrchestrator 单元（init/tick/8 stage）| ☐ | |
| T18 | 23 条 StageRouter 转换（含 T17b + refine 上限 DS-8）| ☐ | |
| T19 | 验证层集成（component→plate→system verifier/audit）| ☐ | |
| T20 | plan-refine 回路（3 层 + 分源≤2/全局≤4 + RefineRequest 归一）| ☐ | |
| T21 | 完整 2 轮 E2E（design-doc → done）| ☐ | |
| T22 | BatchState 跨 tick 持久化 + 恢复 | ☐ | |
| T23 | ProgressTree 构建/同步/聚合/展示/序列化 | ☐ | |
| T24 | ProgressTree plan_refine 动态同步（added/modified/removed/conflicts）| ☐ | |
| T25 | Pre-flight 全路径（4 用户路径 + has_blocking Guardrail）| ☐ | |
| T26 | ResearchAgent 分层知识源 | ☐ | |
| T26b | Tick 编排延迟 P95<2s（DS-10）| ☐ | |
| T26c | verifier Sonnet 复核兜底（DS-9）| ☐ | |
| T26d | PromptRegistry + B12 迁移（背书 T16e/f/g）| ☐ | |
| T26e | PRBackend 选型（背书 T10c/T33）| ☐ | |
| T26f | 环内增量 test_gate + commit_msg（背书 T16l/T16n）| ☐ | |
| T26g | B15 Guardrail REDGuard/FreshGate/RegressionGate（背书 T29/T30）| ☐ | |
| T26h | AuditGate 语义层 + finding 生命周期（背书 T31）| ☐ | |

## Phase 6 — 审计与验证方法论 (B15)

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T27 | `gates/deep_audit.py` 骨架→实际（3-agent 编排）| test_deep_audit(ext) | ☐ | |
| T28 | `commands/audit.md` 内化（去 Superpowers 依赖）| grep 断言 | ☐ | |
| T29 | `loop/guardrail.py` REDGuard + FreshGate | T26g | ☐ | |
| T30 | `loop/guardrail.py` RegressionGate + audit regex 自测 | T26g + test_gate_audit(ext) | ☐ | |
| T31 | `gates/audit.py` + `orchestrator.py` AuditGate 语义层 + finding 生命周期 | T26h | ☐ | |

## Phase 7 — Init-Loop 契约 v5.6 扩展 (IL.2-IL.5)

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T32 | `init-manifest.schema.json`(新建) + `loop/init_contract.py` schema SSOT | IL-AC-06 | ☐ | |
| T33 | +`conventions.ci_platform` + `structure.design_root` 字段及消费点 | IL-AC-08 + T26e | ☐ | |
| T34 | monorepo 单包降级 WARN | IL-AC-08 | ☐ | |
| T35 | reference fixture + round-trip 消费者驱动契约测试 | IL-AC-07 + test_init_contract(ext) | ☐ | |

---

## 阻塞/决策日志

| 日期 | T-task | 阻塞/决策 | 处理 |
|------|--------|----------|------|
| 2026-07-09 | T1 | **状态字段命名契约**：设计 B1.1 表用 `stage`/`verdict`/`round_history`(EngineState字段)，代码用 `current_stage`/`critic_verdict`(20文件/1486测试)，round_history 由 round.py 承载非字段；B1.1 #3 枚举 stale(5值) vs C.10 全量(12值)。语义等价，纯命名/表示分歧，非功能缺口。governs 全部 62 task 的字段引用。 | ✅ 定案 **A 代码为名称权威**：保留代码名，同步 B1.1 表标签+修枚举+澄清 round_history。零代码 churn。 |
| 2026-07-09 | (pre-existing) | **发现既有失败（非本轮引入）**：`test_checkpoint_store.py` 5 项在 clean tree 已 fail——`_fake_state(step="idle")` 与 `CheckpointEnvelope.step: int` 冲突（test fixture bug）。与 T1 无关（stash 验证）。 | ⏳ 记录待处理；不阻塞 T1。建议 Phase 5/独立轮次修 fixture（step 应传 int 或改字段名）。 |
