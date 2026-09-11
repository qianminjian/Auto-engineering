# 2026-09-08 真实 Claude：宿主 session 缺失冒出 Python traceback

## 运行事实

- Gap 决策的 thread、Action 和 tick 均正确时，Core 已接受 Result 并生成下一 Action。
- 公开 `ae-run --tick` 在输出下一宿主 Action 时发现缺少 `CLAUDE_CODE_SESSION_ID`，
  `HostRunLeaseError(HOST_SESSION_ID_UNAVAILABLE)` 直接冒出 traceback。
- 该异常发生在 Core 提交之后，状态事实未损坏，但宿主拿不到可恢复的结构化响应。

## 修复

CLI 增加宿主边界安全投影：保留内部严格异常语义，同时把租约/会话错误转为稳定的
`action=error`、错误码、thread、tick 和恢复建议；不得伪造 session，也不得回滚已提交
的 Core Result。

## 验证

- Host/CLI/状态投影定向回归：30 passed。
- 修复后的全量质量门禁和新 Build 仍需完成。
