# Loop 设计—实现对照审计

> 日期：2026-09-29
> 最新追加：T912 收紧 `--resume` 的 thread 绑定，终态或非当前 thread 不再被直接读取 Action 快照。
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
| 绑定解析 | Action lease fence 与 Worker fence 分层校验；模板 fence 缺失或 native path 漂移不得降级为 generation-only | `host/worker_execution_binding.py`、`host/worker_artifact_repair.py` | T910 回归与全量测试 | 一致 |
| Developer 变更证据 | Git diff、staged diff、最近 commit 和 root commit 只能证明当前 `files_changed` 声明路径；无关 diff 不得制造假通过，越界文件先由 FileAccessGuardrail block | `loop/change_evidence.py`、`loop/guardrail.py` | T911 红绿回归、全量测试、check-gate | 一致 |
| 显式 resume 入口 | `--resume` 只能恢复 EventStore 判定的唯一未终态 thread；终态、未知或其他 thread 必须 fail-closed | `cli/dev_loop.py`、`cli/active_action_source.py` | T912 终态/非当前 thread 回归 | 一致 |
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

- 全量回归：`3057 passed, 1 skipped`。
- 严格覆盖率：`90.66%`，以 `pyproject.toml` 基线为准。
- 架构专项：单一运行时、架构收敛、Runtime Identity、Revision 共 `51 passed`。
- 产品验收/collector 定向：`70 passed`。
- `Ruff`、核心源码 mypy（249 个文件）、产品脚本 mypy、`make check-gate`、规则同步检查通过。
- T909 新制品 `5.8.0-rc.5+sha256.49b19a755b6cd8e8` 的 Codex/Claude Code archive smoke 通过，且两宿主 Build Identity 一致。
- T910 新制品 `5.8.0-rc.5+sha256.562d231e9f74263a` 的 Codex/Claude Code archive smoke 通过，且两宿主 Build Identity 一致；该新制品尚未进行真实产品卸载重装。
- T911 新制品 `5.8.0-rc.5+sha256.85c76f49dbacd4c6` 的 Codex/Claude Code archive smoke 通过，且两宿主 Build Identity 与 content SHA 一致；随后已用官方本地安装器完成 Codex/Claude Code 卸载重装并校验同一 Build。自动验收仍明确为 `product_install: not_run`，因为该脚本不模拟真实产品安装。
- T912 制品 `5.8.0-rc.5+sha256.819989ddb7274d48` 已通过 Codex 与 Claude Code archive smoke；两端 content SHA 均为 `819989ddb7274d485456f0013779c6c1e80b162e5135844419d69d1a361fcdeb`，随后官方本地安装器均返回 `status=installed` 并校验同一 Build。自动验收仍为 `product_install: not_run`。
- 归档自动验收仍返回 `product_install: not_run`（该脚本只做隔离 smoke）；随后已用项目官方本地安装器分别对 Codex 与 Claude Code 完成卸载重装，两个宿主均校验到同一 Build Identity。该安装事实仍不能替代真实连续 L4、Recovery Canary 或 Voice Clone 业务证据。

## 五、追加发现：首次 runtime bootstrap 失败边界

本次对历史真实宿主日志的复核发现了一个与原事故不同、但同样会被用户感知为“Loop 一启动就挂”的边界：

- 在 `_scratch/real-l3-codex-20260929/` 的真实启动记录中，首次 `ae-run --init` 先因默认 `uv` 缓存目录无权限失败；改用临时缓存后，又因无法联网解析 `hatchling` 失败。
- 失败发生在 Core `dev-loop --init` 进入 EventStore 之前，不能归类为 `EVENT_THREAD_NOT_FOUND`、Action 恢复失败或 Loop 状态损坏。
- 原 `scripts/ae-run` 直接把 `uv` 的 stderr 和退出码冒泡，宿主侧缺少稳定的“启动依赖失败”边界，容易继续盲目重试或误判为 Loop 中断。

修复为启动器边界的单一归一规则：

1. `uv venv` 失败时返回原退出码并输出 `AE_RUNTIME_BOOTSTRAP_FAILED`。
2. 首次 `uv run` 失败且项目 runtime 尚未物化 `bin/ae` 时，同样输出该错误码；保留原始 stderr 供诊断。
3. 如果 `bin/ae` 已经存在，则非零退出仍保持 Core/业务错误原语义，不被误标成 bootstrap 失败。
4. 不创建 EventStore 事件、不创建 lease、不自动改写为 `WAIT_RESOURCE`，也不启动第二个恢复循环。
5. `scripts/ae-host-run` 的预 bootstrap watchdog 探针不得吞掉该稳定错误；必须原样保留 stderr 和退出码，并在进入 Loop 前不创建 `.ae-state/events.db`。

T909 验证证据：新增宿主适配器回归使全量达到 `3052 passed, 1 skipped`；严格覆盖率为 `91%`；Ruff、mypy（249 个源码文件）、shell 语法与 `make check-gate` 通过。新制品在 Codex 与 Claude Code 两宿主 archive smoke 均通过，Build ID 为 `5.8.0-rc.5+sha256.49b19a755b6cd8e8`；自动验收仍明确为 `product_install: not_run`。

这项修复解决的是“宿主启动前置失败被伪装成 Loop 失败”的诊断和重试边界，不改变 D17 单 Tick、D53 单 Coordinator、D78 单一运行时或 D79 Worker repair 语义；它也证明了启动器与宿主适配器之间只有一条 bootstrap 错误边界，没有新增第二个 Loop。

## 五点一、T910：Worker 绑定解析不能降级

本轮补齐了一个此前未覆盖的身份错配边界。当前 Action 顶层的 `fencing_token` 是 Host session lease，Host Worker 模板中的 `fencing_token` 是按 `message_id + worker_id + generation` 派生的 Worker fence；两者属于不同层次，不能错误要求字面相等，但也不能因模板 fence 缺失而退化为只有 generation 的绑定。

修复后的唯一解析器要求：Action 绑定存在时，Worker 模板必须同时具备合法 generation 与 Worker fence，且 generation 必须一致；Action 顶层没有重复绑定时，只要模板携带绑定，native recovery probe 仍必须命中 canonical `message_id + worker_id + generation` 路径。这样可以拒绝“项目根内、JSON 合法、但属于旧代际或错误 Worker 的文件”，同时保留未绑定历史迁移 fixture 的兼容边界。

证据：先以红测试复现模板 fence 缺失和模板绑定下的 path drift，再修复统一解析器；相关回归 190 项通过，全量 `3056 passed/1 skipped`，严格覆盖率 `91%`，Ruff、mypy、shell 语法和 `make check-gate` 均通过。隔离的开发 Worker 回路同时暴露了“Worker 结果声明了 files_changed，但工作区快照未产生对应源码”的一致性风险；该风险随后由 T911 收口，本轮没有把隔离 scratch 结果冒充生产变更。

## 五点二、T911：Developer 变更证据必须与任务路径相交

本轮把隔离回路暴露的“声明了 `files_changed`，但实际没有对应源码变更”落实为生产回归。旧的 `GitDiffExists` 只要发现工作区存在任意 tracked/staged diff，就会通过；如果仓库里恰好有别的文件变更，当前 Worker 即使没有写入声明文件，也可能进入后续 Gate。

修复后的单一证据规则是：未暂存 diff、staged diff、最近授权 commit 以及 root commit fallback，都必须按当前 `files_changed` 做 Git pathspec 过滤；删除文件仍保留 pathspec，不因文件已不存在而丢失证据。没有声明文件时，不能用任意 diff 充当开发证据，只能在验证型 batch 的目标文件全部存在且 Core 测试证据通过时走明确的 zero-diff 豁免。默认链将 `FileAccessGuardrail` 前置，越界文件先返回 `block`，不会被 `GitDiffExists` 的 `retry` 抢先遮蔽。

证据：先以两个红测试证明无关 tracked/staged diff 会错误通过，再完成路径过滤、root commit 证据下沉和 Guardrail 顺序修复；相关回归 125 项、全量 `3056 passed/1 skipped`、严格覆盖率 `91%`、Ruff、mypy、shell 语法与 `make check-gate` 均通过。`guardrail.py` 从 636 行降至 614 行，未放宽文件行数门禁。T911 制品 `5.8.0-rc.5+sha256.85c76f49dbacd4c6` 已通过 Codex/Claude Code archive smoke。

## 五点三、T912：显式 resume 不能绕过唯一活动 thread

审计发现 `run_tick_step` 已经通过 `unfinished_threads()` 选择唯一未终态 thread，但 `run_tick_resume` 仍直接按 CLI 传入的 `thread_id` 读取 Action 快照。由于终态 thread 的快照仍可存在，这会让旧 Action 被重新输出，形成“看似恢复、实际重放历史”的旁路。

当前修复把 `--resume` 也绑定到同一 EventStore 选择规则：没有未终态 thread 时返回 `EVENT_THREAD_NOT_ACTIVE`；传入的 thread 不是唯一未终态 thread 时返回 `PROJECT_THREAD_NOT_ACTIVE`；只有绑定通过后才读取该 Action 快照。这样没有新增状态源、循环或兼容路径，且与 D77 的 fail-closed 语义一致。

证据：先以终态 thread 回归复现旧 Action 被输出，再以非当前未终态 thread 回归锁定显式参数绕过；修复后相关 CLI/架构/恢复/宿主回归 `198 passed`，Ruff、目标源码 mypy 和 `git diff --check` 通过。

## 六、仍未闭环的发布证据

以下项目不能由本地测试推断完成：

1. 同一最新 Build 已实际安装到 Codex 和 Claude Code；仍需各执行一次真实设计驱动命令并收集完整产品 evidence。
2. 真实宿主完成 Architect → Developer → Critic → Verification 的连续推进。
3. 发生一次真实 Recovery Canary，并证明恢复 Action 与 `ResultAccepted` 的 causation chain。
4. Voice Clone 真实业务 Gate、usage、machine evidence 和最终 `TERMINAL` 同时通过。
5. 两宿主均满足单次调用、零非预期人工协议修复、零旧状态误续作。

在这些证据齐全前，发布结论必须保持 `◐`。这不是降低实现标准，而是把“代码正确”与“产品真实可运行”分层，避免再次用绿色单测掩盖真实宿主中断。

## 七、后续执行顺序

1. T909 源码、质量门禁与双宿主 archive smoke 已完成；新制品为 `5.8.0-rc.5+sha256.49b19a755b6cd8e8`。
2. T912 新制品已通过两个宿主 archive smoke，并已用官方本地安装器完成 Codex/Claude Code 卸载重装，两个安装器均返回同一 Build Identity；归档自动验收的 `product_install: not_run` 仅表示它不模拟真实产品安装。
3. 下一步运行最小真实宿主 Canary，确认首个 Action、lease、native Worker 和 `record → finalize → validate → tick` 链路；若环境前置失败，应只出现 `AE_RUNTIME_BOOTSTRAP_FAILED`，不得伪造 Loop 状态。
4. 再运行 Voice Clone L4；任何失败必须按 Core、Host、Worker、外部模型、业务项目和验收链六类归属，禁止只修最后一个错误码。
5. 只有双宿主证据由 `product_acceptance.py` 重新读取并通过后，才允许关闭 P0-E2E。

## 明确禁止的回退

- 不恢复 Python Supervisor、Round、CheckpointStore 或第二个 EventStore。
- 不把 `WAIT_RESOURCE`、wait 到期或 provider idle 自动改写为业务失败。
- 不通过降低 schema、关闭 attestation、跳过 native manifest 或放宽 policy 来让验收通过。
- 不把 archive smoke、历史 L4、单元测试或人工补写 evidence 当作当前产品完成。
