# 2026-09-05 真实 Codex Worker 容量中断

## 结论

真实 Codex 轨迹在 Architect、两轮 Developer 和 Critic 后，因宿主返回
`agent thread limit reached` 停止。Stop Report 正确标记为
`HOST_RUNTIME_PROTOCOL_ERROR`，Core 保留了 Critic 修复后的 active Action，未伪造
Worker 结果，也没有推进错误的 Tick。

## 事实链

- 候选 Build：`5.8.0-rc.5+sha256.e65e4f2d21599405`
- 已完成原生 Worker：Architect 1、Developer 4、Critic 1；每次均有 `wait`、业务 outcome、
  `record-worker-outcome`、`finalize`、`validate` 和 `tick` 事实。
- 真实流中没有任何 `close/reclaim` 调用；第 7 次 Worker 启动返回宿主线程额度耗尽。
- 宿主进程退出码为 0，但 Core 仍要求继续，因此 Stop Report 阻止了假终态。

## 根因与修复方向

根因在 Host Driver 的 Worker 生命周期执行，不在 Tick Core：Action 虽然声明了 close 工具
族，Skill 也要求回收，但当前真实 Codex 工具表/别名没有形成可验证的“完成后必回收”步骤，
Coordinator 因而只等待和记录，没有释放已完成句柄。

修复必须保持单 Coordinator、单 Tick：

1. 将 `wait → record → close` 固化为当前 Action 的 machine lifecycle contract，并要求
   close 成功事实才能执行 `finalize`。
2. 宿主启动前验证当前会话暴露了与 spawn/wait 对应的 close 能力；缺失时立即以
   `HOST_AGENT_CAPACITY`/`WAIT_RESOURCE` 保留当前 Action，不假装可持续运行。
3. 增加真实宿主轨迹回归，断言每个 completed Worker 都有 close，且 close 缺失时不允许
   进入下一 Action；修复后重新执行双宿主 L4。

## 发布判定

本次是有效的 fail-closed 诊断，不是 L4 成功。A008 和发布门禁继续保持阻断。

## final50 复验：Worker 回收已修复，但宿主硬超时仍未闭环

- 新候选 Build：`5.8.0-rc.5+sha256.28f62d23e3759496`
- Architect 与 Developer B1 均完成了真实 `spawn → wait → record-worker-outcome → close_agent`；
  这证明上一轮的句柄泄漏修复已进入真实 Codex 工具链。
- B1 的私有 outcome 已原子落盘并成功回收 Worker，但主宿主会话在
  `finalize → validate → submit` 前返回 `TIME_LIMIT_EXCEEDED`，未到达 `TERMINAL`。
- T783 已补齐停止事实：Host Runtime 能从嵌套原生 envelope 识别精确原因，并在 Stop Report
  暴露同一 thread 的 `resume_active_action`；该操作只供宿主 continuation 消费，不创建 Tick、
  Worker 或 Python Coordinator。

因此，当前剩余问题不是“Worker 是否关闭”，而是宿主硬时间上限后的新会话是否能按既定
ResumeCapsule/claim 合同自动接管并完成同一 Action。没有这条真实双宿主 continuation 证据，
A008 仍保持阻断。

## final55 复验：Claude Agent 回包已自动固化，但合同复制错误暴露内联逃逸

- 候选 Build：`5.8.0-rc.5+sha256.b9c77e8a321272e3`
- Claude 的 Architect 原生 Agent 已由 `PostToolUse` Hook 原子写入当前 Action 绑定的
  `native-result_path`，Host 随后完成 `record-worker-outcome → finalize → validate → submit`，
  Core 正确推进到新的 Developer Action。这证明 Claude 不需要 Coordinator 手工读取
  `output_file` 或重建原生 envelope。
- Developer Agent 的启动合同只有一个可定位的复制误差：模型把正确的
  `prompt_sha256` 写成了 `prompt_sha256 + ".txt"`。PreToolUse 原本正确拒绝；模型随后错误地
  在 Coordinator 会话内执行 Developer 工作。该次运行已正常停止，Stop Report 保留了
  `HOST_RUNTIME_PROTOCOL_ERROR / session_ended_with_continue`，没有伪造 Worker 事实或推进 Tick。

修复内容：Claude 合同只允许将“当前期望 hash + `.txt`”确定性归一为期望 hash，其他字段、
路径、Worker ID 和任意 hash 仍 fail-closed；Developer Worker 提示移除 `inline TDD` 歧义，
Skill/Command 明确 Agent 被拒绝时必须保留当前 Action 并等待/重试，不得由 Coordinator inline
执行业务角色。T784 回归已通过；需用新制品重跑真实双宿主终态，A008 继续阻断。

## final56 复验：Claude 异步 Agent 需要 TaskOutput 完成观察

final56 的真实恢复轨迹确认了另一个宿主差异：Claude `Agent` 首次返回的是
`async_launched + agentId` 元数据，业务 Worker 正文由后续 `TaskOutput(task_id)` 返回。
若只捕获 Agent 回执，Host 会把句柄元数据误当成业务结果，随后错误地阻断
`record-worker-outcome`。

修复为同一 PostToolUse 证据链：Agent 回执先原子保存为句柄索引；TaskOutput 通过同一
`agentId/task_id` 精确找到当前 `native_result_path`，只有 `completed` 正文才覆盖索引，
`running/pending` 只记录观察。final56 已通过 `2993 passed/1 skipped`、覆盖率 `90%`、
Ruff/mypy/compileall/diff 门禁；新真实复验已证明 Gate 恢复和 Architect Agent 启动成功，
当前需再次构建制品并验证 TaskOutput 完成后能继续 Developer/终态。A008 仍保持阻断。

## final51 复验：Core 正确发出 B2，宿主误把同 stage 当成同 Action

- 候选 Build：`5.8.0-rc.5+sha256.601f62da27700195`
- Architect 与 Developer B1 均真实完成 `spawn → wait → record-worker-outcome → close_agent → finalize → validate → submit`。
- EventStore 记录了 `BatchCompleted(B1)`，随后发出 `stage=developer`、`batch_id=B2` 且 `message_id` 已变化的新 Action；这证明 Core 没有重复发出 B1，也没有丢失 B1 完成事实。
- 宿主续驱动摘要仅按 stage 判断，错误地把 B2 报告为“同一 Developer Action 需要协调”，因而未启动 B2。该停止属于宿主协议执行错误，不计入 L4。

补强内容：Host continuation contract 现在返回 `same_action_rule` 和完整
`action_identity`，明确只有 `thread_id + message_id` 相同才是同一 Action；SKILL、Command
和回归测试同时锁定“同 stage 新 batch 必须继续”。

## final52 继续验证：Critic 回包缺少非业务摘要元数据

新宿主已按 `message_id` 正确从 B1 进入 B2，再进入新的 Critic Action。Critic 原生回包包含
严格的 `worker_id/status/payload` 业务 envelope，但未包含 `summary`；Host 因当前严格 envelope
校验返回 `WORKER_NATIVE_RESULT_INVALID`，没有写共享 outcomes，也没有推进 Core。该失败说明
`summary` 属于可确定性补齐的审计元数据，不应阻断业务 payload；修复后只在 Host 唯一回写边界
填充固定摘要 `native_worker_result`，不放宽 Worker 身份、状态或 payload 类型校验。

## final74 复验：Claude Worker 闭环已推进，但长任务观察仍未到终态

- 候选 Build：`5.8.0-rc.5+sha256.d83c48d4610073c4`
- 新鲜项目内真实执行已通过 Build Identity 预检、Gap Scan 同 Action repair，并依次完成
  Architect、Developer 的 Agent → TaskOutput → native-result 固化；Core 从 Architect 推进到
  Developer，说明本次 Claude 原生交接链已真正越过首个 Worker。
- Developer 的一次 `TaskOutput` 返回 `timeout`，原生任务状态仍为 `running`。宿主没有把它伪造为
  completed，也没有并发重启；在有界等待后安全退出。Stop Report 正确标记
  `session_ended_with_continue`，保留同一 thread 的 `resume_active_action`；Core 当前仍为
  `developer/CONTINUE`，不是 TERMINAL，也不是成功。
- 本轮新增的安全修复是：Coordinator 读取 Worker `prompt_ref` 正文会被
  `NATIVE_WORKER_PROMPT_READ_FORBIDDEN` 拦截，错误 Agent 启动会得到可执行的机器合同反馈，
  Claude `TaskStop` 继续被禁止。

因此 A008 仍阻断发布。剩余问题已从“原生 Worker 不能启动/无法回写”收敛为“真实长任务需要在下一宿主会话按 Stop Report 恢复同一 Action，并观察 running Worker 的终态”；不得用超时、自然语言完成或人工构造业务结果替代该证据。

### final74 continuation：同 Action 恢复有效，但业务安全 Gate 暴露测试夹具误报

恢复原 Claude 会话后，Host 对原 task 做了继续观察，未重新 spawn。Developer 私有业务 outcome
已完整落盘；第一次 Coordinator Result 因测试结果仍有失败被 Core 拒绝，随后发现临时项目的脱敏测试
使用了形似真实 API key 的字面量，触发 PII Guard。该事实属于真实业务/安全 Gate 反馈，不是 Loop
内核故障；宿主保留同一 Developer Action，并在下一次安全停止时生成相同的
`resume_active_action`。后续验收应使用显式 fake/拼接测试夹具，避免通过修改断言掩盖真实失败。

### final75 复验：PII 修复反馈仍可能诱导削弱测试证据

最新候选已将 PII Guard 的修复反馈明确为“只能替换 fake 夹具，不能修改断言”。但恢复的真实
Claude 会话仍尝试删除 `not.toContain(...)` 断言，并把实际失败改写成“设计缺口”。这次会话已
在形成终态前停止，不能计为成功；它说明提示词约束不足以保护验收证据。下一步增加
T786 `TestEvidenceIntegrityGuardrail`：对开发批次的测试文件变更检查断言删除/显著减少，命中时
当前 Action 保留并返回确定性修复反馈；不通过修改断言、伪造测试统计或删除测试来获得终态。

## final60-final63 复验：Claude L4 被宿主沙箱挡在首个 Action 前

最终候选 Build：`5.8.0-rc.5+sha256.0c167af2749ea00c`。连续三次使用干净临时项目复验，
均没有进入 `dev-loop --init`：

- final60：Claude 将用户目录中的固定插件 runner 视为项目沙箱外路径，未执行 `ae-run`。
- final61：明确写入用户已授权后，仍因全局 Release 路径不在允许目录而退出。
- final62：将同一 Release 放到独立 `/tmp` 目录后，仍被“只允许当前项目根”的路径策略阻断。
- final63：将 Release 原样解包到当前项目根后，插件可见，但 Claude 继续报告 Bash、`uv`、
  Python 和 `cd` 全部被权限系统拦截，未创建 Action。

这些运行的 Stop Report 均为“未发现活动宿主租约”，说明 Core 没有被启动，也不存在 Loop
中断、错误推进或伪造成功。该证据不能替代 Claude L4；发布仍需在具备项目根内 Bash 和固定
插件执行权限的真实 Claude 会话中重跑 A008。代码层的 PostToolUse `Agent|TaskOutput` 捕获、
原子 native-result 固化和禁止 Coordinator inline 已由回归测试覆盖。

## final77 复验：Coordinator 私有 outcome 伪造被真实 Hook 拦截

- 候选 Build：`5.8.0-rc.5+sha256.863beb80fd77864b`
- 干净临时项目真实执行已从 Gap Review 进入 Architect；原生 Architect Worker 在 fresh context
  中完成并写入当前 Action 绑定的私有 outcome，说明 Worker 写入路径没有被新守门器误伤。
- Coordinator 随后尝试直接操作 Worker 私有 outcome，真实 Claude `PreToolUse:Bash` 拒绝了该调用；
  它没有机会把手工 JSON 当成 Worker 事实提交。错误的原生 handle/回包交接继续返回
  `HOST_EVIDENCE_INVALID`，本轮按 fail-closed 结束，未到 TERMINAL，不能计为 A008 成功。

本轮同时发现并修复了守门器把 `2>/dev/null` 误当状态写入的误判；最终实现只把实际重定向到受保护
状态目录的操作视为写入。final78 已通过 `3011 passed/1 skipped`、覆盖率 `90%`、Ruff/mypy/
compileall/diff check，双宿主 archive smoke 通过。A008 仍只剩真实 native-result/handle
交接和 TERMINAL 证据闭环，不能通过放宽守门或恢复第二套循环绕过。

## final82 / final83：native 回执边界与 lease 丢失后的真实复现

- final82 使用 Claude 真实推进 Gap Review → 用户决策 → Research → Architect Worker。
  首个 Worker 的私有 outcome 成功进入 `record-worker-outcome`；设计变更批准后第二次
  Architect Worker 也写出了业务结果，但该结果是裸业务 payload，native Agent 回包只有
  人类摘要。原 Assembler 将两种情况混在一起，退回 native 解析并以
  `WORKER_NATIVE_RESULT_INVALID` 停止。
- final83 使用 Build `5.8.0-rc.5+sha256.b21b124a10ffd994` 重新启动真实 Claude。
  Gap Review 正确停在 `WAIT_USER`，同一 session 按授权继续，Architect 原生 Agent 正确
  启动并返回 `async_launched`。主会话未按合同调用同一 `agentId` 的 `TaskOutput`，在 Stop
  hook 下反复等待，不能计入 L4。
- 恢复尝试中，Claude 用 Bash 改写了绑定的 `.ae-state/host-runtime/native-results`，再构造
  顶层 Worker envelope 使 `record-worker-outcome` 通过。该事实不是原生回包，整轮证据已
  明确标记为不可采信并停止；不能计为成功。
- 根因是 Stop hook 清除 lease 后，`active_native_workers()` 返回无 lease，旧守门器把同一
  session 的协议状态写入当作普通宿主调用放行。T792 已改为：无 active lease 时仍阻断
  `.ae-state`/native-result/Worker 回写/TaskStop，普通项目工具和 Read 保持可用；新增回归
  覆盖该路径。随后全量 `3015 passed/1 skipped`、覆盖率 `90%`、静态门禁通过。

结论：final82/final83 都是 fail-closed 证据，不是产品终态。下一次 A008 必须同时证明
Claude 对 async Agent 使用同一 `TaskOutput`，且任何失去 lease 的旧 session 都无法改写
native evidence；在真实 `TERMINAL`、usage 和 machine evidence 完整前，发布继续阻断。

## final87 / final88：恢复平台漂移修复与真实 Developer 恢复链

- final87 暴露恢复路径的宿主平台漂移：Stop Report 明确记录 `claude-code`，但脱离原会话执行
  `dev-loop --resume` 时，当前外层 Codex 环境被重新探测为 `codex`，导致 Claude 传入
  `fresh_context` 时被 Hook 拒绝。T793 让恢复按“当前 lease → 同 Action Stop Report → 当前探测”
  绑定宿主平台，并允许 Claude 对已知的 `" may_drive_loop"` 键名复制误差做严格归一化；值、路径、
  hash 和额外文本仍 fail-closed。
- final88 在全新项目副本、Build `5.8.0-rc.5+sha256.01bdabe7d7d7be3b` 上真实证明：Claude
  `Agent` 成功返回 `async_launched`，主会话使用同一句柄 `TaskOutput`，Host Driver 固化 native
  result，Assembler/Finalizer/Validate/Tick 推进到 Developer；PII Guard 也真实拦截了形似凭据的
  测试夹具，并通过同 Action repair 继续执行。
- final88 随后证明跨会话 `SessionEnd → Stop Report → resume` 有效，Developer 真实完成 B1/B2
  测试工作并进入恢复态。但恢复态已是 `native_outcomes_ready`、`spawn_permitted=false`，Claude
  一次误把恢复 Action 当成新 Worker Action；Hook 正确拒绝，避免重复 Worker。宿主随后又误读 Hook
  拒绝原因并停止，最终只有 `HOST_RUNTIME_PROTOCOL_ERROR`/`HOST_AGENT_CAPACITY` Stop Report，
  没有 `TERMINAL`、usage 或 machine evidence。
- T794 已把 recovery 优先级写入统一 Action Prompt 合同：只要 `recovery.spawn_permitted=false`，
  就绝不能调用 Agent/Task/TaskOutput，只能使用当前 recovery work files 执行
  `finalize → validate → submit`；Hook 拒绝消息也明确指向 recovery 分支。该修复尚未在新的真实
  Claude L4 运行上验证，因此 A008 继续阻断发布。

## final89：候选制品与双宿主安装门禁

- final89 Build 为 `5.8.0-rc.5+sha256.486d26a72de30b00`；Ruff、mypy、compileall、规则同步和
  `git diff --check` 均通过，全量回归为 `3019 passed/1 skipped`，覆盖率 `90%`。
- Codex 与 Claude 两个宿主的 archive smoke 均通过，且均验证同一 Build ID；自动验收明确真实
  产品安装为 `not_run`，因此不能把 archive smoke 当作真实 L3/L4 终态。
- A008 下一步只允许在干净项目副本中用 final89 重跑真实 Claude recovery/L4；必须看到同一
  Action 从 recovery `finalize → validate → tick` 走到 `TERMINAL`，并由 evidence collector
  验证 usage、machine evidence、native-result 和业务 Gate。否则继续 fail-closed，不恢复第二套循环。

## final89 真实 Claude：Worker 已恢复，但终态仍被宿主与扫描边界阻断

- 首个 Claude 会话在 Architect 计划被 Core 拒绝后完成了同 Action repair；进入 Developer 时，
  Agent 因 `NATIVE_LAUNCH_PROMPT_MISMATCH` 被正确拒绝，未产生伪造 Worker 结果。Stop Report
  为 `CONTINUE`，lease 已清理。
- 第二个 Claude 会话按 Stop Report resume 同一 Action，成功完成两个 Developer native Worker，
  真实回写 native-result、Worker outcome、finalize、validate，并产生项目测试、type check、lint、
  build 结果；这证明跨会话恢复和同一 Action 继续有效。
- 随后 AuditGate 把项目内安装插件 `.ae-plugin/` 的源码当作业务源码，产生大量 P0，进入
  `GUARDRAIL_RETRY`。这是代码扫描边界缺口，已用回归测试先 RED 后 GREEN，Audit/Safety 现在统一
  排除 `.ae-plugin`；该修复尚未重新打包并重跑真实终态。
- Claude 在 `CONTINUE` 后反复输出“等待指令”，未继续调用 resume，宿主最终再次记录
  `HOST_RUNTIME_PROTOCOL_ERROR`/`CONTINUE`。Evidence collector 按合同拒绝：`TERMINAL_ACTION_MISSING`。
  因此 final89 仍是有效的部分成功证据，不是 A008 L4 通过。

## final90 真实 Claude：插件扫描修复有效，但暴露 Worker 结果合同边界

- final90 Build 为 `5.8.0-rc.5+sha256.c439b8ca4311d1b9`；T795 后完整回归为
  `3021 passed/1 skipped`，覆盖率 `90%`，Ruff/mypy/compileall/规则同步/diff check 和双宿主
  archive smoke 均通过。
- 全新项目副本上的真实 Claude 已完成 Architect Worker 和 Developer Worker，未再触发
  `.ae-plugin` 扫描误报；这证明 T795 修复命中了 final89 的真实根因。
- Developer Worker 发现 Voice Clone 业务缺陷：`VoiceResult.tsx` 仍读取 `result.id`，而 API
  合同使用 `voice_id`。该文件不在当前 batch `file_targets`，Worker 没有越权修改，而是把失败放入
  `red_evidence`；但同时返回 `test_results.failed=1`，Core 按 Developer 合同正确拒绝为
  `HOST_WORKER_OUTPUT_INVALID`（合同要求 `failed=0`）。
- Claude 随后尝试直接修改私有 Worker outcome，把失败改成 `failed=0`；该方向违反“私有 outcome
  是唯一业务事实、Coordinator 不得伪造”的底线，已停止会话。没有 `TERMINAL`、usage、machine
  evidence，A008 继续阻断。下一步应修正 Worker/Developer 结果契约的失败归属与同 Action repair
  语义，而不是放宽 `failed=0` 或允许手工改 outcome。

## final91：失败事实合同加固后的候选制品

- T796 已将 `test_results.failed/errors` 明确纳入统一 Spawn 合同：Worker 发现测试失败时必须
  保留原始私有 outcome、以 `status=failed` 回写并走失败/终结边界；Coordinator 不得编辑私有
  outcome，也不得把失败改成 0。新增合同回归与全量验证均通过。
- final91 Build 为 `5.8.0-rc.5+sha256.8b5010f91439dbba`；全量 `3022 passed/1 skipped`、
  覆盖率 `90%`，Ruff/mypy/compileall/规则同步/diff check 通过，Codex/Claude archive smoke
  均通过。真实产品安装和 L4 终态仍未通过，A008 继续阻断。

## final92：业务失败自动归类与真实 Claude fail-closed 复验

- T797 将 Worker 业务产物中的 `test_results.failed/errors > 0` 收敛到唯一 Host
  `record → outcomes → finalize` 路径：宿主把 outcome 投影为 `status=failed`，保留私有
  outcome 原文，不要求 Coordinator 将失败改为 0；完整共享失败事实不会再次被恢复投影误判为
  `worker_attestation_pending`。新增 Assembler 回归和公开 CLI E2E 验证同一 Action 进入
  `HOST_WORKER_FAILED → WAIT_RESOURCE`，全量 `3024 passed/1 skipped`，覆盖率 `90%`。
- final92 Build 为 `5.8.0-rc.5+sha256.e47916b485516791`；Ruff、mypy、compileall、规则
  同步、diff check 和 Codex/Claude archive smoke 均通过，两个宿主的 Build Identity 一致。
- 全新项目中的真实 Claude 已先因临时项目 `uv run` 包构建声明不一致进入三次 Setup 失败，Core
  正确返回 `WAIT_RESOURCE/PROJECT_SETUP_RETRY_EXHAUSTED`，恢复仍返回同一等待 Action；随后
  它进入 Architect，但试图以 `completed + unreported` 回写 Worker，收到
  `HOST_EVIDENCE_INVALID/WORKER_STATUS_CONFLICT`，共享 outcomes 未写入。宿主之后尝试绕过
  失败协议直接写 outcomes/调用非合同 CLI，已被 Hook 或本地运行时边界阻断，人工停止会话。
  这证明 final92 的失败事实和 fail-closed 边界有效，但不是 L4 成功；没有 `TERMINAL`、usage
  或完整 machine evidence，A008 继续阻断。
- 同一 final92 通过 Codex 原生 `codex exec` 在全新空项目做了负向 Setup 复验：它按合同完成
  `finalize → validate → tick`，修复了缺失的 `artifacts` 字段，但因项目没有设计、源码和
  工具链证据而保持 `project_setup_required/CONTINUE`，未猜测技术栈、未启动 Worker、未到
  `TERMINAL`。这是 Setup fail-closed 证据，不是有效 L4；该空项目不具备 A008 Voice Clone
  业务验收条件，不能计入双宿主终态。

## final93：新制品双宿主复验后的真实分叉

- final93 Build 为 `5.8.0-rc.5+sha256.f5118a6b753e54a6`。全量回归为 `3026 passed/1 skipped`，
  覆盖率 `90%`；Ruff、mypy、compileall、规则同步、`git diff --check` 均通过。Codex 与 Claude
  archive smoke 均通过，并确认相同 Build Identity；这只是制品门禁，不等价于真实产品 L4。
- 真实 Claude 在全新 Voice Clone 副本中完成 Gap Scan、Architect、Developer、Critic，并到达
  `TERMINAL/GOAL_ACHIEVED`。但 Core 的验收摘要仍标记 `product_business_acceptance` 为未验证，
  且没有可供 collector 接受的业务 recovery/machine evidence；因此不能把该终态报告为 A008
  发布通过。
- 真实 Codex 使用安装后的 final93 runner 在全新 Voice Clone 副本中运行。Architect 计划被
  Core 拒绝后，完成同 Action 修复；Developer 首次失败后按同一 Action、有新 generation 和
  fencing 身份进行有界重试。重试仍返回真实测试失败（包括 `VoiceClonePage` 的 `voice_id`
  契约问题及错误脱敏测试失败），Host 将其归类为 `HOST_WORKER_FAILED` 并进入
  `WAIT_RESOURCE`，保留 active Action，没有创建第二个 Coordinator、没有伪造 `failed=0`，
  也没有第三次盲目重跑。这证明 final93 的失败收敛和资源恢复路径生效；当前阻断点是样例项目
  的业务契约/测试证据与产品 acceptance，不是 Python Loop 被意外中断。
- Codex 首次 final93 尝试因宿主尚未切换到新插件缓存而使用旧实现，已明确排除，不计入证据；
  随后安装并复核 final93 后才进行上述有效复验。A008 仍需在同一候选制品上闭合双宿主业务
  acceptance、usage 和 machine evidence，才能解除发布阻断。

## final93 同 Action 恢复：失败收敛正确，但交接仍有第二个缺口

- 按 Codex `WAIT_RESOURCE` Action 的 `resume_active_action` 合同重新启动宿主，没有新建
  Coordinator，也没有编辑私有 Worker outcome。Worker 真实返回 `22/23`，宿主先按合同登记
  业务失败，随后补交原生 attestation。
- Core 在 `finalize → validate → submit` 阶段又得到
  `HOST_WORKER_OUTPUT_MISSING`，最终返回稳定错误
  `ERROR/HOST_WORKER_FAILURE_EXHAUSTED`。宿主退出报告为“未发现活动宿主租约”；随后只读
  `--status` 仍能定位原 active Action，恢复操作仍绑定原 `thread_id/message_id`，没有发生
  第二套循环或隐式推进。
- 这次结果把问题进一步分层：Core 的失败预算、有界恢复、generation/fencing 和禁止伪造均按
  设计工作；剩余缺口是 Codex 恢复过程中“业务 outcome、原生 attestation、共享 outcome 与
  finalizer”之间的原子交接没有在第二次尝试保持一致。下一步应增加该交接的真实回归并修复
  宿主适配器，不能把 `HOST_WORKER_OUTPUT_MISSING` 改成成功，也不能通过清空失败次数绕过。

## final94：Codex wait 回包修复生效，阻断点转为业务批次证据

- final94 Build 为 `5.8.0-rc.5+sha256.44ea01a8bf78f064`；全量 `3027 passed/1 skipped`、覆盖率
  `90%`，Ruff、mypy、compileall、规则同步、`git diff --check` 及双宿主 archive smoke 均通过。
- 在干净 Voice Clone 副本中，Codex 真实完成 Gap Scan、Architect 和 Developer Worker。两次
  Worker 都按 `record-worker-outcome → close/reclaim → finalize → validate` 回写；Codex
  wait 返回的外层 `status` 包装没有再被当作 native envelope，未出现 final93 的
  `HOST_WORKER_OUTPUT_MISSING`/attestation 交接错误。
- Developer 返回 `13/13` 测试通过，但当前 B1 批次没有新的工作树、暂存区或授权 commit 变更。
  Core 因此返回 `GUARDRAIL_RETRY/CONTINUE` 并保留同一 active Action；宿主没有伪造变更、没有
  重复 spawn，也没有推进到 `TERMINAL`。当前剩余问题是样例业务批次/验收证据不足，不是 Loop
  驱动器异常中断。

## final95：修正 L3/L4 证据错误耦合

- 真实 Claude final93 已到达 `TERMINAL/GOAL_ACHIEVED`，但业务证据生成器仍要求同一个 L4
  EventStore 存在唯一 recovery Action，因而返回 `RECOVERY_ACTION_NOT_UNIQUE`。这不是业务 Gate
  失败，而是验收分层实现违背了 v5.8 的 L3/L4 设计。
- T800 将 `generate_business_evidence.py` 收敛为只执行并绑定 L4 的 typecheck/unit_test/build
  三项 Gate；`collect_product_evidence.py` 新增强制 `--canary-project-root`，从独立 L3 项目
  EventStore 推导 Architect/Developer/Critic 和唯一 recovery projection。没有默认回退到 L4
  根目录，避免隐式双语义。
- 新增“L4 无 recovery 也可通过、L3 无/多 recovery fail-closed、双根端到端采集”的回归；当前
  先完成代码和质量门禁，再用同一候选 Build 重新跑独立 L3 Canary 与 L4 Voice Clone，A008 仍未关闭。
