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

> ⚠️ **关键风险（2026-07-10 状态核对发现）**：Phase 1+2 代码已落地，但 **v5.6 Tick 引擎尚未接入任何运行入口**——`cli/dev_loop.py` 仍用旧 v5.5 `Orchestrator`；无 `ae dev-loop --init/--tick/--result` CLI 入口；`commands/dev-loop.md` 仍是 v5.1 Agent-tool 模式。即 `tick_orchestrator.py`(1017行,~230单测) 单测全绿但**端到端跑不通**（代码存在未集成）。接线 = Phase 3 的 T9/T10 前置。

| Phase | 名称 | 任务数 | 完成 | 状态 |
|-------|------|:---:|:---:|------|
| 1 | 数据模型 + 核心路由 | 6 | 6 | ✅ 完成 |
| 2 | TickOrchestrator | 6 | 6 | ✅ 完成（代码；**未接线**）|
| 3 | CLI + Command | 7 | 0 | ☐ 未开始（**含接线**：T9 --tick 入口 / T10 命令重写）|
| 4 | Agent Prompt 模板 | 10 | 0 | ☐ 未开始 |
| 4b | Commit→PR→CI/CD Pipeline | 7 | 0 | ☐ 未开始 |
| 5 | 测试 | 17 | 4 | ◐ 部分（单元层 T17/T18/T22/T23 ✅；集成/E2E 待补）|
| 6 | 审计与验证方法论 (B15) | 5 | 0 | ☐ 未开始（deep_audit/audit/guardrail 仅 v5.5 骨架）|
| 7 | Init-Loop 契约扩展 | 4 | 0 | ☐ 未开始（schema.json 缺）|
| **合计** | | **62** | **16** | **~26% 代码；端到端 0%（未接线）** |

---

## Phase 1 — 数据模型 + 核心路由

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T1 | `engine/state.py`（tick/expected_stage/coverage_map/batch_state_json/progress_tree_json + #33-36 + _VALID_STAGES）| T17/T22 + test_engine_state(ext) | ✅ | (本次) |
| T2 | `loop/stage_router.py`（23 转换 + 分源/全局 refine 计数）| T18 | ✅ | (本次) |
| T3 | `engine/batch_state.py`（**新建** B1.1a）| T22 | ✅ | (本次) |
| T4 | `engine/design_doc.py`（**新建** B10.4a parse）| T25/T21 | ✅ | (本次) |
| T4b | `engine/progress_tree.py`（**新建** B9）| T23/T24 | ✅ | (本次) |
| T4c | `engine/gap_analysis.py`（**新建** B10.2）| T25 | ✅ | (本次) |

## Phase 2 — TickOrchestrator

> **实现落点偏离（记录，非降级）**：计划列 `loop/orchestrator.py`（扩展旧文件），实际实现为**新文件** `loop/tick_orchestrator.py`（1017 行）。旧 `orchestrator.py`(1208行, v5.5 连续循环) 保留共存（迁移期）。C.5 描述的是 TickOrchestrator，新文件符合设计意图。**未接入 CLL**（见总览关键风险）。

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T5 | `loop/tick_orchestrator.py` 4 个 `_after_*` verifier/audit handler（+`actions.py`+`verification_layers.py`+DesignDoc accessors）| T17/T19 | ✅ | 4cea2cd/627de93/f518bb8/96399ad |
| T6 | `loop/tick_orchestrator.py` `_build_action()` 全 stage action（gap_scan/gap_review/research/architect/developer/critic/component_verifier/plate_deep_audit/system_verifier/system_deep_audit）| T17 | ✅ | 96399ad |
| T7 | `loop/tick_orchestrator.py` `_apply_result_to_state()` | T17/T19 | ✅ | 96399ad |
| T7b | `loop/tick_orchestrator.py` ProgressTree 更新 + `_display_progress()` | T23 | ✅ | 96399ad |
| T7c | `loop/tick_orchestrator.py` Phase 0 handlers（gap_scan/gap_review/research/inject_supplement + T0.7 复审回路）| T25 | ✅ | 96399ad/81e97cc |
| T8 | `loop/convergence.py` `evaluate()` +design_coverage_ok/system_deep_audit_ok（双通过终态优先）| T21 + test_loop_convergence(ext) | ✅ | 7547c19/54f123a |

> **本轮附带修复（2026-07-10, commit f1b327e）**：code-review 发现 system_deep_audit 覆盖度闸门空操作（expected_format 缺 missing_count/diverged_count）+ 覆盖缺口 → plan_refine 补充设计回路（T19）+ 系统级 refine 的 current_design_section 越界。已修 + 补 3 测试。

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
| T17 | TickOrchestrator 单元（init/tick/8 stage）| ✅ | test_tick_orchestrator.py (52) |
| T18 | 23 条 StageRouter 转换（含 T17b + refine 上限 DS-8）| ✅ | test_stage_router.py (43) |
| T19 | 验证层集成（component→plate→system verifier/audit）| ☐ | |
| T20 | plan-refine 回路（3 层 + 分源≤2/全局≤4 + RefineRequest 归一）| ☐ | 部分见 test_tick_orchestrator TestPlanRefineLimit |
| T21 | 完整 2 轮 E2E（design-doc → done）| ☐ | 仅 LEAF 单轮 TestFullLeafConvergence |
| T22 | BatchState 跨 tick 持久化 + 恢复 | ✅ | test_batch_state.py (21) |
| T23 | ProgressTree 构建/同步/聚合/展示/序列化 | ✅ | test_progress_tree.py (20) |
| T24 | ProgressTree plan_refine 动态同步（added/modified/removed/conflicts）| ☐ | |
| T25 | Pre-flight 全路径（4 用户路径 + has_blocking Guardrail）| ◐ | test_gap_analysis(14)+Phase0 部分 |
| T26 | ResearchAgent 分层知识源 | ☐ | |
| T26b | Tick 编排延迟 P95<2s（DS-10）| ◐ | test_tick_orchestrator TestTickLatencyInstrumentation |
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
| 2026-07-09 | T2↔T5 | **Phase 耦合**：T2 DS-8 改 next() 签名（旧 plan_refine_count/max_plan_refines → 新 refine_source_count/refine_global_count/max_refine_per_source/max_refine_global），破坏 v5.5 orchestrator 4 处调用（orchestrator.py:584/675/713/835）+ orchestrator 测试。C.5 sketch 确认新路由：verifier/audit after-handler 内联路由 + 共享 `refine_allowed` staticmethod，next() 仅 critic-MAJOR 分支。T2 无法原子落地不破 orchestrator（Phase 2 T5-T8 才重写）。 | ✅ 定案 **B**：先做零耦合新文件 T3/T4/T4b/T4c，再把 T2+T5-T8 作为「路由组」耦合单元一次性攻克。T2 状态 = ⛔ 延后至路由组。 |
| 2026-07-09 | T4 | **新依赖决策**：B10.4a 明确「用成熟库 markdown-it-py，不自造正则」，但项目未声明也未安装。自造正则 = 设计降级。 | ✅ 用户定案 **加 markdown-it-py 依赖**：pyproject.toml dependencies += `markdown-it-py>=3.0`（MIT，实测 4.2.0）；`uv sync` 安装。符合设计规格，不降级。 |
| 2026-07-09 | T4→T3 | **组内依赖发现**：T3 BatchState.from_design_doc 构造 Plate/Component（B10.4a 数据类），故 T4（定义这些类）须先于 T3。 | ✅ 新文件组内重排：T4 → T3 → T4b → T4c。T4 完成（本次，23 tests）。 |
| 2026-07-09 | T2 | **next() 签名迁移策略**：DS-8 双预算取代 v5.5 单一 plan_refine_count/max_plan_refines。next() 有 4 处调用（orchestrator.py 584/675/713/835）+ 6 处直接测试调用。713/835 只用前 4 参数安全。 | ✅ 用户定案 **A 单一新 API + 迁移保留 Orchestrator**：next() 只留新签名（无旧参数别名，遵守"禁向后兼容 hack"）。584 T9 分支改直调 `StageRouter.refine_allowed`（单一真相源，单全局预算旁路分源），保留 v5.5 "T9-LIMIT" 标签（新 TickOrchestrator 用 "REFINE_LIMIT"）；675 去 max_plan_refines。测试 6 处直调迁移到 DS-8 参数 + 断言 T9-LIMIT→REFINE_LIMIT。153 tests green，lint 无新增。 |
| 2026-07-10 | 全表 | **状态核对：tracker 严重滞后于代码**。Phase 2（T5-T8+TickOrchestrator）实际已在 4cea2cd/627de93/f518bb8/7547c19/54f123a/96399ad 落地，表却仍标 0/6。核对后更新：Phase 2→6/6✅、Phase 5→4/17◐（单元层）、总完成 6→16。**发现关键风险：v5.6 Tick 引擎未接入 CLL**（dev_loop.py 仍用旧 Orchestrator，无 --tick 入口，dev-loop.md 仍 v5.1 模式）——单测全绿但端到端 0%。接线归 Phase 3 T9/T10。 | ✅ 已更新总览+Phase2+Phase5 表 + 关键风险标注。DESIGN-REFINEMENT-PLAN.md 核对：13 DS 全✅（设计细化门，非实现任务），无待纳入项。 |
