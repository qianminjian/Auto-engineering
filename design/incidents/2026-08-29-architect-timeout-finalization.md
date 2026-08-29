# 2026-08-29 Architect Worker 超时终结事故

## 结论

本次真跑停在 `architect`，不是设计文档或业务代码失败，而是宿主 Worker 超时后的失败终结顺序错误：Assembler 先校验 Architect 的成功业务字段，再判断 Worker 已失败。空的 Coordinator payload 因此被当成普通 Result repair，要求补齐 `plan`、`file_list`、`batch_plan`，同时又禁止重新启动 Worker，最终没有稳定生成 `result.json`。

## 证据

- `architect-0` 原生状态为 `timed_out`，摘要为 `architect worker exceeded the allowed wait window`。
- 首次手工写入的 `outcomes.json` 形状与宿主合同不一致，暴露出提示词虽提到 outcomes、但没有在所有入口重复唯一文件格式的问题。
- 修复分支收到 `COORDINATOR_RESULT_INVALID`（缺少 `plan`、`file_list`、`batch_plan`），这说明失败事实被错误送入成功业务契约。
- 后续 `--tick` 读取不到工作目录中的 `result.json`，是前述组装失败的派生结果；不是新的 Core 状态机故障。

## 设计对照

D37 要求：Worker 失败先写入 `worker_failed` 尝试，Core 返回 `WAIT_RESOURCE`，只有成功 journal 才禁止重复 spawn。失败尝试不应满足任何 Architect/Developer 成功字段，也不应进入 Coordinator-only repair。

## 修复

1. `HostExecutionAssembler.finalize()` 对含 `spawn` 的 Action 先识别非 `completed` outcome，直接调用 `_finalize_worker_failure()`；业务 payload 只在全量 Worker 成功后校验。
2. 失败终结仍原子写入 outcome journal 与 `result.json`，Result 只含 active Action 身份、`HOST_WORKER_TIMEOUT`/`HOST_WORKER_FAILED` 和有界重试次数。
3. 宿主 launcher 与原生 Worker 启动提示词明确唯一格式：`{"outcomes":[{...}]}`；禁止顶层数组、单个对象和字符串化 JSON。
4. 回归测试覆盖“Architect 成功契约 + 空 Coordinator + timed_out outcome”，并断言可解析 Result 已写入。

## 验收

- 超时：`HOST_WORKER_TIMEOUT` → Core `WAIT_RESOURCE`，active Action 不推进。
- 第二次超时：`HOST_WORKER_TIMEOUT_EXHAUSTED`，不无限重启、不伪造计划。
- 成功 Worker 的业务字段缺失：仍进入正常 Result repair，不能被失败快捷路径吞掉。
- 真实宿主 L3/L4 仍需使用包含本修复的新 Build 复验；自动测试和 archive smoke 不能替代真实产品证据。
