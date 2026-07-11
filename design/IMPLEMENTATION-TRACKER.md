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

> ✅ **关键风险已缓解（2026-07-11 T9 接线）**：v5.6 Tick 引擎原「端到端跑不通」（`tick_orchestrator.py` 单测全绿但无运行入口）已接线——`ae dev-loop --init/--tick/--result/--status/--resume` CLI 入口 + 跨进程 `TickOrchestrator.restore()` + A3 写侧落地，e2e 真跑 3 独立进程验证 thread_id/游标跨进程保真（fe8bee2/f4e4175/0a2daca）。**残余**：`commands/dev-loop.md` 仍 v5.1 Agent-tool 模式（T10 重写）+ `skills/SKILL.md`（T11）待做——Command/Skill 层重写是 Phase 3 后续。

| Phase | 名称 | 任务数 | 完成 | 状态 |
|-------|------|:---:|:---:|------|
| 1 | 数据模型 + 核心路由 | 6 | 6 | ✅ 完成 |
| 2 | TickOrchestrator | 6 | 6 | ✅ 完成（代码 + **已接线**，T9：--init/--tick 端到端可跑）|
| 3 | CLI + Command | 8 | 7 | ◐ T9 接线✅ + T9b progress✅ + T10 dev-loop 重写✅ + T10b progress.md✅ + T10c PRBackend✅ + T11 SKILL✅ + T12 BEACON✅（Wave 1 完成）；仅剩 **T10d 语义移除**（G-retire 红线，v5.5 活跃待确认）|
| 4 | Agent Prompt 模板 | 10 | 0 | ☐ 未开始 |
| 4b | Commit→PR→CI/CD Pipeline | 7 | 0 | ☐ 未开始 |
| 5 | 测试 | 17 | 4 | ◐ 部分（单元层 T17/T18/T22/T23 ✅；集成/E2E 待补）|
| 6 | 审计与验证方法论 (B15) | 5 | 0 | ☐ 未开始（deep_audit/audit/guardrail 仅 v5.5 骨架）|
| 7 | Init-Loop 契约扩展 | 4 | 0 | ☐ 未开始（schema.json 缺）|
| 8 | 设计文档深化补充（审计 S-task）| 22 | 22 | ✅ 完成（2026-07-11 深度审计 → 全部收口）|
| 9 | 代码审计修复（审计 A-task）| 15 | 13 | ◐ A2/A5/A6/A7/A8/A10-A15 + checkpoint 契约（A1✅/A3 读+写侧✅，fe8bee2/f4e4175）完成；A4 需决策（接线/删除）；A9 ⛔ mypy 未装 |
| **合计** | | **100** | **58** | **~24% 代码；文档深化 22/22 ✅；代码审计 13/15；端到端：tick 引擎已接线（--init/--tick 真跑✅）+ Phase 3 Wave 1 完成（progress CLI/命令/SKILL/PRBackend/dev-loop v5.6 重写）；下一步 Wave 2 Phase 4 prompt** |

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
| T9 | **TickOrchestrator CLI 接线**（跨进程 restore + A3 写侧 + `dev_loop.py` --init/--tick/--result/--status/--resume/--design-doc）| test_tick_orchestrator(restore/A3) + test_cli_dev_loop_tick(7) + e2e 真跑 3 进程 | ✅ | fe8bee2/f4e4175/0a2daca |
| T9b | `cli/progress.py`（**新建** ae progress）| T23 | ✅ | 4628c33（读持久化 progress_tree_json → display/summary，无 checkpoint 优雅降级；4 tests）|
| T10 | `commands/dev-loop.md` 8-stage 重写（移除 4 外部依赖）| Plugin 验收 + grep 断言 | ✅ | e13da0c（两份 dev-loop.md 统一 v5.6 Tick 协议；action 参考表对齐 _build_action；移除 Plan/code-reviewer/code-review/gsd-code-fixer + dead AE_JSONL_MODE）|
| T10b | `commands/progress.md`（**新建**）| Plugin 验收 | ✅ | 6e30f35（/ae:progress 委托 ae progress，flags 对齐实际 CLI）|
| T10c | `tools/pr_backend.py`（**新建** PRBackend/GitHub/GitLab）| T26e | ✅ | 9da5dbe（PRBackend ABC + gh/glab 薄壳 + select_backend(ci_platform) + doctor 非致命预检；12 tests）|
| T11 | `skills/auto-engineering/SKILL.md` 分层验证约束 | Plugin 验收 + grep | ✅ | 6a4fe19（5 层验证矩阵 + LEAF/PLATE/FULL 自动裁剪 + 不可短路约束；修 JSONL→tick action）|
| T12 | `design/BEACON.md` 更新决策表+当前状态 | 文档评审 | ✅ | e27a8fd（当前状态记 T9 接线完成，无 status 翻转）|
| T10d | v5.5 orchestrator 退役时移除 semantic_evaluator 全链（S-1 代码；semantic_evaluator.py + orchestrator/convergence/round/checkpoint/status + 8 测试）| test_loop_orchestrator/semantic(ext) | ☐ | |

## Phase 4 — Agent Prompt 模板

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T13 | `prompts/roles/` ComponentVerifier prompt | T19/T26c | ✅ | cf4e3e5 |
| T14 | `prompts/roles/` SystemVerifier prompt | T19/T26c | ✅ | cf4e3e5 |
| T15 | `prompts/roles/` Critic prompt 精简 | T19 + grep | ✅ | 02d2112 |
| T16 | `prompts/roles/` Architect prompt design-doc 模式 | T20/T21 | ✅ | cf4e3e5 |
| T16b | `prompts/roles/` + `agents/authz.py` gap_scan/research prompt+授权 | T25/T26 + test_authz(ext) | ✅ | cf4e3e5+25cd2fb |
| T16c | `prompts/roles/` Developer prompt B11 注入 | T21 + wc -w | ✅ | cf4e3e5 |
| T16d | `SKILL.md` + `commands/dev-loop.md` B11 注入 | wc -w + Plugin 验收 | ✅ | e116e37 |
| T16e | `prompts/registry.py`（**新建** PromptRegistry）| T26d | ✅ | 9454dc4 |
| T16f | `prompts/roles/`(9) + `prompts/fragments/`(8) B12 目录骨架+迁移 | T26d | ✅ | cf4e3e5 |
| T16g | `scripts/sync-prompts.py` + `agents/base.py` 重构 | T26d + T16m | ✅ | f8c1710+6adafdd |

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
| T19 | 验证层集成（component→plate→system verifier/audit）| ✅ | test_tick_orchestrator TestPlateConvergence (PLATE 6-agent + FULL 7-agent 尾部路由) |
| T20 | plan-refine 回路（3 层 + 分源≤2/全局≤4 + RefineRequest 归一）| ✅ | loop/refine.py (B6.10 归一) + test_refine(11) + test_tick_orchestrator TestRefineRequestDelivery/TestRefineSourcesAndLimits + fragments/refine_input.md |
| T21 | 完整 2 轮 E2E（design-doc → done）| ✅ | LEAF 单轮 TestFullLeafConvergence + 跨 tick restore E2E TestCrossTickE2E (37de252) + **2 轮 design-doc E2E** TestTwoRoundDesignDocE2E (gap_scan→轮1 覆盖缺口 plan_refine→轮2 收敛 GOAL_ACHIEVED) |
| T22 | BatchState 跨 tick 持久化 + 恢复 | ✅ | test_batch_state.py (21) |
| T23 | ProgressTree 构建/同步/聚合/展示/序列化 | ✅ | test_progress_tree.py (20) |
| T24 | ProgressTree plan_refine 动态同步（added/modified/removed/conflicts）| ✅ | test_progress_tree TestSync (单元) + test_tick_orchestrator TestPlanRefineProgressSync (编排集成: added 保留旧 / removed 标记不删) |
| T25 | Pre-flight 全路径（4 用户路径 + has_blocking Guardrail）| ✅ | test_gap_analysis(14) + **G6 NoDeferredBlockingGap 接线**(guardrail.py, 修复死代码 validate_resolutions 从未接线) + test_guardrail TestNoDeferredBlockingGap(11) + test_tick_orchestrator TestPhase0BlockingGapGuardrail(5, 4 路径 Fill/Research/Defer/Defer+Research + architectural defer→GUARDRAIL_BLOCK) |
| T26 | ResearchAgent 分层知识源 | ✅ | research action 4-tier `knowledge_sources` 契约（tier_order + memory_constraint grep/禁批量并行）+ expected_format(source_tier/confidence/recommended_design) test_tick_orchestrator TestPhase0Research::test_research_action_injects_four_tier_knowledge_contract + test_prompt_registry TestResearchTieredKnowledge(4: 四层/内存护栏/可信度分级/只读) |
| T26b | Tick 编排延迟 P95<2s（DS-10）| ✅ | test_tick_orchestrator TestTickLatencyInstrumentation（逐 tick 打点/预算告警）+ TestOrchestrationP95Budget（≥30 tick 聚合 statistics.quantiles P95<ORCH_BUDGET_MS 断言 + t_gate 墙钟参考观测无阈值，§4108 离线聚合验收）|
| T26c | verifier Sonnet 复核兜底（DS-9）| ✅ | _build_action recheck 字段 (component/system_verifier) + 两 prompt 5 步复核协议 + recheck_log + test_tick_orchestrator TestVerifierRecheck + test_prompt_registry TestVerifierRecheckProtocol |
| T26d | PromptRegistry + B12 迁移（背书 T16e/f/g）| ✅ | 570bec0（B12.5 版本锁）+ test_prompt_registry(24)+test_sync_prompts(9) |
| T26e | PRBackend 选型（背书 T10c/T33）| ☐ | |
| T26f | 环内增量 test_gate + commit_msg（背书 T16l/T16n）| ☐ | |
| T26g | B15 Guardrail REDGuard/FreshGate/RegressionGate（背书 T29/T30）| ✅ | T29 test_guardrail: TestREDGuard(8)+TestFreshGate(5)+name注入(4)+retry粒度(4)；T30 test_guardrail: TestRegressionGate(7，含真跑嵌套 pytest revert-red-restore + git rm 分支)+test_gate_audit TestAuditRegexSelfTest(9)。三类 Guardrail 均有确定性证据测试 |
| T26h | AuditGate 语义层 + finding 生命周期（背书 T31）| ☐ | |

## Phase 6 — 审计与验证方法论 (B15)

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T27 | `gates/deep_audit.py` 骨架→实际（3-agent 编排）| test_deep_audit(ext) | ✅ | DeepAuditFinding.agent_source str→list[str]；`recount_findings()` 权威去重入口（key=(file,line,desc[:40]归一化)，保留最高severity+合并agent_source+重算p0/p1/p2）；DeepAuditGate.run() + tick `_after_plate/system_deep_audit` 共用（消解路由信任Agent自报计数的静默失效 §B6.7a L1068）；test_gate_deep_audit TestDeepAuditGateDedup(6) + test_tick_orchestrator 2 recount 集成（膨胀不误触发/漏报仍触发）|
| T28 | `commands/audit.md` 内化（去 Superpowers 依赖）| grep 断言 | ✅ | audit.md 三阶段自含重写（Phase1 `ae gate-check --all`+make / Phase2 3-agent B6.7a 内化 / Phase3 `recount_findings` 确定性求值），移除"执行通用 `/audit`" Superpowers 运行时委托（B14 零外部依赖）；test_plugin_contract TestAuditCommandInternalized(3: 无通用委托/委托自有Gate+stage/声明零外部依赖）|
| T29 | `loop/guardrail.py` REDGuard + FreshGate | test_guardrail(ext) | ✅ | G7 REDGuard（post/developer：`git log`定位先于实现的独立测试commit + `merge-base --is-ancestor`祖先校验 + 信任red_evidence，`_STRICT_RED` opt-in重跑；纯配置task豁免）+ G8 FreshGate（post/developer,critic：`_aggregate_sha`(files_changed)比对gate快照，陈旧→retry）；`GuardrailResult.guardrail_name`+Chain注入；S-3生产者契约（`_run_developer_gates`注入`files_snapshot_sha`+`ran_at`，否则G8静默失效）；S-4 retry键粒度`{stage}:{guardrail_name}`+FreshGate `rerun_gates`分流（不清实现）；tick挂运行时句柄`batch_state`/`_plan`；`default()`6→8；test_guardrail +REDGuard(8)/FreshGate(5)/name注入(4)/retry粒度(4)/helper(2) |
| T30 | `loop/guardrail.py` RegressionGate + audit regex 自测 | T26g + test_gate_audit(ext) | ✅ | G9 RegressionGate（post/developer，block）：`_current_regression_task`取batch首个`kind=="regression_fix"` task；`revert(git checkout impl^ -- 实现文件)→_run_test MUST FAIL→finally restore(git checkout HEAD)→_run_test MUST PASS`；S-19新建实现文件（impl^无pathspec→rc≠0）走`git rm`模拟"修复前不存在"；`_run_test`用`sys.executable -B -m pytest <root> -k <id> -o addopts= -p no:cacheprovider`（`-B`禁写.pyc避免同秒git checkout mtime相同致陈旧字节码掩盖回退）；无实现文件/缺test_id/缺commit_hash→block；`default()`8→9。plan.py Task+`kind`/`regression_test_id`字段+task_factory透传。audit.py正则自测（`TestAuditRegexSelfTest` 9测：每pattern正例/反例+元测试断言全覆盖）——surfaced并修复`_SILENT_EXCEPT_PY`的`# noqa`死分支（`\b#`永不匹配→改`\bnoqa\b`）。test_guardrail +RegressionGate(7)/factory(9→) |
| T31 | `gates/audit.py` + `orchestrator.py` AuditGate 语义层 + finding 生命周期 | T26h | ☐ | |

## Phase 7 — Init-Loop 契约 v5.6 扩展 (IL.2-IL.5)

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T32 | `init-manifest.schema.json`(新建) + `loop/init_contract.py` schema SSOT | IL-AC-06 | ☐ | |
| T33 | +`conventions.ci_platform` + `structure.design_root` 字段及消费点 | IL-AC-08 + T26e | ☐ | |
| T34 | monorepo 单包降级 WARN | IL-AC-08 | ☐ | |
| T35 | reference fixture + round-trip 消费者驱动契约测试 | IL-AC-07 + test_init_contract(ext) | ☐ | |

---

## Phase 8 — 设计文档深化补充（2026-07-11 深度审计 S-task）

> 来源：2026-07-11 设计文档深度审计（`_scratch/design-audit/AUDIT-REPORT.md` + `findings-{A,B,C}.md`）。
> 性质：**设计规格缺陷收口**（矛盾/契约模糊/边界未定义），非代码缺口。方向遵守 design-document-inviolability：补全规格，不降级。
> 决策（2026-07-11 用户定案）：全做；S-1 方向A（移除语义评估）；S-1 **代码**移除跟踪至 Phase 3 T10d（随 v5.5 退役，避免破坏活跃路径）。

| S | 深化项 | 严重度 | 位置 | 状态 | Commit |
|---|-------|:---:|------|:---:|--------|
| S-1 | B4↔B7 语义评估矛盾收口（v5.6 全路径无语义评估；Python 永不调 LLM）| P1 | §B4 L764/§B7 L1187,L1198 | ✅ | 本轮（代码→T10d）|
| S-2 | coverage_map item 权威 schema（消解 B6.4 字符串 vs B6.6a/B6.10 结构体）| P1 | §B6.4/§B6.6a/§B6.10 | ✅ | 本轮 |
| S-3 | FreshGate(G8) 契约：B5 每 Gate 产出 files_snapshot_sha+ran_at | P1 | §B3.2/§B5.1 | ✅ | 本轮 |
| S-4 | guardrail_retry_counters 键粒度 + G8 retry 语义（rerun_gates 动作）| P1 | §B3 L629-649,L646,L702 | ✅ | 本轮 |
| S-5 | file-bridge 契约边界矩阵（缺失/半写/错位/重复/超时→action+error_code+恢复）| P1 | §C.3.5（新增）| ✅ | 本轮 |
| S-6 | Guardrail 数量统一（当前5/目标9 + 状态列）| P1 | §C.8/附录/§B3 | ✅ | 本轮 |
| S-7 | done verdict 完整枚举 + 终态优先级 + HARD_LIMIT 拆名 | P1 | §C.3.1/§C.5.4/§C.5.5 | ✅ | 本轮 |
| S-8 | B2 转换表增"决策方(router 纯转换/orchestrator 委派)"列 | P1 | §B2 L544-556 | ✅ | 本轮 |
| S-9 | REDGuard RED 证据机制（否则明标为启发式）| P1 | §B15.2 | ✅ | 本轮 |
| S-10 | ResearchAgent 工具级内存护栏规格（authz 限 Read 范围/禁 ls -R）| P1 | §B10.6/§B11.7 | ✅ | 本轮 |
| S-11 | B14 外部依赖清单收口（audit.md 内化关系，消解与 B15.1 矛盾）| P1 | §B14.1/§B15.1 | ✅ | 本轮 |
| S-12 | commit 序列规范（test+impl）+ B9.5 父节点 pending 聚合分支 | P1 | §B13/§B15/§B9.5 | ✅ | 本轮 |
| S-13 | C.12/C.12.1 路径修正 tick_orchestrator.py + 矩阵加"实现状态"澄清 | P1 | §C.12 Phase2 | ✅ | 本轮 |
| S-14 | B1.1 数据模型表补全 #26/#33/#34/#35/#36 | P2 | §B1.1 L370 | ✅ | 本轮 |
| S-15 | B6.1a 现状描述追代码（task_factory 已迁移嵌套 schema）| P2 | §B6.1a L916 | ✅ | 本轮 |
| S-16 | B4 参数→判定对照 + semantic_satisfied 标 legacy | P2 | §B4 | ✅ | 本轮 |
| S-17 | plan_refine 双重身份定案（architect 子模式；澄清 _VALID_STAGES 语义）| P2 | §B1.1/§C.10 | ✅ | 本轮 |
| S-18 | checkpoints WITHOUT ROWID + 大 blob 反模式（定案改 rowid，迁移待落地）| P2 | §B1.3 L485 | ✅ | 本轮（DDL 迁移单列）|
| S-19 | RegressionGate 新建文件分支进伪码 + 正反例断言 | P2 | §B3.3 | ✅ | 本轮 |
| S-20 | 示例坐标加"(示意)"标注（防误读为接线证据）| P2 | §C.3.2/C.3.1 | ✅ | 本轮 |
| Q-1 | B10.5 Defer+Research 复审回路(T0.7)：定案保留 + 理由 | P2 | §B10.5 | ✅ | 本轮 |
| Q-2 | B9 ProgressTree 聚合/removed 保留：定案保留 + 理由 | P2 | §B9.1 | ✅ | 本轮 |

---

## Phase 9 — 代码审计修复（2026-07-11 code audit A-task）

> 来源：2026-07-11 代码实现深度审计（`_scratch/reports/2026-07-11-audit.md`；Phase 1 自动化 + 3 并行只读 agent）。总体 6.8/10。
> 性质：**代码 bug 修复**（活跃 CLI 路径真实 bug + 虚化），区别于 Phase 8（设计规格收口）。全部经 grep 直接验证。
> 决策（2026-07-11 用户定案）：**仅报告，暂不修 → 落表跟踪，作为开发任务**（不跨轮次遗失）。A1/A2/A5 + P2 为纯 bug 修复无架构变更；A3/A4 涉及 tick 接线/删模块需拍板。

| A | 修复项 | 严重度 | 位置 | 验收 | 状态 | Commit |
|---|-------|:---:|------|------|:---:|--------|
| A1 | `ae status` verdict 恒空 → 读 `critic_verdict`（输出 key 仍 `verdict`，符 §B13.2）| P1 | `cli/status.py:73,80` | test_cli_status 断言非空 verdict | ✅ | 89d850a |
| A2 | Gate 崩溃 fail-open → 执行异常计 `failed_count`（fail-closed），区分 skipped(不适用)/errored(崩溃)| P1 | `cli/gate_check.py:96-99,23` | test_gate_check 崩溃 gate → exit≠0 | ✅ | 633af89 |
| A3 | `batch_state_json` 持久化断链（零写零读 → 游标每 tick 归零）| P1 | `state.py:121,215`；`tick_orchestrator.py:236` | T22 跨 tick 恢复 | ✅ 读侧✅（2fc8950 deserialize→EngineState）+ 写侧✅（fe8bee2 `_populate_serialized_state`）+ restore✅（f4e4175）；跨进程游标不归零，e2e 真跑验证 | 2fc8950/fe8bee2/f4e4175 |
| A4 | `gap_analysis.py` 孤儿（GapReport 全实现+有测试，生产 0 引用，tick 用内联 dict）| P1 | `engine/gap_analysis.py` vs `tick_orchestrator.py:516` | 接线去重 or 删除 | ☐ **需决策：接线/删除** | |
| A5 | F821 `Any` 未导入（type_check gate 会红）→ TYPE_CHECKING 块加 `from typing import Any` | P1 | `loop/stage_router.py:284`、`runtime/runtime.py:42` | ruff F821 清零 + type_check gate 绿 | ✅ | 04db92c |
| A6 | 畸形 batch_plan 抛 raw KeyError → 改抛 AEError 契约错误 | P2 | `loop/task_factory.py:58` | test_task_factory 缺 id 断言 | ✅ | c3e6b4f |
| A7 | per-task ctx 仅顶层浅拷贝（注释宣称隔离，名不副实）→ 文档如实标注或 outputs 深拷 | P2 | `loop/round.py:186` | 自含 | ✅ | 715facc |
| A8 | `set_channels` 绕过 write_field 所有权校验 + 重复 `import logging` | P2 | `engine/state.py:321` | 自含 | ✅ | 6cece7f |
| A9 | 8× 集中 `# type: ignore`（graph 节点弱类型区）→ 补 Protocol | P2 | `engine/design_doc.py:220-298` | mypy 无 ignore | ⛔ **需决策**：mypy 未装，验收「mypy 无 ignore」不可本地验证；装 mypy=dep 审批（同 markdown-it-py 先例）or 接受文档化 ignore | |
| A10 | B904：`raise ValueError` 无 `from`（丢异常链）| P2 | `loop/checkpoint/migration.py:62` | ruff B904 清零 | ✅ | 67546c3 |
| A11 | B905：`dict(zip(...))` 无 `strict=`（静默截断）| P2 | `gates/_tools.py:40` | ruff B905 清零 | ✅ | 4301055 |
| A12 | docstring 漂移：guardrail 称 drop→retry+DeprecationWarning，实际 unknown→stop | P2 | `loop/guardrail.py:69-72` | 文档与代码一致 | ✅ | fec06fd |
| A13 | docstring 漂移：ContractGate 声明已不存在的 `run(project_root, contracts=)` 签名 | P2 | `gates/contract.py:14-15` | 文档与代码一致 | ✅ | b9baa9e |
| A14 | docstring 漂移：StageRouter T4/T5 编号在 docstring 与内联注释间互换（判定：内联+设计§B2 为准，docstring 漂移）| P2 | `loop/stage_router.py:8-15` | 编号统一 + 对齐设计追溯 | ✅ | 78ff8ac |
| A15 | ruff 样式批（实际 407 findings 非~186）：安全 `--fix` 已修 264 项/84 文件 | P2 | 全仓 | 安全 auto-fix + 全量零新增失败 | ◐ | 1a22a99（余 163 非自动修 → 新任务）|

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
| 2026-07-11 | Phase 8 + T10d | **设计文档深度审计（S-task 落表）**：3 并行子代理审 v5.6-Design-Loop + INIT-LOOP-CONTRACT，发现 P0×4（全代码缺口，已有 T 编号）+ P1×13 + P2×7 + 过度设计×2（均设计规格缺陷：矛盾/契约模糊/边界未定义）。用户定案：全做 + S-1 方向A（移除语义评估）。S-1 **代码**移除跟踪至 Phase 3 T10d（随 v5.5 退役，避免破坏活跃路径）。 | ◐ Phase 8 执行中；审计报告 `_scratch/design-audit/AUDIT-REPORT.md` + `findings-{A,B,C}.md`。 |
| 2026-07-11 | Phase 9 (A1-A15) | **代码实现深度审计（A-task 落表）**：Phase 1 自动化(ruff/grep) + 3 并行只读 agent 审 auto_engineering/(82文件/16K行)。总体 6.8/10——内核代码工艺高（异常纪律优秀/无静默吞异常/依赖方向干净/无环/DRY），但 3 活跃 CLL 路径真实 P1 bug（A1 status verdict 恒空 / A2 gate 崩溃 fail-open / A3 batch_state 断链）+ A4 gap_analysis 孤儿 + A5 F821 + 10 P2（docstring 漂移/B904/B905/ruff 样式）。全部 grep 直接验证。 | ◐ 用户定案 **仅报告暂不修 → 落表跟踪作为开发任务**。A3 并入 Phase 3 tick 接线；A4 需决策（接线/删除）。报告 `_scratch/reports/2026-07-11-audit.md`。 |
| 2026-07-11 | Phase 9 孤立快修批 | **9 项孤立快修完成（superpowers TDD/lint-verify，每任务一 commit）**：A5=04db92c、A10=67546c3、A11=4301055（prior）+ A12=fec06fd、A13=b9baa9e、A14=78ff8ac（docstring 对齐设计，A14 判定内联+§B2 为准）、A2=633af89（gate fail-closed，TDD）、A6=c3e6b4f（KeyError→AEError，TDD）、A15=1a22a99（ruff safe --fix 264 项/84 文件）。**A14/A2/A6 过程中发现审计估计偏差**：A13 无 AttributeError（Gate 基类有 contracts 默认）、A14 是 docstring 漂移非内联漂移、A15 实际 407 findings 非~186。全量 1692 passed / 8 failed（与修复前完全一致，零新增）。 | ✅ 用户定案 A15 安全 auto-fix + 余项另立（#73）。**下一步：checkpoint 契约修复（A1/A3 根因，方向①反序列化→EngineState）**。A4 决策 / A7-A9 P2 待办。 |
| 2026-07-11 | Phase 9 checkpoint 契约修复 | **deserialize shape-aware 分派 + A1 + e2e（计划 `design/checkpoint-contract-fix-PLAN.md`，8a8991a）**：2fc8950=deserialize_state 按 dict 形状三路分派（channels→Envelope / thread_id→EngineState / else→raw dict，marker 有 guard 测试）关闭 5×test_checkpoint_store；89d850a=A1 status.py 两分支读 critic_verdict（输出 key 仍 verdict）关闭 1×test_cli_status_extended；5983bca=e2e 测试改文件 store 关闭 1×e2e。**修正计划基线错误**：计划 §4 把 e2e test_full_cycle_checkpoint_save_round 归为 deserialize 根因，实测在 clean main 上它从不因 deserialize 失败——真根因是 orchestrator.run() finally close 调用方传入的 :memory: store → 测试随后 list_all 断言失败（独立 store 生命周期 bug）。A3 读侧由 deserialize 修复自动保真（batch_state_json round-trip），写侧仍属 Phase 3。 | ✅ 8 pre-existing 失败 → 1（仅 plugin_contract --format 漂移，#73）；1704 passed，零新增。e2e 修法用户定案「改测试用文件 store」（生产用文件 store，close 释放句柄有意设计；:memory: 从不用于生产）。 |
| 2026-07-11 | Phase 9 P2 收尾 (A7/A8/A9) | **A7=715facc（round.py 如实标注浅拷贝：state 有意共享非缺陷）+ A8=6cece7f（state.py import logging 提模块级去重 + set_channels 所有权旁路如实标注）**。A9 阻塞：8× `# type: ignore` 为 mypy 专属错误码，验收「mypy 无 ignore」；venv 未装 mypy → 无法本地验证移除；盲改 parse-critical 代码违「验证后再说完成」。**A3 写侧确认与 T9 耦合**：`_display_progress` 已写 progress_tree_json，但 batch_state_json 零写且**无 restore 路径**——写而不读回是半措施，必须随 T9 跨进程 restore 一起落地。 | ◐ A7/A8 ✅；A9 ⛔ 需决策（装 mypy dev-dep 审批 or 接受文档化 ignore）。Phase 9 = 13/15。**下一大块：Phase 3 T9 接线**（TickOrchestrator 跨进程 restore + A3 写侧 + CLI --init/--tick + file-bridge，为一体耦合单元，需 grounded 子计划）。红线门：A4 删/接线、Phase 4b CI/CD 配置。 |
| 2026-07-11 | Phase 3 T9 接线（`design/phase3-t9-wiring-PLAN.md`，39a4dd2）| **v5.6 tick 引擎端到端接线（TDD, 每步一 commit）**：fe8bee2=T9b A3 写侧（`_populate_serialized_state` 每 save 前序列化 batch_state/progress_tree 回 EngineState）；f4e4175=T9a 跨进程 `restore()` classmethod（重建 _state/_design_doc/_batch_state/_progress_tree/_plan）+ init 持久化 design_doc_path；0a2daca=T9c CLI `--init/--tick/--result/--status/--resume`（tick 分派先于 LLM preflight，§A.1 Python 不调 LLM）。**根因修正（非降级）**：`clear_stage_fields` 在 architect→developer 清空 `EngineState.batch_plan`(#6)，而 batch_state.py 序列化原假设 #6 跨 tick 存活 → batch_state_json 自包含化（内嵌轻量 batch_plan seed，plates 仍不持久化=主设计决策保留）。e2e 真跑 3 独立 `ae` 进程：--init→architect / --tick→developer(tick2, batch_id 保真) / --status→developer，thread_id `2e0845ee` 跨进程一致。 | ✅ 1717 passed / 1 skipped / 1 pre-existing 失败（plugin_contract：`shutil.which("ae")` 命中 stale 全局 `~/.local/bin/ae` 无 `--format`，非本次回归，归 #73）；零新增失败。A3 全链闭合（读+写+restore）。**下一步**：T10 命令重写 / Phase 4 prompt / 红线门 A4/A9/Phase 4b。 |
| 2026-07-11 | Phase 3 Wave 1 收尾（`design/remaining-execution-PLAN.md`）| **Phase 3 剩余 6 任务完成（TDD, 每任务一 commit）**：e27a8fd=T12 BEACON 当前状态记 T9（无 status 翻转）；4628c33=T9b `cli/progress.py`（读持久化 progress_tree_json → display/summary，无 checkpoint 优雅降级，4 tests）；6e30f35=T10b `commands/progress.md`（/ae:progress 委托）；e13da0c=T10 两份 dev-loop.md 统一 v5.6 Tick 协议重写（action 参考表对齐 `_build_action` 实际输出；**移除 4 外部依赖** Plan/code-reviewer/code-review/gsd-code-fixer + dead ref AE_JSONL_MODE，决策 #46 实施非降级）；6a4fe19=T11 SKILL.md 分层验证约束（5 层矩阵 + LEAF/PLATE/FULL 自动裁剪 + 不可短路）；9da5dbe=T10c `tools/pr_backend.py`（PRBackend ABC + gh/glab 薄壳 + select_backend(ci_platform) + doctor 非致命预检，12 tests，去 gh 硬编码）。 | ✅ Wave 1 blast radius 94 passed / 1 pre-existing 失败（#73 同上，非回归）。Phase 3 = 7/8，仅剩 **T10d**（G-retire 红线，v5.5 活跃待确认时机）。**下一步**：Wave 2 Phase 4 Agent Prompt 模板（T13-T16g）。 |
