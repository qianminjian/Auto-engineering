# 2026-09-09 T838/T839：状态文件改写伪造新运行 liveness

## 结论

T837 已经排除了 observation、native-result 和未提交 work file 的伪活跃，但复核
watchdog 白名单时发现仍保留 `.ae-state/checkpoints.db`，随后 T839 又发现
`.ae-state/events.db` 仍按文件 mtime 观察。新运行的唯一事实源是 EventStore；checkpoint
只允许通过显式迁移入口消费。任一数据库文件的 mtime/大小/WAL 变化都不代表当前 Action
有语义进展，却可能不断刷新 idle deadline。

## 复现

用合法 `CONTINUE` lease 启动宿主适配器，宿主不输出任何语义事件，只每 300ms 改写
`.ae-state/checkpoints.db`，持续 3.6 秒；`--max-idle-seconds 1` 下旧实现返回 0，
没有产生 `HOST_PROCESS_IDLE_TIMEOUT`。这会把“没有 Tick、没有 Worker outcome、没有
终态”的空转误报成宿主成功退出。

回归测试：

```text
tests/test_host_process_exit.py::test_host_run_wrapper_ignores_legacy_checkpoint_writes_for_liveness
```

修复前结果为失败：`returncode == 0`；修复后 checkpoint、EventStore touch、无关状态和
未提交候选文件等 liveness 边界回归通过，停止报告为 `HOST_PROCESS_IDLE_TIMEOUT`。

T839 的正向/反向回归：

```text
tests/test_host_process_exit.py::test_host_run_wrapper_ignores_event_store_touch_for_liveness
tests/test_host_process_exit.py::test_host_run_wrapper_treats_committed_event_store_fact_as_liveness
```

真实 `SQLiteEventStore.append_new()` 产生已提交事件时，观察窗口会延长；只 `touch`
同一个数据库文件时不会延长。

## 根因

watchdog 的“文件发生变化”曾把数据库 mtime 当作新运行的进度信号。这个判断混合了
两种生命周期：EventStore 驱动的新协议与 checkpoint 兼容迁移，也混合了 SQLite 的
持久化实现细节与协议事实。只要观察器没有读取语义签名，兼容层写入、旧工具写入、
数据库维护动作或 WAL checkpoint，都可能把真正失活的宿主伪装成活跃。

## 修复与不变量

- 从新运行 watchdog 的 `state_signature()` 白名单移除 `checkpoints.db`。
- EventStore 不再信任文件 mtime；只读查询事件/投影/Action、Result 回放和 effect receipt
  的语义签名。
- EventStore 已提交事实、已提交 Worker/聚合 outcomes 和合法终态事件仍可刷新观察窗口。
- checkpoint 仍可用于显式迁移，但不会成为普通 `init/tick/resume` 的 liveness 来源。
- observation、native-result、active lease、未提交 work file 和遗留 checkpoint 都不
  能单独证明业务进展。
- 触发 idle 后仍必须经过 process-exit bridge 和 Core status 回查；不得把退出文本当成功。

## 影响判断

这不是恢复第二套 Loop，也不是删除 checkpoint 迁移能力；是把“兼容输入”与“新运行
事实源”严格分层，并把 SQLite 文件层变化与协议层进展分开。它直接修复了“反复改文件
导致 watchdog 永不触发”的同类问题，降低无输出宿主无限占用资源的风险。

本修复只证明宿主空转熔断边界，不构成 Voice Clone L4、双宿主产品 evidence 或
`product_business_acceptance` 通过证据。

## T840 后续复核：重复终态流

T839 修复 EventStore 文件层误报后，继续审查 stdout 白名单发现，同一 Host attempt
如果持续输出不同或相同的 `result`/`turn.completed`，原实现每次都把它们当作新 liveness。
这仍然可能让一个已经产生终态、但没有提交 Core 事实的宿主绕过 idle。

T840 将每个 attempt 的终态流视为一次性信号：首个终态记录可刷新观察窗口，后续终态
记录只保留原始审计，不再刷新 idle。回归测试为
`test_host_run_wrapper_does_not_treat_repeated_terminal_stream_as_progress`；与 EventStore
touch、checkpoint、无关状态和未提交候选文件边界一起通过。

## T841/T842 后续架构收口：checkpoint 不再进入正常运行路径

继续沿“兼容输入不得成为运行事实”的原则反向审计后，发现问题不只在 watchdog：普通
`init/tick/validate/finalize/record/status` 仍会创建 checkpoint store，初始化还会用其
`active_project_thread` 做占用判断；原生启动守门在无 lease 时也会从 checkpoint 定位 Action。
这会让旧状态继续影响新 loop，形成设计上已经禁止的第二套状态源。

T841/T842 的修复是：正常 CLI 只从 EventStore 的最新 thread、projection、Action snapshot
恢复；Orchestrator 的 checkpoint 参数在生产 EventStore 路径为 `None`；无 lease 的重复
启动判断也只读取 EventStore。`--import-checkpoint` 和历史恢复 API 仍保留为显式迁移边界，
不会被普通 init/tick/status/resume 自动调用。

新增/更新回归覆盖：EventStore 与旧 checkpoint thread 冲突、checkpoint-only tick、无
checkpoint init、原生启动守门只依赖 EventStore；最终全量 `3202 passed/1 skipped`，覆盖率
`90%`。这完成的是框架状态源收口，不等于 Voice Clone L4 或双宿主业务终态验收。
