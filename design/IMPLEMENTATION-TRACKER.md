# Auto-Engineering 当前实施跟踪表
> 更新：2026-08-29｜唯一产品任务：P0-E2E 单命令运行到 TERMINAL｜历史 Phase/T 项为支撑证据，不能替代产品完成｜状态：`☐` 未开始／`◐` 进行中／`✅` 已验证

## 唯一 P0：端到端产品闭环

> 权威设计：`design/v5.8-End-to-End-Product-Closure-Design.md`；统一实施计划：`design/v5.8-End-to-End-Product-Closure-PLAN.md`。在本任务关闭前冻结与主链无关的新治理能力、用户管理命令和点状控制补丁。

| 优先级 | ID | 唯一交付任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | P0-E2E | 独立安装后的单命令设计开发闭环 | While 同一宿主 Marketplace 已安装的 Build 已分别启用到 Codex 与 Claude Code, when 用户在空项目执行一次设计驱动命令, both hosts shall 自动完成设计扫描、规划、开发、审查、修复和验证并到达等价 `TERMINAL`，零非预期人工续接、零手工协议修复、零旧计划误续作 | ◐ Build `5.8.0-rc.5+sha256.3927b1f572df8ece` 已通过 `2676 passed, 1 skipped`、90% coverage、静态检查、双宿主 archive smoke 与 Codex L4；Claude Code L4 仍待真实终态验收 |
### 不可独立关闭的四个工作面
| 工作面 | 目标 | 当前判断 |
|---|---|---|
| 设计工程模型 | 设计—缺口—任务—代码—验证使用同一稳定模型追溯 | ✅ 稳定 section 身份已接入公开执行包与内部模型，Agent/Core 双身份闭合 |
| 连续 Host Runtime | Core 单 Tick，Runtime 在一次用户启动内自动运行到合法退出 | ✅ Codex/Claude package-only 离线宿主经真实 finalize/validate/tick operations 连续到 `TERMINAL` |
| Agent 与机器边界 | Agent 只提交推理语义，Core/Runtime 自动生成机器事实 | ✅ Gap Agent 输出可读 `section_ref`；Assembler 确定性绑定内部 ID，旧 `section_id` 仅保留读取兼容 |
| 宿主执行包闭包 | 合法 Result 所需信息全部来自真实宿主可见执行包 | ✅ Coordinator/Worker Prompt 结构化引用及 recovery `semantic_context_refs` 已由双宿主公开包终态轨迹证明 |
| Section 双身份 | Agent 使用可读引用，Core 独占稳定内部 ID 与覆盖事实 | ✅ `host_design_sections.section_ref → design_sections.section_id` 已由 Core 模型与 Assembler 单一解析 |
| Result 接受事务 | Assembler/预校验/Core 任一拒绝均在同一 Action 自动修复 | ◐ 已修复重复 Worker、outcome 覆盖及“计划接受后下一 Action 引用崩溃”；统一章节标签解析与未来 Action 预校验通过 249 项回归，待全量与新 Build L4 |
| 离线生产终态 | 同一生产资产覆盖 Gap、规划、开发、Critic 返工、验证、恢复并到 `TERMINAL` | ✅ package-only Codex/Claude 轨迹不读 Canonical 状态、不用 FakeOperations，均以 9 次 Action context 到 `TERMINAL` |
| 双宿主真实验收 | 独立制品完成 Codex/Claude L4 且语义等价 | ◐ 独立 Build 已证明零开发目录来源；Codex 真跑已暴露跨阶段章节解析、Worker 重复及 Python Profile 能力缺口，均已修复并通过回归；新 Build 双宿主终态仍待执行 |
### 完成纪律
- 既有 Phase/T 项继续保留为历史能力和回归证据，不再据此计算产品完成度。
- 每次真跑故障先归属上述工作面，再修复完整生产链；禁止只修最终报错点。
- 只有 `P0-E2E` 的全部退出证据齐备时才标记完成并允许发布。
## 历史能力证据
Phase 64–66 的真实运行止血、会话解耦、上下文预算、ArtifactRef、Usage Ledger 与恢复证据已归档至 `design/HISTORY.md` 和 Git；当前表只保留仍影响 `P0-E2E` 发布判断的任务。
## Phase 67：双宿主真实项目发布门禁
| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T319 | 中等规模双宿主真实验收 | While 候选版本安装到 Claude Code 与 Codex, when 运行包含返工、深审计和自动 compaction 的真实项目, both hosts shall 无人工交接完成且无批次回退、验证假通过或输入超限 | ◐ archive smoke 已通过；真实产品门禁并入 T350 |
| P0 | T320 | 故障恢复与成本基线 | While 宿主在 rollover 前后异常退出, when 从事件与 capsule 恢复, the run shall 收敛到等价终态并输出可归因成本报告 | ✅ SQLite 重启/重复 claim 等价恢复 + 双 session Usage 聚合；32 tests passed |
| P0 | T321 | v5.8 发布收口 | While T303-T320、T323-T324 全部完成, when 全量测试、覆盖率、静态检查、双宿主安装与真实运行门禁执行, all required checks shall 通过后才允许发布 | ◐ `5.8.0-rc.5` 自动门禁通过；真实产品 LLM 门禁未执行 |
| P1 | T325 | Claude 命令命名空间校准 | While 插件名为 `auto-engineering`, when 用户查看或启动 Claude Code slash command, all active guidance shall 使用宿主实际注册的 `/auto-engineering:dev-loop`，不得继续宣传不存在的 `/ae:*` 别名 | ✅ 当前文档、CLI 提示、设计契约和生成规则已统一；RED 4 failed，GREEN 81 passed/1 skipped；Ruff/mypy/sync/metadata 与 rc.2 Claude archive smoke pass |
## Phase 68：rc.1 真跑缺陷修复
| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T326 | 第二次真跑事故归档 | While rc.1 真跑证据位于外部项目, when 新会话恢复修复, the report shall 保留事实、根因、任务映射和关闭标准且不复制敏感日志 | ✅ 事故报告与任务矩阵已归档 |
| P0 | T327 | Developer Snapshot 跨进程恢复 | While Developer Result 已被接受且下一 Tick 在新进程运行, when critic/verifier Gate 读取文件证据, the Core shall 从持久化事实重建同一非空 snapshot，不依赖进程内 `_dev_snapshot` | ✅ EngineState 持久化并恢复 |
| P0 | T328 | 项目级 active thread 唯一性 | While 项目存在非终态 thread, when 重复 `--init` 或 init/resume 竞争, the Core shall fail-closed 并返回唯一合法恢复入口，不创建 stray active thread | ✅ SQLite 原子租约与唯一 resume |
| P0 | T329 | Gate 三态与 skip 可信语义 | While Gate 未实现、不可执行或缺少证据, when verdict 聚合, the Gate shall 返回 fail；只有机器可证的不适用项才可返回 `not_applicable`，不得以 `passed=true` 表示 skip | ✅ pass/fail/not_applicable 已分离 |
| P0 | T330 | P1 Findings 闭环 | While critic 以 APPROVE 返回 P1, when batch/phase 推进, the Core shall 持久化 finding、绑定修复任务并在最终 Gate 前要求全部关闭 | ✅ open_findings 持久化且零 P1 放行 |
| P1 | T331 | Phase 67 Usage 与 rollover 门禁（历史） | While 真实宿主验收启动, when usage 来源可用, the harness shall 强制启用 Usage Ledger、输出 input/cache/output 归因 | ✅ Usage 基础已实现；强制 rollover 验收由 T347-T350 替代 |
| P1 | T332 | Result Builder 与提交前预检 | While Agent 形成 Result, when 提交 Tick, the host protocol shall 以 schema 构建并本地预检 JSON，降低引号、扩展字段和枚举错误导致的重复 Action | ✅ `--validate-result` 无副作用预检 |
| P1 | T333 | 稳定设计组件身份 | While batch 引用设计章节, when Markdown 标题格式变化, the Core shall 通过规范化稳定 ID 匹配，不依赖反引号或展示文本完全相等 | ✅ 章节编号稳定身份 |
| P1 | T334 | Checkpoint 大对象分层 | While 长轨迹保存 checkpoint, when batch plan、progress tree 或产物重复, the store shall 内容寻址复用大对象并保持恢复等价 | ✅ SHA-256 blob 复用与兼容恢复 |
| P1 | T335 | Agent 成本与审计频率治理 | While plate revision 未变化或 Worker 预算接近上限, when deep audit 被考虑, the Core shall 避免重复审计并记录 requested effort、actual model 与跳过原因 | ✅ 修订去重、预算硬限与模型 receipt |
| P0 | T336 | Phase 68 收口验收 | While T327-T335 完成, when 多进程黄金轨迹、故障注入、全量测试和双宿主 archive 运行, all regressions shall 通过后才允许生成新 rc 并重启真实 LLM 门禁 | ◐ 自动验收通过；待真实 Claude Code 重跑 |
## Phase 69-72：配置、上下文治理、证据链与 Runner
| 范围 | 状态 | 当前证据 |
|---|:---:|---|
| T337-T340 配置初始化 | ✅ | schema/standard profile/首次配置/双宿主 archive 已验收 |
| T341-T350 上下文与成本治理 | ◐ | 固定 Tick rollover 已退役；无 LLM 压测与真实场景/成本门禁归 T411/T412 |
| T351-T354 真跑证据链 | ✅ | Tick 编号、进度守恒、制品版本已验收 |
| T355-T358 位置无关 Runner | ✅ | bundled `ae-run` 与双宿主外部 cwd smoke 已验收；明细见 HISTORY/Git |
## Phase 73：Init Engineering 运行时解耦（设计见 `design/v5.8-Init-Runtime-Decoupling-Design.md`）
| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T359 | ProjectProfile 契约与负向测试 | While Profile schema、命令、路径或证据非法, when Core 校验输入, the system shall 以稳定错误码 fail-closed，且相同规范化事实产生相同 profile_id | ✅ 11 tests；Ruff/mypy 通过 |
| P0 | T360 | Provider SPI 与确定性 Resolver | While 项目存在 AE 显式配置、本地工程事实或 legacy manifest, when Resolver 运行, the system shall 按权威等级合并全部证据、补全缺失字段并显式报告冲突 | ✅ Provider 权威合并/冲突/显式配置；21 tests；Ruff/mypy 通过 |
| P0 | T361 | 有限本地项目探测 | While 项目属于首期支持生态且缺少 Init manifest, when dev-loop 启动, the system shall 只读取白名单入口文件解析语言、路径和已声明命令，不递归扫描、不猜测命令 | ✅ Python/Node/Go/Rust 固定入口探测与 1MiB 门禁；21 tests |
| P0 | T362 | 空项目 setup Action/Result | While 项目只有设计文档且能力不足, when dev-loop 启动或恢复, the system shall 幂等发出 project_setup_required；宿主提交完成后必须重新探测通过才继续 | ✅ setup Action/Result、重新探测、虚假完成拒绝；相关 102 tests |
| P0 | T363 | Gate 与状态恢复解耦 | While Profile 已解析或跨进程恢复, when Gate Registry 构建验证链, the system shall 只消费持久化 ProjectProfile，不读取 Init 专用文件且不回退 Python 默认工具 | ✅ 精确命令 Gate、缺失 fail-closed、checkpoint Profile 恢复；78 tests |
| P1 | T364 | Prompt Contract 有界 Profile 上下文 | While Architect、Developer 或 Verifier 编译 Prompt, when Profile 未变化, each consumer shall 只接收角色所需摘要或 ArtifactRef，不直接读取或重复内联 Init manifest | ✅（19 tests；Ruff；移除 prompt 侧 manifest 依赖） |
| P1 | T365 | Doctor、CLI 与配置语义迁移 | While manifest 缺失、项目待搭建或 legacy 输入存在, when doctor/CLI 诊断, the system shall 分别报告 resolved、setup_required、conflict 或 legacy，不把缺少 Init 产物误报为安装故障 | ✅（76 tests；Ruff/mypy；四态诊断） |
| P0 | T366 | Legacy Init 只读兼容 Adapter | While 旧项目仅提供有效 init-manifest.json, when Resolver 和现有兼容 API 运行, the system shall 生成等价 Profile、保持 manifest mtime 不变并给出非阻断迁移提示 | ✅（legacy 等价转换、mtime、稳定错误；68 tests；Ruff/mypy） |
| P0 | T367 | Phase 73 双宿主收口验收 | While T359-T366 完成, when 已有项目、空项目、冲突、恢复和 legacy 黄金轨迹在 Claude/Codex 执行, both hosts shall 产生等价终态且全量测试、覆盖率、静态检查和真实产品轨迹通过 | ◐ 自动门禁完成：2153 passed/1 skipped、coverage 90%、Ruff/mypy/sync、双宿主 archive install；待 Claude Code/Codex 真实 LLM 轨迹 |
## Phase 74：深度审计修复（详见 `design/v5.8-Deep-Audit-Remediation-PLAN.md`）
| 优先级 | ID | 任务 | 状态 |
|---:|---|---|:---:|
| P0 | T368-T373 | Gate、Result、Spawn、事务、EventStore、Host 与 Profile 恢复 | ✅ 专项与集成验证通过 |
| P1 | T374-T375 | Release/CI、跨平台、审计门禁与验收去虚化 | ✅ check-gate 与双宿主 archive pass |
| P0 | T376 | 全量自动门禁与双宿主 archive 收口 | ✅ 2166 passed/1 skipped、coverage 90.41%；真实 LLM 轨迹仍单独作为 T350/T367/T380 门禁 |
## Phase 75：真跑准入审计收口
| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P1 | T377 | status 异常降级 | While batch state 读取失败, when `dev-loop --status --verbose` 生成摘要, the CLI shall 返回可用的降级摘要且不引用未初始化变量 | ✅ 20 回归测试；Ruff/mypy/check-gate 通过 |
| P2 | T378 | 测试失败缓存清零 | While 测试跨会话失败计数存在, when 同一测试随后通过, the diagnostic cache shall 删除该测试计数并不继续报告陈旧失败 | ✅ 2 回归测试；全量 2166 passed/1 skipped |
| P1 | T379 | 历史秘密与依赖确认 | While 发布候选进入真跑或发布, when Git 历史扫描或依赖审计发现疑似风险, the release record shall 区分当前树、历史树和未验证项，未经人工确认不得宣称安全已闭环 | ◐ 当前 tracked files 无发现；历史 15 条与依赖审计待确认 |
| P0 | T380 | 真实宿主分层证据协议 | While Claude Code 与 Codex 执行候选制品, when Canary 与完整黄金项目完成, the evidence shall separately record product install, usage completeness, duplicate blocks, recovery and semantic equivalence | ◐ 协议已登记，按 T445 补齐场景/成本门禁后执行 |
## Phase 76：设计文档全量/范围入口
| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T381 | 设计文档入口与 Architect 执行树映射 | While `--design-doc` 单独传入或 Architect 回填组件标题, when dev-loop 初始化/校验计划, the system shall 保留全文需求并在 BatchState/ProgressTree 解析到同一节点 | ✅ CLI 入口、组件标题/§ 引用兼容、dry-run 门禁；2171 passed/1 skipped |
| P1 | T382 | 范围约束与 Research/Supplement 注入 | While 自然语言 requirement 与 `--design-doc` 同时传入或 Research 已产出结论, when Architect 编译 Prompt, the system shall 将 requirement 作为范围并注入有界研究/补充摘要 | ✅ Skill/Prompt Contract/回归测试通过；16 条/4000 字符有界 |
| P0 | T383-T384 | 真跑纠偏：路径、EventStore 状态与批量 Gap Review | While 外部项目从任意 cwd 恢复或 gap_review 有多个未决 gap, when status/tick 或 host action 运行, the system shall 以 project-root 解析文档、保持 status 公共契约，并在一次 Action 中完整收集全部 gap 决策后推进 | ✅ rc.5 完整集合校验、Research 队列与 Action schema fail-closed；2178 passed/1 skipped |
| P1 | T385-T386 | 真跑纠偏：Gate 可观测性、契约适用性与宿主续接 | While Gate 异常、契约为空或 verifier 产生 finding, when runner/architect/host 继续, the system shall 保留结构化原因、按真实 contracts 判定 N/A，并使用既有 PLAN_REFINE 契约续接 | ✅ ProfileCommandGate/P2/Contract/status/PLAN_REFINE 纠偏；Ruff/mypy/sync/metadata 通过 |
## Phase 78：架构基线、Gate 转移与确定性修复控制
| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T387-T390 | 事故归档、权威 Spec、Gate fail-closed、ProjectProfile 原生命令 | While required Gate 失败或 pnpm 项目无 typecheck script, when Core 转移或解析 Profile, the system shall 阻止 Critic 并选择已验证的包管理器命令 | ✅ 事故/Spec；Gate 转移与 pnpm 证据命令；自动门禁通过 |
| P0 | T391-T393 | ArchitectureBaseline、结构化 Contract、Research 义务覆盖 | While Architect Result 被接受, when 后续 Stage 执行, the system shall 恢复同一基线并在开发前拒绝未覆盖义务 | ✅ Event/checkpoint 重放；义务矩阵与 Contract fail-closed |
| P0 | T394-T395 | Critic 分类路由、修复/停滞预算、BatchReviewContext | While Finding 越界或重复无进展, when Core 路由, the system shall 分别 PLAN_REFINE 或 STAGNANT，并提供有界累积证据 | ✅ 分类路由、独立预算、有界累积上下文；2190 passed/1 skipped |
| P1 | T396 | immutable spawn challenge 与 Host Receipt 语义绑定 | While 宿主派生 Worker 并提交 Result, when Core 校验 receipt, the system shall 绑定 Action/Worker/result digest 且不覆写 challenge | ✅ challenge/host receipt/Core result digest；待产品复验 |
## Phase 79：PlanPatch 与 Contract 激活修复
| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T397-T398 | 事故归档与 refine 上下文契约 | While Core 等待 PLAN_REFINE, when Architect 重发 full plan 或 revision 错误, the system shall 在状态变更前 fail-closed 并给出重试反馈 | ✅ 前置拒绝、revision 注入与新 ID patch Prompt |
| P0 | T399-T400 | 增量执行树与 Contract 义务激活 | While patch 新增修复 batch 或 contract 跨 batch, when Core 物化计划/运行 Gate, the system shall 保留完成事实并只验证已到达契约 | ✅ 基线增量合并；义务驱动 contract 激活 |
| P0 | T401-T402 | Prompt/spec 同步与收口验收 | While Phase 79 实现完成, when 自动门禁和双宿主制品运行, all regressions shall 通过后才进入真实产品复验 | ◐ 2194/1、coverage 90%、静态/同步/双宿主 archive pass；待真实复验 |
## Phase 80：协议内核收敛重构
> 权威资产：`design/v5.8-Protocol-Kernel-Convergence-Design.md`、`design/v5.8-Protocol-Kernel-Convergence-PLAN.md`；完成前冻结点状补丁。
| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T403 | 协议内核收敛设计资产 | While 方案 B 已获批准, when 实施开始, the specification shall 统一定义 Core/Host/Event/Prompt/Session 边界、迁移顺序、禁止项和发布门禁 | ✅ Spec/PLAN + BEACON/INDEX/HISTORY/Tracker 已同步；T404-T413 已登记 |
| P0 | T404 | 架构特征与负向契约 | While 旧 façade、全状态事件补丁和线程级 Prompt 锁仍存在, when Phase 80 测试运行, the suite shall 稳定暴露这些偏差且不改变现有生产状态 | ✅ 5 项 RED 均按预期失败；GREEN 后与相关回归 209 passed |
| P0 | T405 | Runtime Compatibility Vector 与 Action 边界升级 | While 活动 Action 使用旧运行时修订, when 新版本恢复并接收其因果 Result, the Core shall 完成旧 Action 后只对下一 Action 激活新修订 | ✅ Vector、Action Snapshot/恢复判定及第 76 Tick 边界升级轨迹通过 |
| P0 | T406 | Host Execution Control 与连续驱动契约 | While Action 非终态且无需用户输入, when 宿主提交 Result, the host shall 按机器处置自动执行下一 Action，不把单个 Action 输出当作完成 | ◐ ExecutionControl 与决策映射已完成；第 20 次真跑证明生产 Host Driver/StopGuard 未闭合，转 T461 |
| P0 | T407 | 领域事件 Reducer 与 legacy replay | While 新线程推进状态, when Event Stream 重放, the projection shall 由显式领域事件重建且新路径不得写逐 Tick 完整 EngineState；旧流仍可兼容读取 | ✅ 统一 LegacyEventAdapter + EventStore 新写入隔离；真实 rc.5 fixture 与隔离恢复通过 |
| P0 | T408 | 纯 ActionCompiler 与 Effect Executor | While 相同输入、identity 和 clock 被提供, when Action 重复编译, the compiler shall 生成字节等价草案且不写文件，副作用由独立执行器原子处理 | ✅ Prompt/proof/challenge 通过 EffectIntent 执行；EffectReceipt 与 Event/Projection/Action 同 Tick 事务提交并覆盖回滚；304 项第二批矩阵通过 |
| P0 | T409 | TickKernel 收敛与旧 façade 绞杀 | While StageHandler 返回 TransitionDecision, when Kernel 应用转换, it shall 不解释 Stage 专属命令式字段，并逐阶段退役旧可变写入路径 | ✅ façade 已无 Stage 专属分支；Architecture/Offload/Result/Context/Prevalidation/Gate/Audit 均由独立服务承载；2254 passed/1 skipped |
| P1 | T410 | 协议与恢复遗留语义清理 | While rollover、Prompt、Policy 或 Schema 发生迁移, when 契约校验, the system shall 只保留异常恢复原因并给出稳定兼容或退役诊断 | ✅ handoff 原因已收口；固定 Tick/时间/输入阈值只保留弃用诊断且不参与 Runtime decision |
| P0 | T411 | 跨版本、长轨迹与双宿主验收 | While 确定性 150 Tick 压测与真实业务场景分别运行, when Claude/Codex 完成产品轨迹, both hosts shall 产生等价语义、零非预期停顿且成本门禁完整 | ◐ 无 LLM 150 Tick 轨迹及 archive smoke 通过；真实产品 L3/L4 仍 not_run |
| P0 | T412 | Phase 80 发布收口 | While T404-T411、T413 完成, when 全量、覆盖率、静态、replay、fault injection、archive 和真实产品门禁执行, all required checks shall 通过后才允许生成下一 RC | ◐ 自动门禁 2266 passed/1 skipped、coverage 90%、Ruff/mypy、双宿主 archive pass；待真实产品门禁，不生成下一 RC |
| P0 | T413 | Codex 原生子代理能力绑定 | While Codex 暴露 `collaboration.spawn_agent`, when spawn Action 要求单个或并行 Worker, the host Skill shall 显式映射 `reasoning_effort` 并先调用真实工具，禁止在工具调用失败前主观报告 `HOST_CAPABILITY_UNAVAILABLE` | ✅ RED 契约复现；Skill/Command 显式绑定工具清单、`reasoning_effort=xhigh` 与 CONTINUE；专项 69 passed/1 skipped、全量 2255 passed/1 skipped |
| P0 | T414 | 旧流/PlanPatch 事故持久化 | While 外部真跑报告与事件证据已确认, when 修复会话变化, the project shall 保留脱敏事实、根因、不变量和关闭标准 | ✅ 事故资产已回填根因、不变量、关闭标准与验证证据 |
| P0 | T415 | Legacy Event Adapter 与新写入隔离 | While 旧流含任意历史 `state_patch`, when 新 Runtime replay, the adapter shall 保持旧语义；新事件写入仍 fail-closed | ✅ payload 能力适配全部旧事件；新写入仅 legacy_import 例外 |
| P0 | T416 | 唯一 Architecture Candidate | While baseline 与 PlanPatch 同时存在, when dry-run、obligation 校验和激活运行, all consumers shall 使用同一合并 candidate | ✅ 单次物化；投影/激活共享；candidate drift fail-closed |
| P0 | T417 | obligation 增量与 refine Prompt | While patch 未重述旧 obligation, when Architect refine 校验, the Core shall 继承 baseline；显式更新按稳定身份校验 | ✅ 自动继承、新来源新增、旧来源受控 append；Prompt/schema 同步 |
| P0 | T418 | 真实旧 payload 跨版本黄金轨迹 | While 脱敏 rc.5 前序事件流恢复, when 新 Runtime 接受 patch, the projection shall 等价且进入 Developer | ✅ 固定 fixture 回归；隔离旧 thread 从 Architect 进入 Developer，原项目未写入 |
| P0 | T419 | 不可混淆 Build Identity | While SemVer 相同但提交或制品不同, when Runtime/Action/报告生成, the build identities shall 不同且可追溯 | ✅ Release/source 内容摘要；双宿主同制品身份一致；裸 Python builder 回归 |
| P0 | T420 | 方案 B 全门禁与原地恢复验收 | While T415-T419 完成, when 全量质量与隔离旧 thread 恢复执行, all checks shall 通过且不得改写真实项目历史 | ✅ 2266/1、coverage 90%、Ruff/mypy/sync、隔离恢复、双宿主 archive smoke |
| P1 | T421 | SQLite 测试资源释放 | While CLI/status/Codex integration 测试打开 checkpoint DB, when 测试结束, all connections shall 显式关闭且 coverage run 不产生 ResourceWarning | ✅ sqlite 只读探测显式 close；全量以 ResourceWarning 为 error：2457 passed/1 skipped |
## Phase 81：状态冲突协调与任务续作
> 权威设计：`design/v5.8-State-Reconciliation-Design.md`；完成前冻结点状补丁，rc.5 不再续跑真实项目。
| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T422-T427 | 状态冲突协调与任务续作 | While 显式设计与隐藏状态冲突, when 用户选择重开或协调, the Core shall 保留审计、重建当前 Work Set 并只投影有效 revision | ✅ Inspector、Gate、reinitialize/reconcile、投影和重放已闭环 |
| P0 | T428-T429 | task-aware 证据与 Contract Gate | While 业务任务提交证据, when Gate 校验, the Core shall 拒绝 smoke 冒充业务测试并要求可执行 contract test | ✅ 307 项相关回归通过 |
| P0 | T430 | Phase 81 全门禁与真实产品复验 | While T423-T429 完成, when 隐藏状态、双路径、幂等、跨宿主和产品安装轨迹执行, all checks shall 通过后才允许生成下一 RC | ◐ 2301/1、coverage 90%、Ruff/mypy/sync、Claude/Codex archive smoke 通过；真实 product install/长跑仍 `not_run`，不得生成下一 RC |
| P0 | T431-T433 | 自动续跑、Gap 主链路与 Agent 资源/Repair 收敛 | While setup/gap/worker/refine 主链路运行, when Core/Host 处理状态与失败, the system shall 保持事件、Action、设计路由和恢复语义一致 | ✅ 2327/1、90% coverage、静态/sync/archive；后续真跑又证伪 Worker 身份与设计权威，转 T434-T439 |
## Phase 82：真实宿主闭环与设计权威（审计收敛）
| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T434 | 真实宿主闭环总体验收 | While 内部自动门禁无法覆盖真实宿主, when Phase 82 完成, L1-L4 shall 分别证明协议、轨迹、Canary 和完整黄金项目，不以 archive 或测试数量冒充 product install | ◐ 回归基线 2417/1、90%；真实双宿主 L3/L4 未运行，发布阻断 |
| P0 | T435-T439 | 身份、Invocation、Authority、Fake Host 与黄金语义基础 | While 基础模块已有定向测试, when 审计生产链, the evidence shall 区分参考实现与真实宿主强制路径 | ◐ 模块/定向测试已完成；审计发现结果污染、生产绑定、完整轨迹和语义门禁缺口 |
| P0 | T440-T441 | 严格 SpawnPlan、结果分离、Host Attestation 与版本协商 | While 任一 spawn Action 被真实宿主执行, when Worker 返回, the host shall 只消费机器 invocation 并提交与 Action/Prompt/能力绑定的证明 | ◐ Core 验证已完成；第 20 次真跑证明宿主仍手工拼装三类证明且 Command 仍含 legacy 指令，转 T461-T462 |
| P0 | T442 | Design Decision Ledger、全阶段权威与上下文去重 | While 显式决策、future 项和 Research 并存, when 计划或修复激活, the Core shall 拒绝未批准变更并只传递去重后的相关义务 | ◐ 来源绑定与批准投影已完成；partial ledger 尚未阻止 advisory 架构变化，转 T465 |
| P0 | T443-T459 | 完整轨迹、黄金场景、Hermetic Release 与真跑恢复收口 | While 候选制品进入验收, when 故障矩阵、Canary、完整项目或 Worker 失败执行, both hosts shall 使用严格 Invocation、Core 生成的证明模板和真实配置快照，产生确定恢复语义 | ◐ T443-T459 自动门禁完成；Codex 已从独立内容寻址 Release 安装并通过零开发目录来源验收（Build `5.8.0-rc.5+sha256.32e2f80e47b0399a`）；新 Build 双宿主 L3/L4 长跑仍 not_run |
## Phase 83：Host Runtime 产品闭环收敛
| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---|---|---|---|---|
| P0 | T460 | 第 20 次真跑根因与统一规格 | While 真跑与组件测试结论冲突, when 规划修复, the design shall 以产品链路证据纠正假绿任务并冻结点状补丁 | ✅ 设计与计划已记录；产品未闭合任务已纠正 |
| P0 | T461 | HostRuntimeDriver、RunLease 与 StopGuard | While active Action 为 CONTINUE, when 宿主准备停止, the plugin shall 自动继续或在启动前因能力不足 fail-closed | ✅ Driver/Lease/双宿主 StopGuard 与发布资产验证通过 |
| P0 | T462 | Worker outcome 到 Result 的原子证据事务 | While Worker 已真实完成, when Coordinator finalize, the assembler shall 一次生成全部绑定证明且中断恢复不重新 spawn | ✅ 原子 Assembler、完整 violations 与幂等 journal 已通过生产轨迹 |
| P0 | T463-T464 | BatchCompleted 领域事件与进度单一投影 | While Plan refine 改变计划, when candidate 激活和事件重放, progress shall 按稳定 ID 保留完成事实且永不超过 100% | ✅ 稳定完成事件、最小路由拓扑及 replay 不变量通过 |
| P0 | T465 | partial 设计权威与架构变更批准 Gate | While advisory 与设计冲突, when ledger 非 full, the Core shall 保守执行原设计并要求显式用户批准 | ✅ ChangeRequest/Gate/Approval Event 因果投影通过 |
| P1 | T466 | EventStore 指标事实投影 | While 项目产生 MAJOR/refine/usage 事件, when summary 生成, metrics shall 与重放事实一致或标记 measurement_incomplete | ✅ EventStore replay 指标与 incomplete 语义通过 |
| P0 | T467-T469 | L2 产品轨迹、双宿主 L3 与 Voice Clone L4 | While 候选版本准备真跑或发布, when 任一层证据缺失, the release gate shall 保持阻断 | ◐ L2、2676/1、静态与双宿主 archive 通过；Build `5.8.0-rc.5+sha256.3927b1f572df8ece` 已安装并完成 Codex L4；Claude Code L4 仍待真实复验，发布继续阻断 |
| P0 | T470/T472/T473 | 全类型 Action 的确定性 Result 终结与单一宿主合同 | While 任一 active Action 需要宿主提交 Result, when Action 不含 spawn 或含严格 spawn, the host shall 只提交业务 payload/原生 outcome，由同一 Core assembler 绑定 active Action 并生成完整 v1.1 Result；Action instruction/expected_format 不得要求 Core-owned identity 或手工 proof | ◐ L3 已验证非 spawn 原子文件链与 strict outcomes；随后发现 Developer expected_format 要求 `stage` 却被 Finalizer禁止，RED→GREEN 已在 ActionBuilder 统一剔除 Core-owned 字段，待新 Build L3 |
| P0 | T471 | Architect 合法路由键的执行上下文闭包 | While Architect Gate 要求每个 batch 绑定非空 `plate_keys`, when Core 编译隔离 Worker Prompt, the Action shall 同时在机器字段和 Worker context 中提供同一 `valid_plate_keys` 集合，禁止 Worker 猜测或提交空路由 | ◐ 首轮 Codex L3 因 Worker Prompt 未携带合法集合而以 `ARCHITECT_PLAN_INVALID` 终止；RED→GREEN 已补齐 Prompt Contract 与 ActionBuilder，待新 Build L3 验证 |
| P0 | T474-T553 | 强类型宿主边界、Critic/Result 修复闭环与 Setup 实证续作 | While Critic P0/P1 回源、Result 被 Assembler/Core 拒绝或 Project Setup 声明工程能力, when Runtime 继续驱动, the product shall 保持同一业务 Action、启用全新宿主上下文并自动修复，不把内部失败交还用户 | ◐ Section 双身份与完整 Result 修复事务已实现；2661 passed/1 skipped、Ruff/mypy/sync 通过；全阶段黑盒终态及新 Build 真实 terminal 待复验，继续阻断发布 |
| P0 | T550-T553 | Gap Scan 可证明零结论与可见确认分流 | While 设计驱动 Loop 执行或恢复 Gap Scan, when Result 声称零缺口、产物丢失或发现设计决策, the product shall 校验逐章节覆盖与设计摘要绑定、始终展示有界扫描摘要、仅对真实设计决策进入 WAIT_USER，并禁止用空结果替代丢失产物 | ◐ RED/GREEN、2643/1、coverage 90%、Ruff/mypy/sync 与双宿主 hermetic archive 通过；真实 L4 前台摘要与确认分流待复验 |
| P0 | T554-T557 | 设计批准到下一 Agent 的确定性闭环 | While Research advisory、静态 ledger 与用户批准并存, when Core 产生同 Tick 下一 Architect Action 并由全新 Agent 消费, the product shall 从单一有效权威投影传递 binding 批准、拒绝相同来源范围的语义等价重复申请并生成计划进入 Developer | ◐ 同 Tick 投影、Prompt 传递、新旧事件语义改写收敛、Research obligation、进程恢复后 fresh Architect 首次计划进入 Developer 已验证；2678 passed/1 skipped、coverage 90%、Ruff/mypy/sync 及 Codex/Claude 隔离 archive smoke 通过；待新 Build 真实双宿主 L4 |
| P0 | T558-T562 | Gate、Outcome repair、终态边界与环境预检 | While Core 生成 Gate、拒绝含 Worker outcomes 的 Result、输出 `done` 或解析项目 E2E 能力, when Action 编译/恢复/验收, the system shall 映射 `WAIT_USER`、原子恢复 journal 权威 outcomes、携带 Core/产品未验证边界，并输出浏览器运行时预检；禁止错误执行、重复 spawn、替换事实或把环境缺失冒充产品失败 | ◐ T558-T562 代码与回归完成；当前自动门禁证据待刷新，新 Build 双宿主 L3/L4 与真实业务验收仍阻断发布 |
## Phase 84：跨平台宿主边界与异常可续作
| P1 | T563 | POSIX/Windows 路径越界 fail-closed | ✅ 回归已实现；跨平台路径检查通过 |
| P1 | T564 | Host/机器 OSError → 稳定 Stop Report | ✅ 回归已实现；稳定错误码与机器报告通过 |
| P1 | T565-T586 | 真实成本、日志脱敏、事务故障注入、纵向回放、双宿主 L3-L4、超时与状态可见性 | ◐ T571-T586 已补齐 Worker 超时先行终结、唯一 outcomes 合同、repair 投影隔离、Supervisor 即时心跳、只读 active Action 状态、Build 证据和事故回放；真实 Codex/Claude L3-L4 仍待执行 |
| P0/P1 | T587-T588 | 标准 Marketplace 安装与文档收敛 | ◐ T587 安装器与契约测试完成，待提交后从 GitHub 实际重装；T588 设计和用户指南已同步 |
