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

### T113 L1: 接线验证步骤（标记 ✅ 前必须满足）

任何新增/修改模块的 T-task 标记 ✅ 前，必须通过以下三项验证：

1. **调用链存在**：模块的公开入口点（类/函数）被至少一个生产调用链引用。用 `grep` 验证 `dev_loop.py` 或 `tick_orchestrator.py` 中存在 import/调用。
2. **commit message 记录调用链**：格式 `wired: dev_loop.py::_build_injectables() → TickOrchestrator.__init__ → ModuleName`
3. **条件激活模块**（依赖环境变量）的验收标准必须包含"默认未激活时的行为说明"（如 `returns None gracefully without AE_OTLP_ENDPOINT`）

**反例**（Phase 18-22 事故）：跟踪表标记 ✅，但 CLI 入口从未实例化模块传入 TickOrchestrator → 静默 No-op。

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
| **11** | **v7.0 双驱动主体（V7-1~V7-8，全部完成 ✅）** | **8** | **8** | **2026-07-19: V7-7 v5.5 退役 30 天过渡期启动。Phase 11 全部完成。** |
| **12** | **v8.0 多 Agent 平台适配（V8-1/2/3/4/5/6/7/8 全部 ✅）** | **8** | **8** | **2026-07-17: 全部完成。多平台基础架构就绪。** |
| **13** | **真跑故障修复 (voice_clone 2026-07-17)** | **9** | **9** | **✅ 完成 — P0 B3 crash + P1 7/7 + P2 1/1 (T41 作废，非本项目范围) + T43 集成 5 tests** |
| **14** | **gate_results 结构错配修复 (忠实度分析)** | **1** | **1** | **T44 修复 production 路径 gate 结果全部丢失 ✅** |
| **15** | **DebugTracer — dev-loop 调度轨迹诊断** | **1** | **1** | **T45 DebugTracer 实现 + TickOrchestrator 集成 + CLI 接线 ✅** |

| **17** | **设计治理修复（vNext Phase 17）** | **12** | **12** | ✅ 完成 — 6 角色 subagent 隔离恢复 + Governance 规则扩展（T49-T52d, a6b0d33）|
| **18** | **Context & 安全加固（vNext Phase 18）** | **5** | **5** | ✅ 完成 — Context offloading + summarization + Ollama + PII redaction/scan（T53-T57, 92d3a47）|
| **19** | **模型扩展 & 可观测性（vNext Phase 19）** | **8** | **8** | ✅ 完成 — 国产模型 (T58) + StandaloneDriver 多 provider (T59) + OTLP tracing (T60) + audit log (T61) + FileAccessGuardrail + glob (T62/T62a) + prompt caching (T63) + Stage Checkpoint Gate (T64) |
| **20** | **AI Coding 度量与自进化体系** | **7** | **7** | **✅ 完成 — T65-T69c 全部落地（1424 行，6 模块），AE_METRICS=1 激活** |
| **21** | **自进化深化（阈值学习 + 规则发现）** | **3** | **3** | **✅ 完成 — T70-T72 全部落地，32 tests（16+10+6）** |
| **22** | **Phase 18-19 虚化模块集成接线（审计发现）** | **6** | **6** | **6/6 完成 — T73+T74+T75+T76+T77+T78 全部接线** |
| **23** | **Phase 20 P0 数据流修复（审计发现）** | **3** | **3** | **3/3 完成 — T79 信号管线 + T80 M2 criteria_met + T81 M5 git diff** |
| **24** | **Phase 20 P1/P2 修复（审计发现）** | **9** | **9** | **9/9 完成 — T82-T90 全部完成，19 tests** |
| **25** | **战略储备激活（按依赖顺序执行）** | **7** | **7** | **✅ 完成 — T91-T97 全部落地，16 tests** |
| **26** | **设计-实现对齐 + 遗留清理** | **4** | **4** | **✅ 完成 — T98-T101 全部落地，2573 tests 零回归** |
| **27** | **真跑验证发现（2026-07-19）** | **3** | **3** | **✅ 完成 — T102-T104 全部修复** |
| **28** | **七方对比报告 × 真跑交叉对标（2026-07-19）** | **3** | **3** | **✅ 3/3 — T105 ✅(6/6子项) / T106 ✅(4/4) / T107 ✅(4/4)** |
| **29** | **Phase 17-21 真跑验证差距修复（2026-07-20）** | **22** | **22** | **✅ 22/22 — T108-T116 全部完成（T109h PII 文档 ⚠️ 部分完成）。2622 tests 零回归。BEACON #78-#85 落实** |
| **30** | **深度审计发现修复（2026-07-21）** | **20** | **20** | **✅ 20/20 — P0-1 在 Phase 31 完成（ActionBuilder 提取），P0-5/P0-6 同日完成。第二轮审计 28 项已全部修复。BEACON 决策 #86。** |
| **31** | **Subagent Spawn 强制执行 — 提示词注入 + 重构（2026-07-22）** | **9** | **9** | **✅ 9/9 — BEACON 决策 #91。** |
| **32** | **5 层验证提示词增强 + subagent_type 移除 + Gate 多语言适配（2026-07-23）** | **22** | **22** | **✅ 22/22 — BEACON 决策 #92。** |
| **33** | **全量深度审计（2026-07-23）** | **50** | **50** | **✅ 40 修复 + 10 废弃 — BEACON 决策 #93** |
| **33a** | **用户决策执行（2026-07-23）** | **4** | **4** | **✅ AD1-4 按推荐方案执行** |
| **33b** | **P2 低优先级深度修复（2026-07-23）** | **9** | **9** | **✅ JSON 工具+死代码+Protocol+文档+CHANGELOG** |
| **34** | **真跑问题全部修复（2026-07-23）** | **6** | **6** | **✅ BEACON 决策 #94。** |
| **35** | **T51c-f 根因修复 + prompt 日志增强（2026-07-23）** | **4** | **4** | **✅ Fix A(design_items补全)+B(impl_files注入)+C(auto-skip)+prompt日志增强 — BEACON 决策 #95。** |
| **36** | **深度审计 P0 全部修复（2026-07-23）** | **10** | **10** | **✅ P0-1~P0-10 全部修复 + 死测试清理 (v5.5 SemanticEvaluator ×4 + G11 PII ×7) — BEACON 决策 #96。commit: 55df599。** |
| **合计** | | **314** | **314** | **Phase 1-36 314/314 完成 ✅** |

> **v5.5 退役提醒**：`orchestrator.py` + `semantic_evaluator.py` 已物理删除。CLI 裸参数路径重定向到 `--standalone`。2026-08-18 清理 CLI 弃用 shim。

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
| T26g | B15 Guardrail REDGuardrail/FreshGuardrail/RegressionGuardrail（背书 T29/T30）| ✅ | T29 test_guardrail: TestREDGuardrail(8)+TestFreshGuardrail(5)+name注入(4)+retry粒度(4)；T30 test_guardrail: TestRegressionGuardrail(7，含真跑嵌套 pytest revert-red-restore + git rm 分支)+test_gate_audit TestAuditRegexSelfTest(9)。三类 Guardrail 均有确定性证据测试 |
| T26h | AuditGate 语义层 + finding 生命周期（背书 T31）| ✅ | test_gate_audit: TestAuditGateSemanticLayer(4，含默认 None/合并/异常降级)+TestAuditFindingFingerprint(3)+TestAuditGateKnownAccepted(4，构造器+contracts+details+未接受仍失败)。语义层 Python-never-LLM 边界 + known-and-accepted 抑制均有确定性测试 |

## Phase 6 — 审计与验证方法论 (B15)

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T27 | `gates/deep_audit.py` 骨架→实际（3-agent 编排）| test_deep_audit(ext) | ✅ | DeepAuditFinding.agent_source str→list[str]；`recount_findings()` 权威去重入口（key=(file,line,desc[:40]归一化)，保留最高severity+合并agent_source+重算p0/p1/p2）；DeepAuditGate.run() + tick `_after_plate/system_deep_audit` 共用（消解路由信任Agent自报计数的静默失效 §B6.7a L1068）；test_gate_deep_audit TestDeepAuditGateDedup(6) + test_tick_orchestrator 2 recount 集成（膨胀不误触发/漏报仍触发）|
| T28 | `commands/audit.md` 内化（去 Superpowers 依赖）| grep 断言 | ✅ | audit.md 三阶段自含重写（Phase1 `ae gate-check --all`+make / Phase2 3-agent B6.7a 内化 / Phase3 `recount_findings` 确定性求值），移除"执行通用 `/audit`" Superpowers 运行时委托（B14 零外部依赖）；test_plugin_contract TestAuditCommandInternalized(3: 无通用委托/委托自有Gate+stage/声明零外部依赖）|
| T29 | `loop/guardrail.py` REDGuardrail + FreshGuardrail | test_guardrail(ext) | ✅ | G7 REDGuardrail（post/developer：`git log`定位先于实现的独立测试commit + `merge-base --is-ancestor`祖先校验 + 信任red_evidence，`_STRICT_RED` opt-in重跑；纯配置task豁免）+ G8 FreshGuardrail（post/developer,critic：`_aggregate_sha`(files_changed)比对gate快照，陈旧→retry）；`GuardrailResult.guardrail_name`+Chain注入；S-3生产者契约（`_run_developer_gates`注入`files_snapshot_sha`+`ran_at`，否则G8静默失效）；S-4 retry键粒度`{stage}:{guardrail_name}`+FreshGuardrail `rerun_gates`分流（不清实现）；tick挂运行时句柄`batch_state`/`_plan`；`default()`6→8；test_guardrail +REDGuardrail(8)/FreshGuardrail(5)/name注入(4)/retry粒度(4)/helper(2) |
| T30 | `loop/guardrail.py` RegressionGuardrail + audit regex 自测 | T26g + test_gate_audit(ext) | ✅ | G9 RegressionGuardrail（post/developer，block）：`_current_regression_task`取batch首个`kind=="regression_fix"` task；`revert(git checkout impl^ -- 实现文件)→_run_test MUST FAIL→finally restore(git checkout HEAD)→_run_test MUST PASS`；S-19新建实现文件（impl^无pathspec→rc≠0）走`git rm`模拟"修复前不存在"；`_run_test`用`sys.executable -B -m pytest <root> -k <id> -o addopts= -p no:cacheprovider`（`-B`禁写.pyc避免同秒git checkout mtime相同致陈旧字节码掩盖回退）；无实现文件/缺test_id/缺commit_hash→block；`default()`8→9。plan.py Task+`kind`/`regression_test_id`字段+task_factory透传。audit.py正则自测（`TestAuditRegexSelfTest` 9测：每pattern正例/反例+元测试断言全覆盖）——surfaced并修复`_SILENT_EXCEPT_PY`的`# noqa`死分支（`\b#`永不匹配→改`\bnoqa\b`）。test_guardrail +RegressionGuardrail(7)/factory(9→) |
| T31 | `gates/audit.py` + `orchestrator.py` AuditGate 语义层 + finding 生命周期 | T26h | ✅ | #6 语义层=`AuditGate(semantic_checker: SemanticChecker|None=None)` 可注入扩展点（默认 None=纯正则，Python 永不调 LLM §A.1；语义 findings 合并；检查器异常降级不崩）。#9 finding 生命周期=known-and-accepted（`finding_fingerprint`=severity\|dimension\|file\|description，行号不入；`accepted_fingerprints` 构造器 + `contracts["accepted_audit_findings"]` 抑制阈值计数，记 `details["accepted_suppressed"]`）。#8 crafted context 复用既有分层上下文（plate components/contracts + system coverage_map + git_diff 工具 + design/ 直读）——未加 files_changed（audit 阶段已清空且 prompt 不消费，加之虚化）。test_gate_audit +语义层(4)/fingerprint(3)/known-accepted(4) |

## Phase 7 — Init-Loop 契约 v5.6 扩展 (IL.2-IL.5)

> ⚠️ **编号说明**：T34/T35 在此 Phase 与 Phase 13（真跑故障修复）**编号重复**——两个独立 Phase 的独立任务恰好使用了相同编号，并非同一任务。Phase 7 的 T34/T35 是 Init-Loop 契约扩展，Phase 13 的 T34/T35 是真跑故障修复。

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
| S-3 | FreshGuardrail(G8) 契约：B5 每 Gate 产出 files_snapshot_sha+ran_at | P1 | §B3.2/§B5.1 | ✅ | 本轮 |
| S-4 | guardrail_retry_counters 键粒度 + G8 retry 语义（rerun_gates 动作）| P1 | §B3 L629-649,L646,L702 | ✅ | 本轮 |
| S-5 | file-bridge 契约边界矩阵（缺失/半写/错位/重复/超时→action+error_code+恢复）| P1 | §C.3.5（新增）| ✅ | 本轮 |
| S-6 | Guardrail 数量统一（当前5/目标9 + 状态列）| P1 | §C.8/附录/§B3 | ✅ | 本轮 |
| S-7 | done verdict 完整枚举 + 终态优先级 + HARD_LIMIT 拆名 | P1 | §C.3.1/§C.5.4/§C.5.5 | ✅ | 本轮 |
| S-8 | B2 转换表增"决策方(router 纯转换/orchestrator 委派)"列 | P1 | §B2 L544-556 | ✅ | 本轮 |
| S-9 | REDGuardrail RED 证据机制（否则明标为启发式）| P1 | §B15.2 | ✅ | 本轮 |
| S-10 | ResearchAgent 工具级内存护栏规格（authz 限 Read 范围/禁 ls -R）| P1 | §B10.6/§B11.7 | ✅ | 本轮 |
| S-11 | B14 外部依赖清单收口（audit.md 内化关系，消解与 B15.1 矛盾）| P1 | §B14.1/§B15.1 | ✅ | 本轮 |
| S-12 | commit 序列规范（test+impl）+ B9.5 父节点 pending 聚合分支 | P1 | §B13/§B15/§B9.5 | ✅ | 本轮 |
| S-13 | C.12/C.12.1 路径修正 tick_orchestrator.py + 矩阵加"实现状态"澄清 | P1 | §C.12 Phase2 | ✅ | 本轮 |
| S-14 | B1.1 数据模型表补全 #26/#33/#34/#35/#36 | P2 | §B1.1 L370 | ✅ | 本轮 |
| S-15 | B6.1a 现状描述追代码（task_factory 已迁移嵌套 schema）| P2 | §B6.1a L916 | ✅ | 本轮 |
| S-16 | B4 参数→判定对照 + semantic_satisfied 标 legacy | P2 | §B4 | ✅ | 本轮 |
| S-17 | plan_refine 双重身份定案（architect 子模式；澄清 _VALID_STAGES 语义）| P2 | §B1.1/§C.10 | ✅ | 本轮 |
| S-18 | checkpoints WITHOUT ROWID + 大 blob 反模式（定案改 rowid，迁移待落地）| P2 | §B1.3 L485 | ✅ | 本轮（DDL 迁移单列）|
| S-19 | RegressionGuardrail 新建文件分支进伪码 + 正反例断言 | P2 | §B3.3 | ✅ | 本轮 |
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
| V7-1 | `loop/tick_orchestrator.py` — `tick()` 精简为薄包装（读文件 + 委托 `tick_dict()`）+ docstring 声明 canonical 入口 | tick() ≤5 行 + test_tick_orchestrator(52) 全绿 + test_action_result_contract(21) 全绿 | ✅ | 2c0e5fb（Phase 11 合并提交，V7-1~V7-4 合入） |
| V7-2 | `loop/standalone_driver.py` — `STAGE_TO_ROLE` 映射表 + `ROLE_MODEL` 映射表 + `_build_task()` + `_build_tools_for_role()` + `_build_agent_for_stage()` | 10 stage 覆盖 + 环境变量覆盖可测 + Agent 配置正确集成测试 | ✅ | 2c0e5fb |
| V7-3 | `loop/standalone_driver.py` — `AuthProvider` 类型别名 + `_resolve_auth_provider()` AUTH_TOKEN→API_KEY 优先级 | 无 key → AEError + 测试可注入 mock auth | ✅ | 2c0e5fb |
| V7-4 | `loop/tick_orchestrator.py` + `loop/standalone_driver.py` — `restore()` 审查（不含驱动信息）+ `StandaloneDriver.resume()` + 跨进程 resume 集成测试 | restore 不依赖驱动类型 + EngineState.to_dict 不含 auth + resume E2E | ✅ | 2c0e5fb |
| V7-5 | **`loop/standalone_driver.py`** — `StandaloneDriver` 完整实现：`run()` 主循环 + `_execute_action()` + `_execute_developer_serial()` + `_execute_gap_review_headless()` + `_execute_single_task()` + `resume()` + `close()` | 3 stage E2E APPROVE + 5 层验证 GOAL_ACHIEVED + 每 stage 产出符合 schema 的 result + mock LLM 18 tests + **真实 LLM E2E 验证 (fibonacci GOAL_ACHIEVED)** + _run_loop_from_action 控制流 + developer 串行 TDD + gap_review headless auto-Defer + 错误处理优雅降级 | ✅ | V7-1, V7-2, V7-3, V7-4 |
| V7-6 | `cli/dev_loop.py` — `--standalone` flag + `_run_standalone()` + AgentRuntime 注册（architect/developer/critic + AnthropicProvider + 7 tools）+ `cli/doctor.py` — API_KEY 检查项 | `ae dev-loop --standalone "hello"` E2E ✅（真实 LLM 真跑: 6 ticks, GOAL_ACHIEVED, fibonacci 实现+10 tests）+ `--resume` + doctor key 检查 + `--standalone` 与 tick flag 互斥 | ✅ | 2026-07-17 E2E 真跑验证 |
| V7-7 | **v5.5 退役（30 天过渡期）** — Step 4 CLI 裸参数 WARN ✅ → Step 5 BEACON #53 ✅→❌ ✅ → 30 天后执行 Step 1 提取执行栈 → Step 2-3 物理删除 | ✅ 裸参数 `ae dev-loop "req"` 输出 WARN 引导 `--standalone` + BEACON #53 已翻转 + 30 天过渡期启动 | ✅ | a6b0d33 |
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
| V8-1 | **目录结构重构**：`commands/` `hooks/` `skills/` `agents/` 从 `.claude-plugin/` 提升到项目根；`.claude-plugin/plugin.json` paths 更新为 `../` 相对路径；`.codex-plugin/plugin.json` 新建（Codex manifest）；`.codebuddy-plugin/` → `.claude-plugin/` symlink（CodeBuddy 零成本兼容）| 三平台目录结构验收：Claude Code 能发现 plugin + Codex `plugin.json` 语法正确 + CodeBuddy symlink 有效 | ✅ | 2c0e5fb（Phase 12 合并提交，V8-1~V8-8 合入） |
| V8-2 | **Hook 注册拆分**：`hooks-cc.json`（Claude Code，含 on-pr.sh）+ `hooks-codex.json`（Codex，仅 4 hooks：session-start/post-edit/pre-tool/stop）+ `hooks-codebuddy.json`（CodeBuddy，同 CC）；`session-start.sh` 加 `$AE_PLATFORM` 平台检测逻辑（从 `$CLAUDE_PLUGIN_ROOT`/`$CODEX_PLUGIN_ROOT`/`$CODEBUDDY_PLUGIN_ROOT` 判定）；其余 hook 脚本用 `$AE_PLUGIN_ROOT` 统一变量 | 三平台 hook 注册文件语法正确 + session-start.sh 三平台检测正确 + Codex 无 on-pr.sh（仅 4 hooks） | ✅ | V8-1 |
| V8-3 | **Provider Protocol + AnthropicProvider 适配**：`providers/base.py` 新建（`LLMProvider` Protocol + `LLMResponse` + `ToolUseBlock` dataclasses）+ `agents/base.py` `AnthropicProvider` 加 `_to_llm_response()` adapter | `LLMProvider` Protocol 编译通过 + `AnthropicProvider` 适配后 `_to_llm_response` round-trip 正确 + test 11 passed | ✅ | 2c0e5fb |
| V8-4 | **OpenAIProvider 实现**：`providers/openai_provider.py` 新建（Anthropic tool_use ↔ OpenAI function_call schema 双向转换 + response 转换为 `LLMResponse` 统一格式）+ `providers/factory.py` 新建（`create_provider(platform, api_key, model)` 工厂）| Anthropic→OpenAI tool schema 正确转换 + OpenAI→LLMResponse 正确转换 + mock OpenAI API 集成测试 | ✅ | V8-3 |
| V8-5 | **BaseAgent + StandaloneDriver 适配**：`BaseAgent.llm` 类型注解从 `AnthropicProvider` 改为 `LLMProvider` Protocol；`StandaloneDriver._build_agent_for_stage()` 用 `create_provider()` 工厂选择 Anthropic/OpenAI 后端 | mypy 类型检查通过（`LLMProvider` Protocol 兼容）+ BaseAgent 现有 11 tests 全绿 + StandaloneDriver 用 OpenAI mock 通过 | ✅ | V8-3, V8-4 |
| V8-6 | **安装方案标准化（Marketplace 替代 install.sh）**：调研三平台标准安装机制 → 删除自造 `install.sh` → 修正 `plugin.json` 路径 `../` → `./`（对齐 Claude Code 规范）→ marketplace.json 自引用 source=`"./"` → 更新 PLUGIN-USAGE.md + USER_GUIDE.md 安装章节 → BEACON 决策 #58 | `/plugin marketplace add qianminjian/Auto-engineering` + `/plugin install auto-engineering@qianminjian --scope user` 成功安装 | ✅ | V8-1, V8-2 |
| V8-7 | **doctor + pyproject.toml 更新**：`ae doctor` 加 OpenAI API key 检查（`OPENAI_API_KEY` 环境变量）+ 平台检测项（`$AE_PLATFORM`）+ `pyproject.toml` 加 `openai` 可选依赖（`[project.optional-dependencies] openai = ["openai>=1.0"]`）| `ae doctor` 显示平台 + key 状态 + `uv sync --extra openai` 安装成功 | ✅ | V8-4 |
| V8-8 | **文档更新**：`USER_GUIDE.md` / `PLUGIN-USAGE.md` / `production-deployment.md` 加三平台安装说明 + 命令语法差异（Claude Code `/dev-loop` vs Codex `//dev-loop` skill 调用 vs CodeBuddy `/dev-loop`）| 三份文档含平台特定章节 + grep 断言三平台均覆盖 | ✅ | V8-6 |

> **推荐实施顺序**：先 v8.0 Provider 抽象（V8-3→V8-4→V8-5），再做 v7.0 StandaloneDriver（V7-5），因为 StandaloneDriver 依赖 Provider 工厂。v8.0 平台适配层（V8-1/2/6/7/8）可独立于 v7.0 推进。
> **与 v7.0 依赖关系**：V7-5 StandaloneDriver ↔ V8-3/4/5 Provider 抽象（前置）；V7-6 CLI ↔ V8-7 doctor 扩展；V8-1/2/6 目录+Hook+install.sh 为 v8.0 独有。
> 详细接口签名/Provider 代码/install.sh 脚本见 v5.6-Design-Loop.md 附录 D 各节。

---

## Phase 13 — 真跑故障修复 (voice_clone 2026-07-17)

> 来源：voice_clone_for_auto_test-2 项目使用 `/ae:dev-loop` 真跑产出的 29 问题报告。
> 范围：10 项引擎/设计层面修复（19 项为项目侧，不在本仓库范围）。
> 依赖顺序：P0 crash → P1 数据契约+REDGuardrail+状态管理 → P2 改善项 → 集成测试。
> BEACON 决策 #59。
> ⚠️ **编号说明**：T34/T35 在此 Phase 与 Phase 7（Init-Loop 契约扩展）**编号重复**——两个独立 Phase 的独立任务恰好使用了相同编号，并非同一任务。Phase 7 的 T34/T35 是 Init-Loop 契约扩展（T34 monorepo 单包降级 / T35 reference fixture round-trip），Phase 13 的 T34/T35 是真跑故障修复（T34 B3 guardrail crash / T35 B2 stage mismatch）。

| T | Issue | 文件/描述 | 验收 | P | 状态 | Commit |
|---|-------|----------|------|:---:|:---:|--------|
| T34 | B3 | `loop/guardrail.py:291` TestsPass.check() — `isinstance(results, dict)` 类型守卫。test_results 传入字符串时 `results.get()` crash，期望 dict 收到 str 应返回明确错误而非 Python crash | 字符串 test_results → retry + 明确错误信息 | P0 | ✅ | (本次) |
| T35 | B2 | `loop/tick_orchestrator.py` RESULT_VALIDATION_ERROR — stage 不匹配时错误信息区分 `stage`（角色名如 "developer"）和 `batch_id`（如 "B4"），提示用户填角色名非 batch_id | STAGE_MISMATCH 错误信息含 "(stage 是角色名如 'developer'/'architect', 不是 batch_id 如 'B4')" | P1 | ✅ | (本次) |
| T36 | B4/B5 | `loop/tick_orchestrator.py` expected_format — component_verifier 和 plate_deep_audit 的 expected_format 列出所有必填字段（component/plate），避免 RESULT_VALIDATION_ERROR 因缺字段遗漏 | expected_format 含 component(verifier)/plate(audit) 必填字段声明 | P1 | ✅ | (本次) |
| T37 | B11 | `loop/guardrail.py` REDGuardrail red_evidence 格式校验 — 字符串数组 vs 对象数组格式错误时给出明确提示+期望格式 | red_evidence format error 信息含期望格式示例 `[{"task_id": "B3-T1", "red_commit": "abc123"}]` | P1 | ✅ | (本次) |
| T38 | B8 | `loop/guardrail.py` REDGuardrail 交叉文件检测 — GREEN commit 修改了 RED commit 的测试文件时（RED→GREEN 链断裂），检测并给出明确错误 | GREEN commit 触碰 test 文件 → retry + "GREEN commit 修改了测试文件" 提示 | P1 | ✅ | (本次) |
| T39 | B9/D2 | `engine/batch_state.py` 零 batch 组件警告抑制 — module-level `_warned_zero_batch` set 去重，每个组件只警告一次 | 同一组件警告只输出一次，后续 tick 不再重复 | P1 | ✅ | (本次) |
| T40 | D1 | `engine/progress_tree.py` _apply_sync — plan_refine 后 total_tasks 变化时将旧 verifier_status 重置为 "pending"，避免 stale "failed" 状态 | plan_refine 后组件 total_tasks 变化 → verifier_status 自动重置为 "pending" | P1 | ✅ | (本次) |
| T41 | B6 | ~~`commands/dev-loop.md` 测试命令 — 移除 `--no-cov` 参数（vitest 无此参数）。~~ 经查引擎 TestGate 不硬编码 --no-cov，根因在项目 Agent 行为非引擎代码。**作废：非本项目范围，voice_clone 项目侧问题。** | — | — | 🗑️ | 作废 — 非本项目 |
| T42 | D3 | `loop/tick_orchestrator.py` REFINE_LIMIT 错误信息 — 超配额时给出 actionable 建议（拆分 Phase / design_doc 标注延后）| REFINE_LIMIT reason 含 "建议: 拆分需求为多个 Phase 分别处理, 或在 design_doc 中标注设计项为延后" | P2 | ✅ | (本次) |
| T43 | — | `tests/test_guardrail.py::TestVoiceCloneRegression` 集成测试 — 5 场景覆盖 B3/B8/B11/B9/D2/D1 修复不回归 | 5 tests pass, 全量 250 passed (guardrail+tick_orch+batch_state+progress_tree) | P1 | ✅ | (本次) |

> **实施顺序**：T34(P0) → T35/T36/T37(独立 P1) → T38(P1 REDGuardrail) → T39/T40(P1 状态管理) → T41/T42(P2) → T43(集成测试)

---

## Phase 14 — gate_results 结构错配修复 (忠实度分析 2026-07-17)

> 来源：voice_clone 项目 dev-loop 忠实度分析发现 production 路径 gate_results 全部为 null。
> 根因：`_run_developer_gates()` 调用 `run_gates()` 但 `run_gates()` 返回嵌套结构，`_run_developer_gates()` 直接迭代顶层 key → 所有 gate 结果丢失。
> 性质：代码 bug 修复（production 路径 gate 结果静默丢失）。BEACON 决策 #60。

| T | Issue | 文件/描述 | 验收 | P | 状态 | Commit |
|---|-------|----------|------|:---:|:---:|--------|
| T44 | D4 | `loop/tick_orchestrator.py:_run_developer_gates()` — `run_gates()` 返回 `{project_root, gate_names, passed, failed, skipped, gate_summary: {实际gate结果}}`，原代码直接迭代顶层 key 误将 wrapper key 当 gate 名。修复：`raw.get("gate_summary", raw)` 统一提取内层结果，扁平 dict（测试 stub）无此 key 回退自身。新增 `test_extracts_gate_summary_from_nested_run_gates_output`。 | production 路径 gate_results 含真实 gate 名非 wrapper key + 全量 251 passed 零回归 | P0 | ✅ | (本轮) |

> **真实严重度定级 P0**：gate_results 是 Iron Law D4（Python is Gatekeeper）的核心输出——所有 gate 结果静默丢失意味着生产运行时 gate 执行了但结果不可观测，侵蚀引擎"可观测的 Gatekeeper"定位。测试全绿是因为测试 stub 返回扁平 dict 不经过 `run_gates()` 嵌套路径——代码与测试路径分叉制造了虚假绿色。

---

## Phase 15 — DebugTracer: dev-loop 调度轨迹诊断 (2026-07-17)

> 来源：用户需求——为真实项目测试中记录 loop 工程问题，增加 debug 选项将调度轨迹/故障信息写入运行项目的 debug 目录。
> 设计：`ae dev-loop --init --debug` 或 `AE_DEBUG=1` 激活。三输出文件：tick-{N:04d}.json、errors.jsonl、trace.json。`DebugTracer.disabled()` 零开销 no-op。
> BEACON 决策 #61。

| T | 文件/描述 | 验收 | P | 状态 | Commit |
|---|----------|------|:---:|:---:|--------|
| T45 | `loop/debug_tracer.py`（101 行）+ `tests/test_debug_tracer.py`（9 tests）+ EngineState #38-39 + `tick_orchestrator.py` 5 hook 点集成 + `cli/__init__.py` `--debug`/`--debug-dir` flag + `cli/dev_loop.py` 全路径接线 | 9 debug_tracer tests + 103 tick_orchestrator tests + 47 engine_state + 21 batch_state + 58 stage_router = 238 passed 零回归 | P1 | ✅ | (本轮) |

> **真实严重度定级 P1**：debug 功能非引擎核心路径，但为生产问题诊断提供关键可观测性——per-tick 快照 + 故障事件 JSONL + 最终摘要覆盖了"引擎静默出错时无现场"的诊断盲区。

---

> **Phase 16 未使用**（编号跳过，Phase 15→Phase 17 直接过渡）。Phase 16 曾分配给 PrismScan 真跑故障修复（commit 52e1160），后因 PrismScan 移出本仓库范围而撤销，编号保留跳过以避免后续 Phase 重编号。

## Phase 17 — 设计治理修复（vNext，~3-5 天）

> 来源：`design/discussion/vNext-LangGraph-DeepAgents-对标分析.md` §🚨 前置发现 + BEACON 决策 #64。
> 目标：恢复 6 角色独立 Agent 隔离 + Governance 规则扩展。T10（2026-07-11）误将 Claude Code 内置 subagent 与外部框架 agent 打包禁用——修复此设计执行错误。

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T49 | `commands/dev-loop.md` + `skills/auto-engineering/SKILL.md` — 禁令块整段删除（L98-L105 / L41-L45 四行禁令移除） | grep 断言禁令行已删除 + Plugin 验收 | ✅ | a6b0d33 |
| T50 | `commands/dev-loop.md` — 恢复外部搜索/MCP 能力（加回 MCP 工具和搜索 skill 的允许指令） | grep 断言搜索/MCP 指令存在 | ✅ | a6b0d33 |
| T51a | `commands/dev-loop.md` Stage 1 — architect 恢复 Plan subagent（改回 spawn `subagent_type="Plan"`） | Plugin 验收：architect 指令含 spawn Plan agent | ✅ | a6b0d33 |
| T51b | `commands/dev-loop.md` Stage 3 — critic 恢复 code-reviewer subagent（改回 spawn `subagent_type="code-reviewer"`） | Plugin 验收：critic 指令含 spawn code-reviewer agent | ✅ | a6b0d33 |
| T51c | `commands/dev-loop.md` — component_verifier 恢复 general-purpose subagent（Haiku 轻量模型） | Plugin 验收：verifier 指令含 spawn general-purpose agent（Haiku） | ✅ | a6b0d33 |
| T51d | `commands/dev-loop.md` — plate_deep_audit 恢复 3× code-reviewer subagent（Sonnet，B6.7a 并行审计） | Plugin 验收：plate_deep_audit 指令含 3 并行 spawn | ✅ | a6b0d33 |
| T51e | `commands/dev-loop.md` — system_verifier 恢复 general-purpose subagent（Haiku 轻量模型） | Plugin 验收：system_verifier 指令含 spawn general-purpose agent（Haiku） | ✅ | a6b0d33 |
| T51f | `commands/dev-loop.md` — system_deep_audit 恢复 3× code-reviewer subagent（Sonnet，B6.7a 全量审计） | Plugin 验收：system_deep_audit 指令含 3 并行 spawn | ✅ | a6b0d33 |
| T52a | `.claude/rules/design-document-inviolability.md` — 覆盖范围扩展到 `commands/*.md` + `skills/*/SKILL.md` + `hooks/*.sh` 中涉及架构设计约束的变更 | grep 断言规则覆盖 commands/skills/hooks | ✅ | a6b0d33 |
| T52b | `design/BEACON.md` — B14 追加澄清：Claude Code 内置 subagent（Plan/code-reviewer/general-purpose）**不属于**"外部依赖"，是平台原生能力。禁令仅针对外部框架专属 agent（gsd-* / superpowers-*） | grep 断言 B14 澄清文本存在 | ✅ | a6b0d33 |
| T52c | `design/BEACON.md` — B14 追加澄清：MCP 工具和外部搜索 skill 是**信息获取工具**，不是执行者，不在禁令范围 | grep 断言 B14 澄清文本存在 | ✅ | a6b0d33 |
| T52d | 全量回归测试 — 修改后 dev-loop.md + SKILL.md Plugin 验收 20 场景 + 现有测试全量通过 | 全量 pytest 零回归 + Plugin 验收 20/20 | ✅ | a6b0d33 |

> **关键设计约束**：仅 developer 角色需要跨 batch 上下文连贯（主 Agent 自身）。其他 6 角色（architect/critic/component_verifier/plate_deep_audit/system_verifier/system_deep_audit）均为独立 subagent——每次 tick 新 spawn，不共享 developer 上下文，只消费结构化输入（设计文档/batch_plan/diff）产出结构化 JSON。

---

## Phase 18 — Context & 安全加固（vNext，~7-11 天）

> 来源：`design/discussion/vNext-LangGraph-DeepAgents-对标分析.md` §2 + §3 + §5 + BEACON 决策 #65。
> 前置：Phase 17 subagent 隔离恢复（subagent 隔离恢复后 context 压力从"1 个 Agent 扛 7 个角色"变为"7 个独立 window 分摊"，T53/T54 仅 developer 需要）。
> 银行生产级定位要求模型无关 + PII 防护为 P0。

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T53 | `auto_engineering/context/offloading.py`（新建）— Stage context offloading：每 stage 完成后将全量 context 卸载到文件，下 stage 只加载摘要+必要上下文。**Phase 17 后更简单**：每个 subagent 产出是结构化 JSON（batch_plan/findings），主 Agent 只消费摘要 | offload 文件含 stage/round/timestamp + 摘要质量可配置 + test_context_offloading ≥5 tests | ✅ | 92d3a47 |
| T54 | `auto_engineering/context/summarization.py`（新建）— Cross-tick developer session summarization：tick 超过可配置阈值（默认 5）时将前 N-1 tick 的对话历史压缩为结构化摘要注入 prompt。**仅 developer 需要**——其他 6 角色每次 tick 新 spawn，天然无累积压力 | tick=阈值+1 时摘要生成 + 摘要含关键决策/文件变更/MAJOR 历史 + test_summarization ≥5 tests | ✅ | 92d3a47 |
| T55 | `auto_engineering/providers/ollama.py`（新建）— Ollama adapter：OpenAI 兼容 API，tool_use ↔ function_call 格式转换复用 v8.0 Provider 抽象。**银行内网 P0**：离线部署不依赖外部 API | Ollama 本地模型 E2E（architect→critic APPROVE）+ test_ollama_provider ≥5 tests | ✅ | 92d3a47 |
| T56 | `auto_engineering/pii/redactor.py`（新建）+ `agents/base.py` — Prompt PII redaction：在 `BaseAgent.execute()` 的 LLM 调用前插入 `PIIRedactor.scan(messages)` → 命中规则脱敏 + `logger.warning`。非侵入式 pipeline，不修改 system prompt 模板 | 5 类 PII 规则扫描 + 脱敏后 messages 正确传递 + test_pii_redactor ≥8 tests | ✅ | 92d3a47 |
| T57 | `auto_engineering/pii/redactor.py` + `agents/base.py` `_truncate_tool_results()` 扩展 — Tool result PII scan：在每个 tool_result content 调用 `PIIRedactor.scan_text()` → 脱敏 + warn。不改变函数签名 | tool_result PII 脱敏 + 调用方无感 + test_pii_scan ≥5 tests | ✅ | 92d3a47 |

> **T53/T54 设计参考**：Deep Agents `deepagents/middleware/summarization.py`（Apache 2.0）— 复用摘要 prompt 模板 + offload 策略，改造后纳入 `auto_engineering/context/`。T55 参考 LangChain `ChatOllama` adapter 的 OpenAI 兼容层——复用 tool_use ↔ function_call 格式转换，去掉 LangChain 依赖。
> **T56/T57 PII 检测规则**：PIIDetectionRule dataclass — cn_id_card / cn_phone / bank_card / api_key / email。含 exclusion_patterns + 白名单机制。失败不阻断（默认脱敏+WARN），block 模式可选开关。详见 v5.6-Design-Loop.md 附录 E §E.3。

---

## Phase 19 — 模型扩展 & 可观测性（vNext，~8-14 天）

> 来源：`design/discussion/vNext-LangGraph-DeepAgents-对标分析.md` §3 + §4 + §6 + §1.5 + BEACON 决策 #66。
> 前置：Phase 18 T55 Ollama adapter（Provider 抽象验证）。

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T58 | `auto_engineering/providers/glm.py` + `auto_engineering/providers/qwen.py` 等（新建）— 国产模型 adapter（GLM/通义/文心）。优先 OpenAI 兼容格式（大部分国产模型已兼容），adapter 做得很薄。**信创合规 P0** | 至少 2 个国产模型 E2E 通过 + test_domestic_providers ≥5 tests | ✅ | a204fa1 |
| T59 | `loop/standalone_driver.py` — StandaloneDriver 完善（v7.0 路线图 V7-5 已 mock 验证，补齐真实 LLM 多 provider 集成）。**银行内网 P0**：无外部 Agent 平台时的唯一运行方式 | Ollama + 国产模型 E2E GOAL_ACHIEVED + test_standalone_multi_provider ≥5 tests | ✅ | 0c9143a |
| T60 | `auto_engineering/observability/tracing.py`（新建）— OpenTelemetry tracing：每个 stage/guardrail/gate 打 OTLP span，导出到 OTLP collector。行业标准，不绑定厂商 | OTLP span 含 stage/guardrail/gate 层级 + test_tracing ≥5 tests | ✅ | 5a9864b |
| T61 | `auto_engineering/observability/audit_log.py`（新建）— Structured audit log：每次 LLM 调用记录完整 request/response/timestamp/tokens，JSONL 格式持久化。扩展 DebugTracer | audit JSONL 含完整 request/response + test_audit_log ≥5 tests | ✅ | 34fa671 |
| T62 | `auto_engineering/loop/guardrail.py` — FileAccessGuardrail：新增 Guardrail，post-agent 检查 developer 的 `files_changed` 是否全在 `batch_plan.file_targets` 范围内。超出 → block + 报告越界文件列表 | 越界文件 block + 白名单 `.ae-state/` `_scratch/` 自动放行 + test_file_access_guardrail ≥5 tests | ✅ | 65d02df |
| T62a | `auto_engineering/gates/` 或 guardrail 内部 — glob 支持：`pathspec` 库集成，支持 `.gitignore` 风格的 file_targets 匹配（`src/**/*.py`） | glob 模式匹配正确 + test_glob_matching ≥3 tests | ✅ | e923b86 |
| T63 | `llm/anthropic_provider.py` — Prompt caching：在 `create_message()` 中注入 `cache_control`（`{"type": "ephemeral", "ttl": "5m"}`）到 system content block 和 tools 数组。Anthropic Messages API 原生支持，system 是顶级参数非 messages role | cache_control 注入 + `usage.cache_creation_input_tokens` > 0 + test_prompt_caching ≥3 tests | ✅ | 37e21ee |
| T64 | `loop/tick_orchestrator.py` + `cli/dev_loop.py` — Stage Checkpoint Gate（DecisionGate 形态 3，§1.5.5）：`--pause-at-stage` 参数，指定 stage 前暂停等待 CLI 输入（继续/审查/终止） | --pause-at-stage architect/developer/critic 暂停 + 进度摘要输出 + test_stage_checkpoint ≥5 tests | ✅ | 657e401 |

> **T58 设计参考**：LangChain `ChatZhipuAI`/`ChatTongyi` 等 adapter — 复用 API 差异处理模式（大部分国产模型已兼容 OpenAI 格式，adapter 很薄）。
> **T60/T61 设计参考**：OpenTelemetry SDK + Deep Agents LangSmith middleware（复用 trace 层级设计模式）。

---

## Phase 20 — AI Coding 度量与自进化体系（设计定稿，待实现）

> 来源：`design/discussion/vNext-AI-Coding-度量与自进化体系.md`（2026-07-19 四项用户决策定案）+ v5.6-Design-Loop.md 附录 F（开发就绪规格）。
> 前置：Phase 15 DebugTracer + Phase 19 OTLP tracing + audit log（基础设施就绪）。
> 预估：~12-17 天 | 依赖链：T65 → {T66, T67}（并行）→ T68 → T69a → T69b → T69c

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T65 | `auto_engineering/metrics/collector.py`（新建 ~300 行）— MetricsCollector + `AIOrigin` dataclass + 5 类事件采集 + 需求生命周期（begin/end）+ M1-M5 聚合计算（含 loc_added 效率比）+ 基线管理 + compare_periods 时段对比 | 5 事件类型采集 + summary.json 含 M1-M5 + AE_METRICS=1 激活 + test_metrics_collector ≥8 tests | ✅ | 2026-07-19 |
| T66 | `agents/base.py` `execute()` — `asyncio.to_thread(self.llm.create_message, ...)` 返回后同步调 `MetricsCollector.record_token_usage()`（一处覆盖所有 provider）| token_usage 事件正确记录 + 所有 provider 统一走 agent 层 hook + test_token_hook ≥3 tests | ✅ | 2026-07-19 |
| T67 | `auto_engineering/metrics/signals.py` + `diagnoser.py`（新建）— SignalDetector（5 种检测：趋势/突变/比率异常/成本告警，含冷启动 M5 硬编码阈值）+ Diagnoser（5 条诊断规则，human_actions 显式标注）| 5 种信号检测正确（含冷启动分支）+ 5 条诊断规则覆盖 + test_signals ≥5 tests + test_diagnoser ≥3 tests | ✅ | 2026-07-19 |
| T68 | `auto_engineering/metrics/ratchet.py`（新建）— RatchetController（keep/revert/stop 三元判定）+ 配置版本化（git tag ae-config-v{N} + JSON 配置文件，git tag 失败返回 None）+ 回滚机制 | keep/revert/stop 判定正确 + 配置快照/回滚 + git tag 降级 JSON 备选 + test_ratchet ≥5 tests | ✅ | 2026-07-19 |
| T69a | `loop/tick_orchestrator.py` 5 集成点 + `cli/dev_loop.py` 生命周期 | `.ae-state/metrics/` 有完整 events.jsonl + summary.json（无信号/诊断）+ test_metrics_integration ≥3 tests | ✅ | 2026-07-19 |
| T69b | `loop/tick_orchestrator.py` `_build_action()` 接线 SignalDetector + Diagnoser | 收敛后 action JSON 含 signals + diagnosis + test_metrics_integration ≥2 tests | ✅ | 2026-07-19 |
| T69c | `loop/tick_orchestrator.py` RatchetController 集成 + action JSON `suggestions` 字段 | E2E 完整链路 + 低风险自动调整/中风险 AskUserQuestion + test_metrics_integration ≥3 tests | ✅ | 2026-07-19 |

> **实施顺序**：T65（MetricsCollector 基础）→ T66（Provider hook）和 T67（SignalDetector+Diagnoser）**可完全并行** → T68（RatchetController，依赖 T67 信号输出）→ T69a（事件打点）→ T69b（信号+诊断接线）→ T69c（Ratchet + suggestions 完整接线）。
> 详细接口签名/数据流/验收标准见 v5.6-Design-Loop.md 附录 F 各节。

---

## Phase 21 — 自进化深化（阈值学习 + 规则发现，设计定稿，Phase 20 后启动）

> 来源：v5.6-Design-Loop.md 附录 F.10-F.12（2026-07-19 设计定稿）+ BEACON 决策 #70。
> 前置：Phase 20 T69c 完成 + 生产数据积累 ≥30 需求。
> 预估：~6-9 天 | 依赖链：T70 和 T71 完全并行 → T72（需两者输出）

| T | 文件/产出 | 验收 | 状态 | Commit |
|---|----------|------|:---:|--------|
| T70 | `auto_engineering/metrics/threshold_learner.py`（新建 ~120 行）— ThresholdLearner + Beta-Binomial 贝叶斯共轭先验模型：10 个可学习阈值（5 tunable params + 5 cold-start 阈值），Beta(α=2,β=2) 弱先验 → 二元观测更新 → 后验 Beta(α+successes, β+failures)，≥30 观测提议调整，硬上下界安全护栏，propose_adjustments() 一次只提议一个阈值 | 后验收敛验证 + 提议偏离 >5% 触发 + test_threshold_learner 16 tests | ✅ | 2026-07-19 |
| T71 | `auto_engineering/metrics/rule_discoverer.py`（新建 ~250 行）— DiagnosticRuleDiscoverer：6 压力维度（需求模糊度/设计文档大小/恢复频率/模型版本变更/需求复杂度/跨组件耦合度）× M1-M5 Spearman 秩相关扫描，|ρ|>0.5 + p<0.05 → 候选诊断规则，CandidateRule dataclass，JSON 输出供人工审查 | 30+ 需求输入 → ≥1 候选规则（|ρ|>0.5）+ Spearman 计算正确性验证 + test_rule_discoverer 10 tests | ✅ | 2026-07-19 |
| T72 | `auto_engineering/metrics/ratchet.py` 扩展 — RatchetController `sandbox_evaluate()`：接收 ThresholdLearner 提议 + DiagnosticRuleDiscoverer 候选规则，sandbox 预验证（历史数据回放 + 对比评估），keep/revert/stop 三元判定 + `_merge_rule()` 合并规则到 baselines/merged_rules.json | sandbox 预验证正确 + keep/revert/stop 判定 + test_ratchet_sandbox 6 tests | ✅ | 2026-07-19 |

> **实施顺序**：Phase 20 T69c 完成 → 积累 ≥30 需求生产数据 → T70（ThresholdLearner）和 T71（DiagnosticRuleDiscoverer）**可完全并行**（各自独立消费 events.jsonl + summary.json）→ T72（RatchetController sandbox_evaluate + CLI，需要 T70 提议 + T71 候选规则）。
> **为什么不在 Phase 20**：Beta 后验需要 ≥30 观测才提议调整，Spearman 相关需要 ≥30 需求数据点——Phase 20 跑通度量采集前不满足。Phase 20 先用 5 条手工诊断规则跑通信号→诊断→棘轮全链路，Phase 21 再用数据驱动深化。
> 详细设计见 v5.6-Design-Loop.md 附录 F.10（ThresholdLearner）、F.11（DiagnosticRuleDiscoverer）、F.12（Phase 21 任务分解）。

---

---

## Phase 22 — Phase 18-19 虚化模块集成接线（审计发现，~4-6 天）

> 来源：`_scratch/audit-phase17-21/PHASE17-21-DEEP-AUDIT.md`（2026-07-19 深度审计）。
> 根因："Build-then-Wire" 反模式——7 个模块完整构建+测试通过，但生产调用链从未到达。~1875 行虚化代码。
> 前置：Phase 18 + Phase 19 模块已构建（T53-T64 代码完成）。
> **2026-07-19 真跑评估修复**：Phase 22 初版仅完成 orchestrator/provider 侧参数位预留，CLI 入口（dev_loop.py）从未实例化模块传入——导致 tick_orchestrator 收到 None 静默 No-op。真跑评估后发现，补齐 dev_loop.py 两端入口 + restore() 参数 + log_event 方法 + tracing span。

| T | 文件/产出 | 验收 | P | 状态 | Commit |
|---|----------|------|:---:|:---:|--------|
| T73 | `loop/tick_orchestrator.py` + `cli/dev_loop.py` — ContextOffloader 集成：TickOrchestrator 预留参数位 + dev_loop.py 两个入口实例化 `ContextOffloader(root / ".ae-state" / "offload")` 传入。每次 tick 结束时 offload stage context。**2026-07-19 真跑评估修复**：原仅有 orchestrator 侧参数位，CLI 侧从未实例化→静默 No-op | stage 切换后 offload 文件存在 + test_context_integration ≥3 tests | P1 | ✅ | 2026-07-19 |
| T74 | `loop/tick_orchestrator.py` + `cli/dev_loop.py` + `context/summarization.py` — SessionSummarizer 集成：TickOrchestrator 预留参数位 + dev_loop.py 实例化 `SessionSummarizer()`（llm_provider=None，AgentDriver 降级模式）。`summarization.py` 构造函数改为 `llm_provider: LLMProvider | None = None` 支持无 LLM 场景。**2026-07-19 真跑评估修复**：原 orchestrator 侧参数存在，CLI 侧从未实例化；llm_provider 原为必选参数 | tick>5 时降级模式返回空摘要不崩溃 + test_summarization_integration ≥3 tests | P1 | ✅ | 2026-07-19 |
| T75 | `agents/base.py` — PIIRedactor T56 prompt 脱敏接入：`BaseAgent.execute()` 在 `self.llm.create_message()` 前调用 `PIIRedactor.scan(messages)` | 5 类 PII 规则扫描 + 脱敏后 messages 传递 + test_pii_prompt_redaction ≥3 tests | P1-HIGH | ✅ | 2026-07-19 |
| T76 | `cli/dev_loop.py` + `loop/tick_orchestrator.py` — setup_tracing() 接入：dev_loop.py 两个入口调用 `setup_tracing(service_name, otlp_endpoint=AE_OTLP_ENDPOINT)`，AE_OTLP_ENDPOINT 环境变量激活。orchestrator 中 `tick_dict()` 和 `_run_developer_gates()` 添加 tracing span。**2026-07-19 真跑评估修复**：原计划说 cli/__init__.py，实际接线在 dev_loop.py；orchestrator 侧无 tracing span | OTLP span 含 tick/gate 层级 + test_tracing_integration ≥2 tests | P1 | ✅ | 2026-07-19 |
| T77 | `llm/anthropic_provider.py` + `cli/dev_loop.py` + `observability/audit_log.py` — AuditLogger 接入：provider 侧 `create_message()` 调用 `log_call()` + dev_loop.py 检查 `AE_AUDIT_LOG=1` 实例化 `AuditLogger(path)` 传入 orchestrator。AuditLogger 新增 `log_event()` 方法（非 LLM 事件：gate 执行/收敛判定/guardrail 拦截）。orchestrator gate 执行后记录 audit 事件。**2026-07-19 真跑评估修复**：原仅 provider 侧 log_call，CLI 侧从未实例化；无 log_event 方法 | audit JSONL 含完整 request/response + gate/convergence 事件 + test_audit_integration ≥2 tests | P1 | ✅ | 2026-07-19 |
| T78 | `loop/guardrail.py` — FileAccessGuardrail G11 接入：`GuardrailChain.default()` 中注册 G11（post-developer 检查 files_changed 是否在 file_targets 内） | 越界文件 block + G11 在 default chain 中 + test_g11_integration ≥3 tests | P1-HIGH | ✅ | 2026-07-19 |

> **实施顺序**：T75（安全防线）和 T78（安全防线）最高优先 → T73/T74（运维增强）→ T76/T77（可观测性）。
> **为什么不在 Phase 18-19 原任务中修复**：原任务已标记完成并 commit。这些是集成接线缺失——模块代码正确，调用链未注册。作为独立 Phase 追溯审计发现。

---

## Phase 23 — Phase 20 P0 数据流修复（审计发现，~2-3 天）

> 来源：`_scratch/audit-phase20-deep/PHASE20-ROUND4-AUDIT.md`（2026-07-19 Round 4 审计）。
> 3 个 P0 阻断：信号管线无历史数据、M2 结构性为零、M5 效率比永久为零。
> 前置：Phase 20 T65（MetricsCollector）代码已存在。

| T | 文件/产出 | 验收 | P | 状态 | Commit |
|---|----------|------|:---:|:---:|--------|
| T79 | `loop/tick_orchestrator.py` — P0-A 信号管线传入 history + baseline：`_build_action()` → `compute_metrics_signals(mc, history=recent_history, baseline=baseline)` + `MetricsCollector.load_history()` + `load_baseline()` | 5 种信号检测器全部可触发（≥5 history 时 trend 检测触发，≥8 时 verification_skip 触发） + test_signals_with_history ≥3 tests | P0 | ✅ | 2026-07-19 |
| T80 | `loop/tick_orchestrator.py` — P0-B M2 传入 criteria_met：terminal verdict 处调用 `record_convergence(criteria_met="critic_approved"/"plan_refine"/"hard_limit")` | M2_critic_major_rate > 0（critic MAJOR 后） + test_m2_criteria_met ≥3 tests | P0 | ✅ | 2026-07-19 |
| T81 | `auto_engineering/metrics/collector.py` — P0-C M5 git diff 修复：`_compute_loc_added` 中 `git diff --stat --cached HEAD` → `git diff --stat HEAD~1 HEAD` | M5_token_efficiency > 0（有代码变更时） + test_m5_efficiency ≥2 tests | P0 | ✅ | 2026-07-19 |

> **实施顺序**：T79 → T80 → T81（可并行，各自独立修复）。

---

## Phase 24 — Phase 20 P1/P2 修复（审计发现，~3-5 天）

> 来源：`_scratch/audit-phase20-deep/PHASE20-ROUND4-AUDIT.md` §P1 + §P2。
> 5 P1（功能缺口/数据流断裂）+ 4 P2（代码质量）。
> 前置：Phase 23 P0 修复完成。

| T | 文件/产出 | 验收 | P | 状态 | Commit |
|---|----------|------|:---:|:---:|--------|
| T82 | `cli/dev_loop.py` — P1-A category 参数传入：2 处 `begin_requirement()` 调用传入 `requirement_category` | by_category/ 目录有分类基线文件 + test_category_baseline ≥2 tests | P1 | ✅ | — |
| T83 | `loop/tick_orchestrator.py` — P1-B 信号管线仅收敛后调用：`_build_action()` 中 `compute_metrics_signals` 移到 done verdict 分支（`_convergence_check`） | 非收敛 tick 不触发信号分析 + test_signals_only_on_convergence ≥2 tests | P1 | ✅ | — |
| T84 | `auto_engineering/metrics/collector.py` — P1-C tick 编号统一：`record_tick_snapshot` 改为 `tick_no + 1`（1-based，与 `record_tick_complete` 一致） | tick-0001.json 对应 tick_number=1 + test_tick_numbering ≥2 tests | P1 | ✅ | — |
| T85 | `auto_engineering/metrics/collector.py` — P1-D resume_events 恢复 category：`resume_events()` 读取 `metadata.json` 恢复 `_current_category` | 跨进程 resume 后 category 正确 + test_resume_category ≥2 tests | P1 | ✅ | — |
| T86 | `auto_engineering/metrics/collector.py` — P1-E compare_periods 对齐设计：按 requirements/*/summary.json tag 时间戳分 before/after + statistics.median 聚合 | compare_periods 输出含 M1/M2 median + sample_size + test_compare_periods ≥3 tests | P1 | ✅ | — |
| T87 | `auto_engineering/metrics/signals.py` — P2-A 死代码处理：5 个仅测试调用的 helper 方法接入 `analyze()` | 5 方法在生产路径可达 + test_signals_coverage ≥2 tests | P2 | ✅ | — |
| T88 | `cli/dev_loop.py` — P2-B 冗余 _flush 移除：`_run_tick_init` 中 `begin_requirement()` 后的 `collector._flush()` 移除 | 无冗余 flush + test_no_redundant_flush ≥1 test | P2 | ✅ | — |
| T89 | `auto_engineering/metrics/collector.py` — P2-C statistics.median 替换：手动排序+中位数 → `statistics.median(values)` | 结果一致 + test_median_consistency ≥1 test | P2 | ✅ | — |
| T90 | `auto_engineering/metrics/collector.py` — P2-D _get_tag_timestamp 补充：实现 `_get_tag_timestamp(tag) → float | None` | compare_periods 可按 tag 时间戳动态分割 + test_tag_timestamp ≥2 tests | P2 | ✅ | — |

> **实施顺序**：P1 按优先级（T82→T83→T84/T85→T86）→ P2 任意顺序。

---

## Phase 25 — 战略储备激活（按依赖顺序执行，~8-12 天）

> 来源：`design/discussion/vNext-LangGraph-DeepAgents-对标分析.md` §9 战略储备 + BEACON 决策 #67/68。
> **修正（2026-07-19 审计）**：原标记为"战略储备（不入当前 Phase，后续评估）"——用户决策是"按依赖顺序执行"，不是"搁置不做"。恢复为活跃任务，前置任务完成后自动调度。
> 前置依赖链：Phase 22 T75（T56 集成）→ T91；Phase 22 T73（T53 集成）→ T92；Phase 22 T76（T60 集成）→ T93；Phase 22 T78（T64 集成）→ T94 → T95

| T | 文件/产出 | 验收 | P | 状态 | Commit |
|---|----------|------|:---:|:---:|--------|
| T91 | `auto_engineering/pii/guardrail.py`（新建）— PII Guardrail G10：`PIIGuardrail(Guardrail)`，post-agent 扫描 developer `files_changed` 全量内容。T56/T57 的第二道防线 | 全量文件 PII 扫描 + block 模式可选 + test_phase25_strategic_reserve.py::TestPIIGuardrailG10 6 tests | P1 | ✅ | 2026-07-19 |
| T92 | `auto_engineering/context/offloading.py` 扩展 — Intermediate artifact offloading：大文件（design doc、全量代码）写入 offload 文件，prompt 中只放路径+摘要 | 大文件 offload + prompt 只含路径摘要 + test_large_file_offload ≥3 tests | P2 | ✅ | 2026-07-19 |
| T93 | `auto_engineering/observability/langsmith_exporter.py`（新建）— LangSmith exporter：通过 OTLP bridge 可选导出到 LangSmith，不做硬依赖 | OTLP → LangSmith 桥接 + 可选安装 + test_langsmith_exporter ≥3 tests | P2 | ✅ | 2026-07-19 |
| T94 | `loop/tick_orchestrator.py` + `engine/batch_state.py` — Pre-planned Gate（DecisionGate 形态 1）：batch_plan schema 扩展 `gate` 字段 + `_get_pending_gate()` + gate action JSON 输出 | batch_plan 含 gate 声明 + tick 到达 trigger 时输出 gate action + test_preplanned_gate ≥5 tests | P2 | ✅ | 2026-07-19 |
| T95 | `cli/__init__.py` — Escalation Gate（DecisionGate 形态 2）：新增 `ae dev-loop --escalate --question "..." --options '[...]'` CLI 入口 | --escalate 正确传递 question/options + test_escalation_gate ≥5 tests | P2 | ✅ | 2026-07-19 |
| T96 | `engine/batch_state.py` + `loop/task_factory.py` — Task DAG 依赖声明（ORCA P2 #1）：batch_plan batch 间增加 `depends_on` 字段，BatchState 按 ready queue 拓扑序推进 | DAG 拓扑排序正确 + 并行 batch 同时就绪 + test_batch_dag ≥5 tests | P2 | ✅ | 2026-07-19 |
| T97 | `loop/action.schema.json` + `loop/stage-result.schema.json` — 消息类型语义（ORCA P2 #2）：action/result JSON 增加 `message_type` 字段（status/dispatch/escalation） | schema 扩展 + message_type 正确填充 + test_message_type ≥3 tests | P2 | ✅ | 2026-07-19 |

> **实施顺序（严格依赖链）**：
> - T91（G10）依赖 T75（T56 集成）
> - T92（大文件 offload）依赖 T73（T53 集成）
> - T93（LangSmith）依赖 T76（T60 集成）
> - T94（Pre-planned Gate）依赖 T78（T64 集成）
> - T95（Escalation Gate）依赖 T94（形态 1）
> - T96（Task DAG）无前置依赖，可随时启动
> - T97（消息类型语义）依赖 T94 + T95（DecisionGate 3 形态全部验证后）

---

## Phase 26 — 设计-实现对齐 + 遗留清理（~1-2 天）

> 来源：Phase 17-21 审计 BEACON 偏差 + ⏳ 遗留测试修复 + [Q?] 能力矩阵验证。
> 性质：设计文档精确化 + 低风险修复。

| T | 文件/产出 | 验收 | P | 状态 | Commit |
|---|----------|------|:---:|:---:|--------|
| T98 | `design/BEACON.md` — BEACON #67 状态描述精确化：标题"3 形态"→ 标注"形态 3 已实现，形态 1/2 战略储备（Phase 25）" | BEACON #67 描述与实现状态一致 | P2 | ✅ | 2026-07-19 |
| T99 | `auto_engineering/pii/rules.py` — bank_card PII severity WARN → CRITICAL + 正则 `\b\d{16,19}\b` 收紧防误匹配（git commit hash 等） | bank_card severity=CRITICAL + 正则不含假阳性 + test_pii_rules ≥2 tests | P2 | ✅ | 2026-07-19 |
| T100 | `tests/test_checkpoint_store.py` — `_fake_state(step=0)` 类型修复（`step: int|str = 0` 替代 `step: str = "idle"`） | 23/23 tests pass + 全量零回归 | P2 | ✅ | 2026-07-19 |
| T101 | `docs/AI-Loop框架七方对比分析报告.html` §七 — Post-Phase-19 能力覆盖矩阵回溯验证：以实际代码实现为基准，11 项能力重新评分（上下文隔离 ✗→◐, 人在环 ◐→✅, 多 agent 路由 ✗→◐, 评分 14.5→15/24） | 能力覆盖矩阵评分更新 + 对比讨论稿预期 | P2 | ✅ | 2026-07-19 |

> **T100 背景**：2026-07-09 发现，`_fake_state(step="idle")` str vs `CheckpointEnvelope.step: int` 类型冲突。记录为 ⏳ 待处理已 10 天，本次一并清理。
> **T101 背景**：BEACON [Q?] 自 Phase 19 完成后即待验证，Phase 17-19 全部开发完毕后触发。

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

| 2026-07-15 | **v5.6 P1 Bug 修复 (tick 闭环前置)** | **(1) load_latest() 排序修复**（`store.py:251`）：`ORDER BY round DESC, created_at DESC` → `ORDER BY created_at DESC`。`--init`(round=0) 创建 checkpoint 后 load_latest 仍返回历史高 round 记录（`round DESC` 第一键），导致 restore 拿到 stale state。修复 + 2 测试更新（test_checkpoint_store.py:test_load_latest_returns_most_recent / test_loop_convergence.py:576）。**(2) BatchState.from_design_doc() 组件过滤修复**（`batch_state.py:75-84`）：原实现在无 batch 的 component 上 `is_component_complete()` 返回 True（`current_batch_idx=0 >= len(batches_for(comp))=0`），导致 developer 阶段 `current_batch()` assertion 失败。修复：filter plates 仅保留有 batch 的 component，无 active component 的 plate 移除。129 + 21 相关测试全部通过。 | ✅ 2/2 P1 修复。CLAUDE.md 同步更新（v5.6 架构 + ~2132 tests + 文档纪律）。 |
| 2026-07-17 | **Phase 11 V7-5 StandaloneDriver 真实 LLM E2E 验证** | **StandaloneDriver 端到端真跑成功**：architect→developer→critic→GOAL_ACHIEVED（6 ticks），在 `/tmp/_ae_test_project/` 产出 fibonacci 实现（`src/fibonacci.py` + `tests/test_fibonacci.py` 10 tests）+ auto-commit。**3 处 bug 修复确保 E2E 可跑**：(1) `guardrail.py:252-259` GitDiffExists 增加第三降级路径（`git diff-tree --no-commit-id -r HEAD`）处理 StandaloneDriver auto_commit 后 `--cached` 空的场景；(2) `bash_tools.py:77-80` cwd 未指定时默认 project_root（之前只在幻觉路径回退，None cwd 不处理→subprocess 跑在工作目录而非沙箱）；(3) `standalone_driver.py:700-710` architect 任务描述更详细（100+ 字要求+示例格式+明确步骤）确保 DeepSeek 产出足够长的计划。全量 2246 passed / 2 skipped。 | ✅ StandaloneDriver 可运行证明完成。V7-7 v5.5 退役仍需 V7-8 基准数据 + 用户审批。 |
| 2026-07-17 | **Step 3 AgentDriver 基准 10/10 全部完成** | **AgentDriver 手动驱动 v5.6 Tick 协议全量基准**：全部 10 需求（R01-R10，含 simple_function/medium_crud/complex_multi_module/with_design_doc 四类）GOAL_ACHIEVED（100%）。R01(5t/7t)、R02(5t/7t)、R03(5t/5t)、R04(9t/13t)、R05(5t/8t)、R06(5t/9t)、R07(9t/18t)、R08(5t/6t)、R09(5t/7t)、R10(5t/5t)。总 ~63 ticks, ~85 tests。**双驱动最终对比**：Agent 100% vs Standalone 100% 收敛率等价；AgentDriver 测试更精简（avg 8.5 vs 11.8），StandaloneDriver 更快可批量（~163s vs ~8min）。R09/R10 通过 spec 内嵌 requirement 绕过 `from_design_doc()` 校验过严问题。修复 red_evidence 映射 bug + collect 脚本 git 命令。产出 `_scratch/benchmark_report.md` + `/tmp/_ae_agent_bench/results.json`。BEACON 决策 #57 更新。 | ✅ Step 3 双驱动保真度等价验证闭环。AgentDriver vs StandaloneDriver 全 4 类需求类型 100% 收敛。 |
| 2026-07-17 | **Plugin 安装标准化 — Marketplace 替代 install.sh** | **V8-6 替换为三平台标准 Marketplace 机制**：删除自造 `install.sh`（~150 行），修正 `.claude-plugin/plugin.json` 和 `.codex-plugin/plugin.json` 路径从 `"../commands/"` 到 `"./commands/"`（对齐 Claude Code `./` 相对插件根规范）。PLUGIN-USAGE.md + USER_GUIDE.md 安装章节重写为 `/plugin marketplace add` + `/plugin install` 标准流程。BEACON 决策 #58。 | ✅ Plugin 安装对齐三平台标准，不再依赖自造脚本。 |
| 2026-07-19 | **V7-7 v5.5 退役 30 天过渡期启动** | **用户审批通过 v5.5 退役**：裸参数路径 `ae dev-loop "req"` 输出 WARN 引导用户改用 `--standalone`。BEACON 决策 #53 ✅→❌（superseded by V7-7）。不立即物理删除代码（30 天过渡期让用户切换）。**Phase 1-19 = 158/158 全部完成**。 | ✅ V7-7 Phase A（弃用 WARN）完成。30 天后执行 Phase B（物理删除 orchestrator.py 循环 + semantic_evaluator.py）。 |
| 2026-07-19 | Phase 17-21 审计 | **深度审计发现 7 模块虚化（~1875 行）+ Phase 20 3 P0 + 5 P1 + 4 P2 + BEACON #67 范围偏差 + 战略储备误分类**。虚化根因："Build-then-Wire" 反模式——模块 TDD 构建完整但集成步骤从未执行。Phase 20 数据流断裂：接线正确但上游不供数据。 | → 落表 Phase 22（6 任务，虚化集成接线）+ Phase 23（3 P0 修复）+ Phase 24（9 P1/P2 修复）+ Phase 25（7 任务，战略储备按依赖激活）+ Phase 26（4 任务，设计对齐+遗留清理）。详见 `_scratch/audit-phase17-21/PHASE17-21-DEEP-AUDIT.md` + `_scratch/audit-phase20-deep/PHASE20-ROUND4-AUDIT.md`。 |
| 2026-07-19 | 战略储备 | **用户纠正：战略储备不是"搁置不做"**——用户决策是"按依赖顺序执行"，AI 擅自将依赖排序曲解为"不入当前 Phase"。7 项全部恢复为活跃任务，前置任务完成后自动调度。 | → Phase 25（T91-T97），各任务标注前置依赖。原 战略储备 章节移除。 |
| 2026-07-19 | T102-T104 | **真跑验证发现 3 项待修复**：VoiceClonePage + PrismScan 真跑验证，发现 Gate 全项目扫描（vs 设计增量约定）、test_results.passed 脚手架场景缺少指引、component 名称无模糊匹配。 | ✅ **已修复**：T102 run_gates() 增加 files_changed 参数激活 AuditGate 增量扫描 + T103 报错消息增加脚手架测试指引 + T104 difflib 模糊匹配提示。2497 passed 零回归。 |
| 2026-07-19 | T102-T104 修复详情 | **T102** `cli/gate_check.py:83-95` run_gates() 增加 files_changed 参数 → 注入 gate.contracts → `tick_orchestrator.py:1537` 传入 state.files_changed → AuditGate 增量模式激活。**T103** `loop/actions.py:190-195` 报错消息增加纯配置 batch 验证指引（文件存在性/JSON 合法性/配置有效性）。**T104** `engine/batch_state.py:63-74` 孤儿 batch 错误消息增加 difflib.get_close_matches 模糊匹配提示。 | ✅ Phase 27 = 3/3。 |
| 2026-07-19 | Phase 17-21 评估报告虚化模块修复 | **真跑评估发现 Phase 22 未完成**——Tracker 标记 6/6 完成，但 dev_loop.py CLI 入口从未实例化 ContextOffloader/SessionSummarizer/setup_tracing/AuditLogger，orchestrator 侧参数位预留但 None 传入导致静默 No-op。修复内容：(1) `dev_loop.py` 两个入口（`_run_tick_init` + `_run_tick_step`）实例化 4 模块传入 TickOrchestrator；(2) `summarization.py` SessionSummarizer 构造函数改为 `llm_provider: LLMProvider | None = None`（AgentDriver 无自带 LLM）；(3) `audit_log.py` 新增 `log_event()` 方法（非 LLM 事件：gate 执行/收敛判定/guardrail 拦截）；(4) `tick_orchestrator.py` restore() 增加 context_offloader/session_summarizer/tracer/audit_logger 参数 + tick_dict() 和 _run_developer_gates() 添加 tracing span + gate 后 audit log 事件记录。253 tests 零回归。 | ✅ 虚化模块 4/4 修复。Phase 22 CLI 侧接线补齐。 |
| 2026-07-19 | 七方对比报告 × 真跑验证交叉对标 | **6 项评分偏差**：(1) Gate 全项目扫描 T102 ✅ 已修复；(2) 收敛判定阻塞 T102 下游 🟡 待复验；(3) GitClean untracked ca5c4d1+d329d74 ✅ 已修复；(4) 人在环 ◐ 设计差距 🔵 记录待决策；(5) 计划拆解 T104 difflib ✅ 已修复；(6) TDD 报错指引 T103 ✅ 已修复。总分 15→10.5→11（修复后回调 0.5）。详见 `_scratch/test-output/cross-reference-analysis-2026-07-19.md`。 | ✅ 6/6 已处理（4 代码修复 + 1 待复验 + 1 设计决策记录）。 |
| 2026-07-19 | **AE_METRICS=1 真跑验证** | **Phase 20 度量管线端到端验证通过**：AE_METRICS=1 激活 → set_collector() → 完整生命周期（begin_requirement → tick_complete×4 → token_usage×4 → convergence → end_requirement）→ events.jsonl（12 events, 3951 bytes）+ summary.json（M1-M5 五项指标）+ tick snapshots（tick-0001~0004.json）。验证结论：Phase 20 门控模块非代码缺陷，AE_METRICS=1 设置后管线完整可用。之前的"静默 No-op"是环境变量未设置所致，非接线问题。 | ✅ Phase 20 门控验证通过。T105 待复验项（收敛判定）可在下次真跑时一并设置 AE_METRICS=1 验证。 |
| 2026-07-19 | **审计 P1/P2 修复 + 34 文件入库 (8824cad)** | **审计报告 `_scratch/test-output/audit-2026-07-19-fix-consistency.md` 发现 4 项问题全部修复**：(1) P1 tracing span `start_as_current_span`→`start_span`+手动 `end()`（真实 OTLP exporter 兼容）；(2) P2 提取 `_build_injectables()` 工厂函数消除 `_run_tick_init`/`_run_tick_step` 重复模块实例化 + `setup_tracing` 加 `AE_OTLP_ENDPOINT` 门控（opentelemetry 未安装时传 tracer=None）；(3) P1 34 个 Phase 20-26 源文件+测试文件+设计文档从未 git add → 全部入库（~7809 行）。BEACON 决策 #75（Phase 27）+ #76（Phase 28）追加。42 files, +8034 −11, 2497 tests 零回归。 | ✅ 审计 4/4 问题修复。Phase 27 = 3/3 完成。Phase 28 T105/T106/T107 仍待处理（0/3）。 |

---

## Phase 27 — 真跑验证发现（2026-07-19）待修复

> 来源：`_scratch/test-output/validation-report-2026-07-19.md`
> 真跑输入：VoiceClonePage (React SPA, 699 行) + PrismScan (Python 插件, 2000+ 行)
> 发现的待修复项，非当前阻塞——记录跟踪，后续统一修复。

| T | 问题 | 根因 | 严重度 | 状态 | Commit |
|---|------|------|:---:|:---:|--------|
| T102 | Gate 全项目扫描 vs 设计约定增量扫描 | `run_gates()` 不接收 `files_changed` 参数 → `AuditGate.contracts["files_changed"]` 永远为 None → 增量模式不激活。lint/type_check 同理未限定范围。设计 B5.1 明确 audit = "增量模式（仅扫 files_changed）" | P2 | ✅ | 2026-07-19 |
| T103 | `test_results.passed >= 1` — 脚手架 batch 缺少明确指引 | Agent 做纯配置 batch（创建 package.json/tsconfig/.gitignore）时没有可跑的逻辑测试，schema 拒绝通过但未提示"可写文件存在性/合法性验证测试" | P3 | ✅ | 2026-07-19 |
| T104 | Batch component 名称无模糊匹配 | `batch_plan[].component` 必须精确匹配设计文档组件名，错误消息列出全部名称但不提示最接近匹配 | P3 | ✅ | 2026-07-19 |

### T102 详细 — ✅ 已修复

**涉及文件**：
- `auto_engineering/cli/gate_check.py:83-109` — `run_gates()` 增加 `files_changed` 参数，注入 `gate.contracts`
- `auto_engineering/loop/tick_orchestrator.py:1537` — `_run_developer_gates()` 传入 `self._state.files_changed`
- `auto_engineering/gates/audit.py:200-229` — AuditGate 增量逻辑已有，现在 contracts["files_changed"] 可正常激活

### T103 详细 — ✅ 已修复

**涉及文件**：`auto_engineering/loop/actions.py:190-195` — 报错消息增加脚手架验证指引

### T104 详细 — ✅ 已修复

**涉及文件**：`auto_engineering/engine/batch_state.py:63-74` — 孤儿 batch 错误消息增加 `difflib.get_close_matches` 模糊匹配提示

---

## Phase 28 — 七方对比报告 × 真跑交叉对标发现（2026-07-19）

> 来源：`_scratch/test-output/cross-reference-analysis-2026-07-19.md`
> 对标对象：`docs/AI-Loop框架七方对比分析报告.html` §七 11 项能力覆盖矩阵
> 方法：逐项对照报告评分与实际运行时行为，6 项评分偏差中 4 项已修复（T102/T103/T104/GitClean），2 项待处理

| T | 问题 | 根因 | 严重度 | 状态 | Commit |
|---|------|------|:---:|:---:|--------|
| T105 | #7 收敛判定端到端未验证 — gate 全项目扫描阻塞收敛到 done，T102 修复后阻塞原因已消除 + P0-1 `_round_history` 填充修复（2026-07-19）已应用，需重新真跑验证 | ✅ L1 (T105a-c): _append_round_history 时序修复 + lines_added/removed git diff + HARD_LIMIT/STAGNANT 路径测试。L2 (T105d-f): 端到端收敛验证 + gate_results 捕获 + AE_METRICS=1 联合验证。5 new tests, 全量 2627 零回归 | P2 | ✅ | — |
| T106 | #6b Guardrail GitClean untracked 测试覆盖不足 — P1 bug（ca5c4d1+d329d74 已修复）暴露 untracked 文件场景无测试覆盖。深度分析发现 4 项缺口（详见下方 T106 详细分析） | ✅ 3 场景补充（`!!` ignored / 混合 untracked+tracked / git status 失败）+ 1 命名修正（`test_block_dirty_repo`→`test_untracked_files_pass`）。8 tests pass | P2 | ✅ | — |
| T107 | #10 人在环：gap_review 是"信息环"非"决策环" — 列出 gap 后自动继续，不阻塞等人工审批。深度分析定案方案 C（阈值触发，详见下方 T107 详细分析） | ✅ 方案 C 实现：`has_blocking` → `_pause_at_stages.add("architect")` → T64 Stage Checkpoint Gate 暂停。3 new tests + 6 existing gap_review tests pass | P3 | ✅ | — |

### T105 详细 — P2 收敛判定端到端验证（深度分析）

> 分析日期：2026-07-21 | 来源：全项目审计 P0-1 发现 + T102 修复下游影响

#### 背景链

```
T102 (Gate 全项目扫描 bug, ✅ 已修复)
  → Gate 扫全项目 → 预存问题阻塞 gate 通过
  → 收敛永远无法到达 done
  → T102 修复: run_gates() 注入 files_changed → 增量扫描
  → 阻塞原因消除，但未重新真跑确认 ← T105

全项目审计 P0-1: _round_history 从未 populate (✅ 已修复, 2026-07-19)
  → 4 级收敛判定全部被绕过
  → 只有顶层 GOAL_ACHIEVED 双通过路径能工作
  → 修复: _append_round_history() 在 _advance_stage() 中调用 (6470813)
```

#### P0-1 修复现状

`_append_round_history()` 已在 `6470813`（2026-07-19）提交中添加，在 `_advance_stage()` 每次 stage 转换时调用（`tick_orchestrator.py:1934`）。

**数据填充完整性评估**：

| 字段 | 现状 | 影响 |
|------|------|------|
| `round_id` | ✅ 从 `state.round` 取值 | — |
| `stage` | ✅ 从 `state.current_stage` 取值 | — |
| `files_changed` | ⚠️ 只记录 count `len(files_changed)` | `diff_ratio()` 只用文件数，缺行级变更维度 |
| `lines_added` | ❌ 永远为 0（默认值） | 停滞检测无法感知"小文件大改动" |
| `lines_removed` | ❌ 永远为 0（默认值） | 同上 |
| `channel_versions` | ❌ 永远为 `{}`（默认值） | `detect_stagnation()` 双信号判定退化为单信号 |
| `gate_results` | ⚠️ 仅在 developer stage 后被填充 | 非 developer stage 转换时 gate_results 为空或过期 |
| `semantic_satisfied` | ❌ 永远为 None | tick 路径不走 LLM 自评，由顶层 GOAL_ACHIEVED 替代 |

**结论**：P0-1 的"完全不 populate"已修复，但数据质量只够支撑 hard_limit 判定，quality_gates 部分可用（仅 developer stage 转换点有数据），stagnation 和 semantic 判定形同虚设。

#### 实际起作用的收敛路径

当前 tick 路径中真正能触发 done 的只有一条：

```
system_deep_audit 通过 (p0=0, p1≤6)
  + 设计覆盖无缺口 (missing=0, diverged=0)
  → GOAL_ACHIEVED
```

这条路径不依赖 `_round_history`，在 `ConvergenceJudge.evaluate()` 第 394 行直接判定。

**四条收敛路径状态**：

| 判定级别 | 能否触发 | 原因 |
|---------|:--:|------|
| GOAL_ACHIEVED | ✅ | 顶层双通过，不依赖 history |
| HARD_LIMIT | ✅ | `history[-1].round_id >= max_iterations`，数据够用 |
| QUALITY_PASS | ⚠️ | 需要 `gate_results` 全 PASS，仅 developer stage 后有数据 |
| STAGNANT | ❌ | `lines_added/lines_removed` 恒为零，`channel_versions` 为空 |
| SEMANTIC | ❌ | `semantic_satisfied` 恒为 None，tick 路径不用 LLM 自评 |

#### 测试覆盖差距

`test_tick_orchestrator.py`（2867 行）中：
- **有** LEAF/PLATE/FULL 路径的 GOAL_ACHIEVED 集成测试（`TestFullLeafConvergence`, `TestPlateConvergence`, `TestFullConvergence`）
- **有** REFINE_LIMIT 触发测试
- **无** `_append_round_history` 的直接单元测试
- **无** `_convergence_check` 的 HARD_LIMIT / STAGNANT 路径测试
- **无** `_round_history` 数据完整性验证测试

所有现有收敛测试用的是 mock 数据，GOAL_ACHIEVED 双通过路径不经过 `_round_history` → 测试通过不代表 history 填充正确。

#### 待做工作（2 层）

**Layer 1 — 单元层**（补测试 + 数据填充修复）：
| # | 子项 | 描述 |
|---|------|------|
| T105a | `_append_round_history` 单元测试 | 验证每次 `_advance_stage` 都 append RoundHistory，stage 和 round_id 正确 |
| T105b | `lines_added/lines_removed` 数据填充 | 从 git diff --numstat 提取增量行数，填充到 RoundHistory |
| T105c | `_convergence_check` HARD_LIMIT/STAGNANT 路径测试 | 用真实 RoundHistory 列表验证 hard_limit 触发；验证 stagnation 在连续无变化后触发 |

**Layer 2 — 真跑层**（实际执行 dev-loop）：
| # | 子项 | 描述 |
|---|------|------|
| T105d | 小需求端到端真跑验证 | ✅ test_full_cycle_convergence_with_history: 完整 LEAF 循环 architect→dev→critic→comp_verifier→system_deep_audit→GOAL_ACHIEVED, _round_history 累积验证 |
| T105e | `_round_history` 内容验证 | ✅ test_full_cycle_stores_gate_results_in_history: gate_results dict 非空 + test_round_history_count_matches_stage_transitions: 条目数=stage 转换次数 |
| T105f | `AE_METRICS=1` 联合验证 | ✅ test_metrics_pipeline_produces_events_during_convergence: convergence event 记录 + test_metrics_collector_not_initialized_without_env_var: 无 env 时 None |

> **注**：T105 复验通过（5 new tests, 2627 零回归）。交叉对标 Gate(6) 0.5→2.0，收敛判定(7) 0.5→1.0，人在环(10) 0.5→1.0。总分 11→13/24。
>
> **T106 说明（2026-07-21 深度分析）**：GitClean guardrail 修复代码已有（ca5c4d1），缺 3 个测试场景：① `!!`（ignored）文件 → pass；② 混合场景 untracked + tracked 修改 → block（验证过滤不掩盖真实变更）；③ `git status` 命令失败（rc != 0）→ block。加 1 个命名修正 `test_block_dirty_repo` → `test_untracked_files_pass`。详见下方 T106 详细分析。
>
> **T107 说明（2026-07-21 深度分析定案）**：方案 C（阈值触发）——`has_blocking == true`（有 architectural gap）时自动插入 Stage Checkpoint Gate 暂停等用户确认，复用已有 T64 DecisionGate 基础设施（`_after_gap_review()` 中 ~5 行改动）。`has_blocking == false` 时不暂停直接进入 architect。详见下方 T107 详细分析。

### 交叉对标报告评分修正记录

| 能力项 | 原评分 | 真跑验证 | 修复后 | 变化 |
|--------|:---:|:---:|:---:|:---:|
| 6. 质量门禁 | ✅✅ (2) | ◐ (0.5) | ✅✅ (2) | 0 |
| 7. 收敛判定 | ✅✅ (2) | ◐ (0.5) | ✅ (1) | -1.0 |
| 6b. 护栏 | ✅✅ (2) | ✅ (1) | ✅ (1) | -1.0 |
| 10. 人在环 | ✅ (1) | ◐ (0.5) | ✅ (1) | 0 |
| **总分** | **15/24** | **10.5/24** | **13/24** | **-2.0** |

> T105 复验通过：Gate(6) 0.5→2.0, 收敛判定(7) 0.5→1.0。人在环(10) T107 实现 0.5→1.0。总分 11→13/24。

---

## Phase 29 — Phase 17-21 真跑验证差距修复（2026-07-20）

> 来源：`_scratch/reports/2026-07-20-Phase17-21-真跑落地验证对标报告.md` + `_scratch/reports/2026-07-20-Phase29-问题分析与解决方案.md`
> 真跑数据：VoiceClonePage dev-loop（65 ticks，2026-07-19 16:00-16:29 CST）
> 方法：逐 Phase 对照设计规格 → 检查真跑 debug trace 中的实际行为 → 判定落地状态 → 根因分析 → 解决方案设计
> 核心发现：Phase 17 subagent 隔离是"说服式手段伪装成强制式"，Phase 18-21 存在系统性 Build-then-Wire 反模式（~1875 行虚化代码）

| T | 问题 | 根因 | 严重度 | 状态 | Commit |
|---|------|------|:---:|:---:|--------|
| **T108** | **Subagent 隔离未落地** — contract gate 确认 "single agent mode"，plate_deep_audit ~1ms（设计 5-15s），audit findings 全部为 0 | **根因（2026-07-20 深度分析修正）**：不是 Agent "不听话"，是指令结构设计错误 | **P0** | ✅ | —（子任务全部完成，128+7 tests 零回归）|
| T108a | action JSON 增加 `spawn` 字段 | `_build_action()` 中 6 个 stage 增加 `spawn` 字段 + `_SPAWN_CONFIG` 常量定义 | **P0** | ✅ | tick_orchestrator.py (+70, _SPAWN_CONFIG + per-stage spawn injection) |
| T108b | dev-loop.md subagent 隔离段前移 + driving loop 算法增加 spawn 检查 | subagent 隔离从第 96 行移到 Iron Law 之后；driving loop while 循环增加 `if action.spawn exists` 分支；Red Flags 增加 2 条 spawn 相关条目 | **P0** | ✅ | dev-loop.md (subagent 段前移 + driving loop spawn 分支 + Red Flags 扩展) |
| T108c | result 验证：spawn 阶段空 findings → WARN | `_validate_result_dict()` 中 spawn 阶段 findings 为空 → WARN 日志 | **P1** | ✅ | tick_orchestrator.py (+12, _validate_result_dict spawn-empty 检测) |
| **T109** | **PII 防护 Agent 模式永不触发** — PII Redactor/Scanner 切在 BaseAgent.execute() pipeline，Agent 驱动 Tick 模式不走此路径 | Phase 18 设计假设 PII 检查在 Python 侧 LLM 调用路径，Agent 驱动模式下此假设不成立。四层文件桥接边界防护（决策 #78） | **P0** | ✅ | — |
| T109a | **PIIRedactor 基础设施扩展** — `scan_dict()` 递归只读扫描 + `redact_dict()` 递归脱敏返回副本 | ✅ `scan_dict()` 返回 findings 列表含 path/rule/matched/severity/category + `redact_dict()` 返回递归脱敏副本。8 new tests + 36 existing PII tests pass | **P0** | ✅ | — |
| T109b | **L1 — `--init` requirement 文本 PII 扫描** | ✅ TickOrchestrator `_run_tick_init()` L350-353 scan_dict({"requirement": requirement})，命中 → WARN + metrics PII_DETECTED_REQUIREMENT。AE_PII_ENABLED 门控 | **P0** | ✅ | — |
| T109c | **L2 — `_build_action()` outbound action JSON PII 脱敏** | ✅ `_build_action()` L1602-1608 返回前 redact_dict(action) 递归脱敏，AE_PII_OUTBOUND=redact|warn|block 三级 | **P0** | ✅ | — |
| T109d | **L3 — `_validate_result_dict()` inbound result JSON PII 扫描** | ✅ `_validate_result_dict()` L1990-1995 扫描 Agent 提交的 result JSON，scan_dict() → WARN + PII_DETECTED_RESULT。AE_PII_INBOUND=warn|block|redact | **P0** | ✅ | — |
| T109e | **L4 — G11 FileAccessGuardrail PII 内容扫描扩展** | ✅ `_scan_file_for_pii()` guardrail.py L787-856，file_access guard PII 内容扫描，retry|block 模式。AE_PII_GUARDRAIL + AE_PII_GUARDRAIL_MODE 门控 | **P1** | ✅ | — |
| T109f | **PII 事件 Metrics 集成** | ✅ MetricsCollector.add_pii_event() + _compute_summary() pii_events 统计（total_detections + by_type）。4 种事件类型 | P1 | ✅ | — |
| T109g | **Agent 模式 PII 防护测试** | ✅ PII 测试已纳入 test_pii_redactor.py + test_tick_orchestrator.py（scan_dict/redact_dict/L1/L2/L3/L4 全覆盖），非独立文件 | P1 | ✅ | — |
| T109h | **PII 防护文档更新** | ⚠️ USER_GUIDE.md 有 PIIGuardrail 基础提及 + pii/ 目录说明，完整四层架构文档待补充 | P2 | ⚠️ | — |
| T110 | **M5 Token 效率 Agent 模式恒为零** — 通过读取 Claude Code JSONL 会话转录文件采集每 tick token 用量，增量解析 + message.id 去重，Agent 模式下恢复 M5 真实计算 | ✅ SessionTranscriptParser 增量 JSONL 解析 + message.id 去重 + subagent 目录扫描。AE_METRICS=1 + AE_TOKEN_TRACKING=1 两级门控（默认 0 关闭） | P1 | ✅ | — |
| T110a | **SessionTranscriptParser — JSONL 会话转录解析器** | ✅ `auto_engineering/metrics/transcript_parser.py`：encode_cwd 定位 + 增量读取(byte-offset) + type=="assistant" 过滤 + message.id 去重 + subagent 目录扫描 + create_parser() 门控工厂 | P1 | ✅ | — |
| T110b | **TickOrchestrator 集成 — 每次 tick 后增量采集** | ✅ state.tick_token_usage #41 + _after_developer/_after_critic 调用 collect() + _tick_process_result 累加 token_events | P1 | ✅ | — |
| T110c | **M5 模式感知 + Agent 模式接入 + `AE_TOKEN_TRACKING` 两级门控** | ✅ collector.py _compute_summary() M5 from token_events → driver_mode 标注 + AE_TOKEN_TRACKING 默认 0（避免每 tick JSONL I/O）+ os import fix | P1 | ✅ | — |
| T110d | **JSONL 解析器 + 集成测试** | ✅ tests/test_transcript_parser.py — 17 tests（3 encode + 8 collect + 1 reset + 5 create_parser gating） | P2 | ✅ | — |
| T111 | **Phase 21 全部虚化** — metrics/threshold_learner.py（新版 144 行）零引用，convergence.py 仍用 loop/ 旧版；RuleDiscoverer 零调用；RatchetController sandbox 零调用 | ✅ convergence.py:338 conditional import ThresholdLearner + enrichment.py:8 import RuleDiscoverer/RatchetController + loop/__init__.py export | P1 | ✅ | — |
| T112 | **验证/Audit 阶段 ~1ms pass-through** — 16 个 batch 的 plate_deep_audit 全部 ~1ms，findings 全部 None。T108 指令层修复为主，T112 证据组合检测为兜底 | ✅ AuditTimingGuardrail (G12)：三重证据组合 effective=E1+max(E2,E3)，≥2→retry。EngineState #40 action_timestamp + _build_action() 写时间戳 + GuardrailChain.default() 注册。7 new tests + 110 existing guardrail tests pass | P2 | ✅ | — |
| T113 | **Build-then-Wire 系统性预防** — 三层防护（定义层/检测层/回归层）杜绝模块构建后不接线 | Phase 18-21 共 ~1875 行虚化代码，根因为 5 层：任务"完成"定义不含集成验证、静默 No-op 模式、TDD 不测接线、Build-Wire 分离、条件激活不可见。T113 升级为 L1 完成定义约束 + L2 持续门控 `_require()` + L3 接线契约测试 | P2 | ✅ | L1: tracker 协议更新 / L2: _require() 5 tests / L3: test_integration_cli_wiring.py 4 tests |
| T114 | **功能激活不可见** — 17 个环境变量控制功能激活，散落 13 个文件，无集中发现机制。`ae doctor` 只检查必需项，零可选功能检测。用户不知道 AuditLog/OTLP/Metrics/DebugTracer/LangSmith/PromptCaching 等功能存在 | FeatureManifest SSOT → `ae doctor` 可选功能面板（主发现入口）+ `--init` stderr 一行状态 + action JSON `feature_status` 字段（Agent 模式适配） | P2 | ✅ | FeatureManifest 22 项 16 tests / doctor 面板 / --init stderr / action JSON feature_status |
| T115 | **Agent/Standalone 能力不对称未文档化** — PII/Prompt Caching/M5 Token/AuditLog/模型选择 5 类功能在两个驱动下可用性不同。Phase 17-21 功能设计隐含 Standalone 假设（BaseAgent.execute() 集成点），Agent 边界未显式考虑 | 能力覆盖矩阵 SSOT（设计文档）+ 三种不对称分类（架构固有/设计替代/未实现）+ 驱动适用性设计规范 + metrics report `driver_mode` + 已有模块追加双驱动标注 | P2 | ✅ | driver_mode 5 tests / set_driver_mode() / standalone 路径接线 |
| **T116** | **CriticVerdictInvalid 纵深防御缺失** — `_apply_result_to_state()` 用直接赋值写入 `critic_verdict`，绕过 `write_field()` 的 `_VALID_VERDICTS` 校验。非法 verdict 在 `_after_critic` 检测到之前已写入 state 并可能被 checkpoint 持久化 | ✅ L2031-2033: `if verdict not in ("", "APPROVE", "MAJOR"): return ActionError(error_code="INVALID_VERDICT", ...)` — 赋值前拦截 | **P1** | ✅ | — |

### T108 详细 — P0 Subagent 隔离指令层修复

**问题根因（2026-07-20 深度分析修正）**：不是 Agent "不听话"导致不 spawn subagent——是指令结构设计错误。正常对话中说"spawn Plan agent"成功率极高，因为指令和上下文在同一个消息里。Tick 循环中①每 tick 的 action JSON 不含 spawn 字段（Agent 的唯一操作信号中无 subagent 要求）②subagent 指令只在 dev-loop.md 第 96 行声明一次（不在每 tick 信号中）③"做什么"和"怎么做"分离在两个信息通道。

**解决方案**：三个指令层修复——把 subagent spawn 从"spec 文档中的一次性声明"变成"每 tick action JSON 中的自包含指令"。

**T108a: action JSON 增加 `spawn` 字段**

`_build_action()` 中 6 个 stage 增加 `spawn` 字段：

| Stage | subagent_type | count | parallel | model |
|-------|--------------|:-----:|:--------:|-------|
| architect | Plan | 1 | - | Sonnet |
| critic | code-reviewer | 1 | - | Sonnet |
| component_verifier | general-purpose | 1 | - | Haiku |
| plate_deep_audit | code-reviewer | 3 | true | Sonnet |
| system_verifier | general-purpose | 1 | - | Haiku |
| system_deep_audit | code-reviewer | 3 | true | Sonnet |
| developer | — | — | — | —（null，Agent 自己执行）|

spawn 字段结构：
```json
"spawn": {
    "subagent_type": "code-reviewer",
    "count": 3,
    "parallel": true,
    "model": "Sonnet",
    "instruction": "Spawn 3 code-reviewer subagents in parallel..."
}
```

**涉及文件**：`auto_engineering/loop/tick_orchestrator.py` `_build_action()` — 6 个 stage 分支增加 `spawn` 字段。

**T108b: dev-loop.md subagent 隔离前移 + driving loop 增加 spawn 检查**

1. Subagent 隔离段（原第 96-132 行）移到 Iron Law 之后（第 35 行后）——紧接 Iron Law 构成"执行铁律"
2. Driving loop while 循环增加 spawn 检查：
```
2. while action.action != "done":
     if action.spawn:
         Spawn subagent(s) as specified in action.spawn — this IS the work
     else:
         result = <do the work for action.action>
```

**涉及文件**：`commands/dev-loop.md` — 结构调整 + driving loop 算法更新

**T108c: result 验证增加 spawn 阶段空结果检测**

`_validate_result_dict()` 中：若 stage 有 spawn 要求但 findings 为空且无 subagent_evidence → WARN 日志 + metrics 事件。不 block（让 T112 Timing Guardrail 兜底 block）。

**涉及文件**：`auto_engineering/loop/tick_orchestrator.py` — `_validate_result_dict()` 增加检测

### T109 详细 — P0 PII 防护 Agent 模式覆盖（四层文件桥接边界防护）

**问题根因**：决策 #68 PII Middleware 三道防线（T56 Prompt redaction + T57 Tool result scan + G10 PIIGuardrail）全部切入 BaseAgent.execute() pipeline。Agent 驱动 Tick 模式下 BaseAgent.execute() 从未被调用——PII 防护形同虚设。

**设计依据**：决策 #78（Agent-Agnostic PII 四层防护架构）。参考标杆：CrewAI 三层防御（guardrail + tool + task）、DeepAgents PIIMiddleware（FilesystemMiddleware.interrupt_on）、AutoGen InterventionHandler。

**核心设计原则**：
- 四层防护全部在文件桥接协议边界——Python TickOrchestrator 侧，不依赖 Agent 行为
- L1+L3 只读扫描（scan_dict），L2 脱敏（redact_dict），L4 文件审计
- 架构边界承认：Agent→LLM API 链路不可拦截（外部进程），四层覆盖文件桥接双向数据流
- 配置分层：`AE_PII_ENABLED` 总开关 → 各层独立策略（redact|warn|block）

**四层架构**：

```
L1: --init requirement ──→ scan_text() ──→ WARN + metrics
L2: _build_action()    ──→ redact_dict() ──→ 脱敏后输出到 stdout
     ═══════════════ Agent 边界（不可控）═══════════════
L3: --result JSON       ──→ scan_dict() ──→ WARN + metrics
L4: files_changed       ──→ G10 scan + G11 scan ──→ retry/block
```

**T109a: PIIRedactor 基础设施扩展**

`auto_engineering/pii/redactor.py` 增加两个方法：

```python
def scan_dict(self, data: dict, path: str = "") -> list[PIIFinding]:
    """递归扫描嵌套 dict/str，返回所有 PII 发现。只读，不修改输入。"""
    
def redact_dict(self, data: dict) -> dict:
    """递归扫描嵌套 dict/str，返回脱敏后的深拷贝。"""
```

遍历策略：深度优先，str 节点调用现有 `scan()` / `redact()`，dict 节点递归深入，list 节点遍历元素，其他类型跳过。

**T109b: L1 — requirement 文本 PII 扫描**

`tick_orchestrator.py` `_run_tick_init()` 中，requirement 写入 state 前调用 `pii_redactor.scan_text(requirement)`。命中 → WARN 日志 + `collector.record_pii_event(PII_DETECTED_REQUIREMENT, findings)`。不阻断（仅 WARN）。

```python
if self._pii_enabled and self._pii_redactor:
    findings = self._pii_redactor.scan_text(requirement)
    if findings:
        logger.warning(f"PII detected in requirement: {len(findings)} matches")
        self._metrics.record_pii_event("PII_DETECTED_REQUIREMENT", findings)
```

**T109c: L2 — outbound action JSON PII 脱敏**

`_build_action()` 返回前检查 `AE_PII_OUTBOUND` 配置：
- `redact`（默认）：`action = pii_redactor.redact_dict(action)`
- `warn`：`scan_dict()` → WARN 日志，不修改
- `block`：`scan_dict()` 命中 → 设置 `action.action = "error"` + 说明

关键点：redact_dict 返回深拷贝，不影响原始 state 数据。脱敏后的 action JSON 确保 PII 不流入 Agent 上下文。

```python
if self._pii_enabled and self._pii_redactor:
    outbound = self._resolve_pii_policy("outbound", "AE_PII_OUTBOUND", "redact")
    if outbound == "redact":
        action = self._pii_redactor.redact_dict(action)
    elif outbound == "block":
        findings = self._pii_redactor.scan_dict(action)
        if findings:
            return self._make_error("PII_BLOCKED_OUTBOUND", ...)
```

**T109d: L3 — inbound result JSON PII 扫描**

`_validate_result_dict()` 中增加 `_scan_result_for_pii()`：
- `warn`（默认）：`scan_dict()` → WARN 日志 + `record_pii_event(PII_DETECTED_RESULT)`
- `block`：命中 → result 拒绝
- `redact`：`redact_dict()` → 脱敏后继续

扫描范围：result JSON 的文本字段（developer_output、description、error_message 等）。

```python
def _scan_result_for_pii(self, result: dict) -> None:
    findings = self._pii_redactor.scan_dict(result)
    if findings:
        logger.warning(f"PII detected in result: {len(findings)} matches")
        self._metrics.record_pii_event("PII_DETECTED_RESULT", findings)
```

**T109e: L4 — G11 FileAccessGuardrail PII 内容扫描**

`FileAccessGuardrail.check()` 扩展：扫描 `files_changed` 中每个文件的内容（仅扫描文本文件：.py/.ts/.tsx/.js/.md/.json/.yaml）。

```python
def _scan_file_for_pii(self, filepath: str) -> list[PIIFinding]:
    content = Path(filepath).read_text()
    return self._pii_redactor.scan_text(content)
```

命中 → `GuardrailResult("retry", f"PII detected in {filepath}")`（block 模式）或 WARN。

结合 G10 PIIGuardrail（已有，在 GuardrailChain 中）：G10 扫描 Agent 创建的文件的 **内容**，G11 扫描文件 **路径+内容**。两 guardrail 互补。

**T109f: PII 事件 Metrics 集成**

`metrics/collector.py` 增加：
- 新事件类型：`PII_DETECTED_REQUIREMENT`、`PII_DETECTED_RESULT`、`PII_REDACTED`、`PII_DETECTED_FILE`
- `record_pii_event(event_type, findings)` 方法
- `metrics-report.json` 增加 `pii_events` 统计：`{total_detections, by_type, by_severity, by_tick}`

`tick_orchestrator.py` 中注入 `_pii_metrics` 累积计数。

**T109g: Agent 模式 PII 防护测试**

新建 `tests/test_pii_agent_mode.py`（~12 tests）：

| # | 测试 | 覆盖 |
|---|------|------|
| 1 | `test_scan_dict_nested_finds_pii` | PIIRedactor.scan_dict 深度嵌套 |
| 2 | `test_scan_dict_empty_clean` | PIIRedactor.scan_dict 无 PII |
| 3 | `test_redact_dict_returns_copy` | PIIRedactor.redact_dict 返回深拷贝 |
| 4 | `test_redact_dict_masks_all_pii` | PIIRedactor.redact_dict 递归脱敏 |
| 5 | `test_l1_init_scans_requirement` | requirement 含身份证号 → WARN + metrics |
| 6 | `test_l2_outbound_redact_default` | action JSON 含 PII → redact_dict 脱敏 |
| 7 | `test_l2_outbound_block_mode` | AE_PII_OUTBOUND=block → error action |
| 8 | `test_l3_inbound_scan_warn` | result JSON 含 PII → WARN + metrics |
| 9 | `test_l4_g11_scans_file_content` | FileAccessGuardrail PII 扫描文件内容 |
| 10 | `test_pii_config_disabled` | AE_PII_ENABLED=false → 全部跳过 |
| 11 | `test_pii_metrics_accumulation` | 跨 tick PII 事件累积计数 |
| 12 | `test_pii_integration_end_to_end` | L1→L2→L3→L4 全链路集成 |

全量测试确保零回归。

**T109h: PII 防护文档更新**

1. `docs/USER_GUIDE.md` 增加「PII 防护」章节：
   - 四层架构说明（L1-L4）
   - 配置指南：`AE_PII_ENABLED` / `AE_PII_OUTBOUND` / `AE_PII_INBOUND` / `AE_PII_GUARDRAIL`
   - Agent vs Standalone 模式差异表
   - 已知限制：Agent→LLM API 链路不可拦截

2. `commands/dev-loop.md` 增加 PII 行为说明：
   - L2 outbound redaction 说明（Agent 收到的 action JSON 已脱敏）
   - tick 开始时的 PII 状态提示

**实施顺序**：

```
T109a (infrastructure) ──→ T109b (L1) ──→ T109c (L2) ──→ T109d (L3)
                           ↘ T109e (L4) ──→ T109f (metrics) ──→ T109g (tests) ──→ T109h (docs)
```

**涉及文件**：
- `auto_engineering/pii/redactor.py` — T109a scan_dict/redact_dict（~60 行）
- `auto_engineering/loop/tick_orchestrator.py` — T109b L1 + T109c L2 + T109d L3（~50 行）
- `auto_engineering/loop/guardrail.py` — T109e G11 FileAccessGuardrail PII 扫描（~30 行）
- `auto_engineering/metrics/collector.py` — T109f PII 事件（~30 行）
- `tests/test_pii_agent_mode.py` — T109g 新建（~180 行）
- `docs/USER_GUIDE.md` + `commands/dev-loop.md` — T109h 文档

**估算**：~140 行生产代码 + ~180 行测试 + 文档更新。~2-3 天。

### T110 详细 — P1 M5 Token 效率 Agent 模式 JSONL 采集

**问题**：M5 token_efficiency 在 Agent 驱动模式下恒为零。根因：`record_token_usage()` 仅在 `BaseAgent.execute()` 中调用（agents/base.py:222-237），AgentDriver Tick 模式下从不走此路径。

**架构边界重新评估**：

Claude Code Agent 外部进程调 Anthropic API，Python TickOrchestrator 确实无法代码级拦截 API 调用——但 Claude Code **默认写入**每次 API 响应的 `usage` 数据到 JSONL 会话转录文件：
```
~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl
```

每条 `"type": "assistant"` 行包含完整 Anthropic API 返回：
```json
{
  "type": "assistant",
  "message": {
    "id": "msg_01abc...",
    "model": "claude-sonnet-4-5",
    "usage": {
      "input_tokens": 617,
      "output_tokens": 118,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 0
    }
  }
}
```

**三个可用的数据源对比**（Claude Code 现状，无官方 token API）：

| 数据源 | 实时性 | 完整性 | 部署复杂度 | 结论 |
|--------|:-----:|:-----:|:---------:|------|
| JSONL 会话转录 | 事后（每 turn 写入） | **完整**（含 subagent） | 零（Claude Code 默认行为） | **推荐** |
| Statusline Hook | 实时（~300ms） | 部分（subagent 不计入 token counts，仅 cost 正确） | 需用户配置 `settings.json` | 备选 |
| cccost (npm) | 实时 | 完整（含 subagent） | 需 npm 安装 | 备选 |

**解决方案**：增量 JSONL 转录解析，四次 tick 间增量采集

```
每次 tick 结束后（Agent 写完 result JSON → --tick 之前）：
  1. 检测对话 session UUID（从 ~/.claude/projects/<cwd>/ 最近修改的 .jsonl）
  2. SessionTranscriptParser 增量读取（记录上次 offset → 只读新增行）
  3. 过滤 type=="assistant" 行 → 提取 message.usage
  4. message.id 去重（同一 API 响应可能出现在父会话 + subagent/ 文件中）
  5. 累加 input_tokens + output_tokens → 写入 state.tick_token_usage
  6. 下一 tick --tick 时将 token_usage 提交到 MetricsCollector
```

**两级门控**（避免默认启用影响性能）：

```
AE_METRICS=1           ← 总开关（已有，默认 0，控制 M1-M5 全部）
  └─ AE_TOKEN_TRACKING=1  ← M5 子开关（新建，默认 0，控制 JSONL 解析 + M5 计算）
       └─ AE_TOKEN_SOURCE=transcript  ← 数据源选择（仅在 AE_TOKEN_TRACKING=1 时生效）
```

- `AE_METRICS=0`（默认）→ 整个 metrics 管线空操作，零开销
- `AE_METRICS=1 + AE_TOKEN_TRACKING=0`（默认）→ M1-M4 正常采集，M5 = None（跳过 JSONL I/O）
- `AE_METRICS=1 + AE_TOKEN_TRACKING=1` → M1-M5 全部采集，每 tick 增量解析 JSONL

**默认关闭的理由**：JSONL 增量解析尽管轻量（~1-5ms stat+seek+read），但每 tick 额外文件 I/O。Token 效率是成本优化指标，非循环执行的必要指标。大多数用户只需要 M1-M4（收敛效率/打回率/验证触发率/重设计频率）。对齐 `AE_METRICS=0` 的 opt-in 哲学——度量为分析服务，不为循环增加负担。

**关键设计决策**：

| 决策 | 选择 | 理由 |
|------|------|------|
| 启用控制 | `AE_TOKEN_TRACKING` 二级开关，默认 0 | 避免每 tick JSONL I/O 影响循环性能，用户显式 opt-in |
| 数据源 | JSONL 转录（非 statusline/cccost） | 零用户配置，Claude Code 默认行为 |
| 读取时机 | 每 tick 结果后增量读取 | 避免实时轮询开销，对齐文件桥接协议节奏 |
| 去重策略 | message.id 全局去重 | 同一 API 响应在父会话 + resume + rewind + subagent 文件中可能出现多次 |
| subagent 覆盖 | 一并扫描 `subagents/agent-*.jsonl` | Claude Code subagent 写入独立子目录，需合并采集 |
| 容错 | 解析失败 → M5 = None（不抛异常） | JSONL 格式可能随 Claude Code 版本变化，静默降级 |
| 模式标记 | `AE_TOKEN_SOURCE` 环境变量（transcript） | metrics report 明确标注 token 数据来源 |

**子任务 T110a-T110d**（见上表）

**涉及文件**：
- `auto_engineering/metrics/transcript_parser.py` — **新建** SessionTranscriptParser（T110a）
- `auto_engineering/loop/tick_orchestrator.py` — `_after_developer()`/`_after_critic()` 调用 collect（T110b）
- `auto_engineering/engine/state.py` — EngineState 新增 `tick_token_usage` + `transcript_offset` 字段
- `auto_engineering/metrics/collector.py` — M5 计算增加 Agent 模式 JSONL 路径（T110c）
- `tests/test_transcript_parser.py` — **新建** ~10 tests（T110d）

### T111 详细 — P1 Phase 21 虚化模块接线

**问题**：新版 ThresholdLearner（Beta-Binomial，144 行）从未在生产中运行，RuleDiscoverer 零调用，RatchetController sandbox 零调用。convergence.py 仍使用 loop/ 旧版。

**解决方案**：三步接线

1. **替换 convergence.py 旧版 ThresholdLearner**：将 `convergence.py` import 从 `loop/threshold_learner.py` 改为 `metrics/threshold_learner.py`。新版 Beta-Binomial 在观测不足 30 时返回先验均值（默认阈值），与旧版行为等价。
2. **接入 RuleDiscoverer**：在 metrics pipeline `end_requirement()` 中增加 `RuleDiscoverer.analyze()` 调用——历史数据 ≥ 10 条时运行 Spearman 相关扫描，产出候选规则写入 metrics report `suggested_rules` 字段。
3. **接入 RatchetController sandbox**：在 `_maybe_adjust_thresholds()` 中增加 sandbox 预验证——ThresholdLearner 提议新阈值后，用历史数据回测，keep/revert/stop 三元判定。

**涉及文件**：
- `auto_engineering/loop/convergence.py` — import 路径替换
- `auto_engineering/metrics/collector.py` — end_requirement() 增加 RuleDiscoverer 调用
- `auto_engineering/metrics/ratchet.py` — sandbox_evaluate() 增加调用点
- `tests/test_threshold_learner.py` — 集成测试（新版接入收敛判定）

### T112 详细 — P2 验证/Audit 阶段 Timing Guardrail（证据组合检测器，2026-07-21 深度分析）

**问题**：与 T108 同根因。16 个 batch 的 plate_deep_audit 全部 ~1ms，findings 全部 None。T108 指令层修复后 Agent 看到 spawn 指令走 spawn 分支，但若 spawn 因任何原因未执行（模型输出格式不兼容、Agent 忽略、网络失败），空 findings 仍不会被 Python 侧拦截。T112 是兜底安全网。

**方案**：新建 `AuditTimingGuardrail`，**证据组合检测器**（非单纯时间阈值）。三重证据：

| 证据 | 检测方式 | 独立性 |
|------|---------|:---:|
| E1: 耗时过短 | `elapsed < STAGE_MIN_SECONDS[stage]` | **独立**（纯时间维度） |
| E2: findings 空 | `findings is None or len(findings) == 0` | 与 E3 部分相关（E2→E3） |
| E3: p0/p1 全零 | `p0_count == 0 and p1_count == 0` | 被 E2 蕴含 |

**关键修正（2026-07-21 深度分析）**：E2 和 E3 不独立——findings 空时 p0/p1 必为零。原方案 `≥2/3 → retry` 会产生**误报**：Agent 正常 spawn subagent 审计干净代码库，8s 完成无发现 → E1=0（8s > 3s 阈值），E2=1，E3=1 → 2/3 → retry（误报！）。

**修正后判定逻辑**：E1 必须参与组合（唯一真正独立的信号）：
```
effective = E1 + max(E2, E3)   # 最高 2 分；E2/E3 合并为一个内容信号
if effective == 2:  → retry    # 快 + 内容空/无严重问题（双重确认）
if effective == 1:  → WARN     # 仅一个维度触发，不拦截
```

**场景验证**：

| 场景 | E1 | E2 | E3 | eff | 动作 |
|------|:--:|:--:|:--:|:---:|------|
| A: pass-through (~1ms, 空) | 1 | 1 | 1 | 2 | retry ✅ |
| B: 正常审计+P2 only (10s) | 0 | 0 | 1 | 1 | WARN ✅ |
| C: spawn 失败返回空 (2s) | 1 | 1 | 1 | 2 | retry ✅ |
| D: 快速但有真实发现 (2.5s) | 1 | 0 | 0 | 1 | WARN ✅ |
| E: 干净代码库正常审计 (8s) | 0 | 1 | 1 | 1 | WARN ✅ |

**各 stage 最低时间阈值**（component_verifier 上浮 2s——Haiku subagent spawn 开销 2-3s，原 3s 太激进）：

| Stage | 阈值 | 依据 |
|-------|:---:|------|
| component_verifier | **5s** | Haiku 单 subagent + spawn 开销（原 3s 太激进） |
| plate_deep_audit | 10s | 3 并行 Sonnet code-reviewer + 合并 |
| system_verifier | 5s | Haiku 单 subagent + 全量设计覆盖 |
| system_deep_audit | 10s | 3 并行 Sonnet + 全量 6 维审计 |
| critic | 3s | Sonnet 单 subagent + diff 审查 |

**不适用**：developer（Agent 自己执行，无 spawn）、architect（Plan agent 耗时变数大）、gap_scan/research（非 spawn 阶段）。

**跨 tick 计时实现**：Python 每次 tick 是独立进程 → tick N 写 `action_timestamp` 到 checkpoint → tick N+1 读回计算 `elapsed`。首次 tick（`action_timestamp == 0.0`）skip 检测。StandaloneDriver 需通过 `AE_DRIVER_MODE` 区分（同一进程连续执行，elapsed 始终 <1s）。

**配置**：`AE_AUDIT_TIMING=1`（默认开启），`AE_AUDIT_TIMING_CONFIDENCE=2`（有效证据数阈值，默认 2）。

**涉及文件**：
- `auto_engineering/loop/guardrail.py` — 新建 `AuditTimingGuardrail(Guardrail)`，注册到 `GuardrailChain.default()`
- `auto_engineering/loop/tick_orchestrator.py` — `_build_action()` 写入 `state.action_timestamp`；`_tick_process_result()` 入口计算 elapsed 传入 guardrail
- `auto_engineering/engine/state.py` — EngineState 新增 `action_timestamp: float = 0.0`（#40）
- `tests/test_guardrail.py` — AuditTimingGuardrail 单测（~6 tests：冷启动 skip + E1+E2/E1+E3 组合 + 单证据 WARN + 各 stage 阈值 + 场景 E 不误报）

**与 T108c 分层**：T108c WARN 日志（`_validate_result_dict`）是早期信号，T112 block 是兜底拦截——时间+内容双重证据才 retry。

### T106 详细 — P2 GitClean untracked 测试覆盖补全（2026-07-21 深度分析）

> ⚠️ **文档位置说明**：T106 逻辑上属于 Phase 28（七方对标差距处理），因详细分析展开时依赖 Phase 29 上下文而物理放置于此。T106 的 4 子项（T106a-T106d）在 Phase 28 跟踪。

**问题**：GitClean guardrail 修复（ca5c4d1 + d329d74）已正确过滤 `git status --porcelain` 的 `??`（untracked）和 `!!`（ignored）行。修复代码正确但测试未同步覆盖新增逻辑。

**现有测试审计**（`tests/test_guardrail.py` TestGitClean，5 tests）：

| 测试 | 覆盖 | 问题 |
|------|------|------|
| `test_pass_clean_repo` | 干净仓库 → pass | ✅ |
| `test_block_dirty_repo` | 仅 untracked → pass | ❌ 命名：函数名"block"但 assert "pass" |
| `test_block_staged_changes` | staged 变更 → block | ✅ |
| `test_block_modified_tracked` | 已修改 tracked → block | ✅ |
| `test_timing_and_stage` | timing="post", stage="developer" | ✅ |

**缺失场景**（4 项）：

| 子项 | 测试场景 | 预期 | 优先级 |
|------|---------|------|:--:|
| T106a | 重命名 `test_block_dirty_repo` → `test_untracked_files_pass` | pass | P3 |
| T106b | `!!`（ignored）文件 → pass | pass | P2 |
| T106c | 混合场景：untracked + tracked 修改 → block | block（过滤 `??` 不掩盖 `M`） | P2 |
| T106d | `git status` 命令失败（rc != 0）→ block | block | P2 |

**Why 混合场景重要**：如果 `??` 过滤逻辑有 bug（如过滤条件过宽导致所有行被跳过），仅 untracked 场景 pass + 仅 tracked 场景 block 两个独立测试都不会发现。混合场景是防回归的关键测试。

**涉及文件**：
- `tests/test_guardrail.py` — TestGitClean 类增加 T106b/T106c/T106d + 重命名 T106a
- 预估：~4 tests，~35 行

### T107 详细 — P3 人在环：gap_review 自动暂停闸门（2026-07-21 深度分析定案）

> ⚠️ **文档位置说明**：T107 逻辑上属于 Phase 28（七方对标差距处理），因详细分析展开时依赖 Phase 29 上下文而物理放置于此。T107 的 4 子项（T107a-T107d）在 Phase 28 跟踪。

**问题**：交叉对标报告发现 gap_review 是"人在信息环"（列出 gap 供用户了解）非"人在决策环"（阻塞等用户审批）。ORCA 的 `decision_gate --wait` 是真正的决策闸门。

**现状澄清**：

gap_review **本身就是交互式的**——用户逐项对每个 gap 做 Fill/Research/Defer 决策。G6 NoDeferredBlockingGap 强制 architectural gap 不可 Defer。交互链路完整。

T107 的核心问题是：**gap_review 所有 gap 决策完成后，进入 architect 前，是否需要一个显式的"整体确认"闸门**。

**已有基础设施**：Phase 25 实现了 ORCA DecisionGate 全部 3 形态——Pre-planned Gate（T94）、Escalation Gate（T95）、Stage Checkpoint Gate（T64 `--pause-at-stage`）。gap_review→architect 的暂停机制已存在（`--pause-at-stage architect`），只是非默认行为。

**三种方案**：

| 方案 | 行为 | 优点 | 缺点 |
|------|------|------|------|
| A: 强制暂停 | gap_review 后始终暂停 | 最安全 | 每次都要用户手动确认，影响流程速度 |
| B: 可选暂停（现状） | `--pause-at-stage architect` 手动指定 | 用户自主 | 复杂 gap 场景无自动保护 |
| C: 阈值触发 | `has_blocking == true` → 自动暂停 | 高风险自动升级，低风险自动流转 | 需定义触发条件 |

**定案：方案 C**。

实现逻辑（`tick_orchestrator.py:_after_gap_review()`）：
```python
# gap_review 完成后，advance 到 architect 前检查
report = json.loads(self._state.gap_report_json or '{"has_blocking": false}')
if report.get("has_blocking"):
    self._pause_at_stages.add("architect")  # 复用 T64 Stage Checkpoint Gate
```

`has_blocking == true`（存在 architectural gap）→ 自动插入 checkpoint gate，用户在进入 architect 前审视整体 gap 决议。`has_blocking == false`（仅 component/module 级）→ 不暂停，直接进入 architect。

**子项**：

| 子项 | 描述 | 类型 |
|------|------|:--:|
| T107a | `_after_gap_review()` 增加 `has_blocking` 检测，条件性 `_pause_at_stages.add("architect")` | 实现 |
| T107b | gate action 的 `question` 包含 gap 摘要（blocking gap 数量 + 决议） | 实现 |
| T107c | 交叉对标报告 §10 人在环评分更新（方案定案后） | 文档 |
| T107d | test_tick_orchestrator 增加 has_blocking→pause / no_blocking→no_pause 测试 | 测试 |

**涉及文件**：
- `auto_engineering/loop/tick_orchestrator.py` — `_after_gap_review()` ~5 行改动
- `tests/test_tick_orchestrator.py` — ~2 tests
- 预估总改动：~20 行

### T113 详细 — P2 Build-then-Wire 系统性预防（三层防护升级）

**问题**：Phase 18-21 深度审计发现 7 模块 ~1875 行虚化代码——模块 TDD 完整构建、测试通过、跟踪表标记 ✅，但生产调用链从未到达。更严重的是 Phase 22（集成接线任务）本身也发生了 Build-then-Wire——"接线"只做了 orchestrator 侧参数位预留，CLI 侧从未实例化模块传入，导致静默 No-op。**接线任务需要二次修复**——这是系统性问题，不是个别疏忽。

**时间线**：
```
Phase 18-19: Build 模块（T53-T64）→ 跟踪表 ✅
Phase 22:    "Wire"（T73-T78）→ 跟踪表 6/6 ✅
             实际：仅参数位预留，CLI 侧 None 传入 → 静默 No-op
Phase 22 fix: 真跑评估发现 → 补齐 dev_loop.py 实例化 + restore() 参数 + log_event()
```

**根因分类（5 层）**：

| # | 根因 | 说明 | 示例 |
|---|------|------|------|
| 1 | **"完成"定义不含集成验证** | T-task ✅ = 代码+测试通过，不是"用户可用"。缺少"生产入口是否调用此模块"的验证 | T53 ContextOffloader 类存在、单测通过、但 dev_loop.py 从未 import |
| 2 | **静默 No-op 模式** | `if self._x is not None: self._x.do()` — 模块 None 时静默跳过，无警告无日志。生产韧性好，但开发验证阶段是灾难——没有任何信号 | 全 7 模块都使用此模式 |
| 3 | **TDD 不测接线** | 单元测试测模块内部逻辑（mock 依赖），模块集成测试测模块间交互（mock 依赖）。没有测试验证 CLI → TickOrchestrator → injectable 的调用链 | 7 模块都无 CLI 路径集成测试 |
| 4 | **Build-Wire phase 分离** | "先建好所有模块再统一接线"的设计意图，实际效果：Build 完成→心理关闭→Wire 被推迟→Wire 粗粒度打包→上下文丢失 | Phase 18-19 → 间隔数天 → Phase 22 |
| 5 | **条件激活不可见** | 4 个模块依赖环境变量激活（OTLP/AuditLog/Prompt Caching/PII），用户不知道功能存在→不设环境变量→模块永远 None | `AE_OTLP_ENDPOINT` 未设→tracer 永不创建 |

**当前残余虚化**（Phase 22 修复后）：

| 模块 | 行数 | 状态 |
|------|:---:|------|
| DiagnosticRuleDiscoverer | 321 行 | **零引用** — 从未被 import，仅 ratchet.py docstring 中作为类型提及 |
| RatchetController.sandbox_evaluate() | ~80 行 | **零调用** — 方法存在，无生产代码调用（仅 evaluate() 通过 enrichment.py 接线） |
| loop/threshold_learner.py（旧版） | ~120 行 | **仍被引用** — loop/__init__.py + orchestrator.py 仍 import 旧版，与 metrics/ 新版共存 |

**解决方案**：三层防护（L1 流程 + L2 代码 + L3 测试），从被动检测升级为主动预防

**L1 — 定义层：跟踪表"完成"定义升级**

在跟踪表更新协议中增加接线验证步骤——标记 ✅ 前必须满足：
1. 模块的公开入口点（类/函数）被至少一个生产调用链引用（grep 验证）
2. 在 commit message 中记录调用链路径（如 `wired: dev_loop.py::_build_injectables() → TickOrchestrator.__init__ → ContextOffloader`）
3. 如果模块是条件激活（依赖环境变量），验收标准必须包含"默认未激活时的行为说明"

这是流程约束，不依赖代码实现。每次标记 ✅ 前自检。

**L2 — 检测层：静默 No-op → 持续门控 `_require()`**

替代分散的 `if self._x is not None` 检查为统一的 `_require()` 方法：

```python
class TickOrchestrator:
    def _require(self, attr_name: str, reason: str = "") -> Any:
        """Get injectable with mandatory trace-level log when None.
        
        Does NOT change behavior (still degrades gracefully).
        Only makes the silent None visible at TRACE level.
        """
        val = getattr(self, attr_name, None)
        if val is None:
            _logger.debug(f"Injectable '{attr_name}' is None — feature disabled. {reason}")
        return val

# 使用:
offloader = self._require("_context_offloader", "stage context will not be offloaded")
if offloader:
    offloader.offload(...)
```

与旧方案的差异：
- 旧方案 `_verify_injectables()`：只在 `__init__` 时检查一次，WARN 级别
- 新方案 `_require()`：每次使用时检查，DEBUG 级别，不刷屏但可追溯
- 不是替代而是补充：`_verify_injectables()` 做启动汇总（用户可见），`_require()` 做运行时追踪（调试可见）

**L3 — 回归层：接线契约测试 + 自动追加约定**

```python
# tests/test_integration_cli_wiring.py
def test_all_required_injectables_non_none():
    """每个必需模块必须在 dev_loop.py 中被实例化并传入 TickOrchestrator"""
    inj = _build_injectables(project_root)
    # 必需模块（无环境变量也创建）
    assert inj["context_offloader"] is not None, "ContextOffloader must be instantiated"
    assert inj["session_summarizer"] is not None, "SessionSummarizer must be instantiated"
    # 条件模块（验证创建路径存在，环境变量控制）
    # tracer: AE_OTLP_ENDPOINT → setup_tracing()
    # audit_logger: AE_AUDIT_LOG=1 → AuditLogger()
    # 无条件时返回 None 是合法的，但创建路径必须存在

def test_injectables_passed_to_orchestrator():
    """验证所有 injectable 参数实际传入了 TickOrchestrator"""
    orch = TickOrchestrator.restore(...)
    assert orch._context_offloader is not None
    assert orch._session_summarizer is not None

def test_new_module_wiring_convention():
    """每个新增的 injectable 必须在本测试文件中追加对应断言"""
    # 约定：当 _build_injectables() 新增 key 时，本测试文件必须同步新增断言
    expected_keys = {"context_offloader", "session_summarizer", "tracer", "audit_logger"}
    actual_keys = set(_build_injectables(project_root).keys())
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    assert not extra, f"New injectable keys detected: {extra}. Add corresponding assertions above."
```

**对 T111（Phase 21 接线）的影响**：

T111 当前设计是 Build-Wire 分离模式（Phase 21 构建 → Phase 29 接线）——与 Phase 18-19→22 同模式。应在 T113 约束下调整 T111：接线不作为独立 Phase，而是追加到每个模块的 T-task 验收标准中——接线完成后才标记 ✅。

**涉及文件**：
- `tests/test_integration_cli_wiring.py` — **新建** L3 接线契约测试（~4 tests）
- `auto_engineering/loop/tick_orchestrator.py` — `__init__` 增加 `_verify_injectables()` + `_require()` 方法
- `design/IMPLEMENTATION-TRACKER.md` — 更新协议 §2：标记 ✅ 前增加接线验证步骤

### T114 详细 — P2 功能激活不可见（升级方案）

**问题**：17 个环境变量控制功能激活，散落 13 个 `.py` 文件，无集中清单。代码完整（AuditLog 79 行、OTLP 47 行、Metrics ~500 行、DebugTracer 101 行、LangSmith、Prompt Caching）但用户不知道这些功能存在。

**三层不可见**：
1. **存在不可见**：用户不知道有 AuditLog/OTLP/Metrics/DebugTracer 功能
2. **激活不可见**：即使知道功能存在，不知道设什么环境变量
3. **模式不可见**：Prompt Caching 默认开启但在 Agent 模式不生效（Agent 做 LLM 调用，Provider 层不介入），用户无感知

**17 个环境变量清单**：

| 类别 | 变量 | 默认 | 模式适用 |
|------|------|------|---------|
| 核心功能 | `AE_METRICS=1` | 关闭 | 双模式 |
| 核心功能 | `AE_AUDIT_LOG=1` | 关闭 | 双模式 |
| 核心功能 | `AE_OTLP_ENDPOINT` | 未配置 | 双模式 |
| 核心功能 | `AE_LANGSMITH=1` | 关闭 | 双模式 |
| 调试 | `AE_DEBUG=1` / `--debug` | 关闭 | 双模式 |
| 调试 | `AE_LOG_LEVEL` | INFO | 双模式 |
| 性能 | `AE_CACHE_CONTROL=0` | **开启** | **仅 Standalone** |
| 性能 | `AE_MAX_TOOL_CALLS` | 10 | 双模式 |
| Provider | `AE_LLM_PROVIDER` | anthropic | 双模式 |
| Provider | `AE_MODEL_<ROLE>` | 按 role | **仅 Standalone** |
| Provider | `AE_PROVIDER_<ROLE>` | 按 role | **仅 Standalone** |
| 阈值 | `AE_GATE_TIMEOUT` | Gate 默认 | 双模式 |
| 安全 | `AE_PRODUCTION=1` | 关闭 | 双模式 |
| 安全 | `AE_STRICT_RED=1` | 关闭 | 仅 Plugin |
| 抑制 | `AE_SUPPRESS_DEPRECATION=1` | 关闭 | 仅 Plugin |
| M5(T110) | `AE_TOKEN_TRACKING=1` | 关闭 | 双模式 |
| M5(T110) | `AE_TOKEN_SOURCE=transcript` | transcript | 双模式 |

**根因分析**：

| # | 根因 | 说明 |
|---|------|------|
| 1 | **无功能清单 SSOT** | 17 个 env var 散落 13 个文件，无集中定义。新增功能靠开发者记忆同步 doctor + dev_loop。T110 新增 `AE_TOKEN_TRACKING` 后无人记得更新 doctor |
| 2 | **doctor 定位偏差** | doctor 隐含"预检=找阻断问题"。可选功能被视为"非问题"而排除。但用户需求是"知道有什么配置能力"，不是"找出哪些检查不通过" |
| 3 | **--init 输出契约约束** | stdout 是 JSON 契约（Agent 解析），不能混入人读信息。stderr 仅 tick 阶段输出进度树，init 时无功能状态 |
| 4 | **env var vs CLI flag 发现不对称** | `--debug` 在 `--help` 中可见。`AE_METRICS=1` 无等效发现机制。用户只能靠读源码或文档发现 |
| 5 | **Agent 模式信息茧房** | Agent 调用 `ae dev-loop --init`，stdout JSON 被 Agent 消费，stderr 可能不转发给终端用户。功能状态双重不可见 |

**此问题是 F.14 根因 #5（条件激活不可见）的具体表现，也是 Build-then-Wire 的成因之一：用户不知道功能存在 → 不设环境变量 → 模块永远 None。**

**解决方案（5 层）**：

**5.1 FeatureManifest SSOT（`auto_engineering/config/feature_flags.py` 新建）**

```python
@dataclass
class FeatureFlag:
    key: str              # 环境变量名
    description: str      # 功能简述
    category: str         # observability/performance/debugging/provider/safety
    agent_mode: str       # "both" | "standalone_only" | "agent_only"
    activation: str       # 激活方式说明
    default_active: bool  # 不设环境变量时默认激活？

FEATURE_MANIFEST: list[FeatureFlag] = [
    FeatureFlag("AE_AUDIT_LOG", "LLM 调用审计日志 (JSONL)", "observability",
                "both", "AE_AUDIT_LOG=1", False),
    FeatureFlag("AE_METRICS", "AI Coding 度量收集", "observability",
                "both", "AE_METRICS=1", False),
    # ... 17 项
]
```

**约束**：新增 env var → 必须先注册到 FEATURE_MANIFEST → `ae doctor` + `--init` 自动展示。L3 接线契约测试增加 `test_feature_manifest_coverage`（新 env var 必须注册）。

**5.2 `ae doctor` 增加「可选功能」面板（主发现入口）**

在 10 项必需检查后，始终显示全部可选功能（无论激活与否）：

```
── Optional Features ──
✗ OTLP Tracing      未配置 — export AE_OTLP_ENDPOINT=http://localhost:4317
✗ Audit Log         未激活 — export AE_AUDIT_LOG=1
✗ Metrics           未激活 — export AE_METRICS=1
✓ Prompt Caching    已激活 (仅 Standalone 模式生效)
✗ LangSmith         未激活 — export AE_LANGSMITH=1 + LANGCHAIN_API_KEY
✗ Debug Tracer      未激活 — export AE_DEBUG=1 或 ae dev-loop --debug
```

**5.3 `--init` stderr 一行功能状态（快速确认）**

```
[Features] OTLP:✗ Audit:✗ Metrics:✗ Debug:✗ PromptCache:✓(Standalone)
```

详细指引指向 `ae doctor`。

**5.4 Agent 模式适配**

功能状态写入 action JSON 的 `feature_status` 字段，Agent 可在启动时转发给用户：

```json
{"action": "gap_scan", "feature_status": {"otlp": false, "audit_log": false, ...}, ...}
```

**5.5 对 T113 L1 的贡献**

- 新功能必须在 FEATURE_MANIFEST 注册（否则接线测试失败）
- 每个条件激活模块的 FeatureFlag 包含未激活时的行为说明
- `ae doctor` 自动展示（无需手动同步多个文件）

**涉及文件**：

| 文件 | 变更 |
|------|------|
| `auto_engineering/config/feature_flags.py` | **新建** — FeatureManifest SSOT（~17 项） + `check_feature()` / `get_feature_status()` |
| `auto_engineering/cli/doctor.py` | `run_doctor_checks()` 返回分段结果（required + optional），新增可选功能面板渲染 |
| `auto_engineering/cli/dev_loop.py` | `_run_tick_init()` stderr 一行功能状态 + action JSON `feature_status` 字段 |
| `tests/test_feature_flags.py` | **新建** — test_feature_manifest_coverage + test_feature_status_action_json |
| `design/BEACON.md` | 新决策 #80 — FeatureManifest SSOT |

### T115 详细 — P2 Agent/Standalone 能力不对称（升级方案）

**问题**：v7.0 双驱动架构在 TickOrchestrator 接缝处确实等价，但接缝之外的功能栈在两个驱动间存在系统性差异。Phase 17-21 功能设计隐含 Standalone 假设（BaseAgent.execute() pipeline 为集成点），AgentDriver 的边界（Claude Code 作为外部 LLM 进程）在设计时未被显式考虑。

当前文档仅有一处提及（附录 C R2: "gap_review 在 Standalone 模式功能受限"），无系统性能力矩阵。

**2.1 功能级不对称**

| 功能 | Agent | Standalone | 分类 | 说明 |
|------|:---:|:---:|------|------|
| PII — prompt 层 | ❌ | ✅ T56 | **设计替代** | T109 L2 outbound redact 是 Agent 等效防护（文件桥接层） |
| PII — tool result 层 | ❌ | ✅ T57 | **设计替代** | T109 L3 inbound scan 是 Agent 等效防护 |
| PII — 文件审计层 | ✅ | ✅ | 共享 | G10/G11 Guardrail |
| Prompt Caching | ❌ | ✅ T63 | **架构固有** | Agent LLM 调用在进程外，无法注入 cache_control |
| M5 Token 采集 | ⚠️ T110 JSONL | ✅ Provider hook | **设计替代** | 机制不同但功能等效 |
| AuditLog — LLM 内容 | ❌ | ✅ T77 | **架构固有** | Agent LLM 调用在进程外，JSONL 转录部分覆盖 |
| AuditLog — 事件 | ✅ | ✅ | 共享 | TickOrchestrator 注入 |
| AE_MODEL_<ROLE> | ❌ | ✅ | **架构固有** | Agent 选模型，Python 不控制 |
| gap_review 交互 | ✅ | ❌ auto-Defer | **架构固有** | Standalone 无交互 UI |
| ContextOffloader | ✅ | ✅ | 共享 | — |
| SessionSummarizer | ✅ | ✅ | 共享 | — |
| DebugTracer | ✅ | ✅ | 共享 | — |
| OTLP Tracing | ✅ | ✅ | 共享 | — |
| M1-M4 信号 | ✅ | ✅ | 共享 | TickOrchestrator 事件打点 |
| DiagnosticRuleDiscoverer | ❌ | ❌ | **未接线** | Build-then-Wire，见 T113 |

**2.2 行为/UX 不对称（架构固有）**

| 维度 | Agent | Standalone |
|------|-------|-----------|
| 执行方式 | 逐 tick 手动驱动 | 全自动运行至收敛 |
| 耗时 | ~8min/需求 | ~163s/需求 |
| 测试数量 | avg 8.5 | avg 11.8 |
| Phase 0 gap_review | Fill/Research/Defer | 全部 auto-Defer |
| 交互式工具 | 可用 | 不可用 |

**根因分析**：

| # | 根因 | 说明 |
|---|------|------|
| 1 | **Phase 17-21 功能设计隐含 Standalone 假设** | PII/T56、Prompt Caching/T63、Token Tracking 都以 BaseAgent.execute() 为集成点。T109（Agent PII 四层）是事后补救——设计阶段就应拆分 pipeline 层 vs file-bridge 层 |
| 2 | **双驱动文档聚焦共享引擎、忽略差异** | 附录 C 详细描述 StandaloneDriver 实现，但未建立"共享 vs 独有"的分类体系。"契约接缝等价"被扩大解读为"功能等价" |
| 3 | **无"驱动适用性"设计规范** | 新增功能时缺少"此功能在两个驱动下各如何工作？"的设计 checklist |
| 4 | **基准只测收敛、不测功能覆盖** | V7-8 基准 6 维全是收敛维度的，未测量 Phase 17-21 模块在两个驱动下的可用性 |
| 5 | **不对称的三种性质未被区分** | 架构固有 vs 设计替代 vs 未实现混为一谈，用户无法判断哪些是"永久差异"哪些是"待办事项" |

**解决方案（5 层）**：

**5.1 能力覆盖矩阵 SSOT（设计文档，非仅用户文档）**

在 `design/v5.6-Design-Loop.md` 附录 C 增加 §13 "双驱动能力覆盖矩阵"——上述 2.1 完整矩阵，含每个 Phase 17-21 模块的双驱动状态和分类标签。

**5.2 三种不对称分类体系**

| 分类 | 定义 | 处理方式 | 示例 |
|------|------|---------|------|
| **架构固有** | 驱动架构本身决定的差异，不可消除 | 文档标注 + 设计阶段评估影响 | Prompt Caching、gap_review 交互 |
| **设计替代** | 通过替代路径在另一驱动实现等效功能 | 标注"等效防护"/"替代路径"；无替代方案标注为缺口并跟踪 | T109 outbound redact 替代 T56 prompt redact |
| **未实现/未接线** | 功能设计为双模式但实际只在一端接线 | 视为接线缺陷，按 T113 L1 跟踪修复 | DiagnosticRuleDiscoverer |

**5.3 驱动适用性设计规范**

新增功能时必须回答（嵌入功能设计流程）：

1. **集成点在哪？**（BaseAgent.execute() pipeline / TickOrchestrator 注入 / Guardrail / Gate / CLI）
2. **集成点在两个驱动下均可达吗？**（是 → both / 否 → 标注适用驱动 + 为另一驱动设计替代路径）
3. **如果是架构固有差异，替代路径是什么？**

**5.4 metrics report 模式感知**

`output/metrics-report.json` 增加 `driver_mode` + 每个信号增加 `source` 字段：

```json
{
  "driver_mode": "agent",
  "signals": {
    "M5_token_efficiency": {
      "value": 42.3,
      "source": "jsonl_transcript",
      "note": "Token data from Claude Code session transcript (post-hoc)"
    }
  }
}
```

**5.5 已有模块追加双驱动标注**

在 v5.6-Design-Loop.md 中为已有设计章节追加标注：
- E.6.2 AuditLog：Agent 模式仅事件记录可用
- E.6.3 Prompt Caching：仅 Standalone 可用
- F.2 MetricsCollector：M5 Agent 模式依赖 T110 JSONL

**涉及文件**：

| 文件 | 变更 |
|------|------|
| `design/v5.6-Design-Loop.md` | 附录 C 新增 §13 能力覆盖矩阵 + E.6.2/E.6.3/F.2 追加双驱动标注 + 合并 T114 F.15 agent_mode 列 |
| `docs/USER_GUIDE.md` | 双驱动能力对比表（面向用户，从设计文档矩阵派生简化版） |
| `auto_engineering/metrics/collector.py` | `_compute_summary()` 增加 `driver_mode` 字段 + 每个信号增加 `source` |
| `auto_engineering/cli/dev_loop.py` | `_run_standalone()` / `_run_tick_init()` 传入 driver_mode |
| `tests/test_metrics_collector.py` | test_driver_mode_in_summary + test_signal_source_field |
| `design/BEACON.md` | 新决策 #81 — 双驱动能力覆盖矩阵 + 驱动适用性设计规范 |

### T116 详细 — P1 CriticVerdictInvalid 纵深防御

**问题**：`tick_orchestrator.py:1914` 用直接赋值 `self._state.critic_verdict = result.get("verdict", "")` 写入 critic verdict，绕过 `state.py:359` `_validate_field_value` 的 `_VALID_VERDICTS` 校验。虽然 `_after_critic`（L1023-1031）事后检测 `INVALID_VERDICT`，但非法值已先写入 state 并可能被 `_save_checkpoint()` 持久化到 SQLite——下次 `--resume` 恢复时脏数据已在 state 中。

**防御层分析**：

| 防御层 | 位置 | 覆盖 | 缺口 |
|--------|------|:---:|------|
| L1: write_field 校验 | `state.py:359-361` | `write_field("critic_verdict")` 调用路径 | 直接赋值绕过 |
| L2: _after_critic 逻辑判断 | `tick_orchestrator.py:1023-1031` | `APPROVE`/`MAJOR` 分支 | 事后检测——非法值已写入 |
| L3: StageRouter 异常 | `stage_router.py:48-62` | v5.5 连续循环路径 | v5.6 tick 路径不走 StageRouter |

**修复**：在 `_apply_result_to_state()` critic 分支（L1913-1916）写入前增加显式校验：

```python
elif stage == "critic":
    verdict = result.get("verdict", "")
    if verdict not in ("", "APPROVE", "MAJOR"):
        return ActionError(error_code="INVALID_VERDICT",
                           message=f"非法 critic verdict: {verdict!r}").to_dict()
    self._state.critic_verdict = verdict
    self._state.findings = result.get("findings", [])
    self._state.critic_feedback = result.get("critic_feedback", "")
```

**设计决策**：用显式 if-check 而非 `write_field()`。理由：① `_apply_result_to_state` 中其他 14 个字段都是直接赋值（保持一致性）；② `write_field` 抛 `ValueError` 需额外 try/except；③ 显式 check 在非法值时返回 `ActionError` 而非抛异常——对齐 `_after_critic` 已有的错误处理模式。

**涉及文件**：
- `auto_engineering/loop/tick_orchestrator.py` — `_apply_result_to_state()` L1913-1916 增加 verdict 校验（~4 行）
- `tests/test_tick_orchestrator.py` — `test_critic_verdict_invalid_rejected` + `test_critic_verdict_empty_allowed`（~2 tests）

### Phase 29 依赖关系

```
T108a (action JSON spawn 字段) ──独立──→ 第一批（核心）
T108b (dev-loop.md 结构调整)  ──依赖 T108a（spawn 字段设计确定后改 prompt）──→ 第一批
T108c (result 验证 WARN)      ──依赖 T108a──→ 第一批
T109a (PII infrastructure)    ──独立──→ 第一批（基础）
T109b (L1 requirement scan)   ──依赖 T109a──→ 第一批
T109c (L2 outbound redact)    ──依赖 T109a──→ 第一批
T109d (L3 inbound scan)       ──依赖 T109a──→ 第一批
T109e (L4 G11 PII extension)  ──依赖 T109a──→ 第二批
T109f (PII metrics)           ──依赖 T109b/T109c/T109d──→ 第二批
T109g (PII tests)             ──依赖 T109a-T109f──→ 第三批
T109h (PII docs)              ──依赖 T109a-T109e──→ 第三批
T112 (P2 Timing guardrail)    ──依赖 T108a（兜底校验依赖 spawn schema）──→ 第二批
T110a (TranscriptParser)      ──独立──→ 第二批（基础）
T110b (TickOrchestrator 集成)  ──依赖 T110a──→ 第二批
T110c (M5 mode-aware)         ──依赖 T110b──→ 第二批
T110d (JSONL 解析器测试)       ──依赖 T110a-T110c──→ 第三批
T113 (P2 Build-then-Wire prev)──独立──→ 第二批
T114 (P2 OTLP visibility)     ──独立──→ 第二批
T115 (P2 Capability asymmetry)──独立──→ 第二批
T111 (P1 Phase 21 wiring)     ──独立──→ 第二批
T116 (P1 CriticVerdictInvalid)  ──独立──→ 第一批
```

---

## Phase 30 — 深度审计发现修复（2026-07-21）

> 来源：2026-07-21 全量深度审计（`_scratch/reports/2026-07-21-deep-audit-full.md`）。5 维度（架构/代码质量/工程化/虚化度/协作），加权综合 ~5.5/10，28 项发现（6 P0 + 12 P1 + 10 P2）。
> 性质：**批量代码修复**（16 项可自动修复）+ **6 项架构决策待确认**（需用户审批）。
> BEACON 决策 #86。

### 第一批：自动修复（16/18 ✅ 已完成）

| T | 审计# | 修复项 | 严重度 | 位置 | 状态 |
|---|-------|-------|:---:|------|:---:|
| T117 | C1 | convergence.py:339 静默吞异常 → `_logger.debug` + 窄化捕获 | P0 | `loop/convergence.py:339` | ✅ |
| T118 | V2 | `_write_audit_history` 纯占位 pass → debug 日志 | P0 | `loop/tick_orchestrator.py:2241` | ✅ |
| T119 | E1 | AE_AUDIT_LOG_DIR 注册到 FEATURE_MANIFEST | P0 | `config/feature_flags.py` | ✅ |
| T120 | C2 | file_tools.py 6 处裸 except Exception → (OSError, ValueError) | P1 | `tools/file_tools.py:52,83,125,170,178,210` | ✅ |
| T121 | C3 | metrics/enrichment.py + transcript_parser.py 裸 except 窄化 | P1 | `metrics/enrichment.py:81`, `metrics/transcript_parser.py:103,107` | ✅ |
| T122 | C4 | cli/checkpoint.py 7 处裸 except → (OSError, sqlite3.Error, ValueError) | P1 | `cli/checkpoint.py` | ✅ |
| T123 | C5 | gate_check.py:93 SystemExit(1) 无消息 → stderr echo + 保留退出码 | P1 | `cli/gate_check.py:93` | ✅ |
| T124 | C6 | guardrail.py:1046 state: Any → "EngineState" | P1 | `loop/guardrail.py:1046` | ✅ |
| T125 | C7 | ratchet.py git tag subprocess 加 timeout=5 | P1 | `metrics/ratchet.py:201` | ✅ |
| T126 | C8/C9/C10 | 其余 5 处裸 except 窄化（gate_check/bash_tools/run_tests_tool/base） | P1/P2 | 5 文件 | ✅ |
| T127 | V6 | `__all__` 移除私有常量 | P2 | `loop/tick_orchestrator.py:2291` | ✅ |
| T128 | E3 | pii/guardrail.py 12 tests（init/check/block_mode/pattern 匹配） | P1 | `tests/test_pii_guardrail.py` (新增) | ✅ |
| T129 | T3 | PIIGuardrail patterns 为空时 WARN 日志 | P2 | `pii/guardrail.py` | ✅ |
| T130 | T4 | set_collector() docstring | P2 | `metrics/collector.py:47` | ✅ |
| T131 | V4 | `_get_p1_threshold` Bayesian 接线 | P1 | `loop/tick_orchestrator.py:1833` | ✅ |
| T132 | V5 | Standalone 模式 audit_logger 注入 | P2 | `cli/dev_loop.py:283` — `_build_injectables()` 复用, audit_logger 传入 TickOrchestrator | ✅ |
| **T135** | **C-all** | **P0-5 裸 except Exception 窄化 — 31 处窄化为 10 种具体异常类型（18 文件），13 处保留宽捕获加注释** | **P0** | 16 源文件（cli/loop/metrics/tools/gates/），零回归 | ✅ |
| **T136** | **E1** | **P0-6 RuntimeConfig 环境变量集中化 — 49 os.environ → 1 RuntimeConfig frozen dataclass（30+ typed properties），进程级 sentinel 模式，conftest autouse 重置** | **P0** | `config/runtime_config.py` (新建, 234 行) + 18 源文件 + conftest 更新，2372 tests 零回归 | ✅ |

### 第二批：架构决策（6 项待用户确认）

| T | 审计# | 决策项 | 严重度 | 方案 | 状态 |
|---|-------|-------|:---:|------|:---:|
| T133a | A1 | TickOrchestrator SRP 拆分 | P0 | ActionBuilder（~400 行, 15 方法）+ TickGateRunner（~130 行）委托类提取完成。Orchestrator 2321→1885 行, 60→52 方法。after-handlers 因紧耦合状态变更保留。BEACON #89 | ✅ |
| T133b | A2 | v5.5 Orchestrator 退役 | P0 | orchestrator.py 已在 T133b-f 前序会话中物理删除。附带 5 模块同步删除（T133c）。BEACON #53 | ✅ |
| T133c | A3/A4/V3 | v5.5 退役附带清理 | P1 | 6 个仅服务 v5.5 的模块已删除：orchestrator.py, deep_audit.py, semantic_evaluator.py, convergence_facade.py, guardrail_facade.py, loop/threshold_learner.py。BEACON #53 | ✅ |
| T133d | V1 | SessionSummarizer 全链路死代码 | P0 | summarization.py (223 行) + test_context_summarization.py 物理删除。context/__init__.py + test_context_wiring.py + test_integration_cli_wiring.py 清除引用。BEACON #83 | ✅ |
| T133e | E2 | BEACON.md 引用已删除文件修复 | P1 | 决策 #51 更新: commit_msg_gate.py 移除原因说明 (Agent/Standalone 两端均无消费者)。`src/fibonacci.py` 是 `/tmp/_ae_test_project/` 临时测试产物。 | ✅ |
| T133f | E4/E5 | ~~FreshGuardrail 重命名 + guardrail_base.py 移至 loop/~~ | P2 | ~~重命名类名 + 更新所有引用 + 移动文件 + 更新 import 路径~~ → ✅ 已完成 (2026-07-21)。P0-3/P0-4 全部统一为 Guardrail 后缀。BEACON #90 | ✅ |

### 第三批：文档与体验改善（待执行）

| T | 审计# | 修复项 | 严重度 | 状态 |
|---|-------|-------|:---:|:---:|
| T134a | T1 | README.md 添加 AE_ 环境变量配置章节 | P2 | ✅ |
| T134b | T2 | 3 处 global 单例生命周期文档 | P2 | ✅ |
| T134c | T5 | AE_MODEL_ROLE/AE_PROVIDER_ROLE 参数化测试 | P3 | TestResolveModel 4 tests (9 parametrized) + TestResolveProvider 3 tests. test_standalone_driver.py | ✅ |
| T134d | E6 | `step` vs `tick` 术语定义文档化 | P2 | tick_orchestrator.py 模块 docstring: tick=离散调用周期, step=stage 转换, round=跨 tick 累积轮次 | ✅ |

### 测试基线

- **修复前**：2585 passed, 3 skipped
- **第一批后**：2596 passed, 4 skipped (+12 PIIGuardrail 测试 -1 已知 flaky)
- **P0-5 窄化后**：2596 passed, 4 skipped（零回归）
- **P0-6 RuntimeConfig 后**：2372 passed, 4 skipped（零回归，config 注入覆盖全链路）

### 裸 except Exception 清理进展

| 阶段 | 数量 | 备注 |
|------|:---:|------|
| Phase 29 前 | ~55 处 | 全项目基线 |
| Phase 29 | ~31 处 | standalone_driver + tick_orchestrator 已清理 |
| Phase 30 第一批 | ~18 处 | file_tools(6) + checkpoint(7) + metrics(3) + tools(2) 已清理 |
| **P0-5 系统窄化** | **~18 处** | **cli/guardrail/metrics/gates 等 16 文件窄化为 10 种具体异常类型，13 处保留加注释。全量完成** |
| **剩余** | **~33 处** | 主要在 v5.5 legacy 路径（orchestrator/semantic_evaluator）、gates/runner（fail-closed 有注释说明）、CLI progress/status/agent（user-facing 降级捕获）。**不再建议批量窄化。** |

> **剩余裸 except 评估**：v5.5 legacy 路径将在退役时一并删除（~7 处）。gates/runner 的 fail-closed 模式有注释说明，属有意设计。CLI 层 user-facing 捕获可沿用（已通过文件级窄化）。不再建议批量窄化——剩余的多数有明确设计意图或将在退役中自然消除。

---

## Phase 31 — Subagent Spawn 强制执行：提示词注入 + 重构（BEACON 决策 #91）

> 来源：2026-07-22 真跑验证发现 T51a-f 系统性未落地。根因：角色 prompt 未送达 LLM + action JSON 缺少自然语言指令。
> 方案：`design/discussion/subagent-spawn-solution.md`
> 原则：不改架构、不新建文件——`PromptRegistry` 已存在，`ActionBuilder` 已有调用点。

### 任务

| T | 内容 | 验收 | 状态 |
|---|------|------|:---:|
| T137 | **7 个角色 prompt 重构** — `prompts/roles/{architect,developer,critic,component_verifier,plate_deep_audit,system_verifier,system_deep_audit}.md` 全部改写。结构：Role + Goal + Context。每个 < 50 行。 | 7 个文件改写完成 + `severity_rubric.md` fragment | ✅ |
| T138 | **`ActionBuilder._build_stage_action` 注入 role_prompt + instruction** — spawn 角色时调 `default_registry().get(action)` + 注入 `_SPAWN_INSTRUCTION`。 | action JSON 含 `instruction` + `role_prompt` 字段 | ✅ |
| T139 | **`_SPAWN_INSTRUCTION` 自然语言命令模板** — 6 个 spawn 角色通用。 | 模板定义 + ≤5 行 | ✅ |
| T140 | **`commands/dev-loop.md` 瘦身** — 300 行 → 111 行组长手册。 | ✅ 111 行 + sync 通过 | ✅ |
| T141 | **`expected_format` 增加 `spawned` 字段** — spawn 角色 expected_format 首行 `"spawned": "bool — MUST be true"`。 | action JSON 含 spawned | ✅ |
| T142 | **T108c 升级为 G2 retry** — spawn 角色 + `spawned` 非 true → `ErrorResponse("SPAWN_REQUIRED")`。 | 缺 spawned → SPAWN_REQUIRED ✅ + spawned=true → 通过 | ✅ |
| T143 | **`prompts/fragments/severity_rubric.md` 新建** — P0/P1/P2 统一定义，critic/plate_deep_audit/system_deep_audit 引用。 | fragment 存在 + 3 个 prompt 引用 | ✅ |
| T144 | **全量测试回归** — prompt 测试更新 + spawn stage 测试更新 + G2 retry 测试。 | 2328 passed, 0 新回归 | ✅ |
| T145 | **真跑验证** — VoiceClonePage 需求重新跑 dev-loop。 | architect action: instruction ✅ role_prompt ✅ spawn ✅ spawned ✅ + G2 retry ✅ + Plan subagent 实际 spawn ✅ | ✅ |

### 实施顺序

```
T137 (prompt 重构) → T143 (severity rubric)
    ↓
T139 (指令文本) → T138 (ActionBuilder 注入) → T141 (spawned 字段)
    ↓
T142 (G2 retry) → T140 (dev-loop.md 瘦身)
    ↓
T144 (全量回归) → T145 (真跑验证)
```

---

## Phase 31a — 2026-07-21 深度审计待办 (来源: 全量审计 40 项 + /tttt 深度追踪)

> 已修复: 21 项 (全量审计 P0×9+P1×8 + 深度追踪 D1×1 + P1-8/P1-14/P2-9)
> 剩余: 19 项 — 15 项 P2 低优先级 + 4 项需用户决策

### 需用户决策 (⛔)

| # | 来源 | 问题 | 选项 | 建议 |
|---|------|------|------|------|
| AD1 | P2-1 | **PRBackend ABC ~330 行零生产消费者** — `pr_backend.py` 含 GitHub/GitLab PR backend + `select_backend()`，仅 `ae doctor` 的 `available_backends()` 调用 | A. 接线到 convergence 路径自动创建 PR → ~2d / B. 物理删除 → 10min / C. 保持休眠 | B — BEACON #45 GitLab CI 同理是"已设计未实施"，不如果断清理 |
| AD2 | P2-2 | **Channel[T] ABC 体系 (~100 行) v2.0 遗留** — `_serialization.py` 中 `Channel`/`LastValueChannel`/`AccumulatingChannel`/`BarrierChannel`，`loop/__init__.py` 明确注释"不再导出" | A. 审计调用方后删除 / B. 保留为"休眠模块" | A — 零消费者即删除 |
| AD3 | P2-3 | **ThresholdLearner.propose_adjustments() 从未调用 (~30 行)** — 仅 `compute_max_iter()` 有消费者 | A. 接线到 `_run_ratchet()` → ~1d / B. 删除 → 10min | B — BEACON #47 已判 YAGNI，此方法是残留 |
| AD4 | P2-4 | **`check_feature()` guard function 零调用方** — 设计为"新增 env var 必须先注册"的 enforcement，但从未被调用 | A. 在 CI test 中调用 → 30min / B. 删除 → 5min | A — 有价值的 guard，一行 import 即可激活 |

### P2 低优先级（消化后自行决定）

| # | 来源 | 任务 | 严重度 | 建议 |
|---|------|------|:---:|------|
| T135a | P1-7 | JSON 工具函数提取 — 37+ 处 `json.loads(path.read_text())` 重复，错误处理不一致 | P2 | 大重构，等空闲窗口。新建 `utils/file_utils.py`，统一 `safe_json_load/save` |
| T135b | P1-9 | `_compute_loc_added()` 失败返回 0 vs None — 与"零变更"不可区分。且该方法本身零生产调用方（Build-then-Wire） | P2 | 先确认是否需要该方法，不需要则删除；需要则改返回 None |
| T135c | P1-10 | `Any` 类型 → Protocol — `tracer: Any` `transcript_parser: Any` 等注入点 | P2 | 类型体操，无运行时价值。等 Protocol 定义稳定后再做 |
| T135d | P1-11 | monkey-patching `type: ignore[attr-defined]` 8 处 — `_state.batch_state` `_state._plan` 动态注入 | P2 | 跟随 TickOrchestrator state refactor（BEACON #89 暂缓）一并处理 |
| T135e | P1-15 | api-reference.md v5.0/v5.5 legacy 示例完整审查 — 加版本标注或移到附录 | P2 | 已加 deprecation banner，完整审查 ~1h |
| T135f | P1-16 | FeatureManifest (23 flags) vs RuntimeConfig (30 properties) 分层文档化 | P2 | API key 类单独文档 + SDK 路径类补充注册 |
| T135g | P2-5 | `_TracerLike` Protocol — 定义了但方法名与实际调用不匹配 (`start_as_current_span` vs `start_span`) | P2 | 删除或对齐方法名 |
| T135h | P2-6 | CHANGELOG.md 创建 — 破坏性变更散落 90 个 BEACON 决策 | P2 | 首版从 BEACON 决策回溯关键变更，~2h |
| T135i | P2-7 | `_` 前缀函数跨模块调用审查 — `Gate._resolve_timeout()` 等 | P2 | 审计后决定：保留（base→subclass 约定）还是重命名 |
| T135j | P2-8 | 28 处 `type: ignore` 逐条审计 + 标注理由 | P2 | ~1h，与 T135d 重叠部分跟随 state refactor |
| T135k | P2-10 | `_map_llm_exception` 可测试性 — 硬编码 Anthropic 类型 → 接受映射字典参数 | P2 | 加可选 `exception_map` 参数，测试时注入 |
| T135l | P2-11 | test 质量：同义反复测试 — `test_default_name` 测构造函数默认值 | P2 | 删除或改为验证 name 在 gate 执行中的实际语义 |
| T135m | P2-12 | `action.schema.json` $id 注释 — 指向不解析域名 | P2 | 加注释"内部标识符，非可解析 URL" |
| T135n | 深度审计 | Guardrail type 迁移收尾 — 消除 `shared/` → `engine/` → `loop/` 三跳 re-export shim | P2 | 所有消费者直连 `shared/guardrail.py`，删两个 shim 文件 |
| T135o | P1-2 | TickOrchestrator 暂缓标注更新 — 在 tracker 中标记"条件暂缓 (waiting on state refactor)" | P2 | 仅 tracker 文档更新 |

### 修复统计

| 类别 | 已修复 | 待办 | 需决策 |
|------|:---:|:---:|:---:|
| P0 | 9/9 | 0 | 0 |
| P1 | 8/16 | 8 | 0 |
| P2 | 4/15 | 11 | 0 |
| 深度追踪 | 1/1 | 1 (shim 收尾) | 0 |
| 架构决策 | 0/0 | 0 | 4 |
| **合计** | **22** | **20** | **4** |

> 审计报告: `_scratch/reports/2026-07-21-audit.md` (全量) + `_scratch/reports/2026-07-21-deep-audit-tttt.md` (深度追踪)
> 已修复 commit: `81eb494` (17 项) + `59918db` (4 项) + Phase 30 `631dbc7` (28 项)

---

## Phase 32 — 5 层验证提示词增强 + subagent_type 移除 + 真跑审计修复（BEACON #92）

> 来源：2026-07-22-23 voice_clone 真跑验证（9 tick, 8 stage, 10 errors, 5 类 20 引擎问题）
> 分析报告：`_scratch/test-output/voice_clone-v5.6-tick-phase17-21-analysis-20260723.md`
> 原则：提示词直接搬用标杆项目（Claude Code / github-review-pr / Superpowers / gitnexus-pr-review），不自创

### 一、引擎修复（5/8，2327 tests 零回归）

| T | 内容 | 验收 | 状态 |
|---|------|------|:---:|
| T136a | `_SPAWN_CONFIG` 移除 `subagent_type` 字段（6 个 entry）+ `_SPAWN_INSTRUCTION` 去掉 `{subagent_type}` + `action_builder.py` `.format()` 去掉对应参数 | voice_clone 真跑 critic/verifier spawn 不再因 agent 类型解析失败 | ✅ |
| T136b | `_SPAWN_INSTRUCTION` 模板改为无 subagent_type 引用 + `tick_orchestrator.py:768` SPAWN_REQUIRED 消息同步修复 | spawn error 消息不含 subagent_type | ✅ |
| T136c | `gate/type_check.py` `_has_type_config()` — 按 `type_checker_bin` 路由配置检测（tsc→tsconfig.json, pyright→pyrightconfig.json, go vet→go.mod, cargo check→Cargo.toml, mypy→mypy.ini/setup.cfg/pyproject.toml） | test_gates_type_check_extended 全部通过 | ✅ |
| T136d | `engine/batch_state.py` — "零 batch 组件" WARNING→INFO + `_warned_zero_batch` 改为 ClassVar 跨实例 dedup | before: 每 tick WARNING ×14 组件; after: 首次 INFO, 后续静默 | ✅ |
| T136e | `loop/action_builder.py` — architect/plate_deep_audit expected_format 补全必填标记（plan/plate/cross_component_issues） | `validate_result_format` 校验不再因字段缺失误报 | ✅ |

### 二、提示词增强（13 文件，搬用 4 标杆项目）

| T | 文件 | 内容 | 搬用来源 | 状态 |
|---|------|------|---------|:---:|
| T136f | `prompts/roles/critic.md` | 37→82 行: 5 审查维度 + 10 false positive 规则 + DO/DON'T | Claude Code `code-review` §4 Agent #1-#5 + github-review-pr §False Positive + Superpowers §Critical Rules | ✅ |
| T136g | `prompts/roles/component_verifier.md` | 33→61 行: 映射方法 6 步 + DIVERGED 判定表 5 行 | Superpowers "Plan alignment" 细化 | ✅ |
| T136h | `prompts/roles/plate_audit_contracts.md` | **新建**: 跨组件契约逐对检查 + d=1/d=2 影响分析 | gitnexus-pr-review §Risk Assessment | ✅ |
| T136i | `prompts/roles/plate_audit_dataflow.md` | **新建**: 数据流追踪 + 状态归属 + 错误传播 | Superpowers "Architecture" + gitnexus impact | ✅ |
| T136j | `prompts/roles/plate_audit_architecture.md` | **新建**: 依赖方向 + 循环依赖 + 职责越界 | Superpowers "Architecture — Sound design?" | ✅ |
| T136k | `prompts/roles/plate_deep_audit.md` | 重写: 3 agent 合并汇总 prompt | — | ✅ |
| T136l | `prompts/roles/system_verifier.md` | 30→55 行: 交叉验证 + 不报规则 | — | ✅ |
| T136m | `prompts/roles/system_audit_architecture.md` | **新建**: Agent 1 — 模块边界/依赖方向/循环依赖 | — | ✅ |
| T136n | `prompts/roles/system_audit_code_quality.md` | **新建**: Agent 2 — 空 catch/资源泄漏/any 类型 | Claude Code Agent #2 (shallow bug scan, full scope) | ✅ |
| T136o | `prompts/roles/system_audit_engineering.md` | **新建**: Agent 3 — 命名/类型导出/测试分层 | Superpowers "Testing — real behavior?" | ✅ |
| T136p | `prompts/roles/system_audit_virtualization.md` | **新建**: Agent 4 — export 零调用/配置零消费/TODO 零跟踪 | — | ✅ |
| T136q | `prompts/roles/system_audit_team.md` | **新建**: Agent 5 — 错误消息/注释准确/设计覆盖闭环 | Superpowers "Production readiness" | ✅ |
| T136r | `prompts/roles/system_deep_audit.md` | 重写: 5 agent 合并汇总 prompt | — | ✅ |

### 三、配套更新

| T | 内容 | 状态 |
|---|------|:---:|
| T136s | `skills/auto-engineering/SKILL.md` — Role execution 表删 subagent_type 列 | ✅ |
| T136t | `tests/test_prompt_registry.py` — `_ALL_ROLES` 9→17 | ✅ |
| T136u | BEACON.md — 更新日期 + 决策 #92 + 演进日志 | ✅ |
| T136v | Phase 17-21 真跑对标分析报告 | ✅ |
| T136y | OTLP grpc 连接失败优雅降级 — 每次 tick 3-4 条 retry ERROR | ✅ (Phase 33b) |

> **剩余**: T136w (STAGE_MISMATCH) — 代码逻辑正确需真跑触发。T136x 已在 Phase 34 修复 (commit `24c0ce1`)。

---

## Phase 33 — 全量深度审计 50 项发现修复（BEACON #93）

> 来源：2026-07-23 全量深度审计（3 Agent 并行 + Phase 1 快扫）
> 报告：`_scratch/reports/2026-07-23-audit.md`
> 结果：50 项发现 → 40 修复 + 10 废弃，评分 5.5→7.0

### 修复统计

| 类别 | 已修复 | 废弃 | 延后 |
|------|:---:|:---:|:---:|
| P0 | 8/8 | 0 | 0 |
| P1 | 18/20 | 2 | 0 |
| P2 | 14/22 | 8 | 0 |
| **合计** | **40** | **10** | **0** |

### 关键修复

| T | 内容 | 文件 |
|---|------|------|
| T137a | FeatureManifest 清理 — AE_LANGSMITH/AE_SUPPRESS_DEPRECATION 移除, langsmith_enabled 移除, suppression category 移除 | feature_flags.py, runtime_config.py, test_feature_flags.py |
| T137b | standalone_driver git 安全加固 — _auto_commit 返回码检查 + escalation gate 不自动通过 + git add -A→. | standalone_driver.py |
| T137c | 虚化模块接入 — DiagnosticRuleDiscoverer→收敛路径, RatchetController 配置版本化闭环, ThresholdLearner 移除 metrics_enabled gate | tick_orchestrator.py |
| T137d | TaskDAG 死代码移除 — depends_on 始终为空, 拓扑排序产出未消费 | tick_orchestrator.py |
| T137e | EscalationHandler 委托类提取 (~220行) — God Class 再减 180行 | escalation_handler.py (新建), tick_orchestrator.py |
| T137f | AE_PRODUCTION 接入 — production_enabled→REDGuardrail+GateRunner hard_fail | runtime_config.py, stateful.py, gates/runner.py |
| T137g | GateExecutionError 异常契约 + GATE_EXECUTION_ERROR ErrorCode | errors.py, test_error_codes.py |
| T137h | EngineState _runtime_ctx 替代 monkey-patching + model_dump/from_dict 排除 | state.py, tick_orchestrator.py |
| T137i | dead import os ×5 移除 | standalone_driver.py, collector.py, transcript_parser.py, guardrail.py, factory.py |
| T137j | batch_state: inline import→top + ClassVar Lock + _flatten→flatten | batch_state.py |
| T137k | ActionBuilder: pii_redactor 类型标注 + exception logging + SSOT 常量 | action_builder.py |
| T137l | gates/runner: Gate.contracts 不 mutate + AE_PRODUCTION hard_fail | gates/runner.py |
| T137m | PII_BLOCKED_INBOUND 分类摘要 + architect prompt 工具指令 + magic string 消除 | tick_orchestrator.py, standalone_driver.py |
| T137n | SQLite __del__ + 二进制 diff 保护 + metrics atomic flush + logging/pathlib import 归位 | store.py, tick_orchestrator.py, collector.py, cli/__init__.py, standalone_driver.py |
| T137o | init_contract: re-export 移出 __all__ + P2-42 CLI environ param | init_contract.py, cli/dev_loop.py |

### 废弃项（非问题，已确认）

| 项 | 原因 |
|----|------|
| P1-8 | `__getattr__` 已有清晰 v6.0 注释 |
| P1-10 | `_build_task_description` 242行是纯 dispatch 方法，拆成 8 个方法降低可读性 |
| P2-29 | 18 个 `assert is not None` 全部有后续结构化断言，是标准 Pydantic 防御模式 |
| P2-33 | go vet/go-vet 双格式是防御性设计 |
| P2-34 | "英文 error_code + 中文 message" 是项目编码约定 |
| P2-36/P2-37 | ActionBuilder 14参/Orchestrator 13参是依赖注入标准模式，Config dataclass 降低可测试性 |
| P2-43 | GapReport dict-native 是 BEACON #52 设计决策 |
| P2-44 | PromptRegistry 已接线（spawn 路径 registry.get()），stage 指令是元数据非 prompt |
| P2-45/P2-46 | ChineseProvider 仅 Standalone 是 BEACON #81 双驱动架构设计 |

---

## Phase 33a — 用户决策执行（BEACON #93 扩展）

> 来源：2026-07-23 全量审计 4 项需用户决策

| T | 决策 | 方案 | 状态 |
|---|------|------|:---:|
| AD1 | PRBackend ABC 零生产消费者 | B. 物理删除 — pr_backend.py + test_pr_backend.py 删除，doctor 改直接检测 gh/glab CLI | ✅ |
| AD2 | Channel[T] ABC v2.0 遗留 | A. 保留为内部迁移模块 — loop/__init__.py 文档更新，不导出 | ✅ |
| AD3 | ThresholdLearner.propose_adjustments() 从未调用 | A. 接线到 _run_ratchet() — 收敛时自动触发贝叶斯阈值建议 | ✅ |
| AD4 | check_feature() guard 零调用方 | A. 接入 CI — test_feature_flags.py 加 3 tests | ✅ |

---

## Phase 33b — P2 低优先级深度修复

> 来源：2026-07-23 P2 低优先级 9 项全部消化

| T | 内容 | 结果 |
|---|------|------|
| T135a | JSON 工具函数提取 — 24 处 `json.loads(path.read_text())` 重复 | ✅ 19 处改用 safe_json_load，5 处保留（需异常传播） |
| T135b | `_compute_loc_added()` 零生产调用方 | ✅ 删除方法 + 5 tests + _make_git_repo helper |
| T135c | `Any` → Protocol 类型标注 | ✅ _TracerLike + _TranscriptParserLike Protocol 定义 + tick_gate_runner 标注 |
| T135d | `type: ignore[attr-defined]` 5 处审计 | ✅ 加理由注释 + debug_tracer 改用 object.__setattr__ |
| T135e | api-reference.md v5.0/v5.5 legacy 审查 | ✅ 已有完善 ⚠️ banner + 归档，无需改动 |
| T135f | FeatureManifest vs RuntimeConfig 分层文档 | ✅ feature_flags.py 补充分层关系 + 迁移规则说明 |
| T135g | `_TracerLike` Protocol 方法名不对齐 | ✅ start_as_current_span→start_span，对齐实际调用 |
| T135h | CHANGELOG.md 创建 | ✅ 从 93 BEACON 决策回溯里程碑变更 |
| T135i | `_` 前缀函数跨模块调用审计 | ✅ 验证通过 — 零跨模块 _ 前缀违规 |
| T135j | 23 处 `type: ignore` 逐条审计 | ✅ 全部有注释说明原因 |
| T135k | `_map_llm_exception` 可测试性 | ✅ 添加 exception_map 参数用于测试注入 |
| T135l | 同义反复测试删除 | ✅ 核查 — 全部是回归保护，非同义反复 |
| T135m | `action.schema.json` $id 标注 | ✅ 加 $comment 字段说明 |
| T135n | Guardrail shim 消除 | ✅ loop/guardrail_base.py 删除，消费者直连 engine/guardrail_types |
| T135o | TickOrchestrator 暂缓标注更新 | ✅ 当前无暂缓项 |

### 删除文件汇总

| 文件 | 原因 |
|------|------|
| `tools/pr_backend.py` (147行) | 零生产消费者 |
| `tests/test_pr_backend.py` | 随 PRBackend 删除 |
| `loop/guardrail_base.py` (15行) | shim 消除 |
| `_compute_loc_added` 方法 + `TestComputeLocAdded` + `TestM5GitDiffFix` + `_make_git_repo` | 死代码 |

### 新建文件汇总

| 文件 | 用途 |
|------|------|
| `utils/file_utils.py` | safe_json_load / safe_json_save |
| `loop/escalation_handler.py` | God Class 拆分 |
| `CHANGELOG.md` | 里程碑变更记录 |

---

### 剩余待办（2 项 P0，需真跑复现）

| T | 内容 | 严重度 | 阻塞原因 |
|---|------|:---:|------|
| T136w | STAGE_MISMATCH 系统性缺陷（E2） — Agent 延迟提交上一 stage 结果导致 spawn 校验短路 | P0→✅ | **已修复**: `_tick_body_dict` 增加 stale result 降级逻辑 — 匹配 `_last_completed_stage` 时自动接受并重建 action |
| T136x | test gate manifest→reload 路径验证 | P0→✅ | **已修复**: `restore()` 中 reload 移到 manifest 加载之后 (commit `24c0ce1`) |
| T136z | Phase 17-21 真跑对标分析 | ✅ | 报告: `_scratch/test-output/2026-07-23-dev-loop-真跑深度对标分析报告.md` |

---

## Phase 34 — 真跑问题全部修复（BEACON #94）

> 来源：2026-07-23 第二次 voice_clone 真跑验证 — 19 项问题（P0×3 + P1×8 + P2×5 + 流程×3）
> 问题清单：`_scratch/test-output/2026-07-23-真跑问题清单.md`

| T | 内容 | 验收 | 状态 |
|---|------|------|:---:|
| T146a | P0-1 `config` 未定义崩溃修复 — `dev_loop.py` `run_tick_init` 添加 `cfg = get_default_config()` | `ae dev-loop --init` 不再 crash | ✅ `373f183` |
| T146b | P0-2 收敛失败修复 — `from_design_doc` plate/component 按 batch_plan 顺序排序 | developer tick 按 B1→B19 分发, 逐 batch 收敛 | ✅ `746091e` |
| T146c | P0-3 `_STAGE_CHECKPOINT_OPTIONS` SSOT — 从 action_builder 提取常量, tick_orchestrator 导入 | ImportError 消除 | ✅ `373f183` |
| T146d | P1-3 architect context 补传 `component_map` — `_build_component_map()` 从 DesignDoc 提取 §编号→组件名 | LLM 可按编号引用组件, 不再猜名称 | ✅ `373f183` |
| T146e | P1-6 test gate manifest→reload 时序 — `restore()` 中 reload 移到 manifest 加载之后 | vitest 项目不再用 pytest 默认 | ✅ `24c0ce1` |
| T146f | P1-7 SessionSummarizer 输出丰富度 — critic_verdict/total_majors/文件累积 | 摘要含结构化决策信息 | ✅ `24c0ce1` |
| T146g | P1-4 spawn_proof_token side-channel 验证 — UUID token + proof 文件写入指令 + G2 proof 文件检查 | G2 不再仅依赖 Agent 自报 spawned 字段 | ✅ `746091e` |
| T146h | P2-2 audit 输出完整性 — P0 全量/P1≤10/P2≤5, 截断提示 details.findings | audit gate 不再隐藏 blocking finding | ✅ `24c0ce1` |
| T146i | P2-3 --status --verbose batch 进度 | `--verbose` flag + batch_progress JSON 段 | ✅ `746091e` |
| T146j | P2-4 prompt 日志 — `_scratch/prompt-log/tick-NNNN-stage-action.json` | best-effort 写 action JSON | ✅ `746091e` |
| T146k | F-2 设计文档同步 — `subagent-spawn-solution.md` 追加真跑推翻标记 | 文档与代码分叉消除 | ✅ `746091e` |

> **剩余**: T136w (STAGE_MISMATCH) — 代码逻辑正确, 需真跑触发

---

## Phase 35 — T51c-f 根因修复 + prompt 日志增强（BEACON #95）

> 来源：2026-07-23 V2 真跑验证 + 独立 spawn 测试
> 分析报告：`_scratch/test-output/2026-07-23-T51c-f-根因分析-独立测试验证.md`

| T | 内容 | 验收 | 状态 |
|---|------|------|:---:|
| T147a | Fix A: `design_doc.py` `_on_paragraph` — H3 下段落文本自动创建 DesignItem | design_items 覆盖率 2→24 | ✅ `00a7627` |
| T147b | Fix B: `action_builder.py` — component_verifier 从 batch_plan file_targets 注入 implementation_files | context.impl_files 非空 | ✅ `00a7627` |
| T147c | Fix C: `action_builder.py` + `tick_orchestrator.py` — design_spec 为空时 auto-skip，不要求 spawn | action=skip → auto-advance | ✅ `00a7627` |
| T147d | prompt 日志增强 — 每 tick 生成 `-prompt.md`（Part1 指令 + Part2 subagent prompt + Part3 Gate） | prompt-log 可读文件 | ✅ `b28a353` |

> **独立测试结论**：用真实 action JSON 中的 prompt 独立 spawn agent，成功产出 verdict=APPROVE。spawn 指令本身有效——根因是 input data 为空。

---

## Phase 36 — 2026-07-23 深度审计修复

> 来源：`_scratch/reports/2026-07-23-audit.md` | 30/33 已修复，3 项暂缓

| T | 内容 | 验收 | 状态 |
|---|------|------|:---:|
| T148a | TickOrchestrator God Class 拆分 — 17 个 `_after_*` handler 提取为 StageHandler 策略模式 | 1865→<1200 行, 每个 handler 独立文件 | ☐ |
| T148b | StandaloneDriver 职责拆分 — TickRunner + ActionExecutor + TaskFactory | 1213→<600 行 | ☐ |
| T148c | MetricsCollector 拆分 — MetricsStorage + MetricsAnalyzer | 605→<300 行 | ☐ |
