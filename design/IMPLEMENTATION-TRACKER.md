# Auto-Engineering 当前实施跟踪表

> 更新：2026-07-28｜目标版本：v5.7｜历史摘要见 `design/HISTORY.md`
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
| Phase 63 非交互配置治理 | ☐ 0/1 | T301；待启动 |

## Phase 52：Protocol Envelope v1.1

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T242 | 锁定 action/result 契约盲区 | While Core 发出控制 Action, when schema 校验, the validator shall 接受 gate/skip 且拒绝未声明字段 | ✅ RED 11 failed；GREEN 合并见 T243 |
| P0 | T243 | Envelope 与闭合 schema | While 宿主交换消息, when 消息进入 Core, the protocol shall 校验版本、身份、因果与扩展边界 | ✅ 60 passed；Action/Result schema v1.1 |
| P0 | T244 | Result 因果与幂等 | While Action 已处理, when 相同 Result 重复提交, the Core shall 返回同一后继且只推进一次 | ✅ 29 passed；进程内/跨进程重放与冲突 |
| P0 | T245 | v1.0 兼容入口 | While 旧 payload 可唯一对齐, when 转换, the adapter shall 生成 v1.1；歧义时 fail closed | ✅ 10 passed；结构化兼容日志；stage mismatch fail closed |
| P0 | T246 | Phase 52 验收 | While 协议迁移完成, when 契约与回归门禁运行, the suite shall 全部通过 | ✅ 专项 262 passed；全量 1913 passed / 1 skipped；coverage 90.21%；Ruff/mypy/sync/metadata pass |

## Phase 53：Event Store 与可重放状态

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T247 | LoopEvent 契约 | While 状态转换发生, when 记录事实, the event shall 有单调序列、因果 ID 与 payload hash | ✅ RED import error；GREEN 8 passed |
| P0 | T248 | SQLite EventStore | While 单 Tick 追加事件, when transaction 提交, the store shall 原子写入并执行唯一约束 | ✅ RED import error；GREEN 7 passed |
| P0 | T249 | EngineState Projector | While event log 完整, when 重放, the projector shall 重建语义等价状态 | ✅ RED import error；GREEN 5 passed |
| P0 | T250 | 单 Tick 原子事务 | While 任一步写入失败, when 回滚, the repository shall 不留下半事件或孤立 Action | ✅ RED 6 failed；GREEN 6 passed，三点故障注入 |
| P0 | T251 | v5.6 checkpoint 导入 | While 旧线程首次恢复, when 导入, the system shall 追加一次导入事件且不改写原记录 | ✅ RED API 缺失；GREEN 3 passed |
| P0 | T252 | Phase 53 重放验收 | While 投影被删除, when 从事件重建, the resulting state shall 与提交前等价 | ✅ 新增 32 passed；核心回归 306 passed；全量 1945 passed / 1 skipped；coverage 90.14%；Ruff/mypy/sync/metadata pass |

## Phase 54：Tick Kernel 与 StageHandler

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P1 | T253 | ActionBuilder 无状态化 | While 构建调用交错, when 输入不同 context, the builder shall 不泄漏上次字段 | ✅ RED 1 failed；GREEN 专项 2 passed；相关回归 228 passed；Ruff/mypy pass |
| P1 | T254 | Handler 契约与注册表 | While Kernel 分派 stage, when 查询 registry, the system shall 恰好返回一个 handler | ✅ RED import error；GREEN 5 passed；Ruff/mypy pass |
| P1 | T255 | Gap/Research handlers | While 迁移两组 stage, when 跑特征测试, the trajectory shall 与 v5.6 等价 | ✅ RED import error + registry missing；GREEN 7 handler tests；相关回归 196 passed；Ruff/mypy pass |
| P1 | T256 | 五层验证 handlers | While 进入验证层, when 应用结果, the Core shall 保留 Gate、Guardrail 与升级语义 | ✅ RED import error + registry missing；GREEN 8 handler tests；Gate/Guardrail/Tick 回归 315 passed；Ruff/mypy pass |
| P1 | T257 | Architect/Critic handlers | While 设计审查回退, when handlers 执行, the trajectory shall 保持等价 | ✅ RED import error；GREEN 7 handler tests；Tick 回归 196 passed；Ruff/mypy pass |
| P1 | T258 | Developer handler | While batch 开发推进, when handler 应用结果, checkpoint 与验证触发 shall 保持等价 | ✅ RED import error；GREEN 3 handler tests；Tick/Checkpoint/Offload 回归 218 passed；Ruff/mypy pass |
| P1 | T259 | 终态与 façade 收窄 | While handlers 已迁移, when Kernel 执行, it shall 只承担通用编排职责 | ✅ RED import error；GREEN 3 terminal tests；仅保留 `_after_tick`；相关回归 236 passed；Ruff/mypy pass |
| P1 | T260 | Phase 54 结构验收 | While 全 stage 注册, when 运行结构测试, each stage shall 恰有一个 handler | ✅ 11/11 stage 唯一注册；相关轨迹 394 passed；全量 1981 passed / 1 skipped；coverage 90.33%；Ruff/mypy/sync/metadata pass；Orchestrator 2077→2048 行 |

## Phase 55：Host SPI 2.0

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P1 | T261 | 四层能力模型 | While 能力已声明和探测, when 授权应用, effective shall 为三者安全交集 | ✅ RED 2 failed；GREEN 2 profile tests；Host/Git/Hook 回归 33 passed；Ruff/mypy pass |
| P1 | T262 | Adapter 2.0 契约 | While 宿主接入, when 实现 SPI, the adapter shall 归一化事件、映射 Action 并报告执行 | ✅ RED 3 failed；GREEN probe/map/report 契约；Host 专项 20 passed |
| P1 | T263 | Claude/Codex Profile | While 相同 Action 被映射, when 双宿主执行, the normalized result shall 语义等价 | ✅ 双宿主相同 payload 映射语义等价；平台身份独立保留 |
| P1 | T264 | 未知宿主 fail closed | While 能力只声明未探测, when 请求高风险动作, the profile shall 拒绝执行 | ✅ RED 未拒绝 web_search；GREEN effective capability 映射前拒绝；未知宿主无 Adapter |
| P1 | T265 | Phase 55 双宿主验收 | While archive smoke 通过, when product install 未跑, the report shall 仍显示 not_run | ✅ 105 passed / 1 skipped；Ruff/mypy/sync/metadata pass；真实 product install 保持 not_run |

## Phase 56：黄金轨迹与发布收口

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P1 | T266 | 黄金轨迹格式与 runner | While fixture 被执行, when 比较结果, the runner shall 忽略非语义字段并验证事件、投影与 verdict | ✅ RED import error；GREEN 2 runner tests；仅忽略随机 ID、时间与 host 展示扩展；Ruff/mypy pass |
| P1 | T267 | 十类关键轨迹 | While 关键正常和异常路径运行, when 验收, all ten trajectories shall 通过 | ✅ 十类 fixture 齐备；黄金/真实 Tick/事务/重放/迁移/Guardrail 专项 305 passed |
| P1 | T268 | 故障注入与重放 | While 边界失败发生, when 重试, the Core shall 不重复业务推进且审计链完整 | ✅ 三点事务故障重试仅提交一次；宿主回报无效后安全恢复；35 passed |
| P1 | T269 | 跨宿主语义等价 | While 相同轨迹经过双 Adapter, when 规范化, Core events/state/verdict shall 等价 | ✅ RED import error；GREEN 双 Adapter 黄金轨迹；Host/Hook/Golden 38 passed |
| P1 | T270 | v5.7 全量收口 | While Phase 52-56 完成, when 全部门禁运行, tests shall 通过且覆盖率不低于 90% | ✅ 1996 passed / 1 skipped；coverage 90.35%；Ruff/mypy/sync/metadata/diff pass；双宿主 archive smoke pass、product install not_run；atdo smoke 7/7 |

## Phase 57：收口质量加固

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P1 | T271 | SQLite 与 smoke 告警归零 | While 全量门禁运行, when 资源被释放, the suite shall 不产生 ResourceWarning 或兼容别名告警 | ✅ 根因定位 raw sqlite context 不关闭；专项 5 passed；全量 1996 passed / 1 skipped，零 warnings；atdo smoke 7/7 |
| P1 | T272 | 验收文档命令去漂移 | While 用户按文档执行验收, when 复制命令, the scripts shall 存在且参数符合当前 CLI | ✅ 移除退役脚本引用；统一 build_release + 双宿主 install_acceptance；Doctor 11 项与动态测试基线 |

## Phase 58：真实产品安装验收

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T273 | Claude Code 真实安装 | While release 已安装到真实 Claude Code, when 新宿主进程调用插件命令, the host shall 加载 Skill 并返回有效状态 | ✅ Claude Code 2.1.220；user scope enabled；安装缓存 Skill/runner 完整；`/auto-engineering:status` 实际调用成功 |
| P0 | T274 | Codex 真实安装 | While release 已安装到真实 Codex, when 新宿主进程调用 `$auto-engineering`, the host shall 加载 Skill 并返回有效状态 | ✅ Codex 0.145.0；插件 installed/enabled；`gpt-5.6-sol` 新进程加载安装缓存 Skill 并执行 status；普通执行返回现有 checkpoint |

## Phase 59：真实宿主兼容性加固

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P1 | T275 | 只读 status SQLite 访问 | While Codex 使用 read-only 沙箱, when `status --format json` 读取已有 checkpoint, the command shall 不设置写入型 PRAGMA 且返回真实状态 | ✅ RED WAL/临时目录两类失败；GREEN 快照 + immutable 双路径；100 passed；真实 Codex 返回非空 thread |
| P0 | T276 | 自包含双宿主 marketplace | While release 被解压, when 任一宿主从 marketplace 安装, the plugin root shall 包含完整 Core、Skill、hooks 与 runner | ✅ RED 缺少 plugin payload；GREEN 构建时生成自包含插件目录；安装缓存完整 |
| P1 | T277 | Manifest 零告警 | While Claude 校验 release marketplace, when plugin manifest 被解析, the validator shall 不报告未知字段或缺 description | ✅ 移除未知 metadata、补 description；Claude validator 零告警 |
| P0 | T278 | 双宿主 release 重装验收 | While 新 release 已构建, when Claude/Codex 从该 release 安装并调用 status, both hosts shall 返回真实 checkpoint | ✅ v5.7.0 双宿主 installed/enabled；Claude/Codex 返回同一非空 thread；双缓存 `ae --version` 均为 5.7.0 |
| P0 | T279 | Release 安全解压兼容 | While 系统 Python 不支持 tar filter 参数, when archive smoke 解压, the runner shall 安全拒绝路径穿越并完成正常解压 | ✅ RED ImportError；GREEN 兼容安全解压，路径穿越拒绝；双宿主 archive smoke pass |

## Phase 60：Prompt Contract 与多 Agent 交付完整性

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T280 | 契约模型与静态一致性 | While prompt stage 被注册, when 静态校验运行, the system shall 验证执行模式、Worker 数量和输出契约一致 | ✅ Contract registry + layout tests |
| P0 | T281 | Compiler 与单 Agent 上下文 | While Worker prompt 被构建, when requirement/feedback 存在, the system shall 将关键上下文交付给实际 Worker | ✅ Architect/Critic/Verifier/Gap/Research 接入 |
| P0 | T282 | Inline Developer 契约化 | While Developer 进入实现或返工, when instruction 被渲染, the system shall 包含 tasks、反馈和授权边界 | ✅ 中央角色生效；Git 默认未授权 |
| P0 | T283 | 多 Agent 独立提示词 | While 3/5 个 Worker 被创建, when prompt 被渲染, each worker shall 有完整上下文、唯一角色和输出契约 | ✅ 3/5 Worker 独立 role/context/hash |
| P0 | T284 | 逐 Worker receipt | While 多 Agent 声明完成, when proof 被验证, the system shall 验证每个 Worker 的独立 receipt | ✅ 缺失返回 WORKER_RECEIPT_MISSING |
| P1 | T285 | 输出契约与兼容警告 | While 旧合法 Result 被提交, when 增强字段缺失, the system shall 兼容接受并产生结构化警告 | ✅ extensions.contract_warnings |
| P1 | T286 | 不可覆盖 Prompt 日志 | While 同 tick/stage 重试, when rendered log 写入, the system shall 按 message/audience/hash 保留全部版本 | ✅ rendered 日志不可覆盖且不冒充投递 |
| P0 | T287 | Phase 60 收口 | While T280-T286 完成, when 全部门禁运行, tests shall 通过且覆盖率不低于权威基线 | ✅ 2019 passed / 1 skipped；90.27%；Ruff/mypy/sync pass |

## Phase 61：v5.7.1 发布收口

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T288 | 版本与发布元数据 | While v5.7.1 被构建, when metadata 校验, all version sources shall 一致 | ✅ runtime/plugin/marketplace/README/lock 一致；metadata pass |
| P0 | T289 | 发布专项回归 | While Phase 60 已合入, when release/prompt/host tests 运行, the suite shall 全部通过 | ✅ 初始 139 passed / 1 skipped；最终专项 37 passed / 1 skipped |
| P0 | T290 | 候选制品与哈希 | While release archive 被构建, when 检查内容, it shall 自包含新 Compiler/Contract 并记录 SHA-256 | ✅ r3 SHA-256 `4870ae905a17c740682027b053bdfc9e3b2ea127d5b27350786052387a97e101` |
| P0 | T291 | 双宿主 archive acceptance | While 候选包被解压验收, when Claude/Codex smoke 运行, both shall 通过 | ✅ r3 Claude/Codex package_contract、isolated_uv_sync、doctor、minimal_tick pass |
| P0 | T292 | 双宿主真实安装 | While v5.7.1 安装到真实宿主, when version/status 调用, both shall 返回有效结果 | ✅ r3 installed/enabled；双缓存 version/doctor/status pass；Claude validate 零告警 |
| P0 | T293 | Prompt Contract 真实链路 | While 宿主执行新 Action, when prompt/receipt 被检查, context and worker receipts shall 完整 | ✅ 双缓存 5 Worker、唯一 receipt、缺口上下文完整；Codex 新进程加载安装缓存 |
| P0 | T294 | 发布门禁与推送 | While T288-T293 完成, when 全量门禁运行, tests/coverage/static shall 通过并提交推送 | ✅ 2021 passed / 1 skipped；90.27%；Ruff/mypy/sync/metadata/diff pass；提交推送见 Git |

## Phase 62：v5.7.1 正式发布

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T295 | Claude 非交互输出诊断 | While 插件已真实安装, when 新 Claude 进程执行 `-p`, the host shall 返回有效输出或形成可复现的宿主侧根因证据 | ✅ 插件/认证/doctor 正常；普通与 Skill `-p` 同样无输出；双安装 + 自定义 endpoint，定位宿主环境层 |
| P1 | T296 | 计划状态去漂移 | While Phase 60 已完成, when 读取 Prompt Contract PLAN, all implementation checkboxes shall 与 Tracker 一致 | ✅ 43 个实施检查项全部同步为 `[x]` |
| P0 | T297 | 独立环境双宿主回归 | While 候选包在隔离目录安装, when init/tick/status/resume 运行, both hosts shall 通过且不依赖源码工作区 | ✅ 修复 `dev-loop --format json` 契约；r5 双宿主 package/sync/doctor/init/status/resume pass |
| P1 | T298 | 发布自动化加固 | While release workflow 构建制品, when CI 执行, it shall 校验版本、双宿主 archive、载荷与 SHA-256 | ✅ workflow 校验版本/metadata/双宿主验收并上传 `.sha256`；专项 18 passed |
| P0 | T299 | Phase 62 发布门禁 | While T295-T298 完成, when 全量门禁运行, tests/coverage/static shall 通过且设计证据完整 | ✅ 本地 2023 passed / 1 skipped、90.28%；CI `30373176093` 三 job pass、annotations 0/0/0 |
| P0 | T300 | v5.7.1 正式发布 | While 发布门禁通过, when tag workflow 完成, GitHub Release shall 包含可验证制品与 SHA-256 | ✅ tag `v5.7.1`；workflow `30373283948` pass；远端 SHA-256 `fae483df…86c99` 校验通过 |

## Phase 63：非交互配置治理

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P1 | T301 | `ae.toml` 首次配置闸门重构 | While `ae.toml` 缺失且宿主无 TTY, when `dev-loop --init` 启动, the system shall 通过显式配置策略继续或暂停，准确报告 env/file/default 来源，且不得通过管道模拟交互输入 | ☐ |

## Phase 64：真实运行可信度止血

> Phase 64 是后续真实项目运行的 P0 前置条件，优先于 Phase 63 实施。详细设计与
> 任务步骤见 `design/v5.8-Session-Decoupling-Design.md` 和
> `design/v5.8-Session-Decoupling-PLAN.md`。

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T302 | 会话解耦设计资产 | While 真实运行事故已形成证据, when 设计评审, the specification shall 覆盖状态、会话、预算、计划补丁、验证、审计、恢复和双宿主验收 | ✅ v5.8 Design/PLAN + BEACON/INDEX/HISTORY/v5.7 交叉引用；T303-T324 已登记 |
| P0 | T303 | 真实运行故障黄金轨迹 | While 146-Tick 故障被抽象为 fixture, when 旧实现运行, the suite shall 稳定复现批次回退、状态计数异常和验证假通过 | ☐ |
| P0 | T304 | 工具链验证 fail-closed | While manifest 声明 TypeScript/Vitest, when TestGate 执行, the system shall 调用匹配工具链，并在命令非零或收集零测试时失败 | ☐ |
| P0 | T305 | 文件快照可信绑定 | While Gate 产生结论, when 文件集为空、快照不完整或结果与快照不匹配, the system shall 拒绝通过并返回稳定错误 | ☐ |
| P0 | T306 | 计划补丁与进度不变量 | While 已完成批次存在, when Architect 追加修复批次, the Core shall 只激活新增工作，保留完成集合，并拒绝 `done_tasks > total_tasks` 等非法投影 | ☐ |
| P0 | T307 | Phase 64 止血验收 | While T303-T306 完成, when 故障轨迹与相关回归运行, the suite shall 证明不会重启已完成批次、不会把零测试或空快照判为通过 | ☐ |
| P0 | T322 | 146-Tick 真跑事故报告 | While 真跑证据分散在外部 `_scratch` 与会话中, when 永久报告建立, it shall 区分事实与推断、映射全部修复任务并提供脱敏证据索引 | ✅ 永久报告 11 节；事实/推断分离；T303-T321/T323-T324 追踪矩阵与关闭标准 |

## Phase 65：确定性状态与宿主会话解耦

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T308 | ExecutionSession 与事件契约 | While 一个工程线程跨多个宿主会话运行, when 会话开始、续接或结束, the Core shall 以不可变事件记录 session identity、原因和状态边界且不改变业务进度语义 | ☐ |
| P0 | T309 | ResumeCapsule 最小恢复契约 | While 新宿主会话接管线程, when capsule 被构建, it shall 只包含 active Action、状态摘要、必要证据引用和预算，不包含完整历史对话 | ☐ |
| P0 | T310 | ContextBudget 与 rollover 决策 | While 宿主报告或估算的上下文达到阈值, when Tick Kernel 选择下一 Action, the system shall 确定性发出 `session_rollover` 而不是继续扩张请求 | ☐ |
| P0 | T311 | Rollover Action/Result 幂等恢复 | While rollover 已发出, when 原会话重试或新会话重复接管, the Core shall 只建立一个有效 successor session，并返回同一 active Action | ☐ |
| P1 | T312 | Claude/Codex 会话适配 | While 双宿主收到 rollover, when 宿主创建新会话并提交接管回执, both adapters shall 产生语义等价的 Core 事件和恢复状态 | ☐ |
| P0 | T313 | Phase 65 会话边界验收 | While 长轨迹跨至少三个宿主会话运行, when 任一边界发生中断、重复或延迟, the final projection and verdict shall 与单进程黄金轨迹等价 | ☐ |

## Phase 66：有界上下文、产物引用与成本审计

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T314 | Stage Context Selector | While Action 被编译, when 当前 Stage 请求上下文, the compiler shall 仅选择契约声明的必要字段和有界摘要，不拼接完整历史 | ☐ |
| P0 | T315 | ArtifactRef 与精简 Worker Receipt | While 多 Agent 或深度审计产生大结果, when 结果交付主宿主, the system shall 持久化完整产物并只传递带哈希的引用和有界摘要 | ☐ |
| P1 | T316 | 逐 Tick Usage Ledger | While 宿主可提供 usage, when Action/Result 完成, the system shall 按 thread/session/tick/stage/worker 记录 input、cache read/write、output 和估算来源 | ☐ |
| P1 | T317 | Checkpoint 与审计保留策略 | While 长轨迹持续运行, when 快照、Prompt 和产物超过保留阈值, the system shall 保留事件事实与审计引用并安全压缩可重建副本 | ☐ |
| P0 | T323 | 状态锚点与摘要隔离 | While BEACON 或自动摘要过期、重复或矛盾, when Action/Capsule 被构建, the Core shall 仅依赖事件投影推进，并显式报告信息性上下文漂移 | ☐ |
| P0 | T324 | 修复循环与 Agent 预算 | While repair、Worker 或 Deep Audit 达到策略上限, when 下一 Action 被选择, the system shall 确定性暂停或 rollover，禁止无限追加批次或 Agent | ☐ |
| P0 | T318 | Phase 66 成本与完整性验收 | While T314-T317、T323-T324 完成, when 单/多会话轨迹比较, semantic verdict shall 等价且输入放大率、单会话峰值、摘要隔离、循环上限与审计缺口满足预算 | ☐ |

## Phase 67：双宿主真实项目发布门禁

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | T319 | 中等规模双宿主真实验收 | While 候选版本安装到 Claude Code 与 Codex, when 运行包含返工、深审计和至少一次 rollover 的真实项目, both hosts shall 完成且无批次回退、验证假通过或输入超限 | ☐ |
| P0 | T320 | 故障恢复与成本基线 | While 宿主在 rollover 前后异常退出, when 从事件与 capsule 恢复, the run shall 收敛到等价终态并输出可归因成本报告 | ☐ |
| P0 | T321 | v5.8 发布收口 | While T303-T320、T323-T324 全部完成, when 全量测试、覆盖率、静态检查、双宿主安装与真实运行门禁执行, all required checks shall 通过后才允许发布 | ☐ |

## 执行纪律

1. 先把任务标为 `◐`，再修改代码或文档；验证后更新证据。
2. 功能与缺陷使用 Red → Green → Refactor；不得并发运行多个 pytest。
3. 设计与代码不一致时补齐代码，不降低 Gate、Guardrail 或验证标准。
4. 每个 Phase 结束执行其专项门禁；Phase 64-67 的全量覆盖率和发布验收仅在
   T321 执行。
5. 未经授权不提交、不推送、不发布。

详细文件、测试步骤与命令见 `design/v5.7-Protocol-Kernel-PLAN.md`。
