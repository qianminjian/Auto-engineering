# 2026-08-30 架构审计修复记录

## 结论

本次审计确认，近期真跑反复阻断的核心不是某个业务字段，而是 Action 事实、宿主投影、事务副作用和验收证据没有在所有入口使用同一条确定性链路。代码层已完成修复；真实 Codex/Claude Code L3/L4 仍是独立发布门禁。

## 审计发现与修复

| 风险 | 根因 | 修复 |
|---|---|---|
| R4 | prepare、finalize、status、cleanup 对 Worker generation 的映射入口不一致 | 统一 `_map_bound_action_for_host`，generation-bound 路径全程复用 |
| R4 | EventStore 与 checkpoint 被读取后拼接，可能形成不存在的 Action | EventStore 优先；checkpoint 仅兼容回退；身份冲突 fail-closed |
| R3 | EventStore Tick 回滚后命名 JSON effect 残留 | 事务失败撤销未提交 JSON receipt；内容寻址 Prompt 保留 |
| R3 | 产品验收部分结论由外层调用方自报 | Journal 生成 `machine_claims`，验收器与 trajectory/事件交叉校验 |
| R3 | 状态冲突可能冒出 Python traceback，宿主无法稳定恢复 | init/tick/finalize/status/supervisor 统一输出 `STATE_SOURCE_CONFLICT` 语义 |
| R4 | L2 异步测试绕过公开 CLI，无法发现入口衔接问题 | 增加公开 CLI 异步轨迹：init→Worker→finalize→validate→tick |
| R3 | 用户指南把 Init manifest 写成运行时硬前置，与 D16 冲突 | 明确本地探测/`ae.toml` 为默认输入，旧 manifest 仅作只读兼容 |
| R3 | 生成规则、EARS 和培训指南仍保留 Init manifest 必需的旧口径 | 统一标注历史兼容契约与当前 D16 运行时口径，并增加文档回归 |
| R3 | 损坏宿主 receipt 的排序字段和空事件流恢复会泄漏裸异常 | receipt 先校验非负整数 tick；空事件流返回稳定 `PROJECTION_STREAM_EMPTY`，并补回归测试 |

## 设计约束

1. Core 仍是单 Tick 确定性内核，主 Agent 是唯一 Coordinator，业务角色使用原生独立 Worker。
2. EventStore 是新协议事实源；checkpoint 不得补写或覆盖 EventStore Action。
3. Worker outcome 必须先原子落盘并携带 generation、fencing token；旧代际结果只能审计，不能推进当前 Action。
4. 等待观察不等于 Worker 失败；真实宿主未确认所有权终止时不得并发重跑。
5. 自动测试、archive smoke 和 Core `TERMINAL` 都不能替代真实宿主 L3/L4。

## 验证证据

- 当前候选 Build：`5.8.0-rc.5+sha256.d524ccba699dc023`。
- 全量串行测试：`2820 passed, 1 skipped`；严格覆盖率门禁 `90.00%` 通过。
- 覆盖率：`90%`。
- Ruff、MyPy、`git diff --check`：通过。
- 新增公开 CLI 异步轨迹测试：`test_public_cli_async_worker_trajectory_uses_current_action_artifacts`。
- 新增状态冲突入口回归：init/tick/finalize/status/supervisor。
- Codex 与 Claude Code 使用受控 wheel 缓存完成 archive smoke。
- 损坏 receipt 与空事件流边界回归：`13 passed`（与既有 resilience/replay 测试合并执行）。

## 未关闭事项

- T619：Codex 安装后真实 L3/L4。
- T620：Claude Code 安装后真实 L3/L4。
- T621：只有 T619/T620 同一 Build 均通过后，才评估退役旧 Supervisor。

在上述事项完成前，发布状态必须保持阻断；不得通过降低设计标准、删除失败测试或把模拟宿主结果改写成真实证据来关闭门禁。
