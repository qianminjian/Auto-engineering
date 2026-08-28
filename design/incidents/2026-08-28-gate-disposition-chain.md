# 2026-08-28 真跑事故：Gate 被错误编译为 CONTINUE

## 事实

- 真实项目线程：`3105d983-1e2a-4178-9209-88c8e96a1d79`。
- 第 5 Tick 的 `research` Action 完成后，宿主继续执行第 6 Tick 的 `architect`。
- Architect 返回 `design_change_requests`，Core 正确生成设计变更 Gate。
- Gate 的 `gate.type` 为 `decision`，但 Action 的 `ExecutionControl.disposition` 为 `CONTINUE`。
- Supervisor 按合同尝试继续执行 Gate，最终返回 `ACTION_EXECUTION_ACTION_INVALID`。
- 事件流已证明业务状态和设计权威投影没有丢失；错误发生在 Action → Host 的机器处置映射边界。

## 根因

`control_for_action()` 只把 `state_reconciliation`、`stage_checkpoint`、`manual` 和 `user`
识别为人工 Gate，遗漏了设计变更使用的 `decision` 以及 Agent escalation 使用的
`agent_escalation`。因此 Gate 的用户交互语义与宿主机器处置不一致，Supervisor 误把必须
等待用户的 Action 当成可自动执行 Action。

## 不变量

1. 任何需要真实用户选择、授权或确认的 Gate 必须是 `WAIT_USER`。
2. `WAIT_USER` Gate 不得进入宿主 Action 编译、执行租约或 Worker 调用。
3. 用户结果必须绑定当前 Gate message identity；Core 接受后才生成下一 Action。
4. 自动可验证 Gate 才能是 `CONTINUE`；宿主不得从 stage、问题文本或 Gate 标题推断处置。

## 修复与验收

- 将 Gate 类型映射收敛到单一 `ExecutionControl` 判定源，覆盖 `decision`、
  `agent_escalation`、`state_reconciliation`、`stage_checkpoint`、`manual` 和 `user`。
- 增加跨类型回归：每种人工 Gate 都必须 `WAIT_USER`，设计变更轨迹必须在 Gate 处停止，
  不能创建宿主执行请求。
- 目标验证：目标测试、完整测试、覆盖率、Ruff、mypy、规则同步，以及新 Build 的
  Claude/Codex L3/L4 真实轨迹。

## 关联任务

- `T558`：全类型 Gate → ExecutionControl 统一映射。
- `P0-E2E`：单命令运行到 `TERMINAL`，真实宿主证据仍是发布门禁。
