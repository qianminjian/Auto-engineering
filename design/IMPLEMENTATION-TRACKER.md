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

## 执行纪律

1. 先把任务标为 `◐`，再修改代码或文档；验证后更新证据。
2. 功能与缺陷使用 Red → Green → Refactor；不得并发运行多个 pytest。
3. 设计与代码不一致时补齐代码，不降低 Gate、Guardrail 或验证标准。
4. 每个 Phase 结束执行其专项门禁；T270 才执行全量覆盖率和发布验收。
5. 未经授权不提交、不推送、不发布。

详细文件、测试步骤与命令见 `design/v5.7-Protocol-Kernel-PLAN.md`。
