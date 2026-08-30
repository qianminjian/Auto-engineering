# 2026-08-30 真跑事故：Worker 完成但无结构化产出

## 事实

- 外部项目完成 `project_setup`、`gap_scan`、`gap_review`，进入 `architect`。
- 宿主两次创建并显示 Architect Worker 完成，但没有结构化结果、摘要或 artifact。
- Coordinator 生成空/不可读取的交接文件后调用 Finalizer，最终返回
  `HOST_OUTCOME_INPUT_INVALID`，没有生成可提交的 `result.json`。
- 因而没有进入 Developer、Critic 或 Verification；该事故不涉及 Voice Clone 业务代码。

## 根因

表面故障是 CLI 将缺失交接文件报成 `HOST_OUTCOME_INPUT_INVALID`，但这不是唯一根因。真正
的问题是 Worker 生命周期没有唯一机器合同：

1. Coordinator 同时承担启动 Worker、接收原生返回、创建共享 outcomes 和业务汇总，任何
   一步没有被自然语言执行就会留下“进程完成但无结果”的半状态。
2. invocation 没有逐 Worker 的产出地址，Host 无法判断哪个 Worker 缺失，也无法在上下文
   结束后从可验证 artifact 恢复。
3. CLI、后端和 Assembler 各自解析工作文件，错误分类不一致；因此测试覆盖了函数，却没有
   覆盖真实宿主的“Worker 完成→产出采集→Finalizer”纵向边界。

`HOST_OUTCOME_INPUT_INVALID` 只是上述协议缺口最后暴露出来的错误表现。单独增加一个 CLI
分支只能止血，不能解决跨宿主重复发生的问题。

## 设计不变量

1. Worker 无产出永远不能成为 Architect/Developer 成功结果。
2. spawn Action 的交接文件缺失、为空或不可解析，必须落成 `HOST_WORKER_FAILED`，而不是
   CLI 参数错误。
3. 失败 outcome 不得伪造业务 payload、计划或成功 attestation；句柄不可得必须使用可识别
   的 `unreported:<action>:<worker>` 哨兵，模型使用 `unreported`。
4. 失败 Result 必须写入 outcome journal，并由 Core 按同类失败预算返回 `WAIT_RESOURCE`；
   相同输入重试必须幂等。
5. inline Action 仍对缺失/畸形 Coordinator payload fail-closed，不能扩大恢复语义。

## 统一修复设计与实施

- 严格 `WorkerInvocationSpec` 增加可选的 Action-scoped `outcome_path`；新 Action 必须由
  Worker 先原子写入自己的私有产出，旧 Action 只保留共享 outcomes 兼容读取。
- Host Adapter 将 `outcome_path` 和最小启动合同一起物化，Worker 不得写共享状态；
  Coordinator 只合并私有产出和写业务 payload。
- `HostExecutionAssembler.collect_worker_outcomes_from_artifacts` 成为唯一采集入口，逐项
  校验路径、worker_id、结构和完整 invocation 集合，成功后才写共享 outcomes。
- `run_tick_finalize` 只在共享 outcomes 缺失/为空时调用 Collector；采集失败统一转为
  带 Worker ID 的 `HOST_WORKER_OUTPUT_MISSING/INVALID`，再复用既有失败预算和 journal，
  inline Action 仍保持 fail-closed。
- 回归覆盖私有 artifact 成功采集、缺失 artifact、空/畸形共享文件、重复 finalize 和
  旧 Action 兼容；定向宿主/CLI/Assembler 测试 `118 passed`，全量测试 `2774 passed, 1 skipped`，
  覆盖率保持 90%，Ruff 和 mypy 通过。新宿主 L3/L4 仍需在当前候选 Build 上刷新，不能用本次
  自动回归结果冒充真实闭环。

## 关闭标准

- L1/L2：缺文件、空文件、畸形 JSON、重复调用和进程恢复均形成同一失败语义并通过全量门禁。
- L3：Codex、Claude 新 Build 的真实 spawn Action 均能在 Worker 无输出时自动进入有界重试，
  不要求用户手工拼 JSON。
- L4：完整黄金项目不因“Worker 显示完成但无产出”停在 `HOST_OUTCOME_INPUT_INVALID`；
  该项与双宿主真实终态一并验证，未完成前不得宣称发布。

## 后续重点（非点状修复）

- L2 增加多 Worker 部分成功、晚到 artifact、重复 artifact、Coordinator 崩溃和重试后的
  纵向轨迹，确认 Collector/Journal/Reducer 对同一 Action 只产生一个事实版本。
- L3 在 Claude Code 与 Codex 分别验证真实原生 Worker 能写私有 artifact、宿主能回收句柄，
  并记录 prompt 可见性、隔离证据和 usage；若宿主 API 不支持该能力，必须在 spawn 前
  fail-closed，而不是回退到手工 JSON。
- L4 验证 Architect→Developer→Critic→Verification 的完整业务终态和成本边界；在此之前
  不发布新的 RC。

## 独立质量债务

本次修复未扩大为文件拆分。`make check-gate` 的 line-count ratchet 仍被 HEAD 中既有的
多个超限模块阻断（该基线早于本次改动，属于 T570 重构债务）；这不是本事故的功能验收
结果，也不能用调高阈值掩盖。发布前仍需按 T570 单独完成拆分和门禁收口。
