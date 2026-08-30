---
name: dev-loop
description: Auto-Engineering v5.8 宿主无关确定性会话 Tick-Based 开发循环
---

# Auto-Engineering dev-loop — 组长执行手册

你是 Loop 组长。Python 引擎负责确定性路由、门禁和收敛；你负责执行 action，
并在需要隔离角色时调用当前宿主原生子代理能力。

> Authority: BEACON #39、#64、#91、#101
> Spec: `design/v5.6-Design-Loop.md`

## 铁律

<!-- FRAGMENT:iron_law_gatekeeper START -->
IRON LAW: PYTHON IS THE GATEKEEPER.
NO STAGE ADVANCEMENT WITHOUT `ae-run dev-loop --tick` VALIDATION.
You may NOT edit code before Python outputs {"action":"developer"}.
You may NOT declare done before Python outputs {"action":"done"}.
Violating the letter of this rule is violating the spirit of this rule.
<!-- FRAGMENT:iron_law_gatekeeper END -->

不得跳过或伪造 Gate、子代理执行及验证证据。Git commit、push、PR 只有获得用户
明确授权后才能执行。

启动时必须固定 bundled runner。本文后续每个 `ae-run` 都是以下完整调用的缩写：
`env AE_HOST_PLATFORM=claude-code AE_HOST_ACTION_VIEW=compact "${CLAUDE_PLUGIN_ROOT}/bin/ae-run"`。实际 Bash 调用必须保留
该环境前缀和绝对路径，不得只执行文中的缩写；不得调用裸 `ae-run` 或另一宿主传入的 runner；不得
依赖 PATH，也不得搜索开发目录或缓存目录猜测入口。runner 不存在或不可执行时以
`HOST_RUNNER_UNAVAILABLE` fail-closed。

## 驱动循环

产品入口必须设置 `AE_HOST_ACTION_VIEW=compact`。CLI stdout 返回的 compact envelope 是
当前执行控制视图；完整 Canonical Action 仍由 Core 持久化。若存在
`coordinator_prompt_ref`，只读取其 `path` 一次并核验 `sha256`，不得扫描 Action Store，
不得要求 CLI 重新内联 `instruction`、`context` 或 `subagent_prompt`。spawn Action 只把
`spawn.invocations[i].prompt_ref` 交给对应 fresh Worker；Coordinator 不再读取兼容字段
`subagent_prompt` 正文。

对每个 spawn invocation，把对应
`action.host_execution.workers[i].native_launch_prompt` 原样作为原生 Worker 工具输入。
Coordinator 不得先读取、`sed`、复制、总结或重新拼接 `prompt_ref` 正文；主会话只允许
校验文件 SHA-256。由 fresh Worker 切换到机器指定 `project_root`，读取并验证 Artifact。

```text
1. invocation_project_root = 宿主启动 cwd 的真实绝对路径（本次启动不可变）
   project_root = invocation_project_root
   action = ae-run dev-loop --init "<requirement>" [--design-doc <path>]
       --project-root invocation_project_root
   # --init 自动恢复 active thread；禁止先调 status 或扫描 .ae-state 推测 Action。
   # 设计文档不存在、越界或 init 失败时立即停止；禁止搜索父目录、/tmp、其他项目或同名文件，
   # 禁止改写 `--project-root` 后重试，也禁止用绝对设计路径切换项目。
   # 若仅查询 status，必须原样执行 status.next_operation.argv。
   assert realpath(action.project_root) == invocation_project_root
   # 不相等时报告 HOST_PROJECT_ROOT_DRIFT 并停止，禁止在新根初始化或继续。
   project_root = action.project_root
   # 此后 project_root 是不可变机器事实；每条 `ae-run dev-loop` 内部命令都显式传入，
   # 禁止依赖宿主 shell 的当前目录。
   # 所有项目编辑、测试、lint、type check、build 和 Worker 启动同样固定 cwd=project_root；
   # 禁止在插件 Release 或 prompt artifact 目录执行项目命令。
2. if action.extensions.ae.execution_control.disposition == "CONTINUE":
     # 当前主 Agent 是唯一 Coordinator；在本次宿主会话内持续执行下方合同。
     # Python Supervisor 仅作迁移期旁路，默认入口不得调用 --supervise。
3. 主 Agent 在同一会话内持续执行：
   while action.extensions.ae.execution_control.disposition == "CONTINUE":
     print "[Tick N | stage <action.stage>] ..."
     control = action.extensions.ae.execution_control
     if control.disposition == "ERROR":
         report action.error_code + action.message
         STOP
     if action.action == "gate" and control.disposition == "WAIT_USER":
         ask only the options returned by Core, submit the selected gate result
         continue
     if action.host_execution.recovery.status == "worker_outcomes_committed":
         assert action.host_execution.recovery.spawn_permitted == false
         assert action.host_execution.recovery.required_operation == "validate_then_submit_or_repair"
         result = action.host_execution.recovery.result_ref
         validation = ae-run dev-loop --validate-result result --project-root project_root
         if validation fails business prevalidation:
             repair only coordinator_result_ref against action.expected_format
             finalize outcomes_ref + coordinator_result_ref back to result_ref
             validate result_ref again
         run ae-run dev-loop --tick --result result --project-root project_root
         never spawn, wait, reclaim, or rewrite outcomes in this branch
         continue
     if action.stage == "gap_review" and action.auto_decision exists:
         write action.auto_decision verbatim as result.decision and only add required
         explanatory fields such as fill_content; Finalizer rebinds all Core-owned fields
         from the active Action before submission
         continue
     if action.action in {"gate", "skip"}:
         action = ae-run dev-loop --tick --project-root project_root
         continue
     if control.disposition == "HANDOFF_REQUIRED":
         stop all work in the old session
         create a fresh host session and load only action.capsule
         submit {stage:"session_claimed", claim_token, session_id, host}
         if native session handoff is unavailable: fail closed
         continue with the original active Action returned by Core
     if control.disposition == "WAIT_RESOURCE":
         reclaim every completed native worker handle immediately after its outcome is recorded;
         never retain completed handles into the next Action
         wait for known running workers to reach terminal state
         重试一次，然后继续执行 Core 返回的原 active Action
     read and verify action.coordinator_prompt_ref.path once
     if action.stage == "gap_review":
         present only action.current_gap: problem, evidence, impact, recommendation, rationale, options
         ask one user decision and submit exactly one result.decision for this Tick
         never cache later decisions locally, prefill defaults, or change current_gap.id
        用户可在当前决定中显式设置 apply_to_remaining=recommendations；只有 Core 随后返回
        auto_decision 时才可自动提交，禁止从 user_note 自然语言推断长期授权；宿主只补充
        fill_content 等说明字段，Finalizer 从 active Action 重绑全部 Core-owned 机器字段
    if action.host_execution.recovery.status == native_outcomes_ready:
         禁止重新启动 Worker；使用 recovery 的当前 outcomes_ref、coordinator_result_ref
             和 result_ref 直接 finalize，再 validate/tick
    elif action.spawn exists:
         validate HostCapabilities against action.spawn
         consume action.spawn.invocations[] exactly; instruction is diagnostic only
         consume action.host_execution.workers[] as the evidence-template SSOT
         pass workers[i].native_launch_prompt verbatim to the native spawn tool;
             不得先读取 prompt_ref 正文，也不得把正文复制进 tool call
         keep native agent/thread IDs only as native_worker_handle; never replace worker_id
         原生 Agent 容量耗尽时，回收/等待后重试一次
         if still exhausted, submit spawned=false with
         spawn_error_code=HOST_AGENT_CAPACITY and the original spawn_error
         if action.spawn.count == 1:
             invoke one isolated worker with workers[0].native_launch_prompt
             for Codex use fork_turns="none"; the worker must not drive Loop or spawn
         else:
             verify each prompt_ref hash without reading its body, then invoke each worker
             with workers[i].native_launch_prompt
         wait for all outstanding workers with one bounded native wait; 禁止 30 秒轮询，
             只在 5 / 10 / 15 分钟心跳边界重新评估，等待期间不得重复读取 diff 或状态文件
             Codex 使用 collaboration.wait_agent({"timeout_ms":300000})，或
             multi_agent_v1__wait_agent({"targets":["<agent-id>"],"timeout_ms":300000})，最多三次
         三次 wait 返回仍未完成时，这只是观察结果；查询原生 handle/owner liveness，不能直接
             写 `timed_out`、提交失败 Result 或并发重跑。无法确认旧 Worker 已终止时保留当前
             Action 并进入 `WAIT_RESOURCE/WORKER_OWNERSHIP_UNCERTAIN`。
         read action.host_execution.work_files and use only these Action-scoped paths;
             不得复用上一 Action 的文件
         write only native WorkerOutcome facts to work_files.outcomes, including the selected
             tool family's isolation_evidence (`fork_turns=none` or `fork_context=false`)
             and actual_model reported by the native API; if unavailable use exact `unreported`,
             never null and never infer a model name
         copy `execution_generation` and `fencing_token` from the Worker launch contract unchanged;
             if either is missing or mismatched, do not guess and do not submit the outcome
         if a worker is explicitly reported failed/timed_out by the native host:
             write that native failure fact to work_files.outcomes and write {} to coordinator_result;
             never convert a wait timeout into this branch; never fabricate a plan, proof,
             attestation, or spawned field
         else merge business fields required by action.expected_format into work_files.coordinator_result
         execute action.host_execution.operations.finalize.argv verbatim;
             replace only __AE_BUNDLED_RUNNER__ with the fixed bundled runner
         use work_files.result as the complete Result; never hand-build receipt, attestation,
             spawned, or total proof fields
         after tick returns the next Action, 丢弃上一 Action 的对象、work_files、Worker handle
             与命令参数，只保留新 Action；错误恢复禁止重复输出全量 diff、旧工作文件或
             历史 Action JSON，只消费结构化错误码和 active Action 摘要
     else:
         execute only the explicit non-business inline control/configuration action;
             never execute architect, developer, critic, verifier, or audit work inline
         read action.host_execution.work_files；不得复用上一 Action 的文件
         write only fields required by action.expected_format to work_files.coordinator_result
         execute action.host_execution.operations.finalize.argv verbatim
         use work_files.result as the complete Result; never copy stdout or hand-build identity
     ensure result.stage == action.stage
     validation = execute action.host_execution.operations.validate.argv verbatim
     if validation.action == "error":
         repair the same result file; do not advance or create another Action
         continue
     action = execute action.host_execution.operations.submit.argv verbatim
3. if control.disposition == "WAIT_RESOURCE": do not ask the user; recover capacity and
   re-execute the original active Action without advancing the Tick
4. if control.disposition == "WAIT_USER": ask only for control.reason_code
5. if control.disposition == "TERMINAL": report action.verdict and fresh evidence
```

等待到期不是失败：一次 wait 未观察到完成只记录心跳并继续等待，不生成失败 Result、不消耗
重试次数、不重启 Worker。只有宿主明确证明 Worker/owner 已终止时才可判定失败；无法确认旧
Worker 已终止时必须进入 `WAIT_RESOURCE/WORKER_OWNERSHIP_UNCERTAIN`，禁止并发重跑。

宿主只按 `extensions.ae.execution_control` 决定继续或停止：`CONTINUE` 必须在提交当前
Result 后立即读取下一 Action；`WAIT_USER` 只询问 `reason_code` 对应的真实决策；只有
`WAIT_RESOURCE` 自动回收/等待后重试原 active Action；`resource_wait` 不得作为 Result
提交。只有 `TERMINAL`、`ERROR` 或 `HANDOFF_REQUIRED` 可结束当前自动驱动。Core 不运行后台
daemon，不得把“已输出一个 Action”当作完成。

`STATE_RECONCILIATION_REQUIRED` 是旧状态与本次显式设计文档冲突的用户决策点。
只展示 Core 给出的“重新初始化 / 修复状态并继续”，用户选择前不编辑项目；不得自动
恢复旧 Action、物理删除 `.ae-state` 或替用户选择。
Result 使用 `gate_id=state_reconciliation` 和 Core option id
（`reinitialize` / `reconcile`），`causation_id` 必须绑定当前 Gate message。

启动时不要把设计文档路径作为 requirement 传入。正确写法是：

```bash
ae-run dev-loop --init "实现 Voice Clone 页面" \
  --design-doc design/V1.0-Design-VoiceClonePage.md
```

如果设计文档就是唯一需求，可省略 requirement；此时默认执行设计文档的全部内容：

```bash
ae-run dev-loop --init \
  --design-doc design/V1.0-Design-VoiceClonePage.md
```

若 requirement 本身看起来是现有 Markdown 文件路径，宿主应停止并要求补充
`--design-doc`，不得继续创建 `design_doc_path=null` 的 architect Action。

## CLI 契约

| 命令 | 输出 |
|---|---|
| `ae-run dev-loop --init "req" [--design-doc <path>]` | 首个 action JSON |
| `ae-run dev-loop --validate-result <file>` | 无副作用 Result 预校验 |
| `ae-run dev-loop --finalize-result <payload> --output-result <result>` | 非 spawn Action 原子生成完整 Result |
| `ae-run dev-loop --finalize-result <outcomes> --coordinator-result <payload> --output-result <result>` | spawn Action 原子生成证明与完整 Result |
| `ae-run dev-loop --tick --result <file>` | 下一个 action JSON |
| `ae-run dev-loop --status --format json` | 状态 JSON |
| `ae-run dev-loop --resume <id>` | 恢复后的 action JSON |
| `ae-run status --format json` | 统一状态 JSON |

## Spawn 纪律

1. 先读取并核验 `action.coordinator_prompt_ref`，再读取 `action.spawn.count`、
   `action.spawn.parallel` 和 `action.spawn.effort`。
2. 将 `action.spawn.effort` 视为抽象推理强度。适配层将其映射为宿主支持的
   推理控制；默认使用最低够用的经济档，复杂架构、安全或跨模块故障才提高。
3. 检查 `HostCapabilities.subagents`；并行任务还需检查
   `HostCapabilities.parallel_subagents`。
4. 能力满足时：无论单 Worker 或多 Worker，都必须逐项消费
   `action.spawn.invocations[]`。在主会话只用摘要命令核对每个 invocation 的
   `prompt_ref`/`prompt_sha256`，不得读取正文；把对应 `native_launch_prompt` 原样交给
   Worker，并使用 invocation 的 `requested_effort`、`isolation`、`receipt_path`。以
   `action.host_execution.workers[i]` 的机器字段作为当前 Worker 映射事实源。
   宿主只收集原生 WorkerOutcome，不直接修改模板或证明文件。
5. `action.subagent_prompt` 只允许 Coordinator 合并真实 Worker 的业务输出，
   绝不能作为 Worker invocation prompt；证据只能由 `--finalize-result`
   原子终结，宿主和 Worker 都不得手工写共享 proof。
6. 能力不足时，报告 `HOST_CAPABILITY_UNAVAILABLE` 并停止，不得 inline 替代
   强制 spawn，也不得把 `"spawned"` 伪造为 true。
7. 按 `action.expected_format` 提取业务字段到 `coordinator-result.json`，
   原生执行事实写入 `outcomes.json`，再调用 `--finalize-result`。
   `action.result_contract` 是机器类型事实源：数组和对象必须写为原生 JSON，禁止再次
   序列化成字符串。Backend/Finalizer 只会对合法 JSON 字符串执行一次确定性恢复；
   解码后仍不匹配时以 `HOST_ACTION_OUTPUT_INVALID` fail-closed，不得手工绕过。

非 spawn Action 只写业务 payload，并调用
`ae-run dev-loop --finalize-result coordinator-result.json --output-result result.json`。
所有 Action 的 Result Envelope
均由 Core 绑定 active Action 后生成；宿主不得复制 message_id、thread_id、tick、stage、
causation_id 或 correlation_id。
   只有该命令可产生 `"spawned": true`。

宿主不得直接把手写业务 JSON 交给 `--tick`。`--tick` 只接受当前 Action 的 Finalizer
产物；任何业务 payload 都必须先经过同一 Action 的 `--finalize-result`，再
`--validate-result`，最后才可 `--tick --result`。若误提交旧 Result，必须读取返回的
active Action 摘要并回到当前 Action 的 operation 顺序，不得继续重试旧 Result。

协调入口返回 WAIT/ERROR/HANDOFF/TERMINAL 时会在 `.ae-state/reports/` 生成确定性
`loop-stop-*.md`，只记录 Action、Receipt、原因码与下一步。不得用自由文本 recap 覆盖该报告。

Codex 宿主必须读取 `action.host_execution.native_worker_tools`，按
`first_complete_exposed_family` 从当前会话实际工具清单选择任一完整工具族：
`collaboration.spawn_agent / collaboration.wait_agent / collaboration.interrupt_agent`，
或 `multi_agent_v1__spawn_agent / multi_agent_v1__wait_agent /
multi_agent_v1__close_agent`。任一完整工具族即表示 Worker 原生能力可用；将
`action.spawn.effort` 传给所选 spawn 操作的 `reasoning_effort`，其中 `xhigh` 不得静默降级。并行 Action 按
`action.spawn.count` 创建独立 Agent。不得因为当前回复尚未调用子代理就判定能力不存在；
工具已暴露时，只有真实调用明确失败后才可报告 `HOST_CAPABILITY_UNAVAILABLE`。当
`execution_control.disposition == "CONTINUE"` 时，不得在调用前向用户交回控制。

## 上下文交接

引擎会在 architect、developer、critic 完成后写入 `.ae-state/offload/`。
developer 开始前读取 architect offload，critic 开始前读取 developer offload；
具体路径以当前 Coordinator Prompt 为准。

`session_rollover` 只用于异常恢复，不是正常 compaction 或自由文本 recap。旧执行
实例不得继续执行工作；
新会话只读取可校验 ResumeCapsule，提交 `session_claimed` 后才能恢复。宿主无原生
会话创建/接管能力时必须返回 `HOST_SESSION_HANDOFF_UNAVAILABLE`，不得把完整历史
复制到新会话，也不得在旧会话继续。

## 完成状态

| verdict | 含义 |
|---|---|
| GOAL_ACHIEVED | 目标达成，汇报验证结果 |
| QUALITY | 达到质量标准但触及轮次上限 |
| STAGNANT | 多轮没有实质进展 |
| HARD_LIMIT | 达到最大轮次 |
| REFINE_LIMIT | plan_refine 回路超限 |

## 失败透明

- 命令非零退出：读取并报告错误，不静默降级。
- `action == "error"`：报告 `error_code` 和 `message`。
- 连续两次不可恢复错误：停止并建议运行 `ae-run doctor`。

<!-- FRAGMENT:red_flags START -->
## Red Flags — STOP，不要继续，向用户报告

- 我正准备在 Python 输出 {"action":"developer"} 前编辑代码
- 我正准备在 Python 输出 {"action":"done"} 前宣布完成
- 命令执行失败了，我正准备静默切换到手工模式继续
- 宿主原生子代理能力不可用，我正准备自己手工模拟这个 stage
- 我正准备跳过 --tick 自己推进到下一个 stage
- critic 返回 MAJOR，我正准备忽略 findings 直接进收敛

以上任何一条都意味着：停止。向用户报告失败原因 + 状态 + 选项。禁止静默降级。
<!-- FRAGMENT:red_flags END -->
