# 2026-08-11 project_setup 自动续跑中断

## 事实

- 真跑从空项目发出 `project_setup_required`，宿主提交有效 `project_setup_completed`。
- Core 在构建下一 Action 时抛出 `UNMAPPED_PROJECTION_CHANNEL: current_stage`。
- 持久化投影仍停留在 `project_setup`；未进入 Architect，也不是正常 WAIT_USER。
- 外部证据源：测试项目 `docs/auto-engineering-auto-continuation-interruption-report.md`。

## 根因

`current_stage` 的唯一显式事件所有者是 `StageAdvanced`。`_complete_project_setup()`
直接把内存状态从 `project_setup` 改为 `gap_scan/architect`，却只排队
`ProjectSetupCompleted`。EventStore 路径的 `TickKernel.compile_commit()` 因无法将
这个无所有权变更降级到 fallback channel 而 fail-closed。

既有 project setup 测试未注入 EventStore，所以绕过了生产提交路径。相同直接写入模式
还存在于 Agent escalation 的回退/返回 setup 分支，属于阶段事件所有权缺口，而非单个
字段映射遗漏。

## 修复不变量

1. 所有非初始化 `current_stage` 变化必须伴随唯一 `StageAdvanced(from,to)`。
2. `ProjectSetupCompleted` 只记录 setup 事实，不拥有 stage projection。
3. project setup、escalation 和普通 StageHandler 必须共用相同 EventStore 提交约束。
4. 测试必须覆盖真实 EventStore、独立恢复、事件重放和下一 Action。
5. Kernel 拒绝无事件所有权的状态变化；不得把 `current_stage` 加入通用 fallback 掩盖缺陷。

## 关闭标准

- setup 完成后原子提交 `ProjectSetupCompleted + StageAdvanced + ActionIssued`。
- 重放与持久化投影均进入下一真实 Stage，重复 Result 返回同一 Action。
- escalation 的 stage 变化满足同一所有权规则。
- 定向、全量、Ruff、mypy、规则同步和双宿主 archive smoke 通过。

## 修复结论

- `project_setup → gap_scan/architect` 与 escalation 回退/返回 setup 均显式记录
  `StageAdvanced`。
- 中央 `_advance_stage()` 在 Handler 未提供匹配事实时补齐事件，已有匹配事实不重复。
- EventStore 候选编译纳入事务恢复边界；编译或写入失败都恢复最近持久化投影。
- 生产路径回归使用真实 SQLite EventStore，避免无 EventStore 单测再次制造盲区。
- 验证证据：227 项相关回归、2305 项全量（1 skipped）、90% coverage、Ruff、mypy、
  规则同步及 Claude Code/Codex archive smoke 均通过；真实产品安装仍为 `not_run`。
