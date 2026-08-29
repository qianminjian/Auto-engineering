# 2026-08-28 真跑事故：Outcome Journal 冲突导致 Action 停滞

## 事实

- 真跑停在 Architect tick 7/8，Core 仍保留 active Action。
- 同一 Architect Action `7f2f8ae4-3f73-4e91-9a03-eb76f468b89f` 收到多个不同宿主 context 的 completed receipt。
- Outcome journal 记录 `HOST_EVIDENCE_INVALID: OUTCOME_JOURNAL_CONFLICT`，无法形成唯一可信的 Action Result。
- Supervisor 退出时没有投影稳定的 ERROR/WAIT_RESOURCE，也没有生成可处理的 Stop Report；前台表现为“没有确认但停止”。

## 根因

Result 被 Assembler/Core 拒绝后，恢复投影把“可修复的 Coordinator payload”和“不可变的 Worker outcome”混为一体。旧路径只对
`prepared/accepted/committed` journal 做恢复，`rejected` journal 未物化权威 outcomes；修复宿主包因此可能重新暴露 Worker，
不同 context 重新提交后触发冲突。冲突又未在 Supervisor 的当前 Action 边界 fail-closed，留下 active checkpoint 与已退出进程的不一致状态。

## 设计不变量

1. Core 拒绝一个 Result 不会撤销已经完成并写入 journal 的 Worker 事实。
2. `rejected` 或 `assembly_rejected` journal 恢复时，必须按 Action identity 和 fingerprint 原子物化权威 outcomes。
3. Result repair 是 Coordinator-only 操作；修复包不得再次暴露 Worker 启动合同，也不得重新 spawn 已完成 Worker。
4. Finalizer 遇到已有拒绝 journal 时只能复用 journal outcomes，不能接受宿主替换的 Worker handle、attestation 或完成时间。
5. `OUTCOME_JOURNAL_CONFLICT` 是当前 Action 的致命协调错误：Supervisor 必须立即投影稳定 ERROR/Stop Report，禁止生成下一 context 或静默退出。

## 修复映射

| 层 | 修复 | 验收 |
|---|---|---|
| Execution Assembler | rejected journal 恢复 outcomes；身份/fingerprint 校验；拒绝替换 Worker 事实 | 同 Action 的拒绝→修复只保留首次 outcomes |
| Host Adapter/Backend | 生成 `result_repair_worker_reuse` recovery 包，`spawn_permitted=false` | 修复上下文只包含 Coordinator 操作和 outcomes 引用 |
| Supervisor/CLI | 冲突立即 fail-closed；准备失败也投影 ERROR/Stop Report | 不再出现无确认、无错误的前台停止 |
| Regression tests | 覆盖 journal 恢复、替换事实、无重启、冲突终止和 CLI repair 投影 | 相关 Host/ExecutionControl 套件全部通过 |

## 关闭标准

- 相关回归、全量测试、Ruff、mypy、设计/规则同步和双宿主制品门禁均有新鲜证据。
- 真实 Claude/Codex L3/L4 需使用包含本修复的新 Build 重跑；archive smoke 不得替代真实产品证据。
