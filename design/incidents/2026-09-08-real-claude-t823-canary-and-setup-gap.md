# 2026-09-08 T823-T829 真实 Claude Canary 与宿主/Setup 构建恢复合同缺口

## 结论

- T823 制品 `5.8.0-rc.5+sha256.e443bbe3e47a4b0b` 已完成 Codex/Claude 用户级 Marketplace 重装；两个 archive smoke 均通过。
- 全新项目上的真实 Claude Canary 已从 `project_setup → gap_scan → architect → developer → critic` 到达 `done/APPROVE`；生成了原生 stream、Worker outcome、observation、receipt、EventStore 和最终 `LoopCompleted`。
- 该次 Canary 全程一次成功，没有产生同 Action recovery 事实。产品验收器返回 `CANARY_RECOVERY_NOT_UNIQUE` 是正确的 fail-closed：只能认定 L3 通过，不能把普通成功冒充恢复能力或 L4。
- 第二次强制 recovery Canary 暴露了项目 Setup 的另一个缺口：模型生成的 Python `pyproject.toml` 使用 Hatchling，但没有 wheel package 映射，bootstrap 报 `Unable to determine which files to ship`。适配器在有界窗口后生成 `HOST_PROCESS_TIMEOUT` Stop Report 并保留 active Action，没有裸 traceback 或第二个 Coordinator。
- T827 新鲜 Claude Canary 又暴露了退出事实顺序缺口：Claude 真实输出了 `API Error: Stream idle timeout - no chunks received`，但 `StopFailure` Hook 先清理 lease 并写入 `reason=unknown`，使外层 process-exit bridge 无法读取完整 attempt 输出，最终报告错误地退化为 `HOST_RUNTIME_PROTOCOL_ERROR/unknown`。
- T828 已将外层适配器设为退出事实唯一写入者，并将该上游故障归一为 `HOST_PROVIDER_STREAM_IDLE_TIMEOUT`；该故障仍保留同一 active Action 的恢复合同，不被误判为成功或无原因崩溃。
- T829 调试期间使用上一版 T828 Build 执行真实 Recovery Canary，发现 Claude 持续输出 `thinking_tokens` 但 Core 约 16 分钟没有语义推进；适配器原先把传输层心跳误当作 liveness，导致 300 秒 idle 边界不触发。本次试验按 15 分钟无语义进展规则正常中断，Stop Report 为 `HOST_PROCESS_INTERRUPTED`，未伪造成功。
- T830 使用最终 T829 Build 的真实 L3 Canary 继续暴露了 Recovery 边界缺陷：同一 Architect Action 的 Worker 事实在多次 repair 后，`assembly_rejected` Journal 可能分别沿用旧 `outcomes` 和旧 `outcomes_fingerprint`，形成不可恢复的指纹失配；最终表现为 `OUTCOME_JOURNAL_OUTCOMES_FINGERPRINT_MISMATCH`，而不是业务结果错误。
- T830 已将 Journal 修复为“只成对保留经过校验的 outcomes 与 fingerprint；失配旧对不再复制，若当前有新鲜验证事实则用当前事实重建”，并补充失配重建回归测试。该修复尚未重建最终发布制品，故不能把本次 Canary 计为新 Build 的 L3/L4 成功。

## 根因与边界

这不是 Core 把 Python 重新变成任务驱动器，也不是旧 Supervisor 回流。主链仍是宿主 Agent → 单 Tick/EventStore → Host Adapter → 原生 Worker。

问题在于 Setup 合同只要求“建立工具链并通过 Gate”，对 Python `build-system`、包目录和 Hatch wheel 映射的组合约束没有在前置配置层明确验证，导致错误在 bootstrap/构建阶段才暴露；同时真实 L4 验收要求 recovery，但普通成功轨迹天然不会自动产生 recovery 证据。

T825/T826 的真实验证又确认了一个更直接的循环缺口：达到 `resource_wait` 后，`project_setup_completed` 仍被当作恢复信号，哪怕项目输入完全没有变化。由于每次 action-scoped outcome 都是真实宿主活动，watchdog 不应将其判为空闲；但 Core 也不能因此持续生成 repair Action。原设计有失败次数上限，却没有把“环境已改变”定义成恢复前置条件，这是“有界失败”在实现上被绕开的根因。

## 设计对标与同类风险排查

| 设计底线 | 原实现状态 | 本次处理 | 当前证据 |
|---|---|---|---|
| 业务 Worker 前必须完成 Project Setup | 只有依赖同步通过，包装错误可延后到业务阶段 | ProjectProfile 增加 PEP 517/Hatchling 静态前置门禁；Setup 未完成不得派发 Worker | `python_packaging` 回归与 `uv build` |
| 构建证据必须是真实可发布产物 | Python Profile 默认只跑 `compileall` | 合法 regular package 改为 `uv build`；脚本项目保留 `compileall` | 项目 Profile/Setup 测试 |
| 运行态不得污染发布制品 | `.ae-runtime` 曾可进入 sdist | Hatch sdist 强制排除状态、运行时、虚拟环境和构建目录 | sdist/wheel 内容检查 |
| wait/liveness 不能误杀正常 Worker | watchdog 假设单一 ISO 时间格式 | 兼容 macOS BSD 时间格式，并绑定 Action、generation、fence | host watchdog 回归 |
| 失败恢复不得产生第二个协调者 | 该原则已写入设计，但历史方案容易被误读为运行时后备 | 当前运行树加禁入检查；旧 Supervisor 只保留历史/迁移文档 | `check_host_package.py`、架构回归 |
| L3 成功不能冒充 L4 recovery | 普通成功轨迹没有 recovery 事实 | 验收器保持 fail-closed，Recovery Canary 单独作为发布门禁 | `CANARY_RECOVERY_NOT_UNIQUE` |
| `resource_wait` 恢复必须有环境变化证据 | `allow_recovery=True` 可被未改变的 completed 结果反复触发 | T826 增加项目内容指纹；未变化时原样返回同一等待 Action，变化后才允许一次重新验证，并经 EventStore 持久化 | Setup 重复完成回归 + EventStore 投影回归 |
| 退出事实必须由拥有完整输出的一方写入 | Hook 先于外层 bridge 清 lease，丢失 attempt stream 中的 provider 错误 | T828 让外层适配器在场时 Hook 只返回；bridge 从 `result/text/content` 识别有限错误码，collector 接受受控 Stop Report 集合 | process-exit/Claude Hook/collector 回归 + T827 真实 stream |
| thinking-only 流不能伪造宿主活跃 | Claude 连续输出 `system/thinking_tokens`，但没有 Assistant/Tool/Result 或 Core 进展 | T829 保留原始流但仅让语义事件刷新 idle；thinking-only 超过边界必须触发 `HOST_PROCESS_IDLE_TIMEOUT` | 宿主边界回归 + T829 真实 attempt |
| assembly repair 的 Journal 指纹必须成对一致 | 多次修复可能复制旧 `outcomes` 与旧 `outcomes_fingerprint` 的失配组合，导致每次 finalize 都重复失败 | T830 只保留通过重算校验的旧事实对；失配时使用当前已验证 facts 重建，禁止继续传播损坏 Journal | Journal 回归 + T829 最终 Build 真实 Canary 复现 |

本次问题的共同模式不是“循环次数太少”，而是“边界验证太晚 + 宿主事实格式假设过窄 + 失败类别没有在唯一状态机中及时分流”。今后凡是新能力都必须回答三个问题：业务 Worker 是否已被前置 Gate 放行、宿主事实是否可验证且带完整身份、失败后是否仍由同一个 Action 和唯一 Coordinator 恢复。

## 已验证修复

1. Core 与 Host Assembler 的同 Action 语义修复预算已封顶；耗尽后返回 `HOST_RESULT_REPAIR_EXHAUSTED`，不再无限提交同一候选、不再启动新 Worker。
2. Architect 的 `OBLIGATION_UPDATE_REQUIRED` 返回可执行 `plan_patch.obligation_updates` 指引，保留历史义务，不重写既有 `source_ref`。
3. 宿主 watchdog 不再把 lease 重写、相同 Result 重写或 stale running 当作业务进展；真实首个 Canary 已证明普通终态可收口。
4. T824 已将 Python regular package 的 PEP 517/Hatchling 契约前移到 ProjectProfile；合法配置才使用 `uv build`，并强制 sdist 排除 `.ae-state`、`.ae-runtime`、`.venv`、`dist`、`build`、`_scratch` 和缓存目录。
5. T824 同时修复 macOS BSD `date` 的纳秒与无冒号时区格式解析，避免合法 `running` observation 被 watchdog 忽略。
6. T825 修复外层适配器的用户中断路径：先经 canonical process-exit bridge 写入
   `HOST_PROCESS_INTERRUPTED` Stop Report，再退出并清理租约，避免中断后只剩 active Action 而没有停止事实。
7. T826 修复 Setup 恢复绕过重试上限：Core 对项目输入（相对路径、普通文件内容、内部 symlink 目标）计算 SHA-256；进入 `resource_wait` 时记录指纹，后续只有指纹变化才能重新发出 Setup Action，否则保持原等待 Action，不递增失败次数、不制造假进展。
8. T828 修复退出事实竞态：`AE_HOST_ADAPTER_ACTIVE=1` 时 Claude `SessionEnd`/`StopFailure` Hook 不再清理租约或生成 Stop Report；process-exit bridge 读取完整 attempt 输出，并将 `Stream idle timeout` 归一为 `HOST_PROVIDER_STREAM_IDLE_TIMEOUT`。证据收集器使用受控错误码白名单，不再把合法的具体宿主故障报告当作损坏证据。
9. T829 修复 liveness 分类：Claude `system/thinking_tokens` 仍写入原始 attempt stream，但不再刷新 idle deadline；assistant/tool/result 语义记录和 Action-scoped 状态事实继续刷新。新增持续 thinking-only 的宿主边界回归，确认 idle 超时优先于总时长超时。
10. T830 修复 Outcome Journal 的成对一致性：assembly repair 不再独立继承旧 outcomes 或旧 fingerprint；每次写入前重算并校验二者关系，失配旧记录不能继续污染后续 finalize。

## 后续动作

- 在 T828 Build 上执行受控 Recovery Canary，确认 Setup 已先于业务 Worker 发现包装缺口，且同 Action recovery 证据由宿主/Core 自然产生；若未发生项目输入变化，必须观察到稳定 `resource_wait`，不得出现新 repair Action。
- 将 L3 Canary 拆成“正常终态”和“受控 recovery 终态”两个独立真实场景；recovery 必须由宿主/Worker/Core 自然产生，禁止手工改 Result、Journal、EventStore 或证据。
- 保留本次真实终态作为 L3 证据；在 recovery Canary 和 Voice Clone 业务 Gate 完成前，A008/L4 发布门禁仍保持未关闭。

## 完成边界

本次 T824 已完成的是工程防崩修复，不等于产品目标已完成。自动化测试、archive smoke 和真实 Claude L3 只能证明协议与宿主支撑能力；只有最终 Build 上受控 Recovery Canary、Voice Clone 业务场景以及 Codex/Claude 双宿主产品级 `TERMINAL` 证据全部成立，才允许关闭 P0-E2E。

## 证据

- T829 全量回归：`3184 passed, 1 skipped`；覆盖率 `90%`。
- T827 Build `5.8.0-rc.5+sha256.3dfdf50aba66e487` 的 archive smoke 作为历史证据保留；T828 Build
  `5.8.0-rc.5+sha256.ca0c87dc8e8a4401` 已完成 Codex/Claude Code archive smoke、安装后验收和身份预检。
- 根项目真实 `uv build` 已通过；sdist/wheel 均未包含 `.ae-state`、`.ae-runtime`、`.venv`、`dist`、`build`、`_scratch` 或缓存路径。
- `make check-gate`、Ruff、mypy、项目 Python compileall、`git diff --check`：通过。
- watchdog 空闲超时和用户中断回归：通过；用户中断会生成唯一 Stop Report 且清理租约。
- 真实 Claude L3 项目：`/tmp/ae-a008-l4-t823.e3iLzW`；产品 evidence 因缺少 recovery 事实而未通过，未将失败伪装成通过。
- Recovery Canary：`/tmp/ae-a008-recovery-t823.C4C0C1`；Stop Report 明确为 `HOST_PROCESS_TIMEOUT`，`lease_cleared=false`，下一操作为同一 active Action 的 `resume_active_action`。
- T826 真实 Claude Setup Canary：`/tmp/ae-t826-product.eZ4xyZ`；同一 Build 连续接受 4 个
  `project_setup_completed` outcome，实际生成并检查了 `uv build` 的 wheel/sdist，最终因
  packaging 排除契约仍不完整稳定进入 `resource_wait`，未生成无界 repair Action，且宿主进程
  已退出、租约已清理。该证据证明 Setup 防循环和真实打包前置门禁有效，但没有业务 Worker 或
  `TERMINAL`，不计作 L4。
- T827 真实 Claude Setup Canary：`/tmp/ae-t827-product.wIdZKC`；真实 stream 产生 26 turns、
  最终 `terminal_reason=api_error` 和 `result=API Error: Stream idle timeout - no chunks received`，
  但旧 Build 的 Stop Report 为 `HOST_RUNTIME_PROTOCOL_ERROR/unknown`。该证据证明上游错误真实存在，
  也证明旧实现丢失了退出原因；T828 回归固定为具体稳定码，未将此运行伪装成成功。
- T828 修复后制品：Build `5.8.0-rc.5+sha256.ca0c87dc8e8a4401`，内容 SHA-256
  `ca0c87dc8e8a44016c70b52f9020b221c378dda598ec339ead4cf37c9a94fca8`，archive SHA-256
  `b24873eedc23eff2df8fc8214dc5e67858d622260b3907a60cd1d063ee409622`；Codex/Claude
  archive smoke、安装后验收和身份预检均通过。当前真实产品 L4 仍未声称通过。
- T829 修复后制品：Build `5.8.0-rc.5+sha256.d66086c01a49fd3c`，内容 SHA-256
  `d66086c01a49fd3c3b5dc1cec43a57523913bd030b725e3094fe5ab0cd9da5c1`，archive SHA-256
  `6166d7ec3e4da35f5d64014f23e9213f08c16b9714213391e712a78830792ee1`；Codex/Claude
  archive smoke、安装后验收和身份预检通过。T829 新 Build 的真实产品 L3/L4 仍未声称通过。
- T829 最终 Build 真实 Recovery Canary：`/tmp/ae-t829-final-l3.Q7HDBC`；实际越过
  `project_setup → gap_scan → architect → developer → critic`，并持久化多个原生 Worker
  结果。随后在同一 Architect Action 的 repair 中复现 `OUTCOME_JOURNAL_OUTCOMES_FINGERPRINT_MISMATCH`；
  Stop/人工中断路径未将该运行伪装成成功，active Action 仍保留供修复。该证据只证明缺陷可复现，
  不计作新制品 L3/L4 终态。
- T830 修复后自动化回归：`3185 passed, 1 skipped`；Outcome Journal/Host Assembler 定向
  `101 passed`；覆盖率 `90%`；Ruff、mypy、compileall 和 `make check-gate` 通过。
- T830 修复后制品：Build `5.8.0-rc.5+sha256.fef0f901fb8dee8f`，内容 SHA-256
  `fef0f901fb8dee8fa772c99bd17e9973caeff9b4a8721209227804d3e5a0d3cd`，archive SHA-256
  `26e02e45e5b70efadc2064889a480641f76ee0808c614b5d848525f07787d5ec`；Codex/Claude
  archive smoke、双宿主本地安装和 Build Identity 预检均通过。真实产品 L3/L4 仍未声称通过。
- T831 新鲜 T830 Build Recovery Canary：`/tmp/ae-t830-final-recovery.ka4AYg`；运行越过
  `project_setup → gap_scan` 并完成 Architect 原生 Worker，但 Architect 计划按 TDD 将测试
  与实现放入连续两个 batch，Core 依据“测试不得导入未来实现”规则拒绝
  `ARCHITECT_TEST_IMPLEMENTATION_ORDER_INVALID`。根因是 Prompt 同时表达“测试先行、实现后置”
  与“实现必须同一或更早 batch”，没有明确“会导入实现的测试与实现必须同 batch”。模型随后
  反复修复/重启 Architect，看似 loop 崩溃但实际是契约矛盾和缺少精确修复指令。T831 已修订
  Architect Prompt、提取 Architect 修复提示单一模块，并增加跨 batch 拒绝、同 batch 接受、
  同 Action 不重新 spawn 的回归测试；人工正常中断后 Stop Report 为
  `HOST_PROCESS_INTERRUPTED`，租约已清理，无后台进程。该次不计作 L3/L4 终态。
- T832 复验使用 Build `5.8.0-rc.5+sha256.ec3f74ede384778d`，根目录
  `/tmp/ae-t831-final-recovery.soqjvT`。首次 setup Action 长时间连续发出 Bash 工具调用，
  Core 状态在同一 Action 内没有语义推进；watchdog 的 `has_meaningful_stream_activity`
  将这些 tool_use/tool_result 当作活跃，因此重复诊断绕过了 5 分钟 idle 上限。中断时未写入
  业务 Result，现场保留 setup 状态和 Stop/lease 事实；这证明当前还不能宣称 L3/L4。T832
  的修复目标是让重复工具调用、工具回执和 thinking-only 流不能刷新 idle，只有 Core/Host
  Action-scoped 状态变化或合法终态事件可以刷新观察窗口，并为该行为补宿主回归测试。
- T832 修复后制品：Build `5.8.0-rc.5+sha256.b9949b69d718f0b9`，内容 SHA-256
  `b9949b69d718f0b9f118bebb627ad9c475700d7ea08a0de8a153926a78b2d72f`，archive SHA-256
  `96efcd689ac578b70e70eacb83167421256fe507aa783308c311a51f6cd9aa22`；Codex/Claude archive
  smoke、双宿主本地安装和 Build Identity 预检通过。安装目录中的 adapter 以重复 Bash
  `tool_use` 假宿主复验，实际返回 `HOST_PROCESS_IDLE_TIMEOUT`（exit 143）并生成 Stop Report，
  证明 T832 已进入 packaged runtime。该结果只证明空转熔断，不构成真实 Voice Clone L3/L4 终态。
- T833 复验制品：Build `5.8.0-rc.5+sha256.b381f10340d8aee9`，内容 SHA-256
  `b381f10340d8aee9004a513e5ba5556089ccb8095c584cc8f63f6612ac04ea19`，archive SHA-256
  `219bb3f4e7c02a70bd49f848ab7c60057ea43bfb0e4b81923b31f6e96a757d67`；Codex/Claude archive
  smoke、双宿主本地安装和 Build Identity 预检通过。从归档解出的 adapter 以重复
  `tool_use` 假宿主复验，实际返回 `HOST_PROCESS_IDLE_TIMEOUT`（exit 143），且 packaged
  `build-info` 返回同一 Build ID 与 `source_kind=packaged`。该结果只证明 T833 空转熔断已进入
  分发包，不构成真实 Voice Clone L3/L4 终态。
- T834 复验制品：Build `5.8.0-rc.5+sha256.482edf7d5bc5d67f`，内容 SHA-256
  `482edf7d5bc5d67f1abf30f2cca1ad844cdc1628a9aade65dd9eaf3cb243fe5e`，archive SHA-256
  `0e0359602efe6283a267c4d0aac37a56266b39dad082d143a0a4049250d81d66`；Codex/Claude archive
  smoke、双宿主本地安装和 Build Identity 预检通过。从归档解出的 adapter 以过期
  `native_status=running` observation 假宿主复验，实际返回 `HOST_PROCESS_IDLE_TIMEOUT`
  （exit 143），且 packaged `build-info` 返回同一 Build ID 与 `source_kind=packaged`。该结果
  只证明 stale Hook 有界熔断已进入分发包，不构成真实 Voice Clone L3/L4 终态。
- T835 复验制品：Build `5.8.0-rc.5+sha256.f4d2d3c779089e07`，内容 SHA-256
  `f4d2d3c779089e07a263914559c3d1e8db4bc11eff7637ac0bb75d6eb4725657`，archive SHA-256
  `e0a64521a7c90c8e8f70a593eefcad41cb804d19463805ce610ff3c065c83c72`；Codex/Claude archive
  smoke、双宿主本地安装和 Build Identity 预检通过。从归档解出的 adapter 以重复未知
  `unknown_heartbeat` 流假宿主复验，实际返回 `HOST_PROCESS_IDLE_TIMEOUT`（exit 143），且
  packaged `build-info` 返回同一 Build ID 与 `source_kind=packaged`。该结果只证明未知流量
  不得伪装进展已进入分发包，不构成真实 Voice Clone L3/L4 终态。
- T836 发现并修复另一处同类 liveness 漏洞：watchdog 原先只比对 observation 的
  `action_message_id + execution_generation`，没有验证当前 lease 的 `fencing_token`；同一
  Action/代际下的旧会话 Hook 或格式不完整 observation 理论上仍可能绕过 idle。修复后必须
  同时匹配 action、generation、fencing token，缺失或错误 token 一律不计作 running；新增合法
  observation 与错误 fencing 的黑盒回归，定向结果 `3 passed`；随后全量回归为
  `3192 passed, 1 skipped`、覆盖率 `90%`，静态门禁和双宿主 archive smoke 通过。新 Build
  `5.8.0-rc.5+sha256.ce576c1032bb5409` 已重新安装到 Codex/Claude，archive SHA-256 为
  `459f8ddc945ad8d9391a9576771f268b5e3e443bbaaafa71ed4284ae2764995e`；该结果仍不构成真实
  Voice Clone L3/L4 终态。
- 随后复核发现 lease 持久化仍存在同类边界：Python `load()` 会修复 legacy 空 fencing token，
  但 `save()` 原先可能把空 token 写给直接读取原始 JSON 的 watchdog。现已在 `to_dict()` 的
  唯一序列化边界规范化 token，并增加回归，避免 Core 与外层观察到不同身份事实。
- 再次压力回归发现，连续改写错误 fencing 的 observation 或原始 `native-results` 也能刷新
  通用 liveness。T837 已将两类目录从通用状态签名移除：observation 仅用于有界 native wait，
  原始 native result 仅作待解析证据；只有提交后的 Worker/聚合 outcome 才能延长 idle。定向
  liveness 回归 `6 passed`；随后全量回归为 `3195 passed, 1 skipped`、覆盖率 `90%`，静态
  门禁、双宿主 archive smoke 和双宿主安装通过。T837 Build `5.8.0-rc.5+sha256.80a4fe90c55dd6a2`
  已完成 Build Identity 预检；archive SHA-256 为
  `44ae7205644f4348ee0c79f646758acc71a01c837d8eae5c719a292a2cf496cc`。该结果仍不构成真实
  Voice Clone L3/L4 终态。
