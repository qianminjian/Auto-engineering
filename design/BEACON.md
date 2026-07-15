> 创建：2026-06-24 | 更新：2026-07-15 | 阶段：v5.6 Design — Tick-Based Discrete Invocation + 5 层验证 + Commit→PR→CI/CD Pipeline；PrismScan V5.1 Phase 1 测试完成
> ⚠️ **决策状态翻转管控**：status 列 ✅→❌ 或 ❌→✅ 必须经用户审批。AI 不得自行翻转。详见 `.claude/rules/design-document-inviolability.md` §2。

## 目标与成功标准

1. **`/ae:dev-loop` slash command**：用户触发 Plugin → Python Orchestrator 执行 Architect→Developer→Critic 三阶段 Agent 循环
2. **`ae dev-loop` CLI**：调试入口, stdout JSON 契约 (6 字段)
3. **确定性 Guardrail**：每 Stage 前后自动检查 (G1-G5, pass/block/retry 三态)
4. **Checkpoint 恢复**：SQLite WAL 持久化, 中断可恢复
5. **7+1 道 Gate**：DEFAULT_GATES 7 道: safety → lint → type_check → audit → contract → test → build；按需 Gate 1 道: deep_audit（仅 critic APPROVE 时触发）
6. **5 层验证架构**（v5.6）：critic（diff 级，秒级）→ component_verifier（组件级设计覆盖，Haiku）→ plate_deep_audit（板块级跨组件交互，Sonnet）→ system_verifier（全量设计覆盖，Haiku）→ system_deep_audit（全量代码质量，Sonnet）。频率×范围矩阵：高频窄范围用轻量 Agent，低频全范围用重量 Agent
7. **Init-Loop 接口契约**（IL.1-IL.6）：消费 Init 项目 `.ae-state/init-manifest.json`

## 范围边界

**做：** Tick-Based Discrete Invocation 协议（文件桥接，Python 每次 tick 独立进程）；5 层验证架构（critic → component_verifier → plate_deep_audit → system_verifier → system_deep_audit）；StageRouter T1-T22 + GuardrailChain + 7+1 Gates + ConvergenceJudge + BatchState + SQLite checkpoint；Agent Working Agreements Hook；Init-Loop 接口契约
**不做：** Init Engineering（独立项目）；多 LLM Provider（--llm-provider 选项仅 anthropic，为预留扩展点）、Web UI、SaaS 服务端

## 设计决策

| #  | 决策 | 理由 | 日期 | status |
|----|------|------|------|--------|
| 1-28 | v1.0 → v2.5 完整演进 | LoopEngine/StageGraph/AgentRuntime → Channel/TaskDAG/ConvergenceJudge → Gates/CLI → v1.0 退役 | 2026-06-24→28 | ✅ |
| 29 | **v5.0 路线图: Plugin + Loop + Init 合订** | Plugin 形态 = Bash 委托 `uv run ae <subcommand>`, 控制流在 Python, 参考 LangGraph/AutoGen/CrewAI | 2026-06-29 | ✅ |
| 30 | **Init Engineering 拆分独立项目** | 移除 init/ (528K), 项目只保留 Loop, Init 按 §IL.1-IL.6 实现 | 2026-06-30 | ✅ |
| 31 | **v5.0 深度审计 + 4 P0 修复** | KEY 错误/语义评估器早期返回/init 残留/plugin.json 恢复 (23 项, P0×4) | 2026-07-04 | ✅ |
| 32 | ~~Agent Tool spec 模式~~ (撤销) | Agent 可能跳过规范, markdown 规则无法强制执行 → 改为 JSONL | 2026-07-04 | ❌ |
| 33 | ~~Agent-Engine JSONL 通信协议~~ (已废弃, 被 #39 替代) | Python orchestrator 保留全控制流, architect/critic LLM 走 JSONL stdin/stdout. v5.4 移除 JSONL 路径, 改为 Agent Tool 直接执行模式. v5.6 改为 Tick 文件桥接协议 | 2026-07-04 | ❌ (→ 📝 superseded by #39) |
| **34** | ~~AE_JSONL_MODE 条件开关~~ (已废弃, 被 #39 替代) | JSONL 路径仅在 `AE_JSONL_MODE=1` 时启用. v5.4 删除 `_orchestrator_agent.py` + 所有 AE_JSONL_MODE 引用. v5.6 Tick 协议无需条件开关 | 2026-07-05 | ❌ (→ 📝 superseded by #39) |
| **35** | **GuardrailChain.default() 工厂 + _tasks_from_batch_plan 接入** | guardrail.py 加 default() 返回 5 Guardrail 链；orchestrator 架构师响应中 batch_plan 接入 _tasks_from_batch_plan → developer tasks | 2026-07-05 | ✅ |
| **36** | **TDDGate + StageTransitionGate（借鉴 CrewAI + SonarQube）** | CrewAI GuardrailResult(success/result/error) 三态 + SonarQube 条件门禁模式；TDDGate 强制 Red→Green→Refactor, StageTransitionGate 检查阶段过渡前置条件. v5.4 已删除 — 两者实现的是有状态 Guardrail 检查而非无状态 Gate, 与 Gate.run() 接口不兼容 | 2026-07-05 | ❌ (superseded) |
| **38** | **v5.5 DeepAudit 扩展设计 (T9 plan-refine 回路) + Superpowers 工具集整合** | critic APPROVE 后触发 DeepAuditGate (3-agent 并行全量代码审计), P0>0 或 P1>阈值 → T9 回到 architect 修正计划; P1 阈值从 6 开始自动学习; Architect 集成 Agent-Reach + brainstorming 设计流程; max_iter 从运行日志自动评估; 明确 Python 控制流 vs LLM 推理边界; 整合 Superpowers 5 个 skill (code-reviewer.md 模板 → Critic+DeepAudit, receiving-code-review → Developer, brainstorming+writing-plans → Architect) | 2026-07-06 | ✅ |
| **39** | **v5.6 Tick-Based Discrete Invocation 协议** | 替换连续 while 循环为离散 CLI 调用 (`ae dev-loop --init` → `--tick --result` loop)；文件桥接替代 JSONL stdin/stdout；Python 每次 tick 独立进程 (读 SQLite → 验证 → Guardrail → Gate → ConvergenceJudge → Checkpoint → 输出 action JSON → 退出)；Agent 通过反复调用 `--tick` 驱动循环；Python 永不调 LLM API；8 Agent 规格 (architect/developer/critic + 4 验证层 + BatchState)；StageRouter T1-T22 (含全部验证路径)；BatchState Python 确定性跨 tick 进度管理。33/34 变更为 superseded（JSONL → Tick 文件桥接） | 2026-07-08 | ✅ |
| **40** | **v5.6 5 层验证架构** | ① critic 只做 diff 审查（不判断需求验收，高频秒级）；② component_verifier 组件级设计→代码覆盖映射（Haiku 轻量模型，确定性匹配）；③ plate_deep_audit 板块级跨组件交互质量审计（Sonnet，检查跨组件契约）；④ system_verifier 全量设计覆盖（Haiku，退出闸门一次性）；⑤ system_deep_audit 全量代码质量 6 维审计（Sonnet，退出闸门一次性）。核心原理：频率×范围的矩阵——高频窄范围用轻量 Agent（秒级），低频全范围用重量 Agent（分钟级）。D6 修正：SemanticEvaluator 彻底移除，需求验收由 verifier 层承担。D11: Architect 双模式（模糊需求推理 / 设计文档解析+细化） | 2026-07-08 | ✅ |
| **41** | **v5.6 验证层自动裁剪 (LEAF/PLATE/FULL)** | 基于设计层次自动判定验证深度，不引入手动模式切换。单组件(LEAF, 5 Agent)跳过 plate_deep_audit+system_verifier；单板块多组件(PLATE, 6 Agent)跳过 system_verifier；多板块(FULL, 7 Agent)全量 5 层。判定依据：设计文档/需求本身的层次结构就决定了验证深度——单组件不存在跨组件契约，system_verifier 与 component_verifier scope 完全相同。D13 | 2026-07-08 | ✅ |
| **42** | **v5.6 Pre-flight Gap Analysis + ResearchAgent 分层知识源** | 设计文档模糊章节在主循环前预检（Phase 0，仅 design-doc 模式）：gap_scan 分级(architectural/component/module) → gap_review 用户显式介入(Fill/Research/Defer/Defer+Research) → research 分层检索。architectural gap 阻塞不允许全 defer（G6 Guardrail）。ResearchAgent 四层知识源：Tier0 CLAUDE.md 声明的参考路径+借鉴点 → Tier1 参考代码(三步法,禁批量扫描,96GB事故约束) → Tier2 项目文档KB → Tier3 web fallback；优先策展源、盲搜兜底、findings 标注来源 tier。资产化为项目预置前置(YAGNI)。与 plan_refine 互补：前者消化可预见模糊，后者兜底开发中暴露。D14/D15 | 2026-07-08 | ✅ |
| **43** | **借鉴 Superpowers 提示词技术加固 Agent 行为层 (B11)** | 借鉴 CSO description 纪律/Iron Law/Red Flags/合理化破解表/渐进披露，注入 architect/developer/critic/verifier prompt + SKILL.md + commands（成品文本固化在 §B11，开发直接粘贴）。**不借鉴** Agent 自调节执行模型(=v5.0灭亡根因,保留Python门控)/压力测试评估法(独立项目)/subagent-per-task编排(与Tick loop冲突)。互补：Superpowers说服"应该"，我方门控强制"必须"。D16 | 2026-07-08 | ✅ |
| **44** | **中央提示词管理 (Prompt Registry, B12)** | 提示词散落 3 层(prompts.py/commands/SKILL.md)×3 版本(v5.5/v5.1/v5.0)导致漂移。集中 A/B 类到 `prompts/`(roles+fragments+schema)，frontmatter 声明片段组合，Engine init 一次性加载 + sha256 hash 锁入 checkpoint 保可复现。C 类命令 `.md` 因 Claude Code 发现机制结构约束不移位，共享片段由 `sync-prompts.py` 注入。**不做** 模板引擎/热重载/A-B 框架(YAGNI)。D17 | 2026-07-09 | ✅ |
| **45** | **Commit→PR→CI/CD Pipeline 分层设计 (B13)** | ① **颗粒度**：commit=task / Gate=stage / AI review=batch→system 递进 / PR=loop / merge=PR。人工闸门恒锚 `done` 后（环界线外）。② **PR 颗粒度由输入端控制**（方案 D，呼应 #41 D13），不在 loop 内造切分。方案 C（每板块停）仅强监管作显式开关。③ **CI 双平台**（GitHub Actions + GitLab CI）：单一逻辑入口 + 平台薄壳（DRY）；远程 CI 跑 Gate 非 dev-loop，不需 API_KEY。④ **环内 vs 远程分层**：环内=增量快子集(秒级,skip coverage)，远程=全量权威(pytest+coverage≥90%+build)；**共享 pyproject.toml 标准而非运行时**。⑤ 实施: ci.yml / release.yml fix / code-review.md 校准 / git add -A 收窄 / test gate 增量。D18 | 2026-07-09 | ✅ |
| **46** | **外部 Skill/Agent 依赖管控 (Internalization Constraint, B14)** | 全项目审计：运行时外部 agent 依赖仅在 dev-loop.md v5.1（Plan/code-reviewer//code-review/**gsd-code-fixer** 4 项，2026-07-04 生产失效根因）。原则：① 自有 role+B12 prompt 替代外部 agent spawn（v5.6 已设计，T10 移除）；② 外部技术用**复制内化**（Superpowers→prompts.py 已完成），注释溯源非运行时链接；③ 系统依赖(gh/uv/PyPI)不内化但需 doctor 预检 + 抽象(gh→PRBackend)；④ **gsd-* 零容忍**；⑤ MCP 零运行时调用。D19 | 2026-07-09 | ✅ |
| **47** | **借鉴 Superpowers 验证方法论加固审计与验证层 (B15)** | 合并两组分析（Superpowers 三工具方法论 + `/audit` 三层现状）去重为统一借鉴清单，一律实现为 **Python 确定性门控**（非 Agent 自觉）：REDGuard(TDD RED commit-time 校验,P0) / FreshGate(Gate 证据新鲜度锁定,P1) / RegressionGate(revert-red-restore+审计规则自测,P1)；补 `/audit` 缺口：DeepAuditGate 骨架→实际(P0) / `/audit` 内化去 Superpowers 运行时(P0,B14) / AuditGate 语义层+与 system_deep_audit 分层澄清(P1)。**不借鉴** Agent 自调节(v5.0灭亡根因)/压力测试评估/阈值自学习(YAGNI)。承接 D16+D9。D20 | 2026-07-09 | ✅ |
| **48** | **Init-Loop 契约 v5.6 扩展 (IL.2-IL.5)** | 评估确认契约架构选型正确(单向/文件桥接/只读/forward-compat)，仅补缺口：**A** 抽 `init-manifest.schema.json` 版本化 SSOT(双仓库唯一权威源，Loop 对照 jsonschema 校验/Init 依它生成，复制内化非运行时链接) / **B1** `conventions.ci_platform` 入 manifest(Init 声明，供 B13 CI 壳选型) / **B2** 设计文档内容留 CLI `--design-doc`、manifest 只声明 `structure.design_root` 位置 / **C** monorepo 保留枚举但单包降级+WARN(多包 YAGNI 推迟，不删枚举避免降级) / **D** 消费者驱动契约测试(共享 reference fixture 双仓库同步)。解 spec 债：checkpoints.db 从契约面移除。+IL-AC-06/07/08、Phase 7(T32-T35)。D21 | 2026-07-09 | ✅ |
| **49** | **设计文档深度审计 + 22 项收口深化 (Phase 8)** | 3 并行审计子代理审 v5.6-Design-Loop.md(4214行)+INIT-LOOP-CONTRACT.md：规格成熟度 6.5/10、端到端 2.5/10（内核真实非虚化但全链未接线）。P0×4 全为**代码缺口**(Tick未接线/dev-loop.md v5.1/Init schema/DeepAuditGate骨架)已 T9/T10/T27/T32 跟踪；文档规格缺陷 S-1~S-20+Q-1/Q-2 共 22 项**纯文档收口**(补权威 schema/边界矩阵/枚举，非降级)。**S-1**(B4↔B7 语义评估矛盾)：确认决策 #40/D6 定案——v5.6 全路径无语义评估，B7 2g 属 v5.5 legacy；**代码 semantic_evaluator 全链移除跟踪到 Phase 3 T10d**（随 v5.5 orchestrator 退役，不即时大改以免破坏活跃路径）。无 status 翻转。D22 | 2026-07-11 | ✅ |
| **50** | **PRBackend 选型背书 (T26e)** | 实现验证 T10c(`tools/pr_backend.py`) + T33(`init_contract.py` ci_platform/design_root 提取) 与决策 #45(Commit→PR→CI/CD Pipeline) 一致：① PRBackend ABC + gh/glab 薄壳——单一逻辑入口 + 平台薄壳(DRY)，符合 #45 §③ CI 双平台；② `select_backend(ci_platform)` 从 init-manifest.json 消费 `conventions.ci_platform`(T33)，实现 Init→CI Shell 的全自动平台选择——无需用户指定 `--ci-platform` 标记；③ doctor 预检(`ae doctor`)对 gh/glab 做非致命检测(未安装→WARN, 不阻断)，符合"系统依赖需抽象"约束(#46 §③)。文档数 2 源文件(5543+404行) + 12 tests + 2 提取函数。D23 | 2026-07-12 | ✅ |
| **51** | **环内增量 test_gate + commit_msg 背书 (T26f)** | 实现验证 T16l(`gates/test_gate.py` files_changed→pytest -k) + T16n(`gates/commit_msg_gate.py` Angular 格式) 与决策 #45(环内 vs 远程分层) 一致：① 环内增量测试(`_files_to_pytest_k()` 从 files_changed 推导 test keywords, `-k` 注入 `_build_cmd()`)——环内跑快速子集(秒级, skip coverage)，远程跑全量权威 pypi+coverage≥90%；② commit_msg gate 作为可选 gate(环内 developer stage 后)——Angular 12 类型校验 + subject≤50 字符，可选安装(不在 DEFAULT_GATES，需显式注册)；③ 两者均通过 `-k` 增量 + 可选 gate 设计回避了环内全量测试的 30-60s 延迟——符合 #45 §④ 环内=增量快子集原则。文档数 2 源文件(8187+3407行) + 18 tests(4 test_gate + 14 commit_msg_gate)。D24 | 2026-07-12 | ✅ |
| **52** | **A4 gap_analysis 定案：GapReport schema-SSOT 保留 + 常量复用（非删除）** | 代码审计 A4 原表述"删除孤儿"，深入调研**修正方向**：GapReport/GapItem 是 gap_report_json 的**schema SSOT + 序列化契约 + 校验规则**，与 init-manifest.schema.json 同构——schema 定义体不需生产运行时 import，靠**契约测试**(test_gap_analysis 14 测)保证 dict 数据流符合契约。gap_report 数据流 **dict-native**(跨 tick 序列化存储 + `_build_action` 原样输出 gaps 到 action JSON 给 Agent + in-place resolution 修改)，插入 GapReport 对象需每点 from_dict/asdict 来回转换=负优化。**不删除**(设计 §B10.2 定义模型，删=降级违反 governance)、**不全流程 OO 接线**(负优化)，仅消除**唯一真实瑕疵**：guardrail.py:334 独立重复定义 `_BLOCKING_FORBIDDEN_RESOLUTIONS` → 复用 `gap_analysis._BLOCKING_FORBIDDEN` SSOT(同一 frozenset 对象)。澄清 guardrail:346 注释——与 validate_resolutions 仅共享禁止集常量，校验**时序不同**(apply前拦截 pending_decisions vs apply后审查 report)不可合并。类比 Channel/CheckpointManager 保留决策。D25 | 2026-07-12 | ✅ |
| **53** | **T10d 定案：v5.5 orchestrator + semantic_evaluator 保留（不退役，共存）** | 退役前置只读审计确认 v5.5 orchestrator 是**活代码**：`ae dev-loop "需求"`(裸参数无 tick flag) → cli/__init__.py:212 `_run_v2_orchestrator` → v5.5 连续 while 循环(直调 LLM)，与 v5.6 tick 模式(--init/--tick/--status/--resume → `_run_tick_*`)按设计**并列共存**(docstring :135-142)。semantic_evaluator 唯一运行时消费者=orchestrator.py。用户决策**保留共存**：退役将 (1) 移除可达且有文档的 legacy CLI 路径(破坏性) (2) 需翻转共存决策(设计降级) (3) 级联删 semantic_evaluator 221 行 + 4 测试——撞两条红线，不执行。**修正 D22 中"semantic_evaluator 随 T10d 退役"的计划方向为保留**。类比 Channel/CheckpointManager 保留决策。无 status 翻转。D26 | 2026-07-12 | ✅ |
| **54** | **单引擎 + 双驱动 (Dual-Driver) 远期架构方向 (v7.0) + "永不调 LLM"原则精确化** | 远期规划：v5.6 TickOrchestrator 收敛为**唯一循环引擎**，在 action/result 契约接缝挂两驱动——A(现状) Claude Code Agent 文件桥接填 result / B(v7.0) 独立进程内 AgentRuntime **自带 key** 调 LLM 填 result 回喂同一 tick。ports&adapters：**内部编排完全一致，只换执行后端**；Driver B 复用 v5.5 `_step_2e_run_agent` 执行栈作 tick 填充器，**subsume v5.5 独立跑护城河** → 给 T10d(#53) 明确远期退役出口(换薄驱动非留 fork)。**原则精确化(扩展非翻转,#39/#40 status 不变)**：「Python 永不调 LLM」→「**循环引擎**永不调 LLM；**驱动**可 opt-in 调(需 BYO key)」，引擎保持纯 Python 可测试。**当前只落地 2 项 P0 预留**(Phase 10, 净收益)：action/stage-result 版本化 schema SSOT + 契约测试(T33a)、执行栈标注双驱动共享资产不误删(T33b)。StandaloneDriver 本体 + v5.5 退役 → v7.0(路线图 V7-1~V7-8)。规格 `v7.0-Plan-DualDriver.md`，讨论 `discussion/v7.0-dual-driver-architecture.md`。D27 | 2026-07-12 | ✅ |

## 当前状态

**阶段：** v5.6 里程碑收官 — Tick-Based Discrete Invocation + 5 层验证 + Pre-flight Gap Analysis + Commit→PR→CI/CD Pipeline。Phase 1-10 = 102/102 全完成（含 Phase 10 双驱动接缝预留）。

**最近动作 (2026-07-15)：**
- **v5.6 tick 闭环验证完成**：用 tick driver（`/tmp/_ae_tick_driver6.py`）对 `_scratch/Design-V5.0-plugin-final.md`（71KB PrismScan V5.1 设计文档）跑完整 14 tick 闭环：gap_scan → gap_review → architect → developer → critic → component_verifier → plate_deep_audit → developer(B2) → critic → component_verifier → plate_deep_audit → system_verifier → system_deep_audit → DONE。verdict: GOAL_ACHIEVED。全程 Python TickOrchestrator + SQLite checkpoint 持久化有效、Guardrail + Gate 通过、StageRouter T1-T22 转换正确、5 层验证架构全部触发。
- **P1 Bug 修复（tick 闭环过程中发现）**：
  - `load_latest()` 排序从 `round DESC, created_at DESC` 改为 `created_at DESC`——旧排序 `--init`(round=0) 新建 checkpoint 后 load_latest 仍返回历史高 round 记录，导致 restore 拿到 stale state。修复后 129 相关测试全部通过。
  - `BatchState.from_design_doc()` 组件过滤——原实现保留所有 17 个 plate（含无 batch 的组件），`is_component_complete()` 对 0-batch 组件返回 True（`0 >= 0`），导致 developer 阶段 assertion 失败。修复：filter plates 仅保留有 batch 的 component，无 active component 的 plate 移除。
- **CLAUDE.md 更新**：v5.0→v5.6+v7.0 架构、v5.6 tick CLI、~2132 tests、PrismScan 92 tests、S6.6 Agent 运行时、文档纪律规则。
- **PrismScan V5.1 Phase 1 流转覆盖率补充测试完成**：从 loop flow 流转角度分析 25 条路径，14→23 覆盖（56%→92%）。新增 45 测试。详见 `design/IMPLEMENTATION-TRACKER.md`。
- **文档纪律强化**：用户要求每次操作必须"先记录→再执行→再更新"。新增 memory `feedback-record-before-execute.md`。

**最近动作 (2026-07-12)：**
- **v7.0 双驱动远期架构立项**（决策 #54）：单引擎(TickOrchestrator)+双驱动(Agent/Standalone) ports&adapters，subsume v5.5 独立跑护城河并给 T10d 退役出口；「Python 永不调 LLM」精确化为「引擎不调/驱动可调」(扩展非翻转)。产出 `v7.0-Plan-DualDriver.md` + discussion。**当前落地 Phase 10 两项 P0 预留已实现**(T33a `action.schema.json`+`stage-result.schema.json` 版本化 SSOT + 21 契约测试防漂移；T33b 4 处执行栈「双驱动共享资产」标注)；v7.0 主体(V7-1~V7-8)用户明确搁置、不主动启动，入路线图待后续里程碑
- **T16h ci.yml 薄壳 + ruff 全量转绿** (24afa07)：line-length 100→120 消化中文注释宽度；生产 ruff 全清(E402 上移/E501 折行/SIM108 三元)，测试 per-file-ignore 扩 RUF012/SIM117/B017；`.github/workflows/ci.yml`(uv+ruff+pytest 薄壳)。1968 passed。mypy(203)/coverage-gate 刻意排除薄壳待决策
- **T10d 定案：v5.5 orchestrator + semantic_evaluator 保留**（决策 #53）：退役前置审计确认 v5.5 是活代码(`ae dev-loop` 裸参数路径)，用户决策不退役、保留 v5.5/v6 共存。修正 D22 计划方向。无 status 翻转
- **设计背书收口**：T26e PRBackend 选型背书（决策 #50）+ T26f 环内增量 test_gate + commit_msg（决策 #51）——实现验证通过，与决策 #45 一致。Wave 6 设计背书全部完成

**最近动作 (2026-07-11)：**
- **Phase 3 T9 Tick CLI 接线完成** (fe8bee2/f4e4175/0a2daca)：`ae dev-loop --init/--tick/--status/--resume` + 跨进程 restore（SQLite → EngineState → BatchState/ProgressTree/DesignDoc rehydrate）+ A3 `batch_state_json` 写侧闭合。BatchState 序列化自包含（内嵌轻量 batch_plan seed，plates 不持久化——"不存重 plates"主决策保留）。1717 tests 通过，端到端 3 独立进程验证 thread_id/batch_id 跨进程保真。属实现接线，无 status 翻转、无设计降级
- **设计文档深度审计 + 22 项收口深化** (决策 #49, Phase 8)：3 并行子代理审 4214 行 → 规格 6.5/10、端到端 2.5/10。P0×4 全为代码缺口(已 T9/T10/T27/T32 跟踪)；文档规格缺陷 S-1~S-20+Q-1/Q-2 共 22 项**纯文档收口**（补 CoverageItem/GateVerdict/done verdict 权威 schema + file-bridge 边界矩阵 §C.3.5 + 路径更正 + 过度设计存续论证）。**S-1 语义评估矛盾定案**：v5.6 全路径无语义评估，代码 semantic_evaluator 移除跟踪到 Phase 3 T10d。审计产出 `_scratch/design-audit/`，无 status 翻转
- **Init-Loop 契约 v5.6 扩展** (决策 #48)：`init-manifest.schema.json` 版本化 SSOT + ci_platform/design_root 字段 + monorepo 单包降级 + 消费者驱动契约测试

**下一步：** Phase 1-10 全完成 (102/102)，v5.6 里程碑收官。**v7.0 双驱动主体（V7-1~V7-8）用户明确搁置、不主动启动**，放置待后续里程碑再议；届时 V7-7 v5.5 退役撞决策翻转红线须审批。T10d 已定案保留共存（#53），v7.0 由 Driver B subsume 后再退役。

**阻塞项：** 无

## 设计演进日志

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-11 | **设计文档深度审计 + 22 项收口深化 (Phase 8, 决策 #49)** | 3 并行审计子代理审 v5.6-Design-Loop.md(4214行)+INIT-LOOP-CONTRACT.md：规格 6.5/10、端到端 2.5/10（内核真实非虚化，全链未接线）。分两类：P0×4 全为**代码缺口**(Tick未接线/dev-loop.md v5.1/DeepAuditGate骨架/Init schema)已 T9/T10/T27/T32 跟踪；S-1~S-20+Q-1/Q-2 共 22 项**纯文档规格缺陷收口**——补 CoverageItem/GateVerdict/done verdict 三处权威 schema、file-bridge 边界矩阵(§C.3.5)、B2 决策方列、Tick 路径更正、Guardrail "当前5/目标9"状态列、Q-1/Q-2 过度设计存续论证。**S-1**(B4↔B7 语义评估矛盾)定案：v5.6 全路径无语义评估(呼应 #40/D6)，代码 semantic_evaluator 全链移除跟踪到 Phase 3 T10d（不即时大改以免破坏活跃 v5.5 路径）。全程无 status 翻转、无设计降级（design-document-inviolability 遵守）。审计产出 `_scratch/design-audit/{findings-A/B/C,AUDIT-REPORT}.md`。BEACON 决策 #49 |
| 2026-07-09 | **Init-Loop 契约 v5.6 扩展 (IL.2-IL.5)** | 评估"衔接部分如何定义/是否合理/优化方案"：架构选型正确(单向/文件桥接/只读/forward-compat)，但缺口①跨仓库无 Schema SSOT(文档表+Python函数两处定义→漂移) ②相对 v5.6 滞后(缺 design_doc/ci_platform，monorepo 枚举不自洽)。方案 A(schema SSOT jsonschema 校验)+B(ci_platform/design_root 字段)+C(monorepo 单包降级不删枚举)+D(消费者驱动契约测试)。checkpoints.db 从契约面移除解 spec 债。IL 章重写 + IL-AC-06/07/08 + Phase 7(T32-T35) + D21、discussion §十五。BEACON 决策 #48 |
| 2026-07-09 | **借鉴 Superpowers 验证方法论加固审计与验证层 (B15)** | 两组分析合并去重：① Superpowers 三工具（TDD/verification/requesting-code-review）→ REDGuard+FreshGate+RegressionGate（Python 门控，非 Agent 自觉）；② `/audit` 三层现状（audit.md/audit.py/deep_audit.py）→ 内化+语义层+骨架→实际+分层澄清。+B15 章 6 小节、+D20、+Phase 6(T27-T31)、discussion §十四。BEACON 决策 #47 |
| 2026-07-09 | **Commit→PR→CI/CD Pipeline 专题设计 (B13)** | 5 轮讨论：现状分析(P0 release.yml冲突+无远程CI, P1 code-review.md漂移+虚构引用+git add -A) → 颗粒度金字塔+时间轴+环界线 → PR=plate 是否中断(结论:人工闸门恒在环外,方案D输入端控粒度) → CI 双平台(单一入口+薄壳,DRY) → 环内vs远程(共享pyproject标准非运行时,增量快子集vs全量权威)。+B13 章 9 小节、+D18、+Phase 4b (T16h-T16n)、discussion §十二。BEACON 决策 #45 |
| 2026-07-09 | **中央提示词管理 (Prompt Registry, B12)** | 提示词清单盘点发现散落 3 层(prompts.py/commands/SKILL.md)×3 版本(v5.5/v5.1/v5.0)漂移严重。集中 A/B 类到 `prompts/`(roles+fragments+schema)，frontmatter 声明片段组合，init 一次性加载 + sha256 hash 锁入 checkpoint。C 类命令 `.md` 结构约束不移位，`sync-prompts.py` 注入共享片段。+B12 章 8 小节、+D17、Phase 4 T13-T16d 改写 + T16e/T16f/T16g。文档 2932→3070 行。BEACON 决策 #44 |
| 2026-07-08 | **借鉴 Superpowers 提示词技术加固 Agent 行为层 (B11)** | 分析 Superpowers (9 SKILL.md + 零依赖) 后固化可借鉴项到设计文档：CSO description 纪律 / Iron Law / Red Flags / 合理化破解表（developer/critic/architect/verifier 成品文本）/ Letter-vs-Spirit / 渐进披露。明确不借鉴 3 项（Agent 自调节=v5.0灭亡根因、压力测试评估法=独立项目、subagent-per-task=与Tick冲突）。+B11 章 8 小节、+D16、Phase 4 加 T16c/T16d。文档 2776→2932 行。BEACON 决策 #43 |
| 2026-07-08 | **v5.6 Pre-flight Gap Analysis + ResearchAgent 分层知识源** | 用户提出：设计文档部分章节粗略，应在主循环前预检而非拖到 verifier/audit 才暴露（代价高）。新增 Phase 0：gap_scan 分级 → gap_review 用户介入(Fill/Research/Defer/Defer+Research) → research 分层检索。ResearchAgent 四层知识源(Tier0 CLAUDE.md 声明→Tier3 web)，优先策展源、盲搜兜底、Tier1 三步法禁批量扫描。设计文档 1974→2776 行：+B10 章、+Phase 0 转换 T0.1-T0.8、+G6 Guardrail、+EngineState #28-#32、+3 handler。BEACON 决策 #42 (D14/D15) |
| 2026-07-07 | **v5.5 设计文档三轮审计修复 (8 P0 + 18 P1 + 5 P2) + 实施计划全面更新 + Pre-v5.5 代码审计 + Phase 0 清理任务** | 三轮审计: 控制流补全→数据流一致→章节同步。IMPL-PLAN 扩展为 6 Phase 26 Task: +Phase 0 清理(4) +EngineState(2.0) +severity映射(2.3b) +DocSync骨架(2.6) +batch_plan扩展(3.5) +E2E验证(Phase 5); 全量代码审计确认 v5.0 核心无 stub; +设计→任务对照表 +未覆盖项owner追踪 |
| 2026-07-06 | **v5.5 DeepAudit 扩展设计** | T9 plan-refine 回路 (DeepAudit → architect); P1 阈值自学习; Agent-Reach 集成; max_iter 自适应; Python/LLM 边界映射 |
| 2026-07-06 | **v5.4 JSONL 协议移除 + BEACON 同步 + P0 dead code 清理** | JSONL 路径 (`_orchestrator_agent.py`) 已删除；BEACON.md 移除 7 处 JSONL 引用；`_derive_status` dead code 清理 |
| 2026-07-09 | **外部 Skill/Agent 依赖审计 + 内化约束 (B14)** | 全项目 75.py+3命令+SKILL+5hook 排查：运行时外部依赖仅 dev-loop.md v5.1（Plan/code-reviewer//code-review/gsd-code-fixer 4项）。Superpowers 已复制内化(范本)。gsd-* 零容忍。建立"不 spawn 外部 agent、借鉴=复制非链接、系统依赖需抽象"准入规则。+B14 章 4 小节、+D19、T10 细化为移除 4 项、+T10c(PRBackend)。BEACON 决策 #46 |

## 待解决问题

[已解 DS-10] Tick 延迟 → Python 编排开销 P95<2s（`t_orchestration`=tick墙钟−gate−guard子进程），超标只告警不中断；LLM/gate 墙钟单独观测。规格 C.2.6 | [已解 DS-9] Haiku verifier 误判 → verifier 输出 MISSING/DIVERGED 后插入 Sonnet 窄范围复核，假阳由 system_deep_audit 兜底。规格 B6.6a | [已解 DS-8] plan_refine 环路 → 分源计数 ≤2 + 全局 ≤4，同层第 2 次未解决即停。规格 B2/B4

## 引用文件

@design/v5.6-Design-Loop.md · @design/v7.0-Plan-DualDriver.md · @design/INIT-LOOP-CONTRACT.md · @design/discussion/v5.6-layered-verification-design.md · @design/discussion/v7.0-dual-driver-architecture.md · @design/INDEX.md · @docs/EARS-v5.0.md · @docs/api-reference.md
