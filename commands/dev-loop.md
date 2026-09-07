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

启动时必须固定 bundled runner，并将宿主启动 cwd 规范化后导出为不可变的
`AE_INVOCATION_PROJECT_ROOT`。本文后续每个 `ae-run` 都是以下完整调用的缩写：
`env AE_HOST_PLATFORM=claude-code AE_HOST_ACTION_VIEW=compact "${CLAUDE_PLUGIN_ROOT}/bin/ae-run"`。实际 Bash 调用必须保留
该环境前缀和绝对路径，不得只执行文中的缩写；不得调用裸 `ae-run` 或另一宿主传入的 runner；不得
依赖 PATH，也不得搜索开发目录或缓存目录猜测入口。runner 不存在或不可执行时以
`HOST_RUNNER_UNAVAILABLE` fail-closed。runner 检测到请求根偏离
`AE_INVOCATION_PROJECT_ROOT` 时以 `AE_PROJECT_ROOT_DRIFT` fail-closed。

## 驱动循环

产品入口必须设置 `AE_HOST_ACTION_VIEW=compact`。CLI stdout 返回的 compact envelope 是
当前执行控制视图；完整 Canonical Action 仍由 Core 持久化。若存在
`coordinator_prompt_ref`，只读取其 `path` 一次并核验 `sha256`，不得扫描 Action Store，
不得要求 CLI 重新内联 `instruction` 或 `context`。spawn Action 只把
`spawn.invocations[i].prompt_ref` 交给对应 fresh Worker；Coordinator 不读取 Worker
prompt 正文，也不接受 `subagent_prompt` 旧字段。

对每个 spawn invocation，把对应
`action.host_execution.workers[i].native_launch_prompt` 原样作为原生 Worker 工具输入。
Coordinator 不得先读取、`sed`、复制、总结或重新拼接 `prompt_ref` 正文；主会话只允许
校验文件 SHA-256。由 fresh Worker 切换到机器指定 `project_root`，读取并验证 Artifact。

```text
1. invocation_project_root = 宿主启动 cwd 的真实绝对路径（本次启动不可变）
   # 发布验收若有候选 build_id，必须先执行：
   # ae-run build-info --expect-build-id <candidate-build-id>
   # 非零退出即停止，不得切换 runner 或继续到 init。
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
     # Python 只提供确定性 Core 操作；不得启动宿主会话。
3. 主 Agent 在同一会话内持续执行：
   while action.extensions.ae.execution_control.disposition == "CONTINUE":
     print "[Tick N | stage <action.stage>] ..."
     control = action.extensions.ae.execution_control
     if control.disposition == "ERROR":
         report action.error_code + action.message
         STOP
     if action.action == "gate" and control.disposition == "WAIT_USER":
         ask only the options returned by Core; write only the selected
         {gate_resolution:{gate_id:<current gate id>,resolution:<selected option>}}
         to action.host_execution.work_files.coordinator_result; execute the
         bound operations.finalize.argv, validate.argv and submit.argv in order;
        never call --tick without the finalized Result and never invent a second
        gate loop
        continue
     if action.host_execution.recovery.status == "worker_outcomes_committed":
         assert action.host_execution.recovery.spawn_permitted == false
         assert action.host_execution.recovery.required_operation == "repair_coordinator_then_finalize"
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
     if action.action == "skip":
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
         enforce action.gap_review_contract as a protocol gate
         present only action.current_gap: problem, evidence, impact, recommendation, rationale, options
         historical conversation, gap_scan.gaps, total_gaps, and any future gap details are not display input
         ask one user decision and submit exactly one result.decision for this Tick
         never enumerate, summarize, batch-ask, cache later decisions locally, prefill defaults, or change current_gap.id
        用户可在当前决定中显式设置 apply_to_remaining=recommendations；只有 Core 随后返回
        auto_decision 时才可自动提交，禁止从 user_note 自然语言推断长期授权；宿主只补充
        fill_content 等说明字段，Finalizer 从 active Action 重绑全部 Core-owned 机器字段
    if action.host_execution.recovery.status == worker_attestation_pending:
         私有 Worker outcome 已存在但宿主事实尚未回写；这是宿主回写修复，不是 Worker 失败。
         禁止提交 spawned=false、消耗失败预算或重新 spawn；使用仍有效的原生 handle、model
         和 isolation，按 workers[].record_worker_outcome 固定模板回写后，再按当前 Action
         写入 coordinator_result 并执行 finalize、validate、tick。原生 handle 丢失时停止并
         报告 HOST_WORKER_ATTESTATION_MISSING，不得使用 unreported:* 冒充 completed。
         Claude Code 必须从原生结构化返回的 task_started.task_id/agentId 取得唯一句柄；
         不得启动回显 Agent、不得伪造 completed Worker，也不得把自然语言、worker_id 或摘要当作句柄。
    elif action.host_execution.recovery.status == native_outcomes_ready:
         禁止重新启动 Worker；若 coordinator_result_ready=true，使用 recovery 的当前
             outcomes_ref、coordinator_result_ref 和 result_ref 直接 finalize，再 validate/tick；
             否则只根据已固化 outcomes_ref 生成 Coordinator payload，写入
             coordinator_result_ref 后再 finalize、validate、tick
    elif action.spawn exists:
         validate HostCapabilities against action.spawn
         consume action.spawn.invocations[] exactly; instruction is diagnostic only
         consume action.host_execution.workers[] as the evidence-template SSOT
         pass workers[i].native_launch_prompt verbatim to the native spawn tool;
             不得先读取 prompt_ref 正文，也不得把正文复制进 tool call
         keep native agent/thread IDs only as native_worker_handle; never replace worker_id
         if the native spawn response has no structured handle/agent id or returns an empty
         target list, do not call wait; record a Stop Report with:
         `ae-run --run-module auto_engineering.host.process_exit --project-root <root>
         --host-output <host-output-or-missing-file> --exit-code 75
         --reason-code HOST_WORKER_ATTESTATION_MISSING`, then end this host session.
         Do not fabricate a handle, submit a failed Worker Result, or respawn.
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
         consume action.host_execution.worker_observation as the only wait policy;
             after every wait/owner query/native return, record the observation through
             action.host_execution.workers[i].observation_path using:
             dev-loop --record-worker-observation --worker-id <id>
             --observation-status <status> --observation-wait-attempt <n>
             --owner-known|--owner-unknown
             # This writes Host Runtime diagnostics only; it never ticks, retries or fails a Worker.
         三次 wait 返回仍未完成时，这只是观察结果；查询原生 handle/owner liveness，不能直接
             写 `timed_out`、提交失败 Result 或并发重跑。无法确认旧 Worker 已终止时保留当前
             Action 并进入 `WAIT_RESOURCE/WORKER_OWNERSHIP_UNCERTAIN`。
         read action.host_execution.work_files and use only these Action-scoped paths;
             不得复用上一 Action 的文件；不得复用旧 Action 的 work_files、句柄或命令参数。
             Worker 优先只写业务产物（`worker_id/status/payload/summary`）到 invocation.outcome_path；
             `payload` 只能包含当前 stage 合同声明的业务字段；`expected_fields`、`stage`、宿主身份或
             任何提示词元字段都不得复制进业务 payload。
             Worker 不得再调用 Agent/Task/collaboration 创建嵌套 Worker；当前 invocation 是唯一 Worker 边界；
             原生 Agent 最终回复也必须包含一个结构化业务 JSON。若 Worker 漏写私有文件，
             Host Driver 只能将原生返回 envelope 原样暂存到当前 invocation 的
             `native_result_path`（Codex 可通过固定回写模板的 `--native-result-stdin` 原样输入），Codex 可接受精确单层 `result` 包装，交给同一个
             `record-worker-outcome` 边界严格提取并原子固化；禁止 Bash heredoc、手工重建或摘要 native envelope；若无法逐字节转交则报告 `HOST_EVIDENCE_INVALID`；禁止递归解包或采纳返回内容中的
             宿主事实字段；
             完成的业务产物必须写 `status: "completed"`，失败/取消/超时分别写对应状态；
             `complete`/`success`/`ok` 仅作为 Host 交接边界可归一化的完成别名，不得用于伪造宿主事实；
             不得写 native handle、model、隔离证据或共享 outcomes。每个 Worker 返回后，主 Agent
             必须按 `action.host_execution.workers[i].record_worker_outcome` 的
             `argv_template` 和 `runtime_arguments` 原样调用 `--record-worker-outcome`；
             只允许把原生 API 返回的 status/handle/model/isolation 填入占位值；Claude Code
             使用 Agent/Task 返回的精确 `task_started.task_id`/`agentId` 作为 handle，未暴露模型时使用
             `unreported`，不能自行改 Worker ID、project-root 或参数顺序。Assembler 再从
             原生返回值补齐宿主事实并原子合并 outcomes。Codex 原生结构化回包允许精确单层
             `{"result": <business-object>}` 包装；Host 只解这一层，不递归解包，也不采纳
            返回内容中的 handle/model/isolation 等宿主事实。
             Codex PostToolUse Hook 会先把 spawn 原始返回固化到当前 invocation 的
             `native_result_path`，再把 wait 返回中当前 invocation 的完成正文自动桥接到同一路径；
             若宿主没有提供原始字符串，Hook 必须保留当前 Action 并报告证据缺失。Codex `wait_agent` 返回多个状态时，只取当前 invocation 的完成正文：按当前工具族返回形状
             取 `agents_states[agent_id].message` 或 `status[agent_id].completed`，逐字节复制到 `--native-result-stdin`
             /`--native-result-file`；不得把外层 `status`/`agents_states` 映射整体
             回写，也不得取空 wait、其他 Worker、Coordinator 摘要或手工重建 envelope。读取到的
             native envelope 必须先完成 record-worker-outcome，
             再按 lifecycle contract close_agent，最后使用共享 work_files 执行 Finalizer。
            Codex 在记录每个 completed outcome 后，必须立即按
             `action.host_execution.worker_lifecycle.required_order` 调用当前实际暴露的
             `close_agent`（或 `multi_agent_v1__close_agent`/
             `collaboration.interrupt_agent`）回收对应 native handle；close/reclaim 成功
             之前禁止 finalize、禁止 tick、禁止启动下一 Worker。没有 close 工具或 close
             失败时保留当前 Action，写 Stop Report 并报告宿主容量/生命周期错误，不得把
             “已 wait/已 record”当成已回收。
             Claude Code 的 Agent（Task 兼容别名）是原生完成观察；可能直接返回完成，也可能先返回
             `async_launched`/`running`/`pending`。异步返回后只能对同一 `agentId/task_id` 调用
             `TaskOutput` 直到 completed，期间禁止 Stop、TaskStop、Read、Bash、重启或手工补录。
             Agent 的自然语言回复不是业务结果；只有完成观察中唯一、通过 schema 校验的结构化 JSON
             才能作为 Host 交接输入。Claude 的 PostToolUse 已将原生 envelope 原样写入
             `native_result_path` 时，禁止读取、解析、摘要或重建该文件；只按固定
             `record_worker_outcome` 模板直接消费它。仅当该文件不存在时，才报告
             `HOST_EVIDENCE_INVALID`。取得原生返回的 task_started.task_id/agentId、status 和 model 后立即回写；
             没有可验证句柄时禁止以 unreported:* 冒充 completed。
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
     elif action.action == "project_setup_required":
         # setup 是唯一允许主 Agent 直接修改项目的非 spawn 业务 Action。
         # Core 不生成脚手架；宿主只按 missing_capabilities 和当前设计补齐能力。
         inspect only action.project_root, action.design_doc_path and action.missing_capabilities
         edit only the target project root; do not edit the plugin tree, spawn workers,
            start another loop, or invent an unrequested framework
         if missing_capabilities contains setup_gate:*:
             establish the project's own tool environment (.venv or the declared package-manager environment)
             declare and synchronize the required test/lint/type/build tools in the project configuration
             never use the plugin .ae-state/.ae-runtime as the project environment
             for Python, if .venv/bin/python is absent, run env -u UV_PROJECT_ENVIRONMENT -u VIRTUAL_ENV uv venv .venv
             declare missing pytest/ruff/mypy under the PEP 735 [dependency-groups] dev group
             in pyproject.toml, and configure [tool.pytest.ini_options] with the project test root;
             do not substitute [project.optional-dependencies]
             run env -u UV_PROJECT_ENVIRONMENT -u VIRTUAL_ENV uv sync --dev --project .
             verify gates with the project .venv/bin tools before reporting setup complete
             on a failed setup gate, repair the declaration or environment in place; never run
             rm -rf .venv, delete project state, or reinitialize the project to hide the failure;
             package only source and required metadata, excluding .ae-state, _scratch, .venv, dist,
             and build so absolute-path symlinks cannot enter sdist; retry the same failed command
             at most once in this Action, then submit the Result for Core to issue the next Action
             or resource_wait instead of looping inside the host
         write only action.host_execution.work_files.coordinator_result with:
             {stage:"project_setup", result_type:"project_setup_completed", artifacts:[...]}
         if the command or gate still fails after at most one in-place repair, submit instead:
             {stage:"project_setup", result_type:"project_setup_failed", artifacts:[],
              failure_code:"PROJECT_SETUP_*", failure_summary:"bounded diagnostic", attempts_in_action:1|2}
         This failure payload returns control to Core; do not keep executing setup commands in this Action.
         execute action.host_execution.operations.finalize.argv verbatim
         execute action.host_execution.operations.validate.argv verbatim
         if validation.action == "error":
             repair the same setup coordinator result; do not create another Action
             continue
         execute action.host_execution.operations.submit.argv verbatim
         continue
     else:
         execute only the explicit non-business inline control/configuration action;
             never execute architect, developer, critic, verifier, or audit work inline
         read action.host_execution.work_files；不得复用上一 Action 的文件；
             不得复用旧 Action 的 work_files、句柄或命令参数。
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

宿主调用返回后（包括原生 CLI 进程退出或返回空结果），必须先读取当前 Action 的
`host_execution.continuation`；其 `after_host_return` 必须为
`recheck_core_status`，再执行一次 `ae-run dev-loop --status --format json`。
这不是新的业务 Tick，也不是第二套循环：它只是返回边界的状态回查。若 Core 仍返回
`CONTINUE` 或仍存在 active Action，必须消费 `next_operation=resume_active_action`，
恢复同一 Action 并继续其原有操作；不得把进程返回、空 stdout、模型成功文本或单个
Action 完成报告为 Loop 成功，不得报告成功。只有 `WAIT_USER`、`WAIT_RESOURCE`、`TERMINAL`、`ERROR`
或 `HANDOFF_REQUIRED` 允许让出当前宿主控制权。非零退出、空结果和非终态退出必须
保留 `.ae-state`、记录结构化中断事实并恢复/报告，禁止吞错、重跑已落盘 Worker 或
启动第二个 Coordinator。

Action 身份只由 `thread_id + message_id` 决定；`stage`、`tick` 和 `causation_id` 不能替代身份。
因此同一 stage 的新 batch（例如 `developer B1` 后的 `developer B2`）只要
`message_id` 不同，就必须丢弃上一 Action 的局部对象、路径和 Worker 句柄，按新 Action
重新执行；不得因为 stage 名相同而报告“同一 Action 需要协调”。

Host Runtime 会在项目根内预创建当前 Action `host_execution.work_files` 的父目录；宿主
只使用 Action 给出的完整路径写入，不得自行拼接旧路径、固定文件名、切换到其他 cwd 或
把结果写到项目根外。

等待到期不是失败：一次 wait 未观察到完成只记录心跳并继续等待，不生成失败 Result、不消耗
重试次数、不重启 Worker。只有宿主明确证明 Worker/owner 已终止时才可判定失败；无法确认旧
Worker 已终止时必须进入 `WAIT_RESOURCE/WORKER_OWNERSHIP_UNCERTAIN`，禁止并发重跑。

`action.host_execution.worker_observation` 是等待策略的机器合同：Codex 为三次 300 秒
bounded wait，心跳边界为 5/10/15 分钟；Claude 为同步原生返回。宿主不得从 stage、自然语言
摘要或默认工具超时猜测这些值。每个 Worker 的 `observation_path` 只保存当前 Action 的
最新原生观察，必须与 `execution_generation` 和 `fencing_token` 绑定；它不是 Core 事实源，
也不能替代 `record-worker-outcome`、Finalizer、validate 或 tick。

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

设计文档是 binding source，默认只读。Architect、Worker 和 Coordinator 不得编辑原设计、
注入 `ae:component` 元数据或为补齐结构改写章节；确需改变设计时只能提交
`design_change_requests[]`，由 Core 进入用户 Gate，批准后再执行明确的设计变更 Action。

## CLI 契约

| 命令 | 输出 |
|---|---|
| `ae-run dev-loop --init "req" [--design-doc <path>]` | 首个 action JSON |
| `ae-run dev-loop --validate-result <file>` | 无副作用 Result 预校验 |
| `ae-run dev-loop --finalize-result <payload> --output-result <result>` | 非 spawn Action 原子生成完整 Result |
| `ae-run dev-loop --finalize-result <outcomes> --coordinator-result <payload> --output-result <result>` | spawn Action 原子生成证明与完整 Result |
| `action.host_execution.workers[i].record_worker_outcome` | 逐 Worker 的固定回写命令模板；宿主只填原生 status/handle/model/isolation，必要时附带当前 `native_result_path` |
| `ae-run dev-loop --record-worker-outcome --worker-id <id> --worker-status <status> ...` | 在同一边界校验私有 outcome，必要时从原生返回暂存原子固化，再与宿主事实合并到当前 Action outcomes |
| `ae-run dev-loop --tick --result <file>` | 下一个 action JSON |
| `ae-run dev-loop --status --format json` | 状态 JSON |
| `ae-run dev-loop --resume <thread-id>` | 从 EventStore 恢复后的 action JSON |
| `ae-run dev-loop --import-checkpoint <id>` | 显式将旧 checkpoint 导入 EventStore 后输出 Action |
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
   Claude 异步 Agent 若先返回 `async_launched`，下一次原生调用必须是同一
   `agentId/task_id` 的 `TaskOutput`，直到 completed；期间禁止 Stop、TaskStop、Read/Bash
   探查、重启 Agent 或手工补录。只有同一句柄的完成正文才可固化到该 Worker 的
   `native_result_path`，running/pending 观察不得覆盖句柄元数据。
5. 多 Worker 只有在 `action.coordinator_prompt_ref` 存在时读取该 Coordinator Artifact；
   Worker prompt 永远只来自对应 invocation 的 `prompt_ref`/`native_launch_prompt`，
   绝不从旧 `subagent_prompt` 或其他内联字段推导；证据只能由 `--finalize-result`
   原子终结，宿主和 Worker 都不得手工写共享 proof。
6. 能力不足时，报告 `HOST_CAPABILITY_UNAVAILABLE` 并停止，不得 inline 替代
   强制 spawn，也不得把 `"spawned"` 伪造为 true。
   若 Claude `Agent` 被 PreToolUse Hook 拒绝，必须保留当前 Action 并走结构化
   `HOST_EVIDENCE_INVALID`/`WAIT_RESOURCE` 恢复；不得在 Coordinator 会话内 inline
   执行 Architect、Developer、Critic、Verifier 或 Audit。合同复制错误只能重新读取
   当前 Action 的 `native_launch_prompt` 原文后重试，不得手改 hash、路径、Worker ID
   或 JSON。
7. 按 `action.expected_format` 提取业务字段到 `coordinator-result.json`；每个原生 Worker
   返回后先调用 `--record-worker-outcome`，由 Assembler 写入 `outcomes.json`，再调用
   `--finalize-result`。不得手工编辑共享 outcomes。若 finalize 非零退出、
   `result.json` 缺失或解析失败，必须停留在当前 Action 进入 repair/Stop Report，禁止继续
   validate、submit、tick 或报告 Core 已进入 `ERROR`。
   `action.result_contract` 是机器类型事实源：数组和对象必须写为原生 JSON，禁止再次
   序列化成字符串。Backend/Finalizer 只会对合法 JSON 字符串执行一次确定性恢复；
   解码后仍不匹配时以 `HOST_ACTION_OUTPUT_INVALID` fail-closed，不得手工绕过。

`project_setup_required` 的项目修改仅按上方专用分支执行。宿主必须核验
`constraints.setup_scope.mode == "capability_only"`：只处理项目元数据、工具链、源码/测试根和
最小非业务 smoke/contract test；不得实现用户业务功能、不得创建业务测试、不得编写用户文档，
业务实现只能从 Architect/Developer Action 开始。Smoke 只能证明工具链和空包可执行，不得
导入、创建或引用设计中的业务模块、类、函数或行为；不得为了让 smoke 通过而创建业务模块
桩代码，若 smoke 需要业务模块则应删除或改为非业务 smoke。Core 会以 Setup 开始时的项目文件基线复核该
边界，不能以 `artifacts` 或宿主文字声明绕过。其余非 spawn Action 只写业务 payload，并调用
 Python 项目可固定使用声明测试根中的最小 `test_smoke.py`；Node 项目可使用
 `test_smoke.js/.jsx/.ts/.tsx`。这些文件仅执行工具链自检，不得导入设计模块或写业务断言。
项目测试命令必须一次性、非交互并在完成后退出；Vitest 使用 `vitest run`，不得使用默认
`vitest` 或 `--watch`，Cypress 不得使用 `cypress open`，Playwright 不得使用 UI 模式。
`ae-run dev-loop --finalize-result coordinator-result.json --output-result result.json`。
所有 Action 的 Result Envelope
均由 Core 绑定 active Action 后生成；宿主不得复制 message_id、thread_id、tick、stage、
causation_id 或 correlation_id。
   只有该命令可产生 `"spawned": true`。

宿主不得直接把手写业务 JSON 交给 `--tick`。`--tick` 只接受当前 Action 的 Finalizer
产物；任何业务 payload 都必须先经过同一 Action 的 `--finalize-result`，再
`--validate-result`，最后才可 `--tick --result`。若误提交旧 Result，必须读取返回的
active Action 摘要并回到当前 Action 的 operation 顺序，不得继续重试旧 Result。

若 Guardrail 返回 PII 重试，必须修复真实文件中的凭据或个人数据；测试脱敏用例只能使用明显的
fake 占位符或运行时拼接值，禁止把形似真实凭据的字面量写入源码。必须保持测试断言和失败事实，
不得通过修改断言、伪造测试统计或删除用例来消除门禁。

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
