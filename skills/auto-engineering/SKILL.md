---
name: auto-engineering
description: >
  宿主无关的 Tick-Based Loop Engineering 调度协议
  （architect → developer → critic → verification）。
  Use when the user invokes $auto-engineering, asks to implement through
  dev-loop, check loop status, resume a checkpoint, or run gated development.
---

# Auto-Engineering v5.8 — 跨宿主确定性会话 Tick 协议

Auto-Engineering 将职责拆成两层：

- Python 引擎是确定性 gatekeeper，负责路由、Guardrail、Gate、收敛和 checkpoint。
- 当前 Agent 宿主是执行器，负责推理、编辑、验证，并按 action 调用宿主原生子代理能力。

`$auto-engineering` 是 Codex 的显式入口；其他 Agent 平台使用各自的 Skill 或
Command 适配层进入同一协议。所有平台都必须通过 bundled `ae-run` 调用共享核心，
不得复制或分叉业务逻辑。

启动时先从当前已加载 `SKILL.md` 的绝对安装路径向上解析插件根目录，并固定 bundled runner。
本文后续每个 `ae-run` 都是
`env AE_HOST_PLATFORM=codex AE_HOST_ACTION_VIEW=compact <plugin-root>/bin/ae-run` 的缩写；实际工具调用必须保留该环境
前缀和绝对路径，不得把文中缩写当成实际命令；不得调用裸 `ae-run` 或另一宿主传入的 runner，不得依赖 PATH，
也不得搜索开发工作区或插件缓存来猜测入口。解析出的 runner 不存在或不可执行时，
以 `HOST_RUNNER_UNAVAILABLE` fail-closed。

## 铁律

<!-- FRAGMENT:iron_law_gatekeeper START -->
IRON LAW: PYTHON IS THE GATEKEEPER.
NO STAGE ADVANCEMENT WITHOUT `ae-run dev-loop --tick` VALIDATION.
You may NOT edit code before Python outputs {"action":"developer"}.
You may NOT declare done before Python outputs {"action":"done"}.
Violating the letter of this rule is violating the spirit of this rule.
<!-- FRAGMENT:iron_law_gatekeeper END -->

Git commit、push 和 PR 是外部副作用，只有获得用户明确授权后才能执行；宿主具备
相关能力不等于获得授权。

checkpoint 是循环恢复边界，checkpoint 不要求 commit。普通 developer batch 可以
保留未提交变更并继续 Tick；若某个确定性 Guardrail 确实需要 Git 写操作，必须暂停
并针对具体操作请求用户授权，不得把 checkpoint、clean working tree 或历史授权
解释为当前授权。

## 命令入口

| 用户意图 | 共享命令 |
|---|---|
| 启动开发循环 | `ae-run dev-loop --init "<requirement>"` |
| 预校验 Result | `ae-run dev-loop --validate-result <file>` |
| 推进一个 Tick | `ae-run dev-loop --tick --result <file>` |
| 查看循环状态 | `ae-run status --format json` |
| 恢复 checkpoint | `ae-run dev-loop --resume <id>` |

设计文档模式必须把自然语言需求和文档路径分开传入：

```bash
ae-run dev-loop --init "实现 Voice Clone 页面" \
  --design-doc design/V1.0-Design-VoiceClonePage.md
```

若只按设计文档的全部内容开发，可省略自然语言 requirement：

```bash
ae-run dev-loop --init \
  --design-doc design/V1.0-Design-VoiceClonePage.md
```

不得把 `design/*.md` 路径直接作为 requirement；启动后应核验首个 Action 的
`design_doc_path` 非空。

## Action 执行协议

产品入口必须设置 `AE_HOST_ACTION_VIEW=compact`。CLI stdout 返回的 compact envelope 是
当前执行控制视图；完整 Canonical Action 仍由 Core 持久化。若存在
`coordinator_prompt_ref`，只读取其 `path` 一次并核验 `sha256`，不得扫描 Action Store，
不得要求 CLI 重新内联 `instruction`、`context` 或 `subagent_prompt`。spawn Action 只把
`spawn.invocations[i].prompt_ref` 交给对应 fresh Worker；Coordinator 不再读取兼容字段
`subagent_prompt` 正文。

对每个 spawn invocation，Coordinator 必须把对应
`action.host_execution.workers[i].native_launch_prompt` **原样**作为原生 Worker 工具的
prompt/message。不得先读取、`sed`、复制、总结或拼接 `prompt_ref` 正文；只允许在主会话
用摘要命令校验文件 SHA-256。Worker 在 fresh context 内切换到机器指定 `project_root`，
自行读取并校验 Prompt Artifact 后执行。launcher 中只有路径、摘要和权限，不是业务 Prompt。

每次用户启动 Skill 时，先把宿主启动 `cwd` 的真实绝对路径固定为
`invocation_project_root`。首个 Core 命令必须是带用户原始参数的
`dev-loop --init`；该入口会自动检测已有 thread 并返回 active Action，
禁止先用 `status`、`find`、`rg` 或扫描 `.ae-state` 推测 Action。若仅执行
状态查询，必须原样消费 `status.next_operation`：其 operation 为
`resume_active_action` 时立即执行其 `argv`，不得自行改用无 Result 的 Tick。
若误调 Tick，只允许执行错误返回的同一 `next_operation`。

首个 `--init` 必须显式使用 `--project-root <invocation_project_root>`；相对设计文档只在
该根内解析。设计文档不存在、越界或 init 失败时立即报告并停止：禁止搜索父目录、`/tmp`、
其他项目或同名文件，禁止改写 `--project-root` 后重试，也禁止通过绝对路径切换项目。
取得首个 Action 后必须校验其 `project_root` 与 `invocation_project_root` 的真实路径完全相同；
不一致时报告 `HOST_PROJECT_ROOT_DRIFT` 并停止，禁止在新根初始化或继续。

若首个 Action 的 disposition 为 `CONTINUE`，当前主 Agent 就是唯一 Coordinator，必须在本次
会话内持续执行下面的 Action 合同。Python 不接管原生 Worker，也不替主 Agent 启动另一个
临时主会话；`--supervise` 只保留为迁移期旁路兼容，不得作为默认入口。

每次先读取 `action.extensions.ae.execution_control`。宿主必须在同一次用户启动中执行：

```text
while control.disposition == "CONTINUE":
  execute current Action
  validate and submit Result
  read next Action and its execution_control
```

`CONTINUE` 不允许向用户交回控制；`WAIT_RESOURCE` 由宿主回收已完成 Worker、等待容量
变化后自动重试原 active Action，不询问用户；`WAIT_USER` 只询问 `reason_code` 对应的真实决策；
`TERMINAL`、`ERROR`、`HANDOFF_REQUIRED` 分别表示正常终态、稳定错误和异常接管。
不得根据 stage 名、自然语言 recap 或“已经输出 Action”自行停止。

等待到期不是失败：一次 wait 未观察到完成只记录心跳并继续等待，不生成失败 Result、不消耗
重试次数、不重启 Worker。只有宿主明确证明 Worker/owner 已终止时才可判定失败；无法确认旧
Worker 已终止时必须进入 `WAIT_RESOURCE/WORKER_OWNERSHIP_UNCERTAIN`，禁止并发重跑。

每次取得下一 Action 后，若存在 `action.gap_scan_summary`，必须先向前台输出一次有界扫描摘要：
已核对的设计章节数、缺口数、是否存在阻断项及 `outcome`。`no_gaps_auto_continue`
只展示摘要并继续，不询问用户；`user_decision_required` 必须随后展示当前
`action.current_gap` 并等待用户决定。禁止用自由文本“未发现问题”替代机器摘要。

当 `reason_code == "STATE_RECONCILIATION_REQUIRED"` 时，宿主必须原样展示 Core
返回的 `gate.options`：`reinitialize`（重新初始化）或 `reconcile`（修复状态并继续）。
用户选择前禁止编辑项目文件；宿主不得自动恢复旧 Action、删除 `.ae-state` 或代替用户选择。
提交 Result 时 `gate_resolution.gate_id` 必须为 `state_reconciliation`，`resolution`
必须使用 option id（不是显示标签），并由 `causation_id` 绑定当前 Gate message。

然后读取并核验 `action.coordinator_prompt_ref` 指向的当前 Coordinator Prompt：

- `action.host_execution.recovery.status == "worker_outcomes_committed"`：这是恢复分支，
  必须在任何 `action.spawn` 或 Worker 执行判断之前处理。确认
  `spawn_permitted == false` 且
  `required_operation == "validate_then_submit_or_repair"`。先对 `result_ref`
  原样执行 `operations.validate.argv`：通过则执行 `operations.submit.argv`；业务预检失败则
  仅按 active Action `expected_format` 修复 `coordinator_result_ref`，使用
  Core 恢复的 `outcomes_ref` 并原样执行 `operations.finalize.argv`，再验证和提交。
  禁止创建、等待或回收新 Worker，禁止改写 outcomes；恢复合同不完整则
  fail-closed。
- `action == "error"`：报告 `error_code` 和 `message`，停止。
- `action == "gate"`：若 execution control 为 `WAIT_USER`，先取得用户选择并按 Gate
  Result 契约提交；不得跳过。仅无需用户输入的自动 Gate 才可直接执行下一次 tick。
- `action == "skip"`：直接执行下一次 tick。
- `action == "session_rollover"`：仅表示进程退出、compaction 失败或跨宿主接管等
  异常恢复；正常宿主 compaction 不产生该 Action。旧执行实例停止所有工作 Action；
  通过宿主原生能力
  创建全新会话，只加载 `action.capsule` 指向的 ResumeCapsule，不携带完整聊天历史；
  新会话提交 `{stage:"session_claimed", claim_token, session_id, host}` 后，才可继续
  Core 返回的原 active Action。宿主不能创建/接管新会话时报告
  `HOST_SESSION_HANDOFF_UNAVAILABLE` 并停止，禁止在旧会话降级继续。
- `action == "resource_wait"`：不得把该 Action 当作业务 Result。回收已完成 Worker 的
  原生句柄（宿主提供时），或等待已知运行中 Worker 进入终态；容量变化后重新执行 Core
  保留的原 active Action。该状态不是用户决策点。
- `action.spawn` 存在：检查当前 `HostCapabilities`，并逐项原样消费
  `action.spawn.invocations[]`；`instruction` 与旧 `subagent_prompt` 只作兼容诊断，禁止据此
  重新推导 prompt、effort、隔离方式或 receipt path。原生 spawn 工具输入只能是对应
  `host_execution.workers[i].native_launch_prompt`，不得先读取 Worker Prompt 正文。
- `action.stage == gap_review` 时，只展示 `action.current_gap`：按问题、证据、影响、推荐、
  理由、合法选项的顺序说明，并只询问当前项。用户回答后立即按 `expected_format.decision`
  提交单项 Result；累计决策与游标由 Core 持久化，宿主禁止本地批量缓存、提前询问其他
  gap、代选默认值或改写 `gap_id`。
- 无 `action.spawn`：只允许执行显式声明的控制/配置类 inline Action；Architect、Developer、
  Critic 与各层 Verifier/Audit 均不得由 Coordinator inline 执行业务工作。

Spawn action 必须读取：

- `action.spawn.count`：需要的子代理数量。
- `action.spawn.parallel`：是否要求并行隔离执行。
- `action.spawn.effort`：抽象推理强度，由适配层映射到宿主支持的控制项。

在判断 `action.spawn` 之前先处理 `action.host_execution.recovery`：若状态为
`native_outcomes_ready`，说明当前 Action 的原生 Worker 事实已经落盘，只是 Finalizer 尚未
提交。此时必须禁止重新启动 Worker，直接按 recovery 中的当前 `outcomes_ref`、
`coordinator_result_ref` 和 `result_ref` 调用 Finalizer，再 validate/tick。

默认使用满足任务的最低经济推理强度；只有复杂架构、安全问题、跨模块失败或
action 明确要求时才提高。若 `HostCapabilities.subagents` 不可用，或要求并行但
`HostCapabilities.parallel_subagents` 不可用，必须返回并报告
`HOST_CAPABILITY_UNAVAILABLE`，停止该阶段。不得伪造子代理已经启动、并行执行或
已经生成证据。

### Codex 原生能力绑定

Codex 适配层以当前会话实际暴露的工具清单为能力事实源：

- 先读取 `action.host_execution.native_worker_tools`，按
  `first_complete_exposed_family` 选择当前工具清单中任一完整工具族。当前支持
  `collaboration.spawn_agent / collaboration.wait_agent / collaboration.interrupt_agent`
  与 `multi_agent_v1__spawn_agent / multi_agent_v1__wait_agent /
  multi_agent_v1__close_agent`。任一完整工具族存在时，必须将
  `HostCapabilities.subagents` 视为可用并调用该族；命名空间不同不构成能力缺失，且
  不得因为当前回复尚未调用子代理就判定能力不存在。
- `action.spawn.effort` 映射到所选工具族 spawn 操作的
  `reasoning_effort`；例如 `xhigh` 必须按 `xhigh` 传入，并选择允许该推理参数的
  `fork_turns`，不得因需要高推理强度而降级为 unavailable。
- Codex 创建 Worker 必须使用 invocation 声明的 Prompt，并按所选族使用
  `fork_turns="none"` 或 `fork_context=false`；Worker
  不继承 Coordinator 聊天和 Loop Skill 驱动职责，不得再次调用 `$auto-engineering`、
  `dev-loop` 或 `collaboration.spawn_agent`。
- `action.spawn.parallel=true` 时，只要当前会话允许创建所需数量的独立 Agent，必须按
  `action.spawn.count` 发起原生调用；不能用“本轮尚未创建”为由报告并行能力缺失。
- 当上述工具已经暴露时，工具调用明确失败前，不得报告 `HOST_CAPABILITY_UNAVAILABLE`；
  调用失败后必须保留原始错误证据，不能用主 Agent inline 模拟。
- 原生调用返回 Agent 线程/并发容量耗尽时，先等待已知 Worker 完成并通过宿主原生能力
  回收其句柄，再重试一次。仍失败时提交 `spawned=false`、
  `spawn_error_code=HOST_AGENT_CAPACITY` 和原始 `spawn_error`；不得伪造 Worker。
- 每个 Worker 完成且 outcome 已记录后立即回收其原生句柄；不得把已完成句柄保留到下一 Action。
  并行调用先收齐本 Action 的原生事实，再逐个调用宿主的 close/reclaim 能力，最后 finalize。
- 并行 Worker 启动后使用宿主一次批量/长等待覆盖全部未完成句柄；禁止 30 秒轮询。
  等待仅允许在 5 / 10 / 15 分钟心跳边界重新评估，宿主原生 wait 能在 Worker 完成时提前返回。
  等待期间不得重复读取 diff、状态文件或项目树；完成通知到达后再收集 outcome。
  Codex 必须显式调用 `collaboration.wait_agent({"timeout_ms":300000})`，或
  `multi_agent_v1__wait_agent({"targets":["<agent-id>"],"timeout_ms":300000})`，不得省略
  timeout 使用宿主默认 30 秒；未完成时最多再调用两次相同的 300000ms 等待。
- 三次长等待后 Worker 仍未完成时，仍然只是观察事件：不得写失败 outcome、不得调用
  `--finalize-result`、不得重启 Worker。主 Agent 查询原生 handle 状态并尝试正常取消；只有
  原生宿主明确返回终态失败、确认取消成功或 owner 进程已结束，才写入 `failed`/`timed_out`
  事实并进入 Core 失败重试。若无法确认旧 Worker 已终止，保留 active Action，报告
  `WAIT_RESOURCE/WORKER_OWNERSHIP_UNCERTAIN` 并继续等待，禁止并发重跑和双写。只有宿主
  原生 API 明确给出 `timed_out`，才允许使用 `HOST_WORKER_TIMEOUT`，普通 wait 返回不构成该证据。
- `execution_control.disposition == "CONTINUE"` 时，能力满足的 spawn Action 必须在同一
  次用户启动中继续驱动，不得先向用户输出终态消息或请求无关确认。

能力满足时，使用宿主原生子代理能力：

Core 返回 Action 后，立即把 `action.project_root` 视为本次 Loop 唯一的项目根目录事实源。
后续不读取或推断 shell 当前目录；每条 `ae-run dev-loop` 内部命令（包括 finalize、
validate、tick、status、resume）都必须显式附加
`--project-root <action.project_root>`。即使宿主工具调用改变了 `cwd`，也不得省略或改写该值。
所有项目读取、编辑、测试、lint、type check 与 build 工具也必须以 `action.project_root`
作为工作目录；禁止在插件 Release、prompt artifact 或任意上一次工具目录执行项目命令。

1. 当前严格合同：无论单/多 Worker，都逐个读取并校验
   `action.spawn.invocations[i].prompt_ref` 与 `prompt_sha256`，并原样使用该 invocation
   的 effort、isolation、capabilities 和 `action.spawn.invocations[i].receipt_path`。
   宿主适配器已在
   `action.host_execution.workers[i]` 物化同一 invocation 的证明模板；严格合同下必须
   使用该模板，不得根据原生 Agent 返回值重新推导协议字段。
2. 仅当 active Action 的 Runtime Vector 明确是旧合同且没有 `contract_version` 时，才按
   旧 `subagent_prompt` / `spawn.agents[]` 只读兼容；当前 Action 禁止混用旧字段推导执行。
3. 按 `action.spawn.count` 和 `action.spawn.parallel` 创建隔离执行。
4. 每个 Action 只使用 `action.host_execution.work_files` 给出的三个绝对绑定工作文件
   （相对 `action.project_root`）：`outcomes`、`coordinator_result`、`result`。这些路径由
   `message_id` 的安全摘要隔离；不得改回根目录固定文件，也不得复用上一 Action 的文件。
5. Worker 完成后，Coordinator 只把原生事实写入当前 Action 的 `work_files.outcomes`：
   `worker_id`、`native_worker_handle`、`status`、`payload`、`summary`、
   `actual_model` 和所选工具族的 `isolation_evidence`（`fork_turns=none` 或
   `fork_context=false`）。`actual_model` 使用原生 API 报告值；若 API 不暴露模型标识，
   必须写稳定值 `unreported`，不得填 `null` 或猜测模型名。Worker 不得写 receipt、attestation、challenge 或 total proof
   （workers must not write the shared total proof）。同时必须原样复制启动契约中的
   `execution_generation` 与 `fencing_token`；任一缺失或不匹配时不得猜测、不得提交 outcome。
6. 全部 Worker completed 时，Coordinator 从真实输出合并 `action.expected_format` 要求的业务字段，
   只写入当前 Action 的 `work_files.coordinator_result`；设计冲突写 `design_change_requests[]`，
   不伪造可执行计划。任一 Worker 超时/失败时写 `{}`，不得补业务字段或假装成功。
   `action.result_contract` 是机器类型事实源：数组和对象必须写为原生 JSON，禁止再次
   序列化成字符串。Backend/Finalizer 只对合法 JSON 字符串执行一次确定性恢复；
   解码后仍不匹配时以 `HOST_ACTION_OUTPUT_INVALID` fail-closed，不得手工绕过。
7. 原样执行 `action.host_execution.operations.finalize.argv`：只把首项
   `__AE_BUNDLED_RUNNER__` 替换为启动时固定的 bundled runner，禁止重建、重排或手抄其余参数。
   该内部命令原子生成 Worker receipt、attestation、total proof 和完整 Result，
   并一次性返回全部证据问题。宿主禁止手工重建这些字段。
8. 随后依次原样执行 `operations.validate.argv` 与 `operations.submit.argv`；
   禁止复制 stdout 或继续把 coordinator payload 当成完整 Result。已提交 outcome journal
   必须通过 `host_execution.recovery` 幂等复用，不得重新 spawn。
9. `--tick` 返回下一 Action 后，立即丢弃上一 Action 的对象、工作路径、Worker handle 与
   命令参数，只以新 Action 重新开始本节算法。错误恢复只保留结构化错误码和当前 Action
   摘要；禁止重复输出全量 diff、旧 `outcomes`、旧 `coordinator_result` 或历史 Action JSON。
   若误用了旧路径，Finalizer 会以 active Action 的已存在工作文件自动重绑；宿主随后仍须
   替换本地变量，不能把自动重绑当作跨 Tick 缓存机制。

非 spawn Action（包括 gap_scan、project_setup 与用户决定回执）同样禁止
手工拼装 Result Envelope。宿主只按 `action.expected_format` 写
`work_files.coordinator_result`，再原样执行同一 Action 的
`operations.finalize.argv`、`operations.validate.argv` 与 `operations.submit.argv`；
Core 从 active Action 绑定
message identity、causation、thread、tick、stage 与 correlation。之后使用相同的
`--validate-result`、`--tick --result` 流程。

协调入口返回 WAIT/ERROR/HANDOFF/TERMINAL 时会在 `.ae-state/reports/` 生成确定性
`loop-stop-*.md`，只记录 Action、Receipt、原因码与下一步。不得用自由文本 recap 覆盖该报告。

Core 返回 `resource_wait` / `WAIT_RESOURCE` 时，宿主继续执行上述资源回收流程，并在
容量可用后重新执行原 active Action；不得提交 `resource_wait` 为 Result，也不得推进 Tick。

Gap Review 默认仍是用户决策。用户可通过结构化字段
`apply_to_remaining=recommendations` 授权当前线程后续 Gap 采用 Core 推荐；宿主不得从
`user_note` 自然语言推断授权。授权生效后，Core 会在 Gap Action 返回 `auto_decision`，
宿主必须原样写入该决定，仅按 expected_format 补充 `fill_content` 等说明性字段并继续，
不再次询问，也不得自行构造或扩展授权范围。Finalizer 必须从 active Action 重新绑定
`gap_id`、`resolution`、`decision_source` 和 `policy`，不能信任宿主二次抄写这些机器字段。

## 角色边界

| 角色 | 执行方式 | 职责 |
|---|---|---|
| architect | 隔离子代理 | 设计与 batch plan |
| developer | 1 个 fresh Worker | 按 active batch 执行 TDD 实现与本地验证 |
| critic | 隔离子代理 | diff 审查与门禁结论 |
| component_verifier | 隔离子代理 | 组件设计覆盖验证 |
| plate_deep_audit | 多个隔离子代理 | 板块多维审计 |
| system_verifier | 隔离子代理 | 系统设计覆盖验证 |
| system_deep_audit | 多个隔离子代理 | 全系统多维审计 |

## References

- `commands/dev-loop.md` — 完整 Tick 驱动手册
- `design/v5.6-Design-Loop.md` — 架构与阶段规格
- `design/BEACON.md` — 当前设计决策与状态
