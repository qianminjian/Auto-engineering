# 2026-09-29 Loop 恢复与宿主交接边界审计

## 结论

本轮问题不是某一个 `if` 写错，而是“同一 Action 的事实”在恢复、宿主交接和失败分类三个边界没有完全收口：

1. EventStore 恢复曾直接信任 projection/action snapshot，未验证事件重放结果、序列和身份是否一致。
2. 显式 `thread_id` 曾可能绕过唯一未终态 thread 的选择规则，把历史或终态 thread 带入恢复。
3. Worker 的 invocation、Host template、native result、private outcome 和 observation 曾存在不同 generation/path 绑定，导致“文件存在”被误认成当前 Worker 的事实。
4. Codex wait 的观察预算耗尽不等于 Worker 已终止；通用失败终结器仍可能把未确认所有权写成 `HOST_WORKER_TIMEOUT`，随后触发重试。
5. 非法 recovery kind 或缺失 `host_execution` 曾有默认降级路径，可能保留 spawn 能力。
6. 相同 assembly rejection 可能重复累计 attempt，quarantine 文件名也可能在不同 fencing 下覆盖证据。
7. 宿主 stderr 已被保存为独立证据，但如果不继续转发到适配器前台，嵌套边界会表现为“静默成功”。
8. Release 源树的 symlink/hardlink 直到安装阶段才可能暴露，造成构建绿、安装红。

这些问题共同解释了“Loop 一运行就中断、重复修复后又在另一层报错”：失败事实、恢复事实和宿主进程事实没有共享一条可验证的身份链。

## 设计对齐

当前唯一运行时基线仍为：主 Agent Coordinator → Python 单 Tick → EngineState → EventStore/Reducer；Host 只负责受约束的 spawn/wait/record/finalize/continuation，不创建 Tick、不维护第二套 Loop 状态。

本轮没有改变 BEACON 的架构决策，也没有放宽设计标准。终态 thread 只允许 `status` 只读查看；`resume` 必须命中唯一未终态 thread，并且恢复包必须可以由事件流确定性重建。

## 已实施的闭环修复

### Core / EventStore

- 新增 recovery bundle：读取 stream、projection、active action，并验证 stream 非空、sequence 连续、thread identity 一致、projection 可重放、projection sequence 与 action snapshot sequence 一致。
- 恢复失败统一转为 `STATE_RECOVERY_INVALID`，不回退到 checkpoint、旧 snapshot 或其他状态源。
- 显式 `thread_id` 必须等于唯一未终态 thread；历史/终态 thread 不得进入 resume。
- `--status` 在没有未终态 thread 时只读最新终态 projection，不调用恢复入口，不生成新 Action。

### Host / Worker 证据

- 当前 Action 的 invocation outcome path 在 generation binding 后重写为 canonical path，`record`、`inspect`、`repair` 和 `native` path 使用同一代际。
- Worker ready、native repair 和 failure binding 均校验 generation/fencing；缺失模板不再静默返回未绑定结果。
- Codex `native_wait` 的 timeout 只有在 observation 为同一 Action、同一 Worker、同一 generation/fence、同一 native handle，且原生状态明确为 `timed_out` 时才进入 timeout budget。
- 未确认终止事实统一生成 `HOST_WORKER_OWNER_LOST`，由 Tick 导向 `WAIT_RESOURCE`，保留当前 Action，禁止并发重跑。
- private artifact 损坏与有效 bound native 的恢复仍是同 Action repair；invalid/unbound native 仍是同 Action protocol failure，均不得 spawn。

### 恢复 / 幂等 / 退出边界

- 非法 recovery kind 显式降为 protocol failure；缺失 `host_execution` 时生成无 spawn 的 fail-closed recovery view。
- 相同 assembly rejection 以 rejection fingerprint 幂等重放，不重复增加 attempt；quarantine 文件名纳入 fencing digest，避免跨代际覆盖。
- Worker failure 只按结构化 status/error_code 识别 timeout，不再从自由文本 `TIMEOUT` 等关键词误判业务失败。
- `ae-host-run` 同时保存 stdout/stderr 独立证据，并将 stderr 转发到前台；Stop Report 优先记录可识别的 stderr provider timeout。
- release 构建阶段拒绝 symlink/hardlink，避免归档摘要与安装树不一致。

## 验证证据

- 前一轮定向回归：269 passed，覆盖 EventStore recovery、tick transaction、Worker generation/fence、recovery projection、Host assembler、Outcome Journal、process exit、failure service、release archive 和 P0 跨进程 E2E。
- 本轮相关定向回归：199 passed，新增历史协议失败占位→同代 native repair 的公开 CLI 与 Host assembler 回归。
- 新鲜验证：串行全量 `3046 passed, 1 skipped`；严格覆盖率 `91%`；相关源文件 mypy、Ruff、shell 语法检查和 `make check-gate` 通过。
- 新 Build `5.8.0-rc.5+sha256.7976525f5985e118` 已按官方流程卸载并重装 Codex、Claude Code；两端入口 `build-info --expect-build-id` 均通过，且均为 `source_kind=packaged`。
- 额外回归：native wait timeout 无终止观察进入 owner lost；匹配 terminal observation 才进入 timeout；终态 `--status` 不再要求 active Action；release symlink 在构建期拒绝。
- T902 额外回归：坏 private artifact 首次被移入绑定 quarantine，重复 record 从 bound native 重建 canonical private envelope；公开 CLI 完成 `record→finalize→validate→tick`，不重新 spawn，且保留唯一 completed outcome。
- Ruff、相关 mypy、shell `sh -n` 已通过。

## 对 2026-09-28 外部真跑报告的二次复核

外部报告中的关键事实已在只读状态库中复核：native result 是 `developer-0`、`completed`、13 passed/0 failed；私有 outcome 只有 `status` 与 `payload`，缺少 Host 交接所需的外层身份/摘要；共享 outcomes 已先写入 `HOST_WORKER_OUTPUT_INVALID`。这不是“Worker 没做完”，而是一个已经落盘的协议失败占位。

复核当前实现后又发现原修复仍有两处边界缺口：

1. 恢复投影在看到完整的失败 outcomes 后会提前返回，未再检查绑定 native 是否可修复；因此历史上已经写入协议失败的 Action 仍可能错过 `worker_artifact_repair`。
2. 即使投影出 repair，同一 generation/fencing 下的协议失败占位也不能被 completed native outcome 替换；原逻辑只允许更高 generation 的失败重试，导致修复在共享 outcomes 合并处再次 `OUTCOMES_CONFLICT`。

本轮已补齐：

- 在 `recovery_contract` 集中定义 Worker 协议错误码集合，Worker failure 与恢复投影共享同一分类事实。
- 恢复投影对协议错误优先执行 artifact/native 分类；只有确认 native 绑定有效时才绕过“失败 outcomes 已完整”的短路，其他真实 Worker 失败仍保持原有保护。
- 允许同一 Action、同一 Worker、同一 native handle、同一 generation/fencing 的协议失败占位，被验证过的 completed native outcome 一次性替换；不同句柄、代际或围栏仍 fail-closed。
- 增加公开 CLI `record → finalize → tick → record` 回归，覆盖“先写协议失败、后补有效 native 结果”的真实恢复顺序，确认不重新 spawn、共享 outcomes 只保留一条 completed 事实。

## 尚未关闭的发布门禁

## T902：`worker_artifact_repair` 的原文件隔离缺口

对照 D79 和主设计 §6.11 重新检查后发现，前一轮虽然已经允许“坏 private + 有效 bound native”进入
`worker_artifact_repair`，但 `quarantine_private_artifact()` 只写了脱敏索引，原坏文件仍留在
canonical `outcome_path`。这与“隔离原私有文件、从 native 重建 canonical envelope”的设计不一致，
也会让重复恢复继续读取同一坏文件，无法证明隔离已经完成。

本轮将修复收口为单一语义：首次 repair 校验源文件字节未发生竞态后，把原始字节原子移动到
Action/generation/fencing 绑定的 `.artifact` 隔离文件，同时写入 `.json` 索引；canonical
`outcome_path` 保持空闲。重复 record 时从有效 native 结果重建 canonical private envelope，
共享 outcomes 仍保持同一条幂等事实；不同内容、路径越界或隔离读写异常均 fail-closed。没有改变
主 Agent 唯一 Coordinator、Python 单 Tick 或 EventStore 唯一事实源。

新增证据覆盖：首次隔离、重复调用后的 canonical 重建、quarantine 原始字节摘要、公开 CLI
`record → finalize → validate → tick` 完整链，以及原生结果无效时仍保持协议失败。该缺口属于
恢复证据边界，不是 Worker 业务失败，也不允许通过重新 spawn 绕过。

本轮修复解决的是 Loop/Core/Host 交接的确定性与 fail-closed 问题，不等于真实产品 L4 已通过。仍需单独完成：

- 同一新 Build 在 Codex 与 Claude Code 的独立安装、doctor、入口自检和真实宿主连续运行。
- Recovery Canary：中断、owner uncertain、重复回写、迟到结果和跨进程 resume 的真实证据。
- Voice Clone 真实业务链路和最终 TERMINAL/WAIT_USER 结果。
- 新鲜覆盖率基线和 `make check-gate` 已通过；仍需以下产品级门禁。

这些门禁不能用单元测试、archive smoke 或一次成功 Canary 替代；在全部证据齐全前，不能把项目描述为 L4 完成。

## T903：native recovery probe 的代际路径漂移

继续沿着 D76/D79 检查“私有文件缺失、native 文件存在”的恢复分支时发现，`native_result_worker_ids()`
此前只验证项目根边界、Worker ID 和 native JSON 能否被 parser 接受，没有验证文件路径是否等于当前
Action 的 `message_id + worker_id + execution_generation` canonical 路径。于是旧代际或手工放入的合法 JSON
可能被误投影为当前 Action 的可修复证据，形成与原始事故相同类型的“文件看似有效、身份实际不属于当前任务”问题。

修复后，artifact repair 与 native recovery probe 共用 `bound_native_result_path_is_valid()`：当 Action
声明 generation/fencing 时，必须先通过统一 generation/fence 解析，再命中 `worker_native_result_path()`；
漂移、缺失或非法绑定均返回不可修复，保持同 Action fail-closed，不 spawn、不消费业务失败预算。无代际字段的
历史迁移输入仍保留原有根路径兼容，但当前生产 Action 的绑定字段一旦出现就不能降级。

证据：新增“stale native path 被拒绝、canonical path 被接受”回归，恢复/CLI/Host 相关 110 项通过；
`native_result_recovery.py` 与 `worker_artifact_repair.py` 变更源码 mypy、Ruff、check-gate 通过。

## T904：全量验证被测试环境变量丢失伪造为 Loop 回归

全量第一次执行出现 30 个失败，堆栈全部是测试临时 Git 仓库初始化时的 `/usr/bin/git` exit 69（macOS
Xcode license），不是 Loop 代码失败。根因是 Guardrail 测试为设置提交者身份而整体替换 `env`，丢失父进程
的 PATH 和 `DEVELOPER_DIR`；这会让验证环境随机选择系统 Git，造成“刚跑就崩”的假象。

测试辅助函数现在只覆盖需要的 `GIT_*` 字段，保留父环境中的 PATH/toolchain；115 项 Guardrail/Git
回归通过，随后完整串行回归 `3046 passed, 1 skipped`。这项修复没有改变生产 Loop 逻辑，但消除了质量门禁本身的非确定性。

## T905：Claude 产品证据缺少原始宿主用量时仍可通过

对照真实宿主验收 Runbook 检查产品 Gate 时发现，Claude collector 会生成原始 `stream-json` 用量证明，
但 acceptance 侧仍把缺失的 `host_usage_attestation` 当成旧 artifact 兼容情况直接放行。这样只要外层
artifact 声明了成本，产品验收就可能在没有原始宿主事实时继续，违背“成本必须来自宿主原始输出”的证据边界。

修复后，Claude artifact 在当前产品验收路径中必须携带并通过 hash、bytes、路径和原始 stream 用量校验的
`host_usage_attestation`；缺失时稳定返回 `HOST_USAGE_ATTESTATION_MISSING`，不会信任人工声明的成本。
旧 artifact 的宽松行为只保留在未声明当前 Claude 产品宿主的历史兼容调用中。

证据：产品 acceptance/collector 定向测试通过；后续全量串行回归 `3048 passed, 1 skipped`，严格覆盖率
`91%`。该修复只收紧产品证据 Gate，不改变主 Agent、单 Tick 或 EventStore 唯一事实链。

## T906：产品 native-result manifest 未复用当前 Action 代际绑定

继续检查 L4 产品证据时发现，collector 对已映射 Worker 直接信任 `host_execution.workers[].native_result_path`，
没有复用恢复探针已经使用的 `message_id + worker_id + execution_generation` canonical path 校验。
因此旧代际或手工漂移的合法 JSON 可能进入产品 manifest，形成“格式有效但身份不属于当前 Action”的假证据。

修复后，native recovery probe 与 product evidence collector 共用 `bound_native_result_path_is_valid()`：
当 Action 声明 generation/fencing 时，路径漂移立即返回 `NATIVE_RESULT_EVIDENCE_BINDING_INVALID`；只有当前
Action 的 canonical path 才能进入 manifest。无代际历史输入继续保留兼容边界，但当前绑定一旦存在就不得降级。

证据：新增 stale path fail-closed 回归；产品 acceptance/collector 定向 `68 passed`，全量 `3048 passed/1 skipped`，
覆盖率 `91%`，Ruff、核心 mypy、check-gate 通过。T900–T906 已完成源码级实现与测试验证，但本轮新制品安装验收仍需在提交后执行。
