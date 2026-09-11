# 2026-09-08 真实 Claude 原生 Agent 心跳与假活跃

## 结论

- T818 证明仅按文件修改时间判断 Host 活跃会被重复写入相同 `result.json` 伪装，无法可靠区分进展和重写。
- T819 增加 Claude `PreToolUse` 的 Action/Worker 绑定 `running` 观察，并让 `PostToolUse` 关闭同步 Agent 的旧观察；全量测试达到 `90%` 覆盖率。
- 最新真实 Claude 新副本使用同一 Build 自动恢复一次，完成 `gap_scan → gap_review`，未触发 idle timeout；随后因真实 `WAIT_USER` 停止，属于合法用户决策边界，不是崩溃。
- T820 发现 Claude 兼容别名 `Task` 未进入 Hook matcher；T821 补齐 `Agent/Task` 两条入口。最终 Build `5.8.0-rc.5+sha256.be2686fced1729c2` 的新副本已完成 `gap_scan → gap_review` 并进入 `WAIT_USER`。
- T822 的真实恢复窗口又证明 `active-lease.json` 不能作为 liveness：Architect 第 1 代结果完成后，恢复代只产生 `HOST_WORKER_OUTPUT_MISSING`，但 lease 重写持续刷新 watchdog 的状态签名，造成恢复进程迟迟不收口。修复后 lease 只保留身份/fencing/续驱动授权语义，不再参与业务进度判断。

## 根因

原设计规定主 Agent 是唯一 Coordinator、Python 只做单 Tick 和确定性边界，但宿主进程层仍把“stdout 沉默”“lease 被刷新”“文件 mtime 改变”近似成“有进展”。同步 Claude 原生 Agent 在内部推理期间通常没有 stdout，导致误杀；而结果文件被同内容反复覆盖、lease 被身份刷新又会导致反方向的假活跃。

## 修复

1. watchdog 只观察 Action-scoped 白名单；JSON 事实按规范化内容 hash 判断，重复相同内容不刷新 liveness。
2. Claude Hook 在原生 Agent 启动前写入当前 Action/generation 的 `running` 观察；异步 TaskOutput 继续以同一 handle 更新；Agent 返回后立即写非 running 状态，防止旧观察永久放行 idle。
3. 总运行时、idle、协议拒绝、Coordinator poll 和 auto-resume 均保持显式上限；任何恢复复用同一 Action，不创建第二个 Python Coordinator。
4. T822 将 `active-lease.json` 从 watchdog `state_signature` 白名单移除，并新增回归：持续改写合法 lease、没有任何业务事实时仍必须触发 `HOST_PROCESS_IDLE_TIMEOUT`。
5. T823 将 Core Result rejection 与 Host assembly rejection 收口到同一有界修复事务：第三次拒绝后
   `OutcomeJournal` 不再接受新的 candidate，公开 Finalizer 返回结构化
   `HOST_RESULT_REPAIR_EXHAUSTED`；同时为 `OBLIGATION_UPDATE_REQUIRED` 增加明确的
   `plan_patch.obligation_updates` 修复指引，避免模型把已有义务误当新增义务重写。

## 证据与未完成项

- 自动化：T822 定向回归 `4 passed`；修改后全量回归 `3160 passed, 1 skipped`、90%，Host 进程边界回归、Claude Hook 回归、Ruff、mypy、compileall、check-gate 均通过。
- 真实：最终 Build `5.8.0-rc.5+sha256.be2686fced1729c2` 的新副本进入 `WAIT_USER`；授权恢复推进到 Architect/Critic/Architect，首代 Architect 与 Developer/ Critic outcome 均有有效落盘，恢复代出现 `HOST_WORKER_OUTPUT_MISSING`，后因 `HOST_PROCESS_TIMEOUT` 受控停止，无残留子进程。尚未形成 Voice Clone 业务 `TERMINAL`、双宿主 L4 和 product evidence，因此不能关闭 A008。
- T823 自动化：Core rejection、Finalizer exhausted error 与 obligation repair guidance 回归已通过；真实产品 L4 仍待在最新 Build 上重新执行，不能把这些自动化结果表述为业务终态。
