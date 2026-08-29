# 2026-08-29 真跑事故：旧 Result、Supervisor 静默与 Gap Review 不可消费

## 结论

本次不是三个独立的小故障，而是宿主执行边界没有形成一条可观察、可恢复的闭环：
旧 Result 可以被手工提交；Supervisor 在模型调用早期没有进度事实；状态查询只给出
`stage/verdict`，没有给宿主当前 Action 的缺口和工作文件合同。

## 证据与根因

1. `ACTION_NOT_ACTIVE`：宿主提交了 `project_setup` 旧 Result。Core 按 Action 身份
   绑定拒绝是正确的 fail-closed 行为，但前台缺少当前 active Action 的可消费提示。
2. Supervisor 长时间无输出：原生进程只有 300 秒心跳，且没有 context 启动即时事件；
   真实模型等待期间用户无法区分“未启动、运行中、失联”。
3. `gap_review` 的 `verdict` 为空且 `current_gap` 不可见：简化 status 不是 Action envelope，
   不能指导用户提交单项决策。查询若调用 `build_action()` 还会写事件，可能制造
   `STATE_PROJECTION_MISMATCH`。
4. 报告只写 SemVer `5.8.0-rc.5`，没有内容寻址 Build Identity，无法确认实际运行制品。

## 修复

- `CancellableProcessRunner` 在等待前立即回调 `0.0`，默认心跳改为 30 秒。
- `--supervise` 启动后立即输出接管的 Action 与 stage。
- `dev-loop --status` 只读取 EventStore/Checkpoint 的 active Action，并投影
  `current_gap`、`expected_format` 和 `work_files`；不再调用会提交事件的 `build_action()`。
- 停止报告从 Action runtime revision 提取并记录 Build Identity。
- 新增旧 Result、重复 status、Supervisor 接管和 Build Identity 回归测试。

## 验收边界

本地纵向测试和隔离 archive smoke 通过后，仍需在真实 Codex/Claude 上使用同一 Build
执行 L3/L4，验证 Supervisor 心跳、Gap Review 单项决策和等价 `TERMINAL`。自动测试不能
替代真实宿主验收。
