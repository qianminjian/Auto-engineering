# 2026-09-07 Architect 计划截断与 Host 提前让出事故

## 结论

本次不是单一 Worker 超时，而是两个跨层契约同时失效：

1. Codex Host 没有执行 Action 声明的长等待与返回后续驱动合同，短等待后把 `CONTINUE` Action 留给人工恢复。
2. Worker 已提交完整 Architect 计划，但 Coordinator 修复结果只保留了部分 batch；Core 只做结构校验，没有做 Worker 产物到 accepted Result 的完整覆盖校验。

因此系统发生的是业务语义丢失：Worker 产出的 8 个 batch/27 个任务，最终只激活了 B1/1 个任务。EventStore 没有损坏，但 accepted Result 已不再代表 Worker 的完整产物。

## 证据

- 报告：`docs/auto-engineering-loop-report.md` 第 6、8、21-23 行。
- Worker outcome journal：`.ae-state/host-runtime/outcomes/17d83628-1093-4fc4-987b-73ebbd235a14.json`。
- Worker payload batch：B1-B8，共 27 个任务。
- accepted Result batch：仅 B1，共 1 个任务。
- `active-lease.json` 的 `disposition=CONTINUE`、`yield_allowed=false`，说明宿主返回不应结束当前 Action。

## 根因

当前校验只保证：

- `batch_plan` 非空；
- batch/task 字段和类型合法；
- accepted candidate 内部可以被 BatchState 物化。

当前校验没有保证：

- accepted Architect plan 是 Worker 业务产物的完整投影；
- repair 不能删除未完成 batch/task；
- ProgressTree/BatchState 的总量没有被截断结果重定义；
- Host 实际 wait 参数与 Action 合同一致；
- Host 返回后 `CONTINUE` 必须自动回查并恢复同一 Action。

## 修复工作包

| ID | 工作 | 验收 |
|---|---|---|
| P0-PLANSOURCE | Worker 业务结果生成 canonical coverage manifest/digest；Architect accepted Result 必须完整覆盖 Worker 计划 | 8 batch/27 task 被压缩为 B1/1 时稳定返回 `ARCHITECT_RESULT_COVERAGE_LOSS`，不激活、不推进 |
| P0-REPAIR | 同 Action repair 只能修复 Coordinator 序列化/字段问题，不得缩减业务计划 | rejected→repair 保留原 Worker outcome、coverage digest 和完整任务集合 |
| P0-HOSTWAIT | Host wait 与 continuation 合同变成可执行校验 | 短 wait、未确认终态、`CONTINUE` 让出均进入 recovery，不得静默结束 |
| P1-SCOPE | Developer/Critic/Verifier 统一执行声明范围、Core active scope、实际 evidence 三方绑定 | 错 batch、缺 task、超范围 coverage 均 fail-closed |
| P1-E2E | 公开 CLI 复现本次事故并覆盖中断恢复、repair、跨阶段范围校验 | 安装后 E2E 覆盖率≥80%，项目总覆盖率保持≥90% |
| P2-STRUCTURE | 拆分超大协议文件，减少同一规则分散和遗漏 | `make check-gate` 不因 line-count 失败，行为不变 |

## 当前修复状态（2026-09-07）

- 已完成首轮 P0 防线：Worker/Coordinator Architect coverage 校验、accepted Result manifest、公开 CLI 截断回归、Codex Hook wait timeout 与 running observation 回归、Developer active batch identity 校验。
- 验证结果：全量 `3094 passed, 1 skipped`，覆盖率 `90%`（20128 statements）；Ruff、mypy（226 个源文件）、compileall、Schema、diff 检查和设计资产测试均通过。
- 已补齐 Developer task/file scope、Critic implementation finding scope、Component Verifier design-item/file scope、System Verifier 每条设计项的身份/证据/说明，以及全局 Verifier/Audit 的显式文件 scope；同时修复 Component Verifier 覆盖状态按组件覆盖的问题，改为按 `design_item` 合并，并要求 System Verifier 的条目集合与跨阶段事实集合一致。缺条目现在稳定 fail-closed，并有直接回归与 Codex/Claude 黄金轨迹回归。
- 尚未宣称事故闭环：Host 已增加 Stop/SessionEnd 的 status→resume 机器合同，但真实宿主是否在返回边界持续执行仍需 L3/L4 证明；真实双宿主 L3/L4 仍未完成。`make check-gate` 仍受 11 个既有超长协议文件的 line-count 门禁阻断，当前不把 P2 结构整理冒充 P0 闭环。
- 最新候选包 `5.8.0-rc.5+sha256.993d9708829b9ec6` 已通过 Codex 与 Claude Code 的 archive smoke；两者 `product_install.status=not_run`，所以该证据不能替代真实宿主产品 L3/L4。

## 当前运行态处置

目标项目的 active Action 保留用于审计与回放；不得手工编辑 `.ae-state`，也不得盲目从被截断的 Architect Result 继续 Developer。修复完成后应以新的回放测试和显式恢复流程处理该项目。

## 2026-09-07 新鲜双宿主 L3 复验与新增缺口

同一候选 Build `5.8.0-rc.5+sha256.d85163d3586fde2a` 在全新项目、全新原生会话中完成了真实 L3：

- Codex：`Gap Scan → Architect → Developer(B1/B2) → Critic → TERMINAL/GOAL_ACHIEVED`。
- Claude Code：`Project Setup → Gap Scan → Architect → Developer → Critic → TERMINAL/GOAL_ACHIEVED`。
- 两个宿主均无手工修改 outcome/receipt/EventStore，无活动租约；Claude 真实轨迹包含同 Action 的 Setup 修复、原生 Worker wait、私有 outcome 回写和 Critic 收束。
- 两个状态投影都明确保留 `product_business_acceptance` 未验证；L3 Core 收敛不能替代 L4 产品 Gate。

复验还暴露出一个此前设计没有足够前置约束的初始化问题：Claude `project_setup` 首次生成的 Python `pyproject.toml` 使用了当前 Ruff 不接受的 `src_paths`、`[tool.ruff.lint] src` 和路径数组 `extend` 形状，导致首轮 lint 解析失败。宿主随后在同一 Action 内修复并恢复成功，但用户不应先看到这类可预防失败。

新增修复：Project Setup 的 Core Action、宿主 Skill 和 dev-loop Command 现在明确规定 Ruff 源码路径只放在 `ruff check src tests` 命令参数中，最小 `pyproject.toml` 不生成路径型 Ruff 配置；并增加 Action 文案回归。后续仍需在 L4/新鲜 Build 中验证初始化首轮不再产生该失败。

当前回归证据：`3096 passed, 1 skipped`，覆盖率 `90%`；Ruff、mypy（226 个源文件）、compileall、发布资产检查和 `git diff --check` 通过。`make check-gate` 仍因 11 个既有超长协议文件失败，属于 P2 结构债务，不是本次功能测试失败。

## 2026-09-08 宿主返回边界与无输出挂死复验

新候选 Build `5.8.0-rc.5+sha256.a69a794684241860` 的定向回归新增 16 项宿主边界测试，覆盖自动续驱动、租约保留、无输出超时和嵌套适配器拒绝。

真实 Codex 复验得到两类证据：

- 首次宿主长时间无 stdout，Core 仍保持同一 Architect Action 与 `CONTINUE` lease；适配器按 60 秒观察窗写入 `HOST_PROCESS_IDLE_TIMEOUT`，随后自动恢复同一 Action，日志出现两次有界恢复，不创建新的 Tick/Worker。
- 宿主侧 Codex 模型缓存反复报 `missing field base_instructions`，并出现 WebSocket stream disconnect；这属于外部宿主运行环境故障，不是 Core 业务状态推进。达到 `--max-resumes 2` 前后，active Action 仍被保留，禁止伪装成成功。

本次补强：`scripts/ae-host-run` 默认增加 300 秒 stdout 无输出上限，所有超时仍先回查 Core 再决定恢复；外部中断只做正常退出和租约保留，不再删除临时目录后继续回查；通过 `AE_HOST_ADAPTER_ACTIVE` 拒绝重复嵌套宿主适配器，避免外层和宿主内部各运行一套恢复边界。当前仍不能把该次 Voice Clone 运行计为 L4 TERMINAL：真实宿主环境在 Architect 阶段无进展，产品证据链尚未闭环。

最终安装候选为 `5.8.0-rc.5+sha256.e6f888be0c10876f`；Codex/Claude 发布资产检查均通过，Voice Clone 独立 `lint/test/build` 业务 Gate 均为 pass。该业务 Gate 证据不等于真实宿主 L4，仍需在宿主外部故障恢复后完成完整 Loop 轨迹、Claude 等价轨迹和 collector→product_acceptance 证据链。

## 2026-09-08 追加发现：原生合同拒绝的反馈死循环

在最终候选 Build `5.8.0-rc.5+sha256.0998c91b1fd0ff4c` 的 Claude 真实复验中，Core 保持在同一 Architect Action，Hook 正确拒绝了把 `native_result_path` 当作 Worker 私有 `outcome_path` 的 Agent 启动请求；但宿主模型连续重试，随后 Stop hook 反复返回 `Blocked by hook`。一次会话产生 95 轮重复反馈，最后虽未伪造成功，仍消耗了约 8 分钟和大量上下文，说明“严格拒绝”本身没有配套的宿主级有界熔断。

修复为唯一外层 `scripts/ae-host-run` 增加实时拒绝计数，默认 8 次，可通过 `--max-protocol-refusals` 调整；达到上限后记录 `HOST_PROTOCOL_RETRY_EXHAUSTED`，保留同一 active Action/lease，退出 75，不再自动 resume。新增回归验证同一宿主不会继续反馈循环。这个事件仍不计入 L4 成功：真实产品必须在合同正确消费后重新通过 Architect→终态轨迹。

同一轮真实 Claude 复验又暴露了更基础的准备阶段缺口：Worker 按正确的 `native_launch_prompt` 启动后，首次尝试创建其声明的 `outcome_path` 父目录，被 Hook 以“Worker 写入不属于当前 Action 的 outcome 路径”拒绝。原因不是 Worker 业务错误，而是设计合同要求 Host Runtime 预创建绑定目录，实际实现却只创建了通用 `work_files`（`outcomes/coordinator_result/result`），没有预创建 Worker 的 `outcome_path`、`native_result_path`、`observation_path` 和 `receipt_path` 父目录。修复为 Host Runtime 在 Action 绑定和 root-bound 校验通过后一次性创建全部声明目录，并把这些路径的越界作为启动前 fail-closed 条件；同时把拒绝熔断模式扩展到所有已知 native Worker 协议拒绝码。新增目录准备与越界回归测试。该旧包轨迹仍不计入 L4，必须用包含此修复的新 Build 重新验收。

新 Build 的真实 Claude 续接又发现了结果格式边界：Component Verifier 原生 Agent 已正常完成并返回完整 Claude envelope，但正文只有自然语言，没有 `expected_format` 要求的单个结构化业务 JSON。Coordinator 随后尝试自行读取/改写 native result，连续触发“禁止读取 Worker prompt/禁止手工回写/`NATIVE_RESULT_INVALID`”，最终被 8 次协议拒绝熔断。这里不能放宽为接受自然语言，也不能允许 Coordinator 伪造完成事实；正确的边界行为是固定 `record-worker-outcome` 调用一次，将该 Worker 归类为 `HOST_WORKER_OUTPUT_INVALID` 的失败 outcome，保留原始 native envelope，再走同一 Action 的失败/Finalizer 路径。代码已补充该分类、提示契约和回归测试；当前运行不计入 L4，需用新 Build 验证失败 Worker 是否能正常闭环并继续/终止。

## 2026-09-08 追加发现：Gap Scan 修复退化与宿主终止边界

在新 Build 的全新 Voice Clone 目录中，首次 Gap Scan 曾生成完整的 28 章覆盖；随后 Coordinator 的同 Action 修复结果退化为单个 Gap、单个 `section_findings`，Core 连续以 `SECTION_FINDING_MISSING` 拒绝。结果 Journal 的 `attempt` 已达到 6，说明“允许同 Action 修复”如果没有上限，就会把模型的格式修复错误变成反馈循环和时间消耗，而不是稳定失败。

本次修复：`OutcomeJournal` 将同一 Action 的语义组装修复限制为 3 次；达到上限后公开 CLI 返回 `HOST_RESULT_REPAIR_EXHAUSTED`，保留 rejection history、active Action identity 和违规列表，由宿主 Stop Report 交接，不再自动继续或重新启动 Worker。这个上限只约束语义组装修复，不改变 Worker 失败重试合同。

同一轮真实复验还发现，宿主 stdout 无输出 watchdog 即使已经判定 idle timeout，若宿主进程忽略 `TERM`，外层 `wait` 仍可能永久阻塞。适配器现改为 TERM 后最多等待 5 秒，仍存活则 KILL 目标宿主并继续记录 `HOST_PROCESS_IDLE_TIMEOUT`/`HOST_PROCESS_TIMEOUT`；新增回归覆盖忽略 TERM 的子进程。该边界只终止宿主进程，不创建 Tick、Result 或 Worker 事实。

这两项修复共同落实一个底线：失败可以进入可审计的恢复或停止，但不能变成无上限的模型反馈循环，也不能让宿主边界本身无限挂死。最终 Build `5.8.0-rc.5+sha256.860d2d26bd3740e1` 的全量回归为 `3113 passed/1 skipped`、覆盖率 `90%`；真实 Voice Clone L4 仍未形成 `TERMINAL` 与产品证据链，不得宣称发布完成。

## 2026-09-08 追加发现：嵌套 transcript 误熔断与 Claude 启动认证边界

新的真实 Claude 复验发现，外层适配器把原生 Worker transcript 中的普通 `Blocked by hook`
文本当作协议拒绝。该文本可能只是 Worker 尚未完成时的嵌套 Stop hook 反馈，不能越层触发
宿主熔断；现已改为只统计明确的 `NATIVE_*`/宿主协议错误码，并有回归测试证明普通文本不会
中断合法宿主输出。

同一复验还确认，当前 Claude CLI 使用 `--setting-sources project` 会排除登录来源并返回
`authentication_failed / Not logged in`。Runbook 已改为 `user,project` 配合
`--strict-mcp-config`，保留 OAuth/keychain 认证，同时不加载用户 MCP；启动前还必须做同参数
的只读 capability/auth probe，环境未登录时在 Action 启动前报告，不得伪装成 Worker 失败。

最后，真实宿主启动阶段出现 stdout 长时间为 0 字节而旧 shell 计数 watchdog 未收敛的现象。
适配器现改为独立 Python watchdog，使用 monotonic 时间、增量协议码扫描和 TERM→KILL 的
有界终止合同；这类启动阻塞应形成 `HOST_PROCESS_IDLE_TIMEOUT` 或认证故障证据，而不能
无限等待。

## 2026-09-08 追加发现：Coordinator 轮询造成上下文放大

在使用同一 Build、绝对插件 runner 的真实 Claude Critic 轨迹中，Critic Worker 已经有
`native retrieval=success`、`task.status=completed`，但 Coordinator 没有消费已完成的
Worker outcome，而是重复执行同一 Action 的 `dev-loop --resume`/status 轮询。一次会话达到
122 轮，最终触发 `API Error: 400 invalid params, context window exceeds limit (2013)`，累计
约 13.8M input tokens、约 70 美元；这不是“Worker 还在正常工作”，而是 Coordinator 没有
进展却持续增长上下文的反馈放大。

修复为外层 `ae-host-run` 增加同一宿主尝试内的 Coordinator resume poll 上限，默认 32 次，
可用 `--max-coordinator-polls` 调整。达到上限时记录 `HOST_COORDINATOR_POLL_LIMIT`，保留
active Action/lease、退出 75，禁止自动继续；修复 Coordinator 消费 Worker outcome 的逻辑
后再显式恢复。该保护与 Worker wait/liveness 分离，不会因为单次合法长耗时 Worker 直接被
误判为失败。新增回归覆盖重复 resume 的有界收尾。
