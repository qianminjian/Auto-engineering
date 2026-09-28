# 2026-09-28 宿主 watchdog 未启动导致的超时保护失效

## 现象

宿主进程在一次真实 Loop 运行中退出或卡住后，外层保护没有按预期写入
idle/timeout/protocol marker，导致用户看到“Loop 运行起来就中断/下掉”。Core、
EventStore 和恢复状态并没有证明业务失败；失效的是宿主边界 watchdog。

## 根因

`scripts/ae-host-run` 曾在 heredoc 中直接执行系统 `python3 -`。本机系统 Python
受 Xcode license 状态影响，启动时可能直接被系统拒绝；该失败发生在独立 watchdog
进程中，宿主主流程没有收到结构化失败事实，于是 timeout/idle/protocol 保护等同于
不存在。该实现还复制了 EventStore 读取逻辑，违反 D78/D862 的单一运行时边界。

## 修复

1. 将 watchdog 提取为唯一生产模块 `auto_engineering.host.watchdog`。
2. 统一通过 `scripts/ae-run --run-module` 启动，使用与产品相同的锁定运行时，禁止
   回退系统 `python3`。
3. 在短 idle 窗口前预热/校验项目运行时；运行时无法启动时，宿主拒绝进入无保护运行。
4. watchdog 只调用 `SQLiteEventStore.semantic_signature()` 只读观察当前事实，不创建
   Action、不推进 Tick、不启动 Worker。
5. 对输出文件被截断、并发删除、EventStore 暂不可读、lease/observation 损坏等情况
   fail-closed，保持监控循环而不是让 watchdog 自身异常退出。

## EARS 验收

- While 宿主即将进入 Loop，when 项目运行时尚未预热或无法启动，the host shall
  refuse to run without a watchdog.
- While watchdog 观察当前 Action，when 输出文件或事实文件发生并发删除/截断，the
  watchdog shall continue with the last safe observation and shall not crash.
- While watchdog 判断语义进展，when it reads EventStore, it shall use only the
  canonical read-only API and shall not create Action/Tick/Worker facts.
- While bounded idle/runtime/protocol/poll 条件触发，the watchdog shall write the
  corresponding marker and terminate the host through the existing boundary.

## 验证

- watchdog 直接边界测试：26 passed。
- 宿主进程退出与恢复回归：46 passed。
- fresh 业务回归范围：2897 passed / 1 skipped。
- 严格覆盖率：18291 / 20323 statements，90.001476%。
- 真实 Codex/Claude 独立安装 L4、Voice Clone 业务验收和 Recovery Canary 产品证据
  仍是发布门禁，未被本次自动化回归替代。
