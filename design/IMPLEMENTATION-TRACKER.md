# Auto-Engineering 当前实施跟踪表

> 更新：2026-08-30｜唯一产品任务：P0-E2E 单命令运行到 TERMINAL｜状态：`☐` 未开始／`◐` 进行中／`✅` 已验证

## 导航

- 当前权威设计：[`v5.8-Main-Agent-Coordinator-Recovery-Design.md`](v5.8-Main-Agent-Coordinator-Recovery-Design.md)
- 当前决策：[`BEACON.md`](BEACON.md)
- 历史任务：[`IMPLEMENTATION-TRACKER-HIS.md`](IMPLEMENTATION-TRACKER-HIS.md)
- 项目里程碑：[`HISTORY.md`](HISTORY.md)

## 唯一 P0：端到端产品闭环

| 优先级 | ID | 唯一交付任务 | EARS 验收 | 状态 |
|---:|---|---|---|:---:|
| P0 | P0-E2E | 独立安装后的单命令设计开发闭环 | While 同一 Build 分别安装到 Codex 与 Claude Code, when 用户在空项目执行一次设计驱动命令, both hosts shall 自动完成设计扫描、规划、开发、审查、修复和验证并到达等价 `TERMINAL`，零非预期人工续接、零手工协议修复 | ◐ Phase 85 第一批已实现；自动回归不能替代当前 Build 双宿主 L4，继续阻断发布 |

### 当前工作面

| 工作面 | 当前判断 |
|---|---|
| 设计工程模型 | ✅ section 身份、设计权威和任务追溯已有基础 |
| Core 确定性协议 | ✅ Action/Result、EventStore、Finalizer、Journal 和 Gate 已有基础 |
| 主 Agent 持续协调 | ◐ 默认入口已切回主 Agent；真实宿主连续运行待验收 |
| Worker 生命周期 | ◐ generation/fencing 与等待语义已落地；原生 liveness 待真实宿主验收 |
| 预算 soft | ✅ 默认不硬停；显式 hard 仍可用 |
| 真实异步验收 | ☐ Fake Host 不能关闭；Codex/Claude 同 Build L3/L4 待执行 |

### 完成纪律

- 每次真跑故障先归属完整工作面，禁止只修最终错误码。
- P2 整洁任务不得阻塞 P0 主链。
- 只有 T609–T620 和 P0-E2E 全部取得新鲜证据时才允许发布。

## Phase 85：主 Agent 协调权恢复与宿主生命周期纠偏

> 风险列表示决策对产品架构的影响。设计已批准并进入实施；旧 Supervisor 先旁路，双宿主 L4 通过后再退役。

### 设计与迁移合同

| 优先级 | ID | 风险 | 任务 | 状态 |
|---:|---|:---:|---|:---:|
| P0 | T603 | R4 | 保留 D13 授权争议并由 D53–D56 取代 | ✅ 已登记 |
| P0 | T604 | R4 | 定版当前主 Agent 唯一 Coordinator 边界 | ✅ 已定版，待实现 |
| P0 | T605 | R3 | 定版 Worker 所有权、liveness、generation 与 Artifact 恢复 | ✅ 已定版，待实现 |
| P0 | T606 | R3 | 定版 Codex/Claude 宿主差异合同 | ✅ 已定版，待实现 |
| P0 | T607 | R2 | 预算默认 soft、外部限流分离 | ✅ 已定版，待实现 |
| P0 | T608 | R3 | Supervisor 先旁路后退役迁移合同 | ✅ 已定版，待实现 |

### 恢复正确主链

| 优先级 | ID | 风险 | 任务 | 核心验收 | 状态 |
|---:|---|:---:|---|---|:---:|
| P0 | T609 | R4 | Skill/Command 恢复主 Agent 持续 Action 循环 | 一次命令连续到合法退出，不默认调用 `--supervise` | ✅ L1 文档回归；L3/L4 待验收 |
| P0 | T610 | R3 | 接入现有 work files、Collector、Finalizer、Journal 和机器 argv | 不回滚到手工拼装机器事实 | ✅ L1 既有链路回归；L2 待补 |
| P0 | T611 | R3 | 等待观察、liveness 探测和所有权不确定分流 | wait 不等于失败；无法确认终止时禁止并发重跑 | ◐ 等待语义已统一；L2/L3 待验收 |
| P0 | T612 | R3 | Worker 私有 outcome 先行与有界主会话摘要 | Worker 先原子落盘，主 Agent 只保留引用、摘要和 handle | ✅ L1 合同回归；L3 待验收 |
| P0 | T613 | R3 | OWNER_LOST、generation、lease 和 fencing 防双写 | Collector 只接受 active generation，旧结果只审计 | ◐ generation/fencing 已落地；跨会话 L2/L3 待验收 |
| P0 | T614 | R3 | Coordinator-only repair 全链复用 | Assembler/Core 拒绝不重跑 Worker | ✅ 既有 L1 回归；L3 待验收 |
| P0 | T615 | R2 | 删除默认预算硬停机 | 缺省/soft 模式只记录指标并继续 | ✅ L1 回归；显式 hard 兼容 |

### 真实验收与退役

| 优先级 | ID | 风险 | 任务 | 核心验收 | 状态 |
|---:|---|:---:|---|---|:---:|
| P0 | T616 | R3 | 建立真实异步纵向宿主模拟器 | 第一次 wait 结束后 Worker 继续运行并最终推进 Tick | ✅ 真实子进程 wait→outcome→Collector→Finalizer→Core Tick 回归通过 |
| P0 | T617 | R3 | 历史真跑事故回放矩阵 | 覆盖 wait、owner 丢失、迟到、重复、部分成功和 Core 拒绝 | ✅ 统一回放矩阵覆盖 6 类故障，均验证保留 active Action/拒绝旧事实/只修复 Coordinator |
| P0 | T618 | R3 | 安装制品公开入口契约测试 | 不读取开发目录或 Canonical 私有状态 | ✅ 当前 Build 的 Codex/Claude archive smoke 均通过；真实产品安装仍由 T619/T620 验收 |
| P0 | T619 | R3 | Codex L3/L4 单命令终态 | 覆盖多角色、wait、repair、零人工续接和 TERMINAL | ☐ 等待启动开发 |
| P0 | T620 | R3 | Claude Code L3/L4 等价终态 | 不嵌套 `claude -p`，语义与 Codex 等价 | ☐ 等待启动开发 |
| P1 | T621 | R3 | 双宿主通过后退役旧 Supervisor | T619–T620 通过后删除旧默认主控，永久保留历史设计 | ☐ 前置未满足 |
