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
| Phase 54 Tick Kernel | ◐ 0/8 | T253-T260 |
| Phase 55 Host SPI 2.0 | ☐ 0/5 | T261-T265 |
| Phase 56 黄金轨迹与收口 | ☐ 0/5 | T266-T270 |

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
| P1 | T255 | Gap/Research handlers | While 迁移两组 stage, when 跑特征测试, the trajectory shall 与 v5.6 等价 | ◐ 特征测试待建立 |
| P1 | T256 | 五层验证 handlers | While 进入验证层, when 应用结果, the Core shall 保留 Gate、Guardrail 与升级语义 | ☐ |
| P1 | T257 | Architect/Critic handlers | While 设计审查回退, when handlers 执行, the trajectory shall 保持等价 | ☐ |
| P1 | T258 | Developer handler | While batch 开发推进, when handler 应用结果, checkpoint 与验证触发 shall 保持等价 | ☐ |
| P1 | T259 | 终态与 façade 收窄 | While handlers 已迁移, when Kernel 执行, it shall 只承担通用编排职责 | ☐ |
| P1 | T260 | Phase 54 结构验收 | While 全 stage 注册, when 运行结构测试, each stage shall 恰有一个 handler | ☐ |

## Phase 55：Host SPI 2.0

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P1 | T261 | 四层能力模型 | While 能力已声明和探测, when 授权应用, effective shall 为三者安全交集 | ☐ |
| P1 | T262 | Adapter 2.0 契约 | While 宿主接入, when 实现 SPI, the adapter shall 归一化事件、映射 Action 并报告执行 | ☐ |
| P1 | T263 | Claude/Codex Profile | While 相同 Action 被映射, when 双宿主执行, the normalized result shall 语义等价 | ☐ |
| P1 | T264 | 未知宿主 fail closed | While 能力只声明未探测, when 请求高风险动作, the profile shall 拒绝执行 | ☐ |
| P1 | T265 | Phase 55 双宿主验收 | While archive smoke 通过, when product install 未跑, the report shall 仍显示 not_run | ☐ |

## Phase 56：黄金轨迹与发布收口

| 优先级 | ID | 任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P1 | T266 | 黄金轨迹格式与 runner | While fixture 被执行, when 比较结果, the runner shall 忽略非语义字段并验证事件、投影与 verdict | ☐ |
| P1 | T267 | 十类关键轨迹 | While 关键正常和异常路径运行, when 验收, all ten trajectories shall 通过 | ☐ |
| P1 | T268 | 故障注入与重放 | While 边界失败发生, when 重试, the Core shall 不重复业务推进且审计链完整 | ☐ |
| P1 | T269 | 跨宿主语义等价 | While 相同轨迹经过双 Adapter, when 规范化, Core events/state/verdict shall 等价 | ☐ |
| P1 | T270 | v5.7 全量收口 | While Phase 52-56 完成, when 全部门禁运行, tests shall 通过且覆盖率不低于 90% | ☐ |

## 执行纪律

1. 先把任务标为 `◐`，再修改代码或文档；验证后更新证据。
2. 功能与缺陷使用 Red → Green → Refactor；不得并发运行多个 pytest。
3. 设计与代码不一致时补齐代码，不降低 Gate、Guardrail 或验证标准。
4. 每个 Phase 结束执行其专项门禁；T270 才执行全量覆盖率和发布验收。
5. 未经授权不提交、不推送、不发布。

详细文件、测试步骤与命令见 `design/v5.7-Protocol-Kernel-PLAN.md`。
