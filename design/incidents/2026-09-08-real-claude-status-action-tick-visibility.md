# 2026-09-08 真实 Claude：Status 丢失 active Action tick

## 运行事实

- 新 Build 的真实 Claude 已稳定进入 `gap_review`，Action 本身的事件事实为 tick 2。
- `ae-run dev-loop --status --format json` 的顶层状态显示 tick 1，但旧的
  `active_action` 摘要没有展示 Action tick、correlation_id、causation_id 和 thread_id。
- Coordinator 按可见的顶层 tick 构造决策，Core 正确返回 `ACTION_NOT_ACTIVE`，并将旧
  Result 留入 stale-results；业务状态没有被破坏，但合法用户操作被错误信息阻断。

## 修复

`status_action_summary()` 现在投影 active Action 的完整机器身份：
`message_id/correlation_id/causation_id/thread_id/tick`。这只扩充只读状态，不改变
Core 的单 Tick 或 EventStore 事实模型；新增回归确保人工和宿主可以直接构造合法 Result。

## 验证

- `tests/test_cli_dev_loop_tick.py` 状态投影回归与 Host Runtime 回归：28 passed。
- 修复后需重新通过全量门禁并重建制品；当前真实产品副本不再续作旧 Action。
