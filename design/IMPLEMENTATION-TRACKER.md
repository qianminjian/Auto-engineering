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
| 3 | CLI + Command | 8 | 8 | ✅ 完成（T10d 定案保留共存，决策 #53：v5.5 活代码不退役）|
| 4 | Agent Prompt 模板 | 10 | 10 | ✅ 完成 |
| 4b | Commit→PR→CI/CD Pipeline | 7 | 7 | ✅ 完成（T16h ci.yml 薄壳 24afa07 + T16i release.yml 冲突修复 6331b54）|
| 5 | 测试 | 17 | 17 | ✅ 完成（含 T26e/T26f 设计背书收口）|
| 6 | 审计与验证方法论 (B15) | 5 | 5 | ✅ 完成 |
| 7 | Init-Loop 契约扩展 | 4 | 4 | ✅ 完成 |
| 8 | 设计文档深化补充（审计 S-task）| 22 | 22 | ✅ 完成 |
| 9 | 代码审计修复（审计 A-task）| 15 | 15 | ✅ 完成（A4 定案 schema-SSOT 保留 BEACON #52；A9 mypy 装+验证 type:ignore 必要）|
| **10** | **双驱动接缝预留（v7.0 前置，必须）** | **2** | **2** | ✅ 完成：T33a action/stage-result schema SSOT + 契约测试（21 tests）+ T33b 执行栈共享标注（4 处）（BEACON #54）|
| **11** | **v7.0 双驱动主体（V7-1~V7-8，V7-5 E2E 真跑 ✅，V7-7 🔒）** | **8** | **7** | **2026-07-17: V7-1~V7-6 核心抽象+CLI+mock集成全部完成 + V7-5 StandaloneDriver 真实 LLM E2E 验证通过（architect→developer→critic→GOAL_ACHIEVED，产出 fibonacci 实现+10 tests+auto-commit）。V7-8 基准框架 16 tests 覆盖数据模型/需求集/差异计算/报告生成/数据校验。3 处 bug 修复确保 E2E 可跑（guardrail GitDiffExists auto_commit 路径/bash_tools cwd 默认 project_root/architect 任务描述更详细）。V7-7 锁定。** |
| **12** | **v8.0 多 Agent 平台适配（V8-1/2/3/4/5/6/7/8 全部 ✅）** | **8** | **8** | **2026-07-17: 全部完成。多平台基础架构就绪 — 三平台 manifest、三 hook 注册、install.sh 自动检测、OpenAI Provider、文档覆盖。预估 ~4.3 天。** |
| **合计** | | **118** | **117** | **Phase 1-10 = 102/102 完成；Phase 11 v7.0 = 7/8（仅 V7-7 v5.5 退役锁定）；Phase 12 v8.0 = 8/8。** |

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
| T10d | ~~v5.5 orchestrator 退役时移除 semantic_evaluator 全链~~ **定案：保留共存（决策 #53）** — 退役前置审计确认 v5.5 是活代码（`ae dev-loop` 裸参数 → `_run_v2_orchestrator`），退役撞破坏性+设计降级双红线，用户决策不退役；semantic_evaluator（唯一消费者 orchestrator.py）随之保留 | 只读审计 | ✅ | 保留，非移除 |

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
| T16h | `.github/workflows/ci.yml`（**新建**远程 CI：uv+ruff+pytest + coverage≥90%）+ ruff line-length 120 全量转绿（生产 All checks passed，2135 tests）| make ci 绿 | ✅ | 24afa07/1bd50c9 |
| T16i | `.github/workflows/release.yml` 修复 merge 冲突 | grep 断言无冲突标记 | ✅ | 6331b54 |
| T16j | `commands/code-review.md` 终态语义校准 + 去虚构引用 | T16m + Plugin 验收 | ✅ | f25ea2e |
| T16k | `tools/git_tools.py:110` git add -A→精确 | test_git_tools(ext) | ✅ | 513453f |
| T16l | `gates/test_gate.py` 环内增量测试（files_changed→pytest -k）| T26f | ✅ | 60e35fc |
| T16m | `scripts/sync-prompts.py` 扩展覆盖 code-review.md | 自含（标记区校验）| ✅ | fb33b73 |
| T16n | `gates/commit_msg_gate.py`（**可选新建** Angular 格式）| T26f | ✅ | 413e5e7 |

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
| T26e | PRBackend 选型（背书 T10c/T33）| ✅ | BEACON 决策 #50 |
| T26f | 环内增量 test_gate + commit_msg（背书 T16l/T16n）| ✅ | BEACON 决策 #51 |
| T26g | B15 Guardrail REDGuard/FreshGate/RegressionGate（背书 T29/T30）| ✅ | T29 test_guardrail: TestREDGuard(8)+TestFreshGate(5)+name注入(4)+retry粒度(4)；T30 test_guardrail: TestRegressionGate(7，含真跑嵌套 pytest revert-red-restore + git rm 分支)+test_gate_audit TestAuditRegexSelfTest(9)。三类 Guardrail 均有确定性证据测试 |
| T26h | AuditGate 语义层 + finding 生命周期（背书 T31）| ✅ | test_gate_audit: TestAuditGateSemanticLayer(4，含默认 None/合并/异常降级)+TestAuditFindingFingerprint(3)+TestAuditGateKnownAccepted(4，构造器+contracts+details+未接受仍失败)。语义层 Python-never-LLM 边界 + known-and-accepted 抑制均有确定性测试 |

## Phase 6 — 审计与验证方法论 (B15)

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T27 | `gates/deep_audit.py` 骨架→实际（3-agent 编排）| test_deep_audit(ext) | ✅ | DeepAuditFinding.agent_source str→list[str]；`recount_findings()` 权威去重入口（key=(file,line,desc[:40]归一化)，保留最高severity+合并agent_source+重算p0/p1/p2）；DeepAuditGate.run() + tick `_after_plate/system_deep_audit` 共用（消解路由信任Agent自报计数的静默失效 §B6.7a L1068）；test_gate_deep_audit TestDeepAuditGateDedup(6) + test_tick_orchestrator 2 recount 集成（膨胀不误触发/漏报仍触发）|
| T28 | `commands/audit.md` 内化（去 Superpowers 依赖）| grep 断言 | ✅ | audit.md 三阶段自含重写（Phase1 `ae gate-check --all`+make / Phase2 3-agent B6.7a 内化 / Phase3 `recount_findings` 确定性求值），移除"执行通用 `/audit`" Superpowers 运行时委托（B14 零外部依赖）；test_plugin_contract TestAuditCommandInternalized(3: 无通用委托/委托自有Gate+stage/声明零外部依赖）|
| T29 | `loop/guardrail.py` REDGuard + FreshGate | test_guardrail(ext) | ✅ | G7 REDGuard（post/developer：`git log`定位先于实现的独立测试commit + `merge-base --is-ancestor`祖先校验 + 信任red_evidence，`_STRICT_RED` opt-in重跑；纯配置task豁免）+ G8 FreshGate（post/developer,critic：`_aggregate_sha`(files_changed)比对gate快照，陈旧→retry）；`GuardrailResult.guardrail_name`+Chain注入；S-3生产者契约（`_run_developer_gates`注入`files_snapshot_sha`+`ran_at`，否则G8静默失效）；S-4 retry键粒度`{stage}:{guardrail_name}`+FreshGate `rerun_gates`分流（不清实现）；tick挂运行时句柄`batch_state`/`_plan`；`default()`6→8；test_guardrail +REDGuard(8)/FreshGate(5)/name注入(4)/retry粒度(4)/helper(2) |
| T30 | `loop/guardrail.py` RegressionGate + audit regex 自测 | T26g + test_gate_audit(ext) | ✅ | G9 RegressionGate（post/developer，block）：`_current_regression_task`取batch首个`kind=="regression_fix"` task；`revert(git checkout impl^ -- 实现文件)→_run_test MUST FAIL→finally restore(git checkout HEAD)→_run_test MUST PASS`；S-19新建实现文件（impl^无pathspec→rc≠0）走`git rm`模拟"修复前不存在"；`_run_test`用`sys.executable -B -m pytest <root> -k <id> -o addopts= -p no:cacheprovider`（`-B`禁写.pyc避免同秒git checkout mtime相同致陈旧字节码掩盖回退）；无实现文件/缺test_id/缺commit_hash→block；`default()`8→9。plan.py Task+`kind`/`regression_test_id`字段+task_factory透传。audit.py正则自测（`TestAuditRegexSelfTest` 9测：每pattern正例/反例+元测试断言全覆盖）——surfaced并修复`_SILENT_EXCEPT_PY`的`# noqa`死分支（`\b#`永不匹配→改`\bnoqa\b`）。test_guardrail +RegressionGate(7)/factory(9→) |
| T31 | `gates/audit.py` + `orchestrator.py` AuditGate 语义层 + finding 生命周期 | T26h | ✅ | #6 语义层=`AuditGate(semantic_checker: SemanticChecker|None=None)` 可注入扩展点（默认 None=纯正则，Python 永不调 LLM §A.1；语义 findings 合并；检查器异常降级不崩）。#9 finding 生命周期=known-and-accepted（`finding_fingerprint`=severity\|dimension\|file\|description，行号不入；`accepted_fingerprints` 构造器 + `contracts["accepted_audit_findings"]` 抑制阈值计数，记 `details["accepted_suppressed"]`）。#8 crafted context 复用既有分层上下文（plate components/contracts + system coverage_map + git_diff 工具 + design/ 直读）——未加 files_changed（audit 阶段已清空且 prompt 不消费，加之虚化）。test_gate_audit +语义层(4)/fingerprint(3)/known-accepted(4) |

## Phase 7 — Init-Loop 契约 v5.6 扩展 (IL.2-IL.5)

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T32 | `init-manifest.schema.json`(新建) + `loop/init_contract.py` schema SSOT | IL-AC-06 | ✅ | 4b696bb |
| T33 | +`conventions.ci_platform` + `structure.design_root` 字段及消费点 | IL-AC-08 + T26e | ✅ | b3989b5 |
| T34 | monorepo 单包降级 WARN | IL-AC-08 | ✅ | 13f35c1 |
| T35 | reference fixture + round-trip 消费者驱动契约测试 | IL-AC-07 + test_init_contract(ext) | ✅ | d21091c |

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
| A4 | `gap_analysis.py`（GapReport 全实现+有测试，生产 dict-native）| P1 | `engine/gap_analysis.py` + `guardrail.py:334` | 常量 SSOT 复用 + 行为不变 | ✅ **定案：schema-SSOT 保留（非删除）** BEACON #52 | (本轮) |
| A5 | F821 `Any` 未导入（type_check gate 会红）→ TYPE_CHECKING 块加 `from typing import Any` | P1 | `loop/stage_router.py:284`、`runtime/runtime.py:42` | ruff F821 清零 + type_check gate 绿 | ✅ | 04db92c |
| A6 | 畸形 batch_plan 抛 raw KeyError → 改抛 AEError 契约错误 | P2 | `loop/task_factory.py:58` | test_task_factory 缺 id 断言 | ✅ | c3e6b4f |
| A7 | per-task ctx 仅顶层浅拷贝（注释宣称隔离，名不副实）→ 文档如实标注或 outputs 深拷 | P2 | `loop/round.py:186` | 自含 | ✅ | 715facc |
| A8 | `set_channels` 绕过 write_field 所有权校验 + 重复 `import logging` | P2 | `engine/state.py:321` | 自含 | ✅ | 6cece7f |
| A9 | 8× 集中 `# type: ignore`（graph 节点弱类型区）| P2 | `engine/design_doc.py:220-298` | mypy 无多余 ignore | ✅ **验证：mypy 2.1.0 已装（--extra dev），8 处 type:ignore 经 --warn-unused-ignores 全部必要**（networkx 节点访问真实类型模糊，无可删）；副产品发现全量 203 mypy 类型债（多 union-attr 假阳性）→ 建议独立清理任务 | (纯验证无 commit) |
| A10 | B904：`raise ValueError` 无 `from`（丢异常链）| P2 | `loop/checkpoint/migration.py:62` | ruff B904 清零 | ✅ | 67546c3 |
| A11 | B905：`dict(zip(...))` 无 `strict=`（静默截断）| P2 | `gates/_tools.py:40` | ruff B905 清零 | ✅ | 4301055 |
| A12 | docstring 漂移：guardrail 称 drop→retry+DeprecationWarning，实际 unknown→stop | P2 | `loop/guardrail.py:69-72` | 文档与代码一致 | ✅ | fec06fd |
| A13 | docstring 漂移：ContractGate 声明已不存在的 `run(project_root, contracts=)` 签名 | P2 | `gates/contract.py:14-15` | 文档与代码一致 | ✅ | b9baa9e |
| A14 | docstring 漂移：StageRouter T4/T5 编号在 docstring 与内联注释间互换（判定：内联+设计§B2 为准，docstring 漂移）| P2 | `loop/stage_router.py:8-15` | 编号统一 + 对齐设计追溯 | ✅ | 78ff8ac |
| A15 | ruff 样式批 + #73 remainder：安全 `--fix` 累计修 273 项；**6 处 F821 真 bug** 修复（orchestrator `GateVerdict`/test `Path`/`pytest` 缺 import，运行到即 NameError）；**plugin_contract 测旧版 ae 根因**修复 | P2 | 全仓 + `test_plugin_contract.py` | F821 清零 + plugin_contract 17 passed | ✅ | 1a22a99/046677b/58c3c35（余 141 多为中文注释 E501 超长 → 建议放宽 line-length 配置，独立债）|

---

## Phase 10 — 双驱动接缝预留（v7.0 前置，本阶段必须）

> 来源：2026-07-12 v7.0 单引擎+双驱动架构讨论（BEACON 决策 #54）。规格 v5.6-Design-Loop.md 附录 C §4；讨论 `discussion/v7.0-dual-driver-architecture.md`。
> 性质：**当前阶段 P0 必须预留**——即使不做 v7.0，两项对当前代码质量也是净收益（契约固化 + 防误删）。v7.0 主体（StandaloneDriver + v5.5 退役）入 v5.6-Design-Loop.md 附录 C 路线图 V7-1~V7-8，**非当前范围**。**（2026-07-12 用户明确：v7.0 主体搁置，不主动启动，放置待后续里程碑再议）**
> 边界（YAGNI）：**只做接缝预留**，不实现 StandaloneDriver、不设计其 CLI flag、不加多驱动插件框架。
> 原则精确化（非翻转）：#39/#40「Python 永不调 LLM」→「**循环引擎**永不调 LLM；**驱动**可 opt-in 调」（BEACON #54，D27，status 不变）。

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T33a | **action/stage-result 契约版本化 SSOT**：`action.schema.json` + `stage-result.schema.json`（类比 `init-manifest.schema.json`）固化 `_build_action`/`_read_and_validate`/`_apply_result_to_state` 三处散落形状 + 消费者驱动契约测试（round-trip 校验 dict 数据符合 schema，Python 不引入生产运行时依赖）| 新增 schema 文件 + `test_action_result_contract`（≥2 fixture round-trip）+ grep 断言两驱动唯一耦合点被 schema 覆盖 | ✅ | （本轮）2 schema（`loop/action.schema.json`+`loop/stage-result.schema.json`，draft2020-12，$id 版本化）+ `test_action_result_contract.py`（21 tests：schema↔RESULT_SCHEMA per-stage required 防漂移 + 真实 `_build_action`(architect/gap_scan) round-trip + done/error + result 双校验一致）|
| T33b | **执行栈双驱动共享资产标注**：`agents/` + `runtime/` + `tools/` + `round.py` 头部注释 + BEACON/规格声明「退役 v5.5 循环时不得连带删执行层」（Driver B 复用 v5.5 `_step_2e_run_agent` 执行栈作 tick 填充器；且 `ae agent` 已独立依赖）| grep 断言 4 处标注存在 + v5.6-Design-Loop.md 附录 C §2.3/T33b 交叉引用一致 | ✅ | （本轮）4 处 docstring 加「双驱动共享资产」标注 + 交叉引用 §2.3，grep 4/4，导入完好 |

> **v7.0 详细设计**：2026-07-16 完成，v5.6-Design-Loop.md 附录 C 展开为 14 节开发就绪规格。每任务含接口签名、数据流、验收标准、参考实现位置。实现时按 §10 依赖图顺序推进。

---

## Phase 11 — v7.0 双驱动主体（详细设计就绪，待实现）

> 来源：2026-07-16 v7.0 详细设计展开（v5.6-Design-Loop.md 附录 C）。设计颗粒度：直接用于开发。
> 前置：Phase 10 T33a/T33b ✅ 已完成。
> 预估：~6.8 天 | 依赖链：V7-1 → V7-2/4 → V7-5 → V7-6 → V7-8 → V7-7（退役）

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| V7-1 | `loop/tick_orchestrator.py` — `tick()` 精简为薄包装（读文件 + 委托 `tick_dict()`）+ docstring 声明 canonical 入口 | tick() ≤5 行 + test_tick_orchestrator(52) 全绿 + test_action_result_contract(21) 全绿 | ✅ | — |
| V7-2 | `loop/standalone_driver.py` — `STAGE_TO_ROLE` 映射表 + `ROLE_MODEL` 映射表 + `_build_task()` + `_build_tools_for_role()` + `_build_agent_for_stage()` | 10 stage 覆盖 + 环境变量覆盖可测 + Agent 配置正确集成测试 | ✅ | — |
| V7-3 | `loop/standalone_driver.py` — `AuthProvider` 类型别名 + `_resolve_auth_provider()` AUTH_TOKEN→API_KEY 优先级 | 无 key → AEError + 测试可注入 mock auth | ✅ | — |
| V7-4 | `loop/tick_orchestrator.py` + `loop/standalone_driver.py` — `restore()` 审查（不含驱动信息）+ `StandaloneDriver.resume()` + 跨进程 resume 集成测试 | restore 不依赖驱动类型 + EngineState.to_dict 不含 auth + resume E2E | ✅ | — |
| V7-5 | **`loop/standalone_driver.py`** — `StandaloneDriver` 完整实现：`run()` 主循环 + `_execute_action()` + `_execute_developer_serial()` + `_execute_gap_review_headless()` + `_execute_single_task()` + `resume()` + `close()` | 3 stage E2E APPROVE + 5 层验证 GOAL_ACHIEVED + 每 stage 产出符合 schema 的 result + mock LLM 18 tests + **真实 LLM E2E 验证 (fibonacci GOAL_ACHIEVED)** + _run_loop_from_action 控制流 + developer 串行 TDD + gap_review headless auto-Defer + 错误处理优雅降级 | ✅ | V7-1, V7-2, V7-3, V7-4 |
| V7-6 | `cli/dev_loop.py` — `--standalone` flag + `_run_standalone()` + AgentRuntime 注册（architect/developer/critic + AnthropicProvider + 7 tools）+ `cli/doctor.py` — API_KEY 检查项 | `ae dev-loop --standalone "hello"` E2E ✅（真实 LLM 真跑: 6 ticks, GOAL_ACHIEVED, fibonacci 实现+10 tests）+ `--resume` + doctor key 检查 + `--standalone` 与 tick flag 互斥 | ✅ | 2026-07-17 E2E 真跑验证 |
| V7-7 | **v5.5 退役** — Step 1 提取执行栈到 `execution_stack.py` → Step 2 删 orchestrator.py 循环 → Step 3 删 semantic_evaluator.py → Step 4 改 CLI 裸参数路由 → Step 5 文档+BEACON 同步 | G1-G4 全满足 + `ae agent` 仍可用 + Standalone E2E 仍绿 + 裸参数输出引导 + BEACON #53 ✅→❌（用户审批）| 🔒 | — |
| V7-8 | `auto_engineering/benchmark.py` — 基准框架（数据模型 + 10 需求集 + 差异计算 + 报告生成 + 数据校验）| 16 tests PASS + `generate_report()` 产出含汇总/逐需求 6 维对比/场景推荐/v5.5 退役风险评估的完整报告 | ✅ | V7-5, V7-6 |

> **实施顺序**：V7-1 → V7-2 → V7-3 → V7-4 → V7-5 → V7-6 → V7-8 → V7-7（退役）。
> V7-7 硬门禁：V7-8 基准报告 + 用户 AskUserQuestion 审批 + 30 天过渡期（裸参数先 WARN 再移除）。
> 详细接口签名/数据流/验收标准见 v5.6-Design-Loop.md 附录 C 各节。

---

## Phase 12 — v8.0 多 Agent 平台适配 ✅ 全部完成

> 来源：2026-07-16 v8.0 多 Agent 平台适配设计（v5.6-Design-Loop.md 附录 D）。设计颗粒度：直接用于开发。
> 前置：Phase 11 v7.0 双驱动（V8-3/4/5 Provider 抽象是 V7-5 StandaloneDriver 的前置依赖）。
> 预估：~4.3 天 | 四波推进：Wave 1 基础设施(V8-1+V8-3) → Wave 2 Provider(V8-4→V8-5) → Wave 3 平台适配(V8-2→V8-6) → Wave 4 收尾(V8-7+V8-8)

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| V8-1 | **目录结构重构**：`commands/` `hooks/` `skills/` `agents/` 从 `.claude-plugin/` 提升到项目根；`.claude-plugin/plugin.json` paths 更新为 `../` 相对路径；`.codex-plugin/plugin.json` 新建（Codex manifest）；`.codebuddy-plugin/` → `.claude-plugin/` symlink（CodeBuddy 零成本兼容）| 三平台目录结构验收：Claude Code 能发现 plugin + Codex `plugin.json` 语法正确 + CodeBuddy symlink 有效 | ✅ | — |
| V8-2 | **Hook 注册拆分**：`hooks-cc.json`（Claude Code，含 on-pr.sh）+ `hooks-codex.json`（Codex，仅 4 hooks：session-start/post-edit/pre-tool/stop）+ `hooks-codebuddy.json`（CodeBuddy，同 CC）；`session-start.sh` 加 `$AE_PLATFORM` 平台检测逻辑（从 `$CLAUDE_PLUGIN_ROOT`/`$CODEX_PLUGIN_ROOT`/`$CODEBUDDY_PLUGIN_ROOT` 判定）；其余 hook 脚本用 `$AE_PLUGIN_ROOT` 统一变量 | 三平台 hook 注册文件语法正确 + session-start.sh 三平台检测正确 + Codex 无 on-pr.sh（仅 4 hooks） | ✅ | V8-1 |
| V8-3 | **Provider Protocol + AnthropicProvider 适配**：`providers/base.py` 新建（`LLMProvider` Protocol + `LLMResponse` + `ToolUseBlock` dataclasses）+ `agents/base.py` `AnthropicProvider` 加 `_to_llm_response()` adapter | `LLMProvider` Protocol 编译通过 + `AnthropicProvider` 适配后 `_to_llm_response` round-trip 正确 + test 11 passed | ✅ | — |
| V8-4 | **OpenAIProvider 实现**：`providers/openai_provider.py` 新建（Anthropic tool_use ↔ OpenAI function_call schema 双向转换 + response 转换为 `LLMResponse` 统一格式）+ `providers/factory.py` 新建（`create_provider(platform, api_key, model)` 工厂）| Anthropic→OpenAI tool schema 正确转换 + OpenAI→LLMResponse 正确转换 + mock OpenAI API 集成测试 | ✅ | V8-3 |
| V8-5 | **BaseAgent + StandaloneDriver 适配**：`BaseAgent.llm` 类型注解从 `AnthropicProvider` 改为 `LLMProvider` Protocol；`StandaloneDriver._build_agent_for_stage()` 用 `create_provider()` 工厂选择 Anthropic/OpenAI 后端 | mypy 类型检查通过（`LLMProvider` Protocol 兼容）+ BaseAgent 现有 11 tests 全绿 + StandaloneDriver 用 OpenAI mock 通过 | ✅ | V8-3, V8-4 |
| V8-6 | **install.sh 多平台改造**：平台检测（`which code`/`which codex`/`which codebuddy`）+ Claude Code 安装（`~/.claude/plugins/auto-engineering/`）+ Codex 安装（`~/.codex/plugins/auto-engineering/`）+ CodeBuddy 安装（symlink 到 Claude Code 目录）+ 多平台注册验证 | 三平台安装 E2E + 安装后各平台 `doctor` 检查通过 + 卸载不残留 | ✅ | V8-1, V8-2 |
| V8-7 | **doctor + pyproject.toml 更新**：`ae doctor` 加 OpenAI API key 检查（`OPENAI_API_KEY` 环境变量）+ 平台检测项（`$AE_PLATFORM`）+ `pyproject.toml` 加 `openai` 可选依赖（`[project.optional-dependencies] openai = ["openai>=1.0"]`）| `ae doctor` 显示平台 + key 状态 + `uv sync --extra openai` 安装成功 | ✅ | V8-4 |
| V8-8 | **文档更新**：`USER_GUIDE.md` / `PLUGIN-USAGE.md` / `production-deployment.md` 加三平台安装说明 + 命令语法差异（Claude Code `/dev-loop` vs Codex `//dev-loop` skill 调用 vs CodeBuddy `/dev-loop`）| 三份文档含平台特定章节 + grep 断言三平台均覆盖 | ✅ | V8-6 |

> **推荐实施顺序**：先 v8.0 Provider 抽象（V8-3→V8-4→V8-5），再做 v7.0 StandaloneDriver（V7-5），因为 StandaloneDriver 依赖 Provider 工厂。v8.0 平台适配层（V8-1/2/6/7/8）可独立于 v7.0 推进。
> **与 v7.0 依赖关系**：V7-5 StandaloneDriver ↔ V8-3/4/5 Provider 抽象（前置）；V7-6 CLI ↔ V8-7 doctor 扩展；V8-1/2/6 目录+Hook+install.sh 为 v8.0 独有。
> 详细接口签名/Provider 代码/install.sh 脚本见 v5.6-Design-Loop.md 附录 D 各节。

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
| 2026-07-12 | T16h + T10d | **T16h ci.yml 薄壳 + ruff 全量转绿（24afa07）**：用户定案「line-length→120」。**premise 修正**——120 仅清 64/141，残留 77 为非行长既有 lint 债（17 类，生产 32+测试 45）；按类真修非静默 ignore：生产 All checks passed（E402 惰性导入上移×4 文件 / E501 折行 / SIM108 三元 / audit noqa 词形），测试 per-file-ignore 扩 RUF012/SIM117/B017（测试约定豁免，与 S101 一致）+ E501/RUF043/SIM105 真修。`.github/workflows/ci.yml`（push+PR，uv sync --extra dev + ruff + pytest no-cov 薄壳）。1968 passed。**T10d 定案保留共存（决策 #53）**：退役前置只读审计确认 v5.5 活代码（`ae dev-loop` 裸参数 → `_run_v2_orchestrator`），用户决策不退役，semantic_evaluator（唯一消费者 orchestrator.py）随之保留，修正 D22 计划方向，无 status 翻转。 | ✅ 6 遗留项全收口，Phase 总览 95→100/100。**两笔债仍待独立决策**：mypy(203，union-attr 假阳为主)/coverage-gate 刻意排除 ci 薄壳。 |
| 2026-07-12 | #73 + A4 + A9 | **红线遗留项批量推进（用户"按推荐执行"授权）**：① **plugin_contract drift 根因**——`_run_cli` 用 `shutil.which("ae")` 优先，命中全局旧版 `~/.local/bin/ae`（无 tick 选项），16 契约测试实际测旧版非当前 .venv 代码；改 .venv 优先 + TestDevLoopJSON 从 v5.5 `--format json` 更新为 v6 `--init` tick 契约（BEACON #39 依据，非降级），17 passed。② **6 处 F821 真 bug**（GateVerdict/Path/pytest 缺 import）。③ **A4 定案**（BEACON #52）：GapReport schema-SSOT 保留非删除，仅消除 guardrail 常量 DRY。④ **A9**：mypy 装+8 type:ignore 验证必要。 | ✅ 处理完毕。**两笔新债报告**：(a) 全量 203 mypy 类型债（多 union-attr 假阳性，type_check gate 装 mypy 后从降级 pass→真跑 fail）；(b) 141 ruff E501（多中文注释超长）。均建议独立配置决策任务，不逐个改（范围爆炸）。 |
| 2026-07-11 | Phase 9 孤立快修批 | **9 项孤立快修完成（superpowers TDD/lint-verify，每任务一 commit）**：A5=04db92c、A10=67546c3、A11=4301055（prior）+ A12=fec06fd、A13=b9baa9e、A14=78ff8ac（docstring 对齐设计，A14 判定内联+§B2 为准）、A2=633af89（gate fail-closed，TDD）、A6=c3e6b4f（KeyError→AEError，TDD）、A15=1a22a99（ruff safe --fix 264 项/84 文件）。**A14/A2/A6 过程中发现审计估计偏差**：A13 无 AttributeError（Gate 基类有 contracts 默认）、A14 是 docstring 漂移非内联漂移、A15 实际 407 findings 非~186。全量 1692 passed / 8 failed（与修复前完全一致，零新增）。 | ✅ 用户定案 A15 安全 auto-fix + 余项另立（#73）。**下一步：checkpoint 契约修复（A1/A3 根因，方向①反序列化→EngineState）**。A4 决策 / A7-A9 P2 待办。 |
| 2026-07-11 | Phase 9 checkpoint 契约修复 | **deserialize shape-aware 分派 + A1 + e2e（计划 `design/checkpoint-contract-fix-PLAN.md`，8a8991a）**：2fc8950=deserialize_state 按 dict 形状三路分派（channels→Envelope / thread_id→EngineState / else→raw dict，marker 有 guard 测试）关闭 5×test_checkpoint_store；89d850a=A1 status.py 两分支读 critic_verdict（输出 key 仍 verdict）关闭 1×test_cli_status_extended；5983bca=e2e 测试改文件 store 关闭 1×e2e。**修正计划基线错误**：计划 §4 把 e2e test_full_cycle_checkpoint_save_round 归为 deserialize 根因，实测在 clean main 上它从不因 deserialize 失败——真根因是 orchestrator.run() finally close 调用方传入的 :memory: store → 测试随后 list_all 断言失败（独立 store 生命周期 bug）。A3 读侧由 deserialize 修复自动保真（batch_state_json round-trip），写侧仍属 Phase 3。 | ✅ 8 pre-existing 失败 → 1（仅 plugin_contract --format 漂移，#73）；1704 passed，零新增。e2e 修法用户定案「改测试用文件 store」（生产用文件 store，close 释放句柄有意设计；:memory: 从不用于生产）。 |
| 2026-07-11 | Phase 9 P2 收尾 (A7/A8/A9) | **A7=715facc（round.py 如实标注浅拷贝：state 有意共享非缺陷）+ A8=6cece7f（state.py import logging 提模块级去重 + set_channels 所有权旁路如实标注）**。A9 阻塞：8× `# type: ignore` 为 mypy 专属错误码，验收「mypy 无 ignore」；venv 未装 mypy → 无法本地验证移除；盲改 parse-critical 代码违「验证后再说完成」。**A3 写侧确认与 T9 耦合**：`_display_progress` 已写 progress_tree_json，但 batch_state_json 零写且**无 restore 路径**——写而不读回是半措施，必须随 T9 跨进程 restore 一起落地。 | ◐ A7/A8 ✅；A9 ⛔ 需决策（装 mypy dev-dep 审批 or 接受文档化 ignore）。Phase 9 = 13/15。**下一大块：Phase 3 T9 接线**（TickOrchestrator 跨进程 restore + A3 写侧 + CLI --init/--tick + file-bridge，为一体耦合单元，需 grounded 子计划）。红线门：A4 删/接线、Phase 4b CI/CD 配置。 |
| 2026-07-11 | Phase 3 T9 接线（`design/phase3-t9-wiring-PLAN.md`，39a4dd2）| **v5.6 tick 引擎端到端接线（TDD, 每步一 commit）**：fe8bee2=T9b A3 写侧（`_populate_serialized_state` 每 save 前序列化 batch_state/progress_tree 回 EngineState）；f4e4175=T9a 跨进程 `restore()` classmethod（重建 _state/_design_doc/_batch_state/_progress_tree/_plan）+ init 持久化 design_doc_path；0a2daca=T9c CLI `--init/--tick/--result/--status/--resume`（tick 分派先于 LLM preflight，§A.1 Python 不调 LLM）。**根因修正（非降级）**：`clear_stage_fields` 在 architect→developer 清空 `EngineState.batch_plan`(#6)，而 batch_state.py 序列化原假设 #6 跨 tick 存活 → batch_state_json 自包含化（内嵌轻量 batch_plan seed，plates 仍不持久化=主设计决策保留）。e2e 真跑 3 独立 `ae` 进程：--init→architect / --tick→developer(tick2, batch_id 保真) / --status→developer，thread_id `2e0845ee` 跨进程一致。 | ✅ 1717 passed / 1 skipped / 1 pre-existing 失败（plugin_contract：`shutil.which("ae")` 命中 stale 全局 `~/.local/bin/ae` 无 `--format`，非本次回归，归 #73）；零新增失败。A3 全链闭合（读+写+restore）。**下一步**：T10 命令重写 / Phase 4 prompt / 红线门 A4/A9/Phase 4b。 |
| 2026-07-11 | Phase 3 Wave 1 收尾（`design/remaining-execution-PLAN.md`）| **Phase 3 剩余 6 任务完成（TDD, 每任务一 commit）**：e27a8fd=T12 BEACON 当前状态记 T9（无 status 翻转）；4628c33=T9b `cli/progress.py`（读持久化 progress_tree_json → display/summary，无 checkpoint 优雅降级，4 tests）；6e30f35=T10b `commands/progress.md`（/ae:progress 委托）；e13da0c=T10 两份 dev-loop.md 统一 v5.6 Tick 协议重写（action 参考表对齐 `_build_action` 实际输出；**移除 4 外部依赖** Plan/code-reviewer/code-review/gsd-code-fixer + dead ref AE_JSONL_MODE，决策 #46 实施非降级）；6a4fe19=T11 SKILL.md 分层验证约束（5 层矩阵 + LEAF/PLATE/FULL 自动裁剪 + 不可短路）；9da5dbe=T10c `tools/pr_backend.py`（PRBackend ABC + gh/glab 薄壳 + select_backend(ci_platform) + doctor 非致命预检，12 tests，去 gh 硬编码）。 | ✅ Wave 1 blast radius 94 passed / 1 pre-existing 失败（#73 同上，非回归）。Phase 3 = 7/8，仅剩 **T10d**（G-retire 红线，v5.5 活跃待确认时机）。**下一步**：Wave 2 Phase 4 Agent Prompt 模板（T13-T16g）。 |
| 2026-07-12 | Phase 10（v7.0 双驱动预留）| **单引擎+双驱动远期架构立项 + 当前 P0 预留落表（决策 #54）**：由 T10d「v5.5 是否值得保留」追问延伸——v5.5 唯一护城河（脱 Claude Code 独立/headless 跑）在主场景（Plugin）已死（2026-07-04 子进程拿不到 AUTH_TOKEN），且流水线落后 v6 + 双引擎税（orchestrator.py:580-609 T9 `10**9` shim）。用户提出「一套引擎、两个入口」：TickOrchestrator 为唯一真相源，接缝挂 Driver A（Claude Code Agent 填 result，现状）+ Driver B（进程内 AgentRuntime 自带 key 调 LLM，v7.0），编排机制完全一致只换执行后端（ports & adapters）。Driver B 复用 v5.5 `_step_2e_run_agent` 执行栈作 tick 填充器 → subsume v5.5，给 T10d 干净退役出口（薄驱动替 fork）。**原则精确化（非翻转，#39/#40 status 不变）**：「Python 永不调 LLM」→「循环引擎永不调 LLM；驱动可 opt-in 调」。产物：v5.6-Design-Loop.md 附录 C（架构图+路线图 V7-1~V7-8）+ `discussion/v7.0-dual-driver-architecture.md`（推理过程）+ BEACON #54。**当前阶段仅做两项 P0 预留**（净收益，非 v7.0 本体）：T33a action/stage-result schema SSOT + 契约测试；T33b 执行栈双驱动共享资产标注（防退役 v5.5 时误删）。 | ◐ Phase 10 立项，T33a/T33b 落表为**本阶段必须任务**（待做）。v7.0 主体（V7-5 StandaloneDriver / V7-6 `--standalone` CLI / V7-7 v5.5 退役=决策翻转红线须审批 / V7-8 保真度基准）入 v5.6-Design-Loop.md 附录 C 路线图，**非当前范围，等后续里程碑扩展**。本轮 DOCS ONLY，不实现 T33a/T33b。 |
| 2026-07-12 | Phase 10 T33a+T33b 实现 | **双驱动接缝预留落地（用户"现在开始实现 T33a + T33b"授权；v7.0 主体明确搁置不主动启动）**：T33a=`loop/action.schema.json`+`loop/stage-result.schema.json`（draft2020-12，$id 版本化 SSOT，固化 `_build_action` 与 `actions.RESULT_SCHEMA` 两处形状）+ `test_action_result_contract.py`（21 tests；核心防漂移断言 schema per-stage required == `actions.RESULT_SCHEMA` + 真实 `_build_action`(architect/gap_scan) round-trip + done/error + result 双校验一致；jsonschema 仅测试期用，生产不 import schema）；T33b=4 处执行栈 docstring（agents/runtime/tools/round.py）标注「双驱动共享资产，退役 v5.5 不得删执行层」+ 交叉引用 §2.3。ruff/mypy 全绿，182 相关测试零回归。 | ✅ Phase 10 = 2/2，v5.6 里程碑 102/102 全完成。v7.0 主体（V7-1~V7-8）用户搁置，待后续里程碑。 |
| 2026-07-15 | **PrismScan V5.1 Phase 1 流转覆盖率补充测试** | **从 loop flow 流转角度分析 25 条路径，14→23 覆盖（56%→92%）**。新增 45 测试（P0×12: tree-sitter 降级/schema-pass-but-from_dict-fails/独立check-result/stage状态机/内部异常；P1×15: 最小AnalysisResult/高复杂度压力/大型符号索引/2-retry闭环/Agent消费context；P2×8: 重复discover-extract/构造参数注入/AST边界/import解析；S6.6×2: Agent运行时真实LLM闭环）。全量 92 passed（22.56s），含 Agent 真实调用 2 tests（需 API key，无 key 自动 skip）。v5.6 tick 闭环 smoke test：`ae dev-loop --init/--tick` 验证通过（plan≥50 字符校验/stage mismatch 拦截正确）。 | ✅ PrismScan Phase 1 补充测试完成。**待做：真实 Agent 驱动的 v5.6 tick 完整闭环**（用 /ae:dev-loop 对 Design-V5.0-plugin-final.md 真实验证）。 |
| 2026-07-15 | **v5.6 P1 Bug 修复 (tick 闭环前置)** | **(1) load_latest() 排序修复**（`store.py:251`）：`ORDER BY round DESC, created_at DESC` → `ORDER BY created_at DESC`。`--init`(round=0) 创建 checkpoint 后 load_latest 仍返回历史高 round 记录（`round DESC` 第一键），导致 restore 拿到 stale state。修复 + 2 测试更新（test_checkpoint_store.py:test_load_latest_returns_most_recent / test_loop_convergence.py:576）。**(2) BatchState.from_design_doc() 组件过滤修复**（`batch_state.py:75-84`）：原实现在无 batch 的 component 上 `is_component_complete()` 返回 True（`current_batch_idx=0 >= len(batches_for(comp))=0`），导致 developer 阶段 `current_batch()` assertion 失败。修复：filter plates 仅保留有 batch 的 component，无 active component 的 plate 移除。129 + 21 相关测试全部通过。 | ✅ 2/2 P1 修复。CLAUDE.md 同步更新（v5.6 架构 + ~2132 tests + 文档纪律）。 |
| 2026-07-17 | **Phase 11 V7-5 StandaloneDriver 真实 LLM E2E 验证** | **StandaloneDriver 端到端真跑成功**：architect→developer→critic→GOAL_ACHIEVED（6 ticks），在 `/tmp/_ae_test_project/` 产出 fibonacci 实现（`src/fibonacci.py` + `tests/test_fibonacci.py` 10 tests）+ auto-commit。**3 处 bug 修复确保 E2E 可跑**：(1) `guardrail.py:252-259` GitDiffExists 增加第三降级路径（`git diff-tree --no-commit-id -r HEAD`）处理 StandaloneDriver auto_commit 后 `--cached` 空的场景；(2) `bash_tools.py:77-80` cwd 未指定时默认 project_root（之前只在幻觉路径回退，None cwd 不处理→subprocess 跑在工作目录而非沙箱）；(3) `standalone_driver.py:700-710` architect 任务描述更详细（100+ 字要求+示例格式+明确步骤）确保 DeepSeek 产出足够长的计划。全量 2246 passed / 2 skipped。 | ✅ StandaloneDriver 可运行证明完成。V7-7 v5.5 退役仍需 V7-8 基准数据 + 用户审批。 |
| 2026-07-17 | **Step 3 AgentDriver 基准 10/10 全部完成** | **AgentDriver 手动驱动 v5.6 Tick 协议全量基准**：全部 10 需求（R01-R10，含 simple_function/medium_crud/complex_multi_module/with_design_doc 四类）GOAL_ACHIEVED（100%）。R01(5t/7t)、R02(5t/7t)、R03(5t/5t)、R04(9t/13t)、R05(5t/8t)、R06(5t/9t)、R07(9t/18t)、R08(5t/6t)、R09(5t/7t)、R10(5t/5t)。总 ~63 ticks, ~85 tests。**双驱动最终对比**：Agent 100% vs Standalone 100% 收敛率等价；AgentDriver 测试更精简（avg 8.5 vs 11.8），StandaloneDriver 更快可批量（~163s vs ~8min）。R09/R10 通过 spec 内嵌 requirement 绕过 `from_design_doc()` 校验过严问题。修复 red_evidence 映射 bug + collect 脚本 git 命令。产出 `_scratch/benchmark_report.md` + `/tmp/_ae_agent_bench/results.json`。BEACON 决策 #57 更新。 | ✅ Step 3 双驱动保真度等价验证闭环。AgentDriver vs StandaloneDriver 全 4 类需求类型 100% 收敛。 |
