# Loop 设计—实现对照审计

> 日期：2026-09-29
> 范围：仅 Auto-Engineering Loop 工程；外部 Voice Clone 项目和用户指定的外部事故报告保持只读。
> 对照基线：`design/BEACON.md`、`design/v5.8-Main-Agent-Coordinator-Recovery-Design.md`、`design/v5.8-Real-Host-Acceptance-Runbook.md`、`design/IMPLEMENTATION-TRACKER.md`。

## 结论先行

当前实现已经回到原始设计主线：主 Agent 是唯一 Coordinator，宿主负责连续驱动，Python 只执行确定性单 Tick，EngineState 是可重建投影，EventStore/Reducer 是唯一事实源。旧 Supervisor、Round、CheckpointStore、重复 EventStore 和旧 recovery 不在生产运行路径；它们只作为历史说明或发布包拒绝规则存在。

本次真跑暴露的“坏 private artifact + 有效 native result”死锁已经完成从根因到边界的修复：同一 Action、Worker、generation、fencing 和 canonical path 的 native 事实可以触发 `worker_artifact_repair`，原文件被隔离，不能重新 spawn，也不消费业务失败预算。

当前仍不能宣称产品完成。原因不是 Core 单 Tick 未实现，而是双宿主真实 L4 证据缺失：真实 Voice Clone 业务、Recovery Canary、usage 证据和单命令到 `TERMINAL` 尚未由同一新 Build 在真实产品宿主中证明。archive smoke、单元测试和历史 L4 证据不能替代该门禁。

## 一、分层对照

| 层次 | 设计责任 | 当前实现 | 证据 | 判断 |
|---|---|---|---|---|
| 主 Agent Coordinator | 负责读取 Action、调用原生 Worker、收集、Finalize、Tick；不得由 Python 接管主控 | `skills/auto-engineering/SKILL.md`、`commands/dev-loop.md`、Host Action Runtime | `tests/test_single_runtime_architecture.py`、宿主合同回归 | 一致 |
| Host Continuation | 只在 `CONTINUE + active Action + CONTINUE lease` 时恢复同一宿主调用；不创建 Action/Tick/Worker | `scripts/ae-host-run`、`host/continuation_driver.py`、`host/runtime_driver.py` | `tests/test_continuation_driver.py`、`tests/test_host_process_exit.py` | 一致 |
| CLI 边界 | 提供 `init/tick/status/resume/record`，不保存第二套循环状态 | `cli/dev_loop.py`、`cli/status.py`、`cli/result_recovery_projection.py` | CLI recovery/E2E 回归 | 一致 |
| Tick Kernel | 每次只处理一个输入 Result，编译下一 Action 并原子提交 | `loop/tick_orchestrator.py`、`loop/kernel.py`、`loop/transition_effects.py` | `EventStore.commit_tick`、Tick 回归 | 一致 |
| 状态投影 | EngineState 可从事件重建，不是独立持久化事实 | `engine/state.py`、`loop/reducers.py`、`loop/event_store.py` | projection/sequence/identity 回归 | 一致 |
| 事实存储 | EventStore 是唯一新运行事实源；非 Tick 不得 raw append | `loop/event_store.py`、`event_store_schema.py` | EventStore 架构回归、check-gate | 一致 |
| Worker 业务产物 | Worker 只写业务字段；Host 绑定 handle、model、generation、fence、路径和 attestation | `host/worker_evidence.py`、`host/execution_assembler.py` | private/native parser 与 boundary tests | 一致 |
| 协议恢复 | 格式错误不等于业务失败；有效 native 事实可在同一 Action 修复 | `host/worker_artifact_repair.py`、`cli/native_result_recovery.py` | T902/T903 CLI E2E | 一致 |
| 结果证据 | 产品 artifact 必须绑定 Build、EventStore、native manifest、usage 和 policy | `scripts/collect_product_evidence.py`、`scripts/product_acceptance.py` | T905/T906/T907 定向回归 | 一致 |
| 产品发布 | 只承认同一 Build 的双宿主真实 L4，不把 smoke 当产品完成 | `design/v5.8-Real-Host-Acceptance-Runbook.md`、product acceptance | 当前 `product_install: not_run` | 未完成 |

## 二、多个循环层次的真实边界

设计中有多个“循环”概念，但它们不是多套 Loop：

1. **宿主会话循环**：主 Agent 读取 Action，执行宿主原生工具并继续下一 Action。这是唯一业务协调循环。
2. **单 Tick 事务**：Python 对一个 Result 做一次确定性状态转换；它不是长期 Coordinator，也不启动宿主会话。
3. **EventStore 重放**：恢复时从事件重建投影；它不是新的执行循环，不产生隐含 Worker。
4. **Host Adapter 观察循环**：只观察进程、lease 和 active Action，决定继续观察、恢复或停止；不得创建业务事实。
5. **Worker 生命周期观察**：wait、liveness、close、record 是同一 Worker 的生命周期步骤，不是第二个调度器。

因此，代码中出现 `while`、`resume`、`watchdog` 或 `tick` 并不自动意味着违背设计。真正的违规条件是：这些边界自行创建 Action、改变 EventStore 事实、替换主 Agent、或把等待超时直接转成业务失败。当前架构测试已针对这些违规条件锁定。

## 三、本次事故的根因闭环

| 原问题 | 错误语义 | 修复后的语义 |
|---|---|---|
| private artifact 缺少 Host 外层字段 | 把序列化不完整当作 Worker 业务失败 | 先分类为协议/证据问题 |
| native result 已存在但未被消费 | private 文件被错误视为绝对权威 | 仅当 native 与当前 Action 身份完全绑定时进入 repair |
| repair 继续读取同一坏文件 | 同一输入反复重试，状态不收敛 | 原文件原子移入 Action/generation/fence 隔离区 |
| 协议失败 outcome 已写入 | 后续 recovery 误判为需要新 Worker | 同代有效 native 只替换协议占位，不重新 spawn |
| native path 只检查“根目录内” | 旧代际合法 JSON 可冒充当前结果 | 必须命中 canonical `message_id + worker_id + generation` 路径 |
| 产品 collector 直接信任映射路径 | 产品 manifest 可能收录漂移证据 | 与 recovery probe 共用绑定校验 |
| 旧 product artifact 兼容分支过宽 | 缺少 Claude attestation/policy 仍可通过 | 当前 1.1 artifact 缺失关键证据直接 fail-closed |

## 四、当前验证事实

- 全量回归：`3050 passed, 1 skipped`。
- 严格覆盖率：`91%`，以 `pyproject.toml` 基线为准。
- 架构专项：单一运行时、架构收敛、Runtime Identity、Revision 共 `51 passed`。
- 产品验收/collector 定向：`70 passed`。
- `Ruff`、核心源码 mypy（249 个文件）、产品脚本 mypy、`make check-gate`、规则同步检查通过。
- 当前工作树制品 `5.8.0-rc.5+sha256.4ed638cf97e6b872` 的 Codex/Claude archive smoke 通过。
- 当前 Build `5.8.0-rc.5+sha256.4ed638cf97e6b872` 已按官方本地安装器实际卸载重装到 Codex 与 Claude Code，两者 Build Identity 一致。

## 五、仍未闭环的发布证据

以下项目不能由本地测试推断完成：

1. 同一最新 Build 已实际安装到 Codex 和 Claude Code；仍需各执行一次真实设计驱动命令。
2. 真实宿主完成 Architect → Developer → Critic → Verification 的连续推进。
3. 发生一次真实 Recovery Canary，并证明恢复 Action 与 `ResultAccepted` 的 causation chain。
4. Voice Clone 真实业务 Gate、usage、machine evidence 和最终 `TERMINAL` 同时通过。
5. 两宿主均满足单次调用、零非预期人工协议修复、零旧状态误续作。

在这些证据齐全前，发布结论必须保持 `◐`。这不是降低实现标准，而是把“代码正确”与“产品真实可运行”分层，避免再次用绿色单测掩盖真实宿主中断。

## 六、后续执行顺序

1. 提交并推送 T907；候选 Build `5.8.0-rc.5+sha256.4ed638cf97e6b872` 已生成。
2. 用官方宿主安装脚本卸载并重装该 Build，已分别记录 Build Identity 一致。
3. 下一步运行最小真实宿主 Canary，确认首个 Action、lease、native Worker 和 `record → finalize → validate → tick` 链路。
4. 再运行 Voice Clone L4；任何失败必须按 Core、Host、Worker、外部模型、业务项目和验收链六类归属，禁止只修最后一个错误码。
5. 只有双宿主证据由 `product_acceptance.py` 重新读取并通过后，才允许关闭 P0-E2E。

## 明确禁止的回退

- 不恢复 Python Supervisor、Round、CheckpointStore 或第二个 EventStore。
- 不把 `WAIT_RESOURCE`、wait 到期或 provider idle 自动改写为业务失败。
- 不通过降低 schema、关闭 attestation、跳过 native manifest 或放宽 policy 来让验收通过。
- 不把 archive smoke、历史 L4、单元测试或人工补写 evidence 当作当前产品完成。
