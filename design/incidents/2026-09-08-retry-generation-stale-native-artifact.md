# 2026-09-08：失败 Journal 被非法原生结果占用重试代际

## 现象

在最终 Build 的真实 Claude Canary 中，Loop 已通过 Setup、Architect、Developer、
Critic、Component Verifier 和 Deep Audit。进入下一个 Developer Action 后，宿主先
因错误 native handle 写入了 `HOST_WORKER_OUTPUT_INVALID` 失败事实；随后同一 Action
又得到有效的 completed Worker outcome，但 `record-worker-outcome` 返回
`OUTCOMES_CONFLICT:developer-0`，Core 进入 `WAIT_RESOURCE` 并要求重试 Developer。

## 根因

重试代际绑定函数把“旧 native-result 路径存在”当成“旧代事实可恢复”。失败 Journal
存在时，旧文件可能正是上一次非法或半成品回包；它不能阻止 generation 递增。原实现
因此复用了 generation 1，而失败 Journal 和新的有效回写都绑定同一 Worker 身份，最终
共享 outcomes 无法确定性合并。

## 处置

T810 调整代际判定：

1. 没有失败 Journal 时，保持已有跨会话事实的原代恢复兼容；
2. 有失败 Journal 时，只有通过唯一 `_native_business_artifact` 解析的 native result
   才可以复用原代；
3. 非法/半成品 native 文件不再占用重试代际，新的执行绑定到更高 generation；
4. 仍不允许用新 generation 覆盖同代已确认事实，也不允许 Coordinator 手工改写
   Worker outcome。

## 验证

- 新增回归：失败 Journal + 非法旧 native artifact 必须得到 generation 2。
- 定向测试：`5 passed`、Assembler `23 passed`、Ruff 通过。
- 待完成：重建并安装包含 T810 的候选 Build，再重新执行真实双宿主产品验收。
