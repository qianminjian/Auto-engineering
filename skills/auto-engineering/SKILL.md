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
宿主启动时还必须把真实 cwd 固定为 `AE_INVOCATION_PROJECT_ROOT`；后续 runner
拒绝显式 `--project-root` 或 cwd 偏离该值的请求，并报告 `AE_PROJECT_ROOT_DRIFT`。
本文后续每个 `ae-run` 都是
`env AE_HOST_PLATFORM=codex AE_HOST_ACTION_VIEW=compact <plugin-root>/bin/ae-run` 的缩写；实际工具调用必须保留该环境
前缀和绝对路径，不得把文中缩写当成实际命令；不得把包含 `env ...` 的整段字符串保存到变量后再用 `$VAR` 执行，
必须直接写成 `env AE_HOST_PLATFORM=codex AE_HOST_ACTION_VIEW=compact "<plugin-root>/bin/ae-run" ...`；不得调用裸 `ae-run` 或另一宿主传入的 runner，不得依赖 PATH，
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
| 预检当前制品身份 | `ae-run build-info --expect-build-id <candidate-build-id>` |
| 预校验 Result | `ae-run dev-loop --validate-result <file>` |
| 推进一个 Tick | `ae-run dev-loop --tick --result <file>` |
| 查看循环状态 | `ae-run dev-loop --status --format json` |
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

设计文档是本次 Loop 的 binding source，默认只读。任何 Architect、Worker 或 Coordinator
都不得编辑原设计、注入 `ae:component` 等元数据或为补齐结构改写章节；确需改变设计时，
只能提交 `design_change_requests[]`，由 Core 发出用户 Gate，用户批准后再由明确的变更
Action 写入。

## Action 执行协议

产品入口必须设置 `AE_HOST_ACTION_VIEW=compact`。CLI stdout 返回的 compact envelope 是
当前执行控制视图；完整 Canonical Action 仍由 Core 持久化。若存在
`coordinator_prompt_ref`，只读取其 `path` 一次并核验 `sha256`，不得扫描 Action Store，
不得要求 CLI 重新内联 `instruction` 或 `context`。spawn Action 只把
`spawn.invocations[i].prompt_ref` 交给对应 fresh Worker；Coordinator 不读取 Worker
prompt 正文，也不接受 `subagent_prompt` 旧字段。

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

若本次宿主验收已经取得候选 Release `build_id`，首个 `dev-loop --init` 前必须先执行
`ae-run build-info --expect-build-id <candidate-build-id>`。命令失败时报告实际加载的
Build Identity 并停止；不得启动 Loop、切换到旧缓存入口或手工修复后继续。日常开发若没有
候选 Release，可执行不带 `--expect-build-id` 的 `ae-run build-info` 记录当前源码/制品身份，
但它不能替代真实发布验收的候选身份比较。

首个 `--init` 必须显式使用 `--project-root <invocation_project_root>`；相对设计文档只在
该根内解析。设计文档不存在、越界或 init 失败时立即报告并停止：禁止搜索父目录、`/tmp`、
其他项目或同名文件，禁止改写 `--project-root` 后重试，也禁止通过绝对路径切换项目。
取得首个 Action 后必须校验其 `project_root` 与 `invocation_project_root` 的真实路径完全相同；
不一致时报告 `HOST_PROJECT_ROOT_DRIFT` 并停止，禁止在新根初始化或继续。

若首个 Action 的 disposition 为 `CONTINUE`，当前主 Agent 就是唯一 Coordinator，必须在本次
会话内持续执行下面的 Action 合同。Python 不接管原生 Worker，也不替主 Agent 启动另一个
临时主会话；Python Core 不启动宿主会话。

每次先读取 `action.extensions.ae.execution_control`。宿主必须在同一次用户启动中执行：

```text
while control.disposition == "CONTINUE":
  execute current Action
  validate and submit Result
  read next Action and its execution_control
```

宿主调用返回后（包括原生 CLI 进程退出或 stdout 为空），不能把“进程返回”或模型给出成功文本当作
Loop 成功。必须先消费当前 Action 的 `host_execution.continuation` 合同，其中
`after_host_return` 必须为 `recheck_core_status`，再执行一次
`ae-run dev-loop --status --format json` 回查 Core；若回查得到
`execution_control.disposition == "CONTINUE"` 或 active Action 仍存在，必须立即按
`next_operation=resume_active_action` 恢复同一 active Action，继续执行其绑定的
`finalize → validate → submit` 或 Worker 操作，不得报告成功、请求无关确认或
创建第二个 Coordinator。只有 `WAIT_USER`、`WAIT_RESOURCE`、`TERMINAL`、`ERROR` 或
`HANDOFF_REQUIRED` 才允许按各自合同让出当前宿主控制权；任何空结果、非零退出或
非终态返回都必须保留现有状态并进入恢复/错误处理，不能吞掉为成功。

Action 身份必须以 `thread_id + message_id` 判断；`stage`、`tick` 或自然语言摘要不是身份。
尤其是 `developer B1 → developer B2` 这类同一 stage 的下一 Action，若 `message_id` 已变化，
就是新的 Action：丢弃上一 Action 的对象、路径和 Worker 句柄，立即执行新 Action 的
`spawn/wait/record` 合同。`causation_id` 只表示触发当前 Action 的上一条 Result，不得用它
代替 `message_id` 判断当前 Action 是否相同。

宿主写入 `host_execution.work_files` 前不需要猜测路径或切换 cwd；Host Runtime 会在项目
根内预创建当前 Action 的受控父目录。宿主必须使用 Action 给出的完整相对路径，禁止自行
拼接旧路径、固定文件名或项目外路径。

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
  `required_operation == "repair_coordinator_then_finalize"`。先对 `result_ref`
  原样执行 `operations.validate.argv`：通过则执行 `operations.submit.argv`；业务预检失败则
  仅按 active Action `expected_format` 修复 `coordinator_result_ref`，使用
  Core 恢复的 `outcomes_ref` 并原样执行 `operations.finalize.argv`，再验证和提交。
  这是同一个 active Action 的唯一修复操作名；禁止创建、等待或回收新 Worker，禁止改写
  outcomes；恢复合同不完整则 fail-closed。
- `action == "error"`：报告 `error_code` 和 `message`，停止。
- `action == "project_setup_required"`：这是一个可继续的项目搭建 Action，不是错误也不是
  Python 脚手架入口。只在 `action.project_root` 下读取当前设计与 `missing_capabilities`，
  仅补齐这些明确缺失的工程能力；不得猜测未写入设计的框架、不得修改插件目录、不得调用
  Worker 或启动第二个 Loop。搭建完成后只写当前 Action 的
  `host_execution.work_files.coordinator_result`，按该 Action 的
  `operations.finalize.argv`、`operations.validate.argv`、`operations.submit.argv` 原样执行，
  成功 Result 必须为 `stage=project_setup`、`result_type=project_setup_completed` 和实际
  `artifacts`；若命令或门禁在最多一次就地修复后仍失败，必须提交
  `result_type=project_setup_failed`、`failure_code`、有界 `failure_summary` 和
  `attempts_in_action`（1 或 2），把失败交回 Core，禁止继续在当前 Action 内循环。若缺失项包含 `setup_gate:*`，必须先在项目根建立并同步项目自己的工具环境
  （Python 通常是 `.venv`，Node 使用项目 package manager），将实际需要的测试/lint/type/build
  工具声明到项目配置，再在同一项目环境执行门禁。Python 项目的最小动作是：若不存在
  `.venv/bin/python`，执行 `env -u UV_PROJECT_ENVIRONMENT -u VIRTUAL_ENV uv venv .venv`；在
  `pyproject.toml` 的 PEP 735 `[dependency-groups]` 下声明 `dev = ["pytest", "ruff", "mypy"]`，
  并用 `[tool.pytest.ini_options]` 声明项目测试根；不得用 `[project.optional-dependencies]`
  冒充 dev group；执行
  `env -u UV_PROJECT_ENVIRONMENT -u VIRTUAL_ENV uv sync --dev --project .`；随后用
  `.venv/bin/python`、`.venv/bin/ruff`、`.venv/bin/mypy` 实际运行对应门禁。不得把插件的
  `.ae-state/.ae-runtime` 当作项目环境；调用 `uv` 前不得继承插件的运行时变量。
  Setup Gate 失败时只修正项目声明或工具环境后重跑；不得执行 `rm -rf .venv`、删除项目状态或
  重新初始化项目来掩盖失败。项目打包只纳入源码和必要元数据，必须排除 `.ae-state`、`_scratch`、
  `.venv`、`dist`、`build` 等运行态/构建产物，避免绝对路径 symlink 进入 sdist；同一 Action 内
  同一失败命令最多就地修复后重跑一次，仍失败就提交当前 Result，让 Core 生成下一 Action 或
  `resource_wait`，不得在宿主内部无限循环。
  只有门禁在项目环境中真实通过后才能提交完成；若门禁失败，继续处理 Core 返回的新 setup
  Action，禁止自行循环或手工宣布成功。
- `action == "gate"`：若 execution control 为 `WAIT_USER`，先取得用户选择，按
  `action.expected_format/result_contract` 将唯一嵌套对象
  `{gate_resolution:{gate_id:<当前 Gate>,resolution:<选择>}}` 写入当前
  `host_execution.work_files.coordinator_result`，再原样执行绑定的
  `operations.finalize.argv`、`validate.argv`、`submit.argv`；不得无 Result 调
  `--tick`，不得跳过，也不得另起 Gate 循环。仅无需用户输入的自动 Gate 才可直接执行下一次 tick。
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
  `action.spawn.invocations[]`；`instruction` 只作有界操作诊断，禁止据此
  重新推导 prompt、effort、隔离方式或 receipt path。原生 spawn 工具输入只能是对应
  `host_execution.workers[i].native_launch_prompt`，不得先读取 Worker Prompt 正文。
- `action.stage == gap_review` 时，先执行 `action.gap_review_contract` 协议闸门；只展示
  `action.current_gap`，按问题、证据、影响、推荐、理由、合法选项的顺序说明。历史对话、
  `gap_scan.gaps`、`total_gaps` 和未来缺口详情都不是展示输入，禁止复述、枚举、摘要或批量询问。
  用户回答后立即按 `expected_format.decision` 提交且仅提交一个 Result；累计决策与游标由
  Core 持久化，宿主禁止本地批量缓存、提前询问其他 gap、代选默认值或改写 `gap_id`。
- 无 `action.spawn`：只允许执行显式声明的控制/配置类 inline Action；Architect、Developer、
  Critic 与各层 Verifier/Audit 均不得由 Coordinator inline 执行业务工作。

`project_setup_required` 是上面唯一明确允许宿主直接完成项目搭建的非 spawn 业务 Action；
它的 `constraints.setup_scope.mode` 必须为 `capability_only`：只允许项目元数据、工具链、
源码/测试根和最小非业务 smoke/contract test，不得实现用户业务功能、不得创建业务测试、
不得编写用户文档；业务实现只能从 Architect/Developer Action 开始。Smoke 只能证明工具链
和空包可执行，不得导入、创建或引用设计中的业务模块、类、函数或行为；不得为了让 smoke
通过而创建业务模块桩代码，若 smoke 需要业务模块则应删除或改为非业务 smoke。该边界由 Core 基于 init
文件基线和当前工作区事实复核，不能用 `artifacts` 或文字声明替代；发现新增业务源码/测试时
  Python 项目可固定使用声明测试根中的最小 `test_smoke.py`；Node 项目可使用
  `test_smoke.js/.jsx/.ts/.tsx`。这些文件仅执行工具链自检，不得导入设计模块或写业务断言。
项目测试命令必须一次性、非交互并在完成后退出；Vitest 使用 `vitest run`，不得使用默认
`vitest` 或 `--watch`，Cypress 不得使用 `cypress open`，Playwright 不得使用 UI 模式。
停止推进并等待 Core 返回范围违规反馈。它不改变“Python
只验证、主 Agent 才执行”的边界，也不等价于允许 Coordinator inline 完成 Architect、Developer
等业务阶段。

Spawn action 必须读取：

- `action.spawn.count`：需要的子代理数量。
- `action.spawn.parallel`：是否要求并行隔离执行。
- `action.spawn.effort`：抽象推理强度，由适配层映射到宿主支持的控制项。

在判断 `action.spawn` 之前先处理 `action.host_execution.recovery`：若状态为
`native_outcomes_ready`，说明当前 Action 的原生 Worker 事实已经落盘，只是 Finalizer 尚未
提交。此时必须禁止重新启动 Worker；若 `coordinator_result_ready=true`，直接按 recovery
中的当前 `outcomes_ref`、`coordinator_result_ref` 和 `result_ref` 调用 Finalizer，再
validate/tick；若为 false，只根据已固化 `outcomes_ref` 生成 Coordinator payload，写入
`coordinator_result_ref` 后再 finalize、validate/tick。

若状态为 `worker_attestation_pending`，说明 Worker 私有业务 outcome 已落盘，但宿主尚未
把原生 handle、实际模型或隔离事实交给 Assembler。这不是 Worker 失败，不得提交
`spawned=false`、推进失败预算或重新 spawn；必须保留当前 Action，使用仍有效的原生返回值
按 `workers[].record_worker_outcome` 固定模板完成回写，再写 Coordinator payload 并执行
finalize/validate/submit。若原生 handle 已丢失，必须停止并报告
`HOST_WORKER_ATTESTATION_MISSING`，不得用 `unreported:*` 伪造 completed。Claude Code 的
Agent/Task 原生返回必须从结构化 `task_started.task_id` 或 `agentId` 取得句柄；这是唯一的
native worker handle 来源。缺少句柄时必须停止，不得启动回显 Agent、不得伪造 completed Worker，
也不得把自然语言、worker_id 或摘要当作句柄。若原生 spawn 返回空句柄、空目标列表或
无法确认的句柄，立即调用当前 bundled runner 的
`ae-run --run-module auto_engineering.host.process_exit --project-root <root>
--host-output <不存在或当前宿主输出文件> --exit-code 75
--reason-code HOST_WORKER_ATTESTATION_MISSING` 记录一次 Stop Report，然后结束当前宿主会话；
不得进入 wait、重启 Worker 或提交伪造 Result。

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
  调用失败后必须保留原始错误证据，不能用主 Agent inline 模拟。尤其是 Claude 的
  `Agent` 被 PreToolUse 拒绝时，必须按当前 Action 的 `HOST_EVIDENCE_INVALID`/
  `WAIT_RESOURCE` 出口保留 Action；不得把 Developer、Critic、Architect 或 Verifier
  工作改在 Coordinator 会话内执行。若是合同复制错误，只能重新读取当前 Action 的
  `native_launch_prompt` 原文后重试，不得手改 hash、路径、Worker ID 或 JSON。
- 若 spawn 工具返回结果中没有结构化 Worker 句柄，按上面的
  `HOST_WORKER_ATTESTATION_MISSING` Stop Report 出口结束；空句柄不是可等待的 Worker。
- 原生调用返回 Agent 线程/并发容量耗尽时，先等待已知 Worker 完成并通过宿主原生能力
  回收其句柄，再重试一次。仍失败时提交 `spawned=false`、
  `spawn_error_code=HOST_AGENT_CAPACITY` 和原始 `spawn_error`；不得伪造 Worker。
 每个 Worker 完成且 outcome 已记录后立即回收其原生句柄；不得把已完成句柄保留到下一 Action。
  严格按 `action.host_execution.worker_lifecycle.required_order` 执行：
  `spawn → wait → record_worker_outcome → reclaim → finalize`；Codex 必须对每个已完成
  handle 调用当前工具表中的 `close_agent`（或等价的
  `multi_agent_v1__close_agent`/`collaboration.interrupt_agent`），并确认 close/reclaim
  成功后才能执行 finalize。没有可用 reclaim 工具或 reclaim 返回失败时，不得 finalize、
  不得进入下一 Action，必须保留当前 Action 并报告宿主容量/生命周期错误。
  并行调用先收齐本 Action 的原生事实，再逐个回收句柄，最后 finalize。
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

等待策略的唯一机器事实源是 `action.host_execution.worker_observation`，不得从本段文字或
`instruction` 重新推导预算。Codex/Claude 分别消费 `mode`；每次 wait、owner 查询或原生
返回后，宿主必须按当前 Worker 的 `observation_path` 调用
`dev-loop --record-worker-observation --worker-id <id> --observation-status <status>
--observation-wait-attempt <n> --owner-known|--owner-unknown`。该命令只原子写入 Host
Runtime 诊断文件，不推进 Tick、不生成 Result、不授予重启权限。`unknown` 且 owner 不可
确认时，宿主必须保留原 Action 并按合同报告
`WAIT_RESOURCE/WORKER_OWNERSHIP_UNCERTAIN`；普通 wait 到期不能写成失败。

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
2. 当前运行路径不兼容旧 `subagent_prompt` / `spawn.agents[]` 执行语义；缺少严格
   `contract_version` 与 `spawn.invocations[]` 时必须 fail-closed。历史 Action 只能由显式
   replay/import 迁移入口处理，不得从普通 Worker 编译器自动降级。
3. 按 `action.spawn.count` 和 `action.spawn.parallel` 创建隔离执行。
4. 每个 Action 只使用 `action.host_execution.work_files` 给出的三个绝对绑定工作文件
   （相对 `action.project_root`）：`outcomes`、`coordinator_result`、`result`。这些路径由
   `message_id` 的安全摘要隔离；不得改回根目录固定文件，也不得复用上一 Action 的文件。
   不得复用旧 Action 的 work_files、句柄或命令参数。
5. Worker 完成后优先把业务产物原子写入自己的 `invocation.outcome_path`，字段严格为
   `worker_id`、`status`、`payload`、`summary`；完成的业务产物必须写 `status: "completed"`，
   失败/取消/超时分别写对应状态；`complete`/`success`/`ok` 仅作为 Host 交接边界可归一化的完成别名，
   不得用于伪造宿主事实；不得写 `native_worker_handle`、
   `actual_model`、`isolation_evidence`、receipt、attestation、challenge、total proof
   或任何 Core 身份（workers must not write the shared total proof）。Host Driver 必须从原生 API 取得句柄、实际模型（不暴露时为
   `unreported`）、调用状态和隔离证据，再由 Collector 合并成当前 Action 的
  `work_files.outcomes`。共享 outcomes 必须是 `{"outcomes":[...]}`；不得让 Worker 猜测、
  复制 `spawn.invocations[].isolation` 或伪造宿主事实。Host Driver 同时必须原样复制启动
  契约中的 `execution_generation` 与 `fencing_token`；任一缺失或不匹配时不得提交 outcome。
   宿主 Hook 以运行时提供的顶层 `agent_id` 区分 fresh Worker 与 Coordinator；Coordinator
   直接写入 `worker-outcomes` 必须被拒绝，Worker 只能写当前 Action 绑定的私有路径。
   主 Agent 不得手写共享 outcomes；每个 Worker 返回后必须按
   `action.host_execution.workers[i].record_worker_outcome.argv_template` 和
   `runtime_arguments` 原样调用 `--record-worker-outcome`。只允许填入原生 API
   返回的 status、handle、model、isolation；Claude Code 使用 Agent/Task 返回的精确
   `task_started.task_id`/`agentId` 作为 `native_worker_handle`，未暴露模型时使用 `unreported`；不得改 Worker ID、project-root、参数顺序
   或自行创建另一条回写命令，再执行 `operations.finalize/validate/submit`。
  Claude Code 的 `Agent`（兼容别名 `Task`）调用是原生完成观察，不是 Coordinator 的
  Worker 业务结果。异步宿主可能先返回 `async_launched`；下一次原生调用必须是同一
  `agentId/task_id` 的 `TaskOutput`，直到 completed，期间禁止 Stop、TaskStop、Read/Bash
  探查、重启 Agent 或手工补录。PostToolUse 必须用已固化的 `agentId/task_id` 绑定同一 Worker，
  运行中的观察不得覆盖句柄元数据。
  必须把 `native_launch_prompt` 原样交给
   `Agent`，从原生工具返回的结构化字段 `task_started.task_id`/`agentId` 取得句柄、状态和模型（模型缺失才
   用 `unreported`）。随后只读取对应 `invocation.outcome_path`；若缺失，Host Driver
   只能把原生返回 envelope 原样写入当前 invocation 的 `native_result_path`，或通过固定模板的
   `--native-result-file` 路径，并可用 `--native-result-stdin` 原样输入后由边界原子暂存，再调用同一个
   `host_execution.workers[i].record_worker_outcome` 固定模板，由 Host 边界严格提取并原子
  固化私有业务 outcome。PostToolUse 已写入 `native_result_path` 时，直接按固定回写模板消费该文件，
  不得读取、解析、摘要或重建 native envelope；不得使用 Bash heredoc；如果宿主无法
  逐字节转交原生返回，必须报告 `HOST_EVIDENCE_INVALID` 并保留当前 Action。自然语言不得作为 payload；若原生返回没有可验证句柄，不得以
  `unreported:*` 冒充 completed。解析失败保留当前 Action，不得重新初始化或要求用户切换模式。
  Worker `payload` 只能包含当前 stage 合同声明的业务字段；`expected_fields`、`stage`、宿主身份或
  任何提示词元字段都不得复制进业务 payload。
  Codex PostToolUse Hook 会把 spawn 原始返回固化到当前 invocation 的
  `native_result_path`，并把 wait 返回中当前 invocation 对应 target 的完成正文自动桥接到同一路径；
  如果 Hook 未拿到原始字符串，必须保留当前 Action 并报告证据缺失。Codex 的 `wait_agent` 返回中，只有当前 invocation 对应 target 的完成正文才是 native
  envelope：按当前工具族返回形状取 `agents_states[agent_id].message`，或取
  `status[agent_id].completed`；必须将该字符串原样（不摘要、不重排、不重新 JSON 序列化）通过
  `--native-result-stdin` 或 `--native-result-file` 交给同一个 record-worker-outcome 边界。
  外层 `status`/`agents_states` 映射、空 wait、其他 target、Coordinator 自己的自然语言和
  Worker 私有 outcome 都不是 native envelope，禁止把等待包装整体回写。
  Codex 原生结构化回包允许精确单层 `{"result": <business-object>}` 包装；Host 只解这一层，
   不递归解包，也不采纳返回内容中的 handle/model/isolation 等宿主事实。
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
   若 finalize 非零退出、未生成 `result.json` 或返回解析错误，立即保留当前 Action 并进入
   repair/Stop Report；不得继续执行 validate、submit、tick，不得把命令失败误报为 Core `ERROR`
   或启动新的 Worker。
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

若 Guardrail 返回 PII 重试，先修复真实文件中的凭据或个人数据；测试脱敏用例必须使用明显的
fake 占位符或运行时拼接值，不能把形似真实凭据的字面量写入源码。修复时保持测试断言和失败
事实不变，不得通过修改断言、伪造测试统计或删除用例来消除门禁。

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
