# 2026-08-30 真跑事故：Supervisor/Research 结果闭环未完成

## 结论

本次不是 Voice Clone 业务问题，而是 Loop 的产品闭环仍存在两个系统性断点：

1. 外层宿主启动 `--supervise` 后，无法从机器事实确认 Supervisor 已经到达明确终态；
   Supervisor 异常退出时，旧的 `CONTINUE` lease 仍可能留在项目状态目录，形成“界面已经停止、Core 仍要求继续”的假活跃状态。
2. Research 的业务 payload、Worker outcome 和 Coordinator/Host 证据没有在同一个端到端测试中走完。局部测试验证了字段，却没有验证“Worker 完成 → 结果契约拒绝 → 同 Action 修复 → validate → submit → 下一 Action”的完整回路。

## 真跑事实

- 首个 `project_setup` Action 返回 `CONTINUE` 且 `yield_allowed=false`。
- 宿主曾手写旧 Result，触发 `ACTION_NOT_ACTIVE`，说明入口没有强制只消费当前 Action 给出的执行合同。
- `--supervise` 的后台心跳被当成了完成信号；Supervisor 退出后没有向外层交付唯一结构化终态。
- Gap Scan/Gap Review 正常到达 `WAIT_USER`，Research Worker 实际完成，但 Coordinator payload 被 Core 以 `HOST_EVIDENCE_INVALID` 拒绝。
- 拒绝后未完成同 Action 的自动修复和提交，最终 `active-lease.json` 仍是 `CONTINUE`。

## 根因分层

| 级别 | 根因 | 为什么自动测试漏掉 |
|---|---|---|
| P0 | Supervisor 只有内存循环结果，没有“必须是明确停态”的出口断言，也没有异常时关闭 lease 的统一 finally | Supervisor 单测使用 fake `advance`，没有把 CLI、lease、Stop Hook 和进程退出连起来 |
| P0 | Result contract 的校验链与 Research 实际 payload 没有纵向回放 | Assembler 测试直接调用函数，跳过真实 `--finalize-result → --validate-result → --tick` |
| P1 | Worker outcome、Coordinator payload、attestation 的角色边界由 Prompt 文字约束，缺少黑盒反向测试 | Fake Host 直接把 Worker payload 合成 Result，绕过了真实工作文件和宿主命令 |
| P1 | 失败恢复只验证了“返回 repair action”，没有验证 repair action 被再次执行并最终改变 Core projection | 测试在第一次 rejection stdout 处结束，未继续跑第二个 context |
| P1 | 环境入口存在两套解释（系统 `python3` 与锁定 `uv run`），失败时容易把运行时错误混成业务错误 | 质量门禁没有把入口运行时身份作为 L3 前置事实输出 |

## 统一修复方案

### A. Supervisor 终态不变量

- `ActionScopedProductDriver.run()` 返回前必须确认最终 Action 的处置不是 `EXECUTE_NEXT`；否则生成稳定的 `HOST_SUPERVISOR_PROTOCOL_ERROR`。
- `run_action_supervisor()` 无论是终态、可恢复等待还是异常，都必须通过统一清理逻辑关闭旧 `CONTINUE` lease；等待状态由下一次 Action 重新建立 lease。
- Stop Report 必须记录 Supervisor 退出类别、当前 Action 和最后一次宿主回执，不能只输出异常字符串。

### B. Action-specific Result Contract

- Assembler 的允许字段以 `result_contract.properties` 为机器事实源，`expected_format` 只作兼容回退和人类提示。
- Research 的正常字段、搜索不可用字段和失败诊断字段必须走同一 Finalizer；Worker outcome 不得直接提升为 Coordinator payload。
- rejection 是同一 Action 的 repair transaction：保留 Worker journal，只重新执行 Coordinator context，重新 finalize、validate、submit，不能重新 spawn。

### C. 端到端验收

必须有黑盒轨迹覆盖：

```text
init → project_setup → gap_scan → gap_review → research
→ malformed/valid Research payload → repair → validate → tick
→ next Action 或 WAIT_USER/TERMINAL
```

并注入：旧 Result、Research 字段漂移、Worker 无产出、Supervisor 异常退出、重复结果、
lease 残留和第二次恢复。测试必须检查 EventStore、Outcome Journal、active lease、Stop Report
和最终 Action，而不是只检查某个 Python 返回值。

## 关闭标准

- 同一 Action 的 Research rejection 可在第二个 fresh context 自动修复并完成提交。
- Supervisor 异常退出后不存在 `CONTINUE` 残留 lease，Stop Hook 不再错误阻断。
- 真实工作文件路径、Result contract、Outcome Journal 和 EventStore 的 Action/Thread/Tick 身份一致。
- 新增纵向轨迹在 Codex/Claude fake host 下等价通过；L3/L4 真实宿主仍需单独执行，不能以自动测试代替。
