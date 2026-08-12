# 2026-08-12 Worker 角色误判真跑事故

## 事实

- 外部真跑线程：`056bb3d3-56cf-4eec-9f4c-0d6dc34be838`。
- 阻断在 Architect；宿主提交 `HOST_CAPABILITY_UNAVAILABLE`，理由为 Worker 会话未暴露
  `collaboration.spawn_agent`。
- 事件库中的 Action Build Identity 为
  `5.8.0-rc.5+source.sha256.5fbd55c393876e80`，不是修复后的候选源码。
- 该 Action 的 `spawn` 只有 `count/effort/parallel`，没有 `contract_version`、
  `invocations[]`、Worker capability 和 prompt artifact 绑定。
- 测试项目没有 `ae.toml`；报告所称“已自动生成但只显示 PII”与磁盘事实不一致。

## 根因

旧 Action 只能让宿主读取兼容字段 `subagent_prompt`，无法证明 Coordinator 是否按严格
Invocation 创建隔离 Worker。Worker 又把 Coordinator 专属派生能力当成自身前置条件；
Coordinator 将该角色违规包装为普通能力不足，Core 的 WorkerOutcome 校验未处于这条真实
提交边界，因此循环停止。

## 不变量

1. Worker 必须 `may_spawn_workers=false`；不得通过给 Worker 开放递归派生来修复。
2. 当前 spawn Action 必须携带并只消费 `spawn.invocations[]`，绑定 Prompt hash、effort、
   isolation、receipt 和 attestation。
3. 容量不足保留 Action 并 WAIT_RESOURCE；角色/合同违规 fail-closed；未知 Worker 失败保留
   Action 身份和恢复指令，不推进 Tick。
4. Gap 批量授权只能是线程内结构化事件；不得解析自然语言备注扩大权限。
5. Action feature 状态必须来自当前项目已合并的 RuntimeConfig，而不是裸进程环境。

## 修复与验证

- T440-T441 已在 `a7c5201` 前建立严格 Invocation/Attestation；本次 T447-T448 补齐真实
  Result 边界的角色违规和未知 Worker 失败分类。
- T449 增加 `apply_to_remaining=recommendations` 与 Core-owned `auto_decision`。
- T450 将 RuntimeConfig 注入 ActionBuilder，保证 `ae.toml`、环境和 Action 状态一致。
- 真实 L3 必须使用新 Build Identity 和全新线程复验；旧线程不能作为修复后通过证据。
