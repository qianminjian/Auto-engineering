# Auto-Engineering 当前实施跟踪表

> 更新：2026-07-31｜目标版本：v5.8｜Phase 1-62 明细见 `design/HISTORY.md`
> 状态：`☐` 未开始｜`◐` 进行中｜`✅` 已验证

## 基线与阶段

| 里程碑 | 状态 | 证据 |
|---|:---:|---|
| Phase 1-48 | ✅ | Git 历史与 `design/HISTORY.md` |
| Phase 49 Host-neutral Core | ✅ 22/22 | 双宿主基础适配与发布验收 |
| Phase 50 Codex 迁移收口 | ✅ 8/8 | T233-T240；覆盖率 90.15% |
| Phase 51 质量收口 | ✅ 1/1 | T241；1889 passed / 1 skipped，零告警 |
| Phase 52 Protocol Envelope | ✅ 5/5 | T242-T246；1913 passed / 1 skipped |
| Phase 53 Event Store | ✅ 6/6 | T247-T252；1945 passed / 1 skipped |
| Phase 54 Tick Kernel | ✅ 8/8 | T253-T260 |
| Phase 55 Host SPI 2.0 | ✅ 5/5 | T261-T265 |
| Phase 56 黄金轨迹与收口 | ✅ 5/5 | T266-T270；1996 passed / 1 skipped |
| Phase 57 收口质量加固 | ✅ 2/2 | T271-T272 |
| Phase 58 真实产品安装验收 | ✅ 2/2 | T273-T274；Claude Code/Codex 真实宿主调用通过 |
| Phase 59 真实宿主兼容性加固 | ✅ 5/5 | T275-T279；v5.7.0 双宿主真实安装验收通过 |
| Phase 60 Prompt Contract 重构 | ✅ 8/8 | T280-T287；2019 passed / 1 skipped，coverage 90.27% |
| Phase 61 v5.7.1 发布收口 | ✅ 7/7 | T288-T294；2021 passed / 1 skipped，coverage 90.27% |
| Phase 62 v5.7.1 正式发布 | ✅ 6/6 | T295-T300；GitHub Release 与 SHA-256 已核验 |
| Phase 63 非交互配置治理 | ✅ 1/1 | T301；非交互显式策略与来源报告 |

## Phase 63：非交互配置治理

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P1 | T301 | `ae.toml` 首次配置闸门重构 | While `ae.toml` 缺失且宿主无 TTY, when `dev-loop --init` 启动, the system shall 通过显式配置策略继续或暂停，准确报告 env/file/default 来源，且不得通过管道模拟交互输入 | ✅ `--config-policy`/`AE_CONFIG_POLICY`；require/defaults/create；真实 CLI + 53 tests；全量 2095 passed/1 skipped |

## Phase 64：真实运行可信度止血

> Phase 64 是后续真实项目运行的 P0 前置条件，优先于 Phase 63 实施。详细设计与
> 任务步骤见 `design/v5.8-Session-Decoupling-Design.md` 和
> `design/v5.8-Session-Decoupling-PLAN.md`。

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T302 | 会话解耦设计资产 | While 真实运行事故已形成证据, when 设计评审, the specification shall 覆盖状态、会话、预算、计划补丁、验证、审计、恢复和双宿主验收 | ✅ v5.8 Design/PLAN + BEACON/INDEX/HISTORY/v5.7 交叉引用；T303-T324 已登记 |
| P0 | T303 | 真实运行故障黄金轨迹 | While 146-Tick 故障被抽象为 fixture, when 旧实现运行, the suite shall 稳定复现批次回退、状态计数异常和验证假通过 | ✅ RED 4 failed；GREEN 事故 fixture 4 passed；相关回归 61 passed；Ruff pass |
| P0 | T304 | 工具链验证 fail-closed | While manifest 声明 TypeScript/Vitest, when TestGate 执行, the system shall 调用匹配工具链，并在命令非零或收集零测试时失败 | ✅ TypeScript 自动路由 Vitest；未知 runner/零测试/非零退出 fail；相关回归 70 passed；Ruff pass |
| P0 | T305 | 文件快照可信绑定 | While Gate 产生结论, when 文件集为空、快照不完整或结果与快照不匹配, the system shall 拒绝通过并返回稳定错误 | ✅ Gate 前后 hash/selected_files；空快照、变化、路径逃逸 fail；相关回归 111 passed；Ruff pass |
| P0 | T306 | 计划补丁与进度不变量 | While 已完成批次存在, when Architect 追加修复批次, the Core shall 只激活新增工作，保留完成集合，并拒绝 `done_tasks > total_tasks` 等非法投影 | ✅ 显式 PlanPatch + 旧入口兼容；revision/ID/完成事实/进度不变量；相关回归 301 passed；Ruff/mypy pass |
| P0 | T307 | Phase 64 止血验收 | While T303-T306 完成, when 故障轨迹与相关回归运行, the suite shall 证明不会重启已完成批次、不会把零测试或空快照判为通过 | ✅ 事故/Gate/Guardrail/Kernel/Projector/Golden 专项 447 passed |
| P0 | T322 | 146-Tick 真跑事故报告 | While 真跑证据分散在外部 `_scratch` 与会话中, when 永久报告建立, it shall 区分事实与推断、映射全部修复任务并提供脱敏证据索引 | ✅ 永久报告 11 节；事实/推断分离；T303-T321/T323-T324 追踪矩阵与关闭标准 |

## Phase 65：确定性状态与宿主会话解耦

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T308 | ExecutionSession 与事件契约 | While 一个工程线程跨多个宿主会话运行, when 会话开始、续接或结束, the Core shall 以不可变事件记录 session identity、原因和状态边界且不改变业务进度语义 | ✅ 12 类事件 + 不可变 Session/独立投影；双 active 拒绝；23 passed；Ruff/mypy pass |
| P0 | T309 | ResumeCapsule 最小恢复契约 | While 新宿主会话接管线程, when capsule 被构建, it shall 只包含 active Action、状态摘要、必要证据引用和预算，不包含完整历史对话 | ✅ 严格 Capsule/hash/active Action/ArtifactRef；历史字段禁入；17 passed；Ruff/mypy pass |
| P0 | T310 | ContextBudget 与 rollover 决策（历史） | While 宿主报告或估算的上下文达到阈值, when Tick Kernel 选择下一 Action, the system shall 确定性发出 `session_rollover` 而不是继续扩张请求 | ✅ 历史实现；该日常语义由 T341-T349 纠偏 |
| P0 | T311 | Rollover Action/Result 幂等恢复 | While rollover 已发出, when 原会话重试或新会话重复接管, the Core shall 只建立一个有效 successor session，并返回同一 active Action | ✅ `session_handoff.py` + SQLite 原子 handoff/claim + Protocol schemas；64 tests passed；Ruff/mypy passed |
| P1 | T312 | Claude/Codex 会话适配 | While 双宿主收到 rollover, when 宿主创建新会话并提交接管回执, both adapters shall 产生语义等价的 Core 事件和恢复状态 | ✅ 双宿主 `host_control` 等价映射 + Skill/Command fail-closed；26 tests passed |
| P0 | T313 | Phase 65 会话边界验收 | While 长轨迹跨至少三个宿主会话运行, when 任一边界发生中断、重复或延迟, the final projection and verdict shall 与单进程黄金轨迹等价 | ✅ 150 Tick/3 sessions + replay/late-result；Phase 65 suite 301 passed；Ruff/mypy passed |

## Phase 66：有界上下文、产物引用与成本审计

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T314 | Stage Context Selector | While Action 被编译, when 当前 Stage 请求上下文, the compiler shall 仅选择契约声明的必要字段和有界摘要，不拼接完整历史 | ✅ StageContract 字段/Artifact/64KiB 预算 + 历史禁入；208 tests passed；Ruff/mypy passed |
| P0 | T315 | ArtifactRef 与精简 Worker Receipt | While 多 Agent 或深度审计产生大结果, when 结果交付主宿主, the system shall 持久化完整产物并只传递带哈希的引用和有界摘要 | ✅ 内容寻址 ArtifactStore/schema + 4096B receipt/2048B summary 门禁；13 targeted tests passed；Ruff/mypy passed |
| P1 | T316 | 逐 Tick Usage Ledger | While 宿主可提供 usage, when Action/Result 完成, the system shall 按 thread/session/tick/stage/worker 记录 input、cache read/write、output 和估算来源 | ✅ SQLite Ledger + cache read/write 真实采集 + null unknown；11 targeted tests passed；Ruff/mypy passed |
| P1 | T317 | Checkpoint 与审计保留策略 | While 长轨迹持续运行, when 快照、Prompt 和产物超过保留阈值, the system shall 保留事件事实与审计引用并安全压缩可重建副本 | ✅ 永久事实隔离 + dry-run 候选 + Artifact 引用完整性；3 tests passed；无用户数据删除 |
| P0 | T323 | 状态锚点与摘要隔离 | While BEACON 或自动摘要过期、重复或矛盾, when Action/Capsule 被构建, the Core shall 仅依赖事件投影推进，并显式报告信息性上下文漂移 | ✅ 信息性 authority + anchor drift；冲突摘要不改 stage/tick；5 targeted tests passed |
| P0 | T324 | 修复循环与 Agent 预算 | While repair、Worker 或 Deep Audit 达到策略上限, when 下一 Action 被选择, the system shall 确定性停止扩张并诊断，禁止新增批次或借换会话绕过 | ✅ 扩张预算已实现；rollover 分支由 T341-T349 移除 |
| P0 | T318 | Phase 66 成本与完整性验收 | While T314-T317、T323-T324 完成, when 单/多会话轨迹比较, semantic verdict shall 等价且输入放大率、单会话峰值、摘要隔离、循环上限与审计缺口满足预算 | ✅ 专项 252 passed；最终全量 2095 passed/1 skipped；Ruff 0；mypy 125 files；sync pass |

## Phase 67：双宿主真实项目发布门禁

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T319 | 中等规模双宿主真实验收 | While 候选版本安装到 Claude Code 与 Codex, when 运行包含返工、深审计和自动 compaction 的真实项目, both hosts shall 无人工交接完成且无批次回退、验证假通过或输入超限 | ◐ archive smoke 已通过；真实产品门禁并入 T350 |
| P0 | T320 | 故障恢复与成本基线 | While 宿主在 rollover 前后异常退出, when 从事件与 capsule 恢复, the run shall 收敛到等价终态并输出可归因成本报告 | ✅ SQLite 重启/重复 claim 等价恢复 + 双 session Usage 聚合；32 tests passed |
| P0 | T321 | v5.8 发布收口 | While T303-T320、T323-T324 全部完成, when 全量测试、覆盖率、静态检查、双宿主安装与真实运行门禁执行, all required checks shall 通过后才允许发布 | ◐ `5.8.0-rc.4` 自动门禁通过；真实产品 LLM 门禁未执行 |
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

## Phase 69：项目配置强制初始化

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T337 | 统一 ae.toml schema 与标准 Profile | While Core 生成项目配置, when 文件被 RuntimeConfig 读取, the effective values shall 与生成值逐项一致且环境变量保持最高优先级 | ✅ `render_ae_toml` 与 `SECTION_KEY_MAP` 同源；逐项 roundtrip |
| P0 | T338 | 首次启动强制配置 | While 项目缺少 ae.toml, when dev-loop 启动, the Core shall 创建或要求完成显式配置，禁止无文件继续 | ✅ 缺失自动/向导落盘；空、注释、损坏配置 fail-closed |
| P1 | T339 | 向导推荐默认值与非交互初始化 | While 配置交互可用或宿主无 TTY, when 首次配置, the Core shall 分别提供可确认推荐值或确定性 standard Profile | ✅ 推荐审计/度量/Token/PII/生产安全；env 最高优先级 |
| P0 | T340 | 配置初始化收口验收 | While T337-T339 完成, when 配置专项、全量、双宿主 archive 运行, all generated profiles shall 可读、可覆盖且无静默回退 | ✅ 2110 passed/1 skipped；Ruff/mypy；Claude/Codex archive smoke pass |

## Phase 70：自动上下文与成本治理纠偏

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T341 | 决策与负向契约 | While 旧固定 Tick/人工交接行为存在, when 契约测试运行, the suite shall 先稳定失败并锁定纠偏边界 | ✅ 6 个 RED 失败后 GREEN；固定 Tick/input 不再 rollover |
| P0 | T342 | 配置语义迁移 | While standard Profile 被生成, when 配置读取, the system shall 不设置低位 session Tick 阈值，并对旧配置告警迁移 | ✅ standard Profile 不生成旧阈值；旧文件显式 `CONFIG_DEPRECATED` |
| P0 | T343 | 宿主自动 compaction 适配 | While 宿主压缩上下文, when 下一 Tick 运行, the system shall 无人工交接继续且不改变业务投影 | ✅ 正常路径不再生成 Capsule/rollover；999 Tick 契约保持原 Stage |
| P0 | T344 | ContextManifest 与块级去重 | While Action 编译, when 相同事实跨字段重复, the compiler shall 在模型调用前拒绝并报告重复 hash | ✅ Prompt bundle 携带块 hash/bytes/source；重复正文 fail-closed |
| P0 | T345 | Stage 增量上下文与 Worker 隔离 | While Stage/Worker 获取上下文, when prompt 构建, each consumer shall 只接收最小字段或专属 ArtifactRef | ✅ compiled prompt 不重复顶层 context；Worker 改用独立 `prompt_ref` |
| P0 | T346 | Prompt 与工具输出入口门禁 | While 大型日志/diff/MCP/Worker 输出产生, when 进入主上下文, the system shall 摘要引用化或 fail-closed | ✅ 延续 ArtifactRef/receipt 字节门禁；Worker prompt 正文引用化 |
| P0 | T347 | Usage 语义与测量完整性 | While 宿主报告部分 usage, when ledger 写入, the system shall 区分各指标、保留 null 并记录估算来源 | ✅ input/cache read/write 分列；新增 Core payload、重复块和 estimator |
| P0 | T348 | 成本基准与回归 Harness | While 同 fixture/宿主/模型运行, when before/after 比较, the report shall 给出可归因增量、重复块和 measurement completeness | ✅ 同 fixture/host/model 按完成工作归一化；缺失测量 fail-closed |
| P1 | T349 | 恢复协议收口 | While 真实执行实例中断, when 恢复, the system shall 幂等消费 Capsule；正常 compaction 不触发恢复协议 | ✅ Capsule 原子 claim 保留；恢复原因收口为退出/压缩失败/跨宿主 |
| P0 | T350 | 真实长跑发布门禁 | While 双宿主运行 150 Tick 轨迹, when 宿主管理上下文, both runs shall 零人工交接、零输入超限、零重复块并保持终态等价；不可观测 compaction 标 unknown | ◐ 自动测试与双宿主 archive smoke 通过；待真实产品 150 Tick |

## Phase 71：9-Tick 真跑证据链修复

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T351 | Debug Tick 审计编号 | While Core 完成第 N 次 Tick, when DebugTracer 写快照, the file and payload shall 使用同一 1-based N，且与 Action tick 的因果关系可追溯 | ✅ Debug 与 metrics 统一 `tick_no + 1` |
| P0 | T352 | 首次计划进度物化 | While Architect 为设计组件生成 batch plan, when 进度树初始化, every planned task shall 计入对应组件与父节点，禁止 `done_tasks > total_tasks` | ✅ 保留设计层次并聚合 batch task totals；非法完成数 fail-closed |
| P1 | T353 | 运行制品版本溯源 | While prompt/debug 诊断制品生成, when 事故审计读取单个制品, it shall 显式声明 engine version 与 protocol version | ✅ JSON/Markdown 声明版本；Worker `prompt_ref` 可审计且不重内联 |
| P0 | T354 | Phase 71 收口验收 | While T351-T353 完成, when 专项、全量与双宿主 archive 运行, all evidence shall 编号一致、进度守恒且版本可辨识 | ✅ 2121 passed/1 skipped；coverage 90%；静态检查与双宿主 archive pass |

## Phase 72：插件 Runner 位置无关启动

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T355 | 任意项目目录启动契约 | While 插件安装在宿主缓存且 cwd 是目标项目, when Command/Skill 启动 dev-loop, the host shall 调用 bundled runner，不查找目标项目的 `scripts/ae-run` | ✅ 外部 cwd 回归测试通过；Agent 入口统一调用 `ae-run` |
| P0 | T356 | Bundled `bin/ae-run` | While 插件启用, when 宿主解析 PATH 中的 `ae-run`, the launcher shall 定位自身插件根并委托共享 `scripts/ae-run` | ✅ 位置无关薄包装，仅委托共享 resolver |
| P0 | T357 | 发布与宿主契约 | While release archive 构建, when Claude/Codex 隔离安装验收, both packages shall 包含可执行 `bin/ae-run` 并从外部 cwd 启动 | ✅ archive 含 0755 bin；双宿主从目标 cwd smoke pass |
| P0 | T358 | Phase 72 收口验收 | While T355-T357 完成, when 专项、全量、静态检查与双宿主 archive 运行, all runner paths shall 位置无关且不复制 Core 逻辑 | ✅ 2122 passed/1 skipped；coverage 90%；静态检查与双宿主 archive pass |

## Phase 73：Init Engineering 运行时解耦

> 设计见 `design/v5.8-Init-Runtime-Decoupling-Design.md`。本阶段解除运行时前置依赖，
> 不把 Init Engineering 的问答、模板和脚手架实现并入 Core。

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T359 | ProjectProfile 契约与负向测试 | While Profile schema、命令、路径或证据非法, when Core 校验输入, the system shall 以稳定错误码 fail-closed，且相同规范化事实产生相同 profile_id | ☐ |
| P0 | T360 | Provider SPI 与确定性 Resolver | While 项目存在 AE 显式配置、本地工程事实或 legacy manifest, when Resolver 运行, the system shall 按权威等级合并全部证据、补全缺失字段并显式报告冲突 | ☐ |
| P0 | T361 | 有限本地项目探测 | While 项目属于首期支持生态且缺少 Init manifest, when dev-loop 启动, the system shall 只读取白名单入口文件解析语言、路径和已声明命令，不递归扫描、不猜测命令 | ☐ |
| P0 | T362 | 空项目 setup Action/Result | While 项目只有设计文档且能力不足, when dev-loop 启动或恢复, the system shall 幂等发出 project_setup_required；宿主提交完成后必须重新探测通过才继续 | ☐ |
| P0 | T363 | Gate 与状态恢复解耦 | While Profile 已解析或跨进程恢复, when Gate Registry 构建验证链, the system shall 只消费持久化 ProjectProfile，不读取 Init 专用文件且不回退 Python 默认工具 | ☐ |
| P1 | T364 | Prompt Contract 有界 Profile 上下文 | While Architect、Developer 或 Verifier 编译 Prompt, when Profile 未变化, each consumer shall 只接收角色所需摘要或 ArtifactRef，不直接读取或重复内联 Init manifest | ☐ |
| P1 | T365 | Doctor、CLI 与配置语义迁移 | While manifest 缺失、项目待搭建或 legacy 输入存在, when doctor/CLI 诊断, the system shall 分别报告 resolved、setup_required、conflict 或 legacy，不把缺少 Init 产物误报为安装故障 | ☐ |
| P0 | T366 | Legacy Init 只读兼容 Adapter | While 旧项目仅提供有效 init-manifest.json, when Resolver 和现有兼容 API 运行, the system shall 生成等价 Profile、保持 manifest mtime 不变并给出非阻断迁移提示 | ☐ |
| P0 | T367 | Phase 73 双宿主收口验收 | While T359-T366 完成, when 已有项目、空项目、冲突、恢复和 legacy 黄金轨迹在 Claude/Codex 执行, both hosts shall 产生等价终态且全量测试、覆盖率、静态检查和真实产品轨迹通过 | ☐ |

## 执行纪律

1. 先把任务标为 `◐`，再修改代码或文档；验证后更新证据。
2. 功能与缺陷使用 Red → Green → Refactor；不得并发运行多个 pytest。
3. 设计与代码不一致时补齐代码，不降低 Gate、Guardrail 或验证标准。
4. 每个 Phase 结束执行其专项门禁；Phase 64-67 的全量覆盖率和发布验收仅在
   T321 执行。
5. 未经授权不提交、不推送、不发布。

Phase 73 的边界与验收见 `design/v5.8-Init-Runtime-Decoupling-Design.md`；既有阶段详细
步骤见对应 Design/PLAN 文件。
