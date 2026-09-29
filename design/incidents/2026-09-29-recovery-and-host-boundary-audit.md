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
- 新鲜验证：串行全量 `3043 passed, 1 skipped`；严格覆盖率 `91%`；相关源文件 mypy、Ruff、shell 语法检查和 `make check-gate` 通过。
- 新 Build `5.8.0-rc.5+sha256.c37b122ba3d9d43b` 已按官方流程卸载并重装 Codex、Claude Code；两端入口 `build-info --expect-build-id` 均通过，且均为 `source_kind=packaged`。
- 额外回归：native wait timeout 无终止观察进入 owner lost；匹配 terminal observation 才进入 timeout；终态 `--status` 不再要求 active Action；release symlink 在构建期拒绝。
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

本轮修复解决的是 Loop/Core/Host 交接的确定性与 fail-closed 问题，不等于真实产品 L4 已通过。仍需单独完成：

- 同一新 Build 在 Codex 与 Claude Code 的独立安装、doctor、入口自检和真实宿主连续运行。
- Recovery Canary：中断、owner uncertain、重复回写、迟到结果和跨进程 resume 的真实证据。
- Voice Clone 真实业务链路和最终 TERMINAL/WAIT_USER 结果。
- 新鲜覆盖率基线和 `make check-gate` 已通过；仍需以下产品级门禁。

这些门禁不能用单元测试、archive smoke 或一次成功 Canary 替代；在全部证据齐全前，不能把项目描述为 L4 完成。
