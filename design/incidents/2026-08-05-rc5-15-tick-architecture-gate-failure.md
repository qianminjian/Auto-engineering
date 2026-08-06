# Claude Code v5.8.0-rc.5 15-Tick 架构与 Gate 事故

> 事故日期：2026-08-05  
> 记录日期：2026-08-06  
> 状态：代码与自动门禁修复完成，等待双宿主真实产品复验  
> 严重度：P0（Gate fail-open、架构事实丢失、错误修复路由）  
> 关联任务：T387-T396

## 1. 摘要

Auto-Engineering v5.8.0-rc.5 在 Claude Code 中驱动外部 TypeScript 项目，完成
8 个 Gap 的批量决策与 6 个 Research 后，于 Developer/Critic 修复环节在 Tick 15
进入 `HARD_LIMIT`。停止表象是连续 3 次 `MAJOR`，实际故障链是：Architect 的研究结论
没有固化为跨 Stage 的架构事实，Developer Gate 的硬失败没有阻止进入 Critic，Critic
又只能看到过期设计和局部改动，最终把计划缺口错误路由成同一 Batch 内的点状返修。

本事故不涉及 Voice Clone 产品代码的归属或质量整改；外部项目只是真跑夹具，修复对象
全部位于 Auto-Engineering Loop Core、ProjectProfile、Gate 和 Host 证明协议。

## 2. 证据边界

- 外部原始报告：`docs/ae-loop-real-run-issues-2026-08-05.md`。
- 外部 thread：`472ae6f4-65e4-4101-9ad0-df73894e9f3c`。
- 引擎版本：`5.8.0-rc.5`；终态：`HARD_LIMIT`；停止 Tick：15。
- 原始 Result、EventStore、spawn proof 和项目源码仍保留在外部测试项目；本仓库只持久化
  脱敏事实、代码根因和关闭标准，不复制业务源码或完整运行日志。

## 3. 已确认运行轨迹

| Tick | 阶段 | 结果 |
|---:|---|---|
| 1-2 | gap_scan / gap_review | 识别 8 个 Gap，并在一个 Review Action 中完成全部决策 |
| 3-8 | research | 依次完成 gap-1 至 gap-6，未提前进入 Architect |
| 9 | architect | proof 首次缺 `action_message_id`；人工补齐后接受计划 |
| 10 | developer B1 | 单元测试通过；裸 `tsc` 无法执行但仍进入 Critic |
| 11-15 | critic / repair | 三次 MAJOR 均指向服务端 BFF 契约缺口，点状返修后触发硬上限 |

## 4. 已验证根因

### R1：Gate 结果未参与状态转移（P0）

`TickOrchestrator._tick_process_result()` 在 Developer Result 后执行 Gate，却无条件调用
`_after_tick()`；`DeveloperHandler` 不读取阻断 Gate。因此 `type_check=hard_fail` 仍可生成
Critic Action，违反 BEACON D15 的 fail-closed。

### R2：Architect 成果被当作临时 Stage 字段清除（P0）

`plan`、`batch_plan`、`file_list`、`contracts` 在 Architect 离场时由
`clear_stage_fields()` 清空。后续 ContractGate 得到空契约并返回 N/A，Critic 的
`design_scope` 为空。研究结论虽进入 Architect Prompt，却没有形成所有后续 Stage 共用的
已接受架构基线。

### R3：结构通过不等于设计义务覆盖（P0）

`dry_run_architect_plan()` 只验证 Batch/Task/依赖图可构建，不验证 Research 决策是否被
实现任务和测试任务覆盖。spawn proof 中的详细计划与最终 Architect Result 也没有摘要
绑定，Core 因而接受了“结构合法但缺少服务端完整链路”的计划。

### R4：Critic 把计划缺口错误路由成 Developer 局部返修（P0）

当前所有 `MAJOR` 默认回到 Developer。真跑 Finding 要求新增当前 B1 文件范围之外的
server route、上传、清理和 DTO，属于架构/计划覆盖缺口，应走既有 PLAN_REFINE 返回
Architect，而不是让 Developer 在过窄任务内猜测设计。

### R5：修复预算与停滞判定混用（P1）

配置的 `max_repair_cycles=6` 与 Critic 隐含的连续 MAJOR 上限并非同一计数；系统也不区分
“相同 Finding 无进展”与“Finding 已收敛但出现下一项”。因此第 3 次 MAJOR 被解释为
统一硬上限，而非有证据的停滞或全局预算耗尽。

### R6：ProjectProfile 被低优先级遗留命令污染（P1）

本地探测未从 `pnpm-lock.yaml`、`typescript` 依赖和 `tsconfig` 推导包管理器原生命令，
随后 Legacy Init Provider 补入裸 `tsc`。Profile 被标记为 confirmed，但命令在目标环境
不可执行。

### R7：spawn proof 同时承担挑战、回执和语义产物（P1）

Core 预生成 proof，Prompt 又要求 Worker 覆写同一文件。人工补元数据后，proof 内计划
仍可与最终 Result 不一致。它只能证明文件字段齐全，不能证明“哪个宿主派生动作产生了
哪个结果”。

## 5. 保留项与禁止的伪修复

必须保留 rc.5 已验证正确的“一个 Gap Review 覆盖全部未决 Gap、Research 按队列逐 Tick
消费”语义。禁止以下处理：

1. 回退为单 Gap 单 Tick 或把宿主交互游标写入 Core。
2. 单纯提高 Tick、连续 MAJOR 或修复次数上限。
3. 让 Critic/Developer 重新读取完整聊天历史弥补状态丢失。
4. 用 marker、文件名或 spawn 行为推断业务契约是否存在。
5. 通过放宽 Gate、把 hard-fail 改成 warning，制造流程继续。

## 6. 修复方向

| 方向 | 核心产物 | 关闭证据 |
|---|---|---|
| Gate 转移 | 阻断 Gate 成为确定性 Transition 输入 | hard-fail 后不产生 Critic Action |
| 架构事实 | 事件化 `ArchitectureBaseline` 与稳定摘要 | 跨进程/跨 Stage 可恢复且不被清场 |
| 义务覆盖 | Research/Gap → obligation → task/test 双向矩阵 | 缺 server/test 覆盖的计划在 Architect 阶段拒绝 |
| Critic 路由 | defect / plan_gap / capability 分类 | 越界 Finding 自动 PLAN_REFINE，不消耗局部修复预算 |
| 修复控制 | repair、stagnation、refine 独立计数 | 有进展不误停；无进展按稳定指纹停止 |
| Profile | 包管理器原生命令 + 可执行性置信度 | pnpm 项目不再回退裸 `tsc` |
| Host 证明 | immutable challenge + host receipt + result digest | receipt 不覆写 challenge，结果可因果绑定 |

## 7. EARS 关闭标准

- While 任一 required Gate 返回 hard-fail, when Developer Result 被处理, the system shall
  保持批次未完成且不得生成 Critic Action。
- While Architect Result 被接受, when 后续 Stage 或新进程恢复, the system shall 使用同一
  ArchitectureBaseline 摘要、契约和义务集合。
- While Research 决策要求跨边界能力, when Architect 计划缺少实现或契约测试任务, the
  system shall 在 Developer 前以稳定错误拒绝该计划。
- While Critic Finding 超出当前 Task 文件/契约边界, when Core 路由, the system shall
  生成 PLAN_REFINE 请求而非局部 repair。
- While 连续 Critic Finding 指纹不变且没有证据增量, when 达到停滞阈值, the system
  shall 以 `STAGNANT` 停止；有证据增量时不得误计为同一停滞。
- While pnpm TypeScript 项目无 typecheck script, when ProjectProfile 解析, the system
  shall 选择经验证的包管理器原生命令，不能用遗留裸命令覆盖当前事实。
- While 宿主完成一次原生派生, when 提交 Result, the receipt shall 绑定 challenge、Action、
  Worker 与 artifact/result digest，且不得覆写 challenge。

## 8. 发布边界

Phase 78 的代码、专项/全量测试、静态检查和 archive install 通过，只能说明候选制品具备
再次真跑资格。必须在 Claude Code 与 Codex 至少各完成一次包含 Research、Architect、
Gate hard-fail 注入、PLAN_REFINE 和恢复的黄金轨迹，才能关闭本事故并宣称可发布。

## 9. 自动验证记录（2026-08-06）

- Gate hard-fail 已参与转移；ArchitectureBaseline 支持 checkpoint 与事件重放，
  Gate、Developer、Critic 均读取已接受基线。
- Research obligation、结构化 Contract、越界 Finding PLAN_REFINE、repair/stagnation
  独立预算、pnpm 原生命令及批次累积审查上下文已落地。
- spawn identity 已拆为 immutable challenge、宿主 receipt 与 Core Result SHA-256
  acceptance receipt；旧 proof 仅只读兼容。
- 全量 2190 passed / 1 skipped；最近一次完整 coverage 90%；Ruff、mypy、Prompt/Agent
  规则同步与项目元数据检查通过。
- 尚未执行 Claude Code/Codex 真实产品重跑，因此事故状态保持“待复验”。
