# 2026-09-08：真实 Claude 原生结果漏回写

## 现象

使用 Build `5.8.0-rc.5+sha256.c7d75261ff31cc6d` 运行独立 TypeScript Canary。
Loop 正常通过 Setup/Gap Scan 并进入 Architect；Claude 原生 Agent 返回了结构化结果，
Hook 已将结果写入当前 Action 绑定的 `native-results/...` 文件，但主 Agent 未调用
`record-worker-outcome`，随后直接提交 finalize。

## 根因

这是宿主交接顺序缺口，不是 Core 可以接受业务结果的问题：

1. native result 已存在，但私有 `worker-outcome` 尚未由唯一回写边界物化；
2. `finalize` 只看到私有 outcome 缺失，将其归类为 `HOST_WORKER_FAILED`；
3. 旧恢复投影只检查私有业务 artifact，不检查当前 Action 的 native result；
4. 因而一次“宿主漏回写”可能被错误送入 Worker 失败代际。

## 处置

T809 增加了 native result 恢复前置检查：当当前 Action 的内容寻址 native result
是合法 JSON 且共享 outcome 尚未准备好时，CLI 投影 `worker_attestation_pending`，
隐藏 `spawn`，要求按固定 `record-worker-outcome → finalize → validate → submit`
顺序继续；不消费失败预算、不创建新 Action、不重新 spawn。native envelope 的业务
解析与宿主句柄/模型/隔离事实仍只在 `record-worker-outcome` 边界完成。

T808 同时增强 Architect coverage loss 诊断：明确列出 source/candidate 的
batch/task 身份、缺失项和额外项，并要求同 Action 原样修复，不允许重建 Worker 计划。

## 验证

- 全量回归：`3144 passed, 1 skipped`。
- 覆盖率：`90%`。
- Ruff、mypy、compileall、`make check-gate`：通过。
- 真实 Claude Canary：已验证 native result 落盘与漏回写事实；本轮不计 L3/L4 通过，
  因为尚未完成完整业务闭环。
