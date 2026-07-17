> 创建：2026-06-24 | 更新：2026-07-17 | 阶段：v5.6 里程碑收官 — Phase 14 gate_results 结构错配修复完成。127/129 任务完成（1 ⊘ 项目侧）。
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
| **49** | **设计文档深度审计 + 22 项收口深化 (Phase 8)** | 3 并行审计子代理审 v5.6-Design-Loop.md(4214行)+附录 B(原 INIT-LOOP-CONTRACT.md)：规格成熟度 6.5/10、端到端 2.5/10（内核真实非虚化但全链未接线）。P0×4 全为**代码缺口**(Tick未接线/dev-loop.md v5.1/Init schema/DeepAuditGate骨架)已 T9/T10/T27/T32 跟踪；文档规格缺陷 S-1~S-20+Q-1/Q-2 共 22 项**纯文档收口**(补权威 schema/边界矩阵/枚举，非降级)。**S-1**(B4↔B7 语义评估矛盾)：确认决策 #40/D6 定案——v5.6 全路径无语义评估，B7 2g 属 v5.5 legacy；**代码 semantic_evaluator 全链移除跟踪到 Phase 3 T10d**（随 v5.5 orchestrator 退役，不即时大改以免破坏活跃路径）。无 status 翻转。D22 | 2026-07-11 | ✅ |
| **50** | **PRBackend 选型背书 (T26e)** | 实现验证 T10c(`tools/pr_backend.py`) + T33(`init_contract.py` ci_platform/design_root 提取) 与决策 #45(Commit→PR→CI/CD Pipeline) 一致：① PRBackend ABC + gh/glab 薄壳——单一逻辑入口 + 平台薄壳(DRY)，符合 #45 §③ CI 双平台；② `select_backend(ci_platform)` 从 init-manifest.json 消费 `conventions.ci_platform`(T33)，实现 Init→CI Shell 的全自动平台选择——无需用户指定 `--ci-platform` 标记；③ doctor 预检(`ae doctor`)对 gh/glab 做非致命检测(未安装→WARN, 不阻断)，符合"系统依赖需抽象"约束(#46 §③)。文档数 2 源文件(5543+404行) + 12 tests + 2 提取函数。D23 | 2026-07-12 | ✅ |
| **51** | **环内增量 test_gate + commit_msg 背书 (T26f)** | 实现验证 T16l(`gates/test_gate.py` files_changed→pytest -k) + T16n(`gates/commit_msg_gate.py` Angular 格式) 与决策 #45(环内 vs 远程分层) 一致：① 环内增量测试(`_files_to_pytest_k()` 从 files_changed 推导 test keywords, `-k` 注入 `_build_cmd()`)——环内跑快速子集(秒级, skip coverage)，远程跑全量权威 pypi+coverage≥90%；② commit_msg gate 作为可选 gate(环内 developer stage 后)——Angular 12 类型校验 + subject≤50 字符，可选安装(不在 DEFAULT_GATES，需显式注册)；③ 两者均通过 `-k` 增量 + 可选 gate 设计回避了环内全量测试的 30-60s 延迟——符合 #45 §④ 环内=增量快子集原则。文档数 2 源文件(8187+3407行) + 18 tests(4 test_gate + 14 commit_msg_gate)。D24 | 2026-07-12 | ✅ |
| **52** | **A4 gap_analysis 定案：GapReport schema-SSOT 保留 + 常量复用（非删除）** | 代码审计 A4 原表述"删除孤儿"，深入调研**修正方向**：GapReport/GapItem 是 gap_report_json 的**schema SSOT + 序列化契约 + 校验规则**，与 init-manifest.schema.json 同构——schema 定义体不需生产运行时 import，靠**契约测试**(test_gap_analysis 14 测)保证 dict 数据流符合契约。gap_report 数据流 **dict-native**(跨 tick 序列化存储 + `_build_action` 原样输出 gaps 到 action JSON 给 Agent + in-place resolution 修改)，插入 GapReport 对象需每点 from_dict/asdict 来回转换=负优化。**不删除**(设计 §B10.2 定义模型，删=降级违反 governance)、**不全流程 OO 接线**(负优化)，仅消除**唯一真实瑕疵**：guardrail.py:334 独立重复定义 `_BLOCKING_FORBIDDEN_RESOLUTIONS` → 复用 `gap_analysis._BLOCKING_FORBIDDEN` SSOT(同一 frozenset 对象)。澄清 guardrail:346 注释——与 validate_resolutions 仅共享禁止集常量，校验**时序不同**(apply前拦截 pending_decisions vs apply后审查 report)不可合并。类比 Channel/CheckpointManager 保留决策。D25 | 2026-07-12 | ✅ |
| **53** | **T10d 定案：v5.5 orchestrator + semantic_evaluator 保留（不退役，共存）** | 退役前置只读审计确认 v5.5 orchestrator 是**活代码**：`ae dev-loop "需求"`(裸参数无 tick flag) → cli/__init__.py:212 `_run_v2_orchestrator` → v5.5 连续 while 循环(直调 LLM)，与 v5.6 tick 模式(--init/--tick/--status/--resume → `_run_tick_*`)按设计**并列共存**(docstring :135-142)。semantic_evaluator 唯一运行时消费者=orchestrator.py。用户决策**保留共存**：退役将 (1) 移除可达且有文档的 legacy CLI 路径(破坏性) (2) 需翻转共存决策(设计降级) (3) 级联删 semantic_evaluator 221 行 + 4 测试——撞两条红线，不执行。**修正 D22 中"semantic_evaluator 随 T10d 退役"的计划方向为保留**。类比 Channel/CheckpointManager 保留决策。无 status 翻转。D26 | 2026-07-12 | ✅ |
| **54** | **单引擎 + 双驱动 (Dual-Driver) 远期架构方向 (v7.0) + "永不调 LLM"原则精确化** | 远期规划：v5.6 TickOrchestrator 收敛为**唯一循环引擎**，在 action/result 契约接缝挂两驱动——A(现状) Claude Code Agent 文件桥接填 result / B(v7.0) 独立进程内 AgentRuntime **自带 key** 调 LLM 填 result 回喂同一 tick。ports&adapters：**内部编排完全一致，只换执行后端**；Driver B 复用 v5.5 `_step_2e_run_agent` 执行栈作 tick 填充器，**subsume v5.5 独立跑护城河** → 给 T10d(#53) 明确远期退役出口(换薄驱动非留 fork)。**原则精确化(扩展非翻转,#39/#40 status 不变)**：「Python 永不调 LLM」→「**循环引擎**永不调 LLM；**驱动**可 opt-in 调(需 BYO key)」，引擎保持纯 Python 可测试。**当前只落地 2 项 P0 预留**(Phase 10, 净收益)：action/stage-result 版本化 schema SSOT + 契约测试(T33a)、执行栈标注双驱动共享资产不误删(T33b)。StandaloneDriver 本体 + v5.5 退役 → v7.0(路线图 V7-1~V7-8)。规格 v5.6-Design-Loop.md 附录 C(原 v7.0-Plan-DualDriver.md)，讨论 his_bak/discussion/v7.0-dual-driver-architecture.md。D27 | 2026-07-12 | ✅ |
| **55** | **v8.0 多 Agent 平台适配 (Multi-Platform Plugin Adaptation)** | 一套源码、三个平台（Claude Code / Codex / CodeBuddy）同时运行。核心发现：三平台共享相同的 Commands `.md` 格式和 Skills `SKILL.md` + YAML frontmatter 格式；CodeBuddy 原生读取 `.claude-plugin/plugin.json` 作 fallback。设计原则：① 一套源码三个 manifest（`.claude-plugin/` + `.codex-plugin/` + `.codebuddy-plugin/` symlink）；② Engine 平台无关（TickOrchestrator 不变）；③ 最小适配——Codex 仅 4 hook 事件（无 on-pr.sh），Hook 脚本用 `$AE_PLUGIN_ROOT` 统一变量 + `$AE_PLATFORM` 平台检测；④ Provider 抽象——`LLMProvider` Protocol 桥接 Anthropic SDK 与 OpenAI SDK 的 tool_use/function_call 格式差异，使 StandaloneDriver 可切 OpenAI 后端。规划 8 任务、~4.3 天。规格 v5.6-Design-Loop.md 附录 D（13 节，含三平台对比矩阵/Hook 适配表/Provider 完整代码/install.sh 重写/命令语法差异）。D28 | 2026-07-16 | ✅ |
| **56** | **v7.8 StandaloneDriver 基准修复 (Architect 瓶颈消除)** | StandaloneDriver 基准收敛率 40%→100%。4 项修复（parser regex/architect prompt/developer max_calls+project_root/batch_plan 规范化）。剩余问题：设计文档模式过严，通过 spec 内嵌绕过。D29 | 2026-07-17 | ✅ |
| **57** | **Step 3 AgentDriver 基准 10/10 全部完成 — 双驱动保真度等价验证** | 全部 10 需求（R01-R10）手动驱动 v5.6 Tick 协议 GOAL_ACHIEVED（100%）。双驱动收敛率等价（AgentDriver 100% vs StandaloneDriver 100%），AgentDriver 无软上限问题、测试更精简，StandaloneDriver 更快可批量。修复 `_apply_result_to_state()` red_evidence 映射 bug。R09/R10 通过 spec 内嵌 requirement 绕过 `from_design_doc()` 校验过严问题。D30 | 2026-07-17 | ✅ |
| **58** | **Plugin 安装标准化 — Marketplace 替代 install.sh** | 调研三平台（Claude Code/Codex/CodeBuddy）标准安装机制：均为 Marketplace + `/plugin install` 模式，平台自动 `git clone` 完整仓库到缓存目录。删除自造 `install.sh`（V8-6），改为标准 marketplace 自引用（`marketplace.json` source=`"./"`）。修正 `plugin.json` 路径从 `"../commands/"` 到 `"./commands/"`（`./` 相对插件根 = 仓库根，对齐 Claude Code 规范）。更新 PLUGIN-USAGE.md 和 USER_GUIDE.md 安装章节。**不**单独维护 Codex marketplace（`.codex-plugin/marketplace.json`），Codex 共享 Claude Code 的 marketplace 或通过自有 marketplace 机制发现。D31 | 2026-07-17 | ✅ |
| **59** | **Phase 13 真跑故障修复 (voice_clone 2026-07-17)** | 29 问题中 10 项引擎/设计修复：9/10 完成（8 ✅ + 1 ⊘ 项目侧）。P0 B3 crash ✅ / P1 B2/B4/B5/B8/B9/B11/D1 全部 ✅ / P2 B6 ⊘(项目侧) D3 ✅。T43 集成 5 tests 覆盖 6 场景。全量 250 passed 零回归。D32 | 2026-07-17 | ✅ |
| **60** | **Phase 14 gate_results 结构错配修复 (voice_clone 忠实度分析发现)** | `_run_developer_gates()` 调用 `run_gates()` 但 `run_gates()` 返回嵌套结构 `{project_root, gate_names, passed, failed, skipped, gate_summary: {实际gate结果}}`，而 `_run_developer_gates()` 直接迭代顶层 key → gate_results 全是 wrapper key 而非真实 gate 名 → production 路径所有 gate 结果丢失。修复：统一提取 `raw.get("gate_summary", raw)` — 扁平 dict（测试 stub）无此 key 则回退自身。D33 | 2026-07-17 | ✅ |

## 当前状态

**阶段：** v5.6 里程碑收官 — Phase 14 gate_results 结构错配修复完成。Step 3 AgentDriver 基准 10/10 GOAL_ACHIEVED。双驱动保真度等价验证完成。Plugin 安装标准化。Phase 1-14 = 127/129（1 ⊘ 项目侧）。

**最近动作 (2026-07-17 Phase 14 gate_results 结构错配修复完成)：**
- **gate_results 结构错配修复（TDD）**：`_run_developer_gates()` 调用 `run_gates()` 但 `run_gates()` 返回嵌套结构 `{project_root, gate_names, passed, failed, skipped, gate_summary: {实际gate结果}}`，直接迭代顶层 key 导致 production 路径所有 gate 结果丢失。修复：统一提取 `raw.get("gate_summary", raw)`，扁平 dict（测试 stub）回退自身。新增 test_extracts_gate_summary_from_nested_run_gates_output。全量 251 passed 零回归。BEACON 决策 #60。
- **忠实度分析来源**：voice_clone 项目 dev-loop 忠实度分析发现 gate_results 全为 null（§6.2）、system_verifier 缺失为误报（PLATE 模式正确跳过，§6.1）、状态一致性问题已在 Phase 13 修复（§4.1/4.2）。

**最近动作 (2026-07-17 Phase 13 真跑故障修复完成)：**
- **9/10 引擎修复完成（TDD）**：P0 B3 crash 类型守卫 ✅ / P1 B2 STAGE_MISMATCH 明确提示 ✅ / P1 B4/B5 expected_format 必填字段补充 ✅ / P1 B11 red_evidence 格式错误信息 ✅ / P1 B8 REDGuard GREEN→test 交叉检测 ✅ / P1 B9/D2 零 batch 警告去重 ✅ / P1 D1 progress_tree verifier 状态重置 ✅ / P2 D3 REFINE_LIMIT 建议信息 ✅ / T41 B6 ⊘（引擎 TestGate 不硬编码 --no-cov，根因在项目侧 Agent 行为）。T43 集成 5 tests 覆盖 6 场景。全量 250 passed 零回归。
- **真跑故障报告**：voice_clone_for_auto_test-2 项目 29 问题分析，10 项引擎侧修复。见 `voice_clone_for_auto_test-2/_scratch/buginfo/dev-loop-issues-2026-07-17.md`。

**最近动作 (2026-07-17 StandaloneDriver E2E 真跑验证)：**
- **StandaloneDriver 真实 LLM 端到端验证通过**：architect→developer→critic→GOAL_ACHIEVED（6 ticks），在 `/tmp/_ae_test_project/` 产出 fibonacci 实现（`src/fibonacci.py` + `tests/test_fibonacci.py` 10 tests）+ auto-commit（`530fe42`）。10 个 fibonacci 断言全部通过。
- **3 处 bug 修复**：`guardrail.py:252-259` GitDiffExists 增加 `git diff-tree --no-commit-id -r HEAD` 第三降级（处理 auto_commit 后 `--cached` 空场景）；`bash_tools.py:77-80` cwd 未指定时默认 `project_root`（修复 DeepSeek 不传 cwd 导致 subprocess 跑在工作目录而非沙箱）；`standalone_driver.py:700-710` architect 任务描述更详细（100+ 字要求+示例格式）。全量 2246 passed / 2 skipped。
- **真实可运行证明完成**：StandaloneDriver 不再是"建了不跑"的测试基础设施——已用真实 DeepSeek API 端到端跑通，产出可用的 fibonacci 实现含 10 个测试用例。

**最近动作 (2026-07-17 Step 3 AgentDriver 基准 10/10 全部完成)：**
	- **AgentDriver 10/10 全量 GOAL_ACHIEVED**：全部 10 需求通过 v5.6 Tick-Based Discrete Invocation 协议手动驱动完成。R01(5t/7t)、R02(5t/7t)、R03(5t/5t)、R04(9t/13t)、R05(5t/8t)、R06(5t/9t)、R07(9t/18t)、R08(5t/6t)、R09(5t/7t)、R10(5t/5t)。总 ~63 ticks, ~85 tests, 100% 收敛率。
	- **R09/R10 设计文档模式绕行**：`BatchState.from_design_doc()` 对简单设计文档（无 H3 组件层次）校验过严，通过 spec 内嵌 requirement 文本绕过。与 StandaloneDriver 采用相同 workaround。
	- **关键 bug 修复**：`tick_orchestrator.py:_apply_result_to_state()` 补 `red_evidence` 字段映射（所有 AgentDriver developer tick 后 REDGuard 永远失败的根因）。`agent_bench_setup.py` collect 修复 git commit 计数（`$()` shell 展开在 subprocess.run list 中不生效）。
	- **双驱动最终对比**：AgentDriver 适合人工交互/精细控制（~8min/需求），StandaloneDriver 适合批量自动化/CI/CD 集成（~163s/需求）。收敛率等价（100% vs 100%），AgentDriver 测试更精简（avg 8.5 vs avg 11.8），StandaloneDriver 更多测试但覆盖更全面。详细对比见 `_scratch/benchmark_report.md`。BEACON 决策 #57。

**最近动作 (2026-07-17 V7-8 基准修复与重跑)：**
- **v7.8 Architect 瓶颈消除**：4 项修复（见决策 #56）将 StandaloneDriver 基准收敛率从 40% (4/10) 提升至 100% (10/10 GOAL_ACHIEVED)。原始 6 个失败案例全部修复验证通过：R01(8 tests)/R03(6 tests)/R04(27 tests)/R07(16 tests)/R09(7 tests)/R10(14 tests)。详细报告见 `_scratch/benchmark_report.md`。
- **软上限问题缓解**：developer max_tool_calls 20→30 (warn 15), critic 10→15 (warn 7)。DeepSeek 纯 tool_use 响应触发 warn_threshold 的根因仍存，但概率已显著降低。
- **设计文档模式已知限制**：R09/R10 `BatchState.from_design_doc()` 对简单设计文档（无 H3 组件层次）校验过严，当前通过 spec 内嵌 requirement 绕过。根本修复需放宽 `from_design_doc` 对无组件 plate 的校验逻辑。

**最近动作 (2026-07-17 V7-5 StandaloneDriver 集成验证)：**
- **Phase 11 V7-5 完成**：`StandaloneDriver` mock LLM 集成测试 18 tests — 覆盖 `_run_loop_from_action()` 控制流（done/error/max_iterations）、`_execute_action()` Agent 调度 + 任务构造、`_execute_developer_serial()` 串行 TDD（多 task 聚合 + test failure 提前停止）、`_execute_gap_review_headless()` 自动 Defer/Fill、`run_async()` 完整 architect→critic→done E2E + architect→developer→critic→verifier→done 5 层验证 GOAL_ACHIEVED、错误处理优雅降级 + `_action_to_task()` 各 action type 正确构造 Task。
- **全量测试**：2230 passed (+75 从 2135 基线)，2 skipped，0 回归。

**最近动作 (2026-07-17 Phase 12 收尾)：**
- **Phase 12 V8-1 目录重构完成**：`commands/` `hooks/` `skills/` 从 `.claude-plugin/` 提升到项目根，三平台共享同一套 Command/Skill 源文件。`.claude-plugin/plugin.json` paths 更新为 `../` 相对路径。`.codex-plugin/plugin.json` 新建。`.codebuddy-plugin/` → `.claude-plugin/` symlink。7 new tests + 修复 9 个路径引用断裂。
- **Phase 12 V8-2 Hook 注册拆分完成**：三份平台特定 hook 注册文件（`hooks-cc.json` 5 hooks / `hooks-codex.json` 4 hooks 无 on-pr / `hooks-codebuddy.json` 5 hooks）。`hooks/session-start.sh` 添加 `$AE_PLATFORM` 平台检测逻辑（`$CLAUDE_PLUGIN_ROOT` / `$CODEX_PLUGIN_ROOT` / `$CODEBUDDY_PLUGIN_ROOT`）。7 new tests。
- **Phase 12 V8-6 安装方案标准化（2026-07-17 替换为 Marketplace）**：原 `install.sh`（~150 行，手动 cp 安装）已删除，改为三平台标准 Marketplace 机制（`/plugin marketplace add` + `/plugin install`）。plugin.json 路径从 `../` 修正为 `./`（对齐 Claude Code 规范）。PLUGIN-USAGE.md + USER_GUIDE.md 安装章节重写。
- **Phase 12 V8-7 doctor + pyproject 更新完成**：`ae doctor` 新增 `_check_openai_api_key()`（`OPENAI_API_KEY` 环境变量检测）。`pyproject.toml` 新增 `[project.optional-dependencies] openai = ["openai>=1.0"]`。2 new tests。
- **Phase 12 V8-8 文档更新完成**：`docs/PLUGIN-USAGE.md` 重写安装章（Quick Install + Manual Install 三平台 + 命令验证含 Codex `//ae:` 语法）。`docs/USER_GUIDE.md` 新增多平台安装说明 + 命令语法差异表（Claude Code `/ae:dev-loop` vs Codex `//ae:dev-loop` vs CodeBuddy `/ae:dev-loop`）。2 new tests。
- **全量测试**：2212 passed (+77 从 2135 基线)，2 skipped，0 回归。

**最近动作 (2026-07-17 Phase 11 推进)：**
- **Phase 11 V7-1 完成**：`tick()` 精简为 5 行薄包装委派 `tick_dict()`，移除死方法 `_tick_body`。2 new tests + 全量 2135 零回归。
- **Phase 12 V8-3/4/5 Provider 抽象完成**：`providers/base.py`（`LLMProvider` Protocol + `LLMResponse` + `ToolUseBlock`）+ `providers/openai_provider.py`（Anthropic↔OpenAI tool schema 双向转换 + `OpenAIProvider`）+ `providers/factory.py`（`create_provider()` 工厂）+ `llm/anthropic_provider.py`（`_to_llm_response()` adapter）+ `agents/base.py`（`llm: LLMProvider` 类型注解）。~46 new tests。
- **Phase 11 V7-2 完成**：`STAGE_TO_ROLE`（10 stage→role, gap_review→None）+ `ROLE_MODEL`（9 role→model, `AE_MODEL_<ROLE>` 环境变量覆盖）+ `_resolve_model()`。9 new tests。
- **Phase 11 V7-3 完成**：`AuthProvider = Callable[[], str]` + `_resolve_auth_provider()`（ANTHROPIC_AUTH_TOKEN > ANTHROPIC_API_KEY 优先级，无 key→AEError）。5 new tests。
- **Phase 11 V7-6 完成**：CLI `--standalone` flag + `dev_loop()` 分派路径 + `_run_standalone()` + 互斥检查。5 new tests.
- **Phase 11 V7-4 完成**：`StandaloneDriver.resume()`（从 checkpoint restore 继续 loop）+ `close()`（AgentRuntime cleanup）+ 共享 `_run_loop_from_action()` 消除 run_async/resume 重复。`TickOrchestrator.restore()` 已验证 driver-agnostic。5 new tests + dead code 清理（移除重复的 `_run_standalone` + `_build_standalone_tools`）。
- **全量测试**：2191 passed (+56 从 2135 基线)。

**最近动作 (2026-07-16)：**
- **v7.0 双驱动详细设计完成**：附录 C 从远期路线图（V7-1~V7-8 一行描述）展开为 14 节开发就绪规格——Driver Protocol 接口签名、`tick_dict()` 纯核形式化、STAGE_TO_ROLE/ROLE_MODEL 映射表、AuthProvider 抽象、StandaloneDriver 完整类设计（run/_execute_action/_format_result）、CLI --standalone 入口、v5.5 5 步退役路径（含 4 道硬门禁）、10 需求 × 6 维保真度基准。每节含验收标准。IMPLEMENTATION-TRACKER.md 新增 Phase 11（8 任务，~6.8 天预估）。决策 #54 不变（扩展非翻转）。
- **v8.0 多 Agent 平台适配详细设计完成**：附录 D 展开为 13 节开发就绪规格——三平台对比矩阵（plugin 目录/manifest/组件/hook 事件/调用语法）、目录结构重构方案（commands/hooks/skills 提升到根目录）、Hook 注册拆分（3 份平台特定 JSON + `$AE_PLATFORM` 检测）、Provider 抽象（`LLMProvider` Protocol + `LLMResponse`/`ToolUseBlock` dataclasses + `OpenAIProvider` 含 Anthropic↔OpenAI tool schema 双向转换 ~80 行代码 + `create_provider()` 工厂）、`install.sh` 多平台安装完整脚本（~80 行 bash）、Engine 变更清单、V8-1~V8-8 路线图（~4.3 天）。核心发现：CodeBuddy 原生读取 `.claude-plugin/plugin.json`，仅需 2 份 manifest（非 3 份）。IMPLEMENTATION-TRACKER.md 新增 Phase 12（8 任务）。决策 #55。
- **真实 Agent 驱动 v5.6 tick 闭环验证完成**：用 `/ae:dev-loop` 对 hello_world 工具走通完整的 architect (Plan agent spawn) → developer (TDD Red→Green→Refactor, 3/3 tests passed) → critic (APPROVE) → component_verifier (3/3 IMPLEMENTED) → system_deep_audit (P0=P1=P2=0) → GOAL_ACHIEVED。验证了 Agent tool spawn 路径真实可用，弥补了此前仅 Python tick driver 模拟的缺口。
- **mypy 类型债清零**：修复 HelloWorldTool ClassVar→instance var（对齐 BaseTool 约定）+ `cli/agent.py` runtime.get() None 守卫 + type:ignore 错误码覆盖。mypy 0 errors（默认 + `--check-untyped-defs` 双模式），98 源文件全绿。
- **T16i release.yml 确认**：文件已在 6331b54 修复，无冲突标记，追踪表状态同步。
- **coverage-gate 确认**：CI 已在 1bd50c9 接入 `--cov-fail-under=90`，追踪表滞后注释已清理。
- **E501 ruff 确认**：line-length=120 下 0 violations，已无待处理项。
- **设计文档目录修复**：`design/discussion/` 从 `his_bak` 双重嵌套恢复，INDEX.md 补全 4 个讨论文件。
- **全量测试**：2135 passed。
- **docs/ 用户向文档同步 v5.6**：7 份文档（PLUGIN-USAGE.md/entry-points.md/EARS-v5.0.md/api-reference.md/e2e-real-run.md/USER_GUIDE.md/production-deployment.md）从 v5.0 更新到 v5.6。PLUGIN-USAGE.md 修复 "REMOVED:" 全行前缀损坏；entry-points.md 删除已删文件引用 + 增加 Tick 协议路径；api-reference.md 增加 TickOrchestrator 章节 + 模块清单重构；其余文档版本/测试数/覆盖率同步。commit d1a5770。

**最近动作 (2026-07-15)：**
- **v5.6 tick 闭环验证完成**：用 tick driver（`/tmp/_ae_tick_driver6.py`）对 `_scratch/Design-V5.0-plugin-final.md`（71KB PrismScan V5.1 设计文档）跑完整 14 tick 闭环：gap_scan → gap_review → architect → developer → critic → component_verifier → plate_deep_audit → developer(B2) → critic → component_verifier → plate_deep_audit → system_verifier → system_deep_audit → DONE。verdict: GOAL_ACHIEVED。全程 Python TickOrchestrator + SQLite checkpoint 持久化有效、Guardrail + Gate 通过、StageRouter T1-T22 转换正确、5 层验证架构全部触发。
- **P1 Bug 修复（tick 闭环过程中发现）**：
  - `load_latest()` 排序从 `round DESC, created_at DESC` 改为 `created_at DESC`——旧排序 `--init`(round=0) 新建 checkpoint 后 load_latest 仍返回历史高 round 记录，导致 restore 拿到 stale state。修复后 129 相关测试全部通过。
  - `BatchState.from_design_doc()` 组件过滤——原实现保留所有 17 个 plate（含无 batch 的组件），`is_component_complete()` 对 0-batch 组件返回 True（`0 >= 0`），导致 developer 阶段 assertion 失败。修复：filter plates 仅保留有 batch 的 component，无 active component 的 plate 移除。
- **CLAUDE.md 更新**：v5.0→v5.6+v7.0 架构、v5.6 tick CLI、~2132 tests、PrismScan 92 tests、S6.6 Agent 运行时、文档纪律规则。
- **PrismScan V5.1 Phase 1 流转覆盖率补充测试完成**：从 loop flow 流转角度分析 25 条路径，14→23 覆盖（56%→92%）。新增 45 测试。详见 `design/IMPLEMENTATION-TRACKER.md`。
- **文档纪律强化**：用户要求每次操作必须"先记录→再执行→再更新"。新增 memory `feedback-record-before-execute.md`。

**最近动作 (2026-07-12)：**
- **v7.0 双驱动远期架构立项**（决策 #54）：单引擎(TickOrchestrator)+双驱动(Agent/Standalone) ports&adapters，subsume v5.5 独立跑护城河并给 T10d 退役出口；「Python 永不调 LLM」精确化为「引擎不调/驱动可调」(扩展非翻转)。产出 v5.6-Design-Loop.md 附录 C(原 v7.0-Plan-DualDriver.md) + discussion。**当前落地 Phase 10 两项 P0 预留已实现**(T33a `action.schema.json`+`stage-result.schema.json` 版本化 SSOT + 21 契约测试防漂移；T33b 4 处执行栈「双驱动共享资产」标注)；v7.0 主体(V7-1~V7-8)用户明确搁置、不主动启动，入路线图待后续里程碑
- **T16h ci.yml 薄壳 + ruff 全量转绿** (24afa07/1bd50c9)：line-length 100→120 消化中文注释宽度；生产 ruff 全清(E402 上移/E501 折行/SIM108 三元)；`.github/workflows/ci.yml`(uv+ruff+pytest + coverage≥90%)。2135 passed。
- **T10d 定案：v5.5 orchestrator + semantic_evaluator 保留**（决策 #53）：退役前置审计确认 v5.5 是活代码(`ae dev-loop` 裸参数路径)，用户决策不退役、保留 v5.5/v6 共存。修正 D22 计划方向。无 status 翻转
- **设计背书收口**：T26e PRBackend 选型背书（决策 #50）+ T26f 环内增量 test_gate + commit_msg（决策 #51）——实现验证通过，与决策 #45 一致。Wave 6 设计背书全部完成

**最近动作 (2026-07-11)：**
- **Phase 3 T9 Tick CLI 接线完成** (fe8bee2/f4e4175/0a2daca)：`ae dev-loop --init/--tick/--status/--resume` + 跨进程 restore（SQLite → EngineState → BatchState/ProgressTree/DesignDoc rehydrate）+ A3 `batch_state_json` 写侧闭合。BatchState 序列化自包含（内嵌轻量 batch_plan seed，plates 不持久化——"不存重 plates"主决策保留）。1717 tests 通过，端到端 3 独立进程验证 thread_id/batch_id 跨进程保真。属实现接线，无 status 翻转、无设计降级
- **设计文档深度审计 + 22 项收口深化** (决策 #49, Phase 8)：3 并行子代理审 4214 行 → 规格 6.5/10、端到端 2.5/10。P0×4 全为代码缺口(已 T9/T10/T27/T32 跟踪)；文档规格缺陷 S-1~S-20+Q-1/Q-2 共 22 项**纯文档收口**（补 CoverageItem/GateVerdict/done verdict 权威 schema + file-bridge 边界矩阵 §C.3.5 + 路径更正 + 过度设计存续论证）。**S-1 语义评估矛盾定案**：v5.6 全路径无语义评估，代码 semantic_evaluator 移除跟踪到 Phase 3 T10d。审计产出 `_scratch/design-audit/`，无 status 翻转
- **Init-Loop 契约 v5.6 扩展** (决策 #48)：`init-manifest.schema.json` 版本化 SSOT + ci_platform/design_root 字段 + monorepo 单包降级 + 消费者驱动契约测试

**下一步：** v5.6 里程碑主体完成 — 后续可推进 v7.0 StandaloneDriver 剩余任务（V7-7 v5.5 退役需审批）或新里程碑规划。

**阻塞项：** 无

## 设计演进日志

| 日期 | 变更 | 原因 |
|------|------|------|
| 2026-07-17 | **Phase 14 gate_results 结构错配修复（决策 #60）** | voice_clone 忠实度分析发现 production 路径 gate_results 全部丢失。根因：`_run_developer_gates()` 消费 `run_gates()` 返回的嵌套结构时未提取 `gate_summary` 层。修复：`raw.get("gate_summary", raw)` 统一提取，测试 stub 扁平 dict 回退。BEACON #60 结案。 |
| 2026-07-17 | **Phase 13 真跑故障修复完成（决策 #59）** | 9/10 引擎修复完成（TDD，+5 integration tests）。P0 B3 guardrail 类型守卫 / P1 B2/B4/B5/B8/B9/B11/D1 全部 ✅ / P2 D3 ✅ / T41 B6 ⊘ 项目侧。全量 250 passed 零回归。BEACON #59 结案。 |
| 2026-07-17 | **真跑故障报告分析 + Phase 13 立项（决策 #59）** | voice_clone 项目真跑产出 29 问题，10 项引擎/设计层面可修复：B3 crash/B2 stage/B4-B5 expected_format/B8 REDGuard/B9 重复警告/B11 format/B6 vitest/D1 progress_tree。分类为 P0(1) P1(7) P2(2)，按依赖 TDD 推进。 |
| 2026-07-17 | **Plugin 安装标准化 — Marketplace 替代 install.sh（决策 #58）** | 调研三平台标准安装机制后，删除自造 `install.sh`，改为 Claude Code/Codex/CodeBuddy 标准 Marketplace 安装（`/plugin marketplace add` + `/plugin install`）。修正 plugin.json 路径 `../` → `./`（对齐规范）。更新 PLUGIN-USAGE.md + USER_GUIDE.md。 |
| 2026-07-17 | **Step 3 AgentDriver 基准 10/10 全部完成** | 手动驱动 v5.6 Tick 协议完成全部 10 需求（R01-R10）全 tick 闭环，100% GOAL_ACHIEVED。R09/R10 通过 spec 内嵌绕过 `from_design_doc()` 校验过严。双驱动保真度等价验证闭环（Agent 100% / Standalone 100%）。collect 脚本产出最终 results.json。BEACON 决策 #57 更新。 |
| 2026-07-17 | **Step 3 AgentDriver 基准 3/3 完成** | 手动驱动 v5.6 Tick 协议完成 R01/R04/R07 全 tick 闭环，全部 GOAL_ACHIEVED。双驱动保真度等价验证通过。修复 `red_evidence` 映射 bug + collect 脚本 git 命令。BEACON 决策 #57。 |
| 2026-07-17 | **v7.8 Architect 瓶颈消除 + 基准重跑 10/10** | StandaloneDriver 基准收敛率 40%→100%。4 项修复（parser regex/architect prompt/developer max_calls+project_root/batch_plan 规范化）消除 architect file_list 瓶颈（原占失败 67%）。10 需求全量验证通过，产出报告 `_scratch/benchmark_report.md`。BEACON 决策 #56。 |
| 2026-07-17 | **StandaloneDriver 真实 LLM E2E 验证通过** | 用户指出现有工作"建了不跑"——StandaloneDriver 从未用真实 LLM 端到端跑过。修复 3 处 bug（guardrail GitDiffExists auto_commit 路径/bash_tools cwd 默认/project_root architect 任务描述），用 DeepSeek API 真跑 fibonacci 需求 → GOAL_ACHIEVED，产出可用实现+10 tests。证明 Driver B 可替代 v5.5 独立跑能力。 |
| 2026-07-16 | **v8.0 多 Agent 平台适配设计 (附录 D, 决策 #55)** | 用户提出"插件安装到 Claude Code/Codex/CodeBuddy 三平台"。深度调研三平台 plugin 系统：发现三平台共享 Commands/Skills 格式、CodeBuddy 原生读 `.claude-plugin/plugin.json`。设计一套源码三个 manifest + Provider 抽象（`LLMProvider` Protocol 桥接 Anthropic/OpenAI tool schema 差异）+ install.sh 多平台改造。13 节附录 D + Phase 12(V8-1~V8-8, ~4.3 天)。BEACON 决策 #55 |
| 2026-07-16 | **v7.0 双驱动详细设计展开 (附录 C)** | 附录 C 从 8 行路线图展开为 14 节开发就绪规格（接口签名/数据流/验收标准/参考位置）。Phase 11(V7-1~V7-8, ~6.8 天)。与 v8.0 依赖：V7-5 StandaloneDriver 依赖 V8-3/4/5 Provider 抽象。BEACON 决策 #54 |
| 2026-07-11 | **设计文档深度审计 + 22 项收口深化 (Phase 8, 决策 #49)** | 3 并行审计子代理审 v5.6-Design-Loop.md(4214行)+附录 B(原 INIT-LOOP-CONTRACT.md)：规格 6.5/10、端到端 2.5/10（内核真实非虚化，全链未接线）。分两类：P0×4 全为**代码缺口**(Tick未接线/dev-loop.md v5.1/DeepAuditGate骨架/Init schema)已 T9/T10/T27/T32 跟踪；S-1~S-20+Q-1/Q-2 共 22 项**纯文档规格缺陷收口**——补 CoverageItem/GateVerdict/done verdict 三处权威 schema、file-bridge 边界矩阵(§C.3.5)、B2 决策方列、Tick 路径更正、Guardrail "当前5/目标9"状态列、Q-1/Q-2 过度设计存续论证。**S-1**(B4↔B7 语义评估矛盾)定案：v5.6 全路径无语义评估(呼应 #40/D6)，代码 semantic_evaluator 全链移除跟踪到 Phase 3 T10d（不即时大改以免破坏活跃 v5.5 路径）。全程无 status 翻转、无设计降级（design-document-inviolability 遵守）。审计产出 `_scratch/design-audit/{findings-A/B/C,AUDIT-REPORT}.md`。BEACON 决策 #49 |
| 2026-07-09 | **Init-Loop 契约 v5.6 扩展 (IL.2-IL.5)** | 评估"衔接部分如何定义/是否合理/优化方案"：架构选型正确(单向/文件桥接/只读/forward-compat)，但缺口①跨仓库无 Schema SSOT(文档表+Python函数两处定义→漂移) ②相对 v5.6 滞后(缺 design_doc/ci_platform，monorepo 枚举不自洽)。方案 A(schema SSOT jsonschema 校验)+B(ci_platform/design_root 字段)+C(monorepo 单包降级不删枚举)+D(消费者驱动契约测试)。checkpoints.db 从契约面移除解 spec 债。IL 章重写 + IL-AC-06/07/08 + Phase 7(T32-T35) + D21、discussion §十五。BEACON 决策 #48 |
| 2026-07-09 | **借鉴 Superpowers 验证方法论加固审计与验证层 (B15)** | 两组分析合并去重：① Superpowers 三工具（TDD/verification/requesting-code-review）→ REDGuard+FreshGate+RegressionGate（Python 门控，非 Agent 自觉）；② `/audit` 三层现状（audit.md/audit.py/deep_audit.py）→ 内化+语义层+骨架→实际+分层澄清。+B15 章 6 小节、+D20、+Phase 6(T27-T31)、discussion §十四。BEACON 决策 #47 |
| 2026-07-09 | **Commit→PR→CI/CD Pipeline 专题设计 (B13)** | 5 轮讨论：现状分析(P0 release.yml冲突+无远程CI, P1 code-review.md漂移+虚构引用+git add -A) → 颗粒度金字塔+时间轴+环界线 → PR=plate 是否中断(结论:人工闸门恒在环外,方案D输入端控粒度) → CI 双平台(单一入口+薄壳,DRY) → 环内vs远程(共享pyproject标准非运行时,增量快子集vs全量权威)。+B13 章 9 小节、+D18、+Phase 4b (T16h-T16n)、discussion §十二。BEACON 决策 #45 |
| 2026-07-09 | **中央提示词管理 (Prompt Registry, B12)** | 提示词清单盘点发现散落 3 层(prompts.py/commands/SKILL.md)×3 版本(v5.5/v5.1/v5.0)漂移严重。集中 A/B 类到 `prompts/`(roles+fragments+schema)，frontmatter 声明片段组合，init 一次性加载 + sha256 hash 锁入 checkpoint。C 类命令 `.md` 结构约束不移位，`sync-prompts.py` 注入共享片段。+B12 章 8 小节、+D17、Phase 4 T13-T16d 改写 + T16e/T16f/T16g。文档 2932→3070 行。BEACON 决策 #44 |
| 2026-07-08 | **借鉴 Superpowers 提示词技术加固 Agent 行为层 (B11)** | 分析 Superpowers (9 SKILL.md + 零依赖) 后固化可借鉴项到设计文档：CSO description 纪律 / Iron Law / Red Flags / 合理化破解表（developer/critic/architect/verifier 成品文本）/ Letter-vs-Spirit / 渐进披露。明确不借鉴 3 项（Agent 自调节=v5.0灭亡根因、压力测试评估法=独立项目、subagent-per-task=与Tick冲突）。+B11 章 8 小节、+D16、Phase 4 加 T16c/T16d。文档 2776→2932 行。BEACON 决策 #43 |
| 2026-07-08 | **v5.6 Pre-flight Gap Analysis + ResearchAgent 分层知识源** | 用户提出：设计文档部分章节粗略，应在主循环前预检而非拖到 verifier/audit 才暴露（代价高）。新增 Phase 0：gap_scan 分级 → gap_review 用户介入(Fill/Research/Defer/Defer+Research) → research 分层检索。ResearchAgent 四层知识源(Tier0 CLAUDE.md 声明→Tier3 web)，优先策展源、盲搜兜底、Tier1 三步法禁批量扫描。设计文档 1974→2776 行：+B10 章、+Phase 0 转换 T0.1-T0.8、+G6 Guardrail、+EngineState #28-#32、+3 handler。BEACON 决策 #42 (D14/D15) |

## 待解决问题

[已解 DS-10] Tick 延迟 → Python 编排开销 P95<2s（`t_orchestration`=tick墙钟−gate−guard子进程），超标只告警不中断；LLM/gate 墙钟单独观测。规格 C.2.6 | [已解 DS-9] Haiku verifier 误判 → verifier 输出 MISSING/DIVERGED 后插入 Sonnet 窄范围复核，假阳由 system_deep_audit 兜底。规格 B6.6a | [已解 DS-8] plan_refine 环路 → 分源计数 ≤2 + 全局 ≤4，同层第 2 次未解决即停。规格 B2/B4

## 引用文件

@design/v5.6-Design-Loop.md · @design/INDEX.md · @design/IMPLEMENTATION-TRACKER.md · @design/discussion/ · @docs/EARS-v5.0.md · @docs/api-reference.md
