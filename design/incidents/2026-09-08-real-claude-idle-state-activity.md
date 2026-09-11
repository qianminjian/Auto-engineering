# 2026-09-08 真实 Claude：stdout 静默但 Action 状态仍在推进

## 结论

T812 修复后的真实 Claude 运行已通过 `gap_scan → architect → developer → critic`，但外层
`ae-host-run` 只观察宿主 stdout 文件大小。真实 Claude 在原生 Worker 和 Coordinator 处理期间
可以长时间不增长 stdout；同一时间 `.ae-state` 已产生 native-result、Worker outcome、EventStore
和当前 Action 变化。旧 watchdog 因此把仍在推进的运行判为 `HOST_PROCESS_IDLE_TIMEOUT`，达到有界
恢复次数后让出 active Action。

## 真实证据

- 最终 Build `5.8.0-rc.5+sha256.19188e7207603e4b` 的隔离运行实际推进到 `critic`，并产生了
  `src/index.ts`、`src/types/index.ts`、`src/styles/nature.css`、Developer/Critic native-result
  和同 Action outcome 文件。
- 运行期间 attempt stdout 为空或仅包含宿主 `Execution error`，但 `.ae-state/host-runtime`
  的 native-result、outcome、work 文件持续发生变化。
- 旧 watchdog 只以 attempt stdout 偏移量刷新 idle 时间，最终生成 `HOST_PROCESS_IDLE_TIMEOUT`。

## 根因

stdout 是宿主可见性信号，不是 Core/Host 活动事实。把单一输出流当作 liveness 会把“原生 Worker
静默执行、异步写入绑定证据、宿主尚未输出最终结果”误判为失活；这违反了等待与失活分离的设计
原则。

## 修复

- watchdog 同时观察 stdout 和项目 `.ae-state` 下的 Action-scoped 状态文件活动。
- 排除依赖虚拟环境目录，避免把安装缓存当作业务进展。
- 只有两类信号都在边界内无活动时才触发 idle；触发后仍先回查 Core，继续保持有界恢复。
- 增加真实回归：静默宿主在 `native-results` 目录写入状态文件时不得触发 idle timeout。

## 后续加固

初版 T813 若遍历整个 `.ae-state`，会把 `offload`、prompt 或历史缓存写入误当作
活跃信号，反过来形成“无关任务让 watchdog 永不 idle”的新漏洞。现已改为白名单，
只观察 EventStore/checkpoint、spawn 事实、active lease、native-results、
worker-outcomes、outcomes 和当前 Action work 目录；无关状态变化不再刷新 liveness。

## 验证

- `tests/test_host_process_exit.py`：25 passed，包含 Action 状态活动与无关状态活动的
  正反向回归。
- 全量：`3149 passed, 1 skipped`，覆盖率 `90%`。
- Ruff、mypy、compileall、`make check-gate` 和 `git diff --check` 通过。
