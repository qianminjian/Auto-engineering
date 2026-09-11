# 2026-09-08 真实 Claude 宿主 session 补齐与 Architect idle 窗口

## 结论

- T816 发现真实 Claude 子进程没有暴露 `CLAUDE_CODE_SESSION_ID`；Core 在 Worker 已完成、结果准备提交时返回裸 `HOST_SESSION_ID_UNAVAILABLE`。
- T817 在 `scripts/ae-host-run` 为独立 Claude CLI 生成并继承边界 session；专项回归 50 项通过，全量 3154 passed/1 skipped，覆盖率 90%。
- 新 Build `5.8.0-rc.5+sha256.170094d5549bc8ed` 的新鲜 Claude 运行已从 `gap_scan` 推进到 Architect，session 不再造成提交错误；但 Architect 原生调用在 240 秒 idle 窗口内没有产生可观察的 Worker 交接，watchdog 以 `HOST_PROCESS_IDLE_TIMEOUT` 有界停止并恢复同一 Action。

## 证据

- T816 旧副本：Architect 结果与 Developer `34/34` outcome 已落盘，但最终 `--tick` 因宿主 session 缺失未闭环。
- T817 新副本：Build identity match；初始 `gap_scan` 正常，Architect Action 为 `action_tick=2`；两次 stop report 均保留同一 thread/Action，未发生第二个 Python loop。
- T817 旧副本还证明：lease/lock 文件活动不能作为业务进展；在没有 Worker outcome 的情况下，不能把宿主进程存活判定为有效推进。

## 根因与边界

这是 Host Adapter 与独立 Claude CLI 的 session 环境契约缺口，不是 Core 单 Tick 或 Python Coordinator 越权。修复后仍有一个独立问题：真实原生 Worker 的推理/启动耗时可能超过 240 秒，而 watchdog 没有阶段化心跳或“调用已进入原生 Worker”的可验证信号。

## 后续要求

1. 为原生调用增加 Host-owned、Action-scoped 的阶段心跳/启动确认；lease 更新时间不能充当心跳。
2. idle watchdog 按 `spawn → wait → record → finalize` 阶段采用可证明的超时策略；无有效进展时保留同 Action recovery，不重启已确认完成的 Worker。
3. L4 仍未关闭：必须以新鲜 Claude/Codex 真实产品证据完成 Developer、审查、修复、验证并到达等价 `TERMINAL`。
