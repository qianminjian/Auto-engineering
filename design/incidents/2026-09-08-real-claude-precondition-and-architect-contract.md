# 2026-09-08 真实 Claude 复验：首轮前置条件与 Architect 合同错配

## 结论

这次“才一跑就崩”不是单个模型偶发失误，而是多个边界没有在首个 Worker 之前闭合：

1. 宿主启动参数曾同时使用 `--disable-slash-commands` 和 `/auto-engineering:dev-loop`，直接关闭了要调用的 Skill。
2. Project Setup 的安全分类只识别少数标记，合法的 `toolchain`/smoke 占位文件被误判为业务实现，宿主因此反复修复。
3. 设计文档缺少 H2/H3/`ae` 层次时，Core 到 Gap Scan 才发现前置条件；模型未按提示输出 architectural gap 时，错误被变成昂贵的同 Action 反馈。
4. Architect 的 Core 校验要求 `kind/module_ref/file_targets/depends_on`，但 Prompt 示例和 `expected_format` 没有完整表达同一结构，导致 Worker 结果在后续覆盖/拓扑校验处反复拒绝。

## 真实证据

- 新鲜 Claude L3 已通过安装身份预检，并从 `project_setup → gap_scan → architect`，说明入口、插件加载和前两阶段已真实接通。
- 使用扁平设计文档时，Setup 已通过，但 Gap Scan 返回 `GAP_SCAN_DESIGN_STRUCTURE_INVALID`；这证明设计结构门禁生效，但发现时机和失败呈现仍不够好。
- 使用有 H2/H3 的最小设计文档时，已到 Architect；同一 Action 因 `ARCHITECT_RESULT_COVERAGE_INVALID` / 结果字段修复失败而有界停止，未伪造成功、未重复启动 Worker。
- 之前的质量基线仍有效：全量 `3115 passed, 1 skipped`、覆盖率 `90%`、Ruff、mypy、compileall、`git diff --check` 和 `make check-gate` 通过；这些只能证明 Core 回归，不等于真实产品 L4。

## 为什么此前没有挡住

设计已经覆盖了“拒绝错误结果、同 Action repair、宿主有界退出”，但没有把所有失败都按发生层级前移：

- 启动合同是宿主 CLI 层的组合约束，Core 测试无法发现宿主命令参数自相矛盾。
- Setup 安全范围是“允许集合”，但实现只维护了窄的正则/文件名白名单，新增一种合法 smoke 写法就落入错误分支。
- 设计结构是输入前置条件，却依赖 Gap Scan 模型自己发现并正确表达；缺少启动前可执行预检和明确的用户交接状态。
- Architect 的提示、`expected_format`、运行时 Schema、Core Validator 曾分别描述任务结构，存在“人看到的样例”和“机器真正接受的结构”不一致。

## 已完成的修复

- `ae-host-run` 在启动前拒绝禁用 Skill 与调用 Skill 的矛盾参数。
- Project Setup 统一 `AE_SETUP_SMOKE`、最小 setup/toolchain smoke 标记和测试命名规则，并增加安全文件回归。
- Runbook/Skill/Command 明确扁平设计必须输出 architectural gap；无结构设计不得伪装为 clear document。
- Architect Prompt 和运行时 `expected_format` 统一任务模板，显式要求 `kind`、`module_ref`、`file_targets`、`depends_on`。
- 宿主已有最大运行时长、空闲超时、协议拒绝熔断、Coordinator 轮询上限和语义修复上限；失败保留 active Action/lease，不再无限续跑。

## 仍需完成的 P0

1. 把设计结构检查前移为确定性 preflight；不满足 H2/H3/`ae` 层次时直接产生可提交的 `WAIT_USER`/设计修复合同，禁止先启动 Worker 再靠模型自救。
2. 把 Architect 任务模板提升为一个可复用的 machine-readable contract，Prompt、Result Schema、Validator 和 repair feedback 只引用这一份定义。
3. 为“扁平设计、Setup 合法 smoke、Architect 完整计划、错误结果有界停止”补齐公开 CLI 纵向回归，并用新安装制品重新跑双宿主 L3/L4。
4. 将产品报告明确分成 `Core TERMINAL`、`host lifecycle complete`、`business acceptance pass` 三层，任一层缺失都不得报告为完成。

## 用户可理解的判断

系统现在已经能阻止多种错误继续污染状态，但“能拒绝”不等于“能在正确的地方、第一次就拒绝”。本次真正暴露的是前置条件、提示合同和宿主边界之间仍有多处重复定义。下一步不是继续增加重试次数，而是减少重复定义、前移可确定判断、让不可恢复错误直接交给用户或有界停止。

## 2026-09-08 现场复盘补充：恢复身份与等待语义仍有同类缺口

对 Voice Clone 项目的 EventStore、Host Runtime 和 `docs/auto-engineering-loop-report.md` 做只读核对后，发现现场不是 Core 状态机崩溃，而是“活动 Action 已签发，但宿主交接事实没有闭环”：

- EventStore 已推进到 `developer` tick 5，并保留 `CONTINUE` active Action；该 Action 没有任何新的 Worker/native outcome 文件，宿主进程也不在当前进程列表中，因此用户看到的是悬挂而不是可解释的等待。
- active lease、Action 的 `thread_id/action_message_id` 能对应，但它们仍绑定旧 Build Identity `5.8.0-rc.5+sha256.f46d72d68586709b`；当前源码入口已经是另一个 Build Identity。此前恢复决策没有把“租约身份”和“当前 active Action 身份”做三方严格校验，也没有把旧制品状态清楚标成需要恢复/迁移。
- 自动续驱动原先只判断 `CONTINUE + active_action`，没有同时核对 status、resume operation 和 lease 的 thread/action 身份。该缺口现已改为 fail-closed，并增加旧租约/缺字段回归。
- Codex 第三次普通 `running` wait 原先被代码改写成 `timed_out`，与 Skill/Command 的既定合同冲突；现已改为 `unknown + owner_known=false`，要求确认 Worker 所有权后再取消或进入 `WAIT_RESOURCE`，不得直接失败、重启或让出 `CONTINUE`。

这说明类似问题的共同模式是：**业务状态、宿主状态、恢复身份、时间预算分别有防线，但缺少一条不可拆分的完成判据**。以后必须把一次 Worker 完成定义为：同一 Action/generation/fence 下，原生终态、业务 outcome、宿主 attestation、Coordinator payload、Finalizer、validate、tick 全部完成；任何中间状态只能显示为恢复态，不能显示为成功，也不能被普通超时升级为失败。

## 2026-09-08 入口与状态可见性补充

本轮核验没有把错误调用方式误报为产品故障：`scripts/ae-run` 是 POSIX launcher，必须直接执行，不能写成 `uv run python scripts/ae-run`。同时确认旧项目的 `CONTINUE` Action 与当前运行时 Build Identity 不一致；此前 `dev-loop --status` 只显示可继续，没有把这个审计事实投影给用户。现已增加 Action/当前 Build Identity 的 `match/mismatch` 状态投影，并为 `scripts/ae-run`、`bin/ae-run`、`scripts/ae-host-run` 及其内嵌 watchdog 增加真实解析回归。Build Identity 仍按 D23 作为审计字段，不在本次补丁中擅自改成兼容阻断；但 mismatch 不能再被隐藏或误报为干净续作。

## 2026-09-08 真实 Codex Canary：嵌套 Host Adapter

使用同一内容寻址候选包、干净项目和真实 Codex CLI 验证时，首轮因 `/tmp` 写权限被环境阻断；改用仓库 `_scratch` 和显式宿主权限后，真实轨迹已完成 `project_setup → architect → gap_scan → gap_review`，并在 `WAIT_USER` 正常让出。继续提交推荐决策后，Codex Skill 又启动了内层 `ae-host-run`，外层已经存在适配器，但环境变量和输出路径均被内层重新构造，导致原有两道嵌套保护都可绕过。进程树确认外层与内层 watchdog 同时存在，属于 P0 级“第二套恢复循环”风险；本次已正常中断，未把半成品 Architect Result 计为通过。

修复为项目级 `.ae-state/host-runtime/.adapter-lock` 原子目录锁：同一项目只允许一个 Host Adapter，锁绑定 PID、异常残留只在 owner 已退出时清理；同时修复 `--project-root/--output` 相对路径在切换 cwd 后被二次拼接的问题。新增回归覆盖环境变量清理、不同 output 路径、相对路径和真实内嵌 watchdog 解析。后续必须用包含该锁修复的同一候选重新跑真实宿主，不能沿用本次被中断轨迹关闭 L3/L4。

## 2026-09-08 真实 Codex Hook Wire 复盘：本地 deny 不等于宿主 deny

随后对“Architect 可以直接用 `apply_patch`/Bash 改写 `.ae-state`”做了最小真实 Codex 复验，发现此前 Hook 代码虽然在 Python 单测中返回了 `decision=block`，但实际返回对象混入了宿主 Schema 不允许的内部字段：PreToolUse 顶层的 `reason_code`、`permissionDecision`，以及 Stop 顶层的 `action_message_id`、`continuation` 等。Codex 的 PreToolUse Wire Schema 是严格对象，宿主将这类响应判为无效后继续执行工具，因此出现“防线代码在、危险写入仍发生”的结果。

这不是模型偶发失误，而是验收层级缺失：此前只测了 Python 函数语义，没有测真实宿主解析；安装验收也只证明插件路径和 Python runtime，没有证明宿主真的执行并采纳 Hook 响应。类似风险还包括相对 cwd 下的项目 Hook 路径、旁路 CLI 输出旧协议、Stop 事件继续保护输出旧协议。

本轮修复与证据：

- Codex PreToolUse 只输出官方允许的 `systemMessage` 与 `hookSpecificOutput`，Stop 只输出 `continue=false`、`stopReason`、`systemMessage`；内部错误码不再污染宿主 Wire。
- `native_launch_guard` 的 Codex 旁路入口与主 Hook 使用同一严格输出约束；Claude 旧协议仅保留在 Claude 边界。
- 项目 Hook 改为从 Git 根解析脚本，避免从子目录启动时相对路径失效。
- 安装器新增已安装制品的 Hook Wire Contract 预检；归档集成测试覆盖一次真实 PreToolUse deny；真实 Codex CLI 已验证危险 Bash 未执行、目标文件保持不变。
- 本次最小真实回归的关键证据是：修复前目标文件由 `before` 变为新内容；修复后仍为 `before`，Codex 事件明确记录 `Command blocked by PreToolUse hook`。

结论：宿主 Hook 只能作为工具边界的第一道防线，不能把内部诊断结构直接塞进宿主响应，也不能用“脚本可执行”代替“宿主采纳了阻断”。今后每个宿主事件必须同时具备 Wire Schema 单测、归档制品测试和真实产品阻断证据；缺任一层都不能关闭 L3/L4。
