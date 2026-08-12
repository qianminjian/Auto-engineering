# 三 Worker 证明拼接与恢复误诊事故

> 日期：2026-08-12｜来源：真实项目 Loop 报告｜范围：仅 Auto-Engineering Loop

## 现象

真实线程在 `plate_deep_audit` 的三 Worker Action 停止。历史日志曾出现
`RUNTIME_REVISION_INCOMPATIBLE`；当前候选运行时重新校验同一 Result 时返回
`WORKER_ATTESTATION_INVALID: ATTESTATION_INVALID`。报告同时发现 legacy checkpoint 数为零。

## 已核实事实

- `.ae-state/events.db` 中 EventStore projection 与 active ActionSnapshot 均完整。
- legacy `checkpoints.db` 为零符合事件事实源设计，不代表状态丢失，不应恢复双写。
- active Action 的三项 `spawn.invocations[]` 均含规范 Worker ID、Prompt hash 和唯一
  `.ae-state/spawn-proofs/` 回执路径。
- 宿主 Result 使用原生线程 UUID 替换规范 Worker ID，Codex 却声明 `fresh_context`，遗漏能力
  摘要与 sandbox 字段，并把回执写入另建的 `spawn-receipts/`；Action 指定回执仍为 pending。

## 根因

Core 已 fail-closed，但 Host 执行层仍根据自然语言手工重建证明字段。单元测试直接调用
`WorkerAttestation.completed()`，绕过真实宿主的 ID 和路径拼接，因此没有覆盖该边界。

## 修复决策

1. Host Adapter 从已验证 `SpawnPlan` 物化 `host_execution.workers[]` 证明模板。
2. 原生 Agent/thread UUID 只作为 `native_worker_handle`，不得替换规范 Worker ID。
3. Skill/Command 只消费模板；宿主只能补充真实模型、完成时间和输出证据。
4. 恢复错误明确 EventStore 事实源、thread、Action message ID 和协议差异向量。
5. L2 新增真实 EventStore 三 Worker ActionSnapshot→receipt/attestation→Tick 因果轨迹。

## 永久不变量

- Core 不因宿主拼接困难而放宽 attestation 或 receipt 门禁。
- EventStore 是新线程唯一状态事实源；legacy checkpoint 仅用于旧线程迁移。
- 自动测试必须穿过生产 Host Adapter，不能再由测试运行器自行生成“正确证明”后自证通过。
