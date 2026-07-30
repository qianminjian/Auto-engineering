# Claude Code v5.8.0-rc.1 部分真跑事故

> 事故日期：2026-07-30
> 记录日期：2026-07-30
> 状态：代码修复完成，等待真实产品复验
> 严重度：P0（确定性状态、Gate 可信度与发布验收失效）
> 关联任务：T326-T336

## 1. 摘要

Auto-Engineering v5.8.0-rc.1 在 Claude Code 中驱动 TypeScript/Vitest
`voice_clone_for_auto_CC_Design` 项目，推进至主线程 Tick 12、Developer B3 前停止。
运行完成 B1/B2，但需要多次人工修正 Result，并直接修改 SQLite checkpoint 才能越过
critic Gate。该运行不得作为 T319 或 v5.8 发布通过证据。

## 2. 证据边界

- 外部原始报告：目标项目
  `_scratch/dev-loop-execution-report-20260730.md`。
- 原始状态：目标项目 `.ae-state/checkpoints.db`、metrics、audit、prompt-log 和
  spawn-proofs；本项目不复制原文或可能含敏感信息的日志。
- 本报告只记录脱敏统计、代码根因和任务映射。
- 外部 thread：`6b04f5eb-c28b-46eb-91e9-c9ae17de3499`。

## 3. 已确认事实

| 指标 | 观察值 |
|---|---:|
| 业务进度 | B1/B2 完成，B3 Action active；2/12 batches |
| Protocol Action | 22 |
| 已接受 Result | 11 |
| 已废弃无 Result Action | 10 |
| active Action | 1 |
| stray active thread | 3 |
| Action JSON 总量 | 160,443 bytes |
| 废弃 Action JSON | 65,658 bytes（约 41%） |
| 主线程 checkpoint | 14 |
| checkpoint state JSON | 975,687 bytes |
| checkpoint history JSON | 115,425 bytes |
| 单 checkpoint 最大 state | 94,479 bytes |
| rendered Prompt Markdown | 约 119,674 bytes |
| session handoff | 0 |
| Usage input/output/cache | 全部 0 或 unknown |

## 4. P0 根因

### 4.1 Developer Snapshot 只存在于进程内

`TickOrchestrator._dev_snapshot` 在 Developer 完成后保存 `files_changed`、commit 和
测试结果，critic Gate 依赖它恢复文件快照。真实 Tick 每次启动新 Python 进程，
checkpoint 未保存该字段，导致 `GATE_SNAPSHOT_EMPTY`。运行者直接修改
`checkpoints.state_json.files_changed` 后才继续，破坏合法审计链。

### 4.2 项目允许多个非终态 thread

重复 `--init` 创建三个额外 thread，每个保留一个 active Action。主 thread 的 Result
与其他 active Action 竞争后产生 `ACTION_NOT_ACTIVE`，运行者删除 stray checkpoint。
当前唯一性只约束 thread 内 Action，没有约束项目级非终态 thread。

### 4.3 Contract Gate 把未实现检查表示为通过

真实 checkpoint 记录 `passed=true`，message 却是
`skip: multi-agent mode detected, cross-agent contract 检查待实现`。未实现或证据缺失
不得计为 pass；这违反 fail-closed 与五层验证可信度。

### 4.4 P1 Finding 未形成修复事实

B2 Critic 返回 APPROVE 与两个 P1 测试缺口。当前 Prompt 允许 0 P0 且不超过 2 P1
时 APPROVE，但 Core 没有持久化 open finding 或创建修复任务，后续直接推进 B3。

## 5. P1 根因

1. 真实验收只启用 metrics、audit、PII，未启用 `AE_TOKEN_TRACKING`；因此
   `session_input_units=0`、`tick_token_usage=null`，Usage Ledger 未创建。
2. Agent 手写 Result，中文引号、额外字段和非法枚举在 Core 才被发现，造成同 Stage
   重发 Action。
3. batch component 与 Markdown heading 使用展示文本精确匹配，反引号差异产生
   `孤儿 batch`。
4. checkpoint 重复保存完整 batch plan 与 progress tree，状态随 Tick 线性膨胀。
5. 两个 batch 调用 8 次 Agent；3 个 xhigh deep-audit Worker 在缺少 Usage 的情况下
   无法证明收益。

## 6. 正向证据

- TypeScript 项目使用 Vitest、ESLint、tsc 和 Vite build，runner 路由正确。
- Developer Gate 的非空 selected files 绑定同一 SHA-256。
- 单个 rendered Prompt 约 3–10 KiB，当前 Action 最大约 15 KiB。
- B1/B2 未出现完成批次回退。
- 非法 envelope、枚举和 Result 字段 fail-closed。
- spawn proof 与多 Worker receipt 确实生成。

## 7. 任务映射

| 问题 | 任务 | 关闭证据 |
|---|---|---|
| 跨进程快照丢失 | T327 | 每 Tick 新进程仍可从已接受 Result 重建 Gate snapshot |
| 多 active thread | T328 | 重复 init 不新增 thread，并返回唯一 resume 指引 |
| skip 假通过 | T329 | 未实现/不可执行/缺证据为 fail；N/A 有稳定原因 |
| P1 丢失 | T330 | open finding 持久化、绑定修复并在最终 Gate 清零 |
| Usage 未采集 | T331 | Claude/Codex 验收报告含逐 session/tick/stage/worker usage |
| Result 格式重试 | T332 | Builder/schema preflight 在提交前捕获错误 |
| 标题精确耦合 | T333 | 展示格式变化不改变稳定 section identity |
| checkpoint 膨胀 | T334 | 大对象去重且重放结果等价 |
| Agent 成本偏高 | T335 | revision 去重、预算事件与 requested/actual model 报告 |
| 完整收口 | T336 | 多进程、故障注入、全量与双宿主 archive 验收通过 |

## 8. 关闭标准

- T327-T335 全部完成且无未关闭 P0/P1。
- 不允许人工 SQL、删除 checkpoint 或过滤 Agent 输出后继续。
- 主线程从 init 到 done 至少跨两个 ExecutionSession。
- Usage Ledger 能解释宿主报告 usage；unknown 必须显式而非写 0。
- 所有 Gate 的 pass/fail/not_applicable 语义可审计。
- 多进程黄金轨迹证明 snapshot、active Action 与 progress 可恢复。
- checkpoint 大对象不随 Tick 全量重复复制。
- 新候选包通过 Claude/Codex archive，再从干净项目重跑 T319。

## 9. 修复验证（2026-07-30）

- T327-T335 已实现；全量测试、Ruff、mypy、规则同步和双宿主 archive smoke 通过。
- 自动 archive smoke 不等于真实宿主验收；T336 保持进行中。
- 下一次 Claude Code 真跑禁止人工 SQL，并须先运行
  `ae doctor --acceptance-profile`，Result 提交前运行 `--validate-result`。
